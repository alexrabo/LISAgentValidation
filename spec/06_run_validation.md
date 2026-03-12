# Task 06 — Validation Orchestrator
**Output file:** `demo/harness/run_validation.py`  
**Depends on:** Tasks 01–05 complete, server running on port 8000  
**Global constraints:** see `IMPL_SPEC.md`

---

## Purpose
Orchestrates the full validation run in three phases. Phases are invoked via --phase flag
so they can be run independently (seed once, then run agent, then evaluate).

---

## Usage

```bash
# Phase 1: seed specimens into LIMS (run before agent)
python3 run_validation.py --phase seed --session-id <id>

# Phase 2: (manual) give agent task_prompt.md + server URL, let it run

# Phase 3: evaluate after agent has completed
python3 run_validation.py --phase evaluate --session-id <id> \
  --workflow /path/to/agent/workflow.json \
  --out validation_report.md
```

---

## Phase 1: Seed

```python
def seed(session_id: str, server_url: str = "http://localhost:8000") -> None:
    """
    For each row in scenarios.csv:
    1. POST /tools/create_sample  (values + patient_prior)
    2. POST /tools/advance_sample (to_status="analyzed")
    Print confirmation for each specimen.
    """
```

All HTTP calls include header `X-Session-ID: {session_id}`.

Build `patient_prior` from scenarios.csv columns:
```python
prior = {
    "mean": {"K": float(row["prior_K_mean"]), "Ca": float(row["prior_Ca_mean"]), ...},
    "sd":   {"K": float(row["prior_K_sd"]),   "Ca": float(row["prior_Ca_sd"]),   ...}
}
```

---

## Phase 3: Evaluate

```python
def evaluate(
    session_id: str,
    workflow_path: str,
    output_path: str,
    server_url: str = "http://localhost:8000",
) -> None:
    """
    1. GET /tools/get_audit_log (no specimen filter — full session log)
    2. Check audit log: was query_knowledge called before any apply_autoverification?
       If not, print warning and mark provenance as FAIL.
    3. Read all decisions from SQLite (or from audit_log result fields)
    4. Load expected_outcomes.csv
    5. Run provenance_verifier.py on workflow_path
    6. Run report.py → write output_path
    7. Print pass/fail summary to stdout
    """
```

---

## Stdout Summary Format

```
=== LIS MCP Validation Run ===
Session: {session_id}
Specimens: 11

Decision Quality:
  F1: 0.91 ✅
  Unsafe releases: 0 ✅
  False hold rate: 0.18 ✅

Provenance:
  contamination_hold_threshold: 0.5 → graph-derived ✅
  swap_hold_threshold: 0.25 → graph-derived ✅
  zscore_threshold: 3.0 → graph-derived ✅
  Overall: PASS ✅

Result: PASS ✅
Report written to: validation_report.md
```

---

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Server not running | Clear error: "Server not reachable at http://localhost:8000. Run: uvicorn lims_server:app --port 8000" |
| Specimen already exists (re-seed) | Skip with warning, do not fail |
| workflow.json not found | Provenance verdict = FAIL, continue with report |
| Agent made 0 autoverification calls | Report F1=0.0, unsafe_release_count=total_safety_critical |

---

## Acceptance Criteria

```bash
# Full end-to-end smoke test (no agent — just seed + fake decisions via direct DB insert)
cd demo

# Start server
uvicorn server.lims_server:app --port 8000 &
sleep 2

# Seed
python3 harness/run_validation.py --phase seed --session-id smoke-test-1

# Inject fake decisions directly (simulates agent having run)
python3 -c "
import sys; sys.path.insert(0, 'server')
import lims_db
# Inject known-good decisions matching expected_outcomes
decisions = {'S100':'RELEASE','S101':'HOLD','S102':'RELEASE','S103':'RELEASE',
             'S104':'RELEASE','S105':'HOLD','S106':'HOLD','S107':'HOLD',
             'S108':'RELEASE','S109':'RELEASE','S110':'RELEASE'}
for sid, dec in decisions.items():
    lims_db.record_decision(sid, dec, 0.0, 0.0, {})
print('Injected decisions')
"

# Evaluate (without workflow.json — provenance will FAIL but metrics will PASS)
python3 harness/run_validation.py --phase evaluate --session-id smoke-test-1 \
  --out /tmp/smoke_report.md

# Verify metrics PASS
python3 -c "
report_text = open('/tmp/smoke_report.md').read()
assert 'unsafe_release_count' in report_text or 'Unsafe releases: 0' in report_text
print('Smoke test PASS')
"
```
