"""
NEXUS demo data generator.

CONFIDENTIAL — SYNTHETIC DEMONSTRATION DATA. No real person, phone number,
account, or vehicle is represented. Every dataset produced here is fictional
and generated with a fixed seed so it can be regenerated deterministically:

    python generate_demo_data.py

Produces (all under data/):
    fir.csv, persons.csv, cdr.csv, telecom.csv, bank_transactions.csv,
    social_connections.csv, vehicles.csv, ground_truth.json

The datasets are DELIBERATELY connected across cases (see SCENARIOS below)
so the investigation workflow has real chains to discover, and 5 designed
cross-case scenarios are recorded in ground_truth.json for evaluation.
"""
import csv, json, os, random
from datetime import datetime, timedelta
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))
from normalize import normalize_case_id, normalize_phone

random.seed(26189)
BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
os.makedirs(DATA, exist_ok=True)

SYNTHETIC_NOTICE = "CONFIDENTIAL — SYNTHETIC DEMONSTRATION DATA. No real person or record is represented."

# ------------------------------------------------------------- reference lists
FIRST = ["Ramesh", "Suresh", "Vikram", "Salim", "Deepak", "Ashok", "Rehana", "Imran",
         "Anil", "Rakesh", "Kiran", "Sunil", "Farhan", "Nitin", "Sameer", "Prakash",
         "Javed", "Ganesh", "Priya", "Meena", "Sunita", "Anjali", "Kavita", "Pooja",
         "Rajesh", "Manoj", "Vijay", "Sanjay", "Arun", "Vinod", "Ravi", "Ajay",
         "Naresh", "Mahesh", "Dinesh", "Yogesh", "Santosh", "Ramesh", "Amit", "Rohit",
         "Neha", "Sneha", "Divya", "Shreya", "Kiran", "Zoya", "Aisha", "Fatima"]
LAST = ["Patil", "Yadav", "Shetty", "Khan", "Rane", "Chavan", "Shaikh", "Kadam",
        "Jadhav", "Waghmare", "Bhosale", "Ansari", "Gaikwad", "Qureshi", "More",
        "Momin", "Shinde", "Deshmukh", "Pawar", "Joshi", "Kulkarni", "Naik",
        "Sayyed", "Sheikh", "Chauhan", "Verma", "Mehta", "Rao", "Bhatt", "Iyer"]
AREAS = ["Dharavi", "Kurla West", "Govandi", "Andheri East", "Chembur", "Sion",
         "Mankhurd", "Wadala", "Nagpada", "Bandra East", "Pune Camp", "Marol",
         "Shivaji Nagar", "Vashi", "Thane West", "Kalyan", "Byculla", "Worli"]
STATIONS = {"Dharavi": ("Dharavi PS", "Mumbai", "Maharashtra"),
            "Kurla West": ("Kurla PS", "Mumbai", "Maharashtra"),
            "Govandi": ("Govandi PS", "Mumbai", "Maharashtra"),
            "Andheri East": ("Andheri PS", "Mumbai", "Maharashtra"),
            "Chembur": ("Chembur PS", "Mumbai", "Maharashtra"),
            "Sion": ("Sion PS", "Mumbai", "Maharashtra"),
            "Mankhurd": ("Mankhurd PS", "Mumbai", "Maharashtra"),
            "Wadala": ("Wadala PS", "Mumbai", "Maharashtra"),
            "Nagpada": ("Nagpada PS", "Mumbai", "Maharashtra"),
            "Bandra East": ("Bandra PS", "Mumbai", "Maharashtra"),
            "Pune Camp": ("Pune Camp PS", "Pune", "Maharashtra"),
            "Marol": ("Marol PS", "Mumbai", "Maharashtra"),
            "Shivaji Nagar": ("Shivaji Nagar PS", "Pune", "Maharashtra"),
            "Vashi": ("Vashi PS", "Navi Mumbai", "Maharashtra"),
            "Thane West": ("Thane PS", "Thane", "Maharashtra"),
            "Kalyan": ("Kalyan PS", "Thane", "Maharashtra"),
            "Byculla": ("Byculla PS", "Mumbai", "Maharashtra"),
            "Worli": ("Worli PS", "Mumbai", "Maharashtra")}
SECTIONS = ["BNS 303 (Theft)", "BNS 318 (Cheating)", "NDPS Act 20/22",
            "BNS 61 (Criminal Conspiracy)", "PMLA 3/4", "Arms Act 25",
            "BNS 351 (Criminal Intimidation)", "BNSS 41A", "BNS 336 (Forgery)"]
