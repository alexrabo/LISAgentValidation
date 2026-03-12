"""
Append-only event store backed by SQLite audit_log.
Single source of truth for domain event history.

STUB — _publish() wired but no-op.
Production: GCP Pub/Sub, Redis stream, or NATS — swap body, keep signature.
"""
import sys
from pathlib import Path

# Ensure server/ is importable regardless of working directory
_server_root = str(Path(__file__).parent.parent)
if _server_root not in sys.path:
    sys.path.insert(0, _server_root)

import lims_db

from .types import DomainEvent


class EventStore:
    """Write side of the audit ledger. Append-only."""

    def append(self, event: DomainEvent) -> None:
        lims_db.log_tool_call(
            event.session_id,
            event.event_type,
            {"aggregate_id": event.aggregate_id, **event.payload},
            {"event_id": event.event_id},
        )
        # STUB: asyncio.create_task(self._publish(event))

    def get_stream(self, session_id: str) -> list[dict]:
        return lims_db.get_audit_log(session_id)

    def replay(self, aggregate_id: str, session_id: str) -> list[dict]:
        return [
            e for e in self.get_stream(session_id)
            if e.get("args", {}).get("aggregate_id") == aggregate_id
        ]

    async def _publish(self, event: DomainEvent) -> None:
        """
        STUB — no-op for March 19.
        Production: GCP Pub/Sub topic, Redis stream, or NATS subject.
        Interface stable — swap body, keep signature.
        """
        pass
