const API = "http://localhost:8000";
let TOKEN = localStorage.getItem("adr_token") || null;
let ROLE = localStorage.getItem("adr_role") || "VIEWER";
let USERNAME = localStorage.getItem("adr_user") || "anonymous";
const DEMO_USERS = [
  { username: "admin", password: "admin123", role: "ADMIN" },
  { username: "architect1", password: "architect123", role: "ARCHITECT" },
  { username: "engineer1", password: "engineer123", role: "ENGINEER" },
  { username: "viewer1", password: "viewer123", role: "VIEWER" },
];
const DEMO_PASSWORDS = Object.fromEntries(DEMO_USERS.map((u) => [u.username, u.password]));
const ROLE_GUIDES = {
  ADMIN: {
    dashboard: {
      summary: "This page shows the whole operating picture: document count, version health, override activity, and conflict risk.",
      points: [
        "Use it to confirm the business stays available and trustworthy.",
        "Watch conflicts and overrides to protect integrity before a wrong decision spreads.",
        "Review the audit trail for accountability and quick incident response.",
      ],
      cia: "Confidentiality: only trusted admins should change authority. Integrity: every override is logged and reasoned. Availability: the dashboard keeps critical status visible at a glance.",
    },
    documents: {
      summary: "This page is your registry of every decision document and its versions.",
      points: [
        "Upload and review new policy or architecture drafts.",
        "Track which version is authoritative and whether it was manually overridden.",
        "Make sure all changes are connected to a clear owner and audit trail.",
      ],
      cia: "Confidentiality: restrict document access by role. Integrity: verify version status before publishing. Availability: keep current documents ready for decision-making.",
    },
  },
  ARCHITECT: {
    dashboard: {
      summary: "This page tells you whether decisions are stable, approved, and ready for design work.",
      points: [
        "Check which versions are approved and which are still draft.",
        "See whether there are conflicts that need clarification before design teams rely on the output.",
        "Understand the current authoritative state before proposing changes.",
      ],
      cia: "Confidentiality: only approved content should be shared beyond the team. Integrity: architectural changes must be traceable to the correct version. Availability: the dashboard helps teams find the current source quickly.",
    },
    documents: {
      summary: "Use this page to manage the lifecycle of architecture documents and control which version is trusted.",
      points: [
        "Upload a new policy or architecture version when a design decision changes.",
        "Compare older and newer versions to make sure the right version becomes authoritative.",
        "Review owner and approval history to keep decisions defensible.",
      ],
      cia: "Confidentiality: keep draft design content limited to stakeholders. Integrity: only the right architecture version should be selected. Availability: make the active decision version easy to find.",
    },
  },
  ENGINEER: {
    dashboard: {
      summary: "This page helps you see what the business is currently approved to do and what is still under review.",
      points: [
        "Use it to understand the latest approved decisions that affect implementation.",
        "Review conflicts so your work does not follow a stale or rejected version.",
        "Check whether the current source is actively trusted by the organization.",
      ],
      cia: "Confidentiality: do not expose internal decision details outside the team. Integrity: follow only the authority-resolved version. Availability: quick visibility into the active version reduces wasted engineering effort.",
    },
    documents: {
      summary: "This page shows the documents that matter to engineering work and the status of each version.",
      points: [
        "Open the exact document that defines a policy, platform decision, or design rule.",
        "Check version count and whether the document is accessible to your role.",
        "Use the authoritative version to reduce drift between engineering decisions and approved standards.",
      ],
      cia: "Confidentiality: limit access to sensitive design data. Integrity: use the approved version, not an informal draft. Availability: make the active document easy to locate and read.",
    },
  },
  VIEWER: {
    dashboard: {
      summary: "This page gives a simple status view without exposing sensitive decision management details.",
      points: [
        "See the health of the document set and whether there are unresolved conflicts.",
        "Understand the current posture without editing policy or approvals.",
        "Use the audit trail only as a visible record of important events.",
      ],
      cia: "Confidentiality: you only see the approved, role-appropriate view. Integrity: the dashboard shows what is trusted and what is flagged. Availability: the summary makes status visible to people who need awareness without changing the system.",
    },
    documents: {
      summary: "This page lets you view the documents that are available to your role and understand which version is currently trusted.",
      points: [
        "Review approved documents and understand whether access is allowed for your role.",
        "Check version history to see how a decision has changed over time.",
        "Use the authoritative version to understand the final accepted state.",
      ],
      cia: "Confidentiality: viewers see only permitted documents. Integrity: you are shown the authoritative state, not random drafts. Availability: decision information is presented in a simple, readable way.",
    },
  },
};

