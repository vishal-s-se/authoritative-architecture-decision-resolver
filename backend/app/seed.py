"""
Synthetic evaluation dataset generator.

Produces (approximately, per project spec):
  50 architecture documents
  200 document versions
  100 approval records
  30 owners
  20 access rules
  100 test queries with ground truth

All content is deterministic (seeded) so evaluation is reproducible.
"""
import random
import hashlib
import json
from datetime import datetime, timedelta, timezone
from .database import get_conn, init_db
from .audit import log_event
from passlib.hash import bcrypt

random.seed(42)

OWNER_DEFS = [
    ("Architecture Board", 1.0),
    ("Security Architecture Team", 0.9),
    ("Platform Architecture Team", 0.85),
    ("Data Architecture Team", 0.85),
    ("Engineering Manager", 0.8),
    ("Principal Engineer", 0.75),
    ("Senior Engineer", 0.6),
    ("Developer", 0.5),
]
# pad up to 30 owners with variations
EXTRA_OWNER_PREFIXES = ["Cloud", "Network", "Mobile", "Frontend", "Backend", "DevOps", "SRE",
                         "API", "Identity", "Payments", "Search", "ML Platform", "Infra", "QA", "Compliance"]

TOPICS = [
    "Authentication Architecture", "Database Architecture", "Cloud Deployment Architecture",
    "API Gateway Architecture", "Messaging Architecture", "Caching Architecture",
    "Identity and Access Management Architecture", "Payment Processing Architecture",
    "Logging and Observability Architecture", "Service Mesh Architecture",
    "Data Warehouse Architecture", "Mobile Backend Architecture", "Search Architecture",
    "Notification Architecture", "Disaster Recovery Architecture", "CI/CD Pipeline Architecture",
    "Secrets Management Architecture", "Multi-Tenant Architecture", "Rate Limiting Architecture",
    "Event Sourcing Architecture", "GraphQL Gateway Architecture", "Encryption-at-Rest Architecture",
    "Zero Trust Network Architecture", "Feature Flag Architecture", "Batch Processing Architecture",
    "Streaming Analytics Architecture", "Container Orchestration Architecture", "Edge Computing Architecture",
    "Backup and Restore Architecture", "Single Sign-On Architecture", "Audit Logging Architecture",
    "Service Discovery Architecture", "Load Balancing Architecture", "Data Retention Architecture",
    "Session Management Architecture", "Tokenization Architecture", "Webhooks Architecture",
    "Multi-Region Failover Architecture", "GDPR Compliance Architecture", "Chatbot Platform Architecture",
    "Internal Developer Platform Architecture", "Feature Store Architecture", "Data Lake Architecture",
    "Content Delivery Architecture", "Password Policy Architecture", "API Versioning Architecture",
    "Microservices Communication Architecture", "Kubernetes Cluster Architecture", "Vendor Integration Architecture",
    "Monolith Decomposition Architecture", "Real-Time Bidding Architecture",
]

STATUSES_POOL = ["APPROVED", "DRAFT", "REJECTED", "SUPERSEDED", "ARCHIVED", "PENDING_REVIEW"]

CONTENT_TEMPLATES = {
    "Authentication Architecture": (
        "This document defines the approved authentication mechanism for the organization. "
        "Section 1: Overview. The system uses {mechanism} for user authentication. "
        "Section 2: Token Handling. Access tokens are short-lived and refresh tokens are rotated on use. "
        "Section 3: Multi-Factor Authentication. MFA is required for all administrative accounts. "
        "Section 4.2: Protocol Selection. The approved authentication architecture uses {mechanism} "
        "as the primary protocol for identity verification across internal and external services. "
        "Section 5: Session Expiry. Sessions expire after {expiry} minutes of inactivity."
    ),
    "Database Architecture": (
        "This document defines the approved database architecture. "
        "Section 1: Overview. The primary datastore is {mechanism}. "
        "Section 2: Replication. Data is replicated synchronously across {replicas} availability zones. "
        "Section 4.2: Engine Selection. The approved database architecture uses {mechanism} as the "
        "system of record for transactional workloads. "
        "Section 5: Backup Policy. Backups are taken every 6 hours and retained for 30 days."
    ),
    "default": (
        "This document defines the approved architecture for {topic}. "
        "Section 1: Overview. The organization has adopted {mechanism} as the primary approach. "
        "Section 2: Rationale. This approach was selected after evaluating alternatives for scalability "
        "and operational cost. "
        "Section 4.2: Decision. The approved architecture for {topic} uses {mechanism} going forward. "
        "Section 5: Rollout. Rollout is planned across all business units within two quarters."
    ),
}

