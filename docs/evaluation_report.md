# Evaluation Report

This report is generated from the live SQLite evaluation tables. Run the
application, seed the deterministic planted scenarios, then execute:

```text
POST /api/eval/run?mode=baseline
POST /api/eval/run?mode=proposed
GET  /api/eval/error-analysis
GET  /api/eval/sensitivity
```

The harness evaluates retrieval, authority selection, grounded answers,
citations, access control, and conflict behavior. Results include per-scenario
metrics and are persisted in `eval_results` with the active scoring weights.

Ground truth is authored by planted scenarios, not derived from resolver
scores. Deterministic scoring is appropriate for authority because approval,
ownership, and conflict decisions are governance facts that must be explainable
and reproducible. An LLM may summarize selected content, but must never choose
which version is authoritative.

Limitations include TF-IDF retrieval, synthetic scenarios, and the offline mock
answer provider. Production validation should add representative, independently
reviewed stakeholder cases.