const $main = document.getElementById("main");
const $app = document.getElementById("app");
const $loginScreen = document.getElementById("loginScreen");
const $aiChatPanel = document.getElementById("aiChatPanel");
const $aiChatMessages = document.getElementById("aiChatMessages");
const $aiChatOptions = document.getElementById("aiChatOptions");
const $closeAiChat = document.getElementById("closeAiChat");
const QUICK_QUESTIONS = [
  { label: "Show the currently approved authentication architecture", question: "What authentication architecture is currently approved?" },
  { label: "Which version is authoritative right now?", question: "Which version of the architecture decision is authoritative right now?" },
  { label: "Explain the access rules for my role", question: "What access rules apply to my role?" },
  { label: "Are there any authority conflicts?", question: "Are there any authority conflicts in the current decisions?" },
];

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  if (opts.body && !(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(API + path, { ...opts, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "request failed");
  }
  return res.headers.get("content-type")?.includes("json") ? res.json() : res.text();
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[character]));
}

async function login(username, passwordOverride) {
  const password = passwordOverride ?? DEMO_PASSWORDS[username];
  const data = await api("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  TOKEN = data.token; ROLE = data.role; USERNAME = data.username;
  localStorage.setItem("adr_token", TOKEN);
  localStorage.setItem("adr_role", ROLE);
  localStorage.setItem("adr_user", USERNAME);
  document.getElementById("whoami").textContent = `${USERNAME} (${ROLE})`;
  showApp();
}

function showLogin() {
  $app.classList.add("hidden");
  $loginScreen.classList.remove("hidden");
}

function showApp() {
  $loginScreen.classList.add("hidden");
  $app.classList.remove("hidden");
  if (document.getElementById("roleSwitch")) {
    document.getElementById("roleSwitch").value = USERNAME;
    document.getElementById("whoami").textContent = `${USERNAME} (${ROLE})`;
  }
}

document.getElementById("roleSwitch").addEventListener("change", async (e) => {
  await login(e.target.value);
  route(currentPage);
});

document.getElementById("logoutBtn").addEventListener("click", () => {
  localStorage.removeItem("adr_token");
  localStorage.removeItem("adr_role");
  localStorage.removeItem("adr_user");
  TOKEN = null; ROLE = "VIEWER"; USERNAME = "anonymous";
  showLogin();
});

document.querySelectorAll(".user-login-card").forEach((button) => {
  button.addEventListener("click", async () => {
    const username = button.dataset.user;
    await login(username);
    route(currentPage);
  });
});

document.getElementById("manualLoginBtn").addEventListener("click", async () => {
  const username = document.getElementById("manualUser").value.trim();
  const password = document.getElementById("manualPassword").value;
  if (!username || !password) {
    alert("Enter both username and password.");
    return;
  }
  try {
    await login(username, password);
    route(currentPage);
  } catch (error) {
    alert(error.message);
  }
});

document.querySelectorAll(".nav-item").forEach((el) => {
  el.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
    el.classList.add("active");
    route(el.dataset.page);
  });
});

const floatingAskAi = document.getElementById("floatingAskAi");
function appendChatMessage(text, sender = "bot") {
  const msg = document.createElement("div");
  msg.className = `message ${sender}`;
  msg.textContent = text;
  $aiChatMessages.appendChild(msg);
  $aiChatMessages.scrollTop = $aiChatMessages.scrollHeight;
}

function toggleAiChat(forceOpen) {
  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : $aiChatPanel.classList.contains("hidden");
  $aiChatPanel.classList.toggle("hidden", !shouldOpen);
  if (shouldOpen) {
    renderQuickQuestions($aiChatOptions, $aiChatMessages);
  }
}

if (floatingAskAi) {
  floatingAskAi.addEventListener("click", () => {
    toggleAiChat();
  });
}

if ($closeAiChat) {
  $closeAiChat.addEventListener("click", () => toggleAiChat(false));
}

function renderQuickQuestions(optionsArea, answerArea) {
  optionsArea.innerHTML = QUICK_QUESTIONS.map((item, index) =>
     `<button class="question-option" type="button" data-question-index="${escapeHTML(index)}">${escapeHTML(item.label)}</button>`
  ).join("");
  optionsArea.querySelectorAll(".question-option").forEach((button) => {
    button.addEventListener("click", () => askQuestion(QUICK_QUESTIONS[button.dataset.questionIndex].question, answerArea, optionsArea));
  });
}

async function askQuestion(q, answerArea, optionsArea) {
  optionsArea.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  answerArea.innerHTML = `<div class="message bot">Resolving the authoritative source…</div>`;
  try {
    const r = await api("/api/ask", { method: "POST", body: JSON.stringify({ question: q }) });
      answerArea.innerHTML = r.access_denied
        ? `<div class="message bot">${escapeHTML(r.answer)}</div>`
      : renderAskResult(r);
  } catch (error) {
    answerArea.innerHTML = `<div class="message bot">I could not resolve that option right now.<br><br>Error: ${escapeHTML(error.message)}</div>`;
  } finally {
    optionsArea.querySelectorAll("button").forEach((button) => { button.disabled = false; });
  }
}