MECHANISMS = ["OAuth 2.0 with OpenID Connect", "SAML 2.0 federation", "PostgreSQL with logical replication",
              "MySQL with Galera clustering", "Kubernetes with Istio service mesh", "AWS Lambda with API Gateway",
              "Kafka-based event streaming", "Redis Cluster", "gRPC with mutual TLS", "GraphQL federation",
              "JWT-based stateless sessions", "Vault-managed secrets", "multi-region active-active failover",
              "Envoy-based edge proxying", "Snowflake as the data warehouse engine"]


def _plant_eval_scenarios(conn, owner_ids):
    """Create labelled fixtures whose expected outcomes are authored up front."""
    board = owner_ids["Architecture Board"]
    developer = owner_ids["Developer"]
    security = owner_ids["Security Architecture Team"]
    scenarios = []

    def add_fixture(scenario_type, label, versions, expected_index, behavior="SELECT", restricted=False):
        doc_id = f"scenario-{len(scenarios) + 1:02d}"
        conn.execute(
            "INSERT OR REPLACE INTO documents (id, title, category, created_at) VALUES (?,?,?,?)",
            (doc_id, label, "Planted Evaluation Scenario", "2026-01-01T00:00:00+00:00"),
        )
        version_ids = []
        for number, status, owner_id, content, metadata in versions:
            version_id = f"{doc_id}-v{number}"
            version_ids.append(version_id)
            conn.execute(
                """INSERT OR REPLACE INTO versions
                   (id, document_id, version_number, content, created_date, modified_date,
                    status, content_hash, owner_id, citations_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (version_id, doc_id, number, content, "2026-01-01T00:00:00+00:00",
                 metadata, status, _hash(content), owner_id,
                 json.dumps([{"section": f"Section {number}", "page": number,
                              "chunk_id": f"{version_id}-c1"}])),
            )
        if restricted:
            conn.execute("INSERT INTO access_rules (document_id, role, allowed) VALUES (?,?,0)", (doc_id, "VIEWER"))
        else:
            conn.execute("INSERT INTO access_rules (document_id, role, allowed) VALUES (?,?,1)", (doc_id, "VIEWER"))
        for role in ("ENGINEER", "ARCHITECT"):
            conn.execute("INSERT INTO access_rules (document_id, role, allowed) VALUES (?,?,1)", (doc_id, role))
        expected_id = version_ids[expected_index] if expected_index is not None else None
        expected_version = versions[expected_index][0] if expected_index is not None else None
        if scenario_type == "manual_override_active" and expected_id:
            conn.execute(
                """INSERT OR REPLACE INTO authoritative
                   (document_id, version_id, score, breakdown_json, is_override,
                    override_reason, override_by, previous_version_id, previous_score, updated_at)
                   VALUES (?,?,0,'{}',1,?,?,NULL,NULL,?)""",
                (doc_id, expected_id, "planted manual override", "admin", "2026-01-01T00:00:00+00:00"),
            )
        scenarios.append({
            "label": label,
            "document_id": doc_id if behavior != "AMBIGUOUS" else None,
            "version_id": expected_id,
            "expected_answer": "Manual review required" if behavior == "FLAG_CONFLICT" else (
                "Access denied" if behavior == "DENY" else (
                    "Ambiguous result" if behavior == "AMBIGUOUS" else f"mechanism-{expected_version}")),
            "expected_citation": "MANUAL_REVIEW_REQUIRED" if behavior == "FLAG_CONFLICT" else (
                "ACCESS_DENIED" if behavior == "DENY" else (
                    "AMBIGUOUS" if behavior == "AMBIGUOUS" else f"{doc_id}-v{expected_version}-c1")),
            "scenario_type": scenario_type,
            "expected_behavior": behavior,
        })
        return doc_id, version_ids

    add_fixture("newer_draft_vs_older_approved", "Newer draft versus older approved", [
        (1, "APPROVED", board, "The approved mechanism is mechanism-1.", "2026-01-01T00:00:00+00:00"),
        (2, "DRAFT", developer, "The draft mechanism is mechanism-2.", "2026-02-01T00:00:00+00:00"),
    ], 0)
    add_fixture("newer_pending_review", "Newer pending review", [
        (1, "APPROVED", board, "The approved mechanism is mechanism-3.", "2026-01-01T00:00:00+00:00"),
        (2, "PENDING_REVIEW", developer, "The pending mechanism is mechanism-4.", "2026-02-01T00:00:00+00:00"),
    ], 0)
    add_fixture("newer_rejected", "Newer rejected version", [
        (1, "APPROVED", board, "The approved mechanism is mechanism-5.", "2026-01-01T00:00:00+00:00"),
        (2, "REJECTED", developer, "The rejected mechanism is mechanism-6.", "2026-02-01T00:00:00+00:00"),
    ], 0)
    add_fixture("two_approved_different_owner_authority", "Two approved owner authorities", [
        (1, "APPROVED", developer, "The lower authority mechanism is mechanism-7.", "2026-01-01T00:00:00+00:00"),
        (2, "APPROVED", security, "The higher authority mechanism is mechanism-8.", "2026-02-01T00:00:00+00:00"),
    ], 1)
    add_fixture("superseded_newest", "Superseded newest version", [
        (1, "APPROVED", board, "The approved mechanism is mechanism-9.", "2026-01-01T00:00:00+00:00"),
        (2, "SUPERSEDED", developer, "The superseded mechanism is mechanism-10.", "2026-02-01T00:00:00+00:00"),
    ], 0)
    conflict_doc, conflict_versions = add_fixture("approval_conflict", "Approval conflict", [
        (1, "APPROVED", board, "The conflicted mechanism is mechanism-11.", "2026-01-01T00:00:00+00:00"),
    ], None, "FLAG_CONFLICT")
    conn.execute("INSERT INTO approvals (version_id, approver_owner_id, decision, date, reason) VALUES (?,?,?,?,?)",
                 (conflict_versions[0], board, "APPROVED", "2026-01-01T00:00:00+00:00", "planted approval"))
    conn.execute("INSERT INTO approvals (version_id, approver_owner_id, decision, date, reason) VALUES (?,?,?,?,?)",
                 (conflict_versions[0], developer, "REJECTED", "2026-01-02T00:00:00+00:00", "planted conflict"))
    add_fixture("restricted_document_for_viewer", "Restricted document for viewer", [
        (1, "APPROVED", board, "The restricted mechanism is mechanism-12.", "2026-01-01T00:00:00+00:00"),
    ], 0, restricted=True)
    add_fixture("manual_override_active", "Manual override active", [
        (1, "APPROVED", board, "The automatic mechanism is mechanism-13.", "2026-01-01T00:00:00+00:00"),
        (2, "DRAFT", developer, "The override mechanism is mechanism-14.", "2026-02-01T00:00:00+00:00"),
    ], 1)
    ambiguous_a, _ = add_fixture("ambiguous_query", "Ambiguous architecture source A", [
        (1, "APPROVED", board, "The ambiguous mechanism is mechanism-15.", "2026-01-01T00:00:00+00:00"),
    ], 0)
    ambiguous_b, _ = add_fixture("ambiguous_query", "Ambiguous architecture source B", [
        (1, "APPROVED", board, "The ambiguous mechanism is mechanism-16.", "2026-01-01T00:00:00+00:00"),
    ], 0)
    scenarios[-2]["document_id"] = None
    scenarios[-2]["version_id"] = None
    scenarios[-2]["expected_answer"] = "Ambiguous result"
    scenarios[-2]["expected_citation"] = "AMBIGUOUS"
    scenarios[-1]["document_id"] = None
    scenarios[-1]["version_id"] = None
    scenarios[-1]["expected_answer"] = "Ambiguous result"
    scenarios[-1]["expected_citation"] = "AMBIGUOUS"
    add_fixture("missing_metadata", "Missing metadata", [
        (1, "APPROVED", None, "The metadata-free mechanism is mechanism-17.", "2026-01-01T00:00:00+00:00"),
    ], 0)
    add_fixture("clean_control", "Clean newest approved control", [
        (1, "APPROVED", board, "The older mechanism is mechanism-18.", "2026-01-01T00:00:00+00:00"),
        (2, "APPROVED", board, "The newest mechanism is mechanism-19.", "2026-02-01T00:00:00+00:00"),
    ], 1)
    return scenarios


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _rand_date(days_back_min, days_back_max):
    now = datetime.now(timezone.utc)
    d = now - timedelta(days=random.randint(days_back_min, days_back_max))
    return d.isoformat()


def generate(num_documents=50, target_versions=200, target_approvals=100, num_access_rules=20, num_queries=100):
    random.seed(42)
    conn = get_conn()
    init_db()

    # --- USERS ---
    demo_users = [
        ("admin", "admin123", "ADMIN"),
        ("admin2", "admin2-123", "ADMIN"),
        ("architect1", "architect123", "ARCHITECT"),
        ("engineer1", "engineer123", "ENGINEER"),
        ("viewer1", "viewer123", "VIEWER"),
    ]
    for uname, pwd, role in demo_users:
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?,?,?)",
            (uname, bcrypt.hash(pwd), role),
        )

    # --- OWNERS (>=30) ---
    owners = list(OWNER_DEFS)
    i = 0
    while len(owners) < 30:
        prefix = EXTRA_OWNER_PREFIXES[i % len(EXTRA_OWNER_PREFIXES)]
        owners.append((f"{prefix} Architecture Team", round(random.uniform(0.55, 0.88), 2)))
        i += 1
    owner_ids = {}
    for name, level in owners:
        cur = conn.execute("INSERT OR IGNORE INTO owners (name, authority_level) VALUES (?,?)", (name, level))
        row = conn.execute("SELECT id FROM owners WHERE name=?", (name,)).fetchone()
        owner_ids[name] = row["id"]

    # --- DOCUMENTS + VERSIONS ---
    doc_topics = (TOPICS * ((num_documents // len(TOPICS)) + 1))[:num_documents]
    versions_per_doc = max(2, target_versions // num_documents)

    all_version_rows = []
    doc_ids = []
    for idx, topic in enumerate(doc_topics):
        doc_id = f"doc-{idx+1:03d}"
        doc_ids.append(doc_id)
        conn.execute(
            "INSERT OR IGNORE INTO documents (id, title, category, created_at) VALUES (?,?,?,?)",
            (doc_id, topic, "Architecture Decision", _rand_date(400, 800)),
        )

        n_versions = versions_per_doc + (1 if idx < (target_versions - versions_per_doc * num_documents) else 0)
        n_versions = max(2, n_versions)
        mechanism = random.choice(MECHANISMS)
        template = CONTENT_TEMPLATES.get(topic, CONTENT_TEMPLATES["default"])

        # Build a realistic status trajectory: mostly draft->approved, with an
        # occasional later draft/rejected/superseded to create genuine trap cases.
        for v in range(1, n_versions + 1):
            version_id = f"{doc_id}-v{v}"
            owner_name = random.choice(list(owner_ids.keys()))
            content = template.format(
                mechanism=mechanism, expiry=random.choice([15, 30, 60]),
                replicas=random.choice([2, 3, 5]), topic=topic,
            )
            content += f" (Version {v} of {topic}.)"

            if v == 1:
                status = "APPROVED"
            elif v == n_versions and random.random() < 0.55:
                # Trap case: newest version is only a draft/pending, not yet authoritative
                status = random.choice(["DRAFT", "PENDING_REVIEW"])
            elif v == n_versions:
                status = "APPROVED"
            else:
                status = random.choice(["SUPERSEDED", "APPROVED", "REJECTED", "ARCHIVED"])
                if status == "APPROVED" and v != n_versions:
                    # an older approved version should usually become SUPERSEDED once a newer one is approved later
                    pass

            created = _rand_date(30 * (n_versions - v) + 10, 30 * (n_versions - v) + 40)
            modified = created
            citations = [{"section": "4.2", "page": 8, "chunk_id": f"{version_id}-c1"}]

            conn.execute(
                """INSERT OR IGNORE INTO versions
                   (id, document_id, version_number, content, created_date, modified_date, status,
                    content_hash, owner_id, citations_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (version_id, doc_id, v, content, created, modified, status,
                 _hash(content), owner_ids[owner_name], json.dumps(citations)),
            )
            all_version_rows.append((version_id, doc_id, v, status, owner_name))

    conn.commit()

    # --- ACCESS RULES ---
    roles = ["VIEWER", "ENGINEER", "ARCHITECT"]
    restricted_docs = random.sample(doc_ids, min(num_access_rules // 2, len(doc_ids)))
    count = 0
    for doc_id in restricted_docs:
        conn.execute(
            "INSERT INTO access_rules (document_id, role, allowed) VALUES (?,?,0)", (doc_id, "VIEWER")
        )
        count += 1
        if count >= num_access_rules:
            break
    restricted_set = set(restricted_docs)
    for doc_id in doc_ids:
        for role in ("ARCHITECT", "ENGINEER"):
            conn.execute(
                "INSERT INTO access_rules (document_id, role, allowed) VALUES (?,?,1)",
                (doc_id, role),
            )
        if doc_id not in restricted_set:
            conn.execute(
                "INSERT INTO access_rules (document_id, role, allowed) VALUES (?,?,1)",
                (doc_id, "VIEWER"),
            )
    conn.commit()

    # --- APPROVALS (>=100), including deliberate conflicts on a few versions ---
    approvable_versions = [r for r in all_version_rows if r[3] in ("APPROVED", "REJECTED", "PENDING_REVIEW")]
    random.shuffle(approvable_versions)
    approvals_created = 0
    conflict_versions = set()
    for version_id, doc_id, vnum, status, owner_name in approvable_versions:
        if approvals_created >= target_approvals:
            break
        approver = random.choice(list(owner_ids.keys()))
        decision = "APPROVED" if status == "APPROVED" else ("REJECTED" if status == "REJECTED" else "PENDING_REVIEW")
        conn.execute(
            "INSERT INTO approvals (version_id, approver_owner_id, decision, date, reason) VALUES (?,?,?,?,?)",
            (version_id, owner_ids[approver], decision, _rand_date(5, 300), f"{decision} by {approver}"),
        )
        approvals_created += 1

        # ~4% of approved versions get a deliberate conflicting REJECTED record from another owner
        if decision == "APPROVED" and random.random() < 0.04 and approvals_created < target_approvals:
            other_approver = random.choice([o for o in owner_ids if o != approver])
            conn.execute(
                "INSERT INTO approvals (version_id, approver_owner_id, decision, date, reason) VALUES (?,?,?,?,?)",
                (version_id, owner_ids[other_approver], "REJECTED", _rand_date(1, 4),
                 f"Conflicting rejection by {other_approver}"),
            )
            approvals_created += 1
            conflict_versions.add(version_id)
    conn.commit()

    # --- PLANTED EVAL QUERIES with independent ground truth ---
    conn.execute("DELETE FROM eval_queries")
    scenario_defs = _plant_eval_scenarios(conn, owner_ids)
    query_templates = [
        "What mechanism does the {label} decision use?",
        "Which source answers the {label} architecture question?",
        "What is the approved approach in the {label} record?",
    ]
    made = 0
    while made < num_queries:
        scenario = scenario_defs[made % len(scenario_defs)]
        query = query_templates[made % len(query_templates)].format(label=scenario["label"])
        conn.execute(
            """INSERT INTO eval_queries
               (query, expected_document_id, expected_version_id, expected_answer,
                expected_citation, category, scenario_type, expected_behavior)
               VALUES (?,?,?,?,?,?,?,?)""",
            (query, scenario["document_id"], scenario["version_id"],
             scenario["expected_answer"], scenario["expected_citation"],
             scenario["scenario_type"], scenario["scenario_type"], scenario["expected_behavior"]),
        )
        made += 1
    conn.commit()

    log_event("system", "SEED_DATASET_GENERATED", metadata={
        "documents": len(doc_ids), "versions": len(all_version_rows),
        "approvals": approvals_created, "owners": len(owners), "queries": made,
        "conflict_versions": len(conflict_versions),
    })

    return {
        "documents": len(doc_ids),
        "versions": len(all_version_rows),
        "approvals": approvals_created,
        "owners": len(owners),
        "access_rules": count,
        "queries": made,
        "conflict_versions": list(conflict_versions),
    }


if __name__ == "__main__":
    print(generate())
