const API = window.location.origin;
let TOKEN = localStorage.getItem("adr_token") || null;
let ROLE = localStorage.getItem("adr_role") || "VIEWER";
let USERNAME = localStorage.getItem("adr_user") || "anonymous";

// Require a real login before showing the dashboard at all.
if (!TOKEN) {
  window.location.href = "login.html";
}

const $main = document.getElementById("main");

document.getElementById("logoutBtn").addEventListener("click", () => {
  localStorage.removeItem("adr_token");
  localStorage.removeItem("adr_role");
  localStorage.removeItem("adr_user");
  window.location.href = "login.html";
});

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  if (opts.body && !(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(API + path, { ...opts, headers });
  if (res.status === 401) {
    localStorage.removeItem("adr_token");
    localStorage.removeItem("adr_role");
    localStorage.removeItem("adr_user");
    window.location.href = "login.html";
    throw new Error("session expired");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "request failed");
  }
  return res.headers.get("content-type")?.includes("json") ? res.json() : res.text();
}

document.querySelectorAll(".nav-item").forEach((el) => {
  el.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
    el.classList.add("active");
    route(el.dataset.page);
  });
});

let currentPage = "dashboard";
function route(page) {
  currentPage = page;
  const renderers = {
    dashboard: renderDashboard, ask: renderAsk, documents: renderDocuments,
    resolver: renderResolver, approvals: renderApprovals, override: renderOverride,
    audit: renderAudit, eval: renderEval, settings: renderSettings,
  };
  (renderers[page] || renderDashboard)();
}

function statusBadge(status) {
  return `<span class="badge ${status}">${status}</span>`;
}

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

// ---------------------------------------------------------------- DASHBOARD
async function renderDashboard() {
  $main.innerHTML = `<h1>Dashboard</h1><div class="subtitle">Organization-wide authority &amp; audit posture</div><div id="kpis" class="grid"></div>
  <div class="panel"><h3>Recent Audit Events</h3><div id="recentAudit">Loading…</div></div>
  <div class="panel"><h3>Dataset Controls</h3>
    <p class="subtitle" style="margin-top:-6px">Generates the full synthetic evaluation dataset (documents, versions, approvals, owners, access rules, ground-truth queries). Requires ADMIN.</p>
    <button id="seedBtn">Regenerate Synthetic Dataset</button>
  </div>`;
  document.getElementById("seedBtn").addEventListener("click", async () => {
    try {
      const stats = await api("/api/admin/seed", { method: "POST" });
      toast(`Seeded: ${stats.documents} docs, ${stats.versions} versions, ${stats.approvals} approvals`);
      renderDashboard();
    } catch (e) { toast("Error: " + e.message); }
  });
  try {
    const d = await api("/api/dashboard");
    document.getElementById("kpis").innerHTML = [
      ["Total Documents", d.total_documents], ["Total Versions", d.total_versions],
      ["Approved Versions", d.approved_versions], ["Draft Versions", d.draft_versions],
      ["Authoritative Docs", d.authoritative_documents], ["Manual Overrides", d.manual_overrides],
      ["Authority Conflicts", d.authority_conflicts],
    ].map(([label, v]) => `<div class="card"><div class="kpi">${v}</div><div class="label">${label}</div></div>`).join("");
    document.getElementById("recentAudit").innerHTML = renderAuditTable(d.recent_audit_events);
  } catch (e) {
    document.getElementById("kpis").innerHTML = `<div class="card"><div class="label">No data yet — click "Regenerate Synthetic Dataset" below.</div></div>`;
  }
}

function renderAuditTable(events) {
  if (!events || !events.length) return "<p class='subtitle'>No events yet.</p>";
  return `<table><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Document</th><th>Reason</th></tr></thead><tbody>
    ${events.map(e => `<tr><td class="mono">${(e.timestamp||"").slice(0,19)}</td><td>${e.user||"-"}</td><td>${e.action}</td><td class="mono">${e.document_id||"-"}</td><td>${e.reason||"-"}</td></tr>`).join("")}
  </tbody></table>`;
}

// --------------------------------------------------------------------- ASK
async function renderAsk() {
  $main.innerHTML = `<h1>Ask AI</h1><div class="subtitle">Answers are generated ONLY from the authority-resolved source document.</div>
  <div class="ask-box"><input id="q" placeholder="e.g. What authentication architecture is currently approved?"/><button id="askBtn">Ask</button></div>
  <div id="answerArea"></div>`;
  document.getElementById("askBtn").addEventListener("click", doAsk);
  document.getElementById("q").addEventListener("keydown", (e) => { if (e.key === "Enter") doAsk(); });
}

