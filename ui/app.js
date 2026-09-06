const $ = id => document.getElementById(id);
const esc = s => (s ?? '').toString().replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const api = async (path, opts) => {
  try {
    const r = await fetch(path, opts);
    const d = await r.json().catch(() => ({}));
    return { ok: r.ok, status: r.status, data: d };
  } catch (err) {
    return { ok: false, status: 0, data: { error: err.message } };
  }
};

const TYPE_COLOR = {
  PERSON: '#38bdf8',
  PHONE: '#a855f7',
  CASE: '#f97316',
  BANK_ACCOUNT: '#34d399',
  VEHICLE: '#facc15',
  LOCATION: '#94a3b8'
};

let currentCaseId = null;
let currentHops = 2;
let cy = null;
let cyPerson = null;
let cyPhone = null;
let lastKeyEntities = [];
let HOME_MODE = 'case';
let currentTimelineEvents = [];
let currentTimelineFilter = 'ALL';
let allCasesCache = [];
let currentAlertStatusFilter = 'ALL';
let alertsCache = [];

/* ================================================================ NAVIGATION */
document.querySelectorAll('#nav button').forEach(b => {
  b.onclick = () => showView(b.dataset.v);
});

function showView(v) {
  document.querySelectorAll('#nav button').forEach(x => {
    x.classList.toggle('on', x.dataset.v === v);
  });
  document.querySelectorAll('.view').forEach(x => {
    x.classList.toggle('on', x.id === 'v-' + v);
  });

  if (v === 'cases') loadCases();
  if (v === 'alerts') loadAlerts();
  if (v === 'advanced') loadAdvanced();
  if (v === 'compare') loadCompareView();
  if (v === 'timeline') loadTimelineView(currentCaseId);
  if (v === 'datasources') loadDataSources();
  if (v === 'pathfinder') loadPathFinderView();
  if (v === 'dataquality') loadDataQualityView();
}

/* ================================================================ HOME / SEARCH */
document.querySelectorAll('.mode-btn').forEach(b => {
  b.onclick = () => {
    document.querySelectorAll('.mode-btn').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    HOME_MODE = b.dataset.mode;
    const input = $('homeSearch');
    if (HOME_MODE === 'all') {
      input.placeholder = 'Search by Case ID, Person Name/ID, Phone, Vehicle, or Account...';
    } else if (HOME_MODE === 'case') {
      input.placeholder = 'e.g. 0117/2026, FIR-0170-2026, or FIR 0170/2026';
    } else if (HOME_MODE === 'person') {
      input.placeholder = 'e.g. Ramesh Patil, Ashok Sheikh, or Mahesh Momin';
    } else if (HOME_MODE === 'phone') {
      input.placeholder = 'e.g. 9841506919 or 9821005511 (10-digit number)';
    } else if (HOME_MODE === 'vehicle') {
      input.placeholder = 'e.g. DL-01-AB-1234 or V001';
    } else if (HOME_MODE === 'account') {
      input.placeholder = 'e.g. Bank Account Number or Transaction ID';
    }
  };
});

$('btnHomeSearch').onclick = doHomeSearch;
$('homeSearch').addEventListener('keydown', e => {
  if (e.key === 'Enter') doHomeSearch();
});

function openCandidate(type, id) {
  if ($('homeMultiMatch')) $('homeMultiMatch').style.display = 'none';
  if (type === 'case') investigateCase(id);
  else if (type === 'person') investigatePerson(id);
  else if (type === 'phone') investigatePhone(id);
  else if (type === 'vehicle') investigateVehicle(id);
  else if (type === 'account') investigateAccount(id);
}

