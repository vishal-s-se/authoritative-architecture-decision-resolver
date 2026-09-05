# Sample Input Files

12 ready-to-upload sample files across DOCX, PDF, and TXT — covering different
topics, statuses, and simulated owners — for testing the Document Upload /
Ingestion flow (Documents page in the app).

| File | Format | Status | Owner |
|---|---|---|---|
| Authentication_Architecture_v3_APPROVED | docx | APPROVED | Security Architecture Team |
| Authentication_Architecture_v4_DRAFT | docx | DRAFT | Developer |
| Database_Architecture_v2_APPROVED | docx | APPROVED | Data Architecture Team |
| Database_Architecture_v3_PENDING | pdf | PENDING_REVIEW | Senior Engineer |
| Cloud_Deployment_Architecture_v1_APPROVED | docx | APPROVED | Platform Architecture Team |
| Cloud_Deployment_Architecture_v2_REJECTED | pdf | REJECTED | Developer |
| API_Gateway_Architecture_v1_APPROVED | txt | APPROVED | Platform Architecture Team |
| Secrets_Management_Architecture_v2_APPROVED | docx | APPROVED | Security Architecture Team |
| Messaging_Architecture_v1_DRAFT | txt | DRAFT | Principal Engineer |
| Identity_Access_Management_v5_APPROVED | docx | APPROVED | Architecture Board |
| Observability_Architecture_v2_SUPERSEDED | pdf | SUPERSEDED | Engineering Manager |
| Zero_Trust_Network_Architecture_v1_APPROVED | docx | APPROVED | Architecture Board |

To upload one: go to **Documents** in the app, pick a file, give it a Document ID
(new or existing), choose the Owner and Status shown above, and submit.

Try uploading `Authentication_Architecture_v4_DRAFT.docx` as document ID
`doc-demo-auth` first, then `Authentication_Architecture_v3_APPROVED.docx` as the
same document ID — then check the Authority Resolver page to see the baseline
(newest-wins) pick the wrong one while the proposed resolver correctly picks the
approved version.

Regenerate or extend this set with `python scripts/generate_sample_files.py`.
