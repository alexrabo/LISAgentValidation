# LIS MCP Demo — Execution Plan
**Prepared for:** Step-by-step build with review gates between each task
**Model guidance:** Sonnet (default) / Opus (Tasks 02, 04, 07 — see rationale per task)
**Package manager:** `uv` throughout — no pip
**Test framework:** pytest — unit tests written alongside each component, run before marking VERIFIED
**Target:** `demo/` directory — all new code goes here

---

## Reference Reading (before any task)

| File | When to read |
|------|-------------|
| `CONTEXT.md` | Always — repo orientation, sequence diagram, key invariants |
| `IMPL_SPEC.md` | Always — task registry, global constraints, pass criteria |
| `docs_main/LIS_MCP_DEMO_DESIGN_v2.md` | Always — why this system exists, agent workflow, report format |
| `docs_main/system_architecture.md` | Always — negative guardrails, what must never be coupled |
| `spec/NN_*.md` | Per task only — the assigned task's how |

**Read-only files (never modify):**
- `lis-swap-contamination-triage/environment/src/triage.py`
- `lis-swap-contamination-triage/environment/data/clinical_knowledge.json`
- `lis-swap-contamination-triage/environment/data/visible_batch_nolabels.json`
- `lis-swap-contamination-triage/environment/data/visible_batch.json`

---

## Task 00 — Package `lis-triage-engine` wheel

**Model:** Sonnet
**Depends on:** Nothing — do this before bootstrap
**Outputs:** modified `lis-swap-contamination-triage/environment/pyproject.toml`, `run_triage()` function added to `triage.py`

### Why first

Every other task depends on `from lis_triage_engine import run_triage` resolving. The wheel must exist and be importable before Task 02 can be written or tested.

### Implementation steps

1. Update `lis-swap-contamination-triage/environment/pyproject.toml`:

```toml
[project]
name = "lis-triage-engine"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = []

[project.scripts]
lis-triage = "triage:main"    # CLI entry point preserved for debugging

[tool.uv]
package = true
```

2. Add `run_triage()` public API to the **bottom** of `triage.py` — no changes to existing logic:

```python
def run_triage(batch: dict, workflow: dict) -> dict:
    """
    Importable entry point for lims_server.py.
    Accepts dicts directly (no file I/O). Returns decisions keyed by specimen_id.
    Returns: {specimen_id: {"decision": "HOLD"|"RELEASE",
                             "contamination_score": float,
                             "swap_score": float}}
    """
    # implementation wraps existing triage logic
```

3. Verify the package builds and imports:

```bash
cd lis-swap-contamination-triage/environment
uv build                              # produces dist/lis_triage_engine-1.0.0-*.whl
uv run python -c "from triage import run_triage; print('import OK')"
```

4. Verify `run_triage()` returns correct decisions against known batch:

```bash
uv run python -c "
from triage import run_triage
import json

batch = json.load(open('data/visible_batch_nolabels.json'))
workflow = {
    'contamination_hold_threshold': 0.5,
    'swap_hold_threshold': 0.25,
    'zscore_threshold': 2.0,
    'max_holds': 99,
    'contamination_signatures': [{'name':'EDTA','rule':{'K_min':6.0,'Ca_max':7.5},'analytes':['K','Ca']}],
    'decision_policy': {'contamination_hold_threshold': 0.5, 'swap_hold_threshold': 0.25},
    'analyte_weights': {'K':1.5,'Ca':1.5,'Na':0.5,'Cl':0.5,'HCO3':0.5,'Glucose':0.3},
    'swap_detection': {'analyte_weights': {'K':1.5,'Ca':1.5,'Na':0.5,'Cl':0.5,'HCO3':0.5,'Glucose':0.3}}
}
decisions = run_triage(batch, workflow)
assert decisions['S101']['decision'] == 'HOLD', 'Contamination S101 must be HOLD'
assert decisions['S100']['decision'] == 'RELEASE', 'Normal S100 must be RELEASE'
print('run_triage: PASS')
print(decisions)
"
```

### Review gate
- [x] `uv build` succeeds — wheel at `dist/lis_triage_engine-1.0.0-py3-none-any.whl`
- [x] `from lis_triage_engine import run_triage` imports cleanly from installed wheel
- [x] `run_triage()` returns correct HOLD/RELEASE for known specimens
- [x] No changes to contamination scoring or swap scoring logic
- [x] CLI still works via `lis-triage` entry point

### ✅ VERIFIED — key findings for downstream tasks

**Package structure:**
```
src/
  lis_triage_engine/
    __init__.py     ← exports run_triage via relative import (.triage)
    triage.py       ← scoring logic (copied from src/triage.py)
  triage.py         ← original untouched (TerminalBench Docker uses this path)
```

**Critical for Task 02b and Task 07:** `run_triage()` requires `mode: "prior_relative"` in
`contamination_signatures` to correctly detect S107 (K=6.2, Ca=7.8). In absolute mode,
S107 is missed because Ca=7.8 > Ca_max=7.5. In prior_relative mode, Ca=7.8 is -4.6 SDs
below that patient's prior mean of 9.4 — correctly flagged. The agent's `workflow.json`
must use prior_relative mode. The KG prescribes this via `K_acute_rise.threshold_SD = 3.0`
and `Ca_acute_fall.threshold_SD`. Task 07 prompt must guide the agent to derive this from
the graph, not hardcode it.

---

## Project Bootstrap (do once, after Task 00)

```bash
mkdir -p demo/server demo/harness demo/agent demo/tests demo/config

cd demo

# Initialize uv project
uv init --name lis-mcp-validation-demo --python 3.11

# Runtime dependencies — lis-triage-engine via local path source
uv add fastapi "uvicorn[standard]" "mcp[cli]"

# Add lis-triage-engine as local path dependency
# (adds to pyproject.toml [tool.uv.sources])
uv add lis-triage-engine --source path=../lis-swap-contamination-triage/environment

# Dev/test + lint dependencies (ruff already installed system-wide, pin in project too)
uv add --dev pytest pytest-asyncio httpx ruff

# Verify imports
uv run python -c "from lis_triage_engine import run_triage; print('wheel OK')"
uv run python --version   # must be 3.10+
uv run pytest --version
uv run ruff --version
```

