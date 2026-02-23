"""Convenience imports for Alembic metadata discovery."""

from app.models.user import User
from app.models.ticket import Ticket, TicketComment
from app.models.email_log import EmailLog
from app.models.verification_token import VerificationToken
from app.models.recommendation import Recommendation
from app.models.refresh_token import RefreshToken
from app.models.password_reset_token import PasswordResetToken
from app.models.jira_sync_state import JiraSyncState  # noqa: F401
from app.models.problem import Problem
from app.models.notification import Notification
from app.models.ai_sla_risk_evaluation import AiSlaRiskEvaluation
from app.models.automation_event import AutomationEvent

try:
    from app.models.kb_chunk import KBChunk  # noqa: F401
except ModuleNotFoundError:
    # Optional dependency for environments without pgvector.
    KBChunk = None
