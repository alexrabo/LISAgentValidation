"""
Domain event types. One concrete class per MCP tool call.
The audit_log table IS the event store — these types formalize it.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid4())


@dataclass(kw_only=True)
class DomainEvent:
    """Base event. All fields keyword-only to allow subclasses to set event_type default."""
    event_type: str
    aggregate_id: str
    session_id: str
    payload: dict
    event_id: str = field(default_factory=_uid)
    timestamp: str = field(default_factory=_now)


@dataclass(kw_only=True)
class SampleCreatedEvent(DomainEvent):
    event_type: str = "SampleCreated"


@dataclass(kw_only=True)
class SampleAdvancedEvent(DomainEvent):
    event_type: str = "SampleAdvanced"


@dataclass(kw_only=True)
class AutoverificationAppliedEvent(DomainEvent):
    event_type: str = "AutoverificationApplied"


@dataclass(kw_only=True)
class KnowledgeQueriedEvent(DomainEvent):
    event_type: str = "KnowledgeQueried"


@dataclass(kw_only=True)
class AuditLogQueriedEvent(DomainEvent):
    event_type: str = "AuditLogQueried"
