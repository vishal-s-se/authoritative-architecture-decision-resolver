# Authoritative Architecture Decision Resolver

## What this project is

A large engineering team writes architecture decision documents (e.g. "Authentication
Architecture"), but over time each one accumulates multiple versions — drafts,
revisions, approvals, rejections. Staff often can't tell which version is the
**current approved one**. A naive search just returns whatever was edited most
recently, which is often an unapproved draft.

This project builds an **Authoritative-Version Resolver**: a deterministic,
rule-based system that decides which version of a document is authoritative using
**approval status, owner authority, and recency** — not just "newest wins." Every
decision is explainable, reversible (manual override + rollback), and fully logged.

**Important design principle:** the AI/RAG layer never decides authority. It only
answers questions using whichever version the resolver has already selected. The
resolver's logic is deterministic and auditable, not a black box.

## What's in this repo

```
credentials_login.txt   All demo account usernames/passwords/roles
backend/          FastAPI app — the actual resolver logic lives here
  app/
    authority.py     Core scoring resolver + baseline "newest wins" resolver
    access.py         Role-based access control
    audit.py           Append-only audit logging
    ingestion.py         Document upload/parsing (PDF/DOCX/TXT)
    retrieval.py           Relevance search (finds candidate documents)
    ai.py                    Answers questions using only the resolved version
    evaluation.py              Baseline vs. proposed comparison harness
    seed.py                      Synthetic dataset generator
    database.py, config.py        Schema + configurable scoring weights
frontend/         Plain HTML/CSS/JS dashboard (no build step)
data/             Sample input documents + generated database (on first run)
tests/            Automated test suite covering key edge cases
scripts/          Sample document generator
docs/             Data model design notes
```

## What I'm going to do (project plan, brief)

1. **Data model & scoring formula** — define documents/versions/owners/approvals/
   access rules, and the weighted scoring formula that ranks versions.
2. **Core resolver + baseline** — build the deterministic authority resolver, and a
   naive "newest version wins" baseline to compare against.
3. **Access control, override, audit, rollback** — role-based access, admin override
   with required reason, immutable audit log, and rollback that restores prior state
   without deleting history.
4. **Ingestion & retrieval** — parse uploaded PDF/DOCX/TXT files, and use relevance
   search to find candidate documents (kept strictly separate from authority logic).
5. **AI answer layer** — grounded question-answering restricted to the resolver's
   chosen source, with citations, refusing to answer if the source lacks the info.
6. **Frontend dashboard** — Dashboard, Ask AI, Documents, Authority Resolver
   (baseline vs. proposed comparison), Approvals, Manual Override, Audit Trail,
   Evaluation, Settings.
7. **Testing & evaluation** — automated edge-case tests (conflicting approvals,
   unapproved newer drafts, unauthorized access, override/rollback), plus a
   measurable baseline-vs-proposed accuracy experiment with error analysis.
8. **Stakeholder validation & documentation** — short feedback survey, final README,
   and demo walkthrough.

## Scoring formula

```
Score = 0.40 × Approval + 0.25 × Ownership + 0.20 × Recency + 0.10 × Version Validity + 0.05 × Evidence
```

Approval is weighted highest because that's the entire point of the system — an
unapproved draft should almost never outrank an approved version, no matter how
recent it is. Full rationale in `docs/data_model.md`.

## Installation

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> Use Python 3.11 or 3.12. Very new Python versions (e.g. 3.14) may lack prebuilt
> wheels for some packages and require compiling from source.

## Running locally

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/login.html`. Credentials for all demo accounts are in
**`credentials_login.txt`** at the project root. Log in as `admin`, then click
**"Regenerate Synthetic Dataset"** on the Dashboard to populate the database, and
try the **Ask AI** page. Use the "Log Out" button in the sidebar to switch users.

12 sample documents (DOCX/PDF/TXT) are ready to upload in `data/samples/` — see
`data/samples/README.md` for details on what each one demonstrates.

## Running tests

```bash
cd backend
pip install pytest
pytest ../tests/test_authority.py -v
```

## Status

This is an active build. See `docs/data_model.md` for the schema and scoring
rationale, and `tests/test_authority.py` for the edge cases currently covered
(unapproved newer draft vs. approved older version, conflicting approvals,
unauthorized access, manual override, rollback).