**pyproject.toml additions** (after uv init):
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "F",   # pyflakes
    "I",   # isort
    "UP",  # pyupgrade
    "B",   # flake8-bugbear
]
ignore = ["E501"]  # line length handled by formatter

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.uv.scripts]
dev     = "uvicorn server.lims_server:app --port 8000 --reload"
test    = "pytest tests/ -v"
lint    = "ruff check server/ harness/ tests/"
fmt     = "ruff format server/ harness/ tests/"
seed    = "python harness/run_validation.py --phase seed --session-id dev-run-1"
eval    = "python harness/run_validation.py --phase evaluate --session-id dev-run-1 --workflow agent/workflow.json --out validation_report.md"
build   = "docker-compose build"
up      = "docker-compose up -d"
down    = "docker-compose down"
```

**Create `.env.example`** (committed — no real values):
```bash
# Copy to .env and fill in — never commit .env
KG_JSON_B64=<base64 encoded clinical_knowledge.json>
DB_PATH=/app/data/lims.db
```

**Create `demo/.gitignore`:**
```
.env
data/
config/clinical_knowledge.json
__pycache__/
*.pyc
.venv/
```

**Output:** `demo/pyproject.toml`, `demo/.venv/`, `demo/tests/`, `demo/.env.example`, `demo/.gitignore`, `lis-triage-engine` importable

---

## Execution Order

```
Task 00 (lis-triage-engine wheel)
    │
    REVIEW GATE
    │
Bootstrap (uv init, add deps, .env.example, .gitignore)
    │
    ├──► Task 01 (lims_db.py)  ◄── nothing depends before this
    │         │
    │    REVIEW GATE ──► Task 03 (scenarios.csv) ← independent, run in parallel
    │         │
    │    REVIEW GATE ──► Task 02a (infrastructure)  ← needs Task 00 + 01 VERIFIED
    │         │          Task 04 (provenance_verifier.py) ← parallel with 02a
    │         │          Task 05 (report.py) ← parallel with 02a
    │         │
    │    REVIEW GATE ──► Task 02b (handlers + wiring) ← needs Task 02a VERIFIED
    │         │
    │    REVIEW GATE ──► Task 06 (run_validation.py) ← needs 01, 02b, 03, 04, 05 VERIFIED
    │         │
    │    REVIEW GATE ──► Task 07 (task_prompt.md) ← needs 02b running
    │         │
    │    REVIEW GATE ──► Task 08 (docker-compose + README) ← needs 01–07 VERIFIED
    │         │
    │    REVIEW GATE ──► End-to-end test run
```

---

## Task 01 — `demo/server/lims_db.py`

**Model:** Sonnet
**Depends on:** Bootstrap complete
**Outputs:** `demo/server/lims_db.py`, `demo/tests/test_lims_db.py`

### Implementation steps

1. Create `demo/server/lims_db.py` with:
   - `DB_PATH = "lims.db"` (relative — server sets cwd to `demo/`)
   - `init_db()` — CREATE TABLE IF NOT EXISTS for both tables
   - `create_specimen()` — SHA256 hash of `json.dumps(values, sort_keys=True)`, raises `ValueError` on duplicate
   - `get_specimen()` — returns full row as dict or None
   - `update_specimen_status()` — validates transitions: `created→analyzed`, `analyzed→pending_review` only; raises `ValueError` on illegal transition or unknown ID
   - `record_decision()` — UPDATE only decision fields; does NOT touch `values_json` or `patient_prior_json`
   - `log_tool_call()` — INSERT with `datetime.utcnow().isoformat() + "Z"`
   - `get_audit_log()` — SELECT ordered by id ASC; optional `specimen_id` filter via `LIKE`
   - `query_knowledge_was_called()` — COUNT check, returns bool
   - `get_all_decisions()` — SELECT specimen_id, decision, contamination_score, swap_score

2. Write `demo/tests/test_lims_db.py`:

```python
# Tests to implement:
# test_init_creates_tables
# test_create_specimen_returns_correct_fields
# test_create_specimen_computes_sha256_correctly
# test_create_specimen_raises_on_duplicate
# test_get_specimen_returns_none_for_unknown
# test_update_status_valid_transitions
# test_update_status_raises_on_illegal_transition
# test_update_status_raises_on_unknown_specimen
# test_record_decision_does_not_change_values_json
# test_log_tool_call_appends
# test_get_audit_log_ordered_by_id
# test_get_audit_log_filters_by_specimen_id
# test_query_knowledge_was_called_true
# test_query_knowledge_was_called_false_for_unknown_session
# test_get_all_decisions
```

Each test uses a fresh `tmp_path`-scoped DB (monkeypatched `DB_PATH`).

### Verification

```bash
cd demo

# Spec acceptance test
uv run python -c "
import sys; sys.path.insert(0, 'server')
import lims_db, json
lims_db.init_db()
r = lims_db.create_specimen('S001', 'P001', {'K': 4.1, 'Ca': 9.4}, {'mean': {'K': 4.0}, 'sd': {'K': 0.3}})
print('created:', r)
lims_db.update_specimen_status('S001', 'analyzed')
lims_db.log_tool_call('sess1', 'query_knowledge', {'map_id': 'test'}, {'ok': True})
print('kg_called:', lims_db.query_knowledge_was_called('sess1'))
print('PASS')
"

# Pytest
uv run pytest tests/test_lims_db.py -v
```

**Expected:** `kg_called: True`, `PASS`, all pytest tests green

### Review gate
- [x] Spec acceptance test passes
- [x] All pytest tests green
- [x] `values_json` is never modified after insert (verify via test)
- [x] Update `IMPL_SPEC.md`: Task 01 → `VERIFIED`

---

## Task 03 — `demo/harness/scenarios.csv` + `demo/harness/expected_outcomes.csv`

**Model:** Sonnet
**Depends on:** Bootstrap only (independent of Task 01)
**Outputs:** `demo/harness/scenarios.csv`, `demo/harness/expected_outcomes.csv`, `demo/tests/test_data_integrity.py`

### Implementation steps

1. Write `demo/harness/scenarios.csv` — 11 rows (S100–S110) with all columns from spec:
   `specimen_id, patient_id, scenario_type, K, Ca, Na, Cl, HCO3, Glucose, prior_K_mean, prior_K_sd, prior_Ca_mean, prior_Ca_sd, prior_Na_mean, prior_Na_sd, prior_Cl_mean, prior_Cl_sd, prior_HCO3_mean, prior_HCO3_sd, prior_Glucose_mean, prior_Glucose_sd`

2. Write `demo/harness/expected_outcomes.csv` — 11 rows with:
   `specimen_id, expected_decision, safety_critical, scenario_type, notes`
   - S110 (CKD_NORMAL) → RELEASE — this is the critical interference guard

3. Write `demo/tests/test_data_integrity.py`:

```python
# Tests to implement:
# test_scenarios_has_11_rows
# test_all_specimen_ids_present  (S100–S110)
# test_expected_outcomes_has_11_rows
# test_ckd_specimen_is_release  (S110)
# test_contamination_specimens_are_safety_critical  (S101, S107)
# test_swap_specimens_are_hold  (S105, S106)
# test_normal_specimens_are_release  (S100, S102, S103, S104, S108, S109)
# test_scenario_types_match_between_files
# test_no_expected_decision_column_in_scenarios  (ground truth not in agent-visible file)
```

### Verification

```bash
cd demo
uv run pytest tests/test_data_integrity.py -v

