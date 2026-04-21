"""Shared incident-family taxonomy and reusable AI vocabularies."""

from __future__ import annotations

from typing import Any

CATEGORY_HINTS: dict[str, frozenset[str]] = {
    "infrastructure": frozenset({"infrastructure", "server", "vm", "storage", "cloud", "kubernetes", "k8s", "cluster", "node", "container", "load balancer", "nginx", "autoscaling"}),
    "network": frozenset({"network", "vpn", "dns", "router", "switch", "wifi"}),
    "security": frozenset({"security", "auth", "token", "jwt", "access", "iam", "certificate", "sso", "active directory", "ldap", "kerberos", "group policy", "domain controller", "locked account"}),
    "application": frozenset(
        {
            "application",
            "app",
            "service",
            "api",
            "backend",
            "frontend",
            "dashboard",
            "widget",
            "widgets",
            "analytics",
            "reporting",
            "workspace",
            "review board",
            "export",
            "import",
            "csv",
            "report",
            "parser",
            "parsing",
            "format",
            "formatter",
            "serialization",
            "serialize",
            "schema",
            "date",
            "excel",
            "workbook",
            "payroll",
            "model",
            "inference",
            "llm",
            "embedding",
            "pipeline",
            "microservice",
            "api gateway",
            "circuit breaker",
            "message broker",
            "kafka",
            "rabbitmq",
        }
    ),
    "service_request": frozenset(
        {
            "service",
            "request",
            "onboarding",
            "permission",
            "service account",
            "grant access",
            "distribution rule",
            "forwarding rule",
            "webhook rotation",
            "secret rotation",
            "reminder task",
            "scheduled task",
            "recurring",
            "subscription renewal",
            "approved cadence",
            "approved window",
            "execution owner",
            "integrations team",
        }
    ),
    "hardware": frozenset(
        {
            "hardware",
            "laptop",
            "printer",
            "device",
            "ups",
            "battery",
            "keyboard",
            "dock",
            "monitor",
            "mouse",
            "usb",
            "hotspot",
            "mobile hotspot",
            "modem",
            "sim",
            "sim card",
            "roaming profile",
            "starter kit",
            "equipment",
        }
    ),
    "email": frozenset({"email", "mail", "smtp", "outlook", "mailbox", "relay", "connector", "queue"}),
    "problem": frozenset({"problem", "recurring", "pattern", "rca"}),
}

