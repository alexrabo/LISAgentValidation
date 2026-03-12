"""GetAuditLogHandler — return ordered audit trail for a session."""
import sys
from pathlib import Path

if str(Path(__file__).parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from events.store import EventStore
from events.types import AuditLogQueriedEvent
from services import AuditService


class GetAuditLogHandler:
    def __init__(self, audit: AuditService, events: EventStore):
        self._audit = audit
        self._events = events

    async def handle(self, payload: dict, session_id: str) -> list:
        specimen_filter = payload.get("specimen_id")
        log = self._audit.get_log(session_id, specimen_filter)
        self._events.append(AuditLogQueriedEvent(
            aggregate_id="audit_log",
            session_id=session_id,
            payload={"specimen_id": specimen_filter, "entry_count": len(log)},
        ))
        return log