# Spec acceptance test
uv run python -c "
import csv
with open('harness/scenarios.csv') as f:
    rows = list(csv.DictReader(f))
assert len(rows) == 11, f'Expected 11 rows, got {len(rows)}'
with open('harness/expected_outcomes.csv') as f:
    outcomes = {r['specimen_id']: r for r in csv.DictReader(f)}
assert outcomes['S110']['expected_decision'] == 'RELEASE', 'CKD test must be RELEASE'
assert outcomes['S101']['safety_critical'] == 'true', 'Contamination must be safety_critical'
assert outcomes['S105']['expected_decision'] == 'HOLD'
assert outcomes['S106']['expected_decision'] == 'HOLD'
print('PASS — 11 scenarios, CKD guard correct, swap pair correct')
"
```

### Review gate
- [x] Spec acceptance test passes
- [x] All pytest tests green
- [x] `scenarios.csv` does NOT contain an `expected_decision` column
- [x] S110 is RELEASE (CKD interference guard confirmed)
- [x] Update `IMPL_SPEC.md`: Task 03 → `VERIFIED`

---

## Task 02a — Infrastructure layer

**Model:** Opus
**Rationale:** Sets the architectural skeleton — every pattern in place before business logic. A reviewer opening the repo should see professional structure immediately.
**Depends on:** Task 00 VERIFIED, Task 01 VERIFIED
**Outputs:** `demo/server/` subdirectories + infrastructure files, `demo/server/settings.py`, `demo/tests/test_infrastructure.py`

### Implementation steps

1. Create directory structure:
```bash
mkdir -p demo/server/commands demo/server/queries demo/server/events demo/server/middleware
touch demo/server/commands/__init__.py demo/server/queries/__init__.py
touch demo/server/events/__init__.py demo/server/middleware/__init__.py
```

2. `demo/server/settings.py` — all env var config in one place:
```python
from pydantic_settings import BaseSettings  # included with fastapi

class Settings(BaseSettings):
    db_path: str = "lims.db"
    kg_json_b64: str | None = None
    kg_path: str = "../../lis-swap-contamination-triage/environment/data/clinical_knowledge.json"
    openid_enabled: bool = False
    openid_issuer: str | None = None   # STUB: set for production
    openid_audience: str | None = None # STUB: set for production
    throttle_rpm: int = 60

settings = Settings()

def load_knowledge_graph() -> dict:
    if settings.kg_json_b64:
        return json.loads(base64.b64decode(settings.kg_json_b64).decode())
    with open(settings.kg_path) as f:
        return json.load(f)
```

3. `demo/server/events/types.py` — domain events:
   - `DomainEvent` base dataclass with `event_id`, `event_type`, `aggregate_id`, `session_id`, `payload`, `timestamp`
   - Concrete: `SampleCreatedEvent`, `SampleAdvancedEvent`, `AutoverificationAppliedEvent`, `KnowledgeQueriedEvent`, `AuditLogQueriedEvent`

4. `demo/server/events/store.py` — `EventStore`:
   - `append(event)` → writes to `lims_db.log_tool_call`
   - `get_stream(session_id)` → reads from `lims_db.get_audit_log`
   - `replay(aggregate_id, session_id)` → filters stream by aggregate
   - `_publish(event)` → **STUB** no-op, comment documents GCP Pub/Sub path

5. `demo/server/circuit_breaker.py` — full `CircuitBreaker` implementation (CLOSED/OPEN/HALF_OPEN), module-level `triage_circuit` instance

6. `demo/server/middleware/logging.py` — `RequestLoggingMiddleware` (structured JSON)
7. `demo/server/middleware/auth.py` — `OpenIDMiddleware` (STUB, passthrough when `OPENID_ENABLED=false`)
8. `demo/server/middleware/throttling.py` — `ThrottlingMiddleware` + `_TokenBucket`

9. `demo/server/dispatcher.py` — `ToolDispatcher` + `CommandBus` + `QueryBus` shells (handlers registered but not yet implemented — filled in Task 02b)

10. `demo/tests/test_infrastructure.py`:
```python
# Tests:
# test_circuit_breaker_closed_passes_through
# test_circuit_breaker_opens_after_threshold_failures
# test_circuit_breaker_rejects_when_open
# test_circuit_breaker_half_open_after_timeout
# test_circuit_breaker_closes_on_recovery
# test_event_store_append_writes_to_audit_log
# test_event_store_get_stream_returns_ordered_events
# test_event_store_replay_filters_by_aggregate
# test_throttling_middleware_passes_under_limit
# test_throttling_middleware_blocks_over_limit
# test_auth_middleware_passthrough_when_disabled
# test_auth_middleware_rejects_missing_token_when_enabled
# test_settings_loads_kg_from_b64
# test_settings_loads_kg_from_path
```

### Architecture decisions made during 02a (record of changes from original plan)

**`dispatcher.py` — DELETED.** Dispatcher pattern reviewed and dropped. MCP framework owns
tool→function routing via `@mcp.tool()`. With 5 tools and middleware handling all
cross-cutting concerns (throttle/auth/log) at the HTTP boundary, a string-dispatch layer
adds indirection without value. Direct handler references used instead in `lims_server.py`.

**Service layer added — not in original plan.** `services.py` introduces four services so
handlers never touch `lims_db` directly:
- `LimsService` — specimen lifecycle (create, advance, record, get_all)
- `KnowledgeService` — KG loading (abstracts env vars / file I/O from handlers)
- `ComplianceService` — provenance guard (`knowledge_was_queried`)
- `AuditService` — audit trail reads (`get_log`)
`EventStore` remains the write side of the audit ledger (unchanged).

**`settings.py` kg_path** — changed from relative `../../lis-swap-contamination-triage/...`
to absolute path derived from `__file__`. Relative path broke when tests run from `demo/`.
Task 08 will change default to `config/clinical_knowledge.json` for self-containment.

**`lims_server.py` mount** — MCP SSE app mounted at `/mcp` (not `/`). FastMCP v1.26 exposes
`sse_app()` not `get_asgi_app()`. `@on_event("startup")` replaced with `lifespan` context
manager (FastAPI deprecation).

**`circuit_breaker.py`** — `run_in_executor` returns `asyncio.Future` not a coroutine.
Changed `coro.close()` → `coro.cancel()` (Future API) with coroutine fallback.

**`_build_batch()` in apply_autoverification.py** — corrected format to match `run_triage()`:
`patients` is a list (not dict), key is `specimen_id` (not `id`).

### Review gate
- [x] All directories and `__init__.py` files created
- [x] `EventStore` wraps `lims_db` audit_log correctly
- [x] `CircuitBreaker` state machine transitions verified by tests
- [x] All three middleware classes present — auth stub clearly documented
- [x] `dispatcher.py` deleted — direct handler references used (see decision above)
- [x] `settings.py` drives all env var config — no `os.environ.get()` outside settings
- [x] All pytest tests green (14/14)
- [x] Update `IMPL_SPEC.md`: Task 02a → `VERIFIED`

---

## Task 02b — Command/Query handlers + server wiring

**Model:** Opus
**Rationale:** Business logic — provenance guard, ProcessPoolExecutor + circuit breaker, decision cache, Pydantic models, full tool contract
**Depends on:** Task 02a VERIFIED
**Outputs:** `demo/server/commands/`, `demo/server/queries/`, `demo/server/lims_server.py`, `demo/tests/test_lims_server.py`

### Implementation steps

1. Pydantic input models in `demo/server/commands/__init__.py` and `demo/server/queries/__init__.py`:
```python
# Shared models used by both commands and lims_server tool bindings
class QueryKnowledgeInput(BaseModel):
    map_id: str

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
    zscore_threshold: float

