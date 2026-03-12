"""AdvanceSampleHandler — thin dispatch: validate → service → event → return."""
import sys
from pathlib import Path

if str(Path(__file__).parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from events.store import EventStore
from events.types import SampleAdvancedEvent
from services import LimsService


class AdvanceSampleHandler:
    def __init__(self, service: LimsService, events: EventStore):
        self._service = service
        self._events = events

    async def handle(self, payload: dict, session_id: str) -> dict:
        result = self._service.advance_status(
            payload["specimen_id"],
            payload["to_status"],
        )
        self._events.append(SampleAdvancedEvent(
            aggregate_id=payload["specimen_id"],
            session_id=session_id,
            payload=result,
        ))
        return result