TOPIC_HINTS: dict[str, frozenset[str]] = {
    "crm_integration": frozenset(
        {
            "crm",
            "sync",
            "integration",
            "worker",
            "scheduler",
            "job",
            "token",
            "oauth",
            "credential",
            "secret",
            "requeue",
            "pipeline",
            "contact",
            "contacts",
        }
    ),
    "mail_transport": frozenset(
        {
            "mail",
            "email",
            "smtp",
            "relay",
            "transport",
            "delivery",
            "mailbox",
            "forwarding",
            "connector",
            "deferred",
            "queue",
            "outbound",
        }
    ),
    "payroll_export": frozenset(
        {
            "payroll",
            "export",
            "csv",
            "date",
            "formatter",
            "format",
            "parser",
            "parsing",
            "serializer",
            "serialization",
            "workbook",
            "import",
        }
    ),
    "network_access": frozenset(
        {
            "vpn",
            "dns",
            "route",
            "routing",
            "gateway",
            "firewall",
            "asa",
            "cisco",
            "session",
            "sessions",
            "timeout",
            "reauth",
            "reauthentication",
            "tunnel-group",
            "group-policy",
            "mfa",
            "wifi",
            "remote",
            "split",
            "tunnel",
            "subnet",
            "reconnect",
        }
    ),
    "database_data": frozenset(
        {
            "database",
            "postgres",
            "postgresql",
            "sql",
            "query",
            "table",
            "index",
            "migration",
            "schema",
            "oom",
            "oomkilled",
            "memory",
            "ram",
            "killer",
            "shared_buffers",
            "work_mem",
            "swap",
        }
    ),
    "notification_distribution": frozenset(
        {
            "notification",
            "distribution",
            "recipient",
            "recipients",
            "approval",
            "manager",
            "managers",
            "notice",
            "notices",
        }
    ),
    "auth_path": frozenset({"auth", "authentication", "token", "oauth", "certificate", "identity", "signin", "login", "sso", "policy"}),
    "webhook_rotation": frozenset(
        {
            "webhook",
            "webhook secret",
            "api key rotation",
            "credential rotation",
            "rotate secret",
            "rotate token",
            "webhook reminder",
            "rotation reminder",
            "approved cadence",
            "integrations team",
            "rotation schedule",
        }
    ),
    "scheduled_maintenance": frozenset(
        {
            "reminder task",
            "recurring task",
            "maintenance task",
            "cron job",
            "periodic task",
            "subscription renewal",
            "rotation schedule",
            "scheduled rotation",
            "scheduled maintenance",
        }
    ),
    "kubernetes_cluster": frozenset(
        {
            "kubernetes",
            "k8s",
            "pod",
            "crashloopbackoff",
            "node",
            "nodepool",
            "deployment",
            "helm",
            "namespace",
            "container",
            "image",
            "registry",
            "kubectl",
            "cluster",
            "ingress",
            "service mesh",
            "replicaset",
            "daemonset",
            "statefulset",
            "configmap",
            "secret",
            "liveness probe",
            "readiness probe",
            "oom",
            "evicted",
            "pending",
            "imagepullbackoff",
            "resource limit",
            "resource quota",
        }
    ),
    "ai_ml_pipeline": frozenset(
        {
            "model",
            "inference",
            "training",
            "llm",
            "embedding",
            "vector",
            "gpu",
            "cuda",
            "pytorch",
            "tensorflow",
            "huggingface",
            "ollama",
            "pipeline",
            "dataset",
            "fine-tune",
            "fine-tuning",
            "tokenizer",
            "prompt",
            "rag",
            "retrieval",
            "hallucination",
            "context window",
            "latency",
            "throughput",
            "batch",
            "quantization",
            "model drift",
            "accuracy",
            "prediction",
            "classifier",
        }
    ),
    "system_architecture": frozenset(
        {
            "microservice",
            "monolith",
            "api gateway",
            "load balancer",
            "reverse proxy",
            "nginx",
            "traefik",
            "service discovery",
            "circuit breaker",
            "rate limit",
            "timeout",
            "retry",
            "queue",
            "message broker",
            "kafka",
            "rabbitmq",
            "event bus",
            "pub sub",
            "cache",
            "redis",
            "cdn",
            "horizontal scaling",
            "vertical scaling",
            "autoscaling",
            "health check",
            "liveness",
            "readiness",
            "blue green",
            "canary",
            "rollout",
            "rollback",
        }
    ),
    "database_performance": frozenset(
        {
            "slow query",
            "query timeout",
            "deadlock",
            "lock wait",
            "index missing",
            "full table scan",
            "explain plan",
            "connection pool",
            "connection leak",
            "max connections",
            "replication lag",
            "replica",
            "primary",
            "failover",
            "backup",
            "restore",
            "vacuum",
            "bloat",
            "checkpoint",
            "wal",
            "write ahead log",
            "transaction",
            "rollback",
            "constraint violation",
            "foreign key",
            "cascade",
        }
    ),
    "active_directory": frozenset(
        {
            "active directory",
            "ad",
            "ldap",
            "group policy",
            "gpo",
            "domain controller",
            "dc",
            "trust",
            "kerberos",
            "ntlm",
            "upn",
            "sam",
            "ou",
            "organizational unit",
            "group",
            "user account",
            "disabled account",
            "locked account",
            "password expiry",
            "password policy",
            "forest",
            "domain",
            "site",
            "replication",
            "sysvol",
            "netlogon",
        }
    ),
    "erp_finance": frozenset(
        {
            "erp",
            "sap",
            "oracle",
            "dynamics",
            "netsuite",
            "purchase order",
            "invoice",
            "gl",
            "general ledger",
            "accounts payable",
            "accounts receivable",
            "journal",
            "fiscal year",
            "period close",
            "reconciliation",
            "cost center",
            "profit center",
            "workflow approval",
            "budget",
            "forecast",
            "financial reporting",
        }
    ),
}

