# Authoritative Architecture Decision Resolver

A working prototype that answers one specific question reliably:
**"Which version of this architecture decision document is actually authoritative right now?"**

It is not a generic "chat with your PDFs" app. Retrieval finds *relevant* documents;
a separate, deterministic **Authority Resolver** decides which *version* of the
top candidate is *trustworthy*, using approval status, approver authority,
ownership, recency, version validity, and evidence — never the LLM's opinion.

---

## 1. Problem

Engineering orgs accumulate many versions of the same architecture document.
A naive "newest wins" search can surface an unapproved draft instead of the
ratified decision. Example:

```
Authentication Architecture v1 → Approved   (2026-08-10)
Authentication Architecture v2 → Draft      (2026-08-24)   <- newest, but not authoritative
```

## 2. Solution

1. **Retrieval** (TF-IDF over document titles + content) finds candidate documents by relevance.
2. **Authority Resolver** filters top-K candidates by access, applies a hard
  `APPROVED` eligibility gate, detects approval conflicts, then scores eligible
  versions with a deterministic, configurable formula.
3. **AI/RAG layer** answers the user's question using *only* that one selected version,
   with a citation, and refuses to answer if the source doesn't contain the information.
4. Every authority decision is written to an **immutable audit log**.
5. Administrators can **manually override** the automatic pick (with a required reason)
   and later **rollback** to the previous authoritative version — the override event is
   never deleted from the audit trail.

## 3. Architecture

```
frontend/  Static HTML/CSS/JS SOC-style dashboard (no build step, served by FastAPI)
backend/
  app/
    main.py        FastAPI routes / API surface
    database.py     SQLite schema + connection helper (ANSI SQL, Postgres-portable)
    config.py        Runtime-editable scoring weights (config.json)
    authority.py      *** Core authority resolver + baseline resolver ***
    access.py          Role-based access control
    retrieval.py         TF-IDF relevance search (candidate documents)
    ai.py                  Mock / real LLM answer generation + prompt-injection guard
    ingestion.py             PDF/DOCX/TXT ingestion, hashing, dedup
    audit.py                   Append-only audit log
    evaluation.py                Baseline vs proposed evaluation harness
    seed.py                        Synthetic dataset generator
data/            SQLite DB, config.json, sample .docx files (generated)
tests/           pytest suite covering the 6 required failure cases
scripts/         sample-data generation script
docs/            (this README covers the required documentation topics)
```

**Retrieval determines relevance. The resolver determines trust.** These are
intentionally separate modules with no shared logic, per the project's core requirement.

## 4. Documentation

- [API Reference](docs/api_reference.md)
- [Database Schema](docs/database_schema.md)

## 5. Technology Stack

- Backend: Python 3.11+, FastAPI, Uvicorn, SQLite (WAL-friendly, ANSI SQL only —
  swapping `database.py`'s connection layer for `psycopg2`/`asyncpg` is the only
  change needed to migrate to PostgreSQL)
- Retrieval: scikit-learn TF-IDF + cosine similarity (swap-in point for
  FAISS/Chroma + real embeddings — see `retrieval.py` docstring)
- Document parsing: PyMuPDF (PDF), python-docx (DOCX)
- AI: pluggable — defaults to a deterministic, grounded **mock provider** so the
  app runs fully offline; set `ADR_LLM_API_KEY` to call a real LLM instead
- Frontend: plain HTML/CSS/JS — zero build step, works instantly in VS Code

## 5. Database Schema

See `backend/app/database.py` for full DDL. Key tables:

| Table | Purpose |
|---|---|
| `documents` | One row per logical document (e.g. "Authentication Architecture") |
| `versions` | Every version of every document: status, content, hash, owner, dates |
| `owners` | Roles/teams with an `authority_level` (0–1), e.g. Architecture Board = 1.0 |
| `approvals` | One row per approval/rejection decision on a version (supports conflicts) |
| `access_rules` | Per-document, per-role allow/deny rules |
| `authoritative` | Current authoritative version per document + override/rollback state |
| `audit_log` | Append-only; no UPDATE/DELETE path exposed from the API |
| `eval_queries` / `eval_results` | Ground-truth queries and evaluation run history |
| `feedback` | Stakeholder validation survey responses |

## 6. Authority Scoring Algorithm

```
authority_score = 0.40 * approval_score
                 + 0.25 * ownership_score
                 + 0.20 * recency_score
                 + 0.10 * version_score
                 + 0.05 * evidence_score
```

- **approval_score**: applied after the hard `APPROVED` eligibility gate; other statuses
  remain visible in history but cannot win automatically.