let currentPage = "dashboard";
function route(page) {
  currentPage = page;
  const renderers = {
    dashboard: renderDashboard, ask: renderAsk, documents: renderDocuments,
    resolver: renderResolver, approvals: renderApprovals, override: renderOverride,
    pending: renderPendingChanges, audit: renderAudit, eval: renderEval, settings: renderSettings,
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
function getRoleGuide(page) {
  const roleMap = ROLE_GUIDES[ROLE] || ROLE_GUIDES.VIEWER;
  return roleMap[page] || roleMap.dashboard;
}

async function renderDashboard() {
  const guide = getRoleGuide("dashboard");
  $main.innerHTML = `<h1>Dashboard</h1><div class="subtitle">Organization-wide authority &amp; audit posture</div><div id="kpis" class="grid"></div>
  <div class="panel">
    <h3>What this page is for</h3>
    <p class="subtitle" style="margin-top:-6px; margin-bottom:10px;">${escapeHTML(guide.summary)}</p>
    <ul>
        ${guide.points.map((point) => `<li>${escapeHTML(point)}</li>`).join("")}
    </ul>
    <div class="override-banner" style="margin-bottom:0;">CIA lens: ${escapeHTML(guide.cia)}</div>
  </div>
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
    ].map(([label, v]) => `<div class="card"><div class="kpi">${escapeHTML(v)}</div><div class="label">${escapeHTML(label)}</div></div>`).join("");
    document.getElementById("recentAudit").innerHTML = renderAuditTable(d.recent_audit_events);
  } catch (e) {
    document.getElementById("kpis").innerHTML = `<div class="card"><div class="label">No data yet — click "Regenerate Synthetic Dataset" below.</div></div>`;
  }
}

function renderAuditTable(events) {
  if (!events || !events.length) return "<p class='subtitle'>No events yet.</p>";
  return `<table><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Document</th><th>Reason</th></tr></thead><tbody>
    ${events.map(e => `<tr><td class="mono">${escapeHTML((e.timestamp||"").slice(0,19))}</td><td>${escapeHTML(e.user||"-")}</td><td>${escapeHTML(e.action)}</td><td class="mono">${escapeHTML(e.document_id||"-")}</td><td>${escapeHTML(e.reason||"-")}</td></tr>`).join("")}
  </tbody></table>`;
}

// --------------------------------------------------------------------- ASK
async function renderAsk() {
  $main.innerHTML = `<h1>Decision Lookup</h1><div class="subtitle">Choose an option to get an answer from the authority-resolved source document.</div>
  <div id="askOptions" class="question-options"></div><div id="answerArea"></div>`;
  renderQuickQuestions(document.getElementById("askOptions"), document.getElementById("answerArea"));
}

function renderAskResult(r) {
    if (!r.document_title) {
  return `<div class="message bot">${escapeHTML(r.answer || "No relevant authoritative document was found.")}</div>`;
    }
    let banner = "";
    if (r.conflict) banner += `<div class="conflict-banner">AUTHORITY CONFLICT — Conflicting approval records detected for this version. Manual review required.</div>`;
    if (r.is_override) banner += `<div class="override-banner">MANUAL OVERRIDE ACTIVE — ${escapeHTML(r.override_reason || "")}</div>`;
    const markup = `${banner}
      <div class="answer-block">
        <div class="answer-text">${escapeHTML(r.answer)}</div>
        <div class="source-grid">
          <div><span class="k">Authoritative Document:</span> ${escapeHTML(r.document_title)}</div>
          <div><span class="k">Version:</span> v${escapeHTML(r.version_number)}</div>
          <div><span class="k">Status:</span> ${statusBadge(escapeHTML(r.status))}</div>
          <div><span class="k">Grounded:</span> ${r.grounded ? "Yes" : "No — insufficient evidence"}</div>
          <div><span class="k">Citation:</span> <button class="citation-link" data-version="${escapeHTML(r.version_id)}" data-chunk="${escapeHTML(r.citation.chunk_id)}">Section ${escapeHTML(r.citation.section)}, Page ${escapeHTML(r.citation.page)}</button></div>
          <div><span class="k">Authority Score:</span> <span class="score-big">${escapeHTML(r.authority_score)}%</span></div>
        </div>
        <h3 style="margin-top:16px">Why This Source?</h3>
        ${Object.entries(r.breakdown || {}).map(([k, v]) => `<div class="breakdown-row"><span>${escapeHTML(k)}</span><span>${escapeHTML(v.points)} / ${escapeHTML(v.max)}</span></div>`).join("")}
        <p class="subtitle" style="margin-top:10px">${escapeHTML(r.relevance_note)}</p>
        <form id="feedbackForm" class="panel"><h3>Trust Feedback</h3>${[["answer_clear","Was the answer clear?"],["source_clear","Was the source clear?"],["citation_useful","Was the citation useful?"],["increased_trust","Did this increase trust?"],["would_use","Would you use this instead of manual checking?"]].map(([name,label]) => `<label>${escapeHTML(label)}<select name="${name}"><option value="1">1</option><option value="2">2</option><option value="3">3</option><option value="4">4</option><option value="5">5</option></select></label>`).join("")}<textarea name="comment" placeholder="Comment (optional)"></textarea><button type="submit">Submit feedback</button></form>
      </div>
      </div>`;
    const citationButton = document.querySelector(".citation-link");
    if (citationButton) citationButton.addEventListener("click", () => openCitation(citationButton.dataset.version, citationButton.dataset.chunk));
    const feedbackForm = document.getElementById("feedbackForm");
    feedbackForm.addEventListener("submit", async (event) => { event.preventDefault(); const values = Object.fromEntries(new FormData(feedbackForm)); ["answer_clear","source_clear","citation_useful","increased_trust","would_use"].forEach(key => values[key] = Number(values[key])); try { await api("/api/feedback", { method: "POST", body: JSON.stringify({ query: r.document_title, ...values }) }); toast("Feedback submitted."); feedbackForm.reset(); } catch (error) { toast(`Error: ${error.message}`); } });
    return markup;
}

async function openCitation(versionId, chunkId) {
  try {
    const chunk = await api(`/api/citations/${encodeURIComponent(versionId)}/${encodeURIComponent(chunkId)}`);
    const modal = document.createElement("div"); modal.className = "panel citation-modal";
    modal.innerHTML = `<h3>Source Chunk</h3><p>${escapeHTML(chunk.section)} — Page ${escapeHTML(chunk.page)}</p><pre>${escapeHTML(chunk.source_text)}</pre><button class="secondary">Close</button>`;
    modal.querySelector("button").addEventListener("click", () => modal.remove()); document.body.appendChild(modal);
  } catch (error) { toast(`Citation unavailable: ${error.message}`); }
}

async function sendFeedback(query, positive) {
  const rating = positive ? 5 : 1;
  await api("/api/feedback", {
    method: "POST",
    body: JSON.stringify({
      query, answer_clear: rating, source_clear: rating, citation_useful: rating,
      increased_trust: rating, would_use: rating,
    }),
  });
  toast("Thanks for the feedback!");
}

// --------------------------------------------------------------- DOCUMENTS
async function renderDocuments() {
  const guide = getRoleGuide("documents");
  $main.innerHTML = `<h1>Documents</h1><div class="subtitle">All architecture decision documents and their version counts.</div>
  <div class="panel">
    <h3>How this page helps your role</h3>
    <p class="subtitle" style="margin-top:-6px; margin-bottom:10px;">${escapeHTML(guide.summary)}</p>
    <ul>
      ${guide.points.map((point) => `<li>${escapeHTML(point)}</li>`).join("")}
    </ul>
    <div class="override-banner" style="margin-bottom:0;">CIA lens: ${escapeHTML(guide.cia)}</div>
  </div>
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
  document.getElementById("ownerSelect").innerHTML = owners.map(o => `<option value="${escapeHTML(o.id)}">${escapeHTML(o.name)} (${escapeHTML(o.authority_level)})</option>`).join("");
  const docs = await api("/api/documents");
  document.getElementById("docTable").innerHTML = `<table><thead><tr><th>Title</th><th>ID</th><th>Versions</th><th>Authoritative Version</th><th>Access</th></tr></thead><tbody>
    ${docs.map(d => `<tr data-doc-id="${escapeHTML(d.id)}" class="doc-row" style="cursor:pointer"><td>${escapeHTML(d.title)}</td><td class="mono">${escapeHTML(d.id)}</td><td>${escapeHTML(d.version_count)}</td><td class="mono">${escapeHTML(d.authoritative_version || "-")} ${d.is_override ? "override" : ""}</td><td>${d.accessible ? "allowed" : "denied"}</td></tr>`).join("")}
  </tbody></table>`;
  document.querySelectorAll(".doc-row").forEach(row => row.addEventListener("click", () => openDoc(row.dataset.docId)));

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
  sel.innerHTML = docs.map(d => `<option value="${escapeHTML(d.id)}">${escapeHTML(d.title)} (${escapeHTML(d.id)})</option>`).join("");
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
    if (!proposed.version) {
      const message = proposed.conflict
        ? "⚠ AUTHORITY CONFLICT — Automatic authority resolution is suspended. Review approvals before selecting a source."
        : "NO APPROVED VERSION — No version is eligible for automatic authority resolution.";
      area.innerHTML = `<div class="conflict-banner">${escapeHTML(message)} ${proposed.conflict ? `<button id="reviewConflict">Review</button><button id="resolveConflict">Resolve</button>` : ""}</div>
        <div class="panel"><h3>Baseline</h3><div class="row"><span>Newest version</span><span>v${escapeHTML(baseline.version.version_number)} (${escapeHTML(baseline.version.status)})</span></div></div>`;
      const review = document.getElementById("reviewConflict");
      if (review) review.addEventListener("click", () => route("approvals"));
      const resolve = document.getElementById("resolveConflict");
      if (resolve) resolve.addEventListener("click", () => route("approvals"));
      return;
    }
    area.innerHTML = `
      ${proposed.conflict ? `<div class="conflict-banner">⚠ AUTHORITY CONFLICT — Conflicting approval records detected. Manual review required.</div>` : ""}
      ${proposed.is_override ? `<div class="override-banner">MANUAL OVERRIDE ACTIVE — ${escapeHTML(proposed.override_reason)}</div>` : ""}
      ${proposed.conflict ? `<div class="panel"><button id="reviewConflict">Review</button><button id="overrideConflict">Override</button><button id="resolveConflict">Resolve</button></div>` : ""}
      <div class="metric-compare">
        <div class="col"><h4>BASELINE (newest wins)</h4>
          <div class="row"><span>Version</span><span>v${escapeHTML(baseline.version.version_number)}</span></div>
          <div class="row"><span>Status</span><span>${statusBadge(escapeHTML(baseline.version.status))}</span></div>
          <div class="row"><span>Modified</span><span class="mono">${escapeHTML(baseline.version.modified_date.slice(0,10))}</span></div>
        </div>
        <div class="col"><h4>PROPOSED (authority resolver)</h4>
          <div class="row"><span>Version</span><span>v${escapeHTML(proposed.version.version_number)}</span></div>
          <div class="row"><span>Status</span><span>${statusBadge(escapeHTML(proposed.version.status))}</span></div>
          <div class="row"><span>Authority Score</span><span class="score-big">${escapeHTML(proposed.score)}%</span></div>
        </div>
      </div>
      <div class="panel" style="margin-top:16px"><h3>Score Breakdown (Proposed)</h3>
        ${Object.entries(proposed.breakdown).map(([k,v]) => `<div class="breakdown-row"><span>${escapeHTML(k)} (weight ${escapeHTML((v.weight*100).toFixed(0))}%)</span><span>${escapeHTML(v.points)} / ${escapeHTML(v.max)}</span></div>`).join("")}
      </div>
      <div class="panel"><h3>All Versions</h3>
        <table><thead><tr><th>Version</th><th>Status</th><th>Owner</th><th>Modified</th><th>Approvals</th></tr></thead><tbody>
        ${detail.versions.map(v => `<tr><td>v${escapeHTML(v.version_number)}${v.id===proposed.version.id?' selected':''}</td><td>${statusBadge(escapeHTML(v.status))}</td><td>${escapeHTML(v.owner_id)}</td><td class="mono">${escapeHTML(v.modified_date.slice(0,10))}</td><td>${v.approvals.map(a=>`${escapeHTML(a.approver_name)}:${escapeHTML(a.decision)}`).join(", ")||"-"}</td></tr>`).join("")}
        </tbody></table>
      </div>`;
    const review = document.getElementById("reviewConflict");
    if (review) review.addEventListener("click", () => route("approvals"));
    const resolve = document.getElementById("resolveConflict");
    if (resolve) resolve.addEventListener("click", () => route("approvals"));
    const overrideButton = document.getElementById("overrideConflict");
    if (overrideButton) overrideButton.addEventListener("click", () => route("override"));
  } catch (e) { area.innerHTML = `<div class="conflict-banner">Error: ${escapeHTML(e.message)}</div>`; }
}

// ------------------------------------------------------------- APPROVALS
async function renderApprovals() {
  $main.innerHTML = `<h1>Approvals</h1><div class="subtitle">Add or revoke approval decisions with an auditable reason.</div>
  <label>Select Document</label><select id="apDocSelect"></select>
  <div id="apArea" style="margin-top:14px"></div>`;
  const docs = await api("/api/documents");
  document.getElementById("apDocSelect").innerHTML = docs.map(d => `<option value="${escapeHTML(d.id)}">${escapeHTML(d.title)}</option>`).join("");
  document.getElementById("apDocSelect").addEventListener("change", (e) => loadApprovals(e.target.value));
  if (docs.length) loadApprovals(docs[0].id);
}
async function loadApprovals(docId) {
  const detail = await api(`/api/documents/${docId}`);
  document.getElementById("apArea").innerHTML = detail.versions.map(v => `
    <div class="panel"><h3>v${escapeHTML(v.version_number)} — ${statusBadge(escapeHTML(v.status))}</h3>
    ${v.approvals.length ? `<table><thead><tr><th>Approver</th><th>Decision</th><th>Date</th><th>Reason</th></tr></thead><tbody>
      ${v.approvals.map(a=>`<tr><td>${escapeHTML(a.approver_name)}</td><td>${statusBadge(escapeHTML(a.decision))}</td><td class="mono">${escapeHTML((a.date||"").slice(0,10))}</td><td>${escapeHTML(a.reason||"-")} <button class="secondary revoke-approval" data-id="${escapeHTML(a.id)}">Revoke</button></td></tr>`).join("")}
    </tbody></table>` : "<p class='subtitle'>No approval records.</p>"}
    <form class="approval-form" data-version="${escapeHTML(v.id)}"><select name="decision"><option>APPROVED</option><option>REJECTED</option><option>PENDING_REVIEW</option></select><input name="reason" required minlength="5" placeholder="Reason"/><button type="submit">Add decision</button></form>
    </div>`).join("");
  document.querySelectorAll(".approval-form").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault(); const data = new FormData(form);
    try { await api("/api/approvals", { method: "POST", body: JSON.stringify({ version_id: form.dataset.version, decision: data.get("decision"), reason: data.get("reason") }) }); toast("Approval added."); loadApprovals(docId); }
    catch (error) { toast(`Error: ${error.message}`); }
  }));
  document.querySelectorAll(".revoke-approval").forEach((button) => button.addEventListener("click", async () => {
    const reason = prompt("Reason for revocation:"); if (!reason) return;
    try { await api(`/api/approvals/${button.dataset.id}/revoke`, { method: "POST", body: JSON.stringify({ reason }) }); toast("Approval revoked."); loadApprovals(docId); }
    catch (error) { toast(`Error: ${error.message}`); }
  }));
}

