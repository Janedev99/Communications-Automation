"""
ORM models package.

Import all models here so Alembic's autogenerate can discover them when it
imports this package.
"""
from app.models.user import User, UserRole  # noqa: F401
from app.models.email import (  # noqa: F401
    EmailThread,
    EmailMessage,
    EmailStatus,
    EmailCategory,
    MessageDirection,
    DraftResponse,
    DraftStatus,
    KnowledgeEntry,
    ThreadTier,
    CategorizationSource,
)
from app.models.escalation import Escalation, EscalationSeverity, EscalationStatus  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.ai_budget import AIBudgetUsage  # noqa: F401
from app.models.tier_rule import TierRule  # noqa: F401
from app.models.system_setting import SystemSetting  # noqa: F401
from app.models.release import (  # noqa: F401
    Release,
    UserReleaseDismissal,
    ReleaseStatus,
    GeneratedFromSource,
    HighlightCategory,
)