async function doHomeSearch() {
  const q = $('homeSearch').value.trim();
  $('homeErr').innerHTML = '';
  $('searchSuggestions').style.display = 'none';
  $('searchSuggestions').innerHTML = '';
  if ($('homeMultiMatch')) {
    $('homeMultiMatch').style.display = 'none';
    $('homeMultiMatch').innerHTML = '';
  }
  if (!q) return;

  const { data } = await api('/api/search?q=' + encodeURIComponent(q));

  // Determine candidates based on mode filter or all
  let candidates = data.candidates || [];
  if (HOME_MODE !== 'all') {
    candidates = candidates.filter(c => c.entity_type === HOME_MODE);
  }

  // If exact single match found
  if (candidates.length === 1 && candidates[0].confidence === 100) {
    openCandidate(candidates[0].entity_type, candidates[0].id);
    return;
  }

  // If multiple matches exist, show ranked candidate selection list
  if (candidates.length > 0) {
    if (candidates.length === 1) {
      openCandidate(candidates[0].entity_type, candidates[0].id);
      return;
    }
    if ($('homeMultiMatch')) {
      $('homeMultiMatch').style.display = 'flex';
      $('homeMultiMatch').innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <span style="font-size:12px;color:var(--muted);font-weight:600">Matching Entities (${candidates.length}):</span>
          <span class="dim" style="font-size:11px">Select an entity to launch investigation</span>
        </div>` + candidates.map(c => `
        <div class="candidate-row" onclick="openCandidate('${c.entity_type}', '${esc(c.id)}')">
          <div class="candidate-info">
            <span class="pill ${c.entity_type === 'case' ? 'info' : (c.entity_type === 'person' ? 'ok' : 'ghost')}">${c.entity_type.toUpperCase()}</span>
            <div>
              <b>${esc(c.label)}</b>
              ${c.id !== c.label ? `<span class="dim mono" style="font-size:11px;margin-left:6px">(${esc(c.id)})</span>` : ''}
              <div class="dim" style="font-size:11px">${esc(c.match_reason || '')}</div>
            </div>
          </div>
          <div class="candidate-badges">
            <span class="conf-badge ${c.confidence < 90 ? 'med' : ''}">${c.confidence}% Match</span>
            <button class="btn small ghost" style="padding:2px 8px;font-size:11px">Inspect →</button>
          </div>
        </div>`).join('');
    }
    return;
  }

  // If no candidates found, provide helpful suggestions
  if (HOME_MODE === 'case' || HOME_MODE === 'all') {
    const { data: recent } = await api('/api/cases');
    const sugg = (recent.cases || []).slice(0, 5).map(c => c.case_id);
    $('homeErr').innerHTML = `<div class="err-msg">
      <b>No record found matching "${esc(q)}".</b><br>
      Available registered cases: ${sugg.map(s => `<span class="sugg" onclick="investigateCase('${s}')">${s}</span>`).join(' · ')}
    </div>`;
  } else {
    $('homeErr').innerHTML = `<div class="err-msg">No ${HOME_MODE} record found matching "${esc(q)}". Check spelling or try searching across All Entities.</div>`;
  }
}

async function loadHomeStats() {
  const { data: health } = await api('/api/health');
  if (health) {
    if (health.cases && $('statCasesCount')) $('statCasesCount').textContent = health.cases;
    if (health.nodes && $('statGraphNodes')) $('statGraphNodes').textContent = health.nodes;
    if (health.edges && $('statGraphEdges')) $('statGraphEdges').textContent = health.edges;
  }
}

async function loadRecentCases() {
  const { data } = await api('/api/cases');
  const cases = (data.cases || []);
  allCasesCache = cases;
  const recent = cases.slice(0, 8);
  $('recentCases').innerHTML = recent.map(c => `
    <div class="case-chip" onclick="investigateCase('${c.case_id}')">
      <div class="title">
        <span>${esc(c.case_id)}</span>
        <span class="pill ${c.status === 'Closed' ? 'ghost' : 'info'}">${esc(c.status)}</span>
      </div>
      <div class="meta">${esc(c.police_station)} · ${esc(c.district)}</div>
      <div class="meta dim" style="margin-top:4px">${c.total_entities} entities · ${c.related_case_count} related cases</div>
    </div>`).join('') || '<div class="dim">No registered cases.</div>';
}

/* ================================================================ CASE INVESTIGATION */
async function investigateCase(caseId, hops) {
  currentCaseId = caseId;
  currentHops = hops || currentHops || 2;
  showView('investigate');
  
  $('investContent').innerHTML = `
    <div class="side-panel">
      <div class="empty">Loading case intelligence for <b>${esc(caseId)}</b>…</div>
    </div>`;

  const { ok, data } = await api(`/api/investigation/${encodeURIComponent(caseId)}?hops=${currentHops}`);
  if (!ok) {
    const sugg = (data.did_you_mean || []).map(s => `<span class="sugg" onclick="investigateCase('${s}')">${s}</span>`).join(' · ');
    $('investContent').innerHTML = `
      <div class="card">
        <h3 style="color:var(--crit)">Case Not Found</h3>
        <p class="lede">The requested case <b>${esc(caseId)}</b> does not exist in the active database.</p>
        <p>Available cases you can investigate: ${sugg}</p>
        <button class="btn small mt16" onclick="showView('cases')">View All Cases</button>
      </div>`;
    return;
  }

  lastKeyEntities = data.key_entities || [];
  renderInvestigation(data);
}

function renderInvestigation(data) {
  const c = data.case;
  $('investContent').innerHTML = `
    <div class="case-header">
      <div>
        <h2>${esc(c.case_id)}</h2>
        <div class="lede" style="margin-bottom:0">
          ${esc(c.police_station)} · ${esc(c.district)}, ${esc(c.state)}
          &nbsp;<span class="pill ${c.status === 'Closed' ? 'ghost' : 'info'}">${esc(c.status)}</span>
          &nbsp;<span class="pill ghost">${esc(c.sections_of_law || 'General')}</span>
          &nbsp;<span class="dim mono" style="font-size:11px">Registered: ${esc(c.date || '—')}</span>
        </div>
      </div>
      <div class="invest-toolbar">
        <div class="hops" id="hopButtons">
          ${[1, 2, 3, 4].map(h => `
            <button class="hop-btn ${h === currentHops ? 'on' : ''}" onclick="investigateCase('${c.case_id}', ${h})">
              ${h} Hop${h > 1 ? 's' : ''}
            </button>`).join('')}
        </div>
        <button class="btn small ghost" onclick="openTimelineForCurrentCase()">⏱ Timeline</button>
        <button class="btn small ghost" onclick="openCompareForCurrentCase()">⇄ Compare</button>
        <button class="btn small" onclick="openReportModal('${c.case_id}')">📄 Export Brief</button>
      </div>
    </div>

    <div class="grid g4 mb14">
      <div class="card kpi">
        <div class="n">${data.summary.persons}</div>
        <div class="l">Persons of Interest</div>
      </div>
      <div class="card kpi">
        <div class="n">${data.summary.entities}</div>
        <div class="l">Total Graph Entities</div>
      </div>
      <div class="card kpi">
        <div class="n">${data.summary.relationships}</div>
        <div class="l">Evidentiary Links</div>
      </div>
      <div class="card kpi ${data.summary.related_cases > 0 ? 'active-kpi' : ''}">
        <div class="n">${data.summary.related_cases}</div>
        <div class="l">Related FIR Cases</div>
      </div>
    </div>

    <div class="invest-layout g-side">
      <div>
        <div class="graph-card mb14">
          <div class="graph-toolbar">
            <div class="graph-btn-group">
              <button class="graph-tool-btn" id="btnCyZoomIn" title="Zoom In">+</button>
              <button class="graph-tool-btn" id="btnCyZoomOut" title="Zoom Out">−</button>
              <button class="graph-tool-btn" id="btnCyFit" title="Fit to Screen">⛶</button>
              <button class="graph-tool-btn" id="btnCyReset" title="Reset Layout">↻</button>
            </div>
            <input class="graph-search-input" id="cySearchInput" type="text" placeholder="🔍 Search nodes in canvas...">
            <div class="graph-filters">
              <span class="filter-chip on" data-type="PERSON"><span class="chip-dot" style="background:#38bdf8"></span>Persons</span>
              <span class="filter-chip on" data-type="PHONE"><span class="chip-dot" style="background:#a855f7"></span>Phones</span>
              <span class="filter-chip on" data-type="CASE"><span class="chip-dot" style="background:#f97316"></span>Cases</span>
              <span class="filter-chip on" data-type="VEHICLE"><span class="chip-dot" style="background:#facc15"></span>Vehicles</span>
              <span class="filter-chip on" data-type="BANK_ACCOUNT"><span class="chip-dot" style="background:#34d399"></span>Accounts</span>
            </div>
          </div>
          <div id="cy"></div>
          <div class="legend-row">
            ${Object.entries(TYPE_COLOR).map(([t, col]) => `
              <span><span class="dot" style="background:${col}"></span>${t.replace('_', ' ')}</span>`).join('')}
            <span style="margin-left:auto;color:var(--dim)">Click node to inspect dossier · Click edge to view record</span>
          </div>
        </div>

        <div class="card mb14">
          <div class="section-head">
            <h3>Key Investigative Leads (${data.key_entities.length})</h3>
            <span class="dim">Prioritized by deterministic multi-source scoring (0–100) — not proof of guilt</span>
          </div>
          <div id="entityList"></div>
        </div>

        <div class="card">
          <div class="section-head">
            <h3>Cross-Case Bridges (${data.related_cases.length})</h3>
            <span class="dim">Cases sharing accused persons, phones, vehicles, or bank accounts</span>
          </div>
          <div id="relatedCases"></div>
        </div>
      </div>

      <div class="side-panel" id="sidePanel">
        <div class="empty">
          <b>Investigator Inspection Panel</b><br><br>
          Click any person, phone, vehicle, or case node in the graph, or pick a lead from the list, to inspect why they matter.
        </div>
      </div>
    </div>
  `;

  renderEntityList(data.key_entities);
  renderRelatedCases(data.related_cases);
  renderGraph(data.graph, data.key_entities);

  if (data.key_entities && data.key_entities.length > 0) {
    showEntity(data.key_entities[0].entity_id);
  }
}

function renderEntityList(entities) {
  $('entityList').innerHTML = entities.length ? entities.map(e => {
    const score = e.score_100 !== undefined ? e.score_100 : Math.round((e.relevance_score || 0) * 100);
    const pb = e.point_breakdown || {};
    return `
    <div class="entity-row" onclick="showEntity('${e.entity_id}')">
      <div class="top">
        <span class="name">${esc(e.name)}</span>
        <div style="display:flex;align-items:center;gap:6px">
          <span class="score-badge">${score}/100</span>
          <span class="pill ${e.priority}">${e.priority} PRIORITY</span>
        </div>
      </div>
      <div class="reasons">
        ${e.reasons.slice(0, 3).map(r => `<div>${esc(r)}</div>`).join('')}
      </div>
      ${pb.total_points !== undefined ? `
        <div class="points-breakdown">
          ${pb.direct_case_connection ? `<div class="point-item"><span>Named Accused:</span><b>+${pb.direct_case_connection}</b></div>` : ''}
          ${pb.cross_case_connections ? `<div class="point-item"><span>Cross-Case:</span><b>+${pb.cross_case_connections}</b></div>` : ''}
          ${pb.communication_links ? `<div class="point-item"><span>Calls:</span><b>+${pb.communication_links}</b></div>` : ''}
          ${pb.financial_links ? `<div class="point-item"><span>Transfers:</span><b>+${pb.financial_links}</b></div>` : ''}
          ${pb.multi_source_evidence ? `<div class="point-item"><span>Multi-Source:</span><b>+${pb.multi_source_evidence}</b></div>` : ''}
          ${pb.network_centrality ? `<div class="point-item"><span>Centrality:</span><b>+${pb.network_centrality}</b></div>` : ''}
        </div>` : ''}
      <div style="margin-top:6px;display:flex;justify-content:flex-end">
        <button class="btn small ghost" style="padding:3px 8px;font-size:11px" onclick="event.stopPropagation(); investigatePerson('${e.person_id}')">Open Person Dossier →</button>
      </div>
    </div>`;
  }).join('') : '<div class="dim">No person entities identified within this hop depth.</div>';
}

function renderRelatedCases(related) {
  $('relatedCases').innerHTML = related.length ? related.map(r => `
    <div class="rc-card" onclick="investigateCase('${r.case_id}')">
      <div class="top-line">
        <b style="font-size:13.5px">${esc(r.case_id)}</b>
        <span class="pill info">${esc(r.primary_connection || 'Shared Entity')}</span>
      </div>
      <div class="dim" style="font-size:12px;margin-top:4px">
        ${r.reasons.map(x => esc(x.reason)).join(' · ')}
      </div>
      <div style="margin-top:8px;text-align:right">
        <span style="color:var(--accent);font-size:11.5px;font-weight:600">Investigate ${esc(r.case_id)} →</span>
      </div>
    </div>`).join('') : '<div class="dim">No cross-case bridges discovered at current depth. Expand hops to surface deeper connections.</div>';
}

function renderGraph(graph, keyEntities) {
  const elements = [
    ...graph.nodes.map(n => ({
      data: { id: n.id, label: n.label, type: n.type, hop: n.hop }
    })),
    ...graph.edges.map(e => ({
      data: { id: e.id, source: e.source, target: e.target, label: e.type, evidence: e.evidence }
    }))
  ];

  if (cy) {
    try { cy.destroy(); } catch (e) {}
  }

  cy = cytoscape({
    container: $('cy'),
    elements,
    style: [
      {
        selector: 'node',
        style: {
          'background-color': ele => TYPE_COLOR[ele.data('type')] || '#94a3b8',
          'label': 'data(label)',
          'color': '#f1f5f9',
          'font-size': 10,
          'text-valign': 'bottom',
          'text-margin-y': 4,
          'width': ele => ele.data('hop') === 0 ? 36 : (ele.data('type') === 'PERSON' ? 24 : 18),
          'height': ele => ele.data('hop') === 0 ? 36 : (ele.data('type') === 'PERSON' ? 24 : 18),
          'border-width': 2,
          'border-color': '#090d12',
        }
      },
      {
        selector: 'edge',
        style: {
          'width': 1.5,
          'line-color': '#2a384d',
          'target-arrow-color': '#2a384d',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'opacity': 0.75,
        }
      },
      {
        selector: '.highlighted',
        style: {
          'border-color': '#38bdf8',
          'border-width': 3,
          'line-color': '#38bdf8',
          'target-arrow-color': '#38bdf8',
          'opacity': 1.0,
        }
      },
      {
        selector: '.dimmed',
        style: {
          'opacity': 0.15
        }
      }
    ],
    layout: {
      name: 'fcose',
      animate: false,
      nodeRepulsion: 7500,
      idealEdgeLength: 85
    },
    wheelSensitivity: 0.25,
  });

  // Controls toolbar wiring
  if ($('btnCyZoomIn')) $('btnCyZoomIn').onclick = () => cy.zoom({ level: cy.zoom() * 1.3, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  if ($('btnCyZoomOut')) $('btnCyZoomOut').onclick = () => cy.zoom({ level: cy.zoom() * 0.75, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  if ($('btnCyFit')) $('btnCyFit').onclick = () => cy.fit(null, 30);
  if ($('btnCyReset')) $('btnCyReset').onclick = () => cy.layout({ name: 'fcose', animate: true, nodeRepulsion: 7500, idealEdgeLength: 85 }).run();

  // In-canvas node search
  const sInput = $('cySearchInput');
  if (sInput) {
    sInput.oninput = e => {
      const val = e.target.value.toLowerCase().trim();
      if (!val) {
        cy.elements().removeClass('highlighted dimmed');
        return;
      }
      cy.elements().removeClass('highlighted dimmed').addClass('dimmed');
      const matches = cy.nodes().filter(ele => {
        const lbl = (ele.data('label') || '').toLowerCase();
        const nid = (ele.data('id') || '').toLowerCase();
        return lbl.includes(val) || nid.includes(val);
      });
      matches.removeClass('dimmed').addClass('highlighted');
      matches.neighborhood().removeClass('dimmed').addClass('highlighted');
      if (matches.length > 0) {
        cy.animate({ center: { eles: matches }, zoom: 1.2, duration: 300 });
      }
    };
  }

  // Node type filter chips
  document.querySelectorAll('.graph-filters .filter-chip').forEach(chip => {
    chip.onclick = () => {
      const type = chip.dataset.type;
      const on = chip.classList.toggle('on');
      const nodes = cy.nodes(`[type = "${type}"]`);
      if (on) {
        nodes.style('display', 'element');
        nodes.connectedEdges().style('display', 'element');
      } else {
        nodes.style('display', 'none');
        nodes.connectedEdges().style('display', 'none');
      }
    };
  });

  cy.on('tap', 'node', evt => {
    const id = evt.target.id();
    cy.elements().removeClass('highlighted dimmed');
    cy.elements().addClass('dimmed');
    evt.target.removeClass('dimmed').addClass('highlighted');
    evt.target.neighborhood().removeClass('dimmed').addClass('highlighted');
    showEntity(id);
  });

  cy.on('tap', 'edge', evt => {
    showEdge(evt.target.data());
  });

  cy.on('tap', evt => {
    if (evt.target === cy) {
      cy.elements().removeClass('highlighted dimmed');
    }
  });
}

/* ================================================================ NODE DETAILS PANEL */
async function showEntity(entityId) {
  const panel = $('sidePanel');
  if (!panel) return;

  const { ok, data } = await api('/api/entities/' + encodeURIComponent(entityId));
  if (!ok) return;

  const known = lastKeyEntities.find(e => e.entity_id === entityId);
  let html = '';

  if (data.type === 'PERSON') {
    html += `
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div>
          <h3 style="margin-bottom:2px">${esc(data.label)}</h3>
          <div class="dim mono" style="font-size:11px">${esc(data.person_id || '')}</div>
        </div>
        <span class="pill ${known ? known.priority : 'info'}">${known ? known.priority + ' RELEVANCE' : 'PERSON'}</span>
      </div>

      <div class="kv">
        <div class="k">Occupation</div><div>${esc(data.occupation || '—')}</div>
        <div class="k">Age range</div><div>${esc(data.age_range || '—')}</div>
        <div class="k">Address</div><div>${esc(data.address || '—')}</div>
      </div>

      <div style="margin-top:10px">
        <button class="btn small ghost" style="width:100%" onclick="investigatePerson('${data.person_id}')">
          Open Full Person Dossier →
        </button>
      </div>`;

    if (known) {
      html += `
        <div class="section">
          <h5>Why is this entity relevant?</h5>
          <div style="font-size:12px;line-height:1.7">
            ${known.reasons.map(r => `<div><b style="color:var(--ok)">✓</b> ${esc(r)}</div>`).join('')}
          </div>
          <div class="pill ${known.priority} mt16" style="font-size:11px">
            ${known.priority} PRIORITY · Case Relevance Score: ${known.relevance_score}
          </div>
        </div>`;
    }

    const caseIds = (data.case_ids || '').split('|').filter(Boolean);
    if (caseIds.length) {
      html += `
        <div class="section">
          <h5>Case Involvements (${caseIds.length})</h5>
          ${caseIds.map(c => `
            <div class="rc-card" onclick="investigateCase('${c}')">
              <b>${esc(c)}</b>
            </div>`).join('')}
        </div>`;
    }
  } else if (data.type === 'PHONE') {
    html += `
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div>
          <h3 style="margin-bottom:2px">${esc(data.label)}</h3>
          <div class="dim" style="font-size:11px">Communication Device</div>
        </div>
        <span class="pill info">PHONE</span>
      </div>
      <div class="kv">
        <div class="k">Carrier</div><div>${esc(data.operator || '—')}</div>
        <div class="k">Subscriber</div><div>${esc(data.subscriber_name || '—')}</div>
      </div>
      <div style="margin-top:10px">
        <button class="btn small ghost" style="width:100%" onclick="investigatePhone('${data.label}')">
          Open Phone History & Dossier →
        </button>
      </div>`;
  } else if (data.type === 'CASE') {
    html += `
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div>
          <h3 style="margin-bottom:2px">${esc(data.label)}</h3>
          <div class="dim" style="font-size:11px">${esc(data.police_station || '')}</div>
        </div>
        <span class="pill info">${esc(data.status || 'CASE')}</span>
      </div>
      <div class="kv">
        <div class="k">District</div><div>${esc(data.district || '—')}</div>
        <div class="k">Date</div><div>${esc(data.date || '—')}</div>
        <div class="k">Sections</div><div>${esc(data.sections || '—')}</div>
      </div>
      <div style="margin-top:10px">
        <button class="btn small" style="width:100%" onclick="investigateCase('${data.label}')">
          Investigate This Case →
        </button>
      </div>`;
  } else {
    html += `
      <h3>${esc(data.label)}</h3>
      <div class="pill info">${esc(data.type)}</div>`;
  }

  if (data.connections && data.connections.length) {
    html += `
      <div class="section">
        <h5>Direct Connections (${data.connections.length})</h5>
        ${data.connections.slice(0, 10).map(c => {
          const other = c.target_label || c.source_label;
          const dir = c.target_label ? '→' : '←';
          return `
            <div class="rc-card" style="cursor:default">
              <b>${dir} ${esc(other)}</b><br>
              <span class="dim">${esc(c.type)}${c.evidence ? ' · ' + esc(c.evidence) : ''}</span>
            </div>`;
        }).join('')}
      </div>`;
  }

  panel.innerHTML = html;
}

function showEdge(d) {
  const panel = $('sidePanel');
  if (!panel) return;
  panel.innerHTML = `
    <h3>Evidentiary Link</h3>
    <div class="kv">
      <div class="k">Relationship</div><div><b>${esc(d.label)}</b></div>
      <div class="k">Evidence</div><div>${esc(d.evidence || '—')}</div>
    </div>
    <div class="note" style="margin-top:14px">
      This connection is derived from verified physical source records and can be audited back to the original ingestion file.
    </div>`;
}

/* ================================================================ PERSON DOSSIER */
async function investigatePerson(personId) {
  showView('person');
  $('navPersonBtn').style.display = '';
  $('navPersonBtn').classList.add('on');
  
  $('personContent').innerHTML = `
    <div class="side-panel">
      <div class="empty">Loading dossier for person <b>${esc(personId)}</b>…</div>
    </div>`;

  const { ok, data } = await api('/api/person/' + encodeURIComponent(personId));
  if (!ok) {
    $('personContent').innerHTML = `
      <div class="card">
        <h3 style="color:var(--crit)">Person Not Found</h3>
        <p class="lede">No profile matches identifier <b>${esc(personId)}</b>.</p>
      </div>`;
    return;
  }

  $('personContent').innerHTML = `
    <div class="dossier-header">
      <div>
        <div class="brand-badge">INDIVIDUAL INTELLIGENCE DOSSIER</div>
        <h2>${esc(data.name)}</h2>
        <div class="lede" style="margin-bottom:0">
          ID: <span class="mono">${esc(data.person_id)}</span>
          ${data.aliases ? `· Aliases: <b>${esc(data.aliases)}</b>` : ''}
          · Occupation: <b>${esc(data.occupation)}</b>
          · Age: <b>${esc(data.age_range)}</b>
        </div>
      </div>
      <div>
        ${data.is_bridge ? '<span class="pill crit">CRITICAL NETWORK BRIDGE</span>' : '<span class="pill ok">ENTITY PROFILE</span>'}
      </div>
    </div>

    <div class="dossier-grid">
      <div>
        <div class="graph-card mb14">
          <div id="cyPerson"></div>
          <div class="legend-row">
            ${Object.entries(TYPE_COLOR).map(([t, col]) => `
              <span><span class="dot" style="background:${col}"></span>${t.replace('_', ' ')}</span>`).join('')}
            <span style="margin-left:auto;color:var(--dim)">Ego-network centered on ${esc(data.name)}</span>
          </div>
        </div>

        <div class="card mb14">
          <h3>Why is this person relevant?</h3>
          <div style="line-height:1.8">
            ${data.why_relevant.map(r => `<div><b style="color:var(--ok)">✓</b> ${esc(r)}</div>`).join('')}
          </div>
        </div>

        <div class="card mb14">
          <h3>Case Involvements (${data.case_involvement.length})</h3>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            ${data.case_involvement.map(c => `
              <button class="btn small ghost" onclick="investigateCase('${c}')">
                ◈ ${esc(c)} →
              </button>`).join('') || '<div class="dim">No explicit FIR cases linked.</div>'}
          </div>
        </div>
      </div>

      <div>
        <div class="entity-dossier-card">
          <h4>Associated Contacts (${data.connected_people.length})</h4>
          <div style="max-height:180px;overflow-y:auto">
            ${data.connected_people.map(p => `
              <div class="rc-card" onclick="investigatePerson('${p.entity_id.replace('PERSON:','')}')">
                <b>${esc(p.name)}</b><br>
                <span class="dim">${esc(p.connection)}</span>
              </div>`).join('') || '<div class="dim">No direct contacts recorded.</div>'}
          </div>
        </div>

        <div class="entity-dossier-card">
          <h4>Communication Devices (${data.phones.length})</h4>
          <div style="max-height:140px;overflow-y:auto">
            ${data.phones.map(ph => `
              <div class="rc-card" onclick="investigatePhone('${ph.phone}')">
                <b>📞 ${esc(ph.phone)}</b>
              </div>`).join('') || '<div class="dim">No phones recorded.</div>'}
          </div>
        </div>

        <div class="entity-dossier-card">
          <h4>Tracked Vehicles (${data.vehicles.length})</h4>
          <div style="max-height:120px;overflow-y:auto">
            ${data.vehicles.map(v => `
              <div class="rc-card" style="cursor:default">
                <b>🚗 ${esc(v.registration)}</b>
              </div>`).join('') || '<div class="dim">No vehicles recorded.</div>'}
          </div>
        </div>

        <div class="entity-dossier-card">
          <h4>Bank Accounts (${data.accounts.length})</h4>
          <div style="max-height:120px;overflow-y:auto">
            ${data.accounts.map(a => `
              <div class="rc-card" style="cursor:default">
                <b>🏦 ${esc(a.account)}</b>
              </div>`).join('') || '<div class="dim">No accounts recorded.</div>'}
          </div>
        </div>
      </div>
    </div>
  `;

  renderEgoGraph('cyPerson', data.graph);
}

/* ================================================================ PHONE DOSSIER */
async function investigatePhone(phoneNumber) {
  showView('phone');
  $('navPhoneBtn').style.display = '';
  $('navPhoneBtn').classList.add('on');

  $('phoneContent').innerHTML = `
    <div class="side-panel">
      <div class="empty">Loading phone dossier for <b>${esc(phoneNumber)}</b>…</div>
    </div>`;

  const { ok, data } = await api('/api/phone/' + encodeURIComponent(phoneNumber));
  if (!ok) {
    $('phoneContent').innerHTML = `
      <div class="card">
        <h3 style="color:var(--crit)">Phone Record Not Found</h3>
        <p class="lede">No telecommunication records found for number <b>${esc(phoneNumber)}</b>.</p>
      </div>`;
    return;
  }

  $('phoneContent').innerHTML = `
    <div class="dossier-header">
      <div>
        <div class="brand-badge">TELECOMMUNICATION INTELLIGENCE</div>
        <h2>${esc(data.phone_number)}</h2>
        <div class="lede" style="margin-bottom:0">
          Carrier: <b>${esc(data.operator)}</b>
          · Subscriber: <b>${data.owner ? esc(data.owner.name) : 'Unregistered / Unknown'}</b>
          · Active Since: <b>${esc(data.activation_date)}</b>
        </div>
      </div>
      <div>
        <span class="pill info">TELECOM SUBSCRIBER</span>
      </div>
    </div>

    <div class="dossier-grid">
      <div>
        <div class="graph-card mb14">
          <div id="cyPhone"></div>
          <div class="legend-row">
            ${Object.entries(TYPE_COLOR).map(([t, col]) => `
              <span><span class="dot" style="background:${col}"></span>${t.replace('_', ' ')}</span>`).join('')}
            <span style="margin-left:auto;color:var(--dim)">Calls & relationships for ${esc(data.phone_number)}</span>
          </div>
        </div>

        <div class="card mb14">
          <h3>Why is this device relevant?</h3>
          <div style="line-height:1.8">
            ${data.why_relevant.map(r => `<div><b style="color:var(--ok)">✓</b> ${esc(r)}</div>`).join('')}
          </div>
        </div>

        <div class="card mb14">
          <h3>Associated FIR Investigations (${data.related_cases.length})</h3>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            ${data.related_cases.map(c => `
              <button class="btn small ghost" onclick="investigateCase('${c}')">
                ◈ ${esc(c)} →
              </button>`).join('') || '<div class="dim">No direct FIR cases linked.</div>'}
          </div>
        </div>

        <div class="card">
          <h3>Call Activity Log (Recent)</h3>
          <table style="font-size:12px">
            <thead>
              <tr><th>Timestamp</th><th>Direction</th><th>Contact</th><th>Duration</th><th>Tower</th><th>Case</th></tr>
            </thead>
            <tbody>
              ${data.timeline.map(t => {
                const isCaller = t.caller === data.phone_number;
                const contact = isCaller ? t.receiver : t.caller;
                const dir = isCaller ? 'Outgoing →' : '← Incoming';
                return `
                  <tr>
                    <td class="mono dim">${esc(t.timestamp)}</td>
                    <td>${dir}</td>
                    <td class="mono"><b>${esc(contact)}</b></td>
                    <td>${t.duration}s</td>
                    <td class="dim">${esc(t.tower || '—')}</td>
                    <td>${t.case_id ? `<span class="pill info">${esc(t.case_id)}</span>` : '—'}</td>
                  </tr>`;
              }).join('') || '<tr><td colspan="6" class="dim">No call records available.</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <div class="entity-dossier-card">
          <h4>Frequent Contact Numbers (${data.call_connections.length})</h4>
          <div style="max-height:260px;overflow-y:auto">
            ${data.call_connections.map(c => `
              <div class="rc-card" onclick="investigatePhone('${c.phone}')">
                <b>${esc(c.phone)}</b> (${esc(c.owner_name)})<br>
                <span class="dim">${c.calls} calls · ${c.duration_sec}s total</span>
              </div>`).join('') || '<div class="dim">No call connections.</div>'}
          </div>
        </div>

        <div class="entity-dossier-card">
          <h4>Connected Persons (${data.connected_people.length})</h4>
          <div style="max-height:220px;overflow-y:auto">
            ${data.connected_people.map(p => `
              <div class="rc-card" onclick="investigatePerson('${p.entity_id.replace('PERSON:','')}')">
                <b>👤 ${esc(p.name)}</b><br>
                <span class="dim">Via phone ${esc(p.phone)}</span>
              </div>`).join('') || '<div class="dim">No registered owners identified.</div>'}
          </div>
        </div>
      </div>
    </div>
  `;

  renderEgoGraph('cyPhone', data.graph);
}

function renderEgoGraph(containerId, graph) {
  const container = $(containerId);
  if (!container) return;

  const elements = [
    ...graph.nodes.map(n => ({
      data: { id: n.id, label: n.label, type: n.type, hop: n.hop }
    })),
    ...graph.edges.map(e => ({
      data: { id: e.id, source: e.source, target: e.target, label: e.type, evidence: e.evidence }
    }))
  ];

  cytoscape({
    container,
    elements,
    style: [
      {
        selector: 'node',
        style: {
          'background-color': ele => TYPE_COLOR[ele.data('type')] || '#94a3b8',
          'label': 'data(label)',
          'color': '#f1f5f9',
          'font-size': 10,
          'text-valign': 'bottom',
          'text-margin-y': 4,
          'width': ele => ele.data('hop') === 0 ? 32 : 20,
          'height': ele => ele.data('hop') === 0 ? 32 : 20,
          'border-width': 2,
          'border-color': '#090d12',
        }
      },
      {
        selector: 'edge',
        style: {
          'width': 1.5,
          'line-color': '#2a384d',
          'target-arrow-color': '#2a384d',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'opacity': 0.75,
        }
      }
    ],
    layout: {
      name: 'fcose',
      animate: false,
      nodeRepulsion: 6500,
      idealEdgeLength: 75
    },
    wheelSensitivity: 0.25,
  });
}

/* ================================================================ CASE COMPARISON */
function openCompareForCurrentCase() {
  showView('compare');
  if (currentCaseId && $('cmpCase1')) {
    $('cmpCase1').value = currentCaseId;
  }
  runCompareCases();
}

async function loadCompareView() {
  if (!allCasesCache.length) {
    const { data } = await api('/api/cases');
    allCasesCache = data.cases || [];
  }
  const opts = allCasesCache.map(c => `<option value="${c.case_id}">${c.case_id} — ${c.district} (${c.police_station})</option>`).join('');
  $('cmpCase1').innerHTML = opts;
  $('cmpCase2').innerHTML = opts;

  if (currentCaseId) {
    $('cmpCase1').value = currentCaseId;
    if (allCasesCache.length > 1) {
      const other = allCasesCache.find(c => c.case_id !== currentCaseId);
      if (other) $('cmpCase2').value = other.case_id;
    }
  } else if (allCasesCache.length >= 2) {
    $('cmpCase2').value = allCasesCache[1].case_id;
  }

  $('btnRunCompare').onclick = runCompareCases;
}

async function runCompareCases() {
  const c1 = $('cmpCase1').value;
  const c2 = $('cmpCase2').value;
  if (!c1 || !c2) return;

  $('compareResult').innerHTML = `<div class="card"><div class="dim">Analyzing cross-case intersection between ${c1} and ${c2}…</div></div>`;

  const { ok, data } = await api(`/api/compare?case1=${encodeURIComponent(c1)}&case2=${encodeURIComponent(c2)}`);
  if (!ok) {
    $('compareResult').innerHTML = `<div class="card"><div class="err-msg">Could not compare selected cases.</div></div>`;
    return;
  }

  const s = data.summary;
  $('compareResult').innerHTML = `
    <div class="grid g4 mb14">
      <div class="card kpi ${s.shared_persons > 0 ? 'active-kpi' : ''}">
        <div class="n">${s.shared_persons}</div>
        <div class="l">Shared Persons</div>
      </div>
      <div class="card kpi ${s.shared_phones > 0 ? 'active-kpi' : ''}">
        <div class="n">${s.shared_phones}</div>
        <div class="l">Shared Phones</div>
      </div>
      <div class="card kpi ${s.shared_vehicles > 0 ? 'active-kpi' : ''}">
        <div class="n">${s.shared_vehicles}</div>
        <div class="l">Shared Vehicles</div>
      </div>
      <div class="card kpi ${s.shared_accounts > 0 ? 'active-kpi' : ''}">
        <div class="n">${s.shared_accounts}</div>
        <div class="l">Shared Bank Accounts</div>
      </div>
    </div>

    <div class="grid g2">
      <div class="card">
        <h3>Shared Entity Dossier</h3>
        ${s.total_shared_entities === 0 ? '<div class="dim">No direct shared entities discovered between these two cases.</div>' : ''}
        
        ${data.shared_entities.persons.length ? `
          <div class="mb14">
            <h5 style="color:var(--dim);text-transform:uppercase;font-size:11px;margin:0 0 6px">Persons (${data.shared_entities.persons.length})</h5>
            ${data.shared_entities.persons.map(p => `
              <div class="rc-card" onclick="investigatePerson('${p.id}')">
                <b>👤 ${esc(p.name)}</b> <span class="mono dim">(${esc(p.id)})</span>
              </div>`).join('')}
          </div>` : ''}

        ${data.shared_entities.phones.length ? `
          <div class="mb14">
            <h5 style="color:var(--dim);text-transform:uppercase;font-size:11px;margin:0 0 6px">Phones (${data.shared_entities.phones.length})</h5>
            ${data.shared_entities.phones.map(ph => `
              <div class="rc-card" onclick="investigatePhone('${ph.phone}')">
                <b>📞 ${esc(ph.phone)}</b> ${ph.owner ? `· ${esc(ph.owner)}` : ''}
              </div>`).join('')}
          </div>` : ''}

        ${data.shared_entities.vehicles.length ? `
          <div class="mb14">
            <h5 style="color:var(--dim);text-transform:uppercase;font-size:11px;margin:0 0 6px">Vehicles (${data.shared_entities.vehicles.length})</h5>
            ${data.shared_entities.vehicles.map(v => `
              <div class="rc-card" style="cursor:default">
                <b>🚗 ${esc(v.registration)}</b> · ${esc(v.details)}
              </div>`).join('')}
          </div>` : ''}

        ${data.shared_entities.accounts.length ? `
          <div class="mb14">
            <h5 style="color:var(--dim);text-transform:uppercase;font-size:11px;margin:0 0 6px">Bank Accounts (${data.shared_entities.accounts.length})</h5>
            ${data.shared_entities.accounts.map(a => `
              <div class="rc-card" style="cursor:default">
                <b>🏦 Account: ${esc(a.account)}</b>
              </div>`).join('')}
          </div>` : ''}
      </div>

      <div class="card">
        <h3>Case Quick-Links</h3>
        <div class="card mb14" style="background:var(--panel2)">
          <b>Primary Case: ${esc(data.case_1.case_id)}</b><br>
          <span class="dim">${esc(data.case_1.police_station)} · ${esc(data.case_1.date)}</span><br><br>
          <button class="btn small" onclick="investigateCase('${data.case_1.case_id}')">Open ${data.case_1.case_id} →</button>
        </div>
        <div class="card" style="background:var(--panel2)">
          <b>Comparison Case: ${esc(data.case_2.case_id)}</b><br>
          <span class="dim">${esc(data.case_2.police_station)} · ${esc(data.case_2.date)}</span><br><br>
          <button class="btn small" onclick="investigateCase('${data.case_2.case_id}')">Open ${data.case_2.case_id} →</button>
        </div>
      </div>
    </div>
  `;
}

/* ================================================================ TIMELINE */
function openTimelineForCurrentCase() {
  showView('timeline');
  if (currentCaseId && $('timelineCaseSelect')) {
    $('timelineCaseSelect').value = currentCaseId;
  }
  loadTimelineEvents(currentCaseId);
}

async function loadTimelineView(caseId) {
  if (!allCasesCache.length) {
    const { data } = await api('/api/cases');
    allCasesCache = data.cases || [];
  }
  $('timelineCaseSelect').innerHTML = allCasesCache.map(c => `
    <option value="${c.case_id}">${c.case_id} — ${c.district} (${c.date})</option>`).join('');

  if (caseId) {
    $('timelineCaseSelect').value = caseId;
  }
  
  $('btnRefreshTimeline').onclick = () => loadTimelineEvents($('timelineCaseSelect').value);
  loadTimelineEvents($('timelineCaseSelect').value || caseId);

  // Setup category filter pills
  document.querySelectorAll('.timeline-filters .filter-pill').forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll('.timeline-filters .filter-pill').forEach(b => b.classList.remove('on'));
      btn.classList.add('on');
      currentTimelineFilter = btn.dataset.cat;
      renderTimelineList();
    };
  });
}

async function loadTimelineEvents(caseId) {
  if (!caseId) return;
  $('timelineEvents').innerHTML = '<div class="dim">Gathering chronological case records…</div>';

  const { ok, data } = await api('/api/timeline/' + encodeURIComponent(caseId));
  if (!ok) {
    $('timelineEvents').innerHTML = '<div class="dim">Could not load timeline for this case.</div>';
    return;
  }

  currentTimelineEvents = data.timeline || [];
  renderTimelineList();
}

function renderTimelineList() {
  let list = currentTimelineEvents;
  if (currentTimelineFilter !== 'ALL') {
    list = list.filter(e => e.category === currentTimelineFilter);
  }

  if (!list.length) {
    $('timelineEvents').innerHTML = `<div class="dim">No events recorded under category "${currentTimelineFilter}".</div>`;
    return;
  }

  $('timelineEvents').innerHTML = list.map(e => `
    <div class="tl-item ${e.category}">
      <div class="tl-header">
        <span class="tl-date">${esc(e.timestamp)}</span>
        <span class="pill ${e.category === 'FIR' ? 'high' : (e.category === 'FINANCIAL' ? 'ok' : 'info')}">${esc(e.category)}</span>
      </div>
      <div class="tl-title">${esc(e.title)}</div>
      <div class="tl-desc">${esc(e.description)}</div>
      <div class="dim" style="font-size:11px;margin-top:2px">Source: ${esc(e.source)}</div>
    </div>`).join('');
}

/* ================================================================ INVESTIGATION REPORT */
async function openReportModal(caseId) {
  const modal = $('reportModal');
  const body = $('reportBody');
  modal.style.display = 'flex';
  body.innerHTML = '<div class="dim" style="padding:40px;text-align:center">Compiling investigative brief…</div>';

  const { ok, data } = await api('/api/report/' + encodeURIComponent(caseId));
  if (!ok) {
    body.innerHTML = '<div class="err-msg">Failed to compile investigation report.</div>';
    return;
  }

  const c = data.case;
  body.innerHTML = `
    <div class="report-header-banner">
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div>
          <div class="brand-badge">NEXUS INTELLIGENCE BRIEF · CONFIDENTIAL</div>
          <h1 class="report-title">Case Investigation Report: ${esc(c.case_id)}</h1>
          <div class="dim">Police Station: <b>${esc(c.police_station)}</b> · District: <b>${esc(c.district)}, ${esc(c.state)}</b></div>
          <div class="dim">Report ID: <span class="mono">${esc(data.report_id)}</span> · Generated: <b>${esc(data.generated_at)}</b></div>
        </div>
        <span class="pill ${c.status === 'Closed' ? 'ghost' : 'info'}">${esc(c.status)}</span>
      </div>
    </div>

    <div class="report-disclaimer-box">
      <b>LEGAL DISCLAIMER:</b> ${esc(data.disclaimer)}
    </div>

    <div class="grid g4 mb14">
      <div class="card" style="background:var(--panel2)">
        <div class="n" style="font-size:22px;font-weight:700">${data.metrics.total_entities_2hop}</div>
        <div class="l" style="font-size:10px">Entities in Scope</div>
      </div>
      <div class="card" style="background:var(--panel2)">
        <div class="n" style="font-size:22px;font-weight:700">${data.metrics.relationships_2hop}</div>
        <div class="l" style="font-size:10px">Network Links</div>
      </div>
      <div class="card" style="background:var(--panel2)">
        <div class="n" style="font-size:22px;font-weight:700">${data.metrics.key_leads_count}</div>
        <div class="l" style="font-size:10px">Prioritized Leads</div>
      </div>
      <div class="card" style="background:var(--panel2)">
        <div class="n" style="font-size:22px;font-weight:700">${data.metrics.related_cases_count}</div>
        <div class="l" style="font-size:10px">Companion Cases</div>
      </div>
    </div>

    <div class="card mb14">
      <h3>1. Case Overview & Allegations</h3>
      <div class="kv">
        <div class="k">Date Filed</div><div>${esc(c.date)}</div>
        <div class="k">Sections of Law</div><div>${esc(c.sections_of_law || '—')}</div>
        <div class="k">Complainant</div><div>${esc(c.complainant || '—')}</div>
        <div class="k">Narrative</div><div>${esc(c.description || '—')}</div>
      </div>
    </div>

    <div class="card mb14">
      <h3>2. Key Investigative Leads & Explanations</h3>
      <table style="font-size:12px">
        <thead>
          <tr><th>Priority</th><th>Person Name</th><th>Relevance Score</th><th>Investigative Rationale</th></tr>
        </thead>
        <tbody>
          ${data.key_investigative_leads.map(e => `
            <tr>
              <td><span class="pill ${e.priority}">${e.priority}</span></td>
              <td><b>${esc(e.name)}</b> <span class="mono dim">(${esc(e.person_id)})</span></td>
              <td class="mono">${e.relevance_score}</td>
              <td>${e.reasons.map(r => `✓ ${esc(r)}`).join('<br>')}</td>
            </tr>`).join('') || '<tr><td colspan="4" class="dim">No leads identified.</td></tr>'}
        </tbody>
      </table>
    </div>

    <div class="card mb14">
      <h3>3. Related Cases & Cross-Case Linkages</h3>
      <div class="grid g2">
        ${data.related_cases.map(r => `
          <div class="rc-card" style="cursor:default">
            <b>Case ${esc(r.case_id)}</b> — <span class="pill info">${esc(r.primary_connection || 'Link')}</span><br>
            <span class="dim">${r.reasons.map(x => esc(x.reason)).join(' · ')}</span>
          </div>`).join('') || '<div class="dim">No cross-case linkages detected.</div>'}
      </div>
    </div>

    <div class="card mb14">
      <h3>4. Timeline of Key Events</h3>
      <div style="max-height:220px;overflow-y:auto;padding-right:8px">
        ${data.timeline.slice(0, 15).map(e => `
          <div style="padding:6px 0;border-bottom:1px solid var(--line);font-size:12px">
            <span class="mono dim">${esc(e.timestamp)}</span> · <b>${esc(e.title)}</b><br>
            <span class="dim">${esc(e.description)}</span>
          </div>`).join('') || '<div class="dim">No timeline events recorded.</div>'}
      </div>
    </div>

    <div class="card">
      <h3>5. Active System Alerts</h3>
      ${data.active_alerts.map(a => `
        <div style="padding:6px 0;border-bottom:1px solid var(--line);font-size:12px">
          <span class="pill ${a.severity}">${a.severity}</span> <b>${esc(a.title)}</b><br>
          <span class="dim">${esc(a.detail)}</span>
        </div>`).join('') || '<div class="dim">No anomalies active for this case.</div>'}
    </div>
  `;
}

$('btnCloseReport').onclick = () => { $('reportModal').style.display = 'none'; };
$('btnPrintReport').onclick = () => { window.print(); };

/* ================================================================ CASES REGISTRY */
async function loadCases() {
  const { data } = await api('/api/cases');
  const cases = data.cases || [];
  allCasesCache = cases;
  renderCasesTable(cases);

  $('caseFilterInput').oninput = e => {
    const q = e.target.value.toLowerCase().trim();
    const filtered = allCasesCache.filter(c =>
      c.case_id.toLowerCase().includes(q) ||
      c.district.toLowerCase().includes(q) ||
      c.police_station.toLowerCase().includes(q) ||
      c.status.toLowerCase().includes(q)
    );
    renderCasesTable(filtered);
  };
}

function renderCasesTable(cases) {
  const rows = cases.map(c => `
    <tr class="case-row" onclick="investigateCase('${c.case_id}')">
      <td class="mono"><b>${esc(c.case_id)}</b></td>
      <td>${esc(c.date)}</td>
      <td>${esc(c.police_station)}</td>
      <td>${esc(c.district)}</td>
      <td><span class="pill ${c.status === 'Closed' ? 'ghost' : 'info'}">${esc(c.status)}</span></td>
      <td>${c.total_entities}</td>
      <td><b>${c.related_case_count}</b></td>
      <td><button class="btn small ghost" style="padding:3px 8px;font-size:11px">Investigate →</button></td>
    </tr>`).join('');

  $('casesTbl').innerHTML = `
    <thead>
      <tr><th>FIR ID</th><th>Date</th><th>Police Station</th><th>District</th><th>Status</th><th>Entities</th><th>Related Cases</th><th>Action</th></tr>
    </thead>
    <tbody>${rows || '<tr><td colspan="8" class="dim">No matching cases found.</td></tr>'}</tbody>`;
}

/* ================================================================ UPLOAD / INGESTION */
$('btnUpload').onclick = async () => {
  const file = $('upFile').files[0];
  if (!file) {
    $('uploadResult').innerHTML = '<div class="upload-result fail">Please select a file to upload.</div>';
    return;
  }
  const fd = new FormData();
  fd.append('file', file);
  fd.append('doctype', $('upDoctype').value);
  fd.append('case_id', $('upCaseId').value.trim());

  $('uploadResult').innerHTML = '<div class="dim">Uploading, validating and merging into knowledge graph…</div>';
  const { ok, data } = await api('/api/ingest', { method: 'POST', body: fd });
  
  if (ok && data.records_added > 0) {
    $('uploadResult').innerHTML = `
      <div class="upload-result ok">
        ✓ <b>File processed successfully</b><br>
        ✓ ${data.records_added} of ${data.records_in_file} record(s) validated and appended.<br>
        ✓ Knowledge graph rebuilt immediately without server restart.<br>
        ${data.warnings && data.warnings.length ? '<br>⚠ Warnings:<br>' + data.warnings.slice(0, 4).map(esc).join('<br>') : ''}
        ${data.case_id ? `<br><br><button class="btn small" onclick="investigateCase('${data.case_id}')">Investigate ${data.case_id} Now →</button>` : ''}
      </div>`;
    if (data.case_id) showCaseChecklist(data.case_id);
    loadRecentCases();
    loadHomeStats();
  } else {
    $('uploadResult').innerHTML = `
      <div class="upload-result fail">
        <b>Upload Failed: 0 records processed.</b><br>
        ${(data.errors || []).slice(0, 5).map(esc).join('<br>') || 'Unsupported format or missing required fields.'}
      </div>`;
  }
};

async function showCaseChecklist(caseId) {
  const { ok, data } = await api(`/api/investigation/${encodeURIComponent(caseId)}?hops=1`);
  if (!ok) return;
  const files = new Set(data.graph.edges.map(e => e.source_file).filter(Boolean));
  const need = {
    'fir.csv': 'FIR Report',
    'cdr.csv': 'Call Detail Records (CDR)',
    'bank_transactions.csv': 'Bank Transactions',
    'telecom.csv': 'Telecom Registration',
    'social_connections.csv': 'Social Network',
    'vehicles.csv': 'Vehicles'
  };
  $('caseDataStatus').style.display = '';
  $('caseChecklist').innerHTML = Object.entries(need).map(([f, label]) => `
    <div class="check-item ${files.has(f) || f === 'fir.csv' ? 'have' : ''}">
      ${files.has(f) || f === 'fir.csv' ? '✓' : '○'} ${label}
    </div>`).join('');
}

/* ================================================================ ALERTS */
async function loadAlerts() {
  const { data } = await api('/api/alerts');
  const list = data.alerts || [];
  $('alertBadge').textContent = list.length;
  $('alertsList').innerHTML = list.map(a => `
    <div class="alert-card ${a.severity}">
      <div class="h">
        <span class="pill ${a.severity}">${a.severity}</span>
        <span class="t">${esc(a.title)}</span>
      </div>
      <div class="d">${esc(a.detail)}</div>
      <div class="tech-note">
        <b>Technical Evidence:</b> ${esc(a.technical_details || a.evidence)}
        ${a.entities && a.entities.length ? `· <b>Entities:</b> ${esc(a.entities.join(', '))}` : ''}
      </div>
    </div>`).join('') || '<div class="dim">No active alerts.</div>';
}

/* ================================================================ DATA SOURCES */
async function loadDataSources() {
  const { data } = await api('/api/data-sources');
  const sources = data.sources || [];
  $('dataSourcesTbl').innerHTML = `
    <thead>
      <tr><th>Source Category</th><th>Physical CSV File</th><th>Active Records</th><th>Status</th></tr>
    </thead>
    <tbody>
      ${sources.map(s => `
        <tr>
          <td><b>${esc(s.name)}</b></td>
          <td class="mono">${esc(s.file)}</td>
          <td><b>${s.records.toLocaleString()}</b></td>
          <td><span class="pill ok">Loaded & Active</span></td>
        </tr>`).join('')}
    </tbody>`;
}

/* ================================================================ ADVANCED ANALYTICS */
document.querySelectorAll('.tabs button').forEach(b => {
  b.onclick = () => {
    document.querySelectorAll('.tabs button').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    document.querySelectorAll('.adv-pane').forEach(p => p.style.display = 'none');
    $('adv-' + b.dataset.tab).style.display = '';
    if (b.dataset.tab === 'disruption') loadDisruptionOptions();
    if (b.dataset.tab === 'crosscase') loadCrossCase();
    if (b.dataset.tab === 'linkpred') loadLinkPredictions();
    if (b.dataset.tab === 'audit') loadAudit();
  };
});

async function loadAdvanced() {
  const { data } = await api('/api/analytics/global');
  $('advKpis').innerHTML = [
    ['Top influencers tracked', data.top_influencers ? data.top_influencers.length : 0],
    ['Communities detected', data.communities || 0],
    ['Articulation points', data.articulation_points ? data.articulation_points.length : 0],
  ].map(([l, n]) => `
    <div class="card kpi"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');

  $('influenceTbl').innerHTML = `
    <thead>
      <tr><th>#</th><th>Name</th><th>PageRank</th><th>Degree</th><th>Betweenness</th><th>Closeness</th><th>Eigenvector</th><th>Bridge?</th></tr>
    </thead>
    <tbody>
      ${(data.top_influencers || []).map((p, i) => `
        <tr>
          <td>${i + 1}</td>
          <td><b>${esc(p.name)}</b></td>
          <td class="mono">${p.pagerank}</td>
          <td class="mono">${p.degree_centrality}</td>
          <td class="mono">${p.betweenness}</td>
          <td class="mono">${p.closeness || 0}</td>
          <td class="mono">${p.eigenvector || 0}</td>
          <td>${p.is_articulation_point ? '<span class="pill crit">CUT-VERTEX</span>' : ''}</td>
        </tr>`).join('')}
    </tbody>`;
}

async function loadDisruptionOptions() {
  const { data } = await api('/api/analytics/persons');
  $('disruptTarget').innerHTML = (data.persons || []).map(p => `
    <option value="${esc(p.entity_id)}">${esc(p.name)} (${esc(p.person_id)})</option>`).join('');
}

$('btnSimulate').onclick = async () => {
  const id = $('disruptTarget').value;
  const { ok, data } = await api('/api/analytics/disruption/' + encodeURIComponent(id));
  if (!ok) return;
  const critical = data.is_articulation_point;
  $('disruptResult').innerHTML = `
    <div class="banner ${critical ? 'crit' : 'ok'}" style="margin-top:14px">
      <b>${critical ? '⚠ CRITICAL BRIDGE IDENTIFIED' : '✓ Non-Critical Node'}</b> —
      Simulated removal of <b>${esc(data.name)}</b>:
      Connected network components: ${data.components_before} → <b>${data.components_after}</b>.
      Largest connected group: ${data.largest_before} → <b>${data.largest_after}</b> individuals.
      Network fragmentation impact: <b>${data.fragmentation_pct}%</b>.
    </div>`;
};

async function loadCrossCase() {
  const { data } = await api('/api/cross-case');
  const entries = Object.entries(data.cross_case_links || {});
  $('crossCaseList').innerHTML = entries.length ? entries.map(([cid, rel]) => `
    <div class="rc-card" style="cursor:default;margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;margin-bottom:6px">
        <b>Case ${esc(cid)}</b>
        <button class="btn small ghost" style="padding:2px 8px;font-size:11px" onclick="investigateCase('${cid}')">Open Case →</button>
      </div>
      ${rel.map(r => `
        <div style="font-size:12px;margin-top:4px">
          ↔ Linked with <b>${esc(r.case_id)}</b> via ${r.reasons.map(x => esc(x.shared_entity_type)).join(', ')}
        </div>`).join('')}
    </div>`).join('') : '<div class="dim">No cross-case linkages found.</div>';
}

async function loadLinkPredictions() {
  const { data } = await api('/api/analytics/global');
  const preds = data.link_predictions || [];
  $('linkPredTbl').innerHTML = `
    <thead>
      <tr><th>Entity A</th><th>Entity B</th><th>Predicted Proximity</th><th>Investigative Context</th></tr>
    </thead>
    <tbody>
      ${preds.map(p => `
        <tr>
          <td><b>${esc(p.source)}</b></td>
          <td><b>${esc(p.target)}</b></td>
          <td class="mono"><b>${p.jaccard_score}</b></td>
          <td>${esc(p.rationale)}</td>
        </tr>`).join('') || '<tr><td colspan="4" class="dim">No high-probability unlinked pairs found.</td></tr>'}
    </tbody>`;
}

async function loadAudit() {
  const { data } = await api('/api/audit');
  $('ledgerTbl').innerHTML = `
    <thead>
      <tr><th>Seq #</th><th>Timestamp</th><th>Actor</th><th>Action</th><th>Subject</th><th>Block Hash</th></tr>
    </thead>
    <tbody>
      ${(data.ledger || []).slice().reverse().map(b => `
        <tr>
          <td class="mono dim">${b.index}</td>
          <td class="mono" style="font-size:11px">${esc(b.ts)}</td>
          <td class="mono">${esc(b.actor)}</td>
          <td><span class="pill info">${esc(b.action)}</span></td>
          <td>${esc(b.subject)}</td>
          <td class="mono dim" style="font-size:10px">${esc(b.hash.slice(0, 16))}…</td>
        </tr>`).join('')}
    </tbody>`;
}

$('btnVerifyChain').onclick = async () => {
  $('verifyStatus').textContent = 'Verifying cryptographic chain…';
  const { data } = await api('/api/audit/verify');
  if (data.ok) {
    $('chainBanner').innerHTML = `
      <div class="banner ok" style="margin-top:14px">
        <b>✓ CHAIN INTEGRITY VERIFIED</b> — All ${data.count} SHA-256 blocks validated without tampering.
      </div>`;
    $('verifyStatus').textContent = 'Integrity verified ✓';
  } else {
    $('chainBanner').innerHTML = `
      <div class="banner crit" style="margin-top:14px">
        <b>✕ CHAIN INTEGRITY BROKEN</b> — Hash mismatch detected at sequence #${data.at}.
      </div>`;
    $('verifyStatus').textContent = 'Integrity compromised ✕';
  }
};

/* ================================================================ INITIALIZATION */
loadRecentCases();
loadHomeStats();
loadAlerts();