async function renderPendingChanges() {
  $main.innerHTML = `<h1>Pending Changes</h1><div class="subtitle">A different administrator must review each override or rollback request.</div><div id="pendingArea">Loading…</div>`;
  try {
    const changes = await api("/api/pending-changes");
    document.getElementById("pendingArea").innerHTML = changes.length ? `<table><thead><tr><th>Action</th><th>Document</th><th>Requested By</th><th>Reason</th><th>Review</th></tr></thead><tbody>${changes.map(change => `<tr><td>${escapeHTML(change.action)}</td><td>${escapeHTML(change.document_id)}</td><td>${escapeHTML(change.requested_by)}</td><td>${escapeHTML(change.reason)}</td><td><button class="approve-change" data-id="${escapeHTML(change.id)}" data-decision="APPROVE">Approve</button> <button class="secondary approve-change" data-id="${escapeHTML(change.id)}" data-decision="REJECT">Reject</button></td></tr>`).join("")}</tbody></table>` : "<p class='subtitle'>No pending changes.</p>";
    document.querySelectorAll(".approve-change").forEach(button => button.addEventListener("click", async () => {
      try { await api(`/api/pending-changes/${button.dataset.id}/review`, { method: "POST", body: JSON.stringify({ decision: button.dataset.decision }) }); toast("Change reviewed."); renderPendingChanges(); }
      catch (error) { toast(`Error: ${error.message}`); }
    }));
  } catch (error) { document.getElementById("pendingArea").textContent = error.message; }
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
  document.getElementById("ovDocSelect").innerHTML = docs.map(d => `<option value="${escapeHTML(d.id)}">${escapeHTML(d.title)}</option>`).join("");
  document.getElementById("ovDocSelect").addEventListener("change", (e) => loadOverride(e.target.value));
  if (docs.length) loadOverride(docs[0].id);
}
async function loadOverride(docId) {
  const [detail, current] = await Promise.all([api(`/api/documents/${docId}`), api(`/api/authority/${docId}`)]);
  const currentVersionId = current.version ? current.version.id : "";
  document.getElementById("ovArea").innerHTML = `
    ${current.is_override && current.version ? `<div class="override-banner">MANUAL OVERRIDE ACTIVE on v${escapeHTML(current.version.version_number)} — ${escapeHTML(current.override_reason)}</div><button id="rollbackBtn" class="secondary">Rollback to Previous Authority</button>` : ""}
    <div class="panel"><h3>Choose Version to Make Authoritative</h3>
      <select id="ovVersionSelect">${detail.versions.map(v => `<option value="${escapeHTML(v.id)}" ${v.id===currentVersionId?"selected":""}>v${escapeHTML(v.version_number)} — ${escapeHTML(v.status)}</option>`).join("")}</select>
      <label>Reason (required)</label><textarea id="ovReason" rows="3" placeholder="Explain why this version should be authoritative..."></textarea>
      <div style="margin-top:12px"><button id="ovSubmit">Apply Override</button></div>
    </div>`;
  document.getElementById("ovSubmit").addEventListener("click", async () => {
    try {
      const overrideResult = await api(`/api/authority/${docId}/override`, {
        method: "POST",
        body: JSON.stringify({ version_id: document.getElementById("ovVersionSelect").value, reason: document.getElementById("ovReason").value }),
      });
      toast(overrideResult.warning || "Override applied.");
      loadOverride(docId);
    } catch (e) { toast("Error: " + escapeHTML(e.message)); }
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
  $main.innerHTML = `<h1>Evaluation</h1><div class="subtitle">Live baseline versus weighted versus tiered authority results.</div>
  <div class="pill-row"><button id="runEvaluation">Run Evaluation</button><span id="evalStatus" class="subtitle"></span></div>
  <div id="evalResults" style="margin-top:16px"></div><div id="scenarioChart" class="panel"></div>
  <div id="errorAnalysis" class="panel"></div><div id="sensitivity" class="panel"></div>
  <div class="panel"><h3>Stakeholder Feedback Summary</h3><div id="fbSummary">Loading…</div></div>`;
  document.getElementById("runEvaluation").addEventListener("click", runEval);
  loadEvalHistory();
  const fb = await api("/api/feedback/summary");
  document.getElementById("fbSummary").innerHTML = fb.count ? `
    ${[["Responses", fb.count], ["Answer Clear", fb.answer_clear_average], ["Source Clear", fb.source_clear_average],
      ["Citation Useful", fb.citation_useful_average], ["Increased Trust", fb.increased_trust_average], ["Would Use", fb.would_use_average]]
      .map(([label, value]) => `<div class="row breakdown-row"><span>${escapeHTML(label)}</span><span>${escapeHTML(value)} / 5</span></div>`).join("")}
  ` : "<p class='subtitle'>No feedback submitted yet — use the Ask AI page.</p>";
}
async function runEval() {
  const area = document.getElementById("evalResults");
  const button = document.getElementById("runEvaluation");
  button.disabled = true;
  document.getElementById("evalStatus").textContent = "Running baseline, weighted, and tiered evaluations…";
  try {
    await api("/api/eval/run?mode=baseline", { method: "POST" });
    await api("/api/eval/run?mode=weighted", { method: "POST" });
    await api("/api/eval/run?mode=tiered", { method: "POST" });
    toast("Evaluation complete.");
    loadEvalHistory();
  } catch (e) { area.innerHTML = `<div class="conflict-banner">${escapeHTML(e.message)}</div>`; }
  finally { button.disabled = false; document.getElementById("evalStatus").textContent = ""; }
}
async function loadEvalHistory() {
  const results = await api("/api/eval/results");
  const area = document.getElementById("evalResults");
  if (!results.length) { area.innerHTML = "<p class='subtitle'>No evaluation runs yet.</p>"; return; }
  const latest = Object.fromEntries(results.map((result) => [result.mode, result]));
  const metrics = [["Authority Selection", "authority_selection_accuracy"], ["Answer", "answer_accuracy"], ["Citation", "citation_accuracy"],
    ["Access Control", "access_control_accuracy"], ["Conflict Detection", "conflict_detection_accuracy"], ["Manual Override", "manual_override_success"], ["Rollback", "rollback_success"]];
  area.innerHTML = `<table><thead><tr><th>Metric</th><th>Baseline</th><th>Weighted</th><th>Tiered</th></tr></thead><tbody>
    ${metrics.map(([label, key]) => `<tr><td>${escapeHTML(label)}</td><td>${escapeHTML(latest.baseline?.[key] ?? "n/a")}%</td><td>${escapeHTML(latest.weighted?.[key] ?? "n/a")}%</td><td>${escapeHTML(latest.tiered?.[key] ?? "n/a")}%</td></tr>`).join("")}
  </tbody></table>`;
  renderScenarioChart(latest.tiered?.scenario_metrics || {});
  const analysis = await api("/api/eval/error-analysis");
  document.getElementById("errorAnalysis").innerHTML = `<h3>Error Analysis</h3><table><thead><tr><th>Category</th><th>Count</th><th>Examples</th></tr></thead><tbody>
    ${Object.entries(analysis.counts || {}).map(([category, count]) => `<tr><td>${escapeHTML(category)}</td><td>${escapeHTML(count)}</td><td><details><summary>View</summary>${(analysis.examples[category] || []).map((example) => `<p><b>${escapeHTML(example.query)}</b><br>Expected: ${escapeHTML(JSON.stringify(example.expected))}<br>Got: ${escapeHTML(JSON.stringify(example.got))}<br>${escapeHTML(example.reason)}</p>`).join("")}</details></td></tr>`).join("")}
  </tbody></table>`;
  try {
    const sensitivity = await api("/api/eval/sensitivity");
    document.getElementById("sensitivity").innerHTML = `<h3>Weight Sensitivity</h3><table><thead><tr><th>Weights</th><th>Authority</th><th>Answer</th><th>Conflict</th></tr></thead><tbody>
      ${Object.entries(sensitivity).map(([name, value]) => `<tr><td>${escapeHTML(name)}</td><td>${escapeHTML(value.authority_selection_accuracy)}%</td><td>${escapeHTML(value.answer_accuracy)}%</td><td>${escapeHTML(value.conflict_detection_accuracy)}%</td></tr>`).join("")}
    </tbody></table>`;
  } catch (error) { document.getElementById("sensitivity").textContent = escapeHTML(error.message); }
}

function renderScenarioChart(scenarios) {
  const entries = Object.entries(scenarios);
  document.getElementById("scenarioChart").innerHTML = `<h3>Tiered Accuracy by Scenario</h3><svg viewBox="0 0 760 ${Math.max(160, entries.length * 32)}" role="img" aria-label="Scenario accuracy chart">
    ${entries.map(([name, value], index) => { const accuracy = Number(value.authority_selection_accuracy || 0); const y = index * 32 + 20; return `<text x="0" y="${y}" font-size="11">${escapeHTML(name)}</text><rect x="220" y="${y - 12}" width="${accuracy * 5}" height="18" fill="#2c7a7b"><title>${escapeHTML(accuracy)}%</title></rect><text x="${230 + accuracy * 5}" y="${y}" font-size="11">${escapeHTML(accuracy)}%</text>`; }).join("")}
  </svg>`;
}

// -------------------------------------------------------------- SETTINGS
async function renderSettings() {
  $main.innerHTML = `<h1>Settings</h1><div class="subtitle">Configurable scoring weights. Must sum to 1.0. ADMIN only.</div><div id="settingsArea">Loading…</div>`;
  const cfg = await api("/api/settings");
  const readonly = ROLE !== "ADMIN";
  document.getElementById("settingsArea").innerHTML = `
    <div class="panel"><h3>Resolver Policy</h3>
      <select id="resolverPolicy" ${readonly ? "disabled" : ""}>
        <option value="tiered" ${cfg.resolver_policy === 'tiered' ? 'selected' : ''}>Tiered (Eligibility -> Conflict -> Authority -> Recency)</option>
        <option value="weighted" ${cfg.resolver_policy === 'weighted' ? 'selected' : ''}>Weighted</option>
      </select>
    </div>
    <div class="panel"><h3>Authority Score Weights</h3>
      ${Object.entries(cfg.weights).map(([k, v]) => `
        <label>${escapeHTML(k)} (${escapeHTML((v*100).toFixed(0))}%)</label>
        <input type="number" step="0.01" min="0" max="1" id="w_${escapeHTML(k)}" value="${escapeHTML(v)}" ${readonly ? "disabled" : ""}/>
      `).join("")}
      <div style="margin-top:12px"><button id="saveWeights" ${readonly ? "disabled" : ""}>Save Settings</button></div>
    </div>
    <div class="panel"><h3>Status Scores</h3>
      ${Object.entries(cfg.status_scores).map(([k, v]) => `<div class="breakdown-row"><span>${escapeHTML(k)}</span><span>${escapeHTML(v)}</span></div>`).join("")}
    </div>
    <div class="panel"><h3>AI Provider</h3>
      <div class="breakdown-row"><span>Provider</span><span>${escapeHTML(cfg.ai_provider)}</span></div>
      <div class="breakdown-row"><span>Model</span><span>${escapeHTML(cfg.ai_model)}</span></div>
      <p class="subtitle">Set ADR_LLM_API_KEY env var to switch from the offline mock provider to a live LLM.</p>
    </div>`;
  if (!readonly) {
    document.getElementById("saveWeights").addEventListener("click", async () => {
      const weights = {};
      Object.keys(cfg.weights).forEach(k => weights[k] = parseFloat(document.getElementById(`w_${k}`).value));
      const resolver_policy = document.getElementById("resolverPolicy").value;
      try { await api("/api/settings", { method: "POST", body: JSON.stringify({ weights, resolver_policy }) }); toast("Settings saved."); }
      catch (e) { toast("Error: " + e.message); }
    });
  }
}

// ------------------------------------------------------------------ INIT
(async function init() {
  if (!TOKEN) {
    showLogin();
    return;
  }
  showApp();
  document.getElementById("roleSwitch").value = USERNAME;
  route("dashboard");
})();
