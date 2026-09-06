# NEXUS — Criminal Network Analysis & Investigation System

**CONFIDENTIAL — SYNTHETIC DEMONSTRATION DATA.** Every person, phone number, FIR, bank account, and vehicle in this project is fictional, generated deterministically with a fixed seed (`seed=26189`). No real case data or personal information is used.

NEXUS integrates disconnected law enforcement datasets (FIRs, call records, bank transactions, telecom subscribers, social links, vehicles) into a unified visual knowledge graph to help investigators easily explore cases, discover hidden cross-case bridges, understand why entities matter, and produce actionable intelligence reports.

---

## Primary Product Goal

**Make complex criminal network data simple and intuitive for an investigator to understand.**

The investigator does not need to understand graph algorithms or mathematical formulas. The platform provides a guided investigative workflow:

```
SEARCH (Case / Person / Phone)
   ↓
UNDERSTAND CASE (Summary KPIs & Allegations)
   ↓
SEE IMPORTANT PEOPLE (Ranked Investigative Leads)
   ↓
SEE CONNECTIONS (Interactive N-Hop Knowledge Graph)
   ↓
UNDERSTAND WHY THEY MATTER (Plain-Language Evidence Rationale)
   ↓
DISCOVER RELATED CASES (Cross-Case Bridges via Shared Entities)
   ↓
FOLLOW THE GRAPH (Ego-Networks for Persons and Phones)
   ↓
REVIEW EVIDENCE (Chronological Event Timeline)
   ↓
GENERATE INVESTIGATION SUMMARY (Printable Official Intelligence Brief)
```

---

## Quick Start (Windows & Unix)

### Prerequisites
- Python 3.10+ installed and added to PATH.

### Standard Setup & Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Generate deterministic demonstration dataset (only needed once)
python generate_demo_data.py