class ApplyAutoverificationInput(BaseModel):
    specimen_id: str
    workflow_params: WorkflowParams

class GetAuditLogInput(BaseModel):
    specimen_id: str | None = None
```

2. `commands/create_sample.py` — `CreateSampleHandler`:
   - Calls `lims_db.create_specimen()`, appends `SampleCreatedEvent`

3. `commands/advance_sample.py` — `AdvanceSampleHandler`:
   - Calls `lims_db.update_specimen_status()`, appends `SampleAdvancedEvent`

4. `commands/apply_autoverification.py` — `ApplyAutoverificationHandler` (most complex):
   - Provenance guard: `lims_db.query_knowledge_was_called(session_id)` — return PROVENANCE_GUARD error, do NOT append event
   - Session decision cache: `_decision_cache: dict[str, dict]` at module level
   - If not cached: get all specimens, build batch + workflow dicts, call `await triage_circuit.call(loop.run_in_executor(_executor, run_triage, batch, workflow))`
   - `lims_db.record_decision()`, append `AutoverificationAppliedEvent`
   - Return decision for this specimen_id

5. `queries/query_knowledge.py` — `QueryKnowledgeHandler`:
   - `load_knowledge_graph()`, append `KnowledgeQueriedEvent`, return full KG

6. `queries/get_audit_log.py` — `GetAuditLogHandler`:
   - `event_store.get_stream(session_id)`, optional specimen_id filter, append `AuditLogQueriedEvent`

7. `demo/server/lims_server.py` — thin wiring layer only (see architecture doc sketch)

8. `demo/tests/test_lims_server.py`:
```python
# Tests (TestClient — no live server):
# test_health_returns_ok_and_kg_version
# test_query_knowledge_returns_full_graph
# test_query_knowledge_logs_knowledge_queried_event
# test_kg_loads_from_kg_json_b64
# test_kg_loads_from_kg_path
# test_create_sample_returns_creation_record
# test_create_sample_emits_sample_created_event
# test_create_sample_rejects_missing_specimen_id        ← Pydantic
# test_create_sample_rejects_missing_values             ← Pydantic
# test_advance_sample_returns_transition
# test_advance_sample_rejects_invalid_to_status_type    ← Pydantic
# test_provenance_guard_blocks_before_query_knowledge
# test_provenance_guard_does_not_emit_event_on_block
# test_apply_autoverification_returns_hold_for_contamination  (integration)
# test_apply_autoverification_returns_release_for_normal
# test_apply_autoverification_uses_cache_on_second_call
# test_apply_autoverification_rejects_missing_workflow_params  ← Pydantic
# test_circuit_breaker_surfaces_error_to_agent_on_open
# test_get_audit_log_returns_ordered_events
# test_session_id_generated_if_missing_from_header
# test_different_sessions_isolated_in_cache
# test_different_sessions_isolated_in_event_stream
```

### Verification

```bash
cd demo

export KG_JSON_B64=$(base64 -i ../lis-swap-contamination-triage/environment/data/clinical_knowledge.json | tr -d '\n')
uv run uvicorn server.lims_server:app --port 8000 &
sleep 2

# Provenance guard
curl -s -X POST http://localhost:8000/tools/apply_autoverification \
  -H "Content-Type: application/json" -H "X-Session-ID: t1" \
  -d '{"specimen_id":"S101","workflow_params":{"contamination_hold_threshold":0.5,"swap_hold_threshold":0.25,"zscore_threshold":2.0}}' \
  | python3 -m json.tool
# Expected: PROVENANCE_GUARD

# query_knowledge
curl -s -X POST http://localhost:8000/tools/query_knowledge \
  -H "Content-Type: application/json" -H "X-Session-ID: t2" \
  -d '{"map_id":"contamination_swap_map"}' | python3 -c "
import sys,json; d=json.load(sys.stdin); print('KG:', d['graph_version'])"
# Expected: KG: CLSI_EP33_2023_v1

curl -s http://localhost:8000/health | python3 -m json.tool
kill %1

