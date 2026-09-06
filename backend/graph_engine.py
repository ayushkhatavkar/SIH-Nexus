"""
NEXUS graph engine.

Builds ONE master knowledge graph (networkx MultiDiGraph) from the store,
then answers both case-specific and global investigative questions:

  1. Case-specific: "who/what is connected to FIR-0170-2026, and why?"
     -> case_subgraph() + relevance_scores() + related_cases() + case_timeline()
  2. Person-specific: person_subgraph() -> complete person dossier & ego-graph
  3. Phone-specific: phone_subgraph() -> phone history, calls & ego-graph
  4. Comparison: compare_cases() -> shared entities matrix
  5. Executive Brief: investigation_report() -> comprehensive report
  6. Global: global_analytics(), simulate_removal() -> Advanced Analytics

Every edge carries a `source` / `evidence` field so any relationship can
answer "why are these connected?" with a pointer back to real records.
"""
import hashlib
from collections import defaultdict, Counter
from datetime import datetime

import networkx as nx

from normalize import normalize_case_id, normalize_phone, normalize_id


def build_graph(store):
    G = nx.MultiDiGraph()

    def add_node(nid, ntype, label, **attrs):
        if nid not in G:
            G.add_node(nid, type=ntype, label=label, **attrs)
        else:
            G.nodes[nid]["type"] = ntype
            G.nodes[nid]["label"] = label
            G.nodes[nid].update({k: v for k, v in attrs.items() if v not in (None, "")})

    def add_edge(a, b, etype, **attrs):
        G.add_edge(a, b, key=etype, type=etype, **attrs)

    # ---- telecom records (SIM / phone ownership & case tags)
    for t in store.tables["telecom"]:
        ph = normalize_phone(t.get("phone_number"))
        if not ph:
            continue
        phn = "PHONE:" + ph
        add_node(phn, "PHONE", ph, operator=t.get("operator", ""),
                 activation_date=t.get("activation_date", ""),
                 address=t.get("address", ""), subscriber_name=t.get("subscriber_name", ""))
        pid_raw = t.get("person_id")
        if pid_raw:
            pnode = "PERSON:" + normalize_id(pid_raw)
            add_edge(pnode, phn, "REGISTERED_TO", source="telecom.csv",
                     evidence=f"SIM registered to {t.get('subscriber_name', pid_raw)} ({t.get('operator','')})")
        for cid in (t.get("case_ids") or "").split("|"):
            if cid:
                norm_cid = normalize_case_id(cid)
                if norm_cid:
                    cnode = "CASE:" + norm_cid
                    add_edge(phn, cnode, "LINKED_TO_CASE", source="telecom.csv",
                             evidence=f"Phone {ph} registered in subscriber record for {norm_cid}")

    # ---- persons
    for p in store.tables["persons"]:
        pid = "PERSON:" + normalize_id(p["person_id"])
        add_node(pid, "PERSON", p["name"], person_id=p["person_id"], aliases=p.get("aliases", ""),
                 age_range=p.get("age_range", ""), occupation=p.get("occupation", ""),
                 address=p.get("addresses", ""), case_ids=p.get("case_ids", ""))
        ph = normalize_phone(p.get("phone_numbers"))
        if ph:
            phn = "PHONE:" + ph
            add_node(phn, "PHONE", ph)
            add_edge(pid, phn, "USES", source="persons.csv", evidence=f"Phone used by {p['name']}")
        acc = p.get("primary_account")
        if acc:
            an = "ACCOUNT:" + normalize_id(acc)
            add_node(an, "BANK_ACCOUNT", acc)
            add_edge(pid, an, "OWNS", source="persons.csv", evidence=f"Primary bank account of {p['name']}")

    # ---- cases (FIR)
    for f in store.tables["fir"]:
        cid = normalize_case_id(f.get("case_id")) or f.get("case_id")
        if not cid:
            continue
        cnode = "CASE:" + cid
        add_node(cnode, "CASE", cid, case_id=cid, police_station=f.get("police_station", ""),
                 district=f.get("district", ""), state=f.get("state", ""), date=f.get("date", ""),
                 status=f.get("status", ""), sections=f.get("sections_of_law", ""),
                 complainant=f.get("complainant", ""), description=f.get("description", ""))

        for pid_raw in (f.get("accused_person_ids") or "").split("|"):
            if not pid_raw:
                continue
            pnode = "PERSON:" + normalize_id(pid_raw)
            add_edge(pnode, cnode, "ACCUSED_IN", source=cid, evidence=f"Named as accused in {cid}")

        for veh_raw in (f.get("vehicle_ids") or "").split("|"):
            if not veh_raw:
                continue
            vnode = "VEHICLE:" + normalize_id(veh_raw)
            add_edge(vnode, cnode, "LINKED_TO_CASE", source=cid, evidence=f"Vehicle listed in {cid}")

        for ph_raw in (f.get("phone_numbers") or "").split("|"):
            if not ph_raw:
                continue
            ph = normalize_phone(ph_raw)
            if ph:
                phn = "PHONE:" + ph
                add_node(phn, "PHONE", ph)
                add_edge(phn, cnode, "EVIDENCE_IN_CASE", source=cid, evidence=f"Phone listed in FIR {cid}")

        for acc_raw in (f.get("account_ids") or "").split("|"):
            if not acc_raw:
                continue
            an = "ACCOUNT:" + normalize_id(acc_raw)
            add_node(an, "BANK_ACCOUNT", normalize_id(acc_raw))
            add_edge(an, cnode, "EVIDENCE_IN_CASE", source=cid, evidence=f"Bank account listed in FIR {cid}")

    # ---- vehicles
    for v in store.tables["vehicles"]:
        vid = "VEHICLE:" + normalize_id(v["vehicle_id"])
        add_node(vid, "VEHICLE", v["registration_number"], vehicle_id=v["vehicle_id"],
                 registration_number=v.get("registration_number", ""),
                 vehicle_type=v.get("vehicle_type", ""), location=v.get("location", ""))
        owner = v.get("owner_person_id")
        if owner:
            add_edge("PERSON:" + normalize_id(owner), vid, "OWNS_VEHICLE", source="vehicles.csv",
                     evidence=f"Owner of vehicle {v['registration_number']}")
        for cid in (v.get("case_ids") or "").split("|"):
            if cid:
                norm_cid = normalize_case_id(cid)
                if norm_cid:
                    cnode = "CASE:" + norm_cid
                    add_edge(vid, cnode, "LINKED_TO_CASE", source="vehicles.csv",
                             evidence=f"Vehicle {v['registration_number']} linked to {norm_cid}")

    # ---- CDR (aggregated phone-phone calls & case linking)
    call_agg = defaultdict(lambda: {"n": 0, "sec": 0, "cases": set(), "ids": []})
    for r in store.tables["cdr"]:
        a, b = normalize_phone(r["caller_phone"]), normalize_phone(r["receiver_phone"])
        if not a or not b:
            continue
        k = tuple(sorted([a, b]))
        agg = call_agg[k]
        agg["n"] += 1
        agg["sec"] += int(r.get("duration_seconds") or 0)
        norm_c = normalize_case_id(r.get("case_id"))
        if norm_c:
            agg["cases"].add(norm_c)
            # connect phones directly to the case tagged in CDR
            cnode = "CASE:" + norm_c
            add_edge("PHONE:" + a, cnode, "TAGGED_IN_CASE", source="cdr.csv",
                     evidence=f"Caller phone in CDR tagged to {norm_c}")
            add_edge("PHONE:" + b, cnode, "TAGGED_IN_CASE", source="cdr.csv",
                     evidence=f"Receiver phone in CDR tagged to {norm_c}")
        agg["ids"].append(r["cdr_id"])

    for (a, b), agg in call_agg.items():
        pa, pb = "PHONE:" + a, "PHONE:" + b
        add_node(pa, "PHONE", a)
        add_node(pb, "PHONE", b)
        add_edge(pa, pb, "CALLED", count=agg["n"], total_sec=agg["sec"],
                 cases="|".join(sorted(agg["cases"])), source="cdr.csv",
                 evidence=f"{agg['n']} call(s) ({agg['sec']}s total), e.g. record {agg['ids'][0]}")

    # ---- bank transactions (account-account & case linking)
    txn_agg = defaultdict(lambda: {"n": 0, "amt": 0, "cases": set(), "ids": []})
    for r in store.tables["bank"]:
        sa, ra = normalize_id(r["sender_account"]), normalize_id(r["receiver_account"])
        if not sa or not ra:
            continue
        k = (sa, ra)
        agg = txn_agg[k]
        agg["n"] += 1
        agg["amt"] += int(float(r.get("amount") or 0))
        norm_c = normalize_case_id(r.get("case_id"))
        if norm_c:
            agg["cases"].add(norm_c)
            cnode = "CASE:" + norm_c
            add_edge("ACCOUNT:" + sa, cnode, "TAGGED_IN_CASE", source="bank_transactions.csv",
                     evidence=f"Sender account in transaction tagged to {norm_c}")
            add_edge("ACCOUNT:" + ra, cnode, "TAGGED_IN_CASE", source="bank_transactions.csv",
                     evidence=f"Receiver account in transaction tagged to {norm_c}")
        agg["ids"].append(r["transaction_id"])

    for (sa, ra), agg in txn_agg.items():
        an, bn = "ACCOUNT:" + sa, "ACCOUNT:" + ra
        add_node(an, "BANK_ACCOUNT", sa)
        add_node(bn, "BANK_ACCOUNT", ra)
        add_edge(an, bn, "TRANSFERRED_TO", count=agg["n"], total_amount=agg["amt"],
                 cases="|".join(sorted(agg["cases"])), source="bank_transactions.csv",
                 evidence=f"{agg['n']} transaction(s) totalling Rs {agg['amt']:,}, e.g. {agg['ids'][0]}")

    # ---- social (person-person)
    for r in store.tables["social"]:
        a, b = normalize_id(r["source_person_id"]), normalize_id(r["target_person_id"])
        if not a or not b:
            continue
        pa, pb = "PERSON:" + a, "PERSON:" + b
        if pa in G and pb in G:
            add_edge(pa, pb, "ASSOCIATED_WITH", platform=r.get("platform", ""),
                     relationship_type=r.get("relationship_type", ""),
                     confidence=r.get("confidence", ""), source="social_connections.csv",
                     evidence=f"{r.get('relationship_type','associated')} on {r.get('platform','social media')}",
                     case_id=r.get("case_id", ""))

    return G