TOPIC_TAXONOMY: dict[str, dict[str, Any]] = {
    topic: {
        "hints": hints,
        "label": topic.replace("_", " "),
    }
    for topic, hints in TOPIC_HINTS.items()
}

LOW_SIGNAL_TOKENS: frozenset[str] = frozenset(
    {
        "issue",
        "issues",
        "service",
        "services",
        "problem",
        "problems",
        "failed",
        "failure",
        "update",
        "updates",
        "updated",
        "system",
        "systems",
        "error",
        "errors",
        "stuck",
        "stalled",
        "queue",
    }
)

SHALLOW_MATCH_TOKENS: frozenset[str] = LOW_SIGNAL_TOKENS.union(
    {
        "rotation",
        "rotate",
        "rotated",
        "create",
        "creates",
        "created",
        "review",
        "reviews",
        "reviewed",
        "weekly",
        "dashboard",
        "task",
        "tasks",
    }
)

ACTION_HINTS: tuple[str, ...] = (
    "restart",
    "reboot",
    "reset",
    "clear",
    "flush",
    "recreate",
    "rebuild",
    "rotate",
    "patch",
    "update",
    "disable",
    "enable",
    "replace",
    "rollback",
    "renew",
    "reinstall",
    "restore",
    "unlock",
    "remove",
    "add",
    "assign",
    "sync",
    "reimport",
    "import",
    "apply",
    "switch",
    "move",
    "increase",
    "decrease",
    "whitelist",
    "allowlist",
    "reconfigure",
    "redeploy",
    "correct",
    "align",
    "realign",
    "drain",
    "validate",
)

OUTCOME_HINTS: tuple[str, ...] = ("resolved", "fixed", "worked", "restored", "mitigated", "verified", "closed")

TOPIC_VOCAB: frozenset[str] = frozenset(token for hints in TOPIC_HINTS.values() for token in hints)
HIGH_SIGNAL_VOCAB: frozenset[str] = TOPIC_VOCAB.union(
    token
    for hints in CATEGORY_HINTS.values()
    for token in hints
    if token not in LOW_SIGNAL_TOKENS
)

SERVICE_REQUEST_OPERATION_HINTS: dict[str, frozenset[str]] = {
    "create": frozenset(
        {
            "create",
            "build",
            "assemble",
            "prepare",
            "provision",
            "provisioning",
            "new",
            "onboard",
            "onboarding",
            "register",
            "setup",
            "set up",
        }
    ),
    "grant": frozenset(
        {
            "grant",
            "allow",
            "assign",
            "enable",
            "provide",
            "share",
            "membership",
        }
    ),
    "rotate": frozenset(
        {
            "rotate",
            "rotation",
            "renew",
            "renewal",
            "refresh",
            "replace",
        }
    ),
    "schedule": frozenset(
        {
            "schedule",
            "scheduled",
            "recurring",
            "periodic",
            "cadence",
            "reminder",
            "window",
        }
    ),
    "update": frozenset(
        {
            "update",
            "change",
            "modify",
            "configure",
            "reconfigure",
            "adjust",
        }
    ),
    "remove": frozenset(
        {
            "remove",
            "revoke",
            "delete",
            "disable",
            "decommission",
            "unsubscribe",
        }
    ),
}

SERVICE_REQUEST_RESOURCE_HINTS: dict[str, frozenset[str]] = {
    "account": frozenset(
        {
            "account",
            "service account",
            "technical user",
            "identity",
            "shared mailbox",
            "mailbox",
        }
    ),
    "access": frozenset(
        {
            "access",
            "permission",
            "permissions",
            "role",
            "roles",
            "group",
            "membership",
            "entitlement",
            "entitlements",
        }
    ),
    "credential": frozenset(
        {
            "credential",
            "credentials",
            "secret",
            "token",
            "api key",
            "certificate",
            "password",
            "connector identity",
        }
    ),
    "integration": frozenset(
        {
            "integration",
            "connector",
            "webhook",
            "callback",
            "subscription",
            "endpoint",
            "bridge",
        }
    ),
    "device": frozenset(
        {
            "device",
            "laptop",
            "dock",
            "hotspot",
            "mobile hotspot",
            "modem",
            "sim card",
            "roaming profile",
            "starter kit",
            "equipment",
        }
    ),
    "workspace": frozenset(
        {
            "dashboard",
            "widget",
            "widgets",
            "board",
            "review board",
            "workspace",
            "reporting workspace",
            "analytics workspace",
            "analytics view",
            "dashboard view",
        }
    ),
    "distribution_rule": frozenset(
        {
            "distribution rule",
            "distribution list",
            "recipient mapping",
            "recipient list",
            "forwarding rule",
            "mailbox forwarding",
            "notification recipients",
        }
    ),
    "task": frozenset(
        {
            "task",
            "reminder task",
            "recurring task",
            "maintenance task",
            "checklist",
            "runbook task",
        }
    ),
}

