"""
In-memory data store for NEXUS.

For a hackathon prototype, flat CSVs ARE the database: they're the durable
source of truth on disk, loaded into memory as lists of dicts at startup
and after every successful ingestion. This keeps the project dependency-free
(no DB server) while still being genuinely persistent across restarts.
"""
import csv
import json
import os
import re
import threading
from collections import defaultdict
from datetime import datetime

from normalize import normalize_case_id, normalize_phone, normalize_id, normalize_name

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

FILES = {
    "fir": "fir.csv",
    "persons": "persons.csv",
    "cdr": "cdr.csv",
    "telecom": "telecom.csv",
    "bank": "bank_transactions.csv",
    "social": "social_connections.csv",
    "vehicles": "vehicles.csv",
}

FIELDS = {
    "fir": ["fir_id", "case_id", "date", "police_station", "district", "state",
            "sections_of_law", "complainant", "accused_person_ids", "phone_numbers",
            "vehicle_ids", "account_ids", "description", "status"],
    "persons": ["person_id", "name", "aliases", "age_range", "occupation", "phone_numbers",
                "addresses", "primary_account", "case_ids"],
    "cdr": ["cdr_id", "timestamp", "caller_phone", "receiver_phone", "duration_seconds",
            "call_type", "tower_id", "case_id"],
    "telecom": ["subscriber_id", "phone_number", "person_id", "subscriber_name", "operator",
                "activation_date", "address", "case_ids"],
    "bank": ["transaction_id", "timestamp", "sender_account", "receiver_account",
             "sender_person_id", "receiver_person_id", "amount", "transaction_type",
             "bank", "reference", "case_id"],
    "social": ["relationship_id", "source_person_id", "target_person_id", "platform",
                "relationship_type", "timestamp", "confidence", "case_id"],
    "vehicles": ["vehicle_id", "registration_number", "owner_person_id", "vehicle_type",
                 "location", "case_ids"],
}

REQUIRED_FIELDS = {
    "fir": ["case_id", "date", "police_station"],
    "persons": ["person_id", "name"],
    "cdr": ["cdr_id", "caller_phone", "receiver_phone"],
    "telecom": ["subscriber_id", "phone_number"],
    "bank": ["transaction_id", "sender_account", "receiver_account", "amount"],
    "social": ["relationship_id", "source_person_id", "target_person_id"],
    "vehicles": ["vehicle_id", "registration_number"],
}

_lock = threading.Lock()