class GraphIndex:
    """Holds the built graph plus a cached undirected person-projection for analytics."""
    def __init__(self, store):
        self.store = store
        self.rebuild()

    def rebuild(self):
        self.G = build_graph(self.store)
        self.P = self._person_projection()

    def _person_projection(self):
        P = nx.Graph()
        persons = [n for n, d in self.G.nodes(data=True) if d["type"] == "PERSON"]
        P.add_nodes_from(persons)

        # direct person-person (social) edges
        for u, v, d in self.G.edges(data=True):
            if d["type"] == "ASSOCIATED_WITH" and u in P and v in P:
                if P.has_edge(u, v):
                    P[u][v]["weight"] += 1.0
                else:
                    P.add_edge(u, v, weight=1.0)

        # shared-intermediary edges (phone/account/vehicle/case co-membership)
        for mid_type in ("PHONE", "BANK_ACCOUNT", "VEHICLE", "CASE"):
            buckets = defaultdict(set)
            for n, d in self.G.nodes(data=True):
                if d["type"] != mid_type:
                    continue
                for nb in set(self.G.predecessors(n)) | set(self.G.successors(n)):
                    if nb in self.G and self.G.nodes[nb]["type"] == "PERSON":
                        buckets[n].add(nb)
            for mid, ppl in buckets.items():
                ppl = list(ppl)
                for i in range(len(ppl)):
                    for j in range(i + 1, len(ppl)):
                        a, b = ppl[i], ppl[j]
                        w = 2.0 if mid_type == "CASE" else 1.0
                        if P.has_edge(a, b):
                            P[a][b]["weight"] += w
                        else:
                            P.add_edge(a, b, weight=w)
        return P

    # ------------------------------------------------------------ case subgraph
    def case_subgraph(self, case_id, hops=2):
        cid = normalize_case_id(case_id)
        if not cid:
            return None
        cnode = "CASE:" + cid
        if cnode not in self.G:
            return None
        UG = self.G.to_undirected(as_view=True)
        visited = {cnode: 0}
        frontier = [cnode]
        for h in range(1, hops + 1):
            nxt = []
            for n in frontier:
                for nb in UG.neighbors(n):
                    if nb not in visited:
                        visited[nb] = h
                        nxt.append(nb)
            frontier = nxt
            if not frontier:
                break
        nodes = set(visited.keys())
        edges = []
        for u, v, k, d in self.G.edges(keys=True, data=True):
            if u in nodes and v in nodes:
                edges.append((u, v, k, d))
        return {"case_id": cid, "node_ids": nodes, "hop_of": visited, "edges": edges}

    # ------------------------------------------------------------ relevance scoring
    def relevance_scores(self, case_id, sub):
        """Case-specific, explainable relevance score for every PERSON in the subgraph."""
        if not sub:
            return []
        cid = sub["case_id"]
        cnode = "CASE:" + cid
        nodes = sub["node_ids"]
        hop_of = sub["hop_of"]
        persons = [n for n in nodes if self.G.nodes[n]["type"] == "PERSON"]

        # precompute per-person signal counts within the subgraph
        edge_types_touching = defaultdict(set)
        comm_count = Counter()
        fin_count = Counter()
        veh_count = Counter()
        for u, v, k, d in sub["edges"]:
            for side in (u, v):
                if side in persons:
                    edge_types_touching[side].add(d["type"])
            if d["type"] == "CALLED":
                for side in (u, v):
                    ph_owner = self._owner_of_phone(side)
                    if ph_owner:
                        comm_count[ph_owner] += d.get("count", 1)
            if d["type"] == "TRANSFERRED_TO":
                for side in (u, v):
                    acc_owner = self._owner_of_account(side)
                    if acc_owner:
                        fin_count[acc_owner] += 1
            if d["type"] == "OWNS_VEHICLE":
                if u in persons:
                    veh_count[u] += 1

        degrees = {p: len(list(self.G.to_undirected(as_view=True).neighbors(p))) for p in persons}
        max_deg = max(degrees.values()) if degrees else 1

        results = []
        for p in persons:
            is_accused = 1 if self.G.has_edge(p, cnode, "ACCUSED_IN") else 0
            case_ids = set((self.G.nodes[p].get("case_ids") or "").split("|")) - {""}
            cross_case = len(case_ids - {cid})
            comm = comm_count.get(p, 0)
            fin = fin_count.get(p, 0)
            veh = veh_count.get(p, 0)
            n_sources = len(edge_types_touching.get(p, set()))
            centrality = degrees[p] / max_deg if max_deg else 0
            proximity = 1.0 / (1 + hop_of.get(p, hops_fallback(hop_of)))

            # Deterministic 100-point breakdown
            direct_pts = 25 if is_accused else 0
            cross_pts = min(20, cross_case * 10)
            comm_pts = min(20, comm * 5)
            fin_pts = min(15, fin * 5)
            src_pts = 10 if n_sources >= 3 else (5 if n_sources >= 2 else 0)
            cent_pts = int(round(centrality * 10))
            score_100 = min(100, direct_pts + cross_pts + comm_pts + fin_pts + src_pts + cent_pts)

            comm_n = min(1.0, comm / 6.0)
            fin_n = min(1.0, fin / 3.0)
            cross_n = min(1.0, cross_case / 2.0)
            src_n = min(1.0, n_sources / 4.0)

            score_float = round(score_100 / 100.0, 2)

            reasons = []
            if is_accused:
                reasons.append(f"Directly named as accused in {cid} (+{direct_pts} pts)")
            if cross_case:
                reasons.append(f"Appears in {cross_case} other case(s): {', '.join(sorted(case_ids - {cid}))} (+{cross_pts} pts)")
            if comm:
                reasons.append(f"{comm} communication link(s) (calls) with case-connected phones (+{comm_pts} pts)")
            if fin:
                reasons.append(f"{fin} financial transaction(s) with case-connected accounts (+{fin_pts} pts)")
            if veh:
                reasons.append(f"Owns {veh} vehicle(s) linked to this investigation")
            if src_pts:
                reasons.append(f"Multi-source corroboration across {n_sources} data categories (+{src_pts} pts)")
            if not reasons:
                reasons.append(f"Reached within {hop_of.get(p,'?')} hop(s) of {cid} through network connections")

            priority = "HIGH" if score_100 >= 60 else "MEDIUM" if score_100 >= 35 else "LOW"

            results.append({
                "entity_id": p, "person_id": self.G.nodes[p].get("person_id", p.replace("PERSON:", "")),
                "name": self.G.nodes[p]["label"],
                "relevance_score": score_float,
                "score_100": score_100,
                "priority": priority, "hop": hop_of.get(p, None),
                "reasons": reasons,
                "point_breakdown": {
                    "direct_case_connection": direct_pts,
                    "cross_case_connections": cross_pts,
                    "communication_links": comm_pts,
                    "financial_links": fin_pts,
                    "multi_source_evidence": src_pts,
                    "network_centrality": cent_pts,
                    "total_points": score_100
                },
                "components": {
                    "direct_case_connection": is_accused, "communication_links": round(comm_n, 2),
                    "financial_links": round(fin_n, 2), "cross_case_connections": round(cross_n, 2),
                    "multi_source_evidence": round(src_n, 2), "graph_centrality": round(centrality, 2),
                    "proximity": round(proximity, 2),
                },
            })
        results.sort(key=lambda r: -r["score_100"])
        return results

    def _owner_of_phone(self, phone_node):
        for pred in self.G.predecessors(phone_node):
            if self.G.nodes[pred]["type"] == "PERSON":
                return pred
        return None

    def _owner_of_account(self, account_node):
        for pred in self.G.predecessors(account_node):
            if self.G.nodes[pred]["type"] == "PERSON":
                return pred
        return None

    # ------------------------------------------------------------ related cases
    def related_cases(self, case_id):
        cid = normalize_case_id(case_id)
        if not cid:
            return []
        cnode = "CASE:" + cid
        if cnode not in self.G:
            return []
        directly_linked = set(self.G.predecessors(cnode))
        related = defaultdict(list)

        for ent in directly_linked:
            etype = self.G.nodes[ent]["type"]
            label = self.G.nodes[ent]["label"]
            type_title = etype.replace("_", " ").title()

            # Follow outgoing edges from directly linked entities to other cases
            for succ in self.G.successors(ent):
                if succ != cnode and self.G.nodes[succ]["type"] == "CASE":
                    other = self.G.nodes[succ]["case_id"]
                    related[other].append({
                        "shared_entity_type": etype, "shared_entity": label,
                        "connection_type": f"Shared {type_title}",
                        "reason": f"Shared {type_title}: {label}",
                    })

            # Check multi-case metadata for persons
            if etype == "PERSON":
                case_ids = set((self.G.nodes[ent].get("case_ids") or "").split("|")) - {"", cid}
                for other in case_ids:
                    related[other].append({
                        "shared_entity_type": "PERSON", "shared_entity": label,
                        "connection_type": "Shared Person",
                        "reason": f"Shared Person: {label}",
                    })

            # Check multi-case metadata for vehicles
            elif etype == "VEHICLE":
                v_cases = set((self.G.nodes[ent].get("case_ids") or "").split("|")) - {"", cid}
                for other in v_cases:
                    related[other].append({
                        "shared_entity_type": "VEHICLE", "shared_entity": label,
                        "connection_type": "Shared Vehicle",
                        "reason": f"Shared Vehicle: {label}",
                    })

        out = []
        for other, reasons in related.items():
            seen = set()
            deduped = []
            for r in reasons:
                key = (r["shared_entity_type"], r["shared_entity"])
                if key not in seen:
                    seen.add(key)
                    deduped.append(r)
            # categorize primary connection type
            types_present = {r["shared_entity_type"] for r in deduped}
            primary_conn = "Shared Person" if "PERSON" in types_present else (
                "Shared Phone" if "PHONE" in types_present else (
                    "Shared Vehicle" if "VEHICLE" in types_present else "Shared Account"
                )
            )
            out.append({
                "case_id": other,
                "shared_count": len(deduped),
                "primary_connection": primary_conn,
                "reasons": deduped[:6]
            })
        out.sort(key=lambda r: -r["shared_count"])
        return out

    # ------------------------------------------------------------ person investigation
    def person_subgraph(self, person_id, hops=1):
        pid = normalize_id(person_id)
        pnode = "PERSON:" + pid
        p_row = self.store.find_person(pid)
        if not p_row and pnode in self.G:
            p_row = {
                "person_id": pid, "name": self.G.nodes[pnode].get("label", pid),
                "aliases": self.G.nodes[pnode].get("aliases", ""),
                "occupation": self.G.nodes[pnode].get("occupation", ""),
                "age_range": self.G.nodes[pnode].get("age_range", ""),
                "addresses": self.G.nodes[pnode].get("address", ""),
                "phone_numbers": "", "primary_account": "",
                "case_ids": self.G.nodes[pnode].get("case_ids", "")
            }
        if not p_row:
            return None

        # Build ego-network around this person
        UG = self.G.to_undirected(as_view=True)
        visited = {pnode: 0}
        frontier = [pnode]
        for h in range(1, hops + 1):
            nxt = []
            for n in frontier:
                for nb in UG.neighbors(n):
                    if nb not in visited:
                        visited[nb] = h
                        nxt.append(nb)
            frontier = nxt

        sub_nodes = set(visited.keys())
        nodes_out = []
        for n in sub_nodes:
            d = self.G.nodes[n]
            nodes_out.append({"id": n, "type": d["type"], "label": d["label"], "hop": visited[n]})

        edges_out = []
        for i, (u, v, k, d) in enumerate(self.G.edges(keys=True, data=True)):
            if u in sub_nodes and v in sub_nodes:
                edges_out.append({"id": f"pe{i}", "source": u, "target": v, "type": d["type"],
                                  "evidence": d.get("evidence", ""), "source_file": d.get("source", "")})

        # Identify specific entities tied to this person
        cases_involved = set((p_row.get("case_ids") or "").split("|")) - {""}
        for succ in self.G.successors(pnode):
            if self.G.nodes[succ]["type"] == "CASE":
                cases_involved.add(self.G.nodes[succ]["case_id"])
        for pred in self.G.predecessors(pnode):
            if self.G.nodes[pred]["type"] == "CASE":
                cases_involved.add(self.G.nodes[pred]["case_id"])

        phones = []
        vehicles = []
        accounts = []
        connected_people = []

        for succ in self.G.successors(pnode):
            t = self.G.nodes[succ]["type"]
            lbl = self.G.nodes[succ]["label"]
            if t == "PHONE":
                phones.append({"phone": lbl, "details": self.G.nodes[succ]})
            elif t == "VEHICLE":
                vehicles.append({"registration": lbl, "details": self.G.nodes[succ]})
            elif t == "BANK_ACCOUNT":
                accounts.append({"account": lbl, "details": self.G.nodes[succ]})
            elif t == "PERSON" and succ != pnode:
                connected_people.append({"entity_id": succ, "name": lbl, "connection": "Associated"})

        # Collect incoming connections as well
        for pred in self.G.predecessors(pnode):
            t = self.G.nodes[pred]["type"]
            lbl = self.G.nodes[pred]["label"]
            if t == "PERSON" and pred != pnode and not any(cp["entity_id"] == pred for cp in connected_people):
                connected_people.append({"entity_id": pred, "name": lbl, "connection": "Associated"})

        # Determine network position from person projection P
        deg = self.P.degree(pnode) if pnode in self.P else 0
        is_artic = pnode in nx.articulation_points(self.P) if self.P.number_of_edges() and pnode in self.P else False

        why_relevant = []
        if len(cases_involved) > 1:
            why_relevant.append(f"Multi-case entity: involved in {len(cases_involved)} distinct FIR investigations")
        elif cases_involved:
            why_relevant.append(f"Accused / named in case {list(cases_involved)[0]}")
        if is_artic:
            why_relevant.append("Network bridge: links separate groups within the criminal network")
        if len(phones) > 1:
            why_relevant.append(f"Uses or is linked to {len(phones)} phone numbers")
        if accounts:
            why_relevant.append(f"Linked to {len(accounts)} tracked bank account(s)")
        if not why_relevant:
            why_relevant.append("Connected to active case entities in the knowledge graph")

        return {
            "person_id": p_row["person_id"],
            "name": p_row["name"],
            "aliases": p_row.get("aliases", ""),
            "age_range": p_row.get("age_range", "—"),
            "occupation": p_row.get("occupation", "—"),
            "address": p_row.get("addresses", "—"),
            "case_involvement": sorted(cases_involved),
            "phones": phones,
            "vehicles": vehicles,
            "accounts": accounts,
            "connected_people": connected_people,
            "network_degree": deg,
            "is_bridge": is_artic,
            "why_relevant": why_relevant,
            "graph": {"nodes": nodes_out, "edges": edges_out},
        }

    # ------------------------------------------------------------ phone investigation
    def phone_subgraph(self, phone_number, hops=1):
        ph = normalize_phone(phone_number)
        if not ph:
            return None
        phn = "PHONE:" + ph
        if phn not in self.G:
            return None

        # Find owner / subscriber
        owner = self._owner_of_phone(phn)
        owner_data = None
        if owner:
            owner_data = {
                "entity_id": owner,
                "person_id": self.G.nodes[owner].get("person_id", ""),
                "name": self.G.nodes[owner]["label"],
                "occupation": self.G.nodes[owner].get("occupation", "—"),
            }

        # Find associated cases
        related_cases = set()
        for succ in self.G.successors(phn):
            if self.G.nodes[succ]["type"] == "CASE":
                related_cases.add(self.G.nodes[succ]["case_id"])
        for pred in self.G.predecessors(phn):
            if self.G.nodes[pred]["type"] == "CASE":
                related_cases.add(self.G.nodes[pred]["case_id"])

        # Call connections
        call_connections = []
        connected_people = []
        seen_contacts = set()

        for _, v, d in self.G.out_edges(phn, data=True):
            if d["type"] == "CALLED" and self.G.nodes[v]["type"] == "PHONE":
                cph = self.G.nodes[v]["label"]
                contact_owner = self._owner_of_phone(v)
                c_owner_name = self.G.nodes[contact_owner]["label"] if contact_owner else "Unregistered"
                if cph not in seen_contacts:
                    seen_contacts.add(cph)
                    call_connections.append({
                        "phone": cph, "calls": d.get("count", 1),
                        "duration_sec": d.get("total_sec", 0),
                        "owner_name": c_owner_name, "owner_id": contact_owner,
                        "cases": d.get("cases", "")
                    })
                    if contact_owner and contact_owner != owner:
                        connected_people.append({"entity_id": contact_owner, "name": c_owner_name, "phone": cph})

        for u, _, d in self.G.in_edges(phn, data=True):
            if d["type"] == "CALLED" and self.G.nodes[u]["type"] == "PHONE":
                cph = self.G.nodes[u]["label"]
                contact_owner = self._owner_of_phone(u)
                c_owner_name = self.G.nodes[contact_owner]["label"] if contact_owner else "Unregistered"
                if cph not in seen_contacts:
                    seen_contacts.add(cph)
                    call_connections.append({
                        "phone": cph, "calls": d.get("count", 1),
                        "duration_sec": d.get("total_sec", 0),
                        "owner_name": c_owner_name, "owner_id": contact_owner,
                        "cases": d.get("cases", "")
                    })
                    if contact_owner and contact_owner != owner:
                        connected_people.append({"entity_id": contact_owner, "name": c_owner_name, "phone": cph})

        # Build ego-network for phone
        UG = self.G.to_undirected(as_view=True)
        visited = {phn: 0}
        frontier = [phn]
        for h in range(1, hops + 1):
            nxt = []
            for n in frontier:
                for nb in UG.neighbors(n):
                    if nb not in visited:
                        visited[nb] = h
                        nxt.append(nb)
            frontier = nxt

        sub_nodes = set(visited.keys())
        nodes_out = [{"id": n, "type": self.G.nodes[n]["type"],
                      "label": self.G.nodes[n]["label"], "hop": visited[n]} for n in sub_nodes]
        edges_out = [{"id": f"phe{i}", "source": u, "target": v, "type": d["type"],
                      "evidence": d.get("evidence", ""), "source_file": d.get("source", "")}
                     for i, (u, v, k, d) in enumerate(self.G.edges(keys=True, data=True))
                     if u in sub_nodes and v in sub_nodes]

        # Call Timeline
        call_timeline = []
        for r in self.store.tables["cdr"]:
            if normalize_phone(r.get("caller_phone")) == ph or normalize_phone(r.get("receiver_phone")) == ph:
                call_timeline.append({
                    "timestamp": r.get("timestamp", ""),
                    "caller": r.get("caller_phone", ""),
                    "receiver": r.get("receiver_phone", ""),
                    "duration": r.get("duration_seconds", 0),
                    "call_type": r.get("call_type", "voice"),
                    "tower": r.get("tower_id", ""),
                    "case_id": normalize_case_id(r.get("case_id")) or ""
                })
        call_timeline.sort(key=lambda x: x["timestamp"], reverse=True)

        why_relevant = []
        if len(related_cases) > 1:
            why_relevant.append(f"Cross-case phone: surfaces across {len(related_cases)} separate investigations: {', '.join(sorted(related_cases))}")
        elif related_cases:
            why_relevant.append(f"Directly cited in call detail records of {list(related_cases)[0]}")
        if len(call_connections) >= 3:
            why_relevant.append(f"High communication activity: {len(call_connections)} distinct contact numbers tracked")
        if owner_data:
            why_relevant.append(f"Registered subscriber: {owner_data['name']}")
        else:
            why_relevant.append("Unregistered / burner device pattern")

        return {
            "phone_number": ph,
            "operator": self.G.nodes[phn].get("operator", "—"),
            "activation_date": self.G.nodes[phn].get("activation_date", "—"),
            "address": self.G.nodes[phn].get("address", "—"),
            "owner": owner_data,
            "related_cases": sorted(related_cases),
            "call_connections": call_connections,
            "connected_people": connected_people,
            "timeline": call_timeline[:20],
            "why_relevant": why_relevant,
            "graph": {"nodes": nodes_out, "edges": edges_out}
        }

    # ------------------------------------------------------------ case timeline
    def case_timeline(self, case_id):
        cid = normalize_case_id(case_id)
        if not cid:
            return []
        fir = self.store.get_fir(cid)
        if not fir:
            return []

        events = []
        # 1. FIR Registration
        if fir.get("date"):
            events.append({
                "date": fir["date"],
                "time": "00:00:00",
                "timestamp": fir["date"] + " 00:00:00",
                "category": "FIR",
                "title": f"FIR Registered: {cid}",
                "description": f"Complaint registered at {fir.get('police_station', 'Police Station')}, {fir.get('district', '')}. Sections: {fir.get('sections_of_law', '—')}.",
                "source": "fir.csv"
            })

        # 2. Case Calls from CDR
        sub = self.case_subgraph(cid, hops=2)
        sub_phones = {self.G.nodes[n]["label"] for n in sub["node_ids"] if self.G.nodes[n]["type"] == "PHONE"} if sub else set()

        for r in self.store.tables["cdr"]:
            r_cid = normalize_case_id(r.get("case_id"))
            c_ph, r_ph = normalize_phone(r.get("caller_phone")), normalize_phone(r.get("receiver_phone"))
            if r_cid == cid or (c_ph in sub_phones and r_ph in sub_phones):
                ts = r.get("timestamp", "")
                parts = ts.split()
                d_str = parts[0] if parts else ""
                t_str = parts[1] if len(parts) > 1 else ""
                events.append({
                    "date": d_str,
                    "time": t_str,
                    "timestamp": ts,
                    "category": "CALL",
                    "title": f"Phone Call: {c_ph} -> {r_ph}",
                    "description": f"{r.get('call_type', 'Voice').title()} call duration: {r.get('duration_seconds', 0)}s at tower {r.get('tower_id', '—')}.",
                    "source": "cdr.csv"
                })

        # 3. Case Transactions from Bank
        sub_accts = {self.G.nodes[n]["label"] for n in sub["node_ids"] if self.G.nodes[n]["type"] == "BANK_ACCOUNT"} if sub else set()
        for r in self.store.tables["bank"]:
            r_cid = normalize_case_id(r.get("case_id"))
            sa, ra = normalize_id(r.get("sender_account")), normalize_id(r.get("receiver_account"))
            if r_cid == cid or (sa in sub_accts and ra in sub_accts):
                ts = r.get("timestamp", "")
                parts = ts.split()
                d_str = parts[0] if parts else ""
                t_str = parts[1] if len(parts) > 1 else ""
                events.append({
                    "date": d_str,
                    "time": t_str,
                    "timestamp": ts,
                    "category": "FINANCIAL",
                    "title": f"Bank Transfer: Rs {int(float(r.get('amount', 0))):,}",
                    "description": f"{r.get('transaction_type', 'Transfer')} from {sa} to {ra} via {r.get('bank', 'Bank')} (Ref: {r.get('reference', '—')}).",
                    "source": "bank_transactions.csv"
                })

        # 4. Social Connections
        sub_persons = {self.G.nodes[n].get("person_id") for n in sub["node_ids"] if self.G.nodes[n]["type"] == "PERSON"} if sub else set()
        for r in self.store.tables["social"]:
            r_cid = normalize_case_id(r.get("case_id"))
            sp, tp = normalize_id(r.get("source_person_id")), normalize_id(r.get("target_person_id"))
            if r_cid == cid or (sp in sub_persons and tp in sub_persons):
                ts = r.get("timestamp", "")
                events.append({
                    "date": ts,
                    "time": "00:00:00",
                    "timestamp": ts + " 00:00:00",
                    "category": "SOCIAL",
                    "title": f"Social Link: {sp} & {tp}",
                    "description": f"{r.get('relationship_type', 'Connection').replace('_', ' ').title()} on {r.get('platform', 'platform')} (Confidence: {int(float(r.get('confidence',0))*100)}%).",
                    "source": "social_connections.csv"
                })

        events.sort(key=lambda x: x["timestamp"])
        return events

    # ------------------------------------------------------------ case comparison
    def compare_cases(self, case_id_1, case_id_2):
        c1 = normalize_case_id(case_id_1)
        c2 = normalize_case_id(case_id_2)
        if not c1 or not c2:
            return None
        node1, node2 = "CASE:" + c1, "CASE:" + c2
        if node1 not in self.G or node2 not in self.G:
            return None

        fir1 = self.store.get_fir(c1)
        fir2 = self.store.get_fir(c2)

        # Predecessors of each case
        p1 = set(self.G.predecessors(node1))
        p2 = set(self.G.predecessors(node2))

        # Direct entities
        sub1 = self.case_subgraph(c1, hops=1)
        sub2 = self.case_subgraph(c2, hops=1)

        nodes_in_1 = sub1["node_ids"] - {node1}
        nodes_in_2 = sub2["node_ids"] - {node2}
        all_shared = (p1 & p2) | (nodes_in_1 & nodes_in_2)

        shared_persons = []
        shared_phones = []
        shared_vehicles = []
        shared_accounts = []

        for n in all_shared:
            t = self.G.nodes[n]["type"]
            lbl = self.G.nodes[n]["label"]
            if t == "PERSON":
                shared_persons.append({"entity_id": n, "name": lbl, "id": self.G.nodes[n].get("person_id")})
            elif t == "PHONE":
                owner = self._owner_of_phone(n)
                shared_phones.append({"phone": lbl, "owner": self.G.nodes[owner]["label"] if owner else None})
            elif t == "VEHICLE":
                shared_vehicles.append({"registration": lbl, "details": self.G.nodes[n].get("vehicle_type", "Vehicle")})
            elif t == "BANK_ACCOUNT":
                shared_accounts.append({"account": lbl})

        return {
            "case_1": {"case_id": c1, "police_station": fir1.get("police_station", "") if fir1 else "", "date": fir1.get("date", "") if fir1 else ""},
            "case_2": {"case_id": c2, "police_station": fir2.get("police_station", "") if fir2 else "", "date": fir2.get("date", "") if fir2 else ""},
            "summary": {
                "shared_persons": len(shared_persons),
                "shared_phones": len(shared_phones),
                "shared_vehicles": len(shared_vehicles),
                "shared_accounts": len(shared_accounts),
                "total_shared_entities": len(all_shared)
            },
            "shared_entities": {
                "persons": shared_persons,
                "phones": shared_phones,
                "vehicles": shared_vehicles,
                "accounts": shared_accounts
            }
        }

    # ------------------------------------------------------------ investigation report
    def investigation_report(self, case_id):
        cid = normalize_case_id(case_id)
        if not cid:
            return None
        fir = self.store.get_fir(cid)
        if not fir:
            return None

        sub = self.case_subgraph(cid, hops=2)
        relevance = self.relevance_scores(cid, sub)
        related = self.related_cases(cid)
        timeline = self.case_timeline(cid)
        node_labels = {self.G.nodes[n]["label"] for n in sub["node_ids"]}
        alerts = [a for a in self.alerts() if cid in a.get("detail", "") or set(a.get("entities", [])) & node_labels]

        high_priority = [r for r in relevance if r["priority"] == "HIGH"]
        medium_priority = [r for r in relevance if r["priority"] == "MEDIUM"]

        return {
            "report_id": f"REP-{cid}-{datetime.now().strftime('%Y%m%d%H%M')}",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "case": {
                "case_id": cid,
                "police_station": fir.get("police_station", ""),
                "district": fir.get("district", ""),
                "state": fir.get("state", ""),
                "date": fir.get("date", ""),
                "status": fir.get("status", ""),
                "sections_of_law": fir.get("sections_of_law", ""),
                "complainant": fir.get("complainant", ""),
                "description": fir.get("description", "")
            },
            "metrics": {
                "total_entities_2hop": len(sub["node_ids"]) - 1,
                "relationships_2hop": len(sub["edges"]),
                "key_leads_count": len(high_priority) + len(medium_priority),
                "related_cases_count": len(related),
                "alerts_flagged": len(alerts)
            },
            "key_investigative_leads": high_priority + medium_priority,
            "related_cases": related,
            "timeline": timeline,
            "active_alerts": alerts,
            "disclaimer": "CONFIDENTIAL INVESTIGATIVE INTELLIGENCE REPORT. This report provides network analysis and prioritization of investigative leads to support law enforcement. All relevance scores and connection maps represent objective network proximity and do not constitute legal proof of criminal guilt."
        }

    # ------------------------------------------------------------ global analytics (secondary)
    def global_analytics(self):
        P = self.P
        if P.number_of_nodes() == 0:
            return {"top_influencers": [], "communities": 0, "articulation_points": [],
                    "link_predictions": []}

        deg = nx.degree_centrality(P)
        btw = nx.betweenness_centrality(P, weight=None, normalized=True)
        pr = nx.pagerank(P, weight="weight") if P.number_of_edges() else {n: 0 for n in P.nodes()}

        try:
            close = nx.closeness_centrality(P)
        except Exception:
            close = {n: 0 for n in P.nodes()}

        try:
            eigen = nx.eigenvector_centrality(P, max_iter=1000) if P.number_of_edges() else {n: 0 for n in P.nodes()}
        except Exception:
            eigen = {n: 0 for n in P.nodes()}

        try:
            import community as community_louvain
            comm = community_louvain.best_partition(P, random_state=26189) if P.number_of_edges() else {n: 0 for n in P.nodes()}
        except Exception:
            comm = {n: 0 for n in P.nodes()}

        artic = set(nx.articulation_points(P)) if P.number_of_edges() else set()

        ranked = sorted(P.nodes(), key=lambda n: -pr.get(n, 0))
        top = []
        for n in ranked[:20]:
            top.append({
                "entity_id": n, "name": self.G.nodes[n]["label"],
                "pagerank": round(pr.get(n, 0), 4),
                "degree_centrality": round(deg.get(n, 0), 4),
                "betweenness": round(btw.get(n, 0), 4),
                "closeness": round(close.get(n, 0), 4),
                "eigenvector": round(eigen.get(n, 0), 4),
                "community": comm.get(n, 0),
                "is_articulation_point": n in artic,
            })

        # Link prediction (potential associations between non-adjacent persons)
        predictions = []
        try:
            non_edges = list(nx.non_edges(P))[:200]
            preds = nx.jaccard_coefficient(P, non_edges)
            scored_preds = sorted([(u, v, p) for u, v, p in preds if p > 0.1], key=lambda x: -x[2])[:8]
            for u, v, p in scored_preds:
                predictions.append({
                    "source": self.G.nodes[u]["label"],
                    "target": self.G.nodes[v]["label"],
                    "jaccard_score": round(p, 3),
                    "rationale": "High overlap in shared communication, financial, or case associates"
                })
        except Exception:
            pass

        return {
            "top_influencers": top,
            "communities": len(set(comm.values())),
            "articulation_points": [{"entity_id": n, "name": self.G.nodes[n]["label"]} for n in artic],
            "link_predictions": predictions
        }

    # ------------------------------------------------------------ disruption simulator
    def simulate_removal(self, entity_id):
        P = self.P
        if entity_id not in P:
            return None
        nodes = list(P.nodes())

        def components(exclude):
            pool = set(n for n in nodes if n != exclude)
            visited, comps = set(), []
            for start in pool:
                if start in visited:
                    continue
                stack, comp = [start], []
                visited.add(start)
                while stack:
                    cur = stack.pop()
                    comp.append(cur)
                    for nb in P.neighbors(cur):
                        if nb != exclude and nb in pool and nb not in visited:
                            visited.add(nb)
                            stack.append(nb)
                comps.append(comp)
            return sorted(comps, key=lambda c: -len(c))

        before = components(None)
        after = components(entity_id)
        total = len(nodes)
        frag = ((len(after) - len(before)) / total) * 100 if total else 0
        return {
            "entity_id": entity_id, "name": self.G.nodes[entity_id]["label"],
            "components_before": len(before), "components_after": len(after),
            "largest_before": len(before[0]) if before else 0,
            "largest_after": len(after[0]) if after else 0,
            "fragmentation_pct": round(frag, 1),
            "is_articulation_point": len(after) > len(before),
        }

    # ------------------------------------------------------------ entity detail
    def entity_detail(self, entity_id):
        if entity_id not in self.G:
            return None
        d = dict(self.G.nodes[entity_id])
        out_edges = [{"target": v, "target_label": self.G.nodes[v]["label"], "type": data["type"],
                       "evidence": data.get("evidence", ""), "source": data.get("source", "")}
                      for _, v, data in self.G.out_edges(entity_id, data=True)]
        in_edges = [{"source": u, "source_label": self.G.nodes[u]["label"], "type": data["type"],
                      "evidence": data.get("evidence", ""), "source_file": data.get("source", "")}
                     for u, _, data in self.G.in_edges(entity_id, data=True)]
        d["entity_id"] = entity_id
        d["connections"] = out_edges + in_edges
        return d

    # ------------------------------------------------------------ alerts (evidence-based)
    def alerts(self):
        alerts = []

        def add(sev, atype, title, detail, entities, evidence, technical_metric=""):
            aid = "AL-" + hashlib.md5(title.encode()).hexdigest()[:6].upper()
            alerts.append({
                "id": aid,
                "severity": sev, "type": atype, "title": title, "detail": detail,
                "entities": entities, "evidence": evidence,
                "technical_details": technical_metric or f"Derived from cross-referencing {evidence}.",
                "status": self.store.get_alert_status(aid)
            })

        # same phone used across multiple cases
        phone_cases = defaultdict(set)
        for r in self.store.tables["cdr"]:
            if r.get("case_id"):
                norm_c = normalize_case_id(r["case_id"])
                if norm_c:
                    ph = normalize_phone(r["caller_phone"])
                    if ph:
                        phone_cases[ph].add(norm_c)
                    ph2 = normalize_phone(r["receiver_phone"])
                    if ph2:
                        phone_cases[ph2].add(norm_c)

        for ph, cases in phone_cases.items():
            if len(cases) > 1:
                owner = self._owner_of_phone("PHONE:" + ph)
                owner_name = self.G.nodes[owner]["label"] if owner else "Unregistered subscriber"
                case_str = ", ".join(sorted(cases))
                add("HIGH", "Cross-Case Communication Device",
                    f"Phone {ph} ({owner_name}) surfaces across {len(cases)} cases",
                    f"The same telephone number appears in call detail records tagged to multiple active investigations: {case_str}. This indicates shared equipment or communication links across distinct incidents.",
                    [ph, owner_name], "cdr.csv",
                    f"Found in {len(cases)} distinct case-tagged CDR partitions.")

        # same account across multiple cases
        acc_cases = defaultdict(set)
        for r in self.store.tables["bank"]:
            if r.get("case_id"):
                norm_c = normalize_case_id(r["case_id"])
                if norm_c:
                    acc_cases[normalize_id(r["sender_account"])].add(norm_c)
                    acc_cases[normalize_id(r["receiver_account"])].add(norm_c)

        for acc, cases in acc_cases.items():
            if len(cases) > 1:
                owner = self._owner_of_account("ACCOUNT:" + acc)
                owner_name = self.G.nodes[owner]["label"] if owner else "Account Holder"
                case_str = ", ".join(sorted(cases))
                add("HIGH", "Cross-Case Financial Channel",
                    f"Bank account {acc} linked to {len(cases)} cases",
                    f"Bank account {acc} has financial transactions associated with multiple investigations: {case_str}. Requires scrutiny for potential common money movement.",
                    [acc, owner_name], "bank_transactions.csv",
                    f"Found in {len(cases)} distinct case transaction tags.")

        # same vehicle across cases
        for v in self.store.tables["vehicles"]:
            cases = [normalize_case_id(c) or c for c in (v.get("case_ids") or "").split("|") if c]
            if len(cases) > 1:
                owner = v.get("owner_person_id", "")
                p_owner = "PERSON:" + normalize_id(owner)
                owner_name = self.G.nodes[p_owner]["label"] if p_owner in self.G else "Vehicle Owner"
                case_str = ", ".join(sorted(set(cases)))
                add("MEDIUM", "Cross-Case Vehicle Identification",
                    f"Vehicle {v['registration_number']} cited in {len(cases)} cases",
                    f"Vehicle {v['registration_number']} ({v.get('vehicle_type', 'Vehicle')}) is cited in the records of multiple FIRs: {case_str}.",
                    [v["registration_number"], owner_name], "vehicles.csv",
                    f"Co-registered in {len(cases)} FIR vehicle schedules.")

        # structuring: transactions just under common reporting thresholds
        struct = Counter()
        struct_totals = defaultdict(int)
        for r in self.store.tables["bank"]:
            amt = int(float(r.get("amount") or 0))
            if 45000 <= amt < 50000:
                k = (r["sender_account"], r["receiver_account"])
                struct[k] += 1
                struct_totals[k] += amt

        for (sa, ra), n in struct.items():
            if n >= 2:
                add("MEDIUM", "Potential Financial Structuring",
                    f"Repeated transfers just below statutory threshold (Rs 50,000)",
                    f"{n} consecutive transfers totaling Rs {struct_totals[(sa, ra)]:,} observed from account {sa} to {ra} in the range of Rs 45,000 to Rs 49,999.",
                    [sa, ra], "bank_transactions.csv",
                    f"{n} transactions just below mandatory reporting threshold.")

        # entity connecting many cases (persons)
        for p in self.store.tables["persons"]:
            cases = [normalize_case_id(c) or c for c in (p.get("case_ids") or "").split("|") if c]
            if len(cases) >= 2:
                case_str = ", ".join(sorted(set(cases)))
                add("MEDIUM", "Multi-Case Accused Person",
                    f"{p['name']} named as accused across {len(cases)} investigations",
                    f"Individual {p['name']} ({p.get('person_id')}) is formally cited in {len(cases)} separate FIR cases: {case_str}.",
                    [p["name"], p.get("person_id")], "fir.csv",
                    f"Named in {len(cases)} distinct FIR accused schedules.")

        sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        alerts.sort(key=lambda a: sev_order.get(a["severity"], 9))
        return alerts

    def update_alert_status(self, alert_id, status, notes=""):
        self.store.set_alert_status(alert_id, status, notes)
        return {"ok": True, "alert_id": alert_id, "status": status}

    # ------------------------------------------------------------ entity node resolution
    def resolve_entity_node(self, query):
        """Resolves an arbitrary identifier or search string to a node ID in self.G."""
        if not query:
            return None
        q = str(query).strip()
        if q in self.G:
            return q
        
        cid = normalize_case_id(q)
        if cid and ("CASE:" + cid) in self.G:
            return "CASE:" + cid

        ph = normalize_phone(q)
        if ph and ("PHONE:" + ph) in self.G:
            return "PHONE:" + ph

        pid = normalize_id(q)
        if ("PERSON:" + pid) in self.G:
            return "PERSON:" + pid

        v_matches = self.store.find_vehicle(q)
        if v_matches:
            vid = "VEHICLE:" + normalize_id(v_matches[0]["vehicle_id"])
            if vid in self.G:
                return vid

        p_matches = self.store.resolve_person(q)
        if p_matches:
            pid = "PERSON:" + normalize_id(p_matches[0]["person_id"])
            if pid in self.G:
                return pid

        acc_matches = self.store.find_account(q)
        if acc_matches:
            anode = "ACCOUNT:" + normalize_id(acc_matches[0]["account_id"])
            if anode in self.G:
                return anode

        return None

    # ------------------------------------------------------------ shortest path finder
    def find_path(self, entity_a, entity_b):
        """Finds the shortest network path between two entities with edge evidentiary records."""
        node_a = self.resolve_entity_node(entity_a)
        node_b = self.resolve_entity_node(entity_b)
        if not node_a:
            return {"found": False, "error": f"Entity '{entity_a}' could not be resolved in the network."}
        if not node_b:
            return {"found": False, "error": f"Entity '{entity_b}' could not be resolved in the network."}
        if node_a == node_b:
            return {
                "found": True,
                "source": node_a, "target": node_b,
                "path": [{"id": node_a, "label": self.G.nodes[node_a]["label"], "type": self.G.nodes[node_a]["type"]}],
                "steps": [],
                "length": 0
            }

        UG = self.G.to_undirected(as_view=True)
        if not nx.has_path(UG, node_a, node_b):
            return {
                "found": False,
                "source": node_a, "target": node_b,
                "source_label": self.G.nodes[node_a]["label"],
                "target_label": self.G.nodes[node_b]["label"],
                "error": f"No network path found between '{self.G.nodes[node_a]['label']}' and '{self.G.nodes[node_b]['label']}'."
            }

        path = nx.shortest_path(UG, node_a, node_b)
        path_nodes = []
        for i, n in enumerate(path):
            d = self.G.nodes[n]
            path_nodes.append({
                "id": n, "label": d["label"], "type": d["type"], "step": i,
                "details": {k: v for k, v in d.items() if k not in ("label", "type")}
            })

        steps = []
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            edges_uv = []
            if self.G.has_edge(u, v):
                for k, edata in self.G[u][v].items():
                    edges_uv.append({"direction": f"{u} -> {v}", "type": edata["type"],
                                     "evidence": edata.get("evidence", ""), "source": edata.get("source", "")})
            if self.G.has_edge(v, u):
                for k, edata in self.G[v][u].items():
                    edges_uv.append({"direction": f"{v} -> {u}", "type": edata["type"],
                                     "evidence": edata.get("evidence", ""), "source": edata.get("source", "")})
            primary_edge = edges_uv[0] if edges_uv else {"type": "CONNECTED", "evidence": "Network connection", "source": "graph"}
            steps.append({
                "step_index": i + 1,
                "from_node": {"id": u, "label": self.G.nodes[u]["label"], "type": self.G.nodes[u]["type"]},
                "to_node": {"id": v, "label": self.G.nodes[v]["label"], "type": self.G.nodes[v]["type"]},
                "relationship": primary_edge["type"].replace("_", " ").title(),
                "evidence": primary_edge.get("evidence", ""),
                "source": primary_edge.get("source", ""),
                "all_edges": edges_uv
            })

        return {
            "found": True,
            "source": node_a,
            "target": node_b,
            "source_label": self.G.nodes[node_a]["label"],
            "target_label": self.G.nodes[node_b]["label"],
            "length": len(path) - 1,
            "path": path_nodes,
            "steps": steps
        }

    # ------------------------------------------------------------ dynamic node expansion
    def expand_node(self, node_id, hops=1):
        """Expands ego network of an arbitrary node by 1 or 2 hops."""
        node = self.resolve_entity_node(node_id)
        if not node or node not in self.G:
            return None
        hops = max(1, min(3, hops))
        UG = self.G.to_undirected(as_view=True)
        visited = {node: 0}
        frontier = [node]
        for h in range(1, hops + 1):
            nxt = []
            for n in frontier:
                for nb in UG.neighbors(n):
                    if nb not in visited:
                        visited[nb] = h
                        nxt.append(nb)
            frontier = nxt

        sub_nodes = set(visited.keys())
        nodes_out = [{"id": n, "type": self.G.nodes[n]["type"],
                      "label": self.G.nodes[n]["label"], "hop": visited[n]} for n in sub_nodes]
        edges_out = [{"id": f"xpe{i}", "source": u, "target": v, "type": d["type"],
                      "evidence": d.get("evidence", ""), "source_file": d.get("source", "")}
                     for i, (u, v, k, d) in enumerate(self.G.edges(keys=True, data=True))
                     if u in sub_nodes and v in sub_nodes]

        return {
            "root_node": node,
            "label": self.G.nodes[node]["label"],
            "type": self.G.nodes[node]["type"],
            "hops": hops,
            "graph": {"nodes": nodes_out, "edges": edges_out}
        }

    # ------------------------------------------------------------ vehicle dossier & subgraph
    def vehicle_subgraph(self, vehicle_id, hops=1):
        v_matches = self.store.find_vehicle(vehicle_id)
        if not v_matches:
            vid = normalize_id(vehicle_id)
            vnode = "VEHICLE:" + vid
            if vnode not in self.G:
                return None
            v_info = {"vehicle_id": vid, "registration_number": self.G.nodes[vnode]["label"],
                      "vehicle_type": self.G.nodes[vnode].get("vehicle_type", "Vehicle"),
                      "location": self.G.nodes[vnode].get("location", ""), "owner_person_id": "", "case_ids": ""}
        else:
            v_info = v_matches[0]
            vnode = "VEHICLE:" + normalize_id(v_info["vehicle_id"])
            if vnode not in self.G:
                return None

        UG = self.G.to_undirected(as_view=True)
        visited = {vnode: 0}
        frontier = [vnode]
        for h in range(1, hops + 1):
            nxt = []
            for n in frontier:
                for nb in UG.neighbors(n):
                    if nb not in visited:
                        visited[nb] = h
                        nxt.append(nb)
            frontier = nxt

        sub_nodes = set(visited.keys())
        nodes_out = [{"id": n, "type": self.G.nodes[n]["type"],
                      "label": self.G.nodes[n]["label"], "hop": visited[n]} for n in sub_nodes]
        edges_out = [{"id": f"ve{i}", "source": u, "target": v, "type": d["type"],
                      "evidence": d.get("evidence", ""), "source_file": d.get("source", "")}
                     for i, (u, v, k, d) in enumerate(self.G.edges(keys=True, data=True))
                     if u in sub_nodes and v in sub_nodes]

        owner_data = None
        for pred in self.G.predecessors(vnode):
            if self.G.nodes[pred]["type"] == "PERSON":
                owner_data = {"entity_id": pred, "name": self.G.nodes[pred]["label"], "person_id": self.G.nodes[pred].get("person_id", "")}

        linked_cases = set((v_info.get("case_ids") or "").split("|")) - {""}
        for succ in self.G.successors(vnode):
            if self.G.nodes[succ]["type"] == "CASE":
                linked_cases.add(self.G.nodes[succ]["case_id"])

        return {
            "vehicle_id": v_info.get("vehicle_id", ""),
            "registration_number": v_info.get("registration_number", ""),
            "vehicle_type": v_info.get("vehicle_type", "Vehicle"),
            "location": v_info.get("location", "—"),
            "owner": owner_data,
            "linked_cases": sorted(linked_cases),
            "graph": {"nodes": nodes_out, "edges": edges_out}
        }

    # ------------------------------------------------------------ account dossier & subgraph
    def account_subgraph(self, account_id, hops=1):
        anode = "ACCOUNT:" + normalize_id(account_id)
        if anode not in self.G:
            return None

        acc_matches = self.store.find_account(account_id)
        acc_info = acc_matches[0] if acc_matches else {"account_id": account_id, "bank": "Bank", "owner_name": ""}

        UG = self.G.to_undirected(as_view=True)
        visited = {anode: 0}
        frontier = [anode]
        for h in range(1, hops + 1):
            nxt = []
            for n in frontier:
                for nb in UG.neighbors(n):
                    if nb not in visited:
                        visited[nb] = h
                        nxt.append(nb)
            frontier = nxt

        sub_nodes = set(visited.keys())
        nodes_out = [{"id": n, "type": self.G.nodes[n]["type"],
                      "label": self.G.nodes[n]["label"], "hop": visited[n]} for n in sub_nodes]
        edges_out = [{"id": f"ae{i}", "source": u, "target": v, "type": d["type"],
                      "evidence": d.get("evidence", ""), "source_file": d.get("source", "")}
                     for i, (u, v, k, d) in enumerate(self.G.edges(keys=True, data=True))
                     if u in sub_nodes and v in sub_nodes]

        owner = self._owner_of_account(anode)
        owner_data = None
        if owner:
            owner_data = {"entity_id": owner, "name": self.G.nodes[owner]["label"], "person_id": self.G.nodes[owner].get("person_id", "")}

        txns = []
        for r in self.store.tables["bank"]:
            sa = normalize_id(r.get("sender_account"))
            ra = normalize_id(r.get("receiver_account"))
            target_acc = normalize_id(account_id)
            if sa == target_acc or ra == target_acc:
                txns.append({
                    "transaction_id": r.get("transaction_id", ""),
                    "timestamp": r.get("timestamp", ""),
                    "role": "Sender" if sa == target_acc else "Receiver",
                    "counterparty": ra if sa == target_acc else sa,
                    "amount": int(float(r.get("amount", 0))),
                    "type": r.get("transaction_type", "Transfer"),
                    "bank": r.get("bank", ""),
                    "case_id": r.get("case_id", "")
                })
        txns.sort(key=lambda x: x["timestamp"], reverse=True)

        return {
            "account_id": normalize_id(account_id),
            "bank": acc_info.get("bank", "Bank"),
            "owner": owner_data,
            "transactions": txns[:25],
            "graph": {"nodes": nodes_out, "edges": edges_out}
        }

    # ------------------------------------------------------------ multi-entity search
    def search(self, q):
        q = (q or "").strip()
        if not q:
            return {"type": None, "matches": [], "candidates": []}

        cases = []
        cid = normalize_case_id(q)
        if cid and ("CASE:" + cid) in self.G:
            fir = self.store.get_fir(cid)
            cases.append({
                "entity_type": "case",
                "case_id": cid,
                "police_station": fir.get("police_station", "") if fir else "",
                "district": fir.get("district", "") if fir else "",
                "status": fir.get("status", "") if fir else "",
                "sections_of_law": fir.get("sections_of_law", "") if fir else "",
                "confidence": 100,
                "match_type": "exact_case_id",
                "match_reason": f"Exact Case ID: {cid}"
            })

        phones = []
        ph = normalize_phone(q)
        if ph and ("PHONE:" + ph) in self.G:
            owner = self._owner_of_phone("PHONE:" + ph)
            owner_name = self.G.nodes[owner]["label"] if owner else "Unregistered"
            phones.append({
                "entity_type": "phone",
                "phone": ph,
                "owner": owner_name,
                "owner_id": owner,
                "confidence": 100,
                "match_type": "phone_number",
                "match_reason": f"Phone number ({ph})"
            })

        persons = []
        person_candidates = self.store.resolve_person(q)
        for p in person_candidates[:10]:
            persons.append({
                "entity_type": "person",
                "person_id": p["person_id"],
                "name": p["name"],
                "aliases": p.get("aliases", ""),
                "occupation": p.get("occupation", ""),
                "cases": p.get("case_ids", ""),
                "phone_numbers": p.get("phone_numbers", ""),
                "confidence": p["confidence"],
                "match_type": p["match_type"],
                "match_reason": p["match_reason"]
            })

        vehicles = []
        veh_matches = self.store.find_vehicle(q)
        for v in veh_matches[:5]:
            vehicles.append({
                "entity_type": "vehicle",
                "vehicle_id": v["vehicle_id"],
                "registration_number": v["registration_number"],
                "vehicle_type": v["vehicle_type"],
                "location": v.get("location", ""),
                "confidence": v["confidence"],
                "match_type": v["match_type"],
                "match_reason": v["match_reason"]
            })

        accounts = []
        acc_matches = self.store.find_account(q)
        for a in acc_matches[:5]:
            accounts.append({
                "entity_type": "account",
                "account_id": a["account_id"],
                "owner_name": a.get("owner_name", ""),
                "bank": a.get("bank", ""),
                "confidence": a["confidence"],
                "match_type": a["match_type"],
                "match_reason": a["match_reason"]
            })

        all_candidates = []
        for c in cases:
            all_candidates.append({**c, "id": c["case_id"], "label": c["case_id"]})
        for p in persons:
            all_candidates.append({**p, "id": p["person_id"], "label": p["name"]})
        for ph_item in phones:
            all_candidates.append({**ph_item, "id": ph_item["phone"], "label": ph_item["phone"]})
        for v in vehicles:
            all_candidates.append({**v, "id": v["vehicle_id"], "label": v["registration_number"]})
        for a in accounts:
            all_candidates.append({**a, "id": a["account_id"], "label": a["account_id"]})

        all_candidates.sort(key=lambda x: -x["confidence"])

        # Determine primary category for legacy callers
        if cases:
            primary_type = "case"
            matches = cases
        elif phones and (not persons or phones[0]["confidence"] >= persons[0]["confidence"]):
            primary_type = "phone"
            matches = phones
        elif persons:
            primary_type = "person"
            matches = persons
        elif vehicles:
            primary_type = "vehicle"
            matches = vehicles
        elif accounts:
            primary_type = "account"
            matches = accounts
        else:
            primary_type = None
            matches = []

        return {
            "type": primary_type,
            "matches": matches,
            "candidates": all_candidates,
            "categories": {
                "cases": cases,
                "persons": persons,
                "phones": phones,
                "vehicles": vehicles,
                "accounts": accounts
            }
        }


def hops_fallback(hop_of):
    return max(hop_of.values()) if hop_of else 1

