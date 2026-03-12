"""QueryKnowledgeHandler — serve KG + emit compliance-enabling event."""
import sys
from pathlib import Path

if str(Path(__file__).parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from events.store import EventStore
from events.types import KnowledgeQueriedEvent
from services import KnowledgeService


class QueryKnowledgeHandler:
    def __init__(self, knowledge: KnowledgeService, events: EventStore):
        self._knowledge = knowledge
        self._events = events

    async def handle(self, payload: dict, session_id: str) -> dict:
        kg = self._knowledge.get_knowledge_map()
        self._events.append(KnowledgeQueriedEvent(
            aggregate_id="knowledge_graph",
            session_id=session_id,
            payload={"map_id": payload.get("map_id", ""), "graph_version": kg["graph_version"]},
        ))
        return kg
