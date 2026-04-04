"""
Seed script — inserts 7 similar VPN/network incident tickets then triggers
link_ticket_to_problem on each one.
PROBLEM_TRIGGER_MIN_COUNT = 5, so a problem should auto-create after the 5th.
Run from the backend/ directory:
    python seed_tickets.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import datetime as dt
from app.db.session import SessionLocal
from app.models.ticket import Ticket
from app.models.enums import TicketPriority, TicketStatus, TicketType, TicketCategory
from app.services.problems import link_ticket_to_problem

TICKETS = [
    {
        "id": "SEED-001",
        "title": "VPN connection dropping intermittently",
        "description": (
            "Users in the Paris office report that the VPN connection drops every few hours. "
            "The issue started after the firmware update on the Cisco ASA firewall. "
            "Affected users cannot access internal resources and must reconnect manually."
        ),
        "priority": TicketPriority.high,
        "category": TicketCategory.network,
        "ticket_type": TicketType.incident,
        "assignee": "network-team",
        "reporter": "alice.martin@teamwill.com",
        "status": TicketStatus.open,
        "tags": ["vpn", "network", "cisco", "firewall"],
    },
    {
        "id": "SEED-002",
        "title": "VPN keeps disconnecting for remote users",
        "description": (
            "Several remote employees report that the VPN disconnects every 2-3 hours. "
            "The problem started this week. IT has confirmed the Cisco ASA logs show "
            "session timeouts. Users in Lyon and Bordeaux are affected."
        ),
        "priority": TicketPriority.high,
        "category": TicketCategory.network,
        "ticket_type": TicketType.incident,
        "assignee": "network-team",
        "reporter": "bob.dupont@teamwill.com",
        "status": TicketStatus.open,
        "tags": ["vpn", "network", "disconnect", "remote"],
    },
    {
        "id": "SEED-003",
        "title": "VPN instability after firewall update",
        "description": (
            "Since the firewall firmware was updated on Monday, the VPN has been unstable. "
            "Connections drop after roughly 2 hours of use. Cisco ASA configuration may "
            "need to be reviewed. Affects all remote workers using the corporate VPN."
        ),
        "priority": TicketPriority.high,
        "category": TicketCategory.network,
        "ticket_type": TicketType.incident,
        "assignee": "network-team",
        "reporter": "claire.durand@teamwill.com",
        "status": TicketStatus.in_progress,
        "tags": ["vpn", "firewall", "cisco", "instability"],
    },
    {
        "id": "SEED-004",
        "title": "Cannot stay connected to VPN for more than 2 hours",
        "description": (
            "My VPN session disconnects after approximately 2 hours. I have to reconnect "
            "manually each time which is very disruptive. Other colleagues have the same "
            "issue since Monday. The network team should check the Cisco ASA timeout settings."
        ),
        "priority": TicketPriority.medium,
        "category": TicketCategory.network,
        "ticket_type": TicketType.incident,
        "assignee": "network-team",
        "reporter": "david.leclerc@teamwill.com",
        "status": TicketStatus.open,
        "tags": ["vpn", "network", "timeout"],
    },
    {
        "id": "SEED-005",
        "title": "VPN session timeout issue affecting all remote staff",
        "description": (
            "The corporate VPN disconnects all users after a fixed interval. "
            "This appears to be a configuration issue on the Cisco ASA firewall "
            "introduced during the recent firmware update. The network team is aware "
            "but has not resolved it yet. Productivity is significantly impacted."
        ),
        "priority": TicketPriority.critical,
        "category": TicketCategory.network,
        "ticket_type": TicketType.incident,
        "assignee": "network-team",
        "reporter": "emma.simon@teamwill.com",
        "status": TicketStatus.open,
        "tags": ["vpn", "cisco", "firewall", "critical", "network"],
    },
    {
        "id": "SEED-006",
        "title": "Repeated VPN drops — Cisco ASA firewall suspected",
        "description": (
            "For the fifth consecutive day, the VPN drops at irregular intervals. "
            "Multiple users across different offices are affected. The common factor is "
            "the Cisco ASA firewall firmware update from last week. Session logs show "
            "IKE phase-2 renegotiation failures as the root cause."
        ),
        "priority": TicketPriority.high,
        "category": TicketCategory.network,
        "ticket_type": TicketType.incident,
        "assignee": "network-team",
        "reporter": "francois.moreau@teamwill.com",
        "status": TicketStatus.open,
        "tags": ["vpn", "cisco", "ike", "network", "firewall"],
    },
    {
        "id": "SEED-007",
        "title": "Email server unreachable from outside network",
        "description": (
            "Users outside the office cannot connect to the email server. "
            "The SMTP port 587 appears to be blocked at the network perimeter. "
            "Internal users are unaffected. This may be related to a recent "
            "firewall rule change."
        ),
        "priority": TicketPriority.medium,
        "category": TicketCategory.network,
        "ticket_type": TicketType.incident,
        "assignee": "network-team",
        "reporter": "george.petit@teamwill.com",
        "status": TicketStatus.open,
        "tags": ["email", "smtp", "network", "firewall"],
    },
]

def main():
    with SessionLocal() as db:
        inserted = 0
        skipped = 0
        for t in TICKETS:
            existing = db.get(Ticket, t["id"])
            if existing:
                print(f"  SKIP {t['id']} — already exists")
                skipped += 1
                continue
            ticket = Ticket(
                id=t["id"],
                title=t["title"],
                description=t["description"],
                priority=t["priority"],
                category=t["category"],
                ticket_type=t["ticket_type"],
                assignee=t["assignee"],
                reporter=t["reporter"],
                status=t["status"],
                tags=t["tags"],
                source="seed",
                created_at=dt.datetime.now(dt.timezone.utc),
                updated_at=dt.datetime.now(dt.timezone.utc),
            )
            db.add(ticket)
            db.flush()
            problem = link_ticket_to_problem(db, ticket)
            if problem:
                print(f"  INSERT {t['id']} - linked to problem {problem.id} ({problem.title})")
            else:
                print(f"  INSERT {t['id']} - no problem yet (need {5 - inserted - 1} more similar tickets)")
            inserted += 1

        db.commit()
        print(f"\nDone — {inserted} inserted, {skipped} skipped.")
        print("Check /problems in the app to see if a problem was auto-created.")

if __name__ == "__main__":
    main()