- **ownership_score**: the highest `authority_level` among owners who *approved* this version (falls back to the version's own owner's level if unapproved).
- **recency_score**: exponential decay from `modified_date` with a configurable half-life (default 180 days) — recent but unapproved documents still don't win, because their weight is only 20%.
- **version_score**: rewards higher version numbers, but heavily penalizes `REJECTED`/`ARCHIVED` versions regardless of number.
- **evidence_score**: proportional to citation count (3+ citations = full score).

All weights are configurable in the **Settings** page (ADMIN only) and must sum to 1.0.
The resolver always returns a full breakdown (`points / max` per factor) for transparency.

Conflicting approvals on the same version produce `MANUAL_REVIEW_REQUIRED`; no source
is selected and the conflict is audited. An administrator may explicitly override this
state with a reason.

## 7. AI / RAG Flow

```
question → retrieval.search(top_k=5) → access filtering
         → authority.resolve_authority(document) → ONE approved version
         → ai.answer_question(question, that version's content only)
         → grounded answer + citation, or explicit "not enough information"
```

The AI never sees or chooses between multiple versions — it only ever receives the
single version the resolver already selected. Text extracted from uploaded documents
is scanned for instruction-injection patterns ("ignore previous instructions", etc.)
and neutralized before being used as context (see `ai.sanitize_document_text`).

## 8. Access Control

Roles: `ADMIN`, `ARCHITECT`, `ENGINEER`, `VIEWER`. `ADMIN` always passes. Otherwise,
`access_rules` are consulted per document/role; if the resolver's chosen authoritative
version belongs to a document the current user can't access, the API returns a
generic access-denied message — the document content is never included in that response.

## 9. Manual Override

`POST /api/authority/{document_id}/override` (ADMIN only) requires a `reason` of
at least 5 characters. It stores the previous authoritative version + score so a
rollback can restore it exactly. The UI shows a persistent **"MANUAL OVERRIDE ACTIVE"**
banner everywhere that document's authority is displayed.

## 10. Audit Trail

Every state-changing action (`DOCUMENT_UPLOADED`, `VERSION_CREATED`, `AUTHORITY_CALCULATED`,
`MANUAL_OVERRIDE`, `ROLLBACK`, `ACCESS_DENIED`, `QUERY_ANSWERED`, `SETTINGS_UPDATED`, …) is
appended to `audit_log` with a timestamp, user, before/after values, and free-text reason.
There is no API route to edit or delete audit rows.

## 11. Rollback

`POST /api/authority/{document_id}/rollback` (ADMIN only) restores `previous_version_id`/
`previous_score` captured at override time. The original `MANUAL_OVERRIDE` audit event is
never removed — `ROLLBACK` is recorded as a new, additional event.

## 12. Baseline

`GET /api/authority/{document_id}/baseline` implements the "newest version wins" naive
algorithm with **zero** approval/ownership logic, for direct side-by-side comparison
in the **Authority Resolver** page and the **Test/Evaluation** page.

## 13. Evaluation Methodology

