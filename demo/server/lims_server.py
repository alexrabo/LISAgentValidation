"""
LIMS MCP Server — presentation layer only.

Responsibilities:
  - Build the object graph (composition root)
  - Bind MCP tool names to handlers
  - Mount middleware stack
  - Expose /health endpoint

No business logic lives here. Each tool function is a one-liner that
extracts the session ID and delegates to the appropriate handler.

Design note: Dispatcher pattern was reviewed and dropped in favour of
direct handler references. Middleware (throttle/auth/log) covers all
cross-cutting concerns at the HTTP boundary. With 5 tools and concerns
handled by middleware, a string-dispatch layer adds indirection without
value. See project_architecture.md for the full rationale.
"""
import sys
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

# Ensure server/ is always importable
_here = Path(__file__).parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from fastapi import FastAPI
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

import lims_db
from circuit_breaker import triage_circuit
from commands.advance_sample import AdvanceSampleHandler
from commands.apply_autoverification import ApplyAutoverificationHandler
from commands.create_sample import CreateSampleHandler
from middleware.auth import OpenIDMiddleware
from middleware.logging import RequestLoggingMiddleware
from middleware.throttling import ThrottlingMiddleware
from queries.get_audit_log import GetAuditLogHandler
from queries.query_knowledge import QueryKnowledgeHandler
from services import AuditService, ComplianceService, KnowledgeService, LimsService
from settings import settings


# ── Pydantic input models ─────────────────────────────────────────────────────

class QueryKnowledgeInput(BaseModel):
    map_id: str = "contamination_swap_map"


class CreateSampleInput(BaseModel):
    specimen_id: str
    patient_id: str
    values: dict
    patient_prior: dict


class AdvanceSampleInput(BaseModel):
    specimen_id: str
    to_status: str


class WorkflowParams(BaseModel):
    contamination_hold_threshold: float
    swap_hold_threshold: float
    delta_check_sd_threshold: float  # CLSI EP33 Section 4.3 Table 2 — maps to zscore_threshold in triage.py


class ApplyAutoverificationInput(BaseModel):
    specimen_id: str
    workflow_params: WorkflowParams


class GetAuditLogInput(BaseModel):
    specimen_id: str | None = None


# ── Composition root ──────────────────────────────────────────────────────────

_executor = ProcessPoolExecutor()  # module-level — must not be created inside a handler

_lims       = LimsService(db=lims_db)
_knowledge  = KnowledgeService()
_compliance = ComplianceService(db=lims_db)
_audit      = AuditService(db=lims_db)
from events.store import EventStore
_events_store = EventStore()

_create_sample          = CreateSampleHandler(_lims, _events_store)
_advance_sample         = AdvanceSampleHandler(_lims, _events_store)
_apply_autoverification = ApplyAutoverificationHandler(
    service=_lims,
    compliance=_compliance,
    events=_events_store,
    circuit=triage_circuit,
    executor=_executor,
)
_query_knowledge = QueryKnowledgeHandler(_knowledge, _events_store)
_get_audit_log   = GetAuditLogHandler(_audit, _events_store)


# ── Session ID extraction ─────────────────────────────────────────────────────

def _session_id(ctx: Context) -> str:
    """Extract X-Session-ID from request headers. Generates UUID if missing."""
    try:
        sid = ctx.request_context.request.headers.get("X-Session-ID", "").strip()
        if sid:
            return sid
    except AttributeError:
        pass
    return str(uuid4())


# ── FastMCP + FastAPI apps ────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(application: FastAPI):
    lims_db.DB_PATH = settings.db_path
    lims_db.init_db()
    yield


mcp = FastMCP("lims-server")
app = FastAPI(title="LIMS MCP Server", lifespan=lifespan)

# Middleware — applied in order: throttle → auth → log
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(OpenIDMiddleware)
app.add_middleware(ThrottlingMiddleware, requests_per_minute=settings.throttle_rpm)


@app.get("/health")
def health():
    kg = _knowledge.get_knowledge_map()
    return {"status": "ok", "kg_version": kg["graph_version"], "port": 8000}


# ── MCP tool bindings — one line each ────────────────────────────────────────

@mcp.tool()
async def query_knowledge(input: QueryKnowledgeInput, ctx: Context) -> dict:
    return await _query_knowledge.handle(input.model_dump(), _session_id(ctx))


@mcp.tool()
async def create_sample(input: CreateSampleInput, ctx: Context) -> dict:
    return await _create_sample.handle(input.model_dump(), _session_id(ctx))


@mcp.tool()
async def advance_sample(input: AdvanceSampleInput, ctx: Context) -> dict:
    return await _advance_sample.handle(input.model_dump(), _session_id(ctx))


@mcp.tool()
async def apply_autoverification(input: ApplyAutoverificationInput, ctx: Context) -> dict:
    payload = input.model_dump()
    payload["workflow_params"] = payload["workflow_params"]  # already a dict after model_dump
    return await _apply_autoverification.handle(payload, _session_id(ctx))


@mcp.tool()
async def get_audit_log(input: GetAuditLogInput, ctx: Context) -> list:
    return await _get_audit_log.handle(input.model_dump(), _session_id(ctx))


# Mount MCP SSE app at /mcp — /health remains a clean FastAPI route
app.mount("/mcp", mcp.sse_app())