uv run pytest tests/test_infrastructure.py tests/test_lims_server.py -v
```

### Architecture decisions made during 02b

**Handlers take `session_id: str` directly** — not `ctx`. Session ID extracted once in
`lims_server.py` `_session_id(ctx)` helper and passed as a plain string. Handlers have
zero dependency on FastMCP Context — fully unit-testable without framework mocks.

**Pydantic models live in `lims_server.py`** — not in commands/__init__.py as originally
planned. They are presentation-layer concerns (MCP tool input validation), not domain
concerns. Handlers work with plain dicts.

**No handler-to-handler calls** — Phase 1/2 separation eliminates that need. Harness seeds
specimens before agent runs. If multi-handler orchestration is needed in Q2, use Saga pattern.

### Review gate
- [x] `lims_server.py` contains only tool bindings — no business logic
- [x] Provenance guard in `ComplianceService` — does NOT emit event on block
- [x] `apply_autoverification` uses `triage_circuit.call()` wrapping `run_in_executor`
- [x] Decision cache session-scoped (`handler._cache`), correct HOLD/RELEASE for known specimens
- [x] Pydantic validation tests pass (models tested directly — not via HTTP 422)
- [x] All events appear in `EventStore` stream after each tool call
- [x] All pytest tests green (22/22)
- [x] Update `IMPL_SPEC.md`: Task 02b → `VERIFIED`

---

## Task 04 — `demo/harness/provenance_verifier.py`

**Model:** Opus
**Rationale:** Must navigate exact KG node paths — a silent field name mismatch breaks Layer 2 with no obvious error. Requires careful reading of clinical_knowledge.json structure before writing any code.
**Depends on:** Nothing (standalone) — but read KG first
**Pre-read required:**
```bash
cat lis-swap-contamination-triage/environment/data/clinical_knowledge.json
# Confirm exact node names: "decision_rules", "K_acute_rise"
# Confirm exact field names: "contamination_hold_threshold", "swap_hold_threshold", "threshold_SD"
```
**Outputs:** `demo/harness/provenance_verifier.py`, `demo/tests/test_provenance_verifier.py`

### Implementation steps

1. Implement `verify_provenance(workflow_json_path, knowledge_json_path) -> dict`:

```python
EXPECTED_PARAMS = [
    # (workflow_param, kg_node, kg_field, tolerance)
    ("contamination_hold_threshold", "decision_rules", "contamination_hold_threshold", 0.05),
    ("swap_hold_threshold",          "decision_rules", "swap_hold_threshold",          0.05),
    ("zscore_threshold",             "K_acute_rise",   "threshold_SD",                 0.20),
]
```

   - Load both JSON files
   - For each entry: extract `workflow[workflow_param]` and `kg["nodes"][kg_node][kg_field]`
   - If param missing from workflow → verdict `"missing"`
   - If `abs(agent_value - expected_value) <= tolerance` → verdict `"graph-derived"`
   - Otherwise → verdict `"data-fitted"`
   - `overall_verdict`: `"PASS"` if ALL are `"graph-derived"`, else `"FAIL"`

2. CLI: `--workflow`, `--kg`, `--out`; print human-readable summary with ✅/❌

3. Write `demo/tests/test_provenance_verifier.py`:

```python
# Tests to implement:
# test_pass_with_correct_workflow
# test_fail_with_wrong_contamination_threshold
# test_fail_with_wrong_swap_threshold
# test_fail_with_wrong_zscore_threshold
# test_missing_param_verdict_is_missing
# test_overall_verdict_fail_if_any_param_fails
# test_output_contains_all_three_params
# test_evidence_pack_includes_kg_version
# test_tolerance_boundary_pass  (value exactly at tolerance edge)
# test_tolerance_boundary_fail  (value just over tolerance)
```

### Verification

```bash
cd demo

# PASS case
uv run python -c "
import json
wf = {'contamination_hold_threshold': 0.5, 'swap_hold_threshold': 0.25, 'zscore_threshold': 3.0,
      'decision_policy': {'contamination_hold_threshold': 0.5, 'swap_hold_threshold': 0.25}}
with open('/tmp/test_workflow.json', 'w') as f: json.dump(wf, f)
"
uv run python harness/provenance_verifier.py \
  --workflow /tmp/test_workflow.json \
  --kg ../lis-swap-contamination-triage/environment/data/clinical_knowledge.json \
  --out /tmp/evidence_pack.json
uv run python -c "
import json
ep = json.load(open('/tmp/evidence_pack.json'))
assert ep['overall_verdict'] == 'PASS'
assert all(p['verdict'] == 'graph-derived' for p in ep['parameters'])
print('PASS case: PASS')
"

# FAIL case
uv run python -c "
import json
wf = {'contamination_hold_threshold': 0.3, 'swap_hold_threshold': 0.1, 'zscore_threshold': 1.5}
with open('/tmp/bad_workflow.json', 'w') as f: json.dump(wf, f)
"
uv run python harness/provenance_verifier.py \
  --workflow /tmp/bad_workflow.json \
  --kg ../lis-swap-contamination-triage/environment/data/clinical_knowledge.json \
  --out /tmp/ep_bad.json
uv run python -c "
import json
ep = json.load(open('/tmp/ep_bad.json'))
assert ep['overall_verdict'] == 'FAIL'
print('FAIL case correctly detected: PASS')
"