`scripts` + `app/seed.py` generate a synthetic dataset (~50 documents, ~200 versions,
~100 approvals, 30 owners, access rules, and 100 ground-truth queries — exact counts
are logged to the audit trail on generation and shown after clicking "Regenerate
Synthetic Dataset" on the Dashboard).

`python scripts/run_evaluation.py` runs every planted query through retrieval,
access filtering, the resolver, and grounded answering. It uses a temporary
SQLite copy for mutation checks and generates [`docs/evaluation_report.md`](docs/evaluation_report.md)
from real results. The API equivalent is `POST /api/eval/run?mode=baseline|proposed`.

- Authority Selection Accuracy
- Citation Accuracy
- Access Control Accuracy
- Conflict Detection Accuracy
- Manual Override and Rollback Success
- Per-scenario accuracy, categorized error analysis, and weight sensitivity

Results are stored in `eval_results` and shown historically in the Test/Evaluation page,
so you can literally watch baseline underperform proposed on the same query set.

## 14. Test Cases

The suite has **39 passing tests** across authority resolution, planted scenarios,
FastAPI TestClient RBAC, access non-leakage, change review, audit tamper detection,
chunk citations, upload security, prompt injection, concurrency, duplicate uploads,
and rollback behavior. Run:

```bash
python -m pytest
```

`tests/test_authority.py` includes the core cases:

1. Newer draft vs. older approved → approved wins
2. Two approved versions, different owner authority → higher authority wins
3. Unauthorized user access → denied, no content leak
4. Manual override → becomes authoritative
5. Rollback → previous authority restored, audit event retained
6. Conflicting approval records → flagged, not silently resolved

## 15. Installation

### Prerequisites
- Python 3.11+ (3.12 tested)
- No Node.js / npm required — the frontend has no build step

### Steps (works well with VS Code + GitHub Copilot)

```bash
# 1. Clone/unzip the project, then from the project root:
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# 2. (optional) copy env template
cp ../.env.example ../.env
```

If you ask VS Code Copilot to "install the requirements for this project", point it
at `backend/requirements.txt` — that is the only dependency manifest that matters
(`package.json` at the root is a no-op placeholder since the frontend is plain JS).

## 16. Running Locally

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Set `ADR_JWT_SECRET` from `.env.example`, then open **http://localhost:8000** — FastAPI serves the frontend directly, no separate
dev server needed.

On first load, log in as `admin` (session selector in the sidebar, password
`admin123`) and click **"Regenerate Synthetic Dataset"** on the Dashboard to
populate the database.

## 17. Demo Instructions

1. **Dashboard** → Regenerate Synthetic Dataset.
2. **Ask AI** → "What authentication architecture is currently approved?" → see the
   grounded answer, authoritative source, score breakdown, and citation.
3. **Documents** → upload `data/samples/Authentication_Architecture_v4_DRAFT.docx`
   as document ID `doc-demo-auth` status `DRAFT`, then upload
   `Authentication_Architecture_v3_APPROVED.docx` as the same document ID, status `APPROVED`.
4. **Authority Resolver** → select `doc-demo-auth` → observe BASELINE picks the newer
   (v4) draft while PROPOSED correctly picks the approved v3, with full score breakdown.
5. **Manual Override** (switch role to `admin`) → force a different version authoritative,
   with a reason → see the banner appear everywhere → **Rollback**.
6. **Audit Trail** → see every event above recorded immutably.
7. **Test/Evaluation** → Run Baseline, Run Proposed → compare real, computed accuracy numbers.

## 18. Governance and Security

- Approval/rejection and revocation are role-checked, reason-required, and audited.
- Override and rollback requests require a different administrator to approve them.
- Expiring JWTs require `ADR_JWT_SECRET`; failed logins are rate-limited and audited.
- Uploads enforce size, extension, magic bytes, safe filenames, and duplicate hashes.
- Audit events form a SHA-256 chain verified by `GET /api/audit/verify`.
- Citations return only permission-checked persisted source chunks.

See [`docs/architecture.md`](docs/architecture.md) and [`docs/stakeholder_validation.md`](docs/stakeholder_validation.md).

## 19. Limitations

- TF-IDF retrieval is a practical local stand-in for real embeddings/vector search;
  swap in FAISS/Chroma + a hosted embedding model for production-grade semantic recall.
- The mock AI provider answers via grounded sentence-extraction, not a full LLM — set
  `ADR_LLM_API_KEY` to use a real model.
- Demo users and SQLite remain intended for local validation; production use should add
  durable session management, secret rotation, and PostgreSQL migrations.
- SQLite is fine for this prototype's scale; the schema uses only ANSI SQL so migrating
  to PostgreSQL is a connection-layer swap, not a schema rewrite.

## 20. Future Improvements

- Real vector search (FAISS/Chroma) with chunk-level citations instead of whole-version text.
- Multi-approver quorum rules (e.g. "requires 2 of 3 board members").
- Webhook/Slack notifications on authority changes or detected conflicts.
- Fine-grained field-level redaction for partially-restricted documents instead of all-or-nothing access.
- PostgreSQL + Alembic migrations for multi-user production deployment.

---

## API Quick Reference

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/login` | demo login |
| GET | `/api/dashboard` | KPIs |
| GET/POST | `/api/documents`, `/api/documents/upload` | list / ingest |
| GET | `/api/authority/{id}` , `/api/authority/{id}/baseline` | resolve authority |
| POST | `/api/authority/{id}/override`, `/api/authority/{id}/rollback` | admin actions |
| POST | `/api/authority/{id}/override/remove` | remove active override |
| POST | `/api/approvals`, `/api/approvals/{id}/revoke` | approval governance |
| GET/POST | `/api/pending-changes`, `/api/pending-changes/{id}/review` | second-admin review |
| POST | `/api/ask` | RAG question answering |
| GET | `/api/citations/{version_id}/{chunk_id}` | permission-checked source chunk |
| GET | `/api/audit` | audit trail |
| GET | `/api/audit/verify` | verify audit hash chain |
| GET/POST | `/api/settings` | scoring weights |
| POST | `/api/admin/seed` | regenerate synthetic dataset |
| POST | `/api/eval/run?mode=baseline\|proposed`, GET `/api/eval/results` | evaluation |
| GET | `/api/eval/error-analysis`, `/api/eval/sensitivity` | errors and sensitivity |
| POST | `/api/feedback`, GET `/api/feedback/summary` | stakeholder validation |

Demo accounts (seeded): `admin/admin123`, `admin2/admin2-123`, `architect1/architect123`,
`engineer1/engineer123`, `viewer1/viewer123`.
