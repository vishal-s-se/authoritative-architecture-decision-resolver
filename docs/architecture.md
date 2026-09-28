# Architecture

```mermaid
flowchart TD
    Q[Question] --> R[TF-IDF retrieval]
    R --> A[Access filter]
    A --> D[Deterministic authority resolver]
    D --> L[Grounded answer layer]
    L --> C[Citation and response]
    D --> AL[Hash-chained audit log]
    O[Override request] --> P[Pending change]
    RB[Rollback request] --> P
    P --> S[Second administrator review]
    S --> D
    S --> AL
```

Retrieval finds relevant documents; it does not select authority. The resolver
uses structured status, approval, ownership, recency, version, and evidence
facts. The answer layer receives only the selected version content.

Override and rollback requests are pending until a different administrator
approves them. Audit events include a SHA-256 chain link so tampering is
detectable through `GET /api/audit/verify`.