OCCUPATIONS = ["Driver", "Shopkeeper", "Broker", "Contractor", "Unemployed",
               "Auto mechanic", "Trader", "Real estate agent", "Courier",
               "Electrician", "Fisherman", "Scrap dealer", "Mobile repair technician"]
OPERATORS = ["Airtel", "Jio", "Vi", "BSNL"]
BANKS = ["SBI", "HDFC", "ICICI", "Axis", "PNB", "BOI"]
PLATFORMS = ["WhatsApp", "Facebook", "Instagram", "Telegram"]
REL_TYPES = ["communicates_with", "follows", "member_of", "associated_with"]
VEHICLE_TYPES = ["Motorcycle", "Car", "Auto-rickshaw", "Tempo", "SUV"]

N_PERSONS = 80
N_FIRS = 25
N_CDR = 200
N_BANK = 150
N_TELECOM = 100
N_SOCIAL = 150
N_VEHICLES = 60

# case numbers: deliberately include 170, 117, 139, 158 to match the demo
# scenario narrative, then fill out the rest with distinct random numbers.
FEATURED_CASE_NUMS = [170, 117, 139, 158]
other_pool = [n for n in range(101, 480) if n not in FEATURED_CASE_NUMS]
random.shuffle(other_pool)
CASE_NUMS = FEATURED_CASE_NUMS + other_pool[: N_FIRS - len(FEATURED_CASE_NUMS)]
CASE_IDS = [normalize_case_id(f"{n:04d}/2026") for n in CASE_NUMS]
CASE_A, CASE_B, CASE_C, CASE_D = CASE_IDS[0], CASE_IDS[1], CASE_IDS[2], CASE_IDS[3]  # 170, 117, 139, 158

START = datetime(2026, 1, 10)


def rand_name(used):
    while True:
        n = f"{random.choice(FIRST)} {random.choice(LAST)}"
        if n not in used:
            used.add(n)
            return n


def rand_phone(used):
    while True:
        p = "98" + "".join(random.choice("0123456789") for _ in range(8))
        if p not in used:
            used.add(p)
            return p


def rand_account(used):
    while True:
        a = "".join(random.choice("0123456789") for _ in range(12))
        if a not in used:
            used.add(a)
            return a


def rand_vehicle_reg(used):
    while True:
        v = f"MH{random.randint(1,49):02d}{random.choice('ABCDEFGHJKLMN')}{random.choice('ABCDEFGHJKLMN')}{random.randint(1000,9999)}"
        if v not in used:
            used.add(v)
            return v


def rand_ts(base, max_days=210):
    return base + timedelta(days=random.randint(0, max_days),
                             hours=random.randint(0, 23), minutes=random.randint(0, 59))


# ------------------------------------------------------------------- PERSONS
used_names, used_phones, used_accounts = set(), set(), set()
persons = []
for i in range(1, N_PERSONS + 1):
    pid = f"P{i:03d}"
    name = rand_name(used_names)
    phone = rand_phone(used_phones)
    account = rand_account(used_accounts) if random.random() < 0.85 else ""
    area = random.choice(AREAS)
    persons.append({
        "person_id": pid, "name": name,
        "aliases": name.split()[0][0] + ". " + name.split()[-1],
        "age_range": random.choice(["18-25", "26-35", "36-45", "46-55", "56-65"]),
        "occupation": random.choice(OCCUPATIONS),
        "phone_numbers": phone,
        "addresses": f"{area}, Mumbai" if area != "Pune Camp" else "Pune Camp, Pune",
        "primary_account": account,
        "case_ids": "",  # filled in after FIRs are built
    })
PID = [p["person_id"] for p in persons]
PHONE_OF = {p["person_id"]: p["phone_numbers"] for p in persons}
ACCT_OF = {p["person_id"]: p["primary_account"] for p in persons if p["primary_account"]}
NAME_OF = {p["person_id"]: p["name"] for p in persons}

# ------------------------------------------------------------------- VEHICLES
used_regs = set()
vehicles = []
owner_choices = random.sample(PID, min(N_VEHICLES, N_PERSONS))
for i in range(N_VEHICLES):
    vid = f"V{i+1:03d}"
    owner = owner_choices[i % len(owner_choices)]
    vehicles.append({
        "vehicle_id": vid,
        "registration_number": rand_vehicle_reg(used_regs),
        "owner_person_id": owner,
        "vehicle_type": random.choice(VEHICLE_TYPES),
        "location": random.choice(AREAS),
        "case_ids": "",
    })