class Store:
    def __init__(self):
        self.tables = {k: [] for k in FILES}
        self.alert_states = {}
        self.load_all()
        self._load_alert_states()

    def load_all(self):
        with _lock:
            for key, fname in FILES.items():
                path = os.path.join(DATA_DIR, fname)
                rows = []
                if os.path.exists(path):
                    with open(path, newline="", encoding="utf-8") as f:
                        rows = list(csv.DictReader(f))
                self.tables[key] = rows
        # normalize case ids everywhere on load, in place
        self._normalize_all()

    def _normalize_all(self):
        for r in self.tables["fir"]:
            r["case_id"] = normalize_case_id(r.get("case_id")) or r.get("case_id")
            r["fir_id"] = r["case_id"]
        for key in ("cdr", "bank", "social"):
            for r in self.tables[key]:
                if r.get("case_id"):
                    r["case_id"] = normalize_case_id(r["case_id"]) or r["case_id"]
        for key in ("persons", "telecom", "vehicles"):
            for r in self.tables[key]:
                cids = r.get("case_ids", "")
                if cids:
                    norm = [normalize_case_id(c) or c for c in cids.split("|") if c]
                    r["case_ids"] = "|".join(sorted(set(norm)))

    def _load_alert_states(self):
        path = os.path.join(DATA_DIR, "alert_states.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.alert_states = json.load(f)
            except Exception:
                self.alert_states = {}

    def _save_alert_states(self):
        path = os.path.join(DATA_DIR, "alert_states.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.alert_states, f, indent=2)
        except Exception:
            pass

    def get_alert_status(self, alert_id):
        return self.alert_states.get(alert_id, {}).get("status", "Open")

    def set_alert_status(self, alert_id, status, notes=""):
        with _lock:
            self.alert_states[alert_id] = {
                "status": status,
                "notes": notes,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self._save_alert_states()

    def append_row(self, key, row):
        """Append one normalized row to the in-memory table and persist to CSV."""
        with _lock:
            self.tables[key].append(row)
            path = os.path.join(DATA_DIR, FILES[key])
            write_header = not os.path.exists(path) or os.path.getsize(path) == 0
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS[key])
                if write_header:
                    w.writeheader()
                w.writerow({k: row.get(k, "") for k in FIELDS[key]})

    def case_ids(self):
        return sorted({r["case_id"] for r in self.tables["fir"] if r.get("case_id")})

    def get_fir(self, case_id):
        cid = normalize_case_id(case_id)
        for r in self.tables["fir"]:
            if r["case_id"] == cid:
                return r
        return None

    def resolve_person(self, query):
        """
        Transparent 5-tier entity resolution for person queries:
          Tier 1: Exact Person ID (e.g. 'P052', 'p052') -> 100% confidence
          Tier 2: Exact Normalized Full Name (e.g. 'Ashok Sheikh', 'ashok sheikh', 'Ashok   Sheikh') -> 100% confidence
          Tier 3: Associated Phone Number -> 95% confidence
          Tier 4: Known Alias Match (e.g. alias in p['aliases']) -> 90% confidence
          Tier 5: Partial / Token Match (e.g. 'Ashok', 'Sheikh') -> 75%-85% confidence
        Returns ranked list of candidates with confidence score and match reason.
        """
        if not query:
            return []
        q_raw = str(query).strip()
        q_norm = normalize_name(q_raw)
        q_id = normalize_id(q_raw)
        q_phone = normalize_phone(q_raw)

        candidates = {}

        def add_candidate(p, conf, m_type, reason):
            pid = p["person_id"]
            if pid not in candidates or candidates[pid]["confidence"] < conf:
                candidates[pid] = {
                    "person_id": p["person_id"],
                    "name": p["name"],
                    "aliases": p.get("aliases", ""),
                    "confidence": conf,
                    "match_type": m_type,
                    "match_reason": reason,
                    "occupation": p.get("occupation", ""),
                    "case_ids": p.get("case_ids", ""),
                    "phone_numbers": p.get("phone_numbers", ""),
                    "primary_account": p.get("primary_account", "")
                }

        phone_to_pids = defaultdict(set)
        for p in self.tables["persons"]:
            ph = normalize_phone(p.get("phone_numbers"))
            if ph:
                phone_to_pids[ph].add(p["person_id"])
        for t in self.tables["telecom"]:
            ph = normalize_phone(t.get("phone_number"))
            pid_raw = t.get("person_id")
            if ph and pid_raw:
                phone_to_pids[ph].add(normalize_id(pid_raw))

        q_tokens = set(q_norm.split()) if q_norm else set()

        for p in self.tables["persons"]:
            p_id_norm = normalize_id(p["person_id"])
            p_name_norm = normalize_name(p["name"])
            p_tokens = set(p_name_norm.split()) if p_name_norm else set()

            # Tier 1: Exact Person ID
            if q_id and p_id_norm == q_id:
                add_candidate(p, 100, "exact_id", f"Exact Person ID ({p['person_id']})")
                continue

            # Tier 2: Exact Normalized Name
            if q_norm and p_name_norm == q_norm:
                add_candidate(p, 100, "exact_name", f"Exact Name Match: '{p['name']}'")
                continue

            # Tier 3: Associated Phone
            if q_phone and p["person_id"] in phone_to_pids.get(q_phone, set()):
                add_candidate(p, 95, "associated_phone", f"Associated with Phone: {q_phone}")
                continue

            # Tier 4: Known Alias Match
            aliases = [normalize_name(a) for a in (p.get("aliases") or "").split("|") if a.strip()]
            alias_matched = None
            for a in aliases:
                if a == q_norm:
                    alias_matched = a
                    break
            if alias_matched:
                add_candidate(p, 90, "known_alias", f"Matched Known Alias: '{alias_matched}'")
                continue

            # Tier 5: Token / Word Match
            if q_tokens and p_tokens:
                if q_tokens.issubset(p_tokens):
                    conf = 85 if len(q_tokens) == 1 else 90
                    add_candidate(p, conf, "partial_name", f"Partial Name Match ({' '.join(sorted(q_tokens))})")
                    continue
                elif q_tokens & p_tokens:
                    common = q_tokens & p_tokens
                    add_candidate(p, 75, "partial_name", f"Shared Name Token ({' '.join(sorted(common))})")
                    continue

            # Substring match fallback (minimum 3 characters)
            if len(q_norm) >= 3 and (q_norm in p_name_norm or p_name_norm in q_norm):
                add_candidate(p, 70, "partial_name", f"Partial Substring Match: '{q_norm}'")

        results = list(candidates.values())
        results.sort(key=lambda x: (-x["confidence"], abs(len(x["name"]) - len(q_raw))))
        return results

    def find_person_by_name(self, name):
        """Uses resolve_person to return matching person dicts, maintaining API compatibility."""
        candidates = self.resolve_person(name)
        pid_map = {p["person_id"]: p for p in self.tables["persons"]}
        out = []
        for c in candidates:
            p = pid_map.get(c["person_id"])
            if p:
                p_copy = dict(p)
                p_copy["confidence"] = c["confidence"]
                p_copy["match_type"] = c["match_type"]
                p_copy["match_reason"] = c["match_reason"]
                out.append(p_copy)
        return out

    def find_person(self, person_id):
        pid = normalize_id(person_id)
        for p in self.tables["persons"]:
            if normalize_id(p["person_id"]) == pid:
                return p
        return None

    def find_by_phone(self, phone):
        ph = normalize_phone(phone)
        return [t for t in self.tables["telecom"] if normalize_phone(t.get("phone_number")) == ph]

    def find_vehicle(self, query):
        """Finds vehicle by registration number (any format) or vehicle ID."""
        if not query:
            return []
        q = str(query).strip().upper()
        q_clean = re.sub(r'[^A-Z0-9]', '', q)
        matches = []
        for v in self.tables["vehicles"]:
            vid = normalize_id(v.get("vehicle_id"))
            reg = normalize_id(v.get("registration_number"))
            reg_clean = re.sub(r'[^A-Z0-9]', '', reg) if reg else ""
            if q == vid or (q_clean and q_clean == vid):
                matches.append({
                    "vehicle_id": v["vehicle_id"],
                    "registration_number": v.get("registration_number", ""),
                    "vehicle_type": v.get("vehicle_type", "Vehicle"),
                    "location": v.get("location", ""),
                    "owner_person_id": v.get("owner_person_id", ""),
                    "case_ids": v.get("case_ids", ""),
                    "confidence": 100,
                    "match_type": "exact_id",
                    "match_reason": f"Exact Vehicle ID ({v['vehicle_id']})"
                })
            elif q_clean and reg_clean and (q_clean == reg_clean or q_clean in reg_clean):
                conf = 100 if q_clean == reg_clean else 80
                matches.append({
                    "vehicle_id": v.get("vehicle_id", ""),
                    "registration_number": v["registration_number"],
                    "vehicle_type": v.get("vehicle_type", "Vehicle"),
                    "location": v.get("location", ""),
                    "owner_person_id": v.get("owner_person_id", ""),
                    "case_ids": v.get("case_ids", ""),
                    "confidence": conf,
                    "match_type": "registration_number",
                    "match_reason": f"Registration Number Match ({v['registration_number']})"
                })
        return matches

    def find_account(self, query):
        """Finds bank account by account number or transaction ID."""
        if not query:
            return []
        q = str(query).strip().upper()
        matches = []
        seen = set()
        # Check persons primary accounts
        for p in self.tables["persons"]:
            acc = p.get("primary_account")
            if acc and (q == normalize_id(acc) or q in normalize_id(acc)):
                if acc not in seen:
                    seen.add(acc)
                    matches.append({
                        "account_id": acc,
                        "owner_person_id": p.get("person_id", ""),
                        "owner_name": p.get("name", ""),
                        "bank": "Primary Account",
                        "confidence": 100 if q == normalize_id(acc) else 80,
                        "match_type": "account_number",
                        "match_reason": f"Primary account of {p.get('name')}"
                    })
        # Check bank transactions
        for b in self.tables["bank"]:
            for acc_field, role in [("sender_account", "Sender"), ("receiver_account", "Receiver")]:
                acc = b.get(acc_field)
                if acc and (q == normalize_id(acc) or q in normalize_id(acc)):
                    if acc not in seen:
                        seen.add(acc)
                        matches.append({
                            "account_id": acc,
                            "owner_person_id": b.get(f"{role.lower()}_person_id", ""),
                            "bank": b.get("bank", "Bank"),
                            "confidence": 100 if q == normalize_id(acc) else 80,
                            "match_type": "account_number",
                            "match_reason": f"Appears as {role} account in transactions"
                        })
            tx_id = b.get("transaction_id")
            if tx_id and q == normalize_id(tx_id):
                matches.append({
                    "account_id": b.get("sender_account", ""),
                    "transaction_id": tx_id,
                    "bank": b.get("bank", ""),
                    "confidence": 100,
                    "match_type": "transaction_id",
                    "match_reason": f"Exact Transaction ID ({tx_id})"
                })
        return matches

    def data_quality_audit(self):
        """Performs a comprehensive audit across all ingested datasets."""
        audit_res = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "datasets": {},
            "total_records": 0,
            "missing_fields": [],
            "duplicate_records": [],
            "malformed_phones": [],
            "malformed_cases": [],
            "orphan_entities": [],
            "health_score": 100,
        }

        total_records = 0
        total_issues = 0

        # Known entity pools
        known_pids = {normalize_id(p["person_id"]) for p in self.tables["persons"]}
        known_cids = {r["case_id"] for r in self.tables["fir"]}

        for key, rows in self.tables.items():
            total_records += len(rows)
            audit_res["datasets"][key] = len(rows)
            seen_pks = set()
            pk_name = {"fir": "case_id", "persons": "person_id", "cdr": "cdr_id",
                       "telecom": "subscriber_id", "bank": "transaction_id",
                       "social": "relationship_id", "vehicles": "vehicle_id"}.get(key)

            for i, r in enumerate(rows):
                # 1. Missing required fields
                for req in REQUIRED_FIELDS.get(key, []):
                    if not str(r.get(req, "")).strip():
                        total_issues += 1
                        audit_res["missing_fields"].append({
                            "dataset": key, "record_index": i + 1, "record_id": r.get(pk_name, f"row_{i+1}"),
                            "field": req, "issue": f"Missing required field '{req}'"
                        })

                # 2. Duplicate detection
                if pk_name:
                    pk_val = r.get(pk_name)
                    if pk_val:
                        if pk_val in seen_pks:
                            total_issues += 1
                            audit_res["duplicate_records"].append({
                                "dataset": key, "record_id": pk_val, "issue": f"Duplicate primary key '{pk_val}'"
                            })
                        seen_pks.add(pk_val)

                # 3. Malformed phone numbers
                for pf in ("caller_phone", "receiver_phone", "phone_number", "phone_numbers"):
                    val = r.get(pf)
                    if val:
                        for item in str(val).split("|"):
                            if item.strip() and not normalize_phone(item):
                                total_issues += 1
                                audit_res["malformed_phones"].append({
                                    "dataset": key, "record_id": r.get(pk_name, f"row_{i+1}"),
                                    "field": pf, "raw_value": item.strip(), "issue": "Invalid phone format (<10 digits)"
                                })

                # 4. Malformed case IDs
                for cf in ("case_id", "case_ids"):
                    val = r.get(cf)
                    if val:
                        for item in str(val).split("|"):
                            if item.strip() and not normalize_case_id(item):
                                total_issues += 1
                                audit_res["malformed_cases"].append({
                                    "dataset": key, "record_id": r.get(pk_name, f"row_{i+1}"),
                                    "field": cf, "raw_value": item.strip(), "issue": "Malformed Case/FIR format"
                                })

        # 5. Orphan / Unresolved Entities
        # FIR Accused IDs
        for f in self.tables["fir"]:
            for pid in (f.get("accused_person_ids") or "").split("|"):
                if pid.strip() and normalize_id(pid) not in known_pids:
                    total_issues += 1
                    audit_res["orphan_entities"].append({
                        "source": "fir.csv", "case_id": f.get("case_id"), "entity_type": "ACCUSED_PERSON",
                        "entity_id": pid, "issue": f"Accused person '{pid}' cited in FIR {f.get('case_id')} does not exist in persons registry."
                    })

        # Vehicles owner
        for v in self.tables["vehicles"]:
            owner = v.get("owner_person_id")
            if owner and normalize_id(owner) not in known_pids:
                total_issues += 1
                audit_res["orphan_entities"].append({
                    "source": "vehicles.csv", "entity_type": "VEHICLE_OWNER",
                    "entity_id": owner, "issue": f"Vehicle owner '{owner}' for vehicle {v.get('registration_number')} not found in persons registry."
                })

        audit_res["total_records"] = total_records
        penalty = min(100, int((total_issues / max(1, total_records)) * 100))
        audit_res["health_score"] = max(0, 100 - penalty)
        audit_res["total_issues"] = total_issues

        return audit_res


STORE = Store()

