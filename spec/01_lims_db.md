# Task 01 — SQLite LIMS Database
**Output file:** `demo/server/lims_db.py`  
**Depends on:** nothing  
**Global constraints:** see `IMPL_SPEC.md`

---

## Purpose
Single-file SQLite wrapper for all LIMS state. No ORM. Plain sqlite3 stdlib.
All other components import from this module — it is the only place that touches the DB.

---

## Schema

```sql
CREATE TABLE IF NOT EXISTS specimens (
  specimen_id       TEXT PRIMARY KEY,
  patient_id        TEXT NOT NULL,
  values_json       TEXT NOT NULL,         -- JSON: {"K": 4.1, "Ca": 9.4, ...} WRITE-ONCE
  patient_prior_json TEXT NOT NULL,        -- JSON: {"mean": {...}, "sd": {...}} WRITE-ONCE
  status            TEXT DEFAULT 'created', -- created | analyzed | pending_review
  snapshot_hash     TEXT NOT NULL,         -- SHA256 of values_json (sorted keys)
  created_at        TEXT NOT NULL,         -- ISO8601 UTC
  decision          TEXT,                  -- HOLD | RELEASE (set by apply_autoverification)
  contamination_score REAL,
  swap_score        REAL,
  workflow_params_json TEXT               -- JSON: params used in autoverification run
);

CREATE TABLE IF NOT EXISTS audit_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT NOT NULL,
  tool        TEXT NOT NULL,
  args_json   TEXT NOT NULL,
  result_json TEXT NOT NULL,
  timestamp   TEXT NOT NULL               -- ISO8601 UTC
);
```

---

## Interface (functions to implement)

```python
DB_PATH = "lims.db"

def init_db() -> None:
    """Create tables if they don't exist. Call once at server startup."""

def create_specimen(
    specimen_id: str,
    patient_id: str,
    values: dict,
    patient_prior: dict,
) -> dict:
    """
    Insert specimen. Compute snapshot_hash = SHA256(json.dumps(values, sort_keys=True)).
    Raise ValueError if specimen_id already exists.
    Returns: {"specimen_id", "status", "snapshot_hash", "created_at"}
    """

def get_specimen(specimen_id: str) -> dict | None:
    """Return full specimen row as dict. None if not found."""

def update_specimen_status(specimen_id: str, new_status: str) -> dict:
    """
    Allowed transitions: created→analyzed, analyzed→pending_review.
    Raise ValueError on invalid transition or unknown specimen_id.
    Returns: {"specimen_id", "previous_status", "new_status"}
    """

def record_decision(
    specimen_id: str,
    decision: str,
    contamination_score: float,
    swap_score: float,
    workflow_params: dict,
) -> None:
    """Write decision fields. Does not change status."""

def log_tool_call(
    session_id: str,
    tool: str,
    args: dict,
    result: dict,
) -> None:
    """Append one row to audit_log with current UTC timestamp."""

def get_audit_log(session_id: str, specimen_id: str | None = None) -> list[dict]:
    """
    Return ordered list of audit log rows for session_id.
    If specimen_id given, filter to rows where args_json contains that specimen_id.
    Each row: {"id", "tool", "args", "result", "timestamp"}
    """

def query_knowledge_was_called(session_id: str) -> bool:
    """Return True if audit_log contains a query_knowledge call for this session."""

def get_all_decisions() -> list[dict]:
    """Return [{specimen_id, decision, contamination_score, swap_score}] for all specimens."""
```

---

## Acceptance Criteria

Run this to verify:
```bash
cd demo/server
python3 -c "
import lims_db, json
lims_db.init_db()
r = lims_db.create_specimen('S001', 'P001', {'K': 4.1, 'Ca': 9.4}, {'mean': {'K': 4.0}, 'sd': {'K': 0.3}})
print('created:', r)
lims_db.update_specimen_status('S001', 'analyzed')
lims_db.log_tool_call('sess1', 'query_knowledge', {'map_id': 'test'}, {'ok': True})
print('kg_called:', lims_db.query_knowledge_was_called('sess1'))
print('PASS')
"
```
Expected: no exceptions, `kg_called: True`.