async function doAsk() {
  const q = document.getElementById("q").value.trim();
  if (!q) return;
  const area = document.getElementById("answerArea");
  area.innerHTML = "<p class='subtitle'>Resolving authoritative source…</p>";
  try {
    const r = await api("/api/ask", { method: "POST", body: JSON.stringify({ question: q }) });
    if (r.access_denied) { area.innerHTML = `<div class="conflict-banner">${r.answer}</div>`; return; }
    let banner = "";
    if (r.conflict) banner += `<div class="conflict-banner">⚠ AUTHORITY CONFLICT — Conflicting approval records detected for this version. Manual review required.</div>`;
    if (r.is_override) banner += `<div class="override-banner">MANUAL OVERRIDE ACTIVE — ${r.override_reason || ""}</div>`;
    area.innerHTML = `
      ${banner}
      <div class="answer-block">
        <div class="answer-text">${r.answer}</div>
        <div class="source-grid">
          <div><span class="k">Authoritative Document:</span> ${r.document_title}</div>
          <div><span class="k">Version:</span> v${r.version_number}</div>
          <div><span class="k">Status:</span> ${statusBadge(r.status)}</div>
          <div><span class="k">Grounded:</span> ${r.grounded ? "Yes" : "No — insufficient evidence"}</div>
          <div><span class="k">Citation:</span> Section ${r.citation.section}, Page ${r.citation.page}</div>
          <div><span class="k">Authority Score:</span> <span class="score-big">${r.authority_score}%</span></div>
        </div>
        <h3 style="margin-top:16px">Why This Source?</h3>
        ${Object.entries(r.breakdown).map(([k, v]) => `<div class="breakdown-row"><span>${k}</span><span>${v.points} / ${v.max}</span></div>`).join("")}
        <p class="subtitle" style="margin-top:10px">${r.relevance_note}</p>
      </div>
      <div class="panel" style="margin-top:16px"><h3>Feedback</h3>
        <div class="pill-row">
          <button class="secondary" onclick="sendFeedback('${q.replace(/'/g,"")}', true)">👍 Helpful</button>
          <button class="secondary" onclick="sendFeedback('${q.replace(/'/g,"")}', false)">👎 Not helpful</button>
        </div>
      </div>`;
  } catch (e) {
    area.innerHTML = `<div class="conflict-banner">Error: ${e.message}</div>`;
  }
}

async function sendFeedback(query, positive) {
  await api("/api/feedback", {
    method: "POST",
    body: JSON.stringify({
      query, answer_clear: positive, source_clear: positive, citation_useful: positive,
      increased_trust: positive, would_use: positive,
    }),
  });
  toast("Thanks for the feedback!");
}

// --------------------------------------------------------------- DOCUMENTS
async function renderDocuments() {
  $main.innerHTML = `<h1>Documents</h1><div class="subtitle">All architecture decision documents and their version counts.</div>
  <div id="docTable">Loading…</div>
  <div class="panel"><h3>Upload New Version</h3>
    <form id="uploadForm">
      <label>File (.pdf, .docx, .txt)</label><input type="file" name="file" required/>
      <label>Document Title</label><input type="text" name="title" required/>
      <label>Document ID (existing or new)</label><input type="text" name="document_id" required placeholder="doc-001"/>
      <label>Owner</label><select name="owner_id" id="ownerSelect"></select>
      <label>Status</label>
      <select name="status"><option>DRAFT</option><option>APPROVED</option><option>PENDING_REVIEW</option><option>REJECTED</option><option>SUPERSEDED</option><option>ARCHIVED</option></select>
      <div style="margin-top:12px"><button type="submit">Upload &amp; Ingest</button></div>
    </form>
  </div>`;
  const owners = await api("/api/owners");
  document.getElementById("ownerSelect").innerHTML = owners.map(o => `<option value="${o.id}">${o.name} (${o.authority_level})</option>`).join("");
  const docs = await api("/api/documents");
  document.getElementById("docTable").innerHTML = `<table><thead><tr><th>Title</th><th>ID</th><th>Versions</th><th>Authoritative Version</th><th>Access</th></tr></thead><tbody>
    ${docs.map(d => `<tr onclick="openDoc('${d.id}')" style="cursor:pointer"><td>${d.title}</td><td class="mono">${d.id}</td><td>${d.version_count}</td><td class="mono">${d.authoritative_version || "-"} ${d.is_override ? "🔒" : ""}</td><td>${d.accessible ? "✅" : "🚫"}</td></tr>`).join("")}
  </tbody></table>`;

  document.getElementById("uploadForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await api("/api/documents/upload", { method: "POST", body: fd });
      toast("Uploaded and ingested.");
      renderDocuments();
    } catch (err) { toast("Error: " + err.message); }
  });
}

