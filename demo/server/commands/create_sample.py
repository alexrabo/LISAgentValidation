"""CreateSampleHandler — thin dispatch: validate → service → event → return."""
import sys
from pathlib import Path

if str(Path(__file__).parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from events.store import EventStore
from events.types import SampleCreatedEvent
from services import LimsService


class CreateSampleHandler:
    def __init__(self, service: LimsService, events: EventStore):
        self._service = service
        self._events = events

    async def handle(self, payload: dict, session_id: str) -> dict:
        result = self._service.create_specimen(
            payload["specimen_id"],
            payload["patient_id"],
            payload["values"],
            payload["patient_prior"],
        )
        self._events.append(SampleCreatedEvent(
            aggregate_id=payload["specimen_id"],
            session_id=session_id,
            payload=result,
        ))
        return result