# ---------------------------------------------------------- FIR / CASE SETUP
# Each case gets 2-5 accused persons. Cross-case bridges are injected explicitly below.
person_case_map = {pid: set() for pid in PID}
fir_accused = {}
random.shuffle(PID)
pool_cursor = 0
for cid in CASE_IDS:
    k = random.randint(2, 5)
    accused = []
    for _ in range(k):
        accused.append(PID[pool_cursor % N_PERSONS])
        pool_cursor += 1
    fir_accused[cid] = list(dict.fromkeys(accused))  # dedupe, keep order

# ---- deliberate cross-case scenarios (ground truth) ----
scenarios = []

# Scenario 1: Person shared between Case A (FIR-0170) and Case B (FIR-0117)
bridge_person_ab = fir_accused[CASE_A][0]
if bridge_person_ab not in fir_accused[CASE_B]:
    fir_accused[CASE_B].append(bridge_person_ab)
scenarios.append({"type": "shared_person", "entity": bridge_person_ab,
                   "entity_name": NAME_OF[bridge_person_ab],
                   "cases": [CASE_A, CASE_B],
                   "description": f"{NAME_OF[bridge_person_ab]} ({bridge_person_ab}) is named as accused in both {CASE_A} and {CASE_B}."})

# Scenario 2: Phone shared between Case A (FIR-0170) and Case C (FIR-0139)
# — modeled as a second accused person in Case A whose phone also surfaces via CDR/telecom tied to Case C
bridge_person_ac = fir_accused[CASE_A][1] if len(fir_accused[CASE_A]) > 1 else fir_accused[CASE_A][0]
bridge_phone_ac = PHONE_OF[bridge_person_ac]
if bridge_person_ac not in fir_accused[CASE_C]:
    pass  # phone appears via CDR case_id tagging below, not as a named accused
scenarios.append({"type": "shared_phone", "entity": bridge_phone_ac,
                   "entity_name": f"Phone {bridge_phone_ac} ({NAME_OF[bridge_person_ac]})",
                   "cases": [CASE_A, CASE_C],
                   "description": f"Phone {bridge_phone_ac}, registered to {NAME_OF[bridge_person_ac]}, "
                                   f"appears in CDR traffic tagged to both {CASE_A} and {CASE_C}."})

# Scenario 3: Vehicle shared between Case B (FIR-0117) and Case D (FIR-0158)
bridge_vehicle = vehicles[0]
bridge_vehicle["case_ids"] = f"{CASE_B}|{CASE_D}"
scenarios.append({"type": "shared_vehicle", "entity": bridge_vehicle["vehicle_id"],
                   "entity_name": bridge_vehicle["registration_number"],
                   "cases": [CASE_B, CASE_D],
                   "description": f"Vehicle {bridge_vehicle['registration_number']} is linked to both {CASE_B} and {CASE_D}."})

# Scenario 4: Bank account connects a person from Case A with a person from Case B
person_a_fin = fir_accused[CASE_A][-1]
person_b_fin = fir_accused[CASE_B][-1]
scenarios.append({"type": "financial_link", "entity": f"{person_a_fin}->{person_b_fin}",
                   "entity_name": f"{NAME_OF[person_a_fin]} -> {NAME_OF[person_b_fin]}",
                   "cases": [CASE_A, CASE_B],
                   "description": f"A bank transaction connects {NAME_OF[person_a_fin]} ({CASE_A}) to "
                                   f"{NAME_OF[person_b_fin]} ({CASE_B})."})

# Scenario 5: Communication chain — Case C person calls a Case A bridge, deepening the network
person_c_comm = fir_accused[CASE_C][0]
scenarios.append({"type": "communication_chain", "entity": f"{person_c_comm}->{bridge_person_ac}",
                   "entity_name": f"{NAME_OF[person_c_comm]} -> {NAME_OF[bridge_person_ac]}",
                   "cases": [CASE_C, CASE_A],
                   "description": f"{NAME_OF[person_c_comm]} ({CASE_C}) is in frequent phone contact with "
                                   f"{NAME_OF[bridge_person_ac]}, an accused in {CASE_A}."})

for pid, cids in fir_accused.items():
    for p in cids:
        person_case_map[p].add(pid)