async function openDoc(id) {
  document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
  document.querySelector('[data-page="resolver"]').classList.add("active");
  await renderResolver(id);
}

// -------------------------------------------------------------- RESOLVER
async function renderResolver(preselectDoc) {
  $main.innerHTML = `<h1>Authority Resolver</h1><div class="subtitle">Compare BASELINE (newest-wins) vs PROPOSED (authority-scored) resolution.</div>
  <label>Select Document</label><select id="docSelect"></select>
  <div id="resolverResult" style="margin-top:16px"></div>`;
  const docs = await api("/api/documents");
  const sel = document.getElementById("docSelect");
  sel.innerHTML = docs.map(d => `<option value="${d.id}">${d.title} (${d.id})</option>`).join("");
  if (preselectDoc) sel.value = preselectDoc;
  sel.addEventListener("change", () => loadResolver(sel.value));
  if (docs.length) loadResolver(sel.value);
}

async function loadResolver(docId) {
  const area = document.getElementById("resolverResult");
  area.innerHTML = "Loading…";
  try {
    const [proposed, baseline, detail] = await Promise.all([
      api(`/api/authority/${docId}`), api(`/api/authority/${docId}/baseline`), api(`/api/documents/${docId}`),
    ]);
    area.innerHTML = `
      ${proposed.conflict ? `<div class="conflict-banner">⚠ AUTHORITY CONFLICT — Conflicting approval records detected. Manual review required.</div>` : ""}
      ${proposed.is_override ? `<div class="override-banner">MANUAL OVERRIDE ACTIVE — ${proposed.override_reason}</div>` : ""}
      <div class="metric-compare">
        <div class="col"><h4>BASELINE (newest wins)</h4>
          <div class="row"><span>Version</span><span>v${baseline.version.version_number}</span></div>
          <div class="row"><span>Status</span><span>${statusBadge(baseline.version.status)}</span></div>
          <div class="row"><span>Modified</span><span class="mono">${baseline.version.modified_date.slice(0,10)}</span></div>
        </div>
        <div class="col"><h4>PROPOSED (authority resolver)</h4>
          <div class="row"><span>Version</span><span>v${proposed.version.version_number}</span></div>
          <div class="row"><span>Status</span><span>${statusBadge(proposed.version.status)}</span></div>
          <div class="row"><span>Authority Score</span><span class="score-big">${proposed.score}%</span></div>
        </div>
      </div>
      <div class="panel" style="margin-top:16px"><h3>Score Breakdown (Proposed)</h3>
        ${Object.entries(proposed.breakdown).map(([k,v]) => `<div class="breakdown-row"><span>${k} (weight ${(v.weight*100).toFixed(0)}%)</span><span>${v.points} / ${v.max}</span></div>`).join("")}
      </div>
      <div class="panel"><h3>All Versions</h3>
        <table><thead><tr><th>Version</th><th>Status</th><th>Owner</th><th>Modified</th><th>Approvals</th></tr></thead><tbody>
        ${detail.versions.map(v => `<tr><td>v${v.version_number}${v.id===proposed.version.id?' ⭐':''}</td><td>${statusBadge(v.status)}</td><td>${v.owner_id}</td><td class="mono">${v.modified_date.slice(0,10)}</td><td>${v.approvals.map(a=>`${a.approver_name}:${a.decision}`).join(", ")||"-"}</td></tr>`).join("")}
        </tbody></table>
      </div>`;
  } catch (e) { area.innerHTML = `<div class="conflict-banner">Error: ${e.message}</div>`; }
}