# 3. Launch the application
python server.py
```

Then open your browser to **http://localhost:4173**.

### One-Click Launch
- **Windows**: Double-click `run.bat` (automatically installs dependencies, generates demo data if missing, and launches the application).
- **macOS / Linux**: Run `./run.sh`.

---

## What's Inside

```
NEXUS/
├── backend/
│   ├── normalize.py     # Canonical normalization for Case IDs, Phones, and Entity IDs
│   ├── data_store.py    # Thread-safe in-memory store backed by durable CSV files
│   ├── graph_engine.py  # NetworkX master graph, BFS subgraphs, relevance scoring,
│   │                    # related cases, person/phone dossiers, timeline, comparison,
│   │                    # report generator, and global analytics
│   ├── ingestion.py     # Multi-format ingestion (.csv & .txt key-value) with instant rebuild
│   ├── audit.py         # SHA-256 cryptographic chain-of-custody ledger
│   └── app.py           # Flask REST API + static asset serving
├── data/                # Source-of-truth CSV files + ground_truth.json + audit_ledger.json
├── ui/                  # Clean modern dark-theme SPA (HTML5, CSS3, ES6 JS, Cytoscape.js)
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   └── vendor/          # Cytoscape.js and fcose physics layout libraries
├── generate_demo_data.py # Deterministic synthetic dataset generator
├── server.py            # Main application entry point (port 4173)
├── requirements.txt     # Flask, NetworkX, python-louvain
├── run.bat              # Windows batch launcher
└── run.sh               # Unix shell launcher
```

---

## Key Features

### 1. Case ID & Phone Normalization
Accepts all common variants and resolves them to one canonical identifier:
- `0117/2026`, `FIR-0117-2026`, `FIR 0117/2026`, `fir-117-2026` $\rightarrow$ `FIR-0117-2026`
- `+91 9841506919`, `91-9841506919`, `098415 06919` $\rightarrow$ `9841506919`

### 2. Case Investigation Dashboard
- Header showing police station, district, state, legal sections, and status.
- Summary KPIs: Persons of interest, graph entities, relationships, related cases, alerts.
- Interactive Cytoscape graph with physics layout and 1 to 4 hop depth selector.
- Ranked Key Investigative Leads with `HIGH`, `MEDIUM`, and `LOW` priority tags.
- Context-sensitive Node Details side panel with "Why Relevant" points.

### 3. Person & Phone Dossiers (Ego-Networks)
- **Person Investigation**: Detailed demographic card, case involvement list, connected people, phones, vehicles, bank accounts, and a centered ego-graph.
- **Phone Investigation**: Carrier, activation date, registered subscriber, associated FIRs, call history, frequent contact numbers, and call timeline.

### 4. Cross-Case Discovery
- Automatically surfaces companion cases linked through:
  - **Shared Persons** (accused in multiple investigations)
  - **Shared Phones** (same device in CDR traffic across cases)
  - **Shared Vehicles** (same vehicle cited in multiple FIRs)
  - **Shared Bank Accounts** (financial transfers connecting cases)

### 5. Chronological Case Timeline
- Interactive chronological feed of verified events: FIR registration, phone calls with durations and cell towers, bank transfers, and social links.
- Filterable by event category (Calls, Financial, FIR, Social).

### 6. Side-by-Side Case Comparison
- Select any two cases to analyze shared persons, phones, vehicles, and accounts.
- Direct quick-links to investigate companion cases.

### 7. Official Investigation Brief (Export / Print)
- One-click generation of a comprehensive investigation report.
- Features case overview, metrics, prioritized leads, companion cases, event timeline, active alerts, and an ethical decision-support disclaimer.
- Formatted for clean printing or PDF export.

### 8. Real-Time Ingestion
- Upload FIR (.txt or .csv), CDR, Bank, Telecom, Social, or Vehicle files.
- Automatically validates schema, rejects duplicates, appends to store, and rebuilds the knowledge graph immediately without restarting the server.

### 9. Advanced Analytics & Network Disruption
- Global analytics kept separate from the primary investigator workflow: PageRank, Degree, Betweenness, Closeness, Eigenvector Centrality, Louvain Community Detection, Articulation Points, and Link Prediction.
- **Disruption Simulator**: Simulates the removal of an entity and measures network fragmentation impact.
- **Audit Ledger**: SHA-256 hash-chained log with one-click verification.

---

## API Endpoints

```
GET  /api/cases                             # All case summaries
GET  /api/cases/:caseId                     # Single case metadata
GET  /api/investigation/:caseId?hops=1..4   # Full case investigation payload
GET  /api/investigation/:caseId/graph       # Subgraph nodes & edges
GET  /api/investigation/:caseId/entities    # Ranked relevance leads
GET  /api/investigation/:caseId/related-cases# Related cases
GET  /api/person/:personId                  # Person dossier & ego-graph
GET  /api/phone/:phoneNumber                # Phone dossier & call history
GET  /api/timeline/:caseId                  # Chronological case events
GET  /api/compare?case1=...&case2=...       # Cross-case comparison
GET  /api/report/:caseId                    # Formatted investigative report
GET  /api/entities/:entityId                # Entity details & in/out links
GET  /api/search?q=...                      # Multi-mode search
GET  /api/alerts                            # System anomaly alerts
GET  /api/cross-case                        # Global cross-case map
GET  /api/data-sources                      # Ingested datasets status
GET  /api/analytics/global                  # Global centrality & predictions
GET  /api/analytics/disruption/:entityId    # Node removal simulation
GET  /api/audit                             # Cryptographic audit ledger
GET  /api/audit/verify                      # Hash chain validation
POST /api/ingest                            # Multipart file upload
GET  /api/health                            # System health & entity counts
```

---

## Ethical & Safety Guidelines

NEXUS is an investigative decision-support system. It strictly uses objective terminology:
- *"Investigative Lead"*
- *"Relevant Entity"*
- *"Potential Connection"*
- *"Network Evidence"*
- *"Requires Investigation"*

The system never outputs declarations of criminal guilt. All scores represent objective network proximity to assist law enforcement prioritization.