uv run pytest tests/test_provenance_verifier.py -v
```

### Architecture decisions made during 04

**KG node name** — spec said `"decision_rules"` but actual KG uses `"decision_policy"`.
`EXPECTED_PARAMS` uses `"decision_policy"` to match the real KG. Tests confirm correct values:
`contamination_hold_threshold=0.5`, `swap_hold_threshold=0.3`, `K_acute_rise.threshold_SD=3.0`.
Tolerance for swap (0.05) allows agent value 0.25 — `|0.25-0.3|=0.05` exactly at boundary → PASS.

### Review gate
- [x] PASS case returns `overall_verdict: PASS`, all params `graph-derived`
- [x] FAIL case detected correctly
- [x] Tolerance boundary tests pass (10/10 including exact boundary cases)
- [x] Zero imports from `demo/server/`
- [x] All pytest tests green (10/10)
- [x] Update `IMPL_SPEC.md`: Task 04 → `VERIFIED`

---

## Task 05 — `demo/harness/report.py`

**Model:** Sonnet
**Depends on:** Nothing (standalone formatter)
**Outputs:** `demo/harness/report.py`, `demo/tests/test_report.py`

### Implementation steps

1. Implement `generate_report(run_date, agent_model, kg_version, scenario_set, decisions, expected_outcomes, evidence_pack, audit_log, output_path) -> dict`:
   - Compute metrics (tp/fp/fn/tn from decisions vs expected):
     - `precision = tp / (tp + fp)` if denominator > 0 else 0.0
     - `recall = tp / (tp + fn)` if denominator > 0 else 0.0
     - `f1 = 2 * precision * recall / (precision + recall)` if denominator > 0 else 0.0
     - `unsafe_release_count = fn`
     - `false_hold_rate = fp / (fp + tn)` if denominator > 0 else 0.0
   - Render Markdown per spec template (Decision Quality table, Evidence Pack table, Per-Specimen table, Tool Sequence Audit, CKD section)
   - Write to `output_path`
   - Return metrics dict: `{f1, precision, recall, unsafe_release_count, false_hold_rate, passed}`
   - `passed = unsafe_release_count == 0 and f1 >= 0.80 and false_hold_rate <= 0.34`

2. CLI: `--decisions`, `--expected`, `--evidence-pack`, `--audit-log`, `--model`, `--out`

3. Write `demo/tests/test_report.py`:

```python
# Tests to implement:
# test_perfect_decisions_f1_is_1
# test_unsafe_release_counted_correctly
# test_false_hold_rate_calculated_correctly
# test_passed_false_if_unsafe_release
# test_passed_false_if_f1_below_threshold
# test_passed_false_if_false_hold_rate_above_threshold
# test_report_written_to_output_path
# test_report_contains_ckd_section  (S110)
# test_report_contains_evidence_pack_table
# test_report_contains_per_specimen_table
# test_zero_division_handled_gracefully  (no HOLD decisions at all)
```

### Verification

```bash
cd demo
uv run python -c "
import sys; sys.path.insert(0, 'harness')
import report
decisions = [
    {'specimen_id': 'S100', 'decision': 'RELEASE', 'contamination_score': 0.1, 'swap_score': 0.0},
    {'specimen_id': 'S101', 'decision': 'HOLD',    'contamination_score': 1.4, 'swap_score': 0.0},
]
expected = [
    {'specimen_id': 'S100', 'expected_decision': 'RELEASE', 'safety_critical': 'false'},
    {'specimen_id': 'S101', 'expected_decision': 'HOLD',    'safety_critical': 'true'},
]
ep = {'overall_verdict': 'PASS', 'kg_version': 'CLSI_EP33_2023_v1', 'parameters': []}
metrics = report.generate_report('2026-03-18', 'claude-test', 'CLSI_EP33_2023_v1',
    'test_v1', decisions, expected, ep, [], '/tmp/test_report.md')
assert metrics['unsafe_release_count'] == 0
assert metrics['f1'] == 1.0
print('PASS')
"

uv run pytest tests/test_report.py -v
```

### Review gate
- [x] Spec acceptance test passes (f1==1.0, unsafe_release_count==0)
- [x] Zero imports from `demo/server/`
- [x] All pytest tests green (11/11)
- [x] Update `IMPL_SPEC.md`: Task 05 → `VERIFIED`

---

## Task 06 — `demo/harness/run_validation.py`

**Model:** Sonnet
**Depends on:** Tasks 01, 02, 03, 04, 05 all VERIFIED
**Outputs:** `demo/harness/run_validation.py`, `demo/agent/task_prompt_filled.md` (generated at seed time), `demo/tests/test_run_validation.py`

### Implementation steps

1. Implement `--phase seed`:
   - Read `scenarios.csv`
   - For each row: POST `/tools/create_sample` + POST `/tools/advance_sample` (to `analyzed`)
   - Build `patient_prior` from prior columns: `{"mean": {"K": ..., "Ca": ..., ...}, "sd": {...}}`
   - All calls include `X-Session-ID: {session_id}` header
   - On duplicate specimen (409 / ValueError response): skip with warning, do not fail
   - Generate `demo/agent/task_prompt_filled.md`: replace `{SESSION_ID}` and `{SPECIMEN_TABLE}` from `task_prompt.md`
   - Specimen table must NOT include `scenario_type`, `expected_decision`, or any label column

2. Implement `--phase evaluate`:
   - POST `/tools/get_audit_log` (no specimen filter — full session log)
   - Check: does `query_knowledge` appear before any `apply_autoverification` entry? If not, print warning + mark provenance FAIL
   - Read all decisions: `lims_db.get_all_decisions()` (import lims_db directly — harness reads DB, does not call server for this)
   - Load `expected_outcomes.csv`
   - Run `provenance_verifier.py` — call `verify_provenance()` function directly (no subprocess)
   - Call `report.generate_report()` → write `output_path`
   - Print pass/fail summary per spec stdout format

3. Error handling:
   - Server not running → clear message: `"Server not reachable at http://localhost:8000. Run: uvicorn server.lims_server:app --port 8000"`
   - `workflow.json` not found → provenance verdict = FAIL, continue with report
   - 0 autoverification calls → F1=0.0, unsafe_release_count = count of safety_critical rows

4. Write `demo/tests/test_run_validation.py`:

```python
# Tests to implement:
# test_seed_posts_create_and_advance_for_each_specimen
# test_seed_skips_on_duplicate_without_failing
# test_seed_generates_task_prompt_filled
# test_task_prompt_filled_contains_no_ground_truth_labels
# test_task_prompt_filled_contains_session_id
# test_evaluate_handles_missing_workflow_json  (provenance=FAIL, not crash)
# test_evaluate_handles_zero_autoverification_calls
# test_evaluate_checks_query_knowledge_order
```

### Verification

```bash
cd demo

# Start server
uv run uvicorn server.lims_server:app --port 8000 &
sleep 2

# Full smoke test from spec
uv run python harness/run_validation.py --phase seed --session-id smoke-test-1

# Inject known-good decisions directly (simulates agent having run)
uv run python -c "
import sys; sys.path.insert(0, 'server')
import lims_db
decisions = {'S100':'RELEASE','S101':'HOLD','S102':'RELEASE','S103':'RELEASE',
             'S104':'RELEASE','S105':'HOLD','S106':'HOLD','S107':'HOLD',
             'S108':'RELEASE','S109':'RELEASE','S110':'RELEASE'}
for sid, dec in decisions.items():
    lims_db.record_decision(sid, dec, 0.0, 0.0, {})
print('Injected decisions')
"

# Evaluate (no workflow.json — provenance FAIL but metrics PASS)
uv run python harness/run_validation.py --phase evaluate \
  --session-id smoke-test-1 --out /tmp/smoke_report.md