// ------------------------------------------------------------- APPROVALS
async function renderApprovals() {
  $main.innerHTML = `<h1>Approvals</h1><div class="subtitle">Approval records across all documents. Conflicting decisions are flagged in the resolver.</div>
  <label>Select Document</label><select id="apDocSelect"></select>
  <div id="apArea" style="margin-top:14px"></div>`;
  const docs = await api("/api/documents");
  document.getElementById("apDocSelect").innerHTML = docs.map(d => `<option value="${d.id}">${d.title}</option>`).join("");
  document.getElementById("apDocSelect").addEventListener("change", (e) => loadApprovals(e.target.value));
  if (docs.length) loadApprovals(docs[0].id);
}
async function loadApprovals(docId) {
  const detail = await api(`/api/documents/${docId}`);
  document.getElementById("apArea").innerHTML = detail.versions.map(v => `
    <div class="panel"><h3>v${v.version_number} — ${statusBadge(v.status)}</h3>
    ${v.approvals.length ? `<table><thead><tr><th>Approver</th><th>Decision</th><th>Date</th><th>Reason</th></tr></thead><tbody>
      ${v.approvals.map(a=>`<tr><td>${a.approver_name}</td><td>${statusBadge(a.decision)}</td><td class="mono">${a.date.slice(0,10)}</td><td>${a.reason||"-"}</td></tr>`).join("")}
    </tbody></table>` : "<p class='subtitle'>No approval records.</p>"}
    </div>`).join("");
}

// -------------------------------------------------------------- OVERRIDE
async function renderOverride() {
  if (ROLE !== "ADMIN") {
    $main.innerHTML = `<h1>Manual Override</h1><div class="conflict-banner">Administrator role required. Switch to "admin" in the session selector.</div>`;
    return;
  }
  $main.innerHTML = `<h1>Manual Override</h1><div class="subtitle">Administrators may override the automatically resolved authoritative version. A reason is required and fully audited.</div>
  <label>Select Document</label><select id="ovDocSelect"></select>
  <div id="ovArea" style="margin-top:14px"></div>`;
  const docs = await api("/api/documents");
  document.getElementById("ovDocSelect").innerHTML = docs.map(d => `<option value="${d.id}">${d.title}</option>`).join("");
  document.getElementById("ovDocSelect").addEventListener("change", (e) => loadOverride(e.target.value));
  if (docs.length) loadOverride(docs[0].id);
}
async function loadOverride(docId) {
  const [detail, current] = await Promise.all([api(`/api/documents/${docId}`), api(`/api/authority/${docId}`)]);
  document.getElementById("ovArea").innerHTML = `
    ${current.is_override ? `<div class="override-banner">MANUAL OVERRIDE ACTIVE on v${current.version.version_number} — ${current.override_reason}</div><button id="rollbackBtn" class="secondary">Rollback to Previous Authority</button>` : ""}
    <div class="panel"><h3>Choose Version to Make Authoritative</h3>
      <select id="ovVersionSelect">${detail.versions.map(v => `<option value="${v.id}" ${v.id===current.version.id?"selected":""}>v${v.version_number} — ${v.status}</option>`).join("")}</select>
      <label>Reason (required)</label><textarea id="ovReason" rows="3" placeholder="Explain why this version should be authoritative..."></textarea>
      <div style="margin-top:12px"><button id="ovSubmit">Apply Override</button></div>
    </div>`;
  document.getElementById("ovSubmit").addEventListener("click", async () => {
    try {
      await api(`/api/authority/${docId}/override`, {
        method: "POST",
        body: JSON.stringify({ version_id: document.getElementById("ovVersionSelect").value, reason: document.getElementById("ovReason").value }),
      });
      toast("Override applied.");
      loadOverride(docId);
    } catch (e) { toast("Error: " + e.message); }
  });
  const rb = document.getElementById("rollbackBtn");
  if (rb) rb.addEventListener("click", async () => {
    try { await api(`/api/authority/${docId}/rollback`, { method: "POST" }); toast("Rolled back."); loadOverride(docId); }
    catch (e) { toast("Error: " + e.message); }
  });
}

// ----------------------------------------------------------------- AUDIT
async function renderAudit() {
  $main.innerHTML = `<h1>Audit Trail</h1><div class="subtitle">Immutable log of every authority-affecting event. No delete/edit path exists from the UI.</div><div id="auditTable">Loading…</div>`;
  const events = await api("/api/audit?limit=300");
  document.getElementById("auditTable").innerHTML = renderAuditTable(events);
}

