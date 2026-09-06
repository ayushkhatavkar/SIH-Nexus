"""
Real ingestion: parses an uploaded file, validates + normalizes it, appends
it to the durable CSV store, and returns a summary the UI can show plainly
(counts + warnings), never a raw stack trace.
"""
import csv
import io

from normalize import normalize_case_id, normalize_phone, normalize_id
from data_store import FIELDS

REQUIRED = {
    "fir": ["case_id"],
    "cdr": ["cdr_id", "caller_phone", "receiver_phone"],
    "telecom": ["subscriber_id", "phone_number"],
    "bank": ["transaction_id", "sender_account", "receiver_account"],
    "social": ["relationship_id", "source_person_id", "target_person_id"],
    "vehicles": ["vehicle_id", "registration_number"],
}

DOCTYPE_MAP = {"FIR": "fir", "CDR": "cdr", "BANK": "bank", "TELECOM": "telecom",
               "SOCIAL": "social", "VEHICLE": "vehicles"}


def _parse_fir_text(text, fallback_case_id=None):
    """Very small key:value parser for a single FIR submitted as .txt."""
    row = {k: "" for k in FIELDS["fir"]}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if "fir" in k and ("no" in k or "id" in k):
            row["case_id"] = v
        elif "police station" in k:
            row["police_station"] = v
        elif "district" in k:
            row["district"] = v
        elif "state" in k:
            row["state"] = v
        elif "section" in k:
            row["sections_of_law"] = v
        elif "complainant" in k:
            row["complainant"] = v
        elif "accused" in k:
            row["accused_person_ids"] = v.replace(",", "|").replace(" ", "")
        elif "phone" in k:
            row["phone_numbers"] = v.replace(",", "|").replace(" ", "")
        elif "vehicle" in k:
            row["vehicle_ids"] = v.replace(",", "|").replace(" ", "")
        elif "account" in k:
            row["account_ids"] = v.replace(",", "|").replace(" ", "")
        elif "description" in k or "brief" in k:
            row["description"] = v
        elif "status" in k:
            row["status"] = v
        elif "date" in k:
            row["date"] = v
    if not row["case_id"] and fallback_case_id:
        row["case_id"] = fallback_case_id
    row["fir_id"] = row["case_id"]
    if not row["status"]:
        row["status"] = "Under Investigation"
    return row


def process_upload(store, graph_index, doctype, filename, raw_bytes, case_id_hint=None):
    warnings = []
    errors = []
    key = DOCTYPE_MAP.get(doctype.upper())
    if not key:
        return {"ok": False, "errors": [f"Unsupported data type: {doctype}"], "warnings": [], "records_added": 0}

    text = raw_bytes.decode("utf-8", errors="replace")
    rows_in = []

    if key == "fir" and filename.lower().endswith(".txt"):
        rows_in = [_parse_fir_text(text, case_id_hint)]
    else:
        try:
            reader = csv.DictReader(io.StringIO(text))
            rows_in = list(reader)
        except Exception as e:
            return {"ok": False, "errors": [f"Could not parse file as CSV: {e}"], "warnings": [], "records_added": 0}

    if not rows_in:
        return {"ok": False, "errors": ["No records found in file."], "warnings": [], "records_added": 0}

    added = 0
    existing_ids = {r.get(_primary_key(key)) for r in store.tables[key]}

    for raw in rows_in:
        row = {f: raw.get(f, "") for f in FIELDS[key]}

        # normalize identifiers per dataset
        if key == "fir":
            cid = normalize_case_id(row.get("case_id") or case_id_hint)
            if not cid:
                errors.append(f"Row skipped: could not normalize case id {row.get('case_id')!r}")
                continue
            row["case_id"], row["fir_id"] = cid, cid
        else:
            if row.get("case_id"):
                norm = normalize_case_id(row["case_id"])
                if norm:
                    row["case_id"] = norm
                else:
                    warnings.append(f"Row {raw.get(_primary_key(key), '?')}: case id {row['case_id']!r} could not be normalized, kept as-is")
            elif case_id_hint:
                cid = normalize_case_id(case_id_hint)
                if cid:
                    row["case_id"] = cid

        for phone_field in ("caller_phone", "receiver_phone", "phone_number"):
            if phone_field in row and row[phone_field]:
                norm = normalize_phone(row[phone_field])
                if norm:
                    row[phone_field] = norm
                else:
                    warnings.append(f"Malformed phone number skipped normalization: {row[phone_field]!r}")

        pk = _primary_key(key)
        if not row.get(pk):
            errors.append(f"Row skipped: missing required field '{pk}'")
            continue
        missing = [f for f in REQUIRED[key] if not row.get(f)]
        if missing:
            errors.append(f"Row {row.get(pk)}: missing required field(s) {missing}, skipped")
            continue
        if row[pk] in existing_ids:
            warnings.append(f"Duplicate record {row[pk]} skipped")
            continue

        store.append_row(key, row)
        existing_ids.add(row[pk])
        added += 1

    graph_index.rebuild()

    return {
        "ok": added > 0,
        "records_added": added,
        "records_in_file": len(rows_in),
        "warnings": warnings,
        "errors": errors,
        "case_id": normalize_case_id(case_id_hint) if case_id_hint else None,
    }


def _primary_key(key):
    return {"fir": "case_id", "cdr": "cdr_id", "telecom": "subscriber_id",
            "bank": "transaction_id", "social": "relationship_id",
            "vehicles": "vehicle_id"}[key]
