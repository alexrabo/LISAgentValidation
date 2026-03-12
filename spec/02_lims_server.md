# Task 02 — FastAPI MCP LIMS Server
**Output file:** `demo/server/lims_server.py`  
**Depends on:** Task 01 (`lims_db.py` must exist)  
**Global constraints:** see `IMPL_SPEC.md`

---

## Purpose
FastAPI server exposing 5 MCP tools over HTTP/SSE. Port 8000.
Calls `triage.py` as subprocess for autoverification.
All state stored in SQLite via `lims_db.py`.

---

## Setup

```python
# demo/server/requirements.txt
fastapi
uvicorn[standard]
mcp[cli]
```

```bash
# Run with:
uvicorn lims_server:app --host 0.0.0.0 --port 8000
```

Session ID: extract from request header `X-Session-ID`. If missing, generate UUID and return it.

---

## Tool 1: `query_knowledge`

```
POST /tools/query_knowledge
Body: {"map_id": "contamination_swap_map"}
```

Behavior:
1. Read `clinical_knowledge.json` from path defined in `IMPL_SPEC.md`
2. Log to audit_log: `{tool: "query_knowledge", args: {map_id}, result: {graph_version, map_id}}`
3. Return full JSON content of the knowledge graph

Response:
```json
{
  "graph_version": "CLSI_EP33_2023_v1",
  "map_id": "contamination_swap_map",
  "nodes": { ... },
  "paths": { ... }
}
```

---

## Tool 2: `create_sample`

```
POST /tools/create_sample
Body: {
  "specimen_id": "S101",
  "patient_id": "P002",
  "values": {"K": 6.9, "Ca": 7.1, "Na": 137.5, "Cl": 100.8, "HCO3": 21.8, "Glucose": 112},
  "patient_prior": {"mean": {"K": 4.1, ...}, "sd": {"K": 0.25, ...}}
}
```

Behavior:
1. Call `lims_db.create_specimen(...)` — raises if duplicate
2. Log tool call to audit_log
3. Return creation record

Response:
```json
{"specimen_id": "S101", "status": "created", "snapshot_hash": "<sha256>", "created_at": "<iso8601>"}
```

---

## Tool 3: `advance_sample`

```
POST /tools/advance_sample
Body: {"specimen_id": "S101", "to_status": "analyzed"}
```

Behavior:
1. Call `lims_db.update_specimen_status(...)`
2. Log tool call
3. Return transition record

Response:
```json
{"specimen_id": "S101", "previous_status": "created", "new_status": "analyzed"}
```

---

## Tool 4: `apply_autoverification`

```
POST /tools/apply_autoverification
Body: {"specimen_id": "S101", "workflow_params": {"contamination_hold_threshold": 0.5, "swap_hold_threshold": 0.25, "zscore_threshold": 3.0}}
```

**Guard:** check `lims_db.query_knowledge_was_called(session_id)`.  
If False, return:
```json
{"error": "query_knowledge must be called before apply_autoverification", "code": "PROVENANCE_GUARD"}
```

Behavior:
1. Get specimen from SQLite
2. Get ALL specimens (for swap pairwise comparison) — triage.py needs full batch
3. Write temp `batch.json` and `workflow.json` to `/tmp/`
4. Run: `python3 <triage_path> --batch /tmp/batch.json --workflow /tmp/workflow.json --out /tmp/decisions.json`
5. Read `/tmp/decisions.json`, extract decision for this specimen_id
6. Call `lims_db.record_decision(...)`
7. Log tool call with full result
8. Return decision

Response:
```json
{
  "specimen_id": "S101",
  "decision": "HOLD",
  "contamination_score": 1.42,
  "swap_score": 0.0,
  "workflow_params_used": {"contamination_hold_threshold": 0.5, ...}
}
```

**workflow.json format** (what triage.py expects):
```json
{
  "contamination_hold_threshold": 0.5,
  "swap_hold_threshold": 0.25,
  "zscore_threshold": 3.0,
  "max_holds": 99,
  "contamination_signatures": [
    {
      "name": "EDTA",
      "rule": {"K_min": 6.0, "Ca_max": 7.5},
      "analytes": ["K", "Ca"]
    }
  ],
  "decision_policy": {
    "contamination_hold_threshold": 0.5,
    "swap_hold_threshold": 0.25
  },
  "analyte_weights": {"K": 1.5, "Ca": 1.5, "Na": 0.5, "Cl": 0.5, "HCO3": 0.5, "Glucose": 0.3},
  "swap_detection": {
    "analyte_weights": {"K": 1.5, "Ca": 1.5, "Na": 0.5, "Cl": 0.5, "HCO3": 0.5, "Glucose": 0.3}
  }
}
```

**batch.json format** (what triage.py expects):
```json
{
  "batch_id": "SESSION_BATCH",
  "patients": [
    {"patient_id": "P001", "prior": {"mean": {...}, "sd": {...}}}
  ],
  "specimens": [
    {"specimen_id": "S101", "patient_id": "P002", "values": {...}}
  ]
}
```

---

## Tool 5: `get_audit_log`

```
POST /tools/get_audit_log
Body: {"specimen_id": "S101"}   ← optional filter
```

Behavior:
1. Call `lims_db.get_audit_log(session_id, specimen_id=...)`
2. Return ordered list

Response:
```json
[
  {"tool": "query_knowledge", "args": {"map_id": "contamination_swap_map"}, "timestamp": "..."},
  {"tool": "create_sample", "args": {"specimen_id": "S101", ...}, "timestamp": "..."},
  {"tool": "apply_autoverification", "args": {"specimen_id": "S101"}, "result": {"decision": "HOLD"}, "timestamp": "..."}
]
```

---

## Acceptance Criteria

```bash
# Start server
uvicorn lims_server:app --port 8000 &
sleep 2

# Test query_knowledge guard
curl -s -X POST http://localhost:8000/tools/apply_autoverification \
  -H "Content-Type: application/json" \
  -H "X-Session-ID: test-sess-1" \
  -d '{"specimen_id":"S101","workflow_params":{}}' | python3 -m json.tool
# Expected: {"error": "query_knowledge must be called before apply_autoverification", ...}

# Test full flow
curl -s -X POST http://localhost:8000/tools/query_knowledge \
  -H "X-Session-ID: test-sess-2" \
  -d '{"map_id":"contamination_swap_map"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print('KG ok:', d['graph_version'])"
# Expected: KG ok: CLSI_EP33_2023_v1
```