// ------------------------------------------------------------------ EVAL
async function renderEval() {
  $main.innerHTML = `<h1>Test / Evaluation</h1><div class="subtitle">Runs the ground-truth query set through both resolvers and computes real metrics — nothing is hardcoded.</div>
  <div class="pill-row"><button id="runBaseline">Run Baseline</button><button id="runProposed">Run Proposed</button></div>
  <div id="evalResults" style="margin-top:16px"></div>
  <div class="panel"><h3>Stakeholder Feedback Summary</h3><div id="fbSummary">Loading…</div></div>`;
  document.getElementById("runBaseline").addEventListener("click", () => runEval("baseline"));
  document.getElementById("runProposed").addEventListener("click", () => runEval("proposed"));
  loadEvalHistory();
  const fb = await api("/api/feedback/summary");
  document.getElementById("fbSummary").innerHTML = fb.count ? `
    <div class="row breakdown-row"><span>Responses</span><span>${fb.count}</span></div>
    <div class="row breakdown-row"><span>Answer Clear</span><span>${fb.answer_clear_pct}%</span></div>
    <div class="row breakdown-row"><span>Source Clear</span><span>${fb.source_clear_pct}%</span></div>
    <div class="row breakdown-row"><span>Citation Useful</span><span>${fb.citation_useful_pct}%</span></div>
    <div class="row breakdown-row"><span>Increased Trust</span><span>${fb.increased_trust_pct}%</span></div>
    <div class="row breakdown-row"><span>Would Use</span><span>${fb.would_use_pct}%</span></div>
  ` : "<p class='subtitle'>No feedback submitted yet — use the Ask AI page.</p>";
}
async function runEval(mode) {
  const area = document.getElementById("evalResults");
  area.innerHTML = "Running evaluation over ground-truth query set…";
  try {
    const r = await api(`/api/eval/run?mode=${mode}`, { method: "POST" });
    toast(`${mode} run complete: ${r.authority_selection_accuracy}% accuracy`);
    loadEvalHistory();
  } catch (e) { area.innerHTML = `<div class="conflict-banner">${e.message}</div>`; }
}
async function loadEvalHistory() {
  const results = await api("/api/eval/results");
  const area = document.getElementById("evalResults");
  if (!results.length) { area.innerHTML = "<p class='subtitle'>No evaluation runs yet.</p>"; return; }
  area.innerHTML = `<table><thead><tr><th>Run</th><th>Mode</th><th>Authority Acc.</th><th>Citation Acc.</th><th>Access Acc.</th><th>Conflict Det.</th><th>Errors</th></tr></thead><tbody>
    ${results.map(r => `<tr><td class="mono">${r.run_id}</td><td>${r.mode}</td><td>${r.authority_selection_accuracy}%</td><td>${r.citation_accuracy}%</td><td>${r.access_control_accuracy}%</td><td>${r.conflict_detection_accuracy ?? "n/a"}</td><td>${r.error_count}</td></tr>`).join("")}
  </tbody></table>`;
}

// -------------------------------------------------------------- SETTINGS
async function renderSettings() {
  $main.innerHTML = `<h1>Settings</h1><div class="subtitle">Configurable scoring weights. Must sum to 1.0. ADMIN only.</div><div id="settingsArea">Loading…</div>`;
  const cfg = await api("/api/settings");
  const readonly = ROLE !== "ADMIN";
  document.getElementById("settingsArea").innerHTML = `
    <div class="panel"><h3>Authority Score Weights</h3>
      ${Object.entries(cfg.weights).map(([k, v]) => `
        <label>${k} (${(v*100).toFixed(0)}%)</label>
        <input type="number" step="0.01" min="0" max="1" id="w_${k}" value="${v}" ${readonly ? "disabled" : ""}/>
      `).join("")}
      <div style="margin-top:12px"><button id="saveWeights" ${readonly ? "disabled" : ""}>Save Weights</button></div>
    </div>
    <div class="panel"><h3>Status Scores</h3>
      ${Object.entries(cfg.status_scores).map(([k, v]) => `<div class="breakdown-row"><span>${k}</span><span>${v}</span></div>`).join("")}
    </div>
    <div class="panel"><h3>AI Provider</h3>
      <div class="breakdown-row"><span>Provider</span><span>${cfg.ai_provider}</span></div>
      <div class="breakdown-row"><span>Model</span><span>${cfg.ai_model}</span></div>
      <p class="subtitle">Set ADR_LLM_API_KEY env var to switch from the offline mock provider to a live LLM.</p>
    </div>`;
  if (!readonly) {
    document.getElementById("saveWeights").addEventListener("click", async () => {
      const weights = {};
      Object.keys(cfg.weights).forEach(k => weights[k] = parseFloat(document.getElementById(`w_${k}`).value));
      try { await api("/api/settings", { method: "POST", body: JSON.stringify({ weights }) }); toast("Weights saved."); }
      catch (e) { toast("Error: " + e.message); }
    });
  }
}

// ------------------------------------------------------------------ INIT
(function init() {
  document.getElementById("whoami").textContent = `${USERNAME} (${ROLE})`;
  route("dashboard");
})();
