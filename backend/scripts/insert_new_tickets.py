"""One-shot script to insert TW-2011 through TW-2017 without touching existing data."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models.enums import TicketCategory, TicketPriority, TicketStatus, TicketType  # noqa: E402
from app.models.ticket import Ticket, TicketComment  # noqa: E402


def utc(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


NEW_TICKETS = [
    {
        "id": "TW-2011",
        "title": "API pods entering CrashLoopBackOff after node pool upgrade",
        "description": (
            "Following the node pool upgrade from 1.27 to 1.29 on the production cluster, "
            "three API service pods are stuck in CrashLoopBackOff. Logs show OOMKilled events "
            "-- the new node type has different memory allocation defaults. Other pods on the "
            "same deployment are running normally. The issue started immediately after the "
            "rolling upgrade completed."
        ),
        "status": TicketStatus.open,
        "priority": TicketPriority.critical,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.infrastructure,
        "assignee": "Youssef Hamdi",
        "reporter": "DevOps Team",
        "created_at": utc("2026-03-20T09:00:00Z"),
        "updated_at": utc("2026-03-20T10:30:00Z"),
        "due_at": utc("2026-03-20T17:00:00Z"),
        "resolution": None,
        "tags": ["kubernetes", "k8s", "oom", "node-pool", "crashloopbackoff"],
        "comments": [
            (
                "c20111",
                "Leila Ben Amor",
                "kubectl describe pod confirms OOMKilled on all three replicas -- memory request is 512Mi but new node type enforces a 256Mi limit by default.",
                "2026-03-20T09:45:00Z",
            ),
            (
                "c20112",
                "Youssef Hamdi",
                "Patching the deployment manifest to set explicit resource limits; rolling restart in progress on staging first.",
                "2026-03-20T10:25:00Z",
            ),
        ],
    },
    {
        "id": "TW-2012",
        "title": "New service deployment blocked by ImagePullBackOff on staging",
        "description": (
            "The staging deployment of the new notification microservice is failing with "
            "ImagePullBackOff on all 3 replicas. The container image was pushed to the private "
            "registry 2 hours ago. The registry credentials secret in the staging namespace "
            "appears to have expired -- it was last rotated 90 days ago and the token TTL is "
            "90 days. Other services using the same registry are unaffected because they use "
            "cached image layers."
        ),
        "status": TicketStatus.open,
        "priority": TicketPriority.high,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.infrastructure,
        "assignee": "Leila Ben Amor",
        "reporter": "Finance Team",
        "created_at": utc("2026-03-21T11:00:00Z"),
        "updated_at": utc("2026-03-21T12:15:00Z"),
        "due_at": utc("2026-03-22T11:00:00Z"),
        "resolution": None,
        "tags": ["kubernetes", "imagepullbackoff", "registry", "secret", "staging"],
        "comments": [
            (
                "c20121",
                "Mohamed Chaari",
                "Confirmed: the registry pull secret in the staging namespace expired today. The token was created 90 days ago with a 90-day TTL.",
                "2026-03-21T11:35:00Z",
            ),
            (
                "c20122",
                "Leila Ben Amor",
                "Rotating the registry service account token and patching the imagePullSecrets in the deployment manifest.",
                "2026-03-21T12:10:00Z",
            ),
        ],
    },
    {
        "id": "TW-2013",
        "title": "Ollama inference latency spiked from 800ms to 12s after model swap",
        "description": (
            "After switching from qwen3:4b to qwen3:7b on the recommendation service, LLM "
            "inference latency jumped from an average of 800ms to over 12 seconds per request. "
            "The host machine has 16GB RAM and no GPU -- the larger model is being loaded in "
            "CPU-only mode. The embedding pipeline is unaffected. Agents are experiencing "
            "timeouts on the chatbot. The 4b model was working correctly before the change."
        ),
        "status": TicketStatus.open,
        "priority": TicketPriority.high,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.application,
        "assignee": "Youssef Hamdi",
        "reporter": "AI Team",
        "created_at": utc("2026-03-22T08:00:00Z"),
        "updated_at": utc("2026-03-22T09:20:00Z"),
        "due_at": utc("2026-03-22T16:00:00Z"),
        "resolution": None,
        "tags": ["ollama", "llm", "inference", "latency", "model", "cpu"],
        "comments": [
            (
                "c20131",
                "Nadia Boucher",
                "Profiling confirms the 7b model exceeds available RAM and is swapping to disk -- effective throughput is 2 tokens/s versus 18 tokens/s on the 4b model.",
                "2026-03-22T08:50:00Z",
            ),
            (
                "c20132",
                "Youssef Hamdi",
                "Rolling back to qwen3:4b while we evaluate a GPU node or a quantized 7b variant that fits within the memory envelope.",
                "2026-03-22T09:15:00Z",
            ),
        ],
    },
    {
        "id": "TW-2014",
        "title": "KB semantic search returning unrelated tickets for VPN queries",
        "description": (
            "The RAG retrieval pipeline is returning mail/email chunks as the top results when "
            "agents query about VPN connectivity issues. The cosine similarity scores for these "
            "cross-domain matches are above 0.72 which is above the retrieval threshold. "
            "Investigation shows the embedding model is conflating 'certificate' signals between "
            "VPN TLS certificates and mail relay SSL certificates. The context gate should be "
            "blocking these but the topic family overlap is causing false positives."
        ),
        "status": TicketStatus.open,
        "priority": TicketPriority.medium,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.application,
        "assignee": "Youssef Hamdi",
        "reporter": "AI Team",
        "created_at": utc("2026-03-22T13:00:00Z"),
        "updated_at": utc("2026-03-22T14:10:00Z"),
        "due_at": utc("2026-03-25T13:00:00Z"),
        "resolution": None,
        "tags": ["rag", "retrieval", "embedding", "vector", "context-gate"],
        "comments": [
            (
                "c20141",
                "Mohamed Chaari",
                "The auth_path and network_access topic families both contain 'certificate' -- the context gate scores both topics equally and lets the mail chunk through.",
                "2026-03-22T13:40:00Z",
            ),
            (
                "c20142",
                "Youssef Hamdi",
                "Investigating whether adding stricter anti-overlap tokens to the topic families or lowering the cross-domain similarity ceiling resolves the bleed.",
                "2026-03-22T14:05:00Z",
            ),
        ],
    },
    {
        "id": "TW-2015",
        "title": "Notification service Kafka consumer lag exceeding 50k messages",
        "description": (
            "The notification distribution consumer group is falling behind -- current lag is "
            "52,847 messages and growing. The consumer was processing 3,000 messages/minute "
            "before a deployment last Tuesday. After the deployment, throughput dropped to "
            "400 messages/minute. The bottleneck appears to be in the database write path -- "
            "each notification triggers 3 synchronous DB writes without batching. The message "
            "broker is healthy and producer throughput is unchanged."
        ),
        "status": TicketStatus.open,
        "priority": TicketPriority.critical,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.application,
        "assignee": "Mohamed Chaari",
        "reporter": "Platform Team",
        "created_at": utc("2026-03-23T07:30:00Z"),
        "updated_at": utc("2026-03-23T09:00:00Z"),
        "due_at": utc("2026-03-23T14:00:00Z"),
        "resolution": None,
        "tags": ["kafka", "consumer-lag", "message-broker", "throughput", "notification"],
        "comments": [
            (
                "c20151",
                "Amina Rafi",
                "DB slow query log confirms each consumer handler is issuing 3 sequential INSERTs per message -- batching was accidentally removed in the Tuesday deploy.",
                "2026-03-23T08:10:00Z",
            ),
            (
                "c20152",
                "Mohamed Chaari",
                "Re-introducing batch writes (50 messages/flush) in a hotfix branch; estimating consumer will catch up within 2 hours once deployed.",
                "2026-03-23T08:55:00Z",
            ),
        ],
    },
    {
        "id": "TW-2016",
        "title": "Circuit breaker open on payment gateway integration -- all transactions failing",
        "description": (
            "The circuit breaker on the payment gateway API client has been in OPEN state for "
            "47 minutes. All payment transactions are failing fast without reaching the gateway. "
            "The circuit opened after the gateway returned 503 errors for 90 seconds during a "
            "maintenance window. The gateway is now healthy and returning 200s, but the circuit "
            "breaker has not reset because the half-open probe requests are timing out at the "
            "load balancer level -- the LB health check timeout (2s) is shorter than the "
            "circuit breaker probe timeout (5s)."
        ),
        "status": TicketStatus.open,
        "priority": TicketPriority.critical,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.application,
        "assignee": "Nadia Boucher",
        "reporter": "Finance Team",
        "created_at": utc("2026-03-24T10:00:00Z"),
        "updated_at": utc("2026-03-24T10:55:00Z"),
        "due_at": utc("2026-03-24T12:00:00Z"),
        "resolution": None,
        "tags": ["circuit-breaker", "payment", "api-gateway", "load-balancer", "timeout"],
        "comments": [
            (
                "c20161",
                "Leila Ben Amor",
                "LB access logs confirm the half-open probes are being dropped at the 2s LB timeout before the circuit breaker can record a success.",
                "2026-03-24T10:30:00Z",
            ),
            (
                "c20162",
                "Nadia Boucher",
                "Aligning LB health check timeout to 6s and manually forcing the circuit to HALF-OPEN to unblock transactions while the config change propagates.",
                "2026-03-24T10:50:00Z",
            ),
        ],
    },
    {
        "id": "TW-2017",
        "title": "Deadlock detected on tickets table during concurrent SLA updates",
        "description": (
            "The SLA monitor is producing deadlock errors when it attempts to update sla_status "
            "on multiple tickets simultaneously. The deadlock occurs because the SLA monitor "
            "acquires row locks in ticket_id ASC order while the Jira reconciliation process "
            "acquires them in updated_at DESC order. The two processes run concurrently every "
            "5 minutes and occasionally overlap. Approximately 3% of SLA updates are failing "
            "silently due to deadlock rollbacks."
        ),
        "status": TicketStatus.open,
        "priority": TicketPriority.high,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.infrastructure,
        "assignee": "Youssef Hamdi",
        "reporter": "Platform Team",
        "created_at": utc("2026-03-25T08:00:00Z"),
        "updated_at": utc("2026-03-25T09:30:00Z"),
        "due_at": utc("2026-03-26T08:00:00Z"),
        "resolution": None,
        "tags": ["deadlock", "postgresql", "sla-monitor", "transaction", "lock"],
        "comments": [
            (
                "c20171",
                "Amina Rafi",
                "pg_locks confirms the cross-lock pattern: SLA monitor holds row A waiting for row B while reconcile holds row B waiting for row A -- classic deadlock.",
                "2026-03-25T08:45:00Z",
            ),
            (
                "c20172",
                "Youssef Hamdi",
                "Standardising both processes to acquire ticket row locks in ticket_id ASC order; will redeploy SLA monitor and reconcile together to eliminate the ordering conflict.",
                "2026-03-25T09:25:00Z",
            ),
        ],
    },
]


def main() -> None:
    db = SessionLocal()
    inserted = 0
    try:
        for p in NEW_TICKETS:
            if db.get(Ticket, p["id"]):
                print(f"  {p['id']}: already exists, skipping")
                continue
            comments = p["comments"]
            comment_times = [utc(c[3]) for c in comments]
            ticket = Ticket(
                id=p["id"],
                title=p["title"],
                description=p["description"],
                status=p["status"],
                priority=p["priority"],
                ticket_type=p["ticket_type"],
                category=p["category"],
                assignee=p["assignee"],
                reporter=p["reporter"],
                problem_id=None,
                auto_assignment_applied=False,
                auto_priority_applied=False,
                assignment_model_version="seeded-manual",
                priority_model_version="seeded-manual",
                predicted_priority=p["priority"],
                predicted_ticket_type=p["ticket_type"],
                predicted_category=p["category"],
                assignment_change_count=0,
                first_action_at=min(comment_times) if comment_times else None,
                resolved_at=None,
                created_at=p["created_at"],
                updated_at=p["updated_at"],
                source="local",
                jira_key=None,
                jira_issue_id=None,
                jira_created_at=None,
                jira_updated_at=None,
                external_id=None,
                external_source=None,
                external_updated_at=None,
                last_synced_at=None,
                due_at=p["due_at"],
                raw_payload=None,
                jira_sla_payload=None,
                sla_status=None,
                sla_first_response_due_at=None,
                sla_resolution_due_at=None,
                sla_first_response_breached=False,
                sla_resolution_breached=False,
                sla_first_response_completed_at=None,
                sla_resolution_completed_at=None,
                sla_remaining_minutes=None,
                sla_elapsed_minutes=None,
                sla_last_synced_at=None,
                priority_auto_escalated=False,
                priority_escalation_reason=None,
                priority_escalated_at=None,
                resolution=p["resolution"],
                tags=list(p["tags"]),
            )
            db.add(ticket)
            for cid, author, content, ts in comments:
                db.add(
                    TicketComment(
                        id=cid,
                        ticket_id=p["id"],
                        author=author,
                        content=content,
                        created_at=utc(ts),
                        updated_at=None,
                        jira_comment_id=None,
                        jira_created_at=None,
                        jira_updated_at=None,
                        external_comment_id=None,
                        external_source=None,
                        external_updated_at=None,
                        raw_payload=None,
                    )
                )
            print(f"  {p['id']}: inserted")
            inserted += 1
        db.commit()
        print(f"\nDone -- {inserted} ticket(s) inserted.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
