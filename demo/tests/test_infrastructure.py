"""
Tests for Task 02a infrastructure components:
  circuit_breaker.py, events/store.py, middleware/*, settings.py
"""
import asyncio
import base64
import json
import sys
from pathlib import Path
from time import monotonic
from unittest.mock import AsyncMock, patch

import pytest

# Make server/ importable
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

import lims_db
from circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState
from events.store import EventStore
from events.types import KnowledgeQueriedEvent, SampleCreatedEvent


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "infra_test.db")
    monkeypatch.setattr(lims_db, "DB_PATH", db_file)
    lims_db.init_db()


# ── CircuitBreaker ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_circuit_breaker_closed_passes_through():
    cb = CircuitBreaker()

    async def ok():
        return "ok"

    result = await cb.call(ok())
    assert result == "ok"


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold_failures():
    cb = CircuitBreaker(failure_threshold=2)

    async def failing():
        raise RuntimeError("boom")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await cb.call(failing())

    assert cb.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_circuit_breaker_rejects_when_open():
    cb = CircuitBreaker(failure_threshold=1)

    async def failing():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await cb.call(failing())

    assert cb.state == CircuitState.OPEN

    async def safe():
        return "ok"

    with pytest.raises(CircuitOpenError):
        await cb.call(safe())


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_after_timeout(monkeypatch):
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)

    async def failing():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await cb.call(failing())

    assert cb.state == CircuitState.OPEN

    # Simulate timeout elapsed by patching _opened_at to far in the past
    cb._opened_at = monotonic() - 1.0

    async def recovered():
        return "recovered"

    # Next call should transition to HALF_OPEN and attempt the call
    result = await cb.call(recovered())
    assert result == "recovered"
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_circuit_breaker_closes_on_recovery():
    cb = CircuitBreaker(failure_threshold=3)

    async def ok():
        return "ok"

    await cb.call(ok())
    assert cb.state == CircuitState.CLOSED
    assert cb._failures == 0


# ── EventStore ────────────────────────────────────────────────────────────────

def test_event_store_append_writes_to_audit_log():
    store = EventStore()
    event = SampleCreatedEvent(
        aggregate_id="S001",
        session_id="sess-test",
        payload={"status": "created"},
    )
    store.append(event)
    rows = lims_db.get_audit_log("sess-test")
    assert len(rows) == 1
    assert rows[0]["tool"] == "SampleCreated"


def test_event_store_get_stream_returns_ordered_events():
    store = EventStore()
    for i in range(3):
        store.append(SampleCreatedEvent(
            aggregate_id=f"S00{i}",
            session_id="sess-order",
            payload={"i": i},
        ))
    rows = store.get_stream("sess-order")
    assert len(rows) == 3
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids)


def test_event_store_replay_filters_by_aggregate():
    store = EventStore()
    store.append(SampleCreatedEvent(
        aggregate_id="S001", session_id="sess-rep", payload={}
    ))
    store.append(KnowledgeQueriedEvent(
        aggregate_id="knowledge_graph", session_id="sess-rep", payload={"map_id": "test"}
    ))
    replayed = store.replay("S001", "sess-rep")
    assert len(replayed) == 1
    assert replayed[0]["args"]["aggregate_id"] == "S001"


# ── ThrottlingMiddleware ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_throttling_middleware_passes_under_limit():
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from middleware.throttling import ThrottlingMiddleware

    def homepage(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(ThrottlingMiddleware, requests_per_minute=60)

    client = TestClient(app, headers={"X-Session-ID": "throttle-test"})
    response = client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_throttling_middleware_blocks_over_limit():
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from middleware.throttling import ThrottlingMiddleware

    def homepage(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", homepage)])
    # rpm=1 means only 1 token initially — second request in rapid succession should fail
    app.add_middleware(ThrottlingMiddleware, requests_per_minute=1)

    client = TestClient(app, headers={"X-Session-ID": "throttle-block"})
    r1 = client.get("/")
    assert r1.status_code == 200
    r2 = client.get("/")
    assert r2.status_code == 429
    assert r2.json()["code"] == "THROTTLED"


# ── OpenIDMiddleware ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auth_middleware_passthrough_when_disabled():
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from middleware.auth import OpenIDMiddleware
    import settings as s

    def homepage(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(OpenIDMiddleware)

    # openid_enabled defaults to False
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_auth_middleware_rejects_missing_token_when_enabled(monkeypatch):
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    import middleware.auth as auth_mod
    from middleware.auth import OpenIDMiddleware

    # Patch settings to enable OpenID
    monkeypatch.setattr(auth_mod.settings, "openid_enabled", True)

    def homepage(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(OpenIDMiddleware)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/")
    assert response.status_code == 401
    assert response.json()["code"] == "MISSING_TOKEN"


# ── Settings / KG loading ─────────────────────────────────────────────────────

def test_settings_loads_kg_from_b64(monkeypatch):
    from settings import load_knowledge_graph
    import settings as s

    kg = {"graph_version": "TEST_V1", "nodes": {}}
    b64 = base64.b64encode(json.dumps(kg).encode()).decode()
    monkeypatch.setattr(s.settings, "kg_json_b64", b64)

    result = load_knowledge_graph()
    assert result["graph_version"] == "TEST_V1"


def test_settings_loads_kg_from_path(tmp_path, monkeypatch):
    from settings import load_knowledge_graph
    import settings as s

    kg = {"graph_version": "PATH_V1", "nodes": {}}
    kg_file = tmp_path / "kg.json"
    kg_file.write_text(json.dumps(kg))

    monkeypatch.setattr(s.settings, "kg_json_b64", None)
    monkeypatch.setattr(s.settings, "kg_path", str(kg_file))

    result = load_knowledge_graph()
    assert result["graph_version"] == "PATH_V1"
