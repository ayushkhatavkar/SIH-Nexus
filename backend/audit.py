import hashlib
import json
import os
import threading
from datetime import datetime

LEDGER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "audit_ledger.json")
_lock = threading.Lock()


def _load():
    if os.path.exists(LEDGER_PATH):
        with open(LEDGER_PATH) as f:
            return json.load(f)
    return []


def _save(ledger):
    with open(LEDGER_PATH, "w") as f:
        json.dump(ledger, f, indent=2)


def log(actor, action, subject, payload):
    with _lock:
        ledger = _load()
        prev = ledger[-1]["hash"] if ledger else "0" * 64
        body = json.dumps({"actor": actor, "action": action, "subject": subject,
                            "payload": payload, "prev": prev}, sort_keys=True)
        h = hashlib.sha256(body.encode()).hexdigest()
        entry = {"index": len(ledger), "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  "actor": actor, "action": action, "subject": subject, "payload": payload,
                  "prev": prev, "hash": h}
        ledger.append(entry)
        _save(ledger)
        return entry


def all_entries():
    return _load()


def verify():
    ledger = _load()
    for i, b in enumerate(ledger):
        body = json.dumps({"actor": b["actor"], "action": b["action"], "subject": b["subject"],
                            "payload": b["payload"], "prev": b["prev"]}, sort_keys=True)
        h = hashlib.sha256(body.encode()).hexdigest()
        prev_ok = b["prev"] == ("0" * 64 if i == 0 else ledger[i - 1]["hash"])
        if h != b["hash"] or not prev_ok:
            return {"ok": False, "at": b["index"]}
    return {"ok": True, "count": len(ledger)}
