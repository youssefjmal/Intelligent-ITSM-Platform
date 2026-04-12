"""Enrich local/seed tickets: create KB chunks + run AI classification for tickets missing them.

This fixes seed tickets that were inserted without going through the Jira ingest pipeline
and therefore have no KB chunks (used for semantic retrieval) and no AI predictions.

Run from the backend directory:
    python scripts/enrich_local_tickets.py              # full enrichment (KB + classify)
    python scripts/enrich_local_tickets.py --skip-classify  # KB chunks only (no Ollama needed)
    python scripts/enrich_local_tickets.py --dry-run        # print plan without writing
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.ticket import Ticket  # noqa: E402
from app.services.embeddings import compute_embedding, upsert_kb_chunk  # noqa: E402


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ticket_issue_content(ticket: Ticket) -> str:
    parts = [ticket.title.strip()]
    if ticket.description and ticket.description.strip():
        parts.append(ticket.description.strip())
    if ticket.resolution and ticket.resolution.strip():
        parts.append(f"Resolution: {ticket.resolution.strip()}")
    return " ".join(parts)


def _derive_jira_key(ticket: Ticket) -> str:
    """Return a stable, unique jira_key for a local ticket.

    Uses the ticket's own ID uppercased so it's deterministic and readable
    (e.g. "seed-db-001" -> "SEED-DB-001", "TW-001" -> "TW-001").
    """
    return ticket.id.upper()


def enrich(*, skip_classify: bool = False, dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        # Tickets needing KB enrichment (no jira_key yet)
        kb_tickets: list[Ticket] = db.execute(
            select(Ticket).where(Ticket.jira_key.is_(None)).order_by(Ticket.created_at)
        ).scalars().all()

        # Tickets needing classification (no predicted_category, regardless of jira_key)
        classify_tickets: list[Ticket] = [] if skip_classify else db.execute(
            select(Ticket).where(Ticket.predicted_category.is_(None)).order_by(Ticket.created_at)
        ).scalars().all()

        tickets = list({t.id: t for t in [*kb_tickets, *classify_tickets]}.values())

        if not tickets:
            print("No local tickets without jira_key found -- nothing to do.")
            return

        print(f"Found {len(tickets)} tickets to enrich.")
        if dry_run:
            for t in tickets:
                print(f"  {t.id!r:30s}  title={t.title[:60]!r}")
            print("\n[dry-run] No changes written.")
            return

        enriched = 0
        kb_created = 0
        classified = 0
        errors = 0

        for ticket in tickets:
            needs_kb = ticket.jira_key is None
            jira_key = ticket.jira_key or _derive_jira_key(ticket)
            if needs_kb:
                ticket.jira_key = jira_key
            print(f"\n[{ticket.id}] jira_key={jira_key}  needs_kb={needs_kb}  needs_classify={ticket.predicted_category is None}")

            # ── Issue-level KB chunk (title + description + resolution) ──────
            issue_text = _ticket_issue_content(ticket)
            if needs_kb and issue_text:
                try:
                    embedding = compute_embedding(issue_text)
                    upsert_kb_chunk(
                        db,
                        source_type="jira_issue",
                        jira_issue_id=ticket.id,
                        jira_key=jira_key,
                        comment_id=None,
                        content=issue_text,
                        content_hash=_sha256(issue_text),
                        metadata={
                            "ticket_id": ticket.id,
                            "status": str(getattr(ticket.status, "value", ticket.status)),
                            "category": str(getattr(ticket.category, "value", ticket.category)),
                            "priority": str(getattr(ticket.priority, "value", ticket.priority)),
                        },
                        embedding=embedding,
                    )
                    print(f"  [KB issue]   chunk created ({len(issue_text)} chars)")
                    kb_created += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"  [KB issue]   FAILED: {exc}")
                    errors += 1

            # ── Comment-level KB chunks ────────────────────────────────────
            for comment in ticket.comments if needs_kb else []:
                content = (comment.content or "").strip()
                if not content:
                    continue
                comment_text = f"[{comment.author}]: {content}"
                try:
                    embedding = compute_embedding(comment_text)
                    upsert_kb_chunk(
                        db,
                        source_type="jira_comment",
                        jira_issue_id=ticket.id,
                        jira_key=jira_key,
                        comment_id=str(comment.id),
                        content=comment_text,
                        content_hash=_sha256(comment_text),
                        metadata={"ticket_id": ticket.id, "author": comment.author},
                        embedding=embedding,
                    )
                    print(f"  [KB comment] {comment.id} created")
                    kb_created += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"  [KB comment] {comment.id} FAILED: {exc}")
                    errors += 1

            # ── AI classification ─────────────────────────────────────────
            if not skip_classify and ticket.predicted_category is None:
                try:
                    from app.services.ai.classifier import classify_ticket  # noqa: PLC0415

                    priority, ticket_type, category, _ = classify_ticket(
                        ticket.title,
                        ticket.description or ticket.title,
                        db=db,
                        use_llm=True,
                        ticket_id=ticket.id,
                        trigger="enrich_seed",
                    )
                    ticket.predicted_priority = priority
                    ticket.predicted_ticket_type = ticket_type
                    ticket.predicted_category = category
                    print(
                        f"  [AI]         classified -> priority={getattr(priority, 'value', priority)}"
                        f" category={getattr(category, 'value', category)}"
                    )
                    classified += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"  [AI]         classification FAILED: {exc}")
                    errors += 1

            db.flush()
            enriched += 1

        db.commit()
        print(
            f"\nDone. Done. enriched={enriched}  kb_chunks_created={kb_created}"
            f"  classified={classified}  errors={errors}"
        )

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich local/seed tickets with KB chunks and AI classification.")
    parser.add_argument("--skip-classify", action="store_true", help="Skip AI classification (KB chunks only)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    args = parser.parse_args()
    enrich(skip_classify=args.skip_classify, dry_run=args.dry_run)