SERVICE_REQUEST_GOVERNANCE_HINTS: dict[str, frozenset[str]] = {
    "approval": frozenset({"approval", "approved", "approver", "authorize", "authorized"}),
    "owner": frozenset({"owner", "responsible", "assignee", "requester", "subscriber"}),
    "cadence": frozenset({"cadence", "schedule", "scheduled", "window", "recurring", "periodic"}),
    "policy": frozenset({"policy", "standard", "compliance", "lifecycle", "checklist", "prerequisite"}),
    "validation": frozenset({"verify", "validation", "confirm", "test", "document", "record"}),
}

SERVICE_REQUEST_FAMILY_HINTS: dict[str, frozenset[str]] = {
    "account_provisioning": frozenset(
        {
            "create account",
            "new account",
            "service account",
            "provision account",
            "account onboarding",
            "technical user",
            "shared mailbox",
        }
    ),
    "access_provisioning": frozenset(
        {
            "grant access",
            "access request",
            "permission request",
            "role assignment",
            "group membership",
            "shared drive access",
            "folder access",
            "entitlement",
        }
    ),
    "credential_rotation": frozenset(
        {
            "credential rotation",
            "secret rotation",
            "token rotation",
            "api key rotation",
            "rotate secret",
            "rotate token",
            "renew certificate",
            "connector identity",
            "rotation schedule",
        }
    ),
    "scheduled_maintenance": frozenset(
        {
            "reminder task",
            "recurring task",
            "maintenance task",
            "periodic task",
            "cron job",
            "scheduled maintenance",
            "approved cadence",
            "maintenance window",
        }
    ),
    "notification_distribution_change": frozenset(
        {
            "distribution rule",
            "distribution list",
            "recipient mapping",
            "recipient list",
            "forwarding rule",
            "mailbox forwarding",
            "notification routing",
        }
    ),
    "integration_configuration": frozenset(
        {
            "webhook",
            "integration setup",
            "configure integration",
            "connector",
            "callback endpoint",
            "endpoint configuration",
            "subscription",
        }
    ),
    "device_provisioning": frozenset(
        {
            "provision laptop",
            "new laptop",
            "laptop and dock",
            "starter kit",
            "prepare hotspot",
            "mobile hotspot",
            "roaming profile",
            "prepare device",
            "field engineer equipment",
        }
    ),
    "reporting_workspace_setup": frozenset(
        {
            "build dashboard",
            "create dashboard",
            "assemble dashboard",
            "share dashboard",
            "weekly review board",
            "sla dashboard",
            "reporting dashboard",
            "dashboard widgets",
            "analytics workspace",
        }
    ),
}

SERVICE_REQUEST_INCIDENT_CONFLICT_HINTS: frozenset[str] = frozenset(
    {
        "error",
        "failed",
        "failure",
        "broken",
        "cannot",
        "can't",
        "unable",
        "timeout",
        "timed out",
        "crash",
        "outage",
        "down",
        "degraded",
        "denied",
        "forbidden",
        "unauthorized",
        "not responding",
        "returns error",
        "returning error",
        "blocked",
        "stuck",
    }
)

SERVICE_REQUEST_HINT_VOCAB: frozenset[str] = frozenset(
    token
    for hint_map in (
        SERVICE_REQUEST_OPERATION_HINTS,
        SERVICE_REQUEST_RESOURCE_HINTS,
        SERVICE_REQUEST_GOVERNANCE_HINTS,
        SERVICE_REQUEST_FAMILY_HINTS,
    )
    for hints in hint_map.values()
    for token in hints
)
