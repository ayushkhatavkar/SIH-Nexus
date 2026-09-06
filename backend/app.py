"""
NEXUS backend — Flask.

Serves the static frontend from ../ui and the investigation API under /api.
Run:  python server.py   (see repo root)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request, send_from_directory

from data_store import Store
from graph_engine import GraphIndex
from normalize import normalize_case_id, normalize_id, normalize_phone
import ingestion
import audit

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(BASE, "ui")

app = Flask(__name__, static_folder=None)

store = Store()
graph_index = GraphIndex(store)
audit.log("system", "SYSTEM_START", "NEXUS", {"cases": len(store.case_ids())})

DEFAULT_HOPS = 2


# ------------------------------------------------------------------ static
@app.route("/")
def index():
    return send_from_directory(UI_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    if os.path.exists(os.path.join(UI_DIR, path)):
        return send_from_directory(UI_DIR, path)
    return send_from_directory(UI_DIR, "index.html")


# ------------------------------------------------------------------ helpers
def case_summary(case_id):
    cid = normalize_case_id(case_id)
    if not cid:
        return None
    fir = store.get_fir(cid)
    if not fir:
        return None
    sub = graph_index.case_subgraph(cid, hops=1)
    types = {}
    if sub:
        for n in sub["node_ids"]:
            t = graph_index.G.nodes[n]["type"]
            types[t] = types.get(t, 0) + 1
    related = graph_index.related_cases(cid)
    return {
        "case_id": fir["case_id"],
        "police_station": fir.get("police_station", ""),
        "district": fir.get("district", ""),
        "state": fir.get("state", ""),
        "date": fir.get("date", ""),
        "status": fir.get("status", ""),
        "sections_of_law": fir.get("sections_of_law", ""),
        "description": fir.get("description", ""),
        "entity_counts": types,
        "total_entities": (len(sub["node_ids"]) - 1) if sub else 0,
        "related_case_count": len(related),
    }


def suggest_cases(query):
    ids = store.case_ids()
    q = (query or "").lower()
    return [c for c in ids if q in c.lower()][:5] or ids[:5]


# ------------------------------------------------------------------ cases
@app.route("/api/cases")
def api_cases():
    out = []
    for cid in store.case_ids():
        s = case_summary(cid)
        if s:
            out.append(s)
    out.sort(key=lambda c: c["date"], reverse=True)
    return jsonify({"cases": out, "count": len(out)})


@app.route("/api/cases/<case_id>")
def api_case_detail(case_id):
    s = case_summary(case_id)
    if not s:
        return jsonify({"error": "Case not found.", "did_you_mean": suggest_cases(case_id)}), 404
    return jsonify(s)


# ------------------------------------------------------------------ investigation
@app.route("/api/investigation/<case_id>")
def api_investigation(case_id):
    hops = int(request.args.get("hops", DEFAULT_HOPS))
    hops = max(1, min(4, hops))
    cid = normalize_case_id(case_id)
    if not cid:
        return jsonify({"error": f'Case "{case_id}" not found.',
                         "did_you_mean": suggest_cases(case_id)}), 404

    fir = store.get_fir(cid)
    if not fir:
        return jsonify({"error": f'Case "{case_id}" not found.',
                         "did_you_mean": suggest_cases(case_id)}), 404

    sub = graph_index.case_subgraph(cid, hops=hops)
    if not sub:
        return jsonify({"error": f'Case graph for "{case_id}" could not be generated.',
                         "did_you_mean": suggest_cases(case_id)}), 404

    scores = graph_index.relevance_scores(cid, sub)
    related = graph_index.related_cases(cid)
    
    # scope alerts to entities present in this subgraph or tagged to this case
    all_alerts = graph_index.alerts()
    node_labels = {graph_index.G.nodes[n]["label"] for n in sub["node_ids"]}
    scoped_alerts = [a for a in all_alerts if cid in a.get("detail", "") or (set(a.get("entities", [])) & node_labels)]

    nodes = []
    for n in sub["node_ids"]:
        d = graph_index.G.nodes[n]
        nodes.append({"id": n, "type": d["type"], "label": d["label"], "hop": sub["hop_of"][n]})
    edges = []
    for i, (u, v, k, d) in enumerate(sub["edges"]):
        edges.append({"id": f"e{i}", "source": u, "target": v, "type": d["type"],
                       "evidence": d.get("evidence", ""), "source_file": d.get("source", "")})

    persons_total = sum(1 for n in sub["node_ids"] if graph_index.G.nodes[n]["type"] == "PERSON")
    financial_links = sum(1 for _, _, _, d in sub["edges"] if d["type"] == "TRANSFERRED_TO")
    comm_links = sum(1 for _, _, _, d in sub["edges"] if d["type"] == "CALLED")

    audit.log("investigator", "CASE_INVESTIGATED", cid, {"hops": hops, "entities": len(nodes)})

    return jsonify({
        "case": case_summary(cid),
        "hops": hops,
        "summary": {
            "entities": len(nodes) - 1,
            "persons": persons_total,
            "relationships": len(edges),
            "related_cases": len(related),
            "financial_links": financial_links,
            "communication_links": comm_links,
            "high_priority_entities": sum(1 for s in scores if s["priority"] == "HIGH"),
        },
        "graph": {"nodes": nodes, "edges": edges},
        "key_entities": scores[:20],
        "related_cases": related,
        "alerts": scoped_alerts,
    })


@app.route("/api/investigation/<case_id>/graph")
def api_investigation_graph(case_id):
    hops = int(request.args.get("hops", DEFAULT_HOPS))
    hops = max(1, min(4, hops))
    cid = normalize_case_id(case_id)
    if not cid:
        return jsonify({"error": "Case not found.", "did_you_mean": suggest_cases(case_id)}), 404
    sub = graph_index.case_subgraph(cid, hops=hops)
    if not sub:
        return jsonify({"error": "Case not found.", "did_you_mean": suggest_cases(case_id)}), 404
    nodes = [{"id": n, "type": graph_index.G.nodes[n]["type"], "label": graph_index.G.nodes[n]["label"],
              "hop": sub["hop_of"][n]} for n in sub["node_ids"]]
    edges = [{"source": u, "target": v, "type": d["type"], "evidence": d.get("evidence", "")}
              for u, v, k, d in sub["edges"]]
    return jsonify({"nodes": nodes, "edges": edges})


@app.route("/api/investigation/<case_id>/entities")
def api_investigation_entities(case_id):
    hops = int(request.args.get("hops", DEFAULT_HOPS))
    hops = max(1, min(4, hops))
    cid = normalize_case_id(case_id)
    if not cid:
        return jsonify({"error": "Case not found.", "did_you_mean": suggest_cases(case_id)}), 404
    sub = graph_index.case_subgraph(cid, hops=hops)
    if not sub:
        return jsonify({"error": "Case not found.", "did_you_mean": suggest_cases(case_id)}), 404
    return jsonify({"entities": graph_index.relevance_scores(cid, sub)})


@app.route("/api/investigation/<case_id>/related-cases")
def api_related_cases(case_id):
    cid = normalize_case_id(case_id)
    if not cid or not store.get_fir(cid):
        return jsonify({"error": "Case not found.", "did_you_mean": suggest_cases(case_id)}), 404
    return jsonify({"related_cases": graph_index.related_cases(cid)})


# ------------------------------------------------------------------ person & phone investigation
@app.route("/api/person/<path:person_id>")
def api_person_investigation(person_id):
    hops = int(request.args.get("hops", 1))
    d = graph_index.person_subgraph(person_id, hops=hops)
    if not d:
        return jsonify({"error": f"Person '{person_id}' not found."}), 404
    audit.log("investigator", "PERSON_INVESTIGATED", person_id, {"name": d["name"]})
    return jsonify(d)


@app.route("/api/phone/<path:phone_number>")
def api_phone_investigation(phone_number):
    hops = int(request.args.get("hops", 1))
    d = graph_index.phone_subgraph(phone_number, hops=hops)
    if not d:
        return jsonify({"error": f"Phone '{phone_number}' not found."}), 404
    audit.log("investigator", "PHONE_INVESTIGATED", phone_number, {})
    return jsonify(d)


@app.route("/api/vehicle/<path:vehicle_id>")
def api_vehicle_investigation(vehicle_id):
    hops = int(request.args.get("hops", 1))
    d = graph_index.vehicle_subgraph(vehicle_id, hops=hops)
    if not d:
        return jsonify({"error": f"Vehicle '{vehicle_id}' not found."}), 404
    audit.log("investigator", "VEHICLE_INVESTIGATED", vehicle_id, {"reg": d.get("registration_number")})
    return jsonify(d)


@app.route("/api/account/<path:account_id>")
def api_account_investigation(account_id):
    hops = int(request.args.get("hops", 1))
    d = graph_index.account_subgraph(account_id, hops=hops)
    if not d:
        return jsonify({"error": f"Account '{account_id}' not found."}), 404
    audit.log("investigator", "ACCOUNT_INVESTIGATED", account_id, {})
    return jsonify(d)


# ------------------------------------------------------------------ shortest path & dynamic expansion
@app.route("/api/path")
def api_find_path():
    src = request.args.get("from") or request.args.get("source") or ""
    dst = request.args.get("to") or request.args.get("target") or ""
    if not src or not dst:
        return jsonify({"error": "Both 'from' and 'to' entity parameters are required."}), 400
    res = graph_index.find_path(src, dst)
    if not res.get("found"):
        return jsonify(res), 404
    audit.log("investigator", "PATH_FOUND", f"{src} -> {dst}", {"length": res.get("length")})
    return jsonify(res)


@app.route("/api/node-expand/<path:node_id>")
def api_node_expand(node_id):
    hops = int(request.args.get("hops", 1))
    res = graph_index.expand_node(node_id, hops=hops)
    if not res:
        return jsonify({"error": f"Node '{node_id}' not found."}), 404
    return jsonify(res)


# ------------------------------------------------------------------ timeline, compare, report
@app.route("/api/timeline/<case_id>")
def api_case_timeline(case_id):
    cid = normalize_case_id(case_id)
    if not cid or not store.get_fir(cid):
        return jsonify({"error": "Case not found.", "did_you_mean": suggest_cases(case_id)}), 404
    tl = graph_index.case_timeline(cid)
    return jsonify({"case_id": cid, "timeline": tl, "count": len(tl)})


@app.route("/api/compare")
def api_compare_cases():
    c1 = request.args.get("case1", "")
    c2 = request.args.get("case2", "")
    cmp_res = graph_index.compare_cases(c1, c2)
    if not cmp_res:
        return jsonify({"error": "Could not compare cases. Please verify both Case IDs."}), 400
    return jsonify(cmp_res)


@app.route("/api/report/<case_id>")
def api_investigation_report(case_id):
    cid = normalize_case_id(case_id)
    if not cid or not store.get_fir(cid):
        return jsonify({"error": "Case not found.", "did_you_mean": suggest_cases(case_id)}), 404
    rep = graph_index.investigation_report(cid)
    audit.log("investigator", "REPORT_GENERATED", cid, {"report_id": rep["report_id"]})
    return jsonify(rep)


# ------------------------------------------------------------------ entities
@app.route("/api/entities/<path:entity_id>")
def api_entity(entity_id):
    d = graph_index.entity_detail(entity_id)
    if not d:
        return jsonify({"error": "Entity not found."}), 404
    return jsonify(d)


@app.route("/api/entities/<path:entity_id>/connections")
def api_entity_connections(entity_id):
    d = graph_index.entity_detail(entity_id)
    if not d:
        return jsonify({"error": "Entity not found."}), 404
    return jsonify({"connections": d["connections"]})


# ------------------------------------------------------------------ search
@app.route("/api/search")
def api_search():
    q = request.args.get("q", "")
    return jsonify(graph_index.search(q))


# ------------------------------------------------------------------ data quality
@app.route("/api/data-quality")
def api_data_quality():
    return jsonify(store.data_quality_audit())


# ------------------------------------------------------------------ alerts
@app.route("/api/alerts")
def api_alerts():
    return jsonify({"alerts": graph_index.alerts()})


@app.route("/api/alerts/<alert_id>/status", methods=["POST"])
def api_alert_status(alert_id):
    body = request.get_json(silent=True) or {}
    status = body.get("status", "Open")
    notes = body.get("notes", "")
    valid_statuses = ["Open", "Investigating", "Dismissed", "Resolved"]
    if status not in valid_statuses:
        return jsonify({"error": f"Invalid status '{status}'. Must be one of {valid_statuses}."}), 400
    res = graph_index.update_alert_status(alert_id, status, notes)
    audit.log("investigator", "ALERT_STATUS_UPDATED", alert_id, {"new_status": status})
    return jsonify(res)


# ------------------------------------------------------------------ cross-case
@app.route("/api/cross-case")
def api_cross_case():
    out = {}
    for cid in store.case_ids():
        rel = graph_index.related_cases(cid)
        if rel:
            out[cid] = rel
    return jsonify({"cross_case_links": out})


# ------------------------------------------------------------------ global analytics (secondary, advanced)
@app.route("/api/analytics/global")
def api_global_analytics():
    return jsonify(graph_index.global_analytics())


@app.route("/api/analytics/disruption/<path:entity_id>")
def api_disruption(entity_id):
    res = graph_index.simulate_removal(entity_id)
    if not res:
        return jsonify({"error": "Entity not found in person network."}), 404
    return jsonify(res)


@app.route("/api/analytics/persons")
def api_persons_list():
    return jsonify({"persons": [{"entity_id": "PERSON:" + normalize_id(p["person_id"]),
                                   "person_id": p["person_id"], "name": p["name"]}
                                  for p in store.tables["persons"]]})


# ------------------------------------------------------------------ audit
@app.route("/api/audit")
def api_audit():
    return jsonify({"ledger": audit.all_entries()})


@app.route("/api/audit/verify")
def api_audit_verify():
    return jsonify(audit.verify())


# ------------------------------------------------------------------ data sources status
@app.route("/api/data-sources")
def api_data_sources():
    from data_store import FILES
    out = []
    for key, fname in FILES.items():
        out.append({"name": key.upper(), "file": fname, "records": len(store.tables[key]), "loaded": True})
    return jsonify({"sources": out})


# ------------------------------------------------------------------ ingestion
@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    if "file" not in request.files:
        return jsonify({"ok": False, "errors": ["No file uploaded."]}), 400
    f = request.files["file"]
    doctype = request.form.get("doctype", "")
    case_id_hint = request.form.get("case_id", "")
    raw = f.read()
    result = ingestion.process_upload(store, graph_index, doctype, f.filename, raw, case_id_hint)
    audit.log("admin", "DATA_INGESTED", f.filename,
              {"doctype": doctype, "case_id": case_id_hint, "records_added": result.get("records_added", 0)})
    status = 200 if result.get("records_added", 0) > 0 else 400
    return jsonify(result), status


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "cases": len(store.case_ids()),
                     "nodes": graph_index.G.number_of_nodes(), "edges": graph_index.G.number_of_edges()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=4173, debug=False)