# ------------------------------------------------------------------- FIRS
firs = []
for cid in CASE_IDS:
    area = random.choice(AREAS)
    station, district, state = STATIONS[area]
    accused = fir_accused[cid]
    veh = [v for v in vehicles if v["owner_person_id"] in accused]
    veh_ids = [v["vehicle_id"] for v in veh[:2]]
    accts = [ACCT_OF[p] for p in accused if p in ACCT_OF][:2]
    phones = [PHONE_OF[p] for p in accused][:3]
    firs.append({
        "fir_id": cid, "case_id": cid,
        "date": rand_ts(START, 200).strftime("%Y-%m-%d"),
        "police_station": station, "district": district, "state": state,
        "sections_of_law": random.choice(SECTIONS),
        "complainant": rand_name(used_names),
        "accused_person_ids": "|".join(accused),
        "phone_numbers": "|".join(phones),
        "vehicle_ids": "|".join(veh_ids),
        "account_ids": "|".join(accts),
        "description": f"Complaint registered regarding an incident involving {len(accused)} accused "
                        f"person(s) in the {area} area. Investigation ongoing.",
        "status": random.choice(["Under Investigation", "Under Investigation", "Chargesheet Filed", "Closed"]),
    })
    for v in veh:
        existing = v["case_ids"].split("|") if v["case_ids"] else []
        v["case_ids"] = "|".join(sorted(set(existing + [cid])))

for p in persons:
    p["case_ids"] = "|".join(sorted(person_case_map[p["person_id"]]))

# ------------------------------------------------------------------- TELECOM
telecom = []
tel_used_ids = set()
for i, p in enumerate(persons):
    telecom.append({
        "subscriber_id": f"T{i+1:03d}", "phone_number": p["phone_numbers"],
        "person_id": p["person_id"], "subscriber_name": p["name"],
        "operator": random.choice(OPERATORS),
        "activation_date": rand_ts(START - timedelta(days=400), 400).strftime("%Y-%m-%d"),
        "address": p["addresses"], "case_ids": p["case_ids"],
    })
# extra burner/unregistered numbers to reach N_TELECOM
burner_phones = []
while len(telecom) < N_TELECOM:
    ph = rand_phone(used_phones)
    burner_phones.append(ph)
    telecom.append({
        "subscriber_id": f"T{len(telecom)+1:03d}", "phone_number": ph,
        "person_id": "", "subscriber_name": "NOT REGISTERED",
        "operator": random.choice(OPERATORS),
        "activation_date": rand_ts(START, 200).strftime("%Y-%m-%d"),
        "address": "", "case_ids": "",
    })

# ------------------------------------------------------------------- CDR
cdr = []
call_links = []
# base: accused persons in each case call each other
for cid, accused in fir_accused.items():
    for i in range(len(accused) - 1):
        call_links.append((accused[i], accused[i + 1], cid))
# scenario 2 + 5: explicit cross-case communication chain
call_links.append((bridge_person_ac, person_c_comm, CASE_C))
call_links.append((bridge_person_ac, bridge_person_ab, CASE_A))
# pad with random social calls among persons to reach N_CDR
while len(call_links) < N_CDR // 3:
    a, b = random.sample(PID, 2)
    call_links.append((a, b, ""))

for i in range(N_CDR):
    a, b, cid = call_links[i % len(call_links)]
    ts = rand_ts(START)
    cdr.append({
        "cdr_id": f"C{i+1:04d}", "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "caller_phone": PHONE_OF[a], "receiver_phone": PHONE_OF[b],
        "duration_seconds": random.randint(15, 900),
        "call_type": random.choice(["voice", "voice", "voice", "sms"]),
        "tower_id": f"TWR-{random.randint(1,40):03d}",
        "case_id": cid,
    })
# tag the scenario-2 bridge phone's calls into CASE_C explicitly (shared phone across cases)
cdr.append({
    "cdr_id": f"C{N_CDR+1:04d}", "timestamp": rand_ts(START).strftime("%Y-%m-%d %H:%M:%S"),
    "caller_phone": bridge_phone_ac, "receiver_phone": PHONE_OF[person_c_comm],
    "duration_seconds": random.randint(60, 500), "call_type": "voice",
    "tower_id": "TWR-017", "case_id": CASE_C,
})

# ------------------------------------------------------------------- BANK
bank = []
txn_links = []
for cid, accused in fir_accused.items():
    accts = [ACCT_OF[p] for p in accused if p in ACCT_OF]
    for i in range(len(accts) - 1):
        txn_links.append((accts[i], accts[i + 1],
                           [p for p in accused if ACCT_OF.get(p) == accts[i]][0],
                           [p for p in accused if ACCT_OF.get(p) == accts[i + 1]][0], cid))
