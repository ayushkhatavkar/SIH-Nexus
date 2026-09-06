"""
Canonical normalization for NEXUS.

Case IDs and phone numbers arrive in the wild in many textual shapes.
Every layer of the app (ingestion, storage, search, graph, API) must
resolve them to ONE canonical form or "same case / same phone" lookups
silently fail. This module is the single source of truth for that.
"""
import re

CASE_RX = re.compile(r'^(\d{1,6})-(\d{4})$')


def normalize_case_id(raw):
    """
    'FIR-0170-2026', '0170/2026', 'FIR 0170/2026', 'fir0170-2026'
    all normalize to 'FIR-0170-2026'.
    Returns None if the input cannot be parsed as a case id.
    """
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if not s:
        return None
    # drop a leading FIR token in any of its separator forms: "FIR-", "FIR ", "FIR"
    s = re.sub(r'^FIR[\s\-]*', '', s)
    # unify separators: slashes and spaces become hyphens
    s = re.sub(r'[/\s]+', '-', s)
    # collapse repeated hyphens
    s = re.sub(r'-+', '-', s).strip('-')
    m = CASE_RX.match(s)
    if not m:
        return None
    num, year = m.groups()
    num = num.zfill(4)
    return f"FIR-{num}-{year}"


def normalize_phone(raw):
    """
    '9821005511', '+91 9821005511', '91-9821005511', '098210 05511'
    all normalize to '9821005511' (last 10 digits).
    Returns None if fewer than 10 digits are present.
    """
    if raw is None:
        return None
    digits = re.sub(r'\D', '', str(raw))
    if len(digits) < 10:
        return None
    return digits[-10:]


def normalize_name(raw):
    """
    Normalizes a person name for search and matching:
    - strips leading/trailing whitespace
    - collapses multiple spaces into a single space
    - lowercases for case-insensitive matching
    - removes punctuation (e.g. 'A. Sheikh' -> 'a sheikh')
    """
    if raw is None:
        return ""
    s = str(raw).strip().lower()
    s = re.sub(r'[^\w\s]', '', s)
    s = re.sub(r'\s+', ' ', s)
    return s


def normalize_id(raw):
    """Generic whitespace/case trim for stable IDs like person_id, vehicle_id, account ids."""
    if raw is None:
        return None
    return str(raw).strip().upper()


if __name__ == "__main__":
    tests = [
        ("FIR-0170-2026", "FIR-0170-2026"),
        ("0170/2026", "FIR-0170-2026"),
        ("FIR 0170/2026", "FIR-0170-2026"),
        ("fir-170-2026", "FIR-0170-2026"),
        ("  FIR   0170 / 2026 ", "FIR-0170-2026"),
    ]
    for raw, expected in tests:
        got = normalize_case_id(raw)
        status = "OK" if got == expected else "FAIL"
        print(f"[{status}] normalize_case_id({raw!r}) = {got!r} (expected {expected!r})")

    ptests = [
        ("9821005511", "9821005511"),
        ("+91 9821005511", "9821005511"),
        ("91-9821005511", "9821005511"),
        ("098210 05511", "9821005511"),
    ]
    for raw, expected in ptests:
        got = normalize_phone(raw)
        status = "OK" if got == expected else "FAIL"
        print(f"[{status}] normalize_phone({raw!r}) = {got!r} (expected {expected!r})")
