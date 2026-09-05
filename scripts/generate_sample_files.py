"""
Generates a varied library of sample input files (DOCX, PDF, TXT) under
data/samples/ so reviewers have plenty of real material to test the
Document Upload / Ingestion flow with — different topics, different
statuses, different simulated authors/owners, and different file formats.

Usage: python scripts/generate_sample_files.py
"""
import os
import docx
import fitz  # PyMuPDF

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "samples")
os.makedirs(OUT_DIR, exist_ok=True)

# (filename, title, version_label, status, owner, mechanism, note)
SAMPLES = [
    ("Authentication_Architecture_v3_APPROVED", "Authentication Architecture", "3", "APPROVED",
     "Security Architecture Team", "OAuth 2.0 with OpenID Connect",
     "This decision was ratified by the Architecture Board on 2026-08-10.", "docx"),
    ("Authentication_Architecture_v4_DRAFT", "Authentication Architecture", "4", "DRAFT",
     "Developer", "OAuth 2.0 with OpenID Connect and passkey-based WebAuthn",
     "This revision is still under committee review and has not yet been approved.", "docx"),
    ("Database_Architecture_v2_APPROVED", "Database Architecture", "2", "APPROVED",
     "Data Architecture Team", "PostgreSQL with logical replication",
     "Approved by the Architecture Board following a 2-week evaluation period.", "docx"),
    ("Database_Architecture_v3_PENDING", "Database Architecture", "3", "PENDING_REVIEW",
     "Senior Engineer", "PostgreSQL with logical replication and read replicas",
     "Submitted for review; awaiting Architecture Board sign-off.", "pdf"),
    ("Cloud_Deployment_Architecture_v1_APPROVED", "Cloud Deployment Architecture", "1", "APPROVED",
     "Platform Architecture Team", "Kubernetes with Istio service mesh",
     "Initial approved deployment architecture for all production workloads.", "docx"),
    ("Cloud_Deployment_Architecture_v2_REJECTED", "Cloud Deployment Architecture", "2", "REJECTED",
     "Developer", "Serverless-only deployment via AWS Lambda",
     "Rejected by the Architecture Board due to cold-start latency concerns.", "pdf"),
    ("API_Gateway_Architecture_v1_APPROVED", "API Gateway Architecture", "1", "APPROVED",
     "Platform Architecture Team", "Envoy-based edge proxying",
     "Approved as the standard gateway layer for all external APIs.", "txt"),
    ("Secrets_Management_Architecture_v2_APPROVED", "Secrets Management Architecture", "2", "APPROVED",
     "Security Architecture Team", "Vault-managed secrets",
     "Approved following a security audit; supersedes the plaintext config approach.", "docx"),
    ("Messaging_Architecture_v1_DRAFT", "Messaging Architecture", "1", "DRAFT",
     "Principal Engineer", "Kafka-based event streaming",
     "Early draft circulated for informal feedback; not yet submitted for approval.", "txt"),
    ("Identity_Access_Management_v5_APPROVED", "Identity and Access Management Architecture", "5", "APPROVED",
     "Architecture Board", "SAML 2.0 federation with SSO",
     "Approved directly by the Architecture Board as the org-wide IAM standard.", "docx"),
    ("Observability_Architecture_v2_SUPERSEDED", "Logging and Observability Architecture", "2", "SUPERSEDED",
     "Engineering Manager", "Self-hosted ELK stack",
     "Superseded by v3's managed observability approach; retained for historical reference.", "pdf"),
    ("Zero_Trust_Network_Architecture_v1_APPROVED", "Zero Trust Network Architecture", "1", "APPROVED",
     "Architecture Board", "mutual TLS with identity-aware proxying",
     "Approved as the target-state network security model for all new services.", "docx"),
]


def build_docx(path, title, version_label, status, owner, mechanism, note):
    d = docx.Document()
    d.add_heading(title, level=0)
    d.add_paragraph(f"Version: {version_label}")
    d.add_paragraph(f"Status: {status}")
    d.add_paragraph(f"Owner: {owner}")
    d.add_heading("Section 1: Overview", level=1)
    d.add_paragraph(f"This document defines the architecture under consideration. "
                     f"The proposed approach uses {mechanism}.")
    d.add_heading("Section 2: Rationale", level=1)
    d.add_paragraph("This approach was evaluated against alternatives for scalability, "
                     "operational cost, and long-term maintainability.")
    d.add_heading("Section 4.2: Decision", level=1)
    d.add_paragraph(f"The architecture for {title} uses {mechanism} going forward. {note}")
    d.add_heading("Section 5: Rollout", level=1)
    d.add_paragraph("Rollout is planned across all affected business units within two quarters.")
    d.save(path)


def build_pdf(path, title, version_label, status, owner, mechanism, note):
    doc = fitz.open()
    page = doc.new_page()
    text = (
        f"{title}\n\n"
        f"Version: {version_label}\n"
        f"Status: {status}\n"
        f"Owner: {owner}\n\n"
        f"Section 1: Overview\n"
        f"This document defines the architecture under consideration. "
        f"The proposed approach uses {mechanism}.\n\n"
        f"Section 2: Rationale\n"
        f"This approach was evaluated against alternatives for scalability, "
        f"operational cost, and long-term maintainability.\n\n"
        f"Section 4.2: Decision\n"
        f"The architecture for {title} uses {mechanism} going forward. {note}\n\n"
        f"Section 5: Rollout\n"
        f"Rollout is planned across all affected business units within two quarters.\n"
    )
    page.insert_text((50, 72), text, fontsize=11)
    doc.save(path)
    doc.close()


def build_txt(path, title, version_label, status, owner, mechanism, note):
    content = (
        f"{title}\n"
        f"Version: {version_label}\n"
        f"Status: {status}\n"
        f"Owner: {owner}\n\n"
        f"Section 1: Overview\n"
        f"This document defines the architecture under consideration. "
        f"The proposed approach uses {mechanism}.\n\n"
        f"Section 2: Rationale\n"
        f"This approach was evaluated against alternatives for scalability, "
        f"operational cost, and long-term maintainability.\n\n"
        f"Section 4.2: Decision\n"
        f"The architecture for {title} uses {mechanism} going forward. {note}\n\n"
        f"Section 5: Rollout\n"
        f"Rollout is planned across all affected business units within two quarters.\n"
    )
    with open(path, "w") as f:
        f.write(content)


BUILDERS = {"docx": build_docx, "pdf": build_pdf, "txt": build_txt}

if __name__ == "__main__":
    for filename, title, version_label, status, owner, mechanism, note, ext in SAMPLES:
        path = os.path.join(OUT_DIR, f"{filename}.{ext}")
        BUILDERS[ext](path, title, version_label, status, owner, mechanism, note)
        print("wrote", path)
    print(f"\n{len(SAMPLES)} sample files written to {OUT_DIR}")