# scenario 4: explicit financial bridge between case A and case B persons
if person_a_fin in ACCT_OF and person_b_fin in ACCT_OF:
    txn_links.append((ACCT_OF[person_a_fin], ACCT_OF[person_b_fin], person_a_fin, person_b_fin, CASE_A))
while len(txn_links) < N_BANK // 2:
    a, b = random.sample([p for p in PID if p in ACCT_OF], 2)
    txn_links.append((ACCT_OF[a], ACCT_OF[b], a, b, ""))

for i in range(N_BANK):
    sa, ra, sp, rp, cid = txn_links[i % len(txn_links)]
    bank.append({
        "transaction_id": f"TXN{i+1:04d}", "timestamp": rand_ts(START).strftime("%Y-%m-%d %H:%M:%S"),
        "sender_account": sa, "receiver_account": ra,
        "sender_person_id": sp, "receiver_person_id": rp,
        "amount": random.choice([5000, 12000, 25000, 48000, 49500, 75000, 150000, 300000]),
        "transaction_type": random.choice(["NEFT", "IMPS", "UPI", "RTGS"]),
        "bank": random.choice(BANKS), "reference": f"REF{random.randint(100000,999999)}",
        "case_id": cid,
    })

# ------------------------------------------------------------------- SOCIAL
social = []
for i in range(N_SOCIAL):
    a, b = random.sample(PID, 2)
    social.append({
        "relationship_id": f"S{i+1:04d}", "source_person_id": a, "target_person_id": b,
        "platform": random.choice(PLATFORMS), "relationship_type": random.choice(REL_TYPES),
        "timestamp": rand_ts(START).strftime("%Y-%m-%d"),
        "confidence": round(random.uniform(0.55, 0.98), 2),
        "case_id": random.choice(list(person_case_map[a] | person_case_map[b]) + [""]),
    })

# ------------------------------------------------------------------------ WRITE
def write_csv(name, rows, fields):
    with open(os.path.join(DATA, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

write_csv("persons.csv", persons,
           ["person_id", "name", "aliases", "age_range", "occupation", "phone_numbers",
            "addresses", "primary_account", "case_ids"])
write_csv("fir.csv", firs,
           ["fir_id", "case_id", "date", "police_station", "district", "state",
            "sections_of_law", "complainant", "accused_person_ids", "phone_numbers",
            "vehicle_ids", "account_ids", "description", "status"])
write_csv("cdr.csv", cdr,
           ["cdr_id", "timestamp", "caller_phone", "receiver_phone", "duration_seconds",
            "call_type", "tower_id", "case_id"])
write_csv("telecom.csv", telecom,
           ["subscriber_id", "phone_number", "person_id", "subscriber_name", "operator",
            "activation_date", "address", "case_ids"])
write_csv("bank_transactions.csv", bank,
           ["transaction_id", "timestamp", "sender_account", "receiver_account",
            "sender_person_id", "receiver_person_id", "amount", "transaction_type",
            "bank", "reference", "case_id"])
write_csv("social_connections.csv", social,
           ["relationship_id", "source_person_id", "target_person_id", "platform",
            "relationship_type", "timestamp", "confidence", "case_id"])
write_csv("vehicles.csv", vehicles,
           ["vehicle_id", "registration_number", "owner_person_id", "vehicle_type",
            "location", "case_ids"])

ground_truth = {
    "notice": SYNTHETIC_NOTICE,
    "featured_cases": {"case_a": CASE_A, "case_b": CASE_B, "case_c": CASE_C, "case_d": CASE_D},
    "scenarios": scenarios,
    "case_id": CASE_A,
    "important_entities": [bridge_person_ab, bridge_person_ac],
    "related_cases": [CASE_B, CASE_C],
}
with open(os.path.join(DATA, "ground_truth.json"), "w") as f:
    json.dump(ground_truth, f, indent=2)

print(f"Persons        : {len(persons)}")
print(f"FIR cases      : {len(firs)}")
print(f"CDR records    : {len(cdr)}")
print(f"Telecom records: {len(telecom)}")
print(f"Bank txns      : {len(bank)}")
print(f"Social links   : {len(social)}")
print(f"Vehicles       : {len(vehicles)}")
print(f"\nFeatured cases : A={CASE_A}  B={CASE_B}  C={CASE_C}  D={CASE_D}")
print(f"Written to {DATA}")
print(f"\n{SYNTHETIC_NOTICE}")
