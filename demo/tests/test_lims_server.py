"""
Tests for Task 02b — handlers + lims_server.py

Strategy:
  - Handler unit tests: import handlers directly, inject real services
    with isolated tmp_path DB. No HTTP, no MCP protocol needed.
  - /health: TestClient on the FastAPI app (smoke test only).
  - Pydantic models: tested directly — validation happens at the MCP
    tool binding layer before handlers are called.

Handlers take session_id: str directly, so no Context mock needed.
"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Make server/ importable
_server = str(Path(__file__).parent.parent / "server")
if _server not in sys.path:
    sys.path.insert(0, _server)

import lims_db
from circuit_breaker import CircuitBreaker, CircuitOpenError
from commands.advance_sample import AdvanceSampleHandler
from commands.apply_autoverification import ApplyAutoverificationHandler
from commands.create_sample import CreateSampleHandler
from events.store import EventStore
from queries.get_audit_log import GetAuditLogHandler
from queries.query_knowledge import QueryKnowledgeHandler
from services import AuditService, ComplianceService, KnowledgeService, LimsService


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_server.db")
    monkeypatch.setattr(lims_db, "DB_PATH", db_file)
    lims_db.init_db()


@pytest.fixture()
def svc():
    return LimsService(db=lims_db)


@pytest.fixture()
def events():
    return EventStore()


@pytest.fixture()
def compliance():
    return ComplianceService(db=lims_db)


@pytest.fixture()
def audit():
    return AuditService(db=lims_db)


@pytest.fixture()
def knowledge():
    return KnowledgeService()


@pytest.fixture()
def executor():
    ex = ProcessPoolExecutor(max_workers=1)
    yield ex
    ex.shutdown(wait=False)


@pytest.fixture()
def autoverify(svc, compliance, events, executor):
    return ApplyAutoverificationHandler(
        service=svc,
        compliance=compliance,
        events=events,
        circuit=CircuitBreaker(),
        executor=executor,
    )


def _seed_specimen(specimen_id="S100", patient_id="P001",
                   values=None, prior=None):
    """Insert + advance a specimen to analyzed status."""
    values = values or {"K": 4.1, "Ca": 9.4, "Na": 140, "Cl": 102,
                        "HCO3": 24, "Glucose": 5.2}
    prior = prior or {"mean": {"K": 4.0, "Ca": 9.4, "Na": 140,
                                "Cl": 102, "HCO3": 24, "Glucose": 5.2},
                      "sd":   {"K": 0.3, "Ca": 0.4, "Na": 3.0,
                                "Cl": 3.0, "HCO3": 2.0, "Glucose": 0.5}}
    lims_db.create_specimen(specimen_id, patient_id, values, prior)
    lims_db.update_specimen_status(specimen_id, "analyzed")


# ── /health ───────────────────────────────────────────────────────────────────

def test_health_returns_ok_and_kg_version():
    from fastapi.testclient import TestClient
    from lims_server import app
    client = TestClient(app, raise_server_exceptions=True)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "kg_version" in body
    assert body["kg_version"] == "CLSI_EP33_2023_v1"


# ── query_knowledge ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_knowledge_returns_full_graph(knowledge, events):
    h = QueryKnowledgeHandler(knowledge, events)
    result = await h.handle({"map_id": "contamination_swap_map"}, "sess-qk")
    assert "graph_version" in result
    assert result["graph_version"] == "CLSI_EP33_2023_v1"
    assert "nodes" in result


@pytest.mark.asyncio
async def test_query_knowledge_logs_knowledge_queried_event(knowledge, events):
    h = QueryKnowledgeHandler(knowledge, events)
    await h.handle({"map_id": "contamination_swap_map"}, "sess-log")
    log = lims_db.get_audit_log("sess-log")
    assert any(e["tool"] == "KnowledgeQueried" for e in log)


@pytest.mark.asyncio
async def test_kg_loads_from_kg_path(tmp_path, monkeypatch):
    import settings as s
    kg = {"graph_version": "TEST_V1", "nodes": {}}
    kg_file = tmp_path / "kg.json"
    kg_file.write_text(json.dumps(kg))
    monkeypatch.setattr(s.settings, "kg_json_b64", None)
    monkeypatch.setattr(s.settings, "kg_path", str(kg_file))
    svc = KnowledgeService()
    result = svc.get_knowledge_map()
    assert result["graph_version"] == "TEST_V1"


# ── create_sample ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_sample_returns_creation_record(svc, events):
    h = CreateSampleHandler(svc, events)
    result = await h.handle({
        "specimen_id": "S001", "patient_id": "P001",
        "values": {"K": 4.1}, "patient_prior": {},
    }, "sess-cs")
    assert result["specimen_id"] == "S001"
    assert result["status"] == "created"
    assert "snapshot_hash" in result


@pytest.mark.asyncio
async def test_create_sample_emits_sample_created_event(svc, events):
    h = CreateSampleHandler(svc, events)
    await h.handle({
        "specimen_id": "S002", "patient_id": "P002",
        "values": {"K": 4.1}, "patient_prior": {},
    }, "sess-ev")
    log = lims_db.get_audit_log("sess-ev")
    assert any(e["tool"] == "SampleCreated" for e in log)


@pytest.mark.asyncio
async def test_create_sample_raises_on_duplicate(svc, events):
    h = CreateSampleHandler(svc, events)
    await h.handle({
        "specimen_id": "S003", "patient_id": "P003",
        "values": {"K": 4.1}, "patient_prior": {},
    }, "sess-dup")
    with pytest.raises(ValueError, match="already exists"):
        await h.handle({
            "specimen_id": "S003", "patient_id": "P003",
            "values": {"K": 4.1}, "patient_prior": {},
        }, "sess-dup")


# ── advance_sample ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_advance_sample_returns_transition(svc, events):
    lims_db.create_specimen("S004", "P004", {"K": 4.0}, {})
    h = AdvanceSampleHandler(svc, events)
    result = await h.handle({"specimen_id": "S004", "to_status": "analyzed"}, "sess-adv")
    assert result["previous_status"] == "created"
    assert result["new_status"] == "analyzed"


@pytest.mark.asyncio
async def test_advance_sample_raises_on_illegal_transition(svc, events):
    lims_db.create_specimen("S005", "P005", {"K": 4.0}, {})
    h = AdvanceSampleHandler(svc, events)
    with pytest.raises(ValueError, match="Illegal"):
        await h.handle({"specimen_id": "S005", "to_status": "pending_review"}, "sess-ill")


# ── provenance guard ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_provenance_guard_blocks_before_query_knowledge(autoverify):
    _seed_specimen()
    result = await autoverify.handle({
        "specimen_id": "S100",
        "workflow_params": {"contamination_hold_threshold": 0.5,
                            "swap_hold_threshold": 0.3, "delta_check_sd_threshold": 3.0},
    }, "sess-guard")
    assert result["code"] == "PROVENANCE_GUARD"


@pytest.mark.asyncio
async def test_provenance_guard_does_not_emit_event_on_block(autoverify):
    _seed_specimen()
    await autoverify.handle({
        "specimen_id": "S100",
        "workflow_params": {"contamination_hold_threshold": 0.5,
                            "swap_hold_threshold": 0.3, "delta_check_sd_threshold": 3.0},
    }, "sess-nolog")
    log = lims_db.get_audit_log("sess-nolog")
    # No AutoverificationApplied event should appear
    assert not any(e["tool"] == "AutoverificationApplied" for e in log)


# ── apply_autoverification ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_autoverification_returns_hold_for_contamination(autoverify):
    # S101: K=6.9, Ca=7.1 — clear EDTA contamination
    _seed_specimen("S101", "P101",
                   values={"K": 6.9, "Ca": 7.1, "Na": 138, "Cl": 100,
                           "HCO3": 22, "Glucose": 5.0},
                   prior={"mean": {"K": 4.0, "Ca": 9.4, "Na": 140,
                                   "Cl": 102, "HCO3": 24, "Glucose": 5.0},
                          "sd":   {"K": 0.3, "Ca": 0.4, "Na": 3.0,
                                   "Cl": 3.0, "HCO3": 2.0, "Glucose": 0.5}})
    lims_db.log_tool_call("sess-hold", "query_knowledge", {}, {})
    result = await autoverify.handle({
        "specimen_id": "S101",
        "workflow_params": {"contamination_hold_threshold": 0.5,
                            "swap_hold_threshold": 0.3, "delta_check_sd_threshold": 3.0},
    }, "sess-hold")
    assert result["decision"] == "HOLD"
    assert result["contamination_score"] > 0


@pytest.mark.asyncio
async def test_apply_autoverification_returns_release_for_normal(autoverify):
    _seed_specimen("S100", "P100")
    lims_db.log_tool_call("sess-rel", "query_knowledge", {}, {})
    result = await autoverify.handle({
        "specimen_id": "S100",
        "workflow_params": {"contamination_hold_threshold": 0.5,
                            "swap_hold_threshold": 0.3, "delta_check_sd_threshold": 3.0},
    }, "sess-rel")
    assert result["decision"] == "RELEASE"


@pytest.mark.asyncio
async def test_apply_autoverification_uses_cache_on_second_call(autoverify):
    _seed_specimen("S100", "P100")
    lims_db.log_tool_call("sess-cache", "query_knowledge", {}, {})
    wp = {"contamination_hold_threshold": 0.5,
          "swap_hold_threshold": 0.3, "delta_check_sd_threshold": 3.0}
    # First call populates cache
    r1 = await autoverify.handle({"specimen_id": "S100", "workflow_params": wp},
                                  "sess-cache")
    # Second call should use cache — same result
    r2 = await autoverify.handle({"specimen_id": "S100", "workflow_params": wp},
                                  "sess-cache")
    assert r1["decision"] == r2["decision"]
    assert "sess-cache" in autoverify._cache


@pytest.mark.asyncio
async def test_circuit_breaker_surfaces_error_to_agent_on_open(svc, compliance, events):
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=9999.0)
    ex = ProcessPoolExecutor(max_workers=1)

    handler = ApplyAutoverificationHandler(
        service=svc, compliance=compliance, events=events,
        circuit=cb, executor=ex,
    )
    _seed_specimen("S100", "P100")
    lims_db.log_tool_call("sess-cb", "query_knowledge", {}, {})

    # Force circuit open
    cb.state = __import__("circuit_breaker").CircuitState.OPEN
    cb._opened_at = __import__("time").monotonic()

    result = await handler.handle({
        "specimen_id": "S100",
        "workflow_params": {"contamination_hold_threshold": 0.5,
                            "swap_hold_threshold": 0.3, "delta_check_sd_threshold": 3.0},
    }, "sess-cb")
    assert result["code"] == "TRIAGE_UNAVAILABLE"
    ex.shutdown(wait=False)


# ── get_audit_log ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_audit_log_returns_ordered_events(audit, events):
    for i in range(3):
        lims_db.log_tool_call("sess-alog", f"tool_{i}", {"i": i}, {})
    h = GetAuditLogHandler(audit, events)
    result = await h.handle({}, "sess-alog")
    assert len(result) >= 3
    ids = [e["id"] for e in result]
    assert ids == sorted(ids)


# ── session isolation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_different_sessions_isolated_in_event_stream(knowledge, events):
    h = QueryKnowledgeHandler(knowledge, events)
    await h.handle({"map_id": "test"}, "sess-A")
    await h.handle({"map_id": "test"}, "sess-B")
    log_a = lims_db.get_audit_log("sess-A")
    log_b = lims_db.get_audit_log("sess-B")
    assert len(log_a) == 1
    assert len(log_b) == 1


@pytest.mark.asyncio
async def test_different_sessions_isolated_in_cache(autoverify):
    _seed_specimen("S100", "P100")
    lims_db.log_tool_call("sess-X", "query_knowledge", {}, {})
    lims_db.log_tool_call("sess-Y", "query_knowledge", {}, {})
    wp = {"contamination_hold_threshold": 0.5,
          "swap_hold_threshold": 0.3, "delta_check_sd_threshold": 3.0}
    await autoverify.handle({"specimen_id": "S100", "workflow_params": wp}, "sess-X")
    await autoverify.handle({"specimen_id": "S100", "workflow_params": wp}, "sess-Y")
    assert "sess-X" in autoverify._cache
    assert "sess-Y" in autoverify._cache
    assert autoverify._cache["sess-X"] is not autoverify._cache["sess-Y"]


# ── Pydantic model validation ─────────────────────────────────────────────────

def test_create_sample_rejects_missing_specimen_id():
    from pydantic import ValidationError
    from lims_server import CreateSampleInput
    with pytest.raises(ValidationError):
        CreateSampleInput(patient_id="P001", values={"K": 4.1}, patient_prior={})


def test_create_sample_rejects_missing_values():
    from pydantic import ValidationError
    from lims_server import CreateSampleInput
    with pytest.raises(ValidationError):
        CreateSampleInput(specimen_id="S001", patient_id="P001", patient_prior={})


def test_advance_sample_rejects_missing_to_status():
    from pydantic import ValidationError
    from lims_server import AdvanceSampleInput
    with pytest.raises(ValidationError):
        AdvanceSampleInput(specimen_id="S001")


def test_apply_autoverification_rejects_missing_workflow_params():
    from pydantic import ValidationError
    from lims_server import ApplyAutoverificationInput
    with pytest.raises(ValidationError):
        ApplyAutoverificationInput(specimen_id="S001")
