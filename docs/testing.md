# Testing and Error Boundaries

This document provides a comprehensive overview of the testing strategy, error handling, and resolution of edge cases found during evaluation phases for the Authoritative Architecture Decision Resolver.

## Running Tests

The test suite covers the entire application layer, including RBAC, authority scoring, retrieval integration, AI grounding constraints, and cryptographic audit logging.

To run the full suite:

```bash
python -m pytest
```

To run with verbose output and see exactly what is being executed:

```bash
python -m pytest -v
```

## Test Files and Coverage

The following test files make up the test suite (from `pytest --collect-only -q`):

- **`tests/test_api_security.py`**:
  - `test_rbac_denies_viewer_mutations`: Ensures read-only roles cannot upload or approve.
  - `test_rollback_without_history_is_clean_400`: Prevents rollback if no prior history exists.
  - `test_restricted_ask_and_citation_do_not_leak`: Verifies document contents and citations never leak if access is denied.
  - `test_two_admin_change_review_rejects_self_approval`: Asserts that an administrator cannot approve their own override/rollback request.
  - `test_audit_verify_endpoint_passes`: Verifies the audit chain logic works correctly.
  - `test_login_failures_are_rate_limited`: Confirms anti-brute-force rate limiting (429 status after 5 failed login attempts).
  - `test_duplicate_upload_is_rejected`: Asserts upload API returns a 400 when an identical file hash is detected.
  - `test_prompt_injection_is_neutralized`: Confirms that instructions hidden in documents (e.g. "ignore previous instructions") are neutralized before hitting the AI layer.
  - `test_feedback_submission_is_audited`: Ensures user feedback from Ask AI is persisted and logged.
  - `test_evaluation_run_is_audited`: Ensures that running the evaluation harness is logged.

- **`tests/test_audit_chain.py`**:
  - `test_audit_chain_verifies_and_reports_tampering`: Validates that modifying any value or deleting an event in SQLite breaks the hash chain and is caught by the verifier.
  - `test_legacy_hash_columns_are_added_safely`: Validates schema migrations work correctly.

- **`tests/test_authority.py`**:
  - Contains the core logic required by the project specifications:
    - `test_case_1_older_approved_beats_newer_draft`: Governance outranks recency.
    - `test_case_2_owner_authority_breaks_ties`: Senior roles (e.g. Security) outrank junior roles.
    - `test_case_3_unauthorized_access_denied`: Document-level RBAC integration.
    - `test_case_4_manual_override`: Admins can force an authoritative version.
    - `test_case_5_rollback_restores_and_keeps_audit`: Reverting an override is fully tracked.
    - `test_case_6_conflicting_approvals_flagged`: Detection of dual `APPROVED` / `REJECTED` states.
    - `test_case_7_conflict_suspends_automatic_resolution`: The resolver refuses to silently guess when a conflict is active.
    - `test_case_8_missing_access_rule_denies_non_admin`: Implicit deny by default.
    - `test_case_9_document_instructions_are_neutralized`: Guardrail integration test.
    - `test_concurrent_overrides_leave_one_consistent_authoritative_row`: Database consistency under concurrent mutations.

- **`tests/test_frontend_escape.py`**:
  - `test_frontend_escape_regression_script`: Prevents XSS/HTML injection from malicious document titles.

- **`tests/test_ingestion_chunks.py`**:
  - `test_split_sections_has_real_metadata`: Document chunking extracts headers correctly.
  - `test_ingestion_persists_chunks_and_citations`: Database schema correctly stores chunks and maps them to version IDs.

- **`tests/test_seed_scenarios.py`**:
  - Evaluates the offline harness and confirms dataset sizes (`test_seed_meets_dataset_size_contract`).
  - Ensures every single planted scenario variant successfully resolves to its expected independent ground truth (e.g., `newer_draft_vs_older_approved`, `approval_conflict`, `ambiguous_query`).
  - `test_ai_answer_grounded_citation`: Evaluates the strict AI grounding rules.

- **`tests/test_tiered.py`**:
  - Validates edge case handling of the `tiered` resolver policy (which prioritizes strict ownership > recency > version).
  
- **`tests/test_upload_security.py`**:
  - `test_filename_is_sanitized`: Directory traversal prevention.
  - `test_magic_bytes_are_checked`: MIME validation.
  - `test_text_upload_is_accepted`: Base upload flow.

## Review 2 Case Studies: Bugs and Fixes

### 1. TF-IDF Token Collision on Variant Scenarios
**Root Cause:** Evaluation scenarios used numbers (e.g., "variant 19", "mechanism-18") to distinguish similar test files. The default Scikit-Learn TF-IDF vectorizer configuration strips numbers and very short character sequences during tokenization. As a result, 5 distinct documents appeared perfectly identical to the retrieval engine, causing retrieval collision (incorrect documents were returned for specific queries).

**Fix:** The dataset generator (`seed.py`) was updated to use distinct alphabetical keywords (e.g., `alpha`, `beta`, `gamma`) instead of numbers for variant identifiers. This ensures each document has unique semantic tokens that TF-IDF preserves.

### 2. AI Grounding Contradiction
**Root Cause:** In the mock AI layer (`ai.py`), when a document chunk did not contain enough information to answer a user's question, the mock LLM correctly generated a refusal string (e.g., "does not contain enough information"). However, the system still returned the top matching chunk's citation alongside the refusal, creating a UX contradiction (a citation pointing to a source that allegedly lacks the answer).

**Fix:** Logic was added to `ai.py` to enforce that if the system cannot find a confident answer (grounded = False), the `citation` field must be forced to `None` and the answer defaults to an explicit refusal. Additionally, stop-word removal was added to the mock matcher to ensure it didn't falsely reject valid grounding due to common words, allowing valid answers to successfully attach their citations.

## Error Boundaries

The API enforces strict error boundaries for governance, security, and edge-case behaviors. The table below documents the exact response and audit behavior for each scenario.

| Scenario | HTTP Status / Response Body | Audit Event Logged? |
|---|---|---|
| **Invalid Login** | `401 Unauthorized`: "invalid credentials" | `LOGIN_FAILED` |
| **Brute-Force Login (≥5 attempts in 60s)** | `429 Too Many Requests`: "too many login attempts" | None |
| **Expired or Missing JWT** | Token decoder treats user as unauthenticated (`anonymous` / `VIEWER` role). Subsequent protected routes return `403`. | None |
| **Unauthorized Role** | `403 Forbidden`: "administrator role required" or "architect or administrator role required" | None (caught at middleware level) |
| **Restricted Document Access** | `403 Forbidden`: "access denied" (API) or `{"access_denied": True}` with refusal message (Ask AI). | `ACCESS_DENIED` |
| **Malformed Upload** (e.g., restricted MIME type) | `400 Bad Request`: "unsupported file format" | None |
| **Duplicate Content Hash** (Uploading identical file) | `400 Bad Request`: "duplicate content detected — identical to version X" | None |
| **Oversized File Upload** | `400 Bad Request`: "file exceeds 10MB limit" | None |
| **Resolver Conflict** (Simultaneous Approved & Rejected statuses) | `200 OK` (Ask AI): `{"conflict": True, "status": "MANUAL_REVIEW_REQUIRED"}` with refusal message. | `AUTHORITY_CONFLICT` |
| **Self-Approval on Change Review** | `400 Bad Request`: "a requester cannot approve their own change" | None |
| **Audit Chain Tampering** | `200 OK` (Verify endpoint): `{"valid": False, "first_broken_event": <event_id>}` | None |