uv run python -c "
text = open('/tmp/smoke_report.md').read()
assert 'Unsafe releases' in text
print('Smoke test PASS')
"

kill %1

uv run pytest tests/test_run_validation.py -v
```

### Review gate
### Architecture decisions made during 06

**Seed via lims_db directly** — original plan called for HTTP POST to `/tools/create_sample`.
Changed to direct lims_db calls because: (1) FastMCP exposes tools via SSE protocol, not
plain HTTP POST; (2) seed happens before the agent runs — the server is not required;
(3) direct DB seeding is faster and more reliable for the harness. The server's purpose
is to give the agent an interface during Phase 2, not to be the only path to the DB.

**display_name in evidence_pack** — evaluate phase uses `p.get('display_name', p['param'])`
to show lab-friendly names (e.g. "Delta Check Divisor (SD)") in the stdout summary.

### Review gate
- [x] Seed phase creates and advances all specimens (8/8 tests)
- [x] `task_prompt_filled.md` contains no ground truth labels
- [x] Evaluate phase produces report correctly
- [x] Missing `workflow.json` handled gracefully (provenance FAIL, report continues)
- [x] `expected_outcomes.csv` never served through any MCP tool
- [x] Zero imports from `demo/server/` in harness (lims_db only via sys.path)
- [x] All pytest tests green (8/8)
- [x] Update `IMPL_SPEC.md`: Task 06 → `VERIFIED`

---

## Task 07 — `demo/agent/task_prompt.md`

**Model:** Opus
**Rationale:** This is a test instrument — it must guide the agent to use `query_knowledge` first and derive thresholds from the graph, without revealing the correct threshold values or ground truth labels. Subtle phrasing errors here invalidate the test.
**Depends on:** Task 02 running (to manually verify prompt works)
**Outputs:** `demo/agent/task_prompt.md`

### Implementation steps

1. Write `demo/agent/task_prompt.md` per spec template with `{SESSION_ID}` and `{SPECIMEN_TABLE}` placeholders

2. **Mandatory constraints to verify manually:**
   - Does NOT contain: `HOLD`, `RELEASE`, any numeric threshold values (0.5, 0.25, 3.0), `expected_decision`
   - DOES explicitly require `query_knowledge` before `apply_autoverification`
   - DOES warn about provenance verification
   - DOES list all 5 tools with correct signatures
   - Specimen table placeholder must omit `scenario_type` column

3. Verify `task_prompt_filled.md` (generated by Task 06 seed) correctly substitutes `{SPECIMEN_TABLE}` from `scenarios.csv` without label columns

### Verification (manual review checklist)

```bash
cd demo

# Check for ground truth leakage
grep -i "HOLD\|RELEASE\|0\.5\|0\.25\|expected_decision\|CONTAMINATION\|SWAP\|NORMAL" \
  agent/task_prompt.md
# Expected: NO MATCHES

# Confirm query_knowledge required
grep -i "query_knowledge" agent/task_prompt.md
# Expected: at least 2 mentions (instruction + tool list)

# Confirm provenance warning present
grep -i "provenance\|knowledge graph" agent/task_prompt.md
# Expected: at least 1 match
```

### Architecture decisions made during 07

**`delta_check_sd_threshold` used throughout** — not `zscore_threshold`. Prompt uses
lab terminology (delta check divisor, CLSI EP33 Section 4.3 Table 2) and points agent
to `nodes.K_acute_rise` in the graph. The internal→external name mapping is in
`_build_workflow()` in `apply_autoverification.py`.

**grep false positives acknowledged** — `contamination_hold_threshold` field name
matches `CONTAMINATION` grep but is a field name, not a scenario label. Prompt is clean.

### Review gate
- [x] No ground truth leakage (HOLD/RELEASE/scenario labels not present)
- [x] `query_knowledge` explicitly required first (6 mentions)
- [x] Provenance warning present (12 mentions)
- [x] All 5 tool signatures correct with `delta_check_sd_threshold`
- [x] Specimen table placeholder omits `scenario_type` and label columns
- [x] Update `IMPL_SPEC.md`: Task 07 → `VERIFIED`

---

## Task 08 — Docker + README

**Model:** Sonnet
**Depends on:** Tasks 01–07 all VERIFIED
**Outputs:** `demo/docker-compose.yml`, `demo/server/Dockerfile`, `demo/README.md`, `demo/config/clinical_knowledge.SAMPLE.json`

### Implementation steps

1. `/health` endpoint already implemented in Task 02. Verify it returns `kg_version` from `load_knowledge_graph()`.

2. Write `demo/server/Dockerfile`:
   - `python:3.11-slim`, install `requirements.txt` via pip
   - `lis-triage-engine` installed from published wheel (requirements.txt includes it)
   - Copy `lims_server.py`, `lims_db.py`
   - `ENV DB_PATH=/app/data/lims.db` — KG injected at runtime via `KG_JSON_B64`, not baked in
   - No volume mounts for KG — self-contained image

3. Write `demo/docker-compose.yml`:
   - Volume: `./data:/app/data` (lims.db persists here — no KG volume)
   - `env_file: .env` (contains `KG_JSON_B64`, `DB_PATH`)
   - No `../../` relative paths — image is self-contained

4. Write `demo/config/clinical_knowledge.SAMPLE.json` — structure only, all threshold values zeroed:
   ```json
   {
     "graph_version": "CLSI_EP33_2023_v1",
     "map_id": "contamination_swap_map",
     "_note": "Sample structure only — values illustrative, not authoritative. Set KG_JSON_B64 with real KG.",
     "nodes": {
       "K_acute_rise": {"threshold_SD": 0.0, "source": "CLSI_EP33"},
       "decision_rules": {"contamination_hold_threshold": 0.0, "swap_hold_threshold": 0.0}
     }
   }
   ```

5. Write `demo/README.md` — include Allotrope ADM Phase 2 callout section:
   ```markdown
   ## Phase 2 — Allotrope ADM Integration (post March 19)
   In production, `create_sample` receives Allotrope Foundation Data Model (ADM)
   documents directly from lab analyzers. ADM adds container_type, instrument_id,
   reagent_lot, and accession chain of custody to every specimen — giving knowledge
   graph rules provenance-aware decision capability that pure delta-check cannot match.
   This demo uses seeded CSV values as a stand-in for that data layer.
   ```

### Verification

```bash
cd demo

