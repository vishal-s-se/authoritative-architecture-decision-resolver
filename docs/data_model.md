# Data Model — Authoritative Architecture Decision Resolver

## Entities

| Entity | Purpose |
|---|---|
| Document | The logical decision (e.g. "Authentication Architecture") — has many versions |
| Version | One specific revision of a document — has content, status, owner |
| Owner | A team/role that can own or approve versions — has an authority level |
| Approval | A decision record (approved/rejected/pending) tied to one version + one owner |
| Access Rule | Which roles can see which documents |
| Authoritative | Tracks the currently selected version per document, plus override state |
| Audit Log | Append-only record of everything that happens |

## Fields

**Document**: `id, title, category, created_at`

**Version**: `id, document_id, version_number, content, created_date, modified_date, status (APPROVED/DRAFT/REJECTED/SUPERSEDED/ARCHIVED/PENDING_REVIEW), content_hash, owner_id, citations`

**Owner**: `id, name, authority_level (0.0–1.0)`

**Approval**: `id, version_id, approver_owner_id, decision, date, reason`

**Access Rule**: `id, document_id, role, allowed`

**Authoritative**: `document_id, version_id, score, breakdown, is_override, override_reason, override_by, previous_version_id, previous_score, updated_at`

**Audit Log**: `event_id, timestamp, user, action, document_id, version_id, previous_value, new_value, reason, metadata`

## Relationships

- Document 1 → many Version
- Version 1 → many Approval
- Owner 1 → many Approval, Owner 1 → many Version (as owner)
- Document 1 → many Access Rule
- Document 1 → 1 Authoritative (current pick)

## Scoring Formula

```
Score = 0.40 × Approval + 0.25 × Ownership + 0.20 × Recency + 0.10 × Version Validity + 0.05 × Evidence
```

**Why these weights:**
- **Approval (40%)** — the highest weight because approval status is the entire point of the system: an unapproved document should almost never outrank an approved one.
- **Ownership (25%)** — an approval/rejection from a higher-authority body (e.g. Architecture Board) should outweigh one from a single developer.
- **Recency (20%)** — still matters, but capped so it can never override approval status on its own.
- **Version Validity (10%)** and **Evidence/Citations (5%)** — tie-breakers, not primary decision factors.

All weights are configurable at runtime (not hardcoded), so the formula can be tuned without code changes. See `backend/app/config.py`.
