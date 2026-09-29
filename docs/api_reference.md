# API Reference

This table provides a reference for all endpoints exposed by the Authoritative Architecture Decision Resolver API.

| Method | Path | Required Role | Request Body Schema | Response Schema | Audit Event | Purpose |
|---|---|---|---|---|---|---|
| POST | `/api/auth/login` | None | `LoginRequest` | `{"token", "username", "role"}` | `LOGIN`, `LOGIN_FAILED` | Authenticate and get JWT token. |
| GET | `/api/dashboard` | None | None | Dashboard stats | None | Fetch overall system statistics. |
| GET | `/api/documents` | VIEWER | None | List of documents | None | List all architecture documents. |
| GET | `/api/documents/{document_id}` | VIEWER (if allowed) | None | Document and versions | `VIEW_DOCUMENT` (if denied) | Fetch document details and its versions. |
| POST | `/api/documents/upload` | ADMIN/ARCHITECT | Multipart Form | Upload Result | None | Upload a new document or version. |
| GET | `/api/owners` | None | None | List of owners | None | List all approval authorities. |
| GET | `/api/authority/{document_id}` | VIEWER (if allowed) | None | `{"version", "score", ...}` | `VIEW_AUTHORITY` (if denied) | Run full tiered authority resolution. |
| GET | `/api/authority/{document_id}/baseline` | VIEWER (if allowed) | None | `{"version", "score", ...}` | `VIEW_BASELINE` (if denied) | Run naive baseline resolution. |
| POST | `/api/approvals` | ADMIN/ARCHITECT | `ApprovalRequest` | `{"ok", "version_id", "decision"}` | `APPROVAL_ADDED`, `AUTHORITY_CHANGED` | Add a decision to a version. |
| POST | `/api/approvals/{id}/revoke` | ADMIN/ARCHITECT | `RevokeApprovalRequest` | `{"ok", "approval_id"}` | `APPROVAL_REVOKED`, `AUTHORITY_CHANGED` | Revoke a previous approval. |
| POST | `/api/authority/{id}/override` | ADMIN | `OverrideRequest` | `{"pending_change_id", "status"}` | `CHANGE_REQUESTED` | Request a manual authority override. |
| POST | `/api/authority/{id}/override/remove` | ADMIN | `RemoveOverrideRequest` | `{"ok", "authority"}` | `OVERRIDE_REMOVED` | Remove an active manual override. |
| POST | `/api/authority/{id}/rollback` | ADMIN | None | `{"pending_change_id", "status"}` | `CHANGE_REQUESTED` | Request to rollback to the previous authoritative version. |
| GET | `/api/pending-changes` | ADMIN | None | List of pending changes | None | View all pending manual changes. |
| POST | `/api/pending-changes/{id}/review` | ADMIN | `ChangeReviewRequest` | `{"status", "result"}` | `CHANGE_APPROVED`, `CHANGE_REJECTED` | Approve or reject a pending change. |
| POST | `/api/ask` | VIEWER | `AskRequest` | `{"answer", "grounded", ...}` | `QUERY_ANSWERED` | Ask a question against authoritative versions. |
| GET | `/api/audit` | ADMIN | None | List of audit events | None | Fetch the secure audit log. |
| GET | `/api/audit/verify` | ADMIN | None | `{"valid", "corrupted"}` | None | Verify the cryptographic integrity of the audit chain. |
| GET | `/api/citations/{version_id}/{chunk_id}` | VIEWER | None | `{"chunk_id", "source_text", ...}` | `VIEW_CITATION` (if denied) | Fetch the specific text chunk for a citation. |
| GET | `/api/settings` | None | None | Current config | None | Retrieve system configuration settings. |
| POST | `/api/settings` | ADMIN | `SettingsRequest` | Current config | `SETTINGS_UPDATED` | Update resolver weights and policies. |
| POST | `/api/admin/seed` | ADMIN | None | Seed stats | None | Reset and re-seed the test database. |
| POST | `/api/eval/run` | VIEWER | None | Eval metrics | `EVAL_RUN` | Run evaluation harness for a specific resolver mode. |
| GET | `/api/eval/results` | None | None | List of previous evals | None | List past evaluation results. |
| GET | `/api/eval/queries` | None | None | List of queries | None | View planted evaluation queries. |
| GET | `/api/eval/error-analysis` | ADMIN | None | Error counts/examples | None | View detailed error analysis for the proposed resolver. |
| GET | `/api/eval/sensitivity` | ADMIN | None | Sensitivity results | None | Compare resolver modes under varied weights. |
| POST | `/api/feedback` | None | `FeedbackRequest` | `{"ok": True}` | `FEEDBACK_SUBMITTED` | Submit feedback on Ask AI response. |
| GET | `/api/feedback/summary` | None | None | Feedback stats | None | Retrieve aggregated feedback metrics. |