# Encode KG for local Docker test
export KG_JSON_B64=$(base64 -i ../lis-swap-contamination-triage/environment/data/clinical_knowledge.json | tr -d '\n')
echo "KG_JSON_B64=$KG_JSON_B64" > .env
echo "DB_PATH=/app/data/lims.db" >> .env

docker-compose up -d
sleep 3
curl -s http://localhost:8000/health | python3 -m json.tool
# Expected: {"status": "ok", "kg_version": "CLSI_EP33_2023_v1", "port": 8000}
docker-compose down
rm .env   # clean up local test secret
```

### Self-containment fixes (required for Task 08)
- `demo/pyproject.toml`: change `lis-triage-engine` source from monorepo path to `wheels/` local copy
  - Copy built `.whl` into `demo/wheels/lis_triage_engine-1.0.0-py3-none-any.whl`
  - `lis-triage-engine = { path = "wheels/lis_triage_engine-1.0.0-py3-none-any.whl" }`
- `demo/server/settings.py`: change default `kg_path` from `../../lis-swap-contamination-triage/...` to `config/clinical_knowledge.json`
  - Copy KG locally into `demo/config/clinical_knowledge.json` (already gitignored)
  - Docker uses `KG_JSON_B64` exclusively — no file path needed in container

### Review gate
### Architecture decisions made during 08

**Self-containment fixes applied:**
- Wheel copied to `demo/wheels/` — pyproject.toml sources updated to local wheel path
- `settings.py` kg_path default changed from monorepo `../../lis-swap-contamination-triage/...`
  to `config/clinical_knowledge.json` (inside demo/)
- Real KG copied to `demo/config/clinical_knowledge.json` (gitignored)
- `demo/config/clinical_knowledge.SAMPLE.json` committed — structure only, values zeroed

**Dockerfile uses KG_JSON_B64 exclusively** — no volume mount for KG.
`demo/data/` volume for lims.db only.

### Review gate
- [x] `/health` returns correct kg_version (verified by test suite)
- [x] `demo/` self-contained — no paths escaping to sibling directories
- [x] `lims.db` stored in `demo/data/` via volume mount
- [x] KG injected via `KG_JSON_B64` — not baked into image
- [x] README includes ALCOA+, Allotrope ADM, two-layer evaluation callouts
- [x] All 96 tests green after self-containment changes
- [x] Update `IMPL_SPEC.md`: Task 08 → `VERIFIED`

---

## End-to-End Test Run

**All tasks must be VERIFIED before this step.**

```bash
cd demo

# 1. Start server
docker-compose up -d

# 2. Fresh DB
rm -f data/lims.db

# 3. Seed
uv run python harness/run_validation.py --phase seed --session-id e2e-run-1

# 4. Hand agent/task_prompt_filled.md to Claude
#    Agent must write agent/workflow.json and call all 5 tools

# 5. Evaluate
uv run python harness/run_validation.py --phase evaluate \
  --session-id e2e-run-1 \
  --workflow agent/workflow.json \
  --out validation_report.md

# 6. Confirm pass criteria
uv run python -c "
import re
text = open('validation_report.md').read()
# Layer 1: decision quality
assert 'Unsafe releases | 0' in text or 'unsafe_release_count: 0' in text
# Layer 2: provenance
assert 'PASS' in text
print('E2E: PASS')
"

docker-compose down
```

**Pass criteria (both layers):**
- `unsafe_release_count == 0`
- `F1 >= 0.80`
- `false_hold_rate <= 0.34`
- `provenance_verdict == PASS`

---

## Full Pytest Suite

Run after all tasks are VERIFIED:

```bash
cd demo
uv run pytest tests/ -v --tb=short

# Coverage report (informational)
uv add --dev pytest-cov
uv run pytest tests/ --cov=server --cov=harness --cov-report=term-missing
```

**Minimum coverage targets:**
- `lims_db.py`: 95%+
- `provenance_verifier.py`: 90%+
- `report.py`: 85%+

---

## Known Tech Debt

| # | Item | File | Post-demo fix |
|---|------|------|---------------|
| 1 | `zscore_threshold` key in `triage.py` | `lis-swap-contamination-triage/environment/src/triage.py` | Rename to `delta_check_sd_threshold` + update all TerminalBench workflow.json fixtures in a coordinated commit. Currently mapped at the MCP boundary in `_build_workflow()`. |
| 2 | `demo/` not self-contained | `demo/pyproject.toml`, `demo/server/settings.py` | Task 08: copy wheel to `demo/wheels/`, change kg_path default to `config/clinical_knowledge.json`. |
| 3 | `[tool.uv.scripts]` not supported by installed uv version | `demo/pyproject.toml` | Remove or replace with Makefile when uv version supports it. Non-blocking. |

---

## Key Invariants (verify at each task)

1. `values_json` and `patient_prior_json` written once in `create_specimen` — never updated
2. `query_knowledge` appears in audit_log before any `apply_autoverification` — enforced by server guard
3. `provenance_verifier.py` imports nothing from `demo/server/`
4. `expected_outcomes.csv` never served through any MCP tool
5. `triage.py` called as subprocess only — never imported
6. Session ID comes from `X-Session-ID` header — server never silently assigns one
7. Audit log is append-only — no DELETE or UPDATE on `audit_log` table
8. Full args and result logged in audit_log — no truncation

---

## Files Created (final state)

```
demo/
  pyproject.toml              ← uv project, fastapi + uvicorn + mcp + pytest
  server/
    lims_db.py                ← Task 01
    lims_server.py            ← Task 02
    requirements.txt          ← Task 02
    Dockerfile                ← Task 08
  harness/
    scenarios.csv             ← Task 03
    expected_outcomes.csv     ← Task 03
    provenance_verifier.py    ← Task 04
    report.py                 ← Task 05
    run_validation.py         ← Task 06
  agent/
    task_prompt.md            ← Task 07
    task_prompt_filled.md     ← generated by Task 06 seed
    workflow.json             ← written by agent at runtime
  tests/
    test_lims_db.py           ← Task 01
    test_lims_server.py       ← Task 02
    test_data_integrity.py         ← Task 03
    test_provenance_verifier.py ← Task 04
    test_report.py            ← Task 05
    test_run_validation.py    ← Task 06
  docker-compose.yml          ← Task 08
  README.md                   ← Task 08
  data/                       ← runtime only (lims.db) — gitignored
```
