"""
SQLite LIMS database — single file that owns all DB state.
No ORM. Plain sqlite3 stdlib. All other components import from here.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

DB_PATH = "lims.db"

ALLOWED_TRANSITIONS = {
    "created": "analyzed",
    "analyzed": "pending_review",
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Call once at server startup."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS specimens (
                specimen_id          TEXT PRIMARY KEY,
                patient_id           TEXT NOT NULL,
                values_json          TEXT NOT NULL,
                patient_prior_json   TEXT NOT NULL,
                status               TEXT DEFAULT 'created',
                snapshot_hash        TEXT NOT NULL,
                created_at           TEXT NOT NULL,
                decision             TEXT,
                contamination_score  REAL,
                swap_score           REAL,
                workflow_params_json TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                tool        TEXT NOT NULL,
                args_json   TEXT NOT NULL,
                result_json TEXT NOT NULL,
                timestamp   TEXT NOT NULL
            )
        """)
        conn.commit()


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
    values_json = json.dumps(values, sort_keys=True)
    snapshot_hash = hashlib.sha256(values_json.encode()).hexdigest()
    created_at = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        existing = conn.execute(
            "SELECT specimen_id FROM specimens WHERE specimen_id = ?", (specimen_id,)
        ).fetchone()
        if existing:
            raise ValueError(f"Specimen {specimen_id!r} already exists")

        conn.execute(
            """
            INSERT INTO specimens
                (specimen_id, patient_id, values_json, patient_prior_json,
                 status, snapshot_hash, created_at)
            VALUES (?, ?, ?, ?, 'created', ?, ?)
            """,
            (
                specimen_id,
                patient_id,
                values_json,
                json.dumps(patient_prior),
                snapshot_hash,
                created_at,
            ),
        )
        conn.commit()

    return {
        "specimen_id": specimen_id,
        "status": "created",
        "snapshot_hash": snapshot_hash,
        "created_at": created_at,
    }


def get_specimen(specimen_id: str) -> dict | None:
    """Return full specimen row as dict. None if not found."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM specimens WHERE specimen_id = ?", (specimen_id,)
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def update_specimen_status(specimen_id: str, new_status: str) -> dict:
    """
    Allowed transitions: created→analyzed, analyzed→pending_review.
    Raise ValueError on invalid transition or unknown specimen_id.
    Returns: {"specimen_id", "previous_status", "new_status"}
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT status FROM specimens WHERE specimen_id = ?", (specimen_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown specimen_id: {specimen_id!r}")

        current_status = row["status"]
        allowed_next = ALLOWED_TRANSITIONS.get(current_status)
        if allowed_next != new_status:
            raise ValueError(
                f"Illegal status transition for {specimen_id!r}: "
                f"{current_status!r} → {new_status!r}. "
                f"Allowed: {current_status!r} → {allowed_next!r}"
            )

        conn.execute(
            "UPDATE specimens SET status = ? WHERE specimen_id = ?",
            (new_status, specimen_id),
        )
        conn.commit()

    return {
        "specimen_id": specimen_id,
        "previous_status": current_status,
        "new_status": new_status,
    }


def record_decision(
    specimen_id: str,
    decision: str,
    contamination_score: float,
    swap_score: float,
    workflow_params: dict,
) -> None:
    """Write decision fields only. Does not touch values_json or patient_prior_json."""
    with _connect() as conn:
        conn.execute(
            """
            UPDATE specimens
            SET decision = ?, contamination_score = ?, swap_score = ?,
                workflow_params_json = ?
            WHERE specimen_id = ?
            """,
            (
                decision,
                contamination_score,
                swap_score,
                json.dumps(workflow_params),
                specimen_id,
            ),
        )
        conn.commit()


def log_tool_call(
    session_id: str,
    tool: str,
    args: dict,
    result: dict,
) -> None:
    """Append one row to audit_log with current UTC timestamp."""
    timestamp = datetime.now(timezone.utc).isoformat() + "Z"
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (session_id, tool, args_json, result_json, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, tool, json.dumps(args), json.dumps(result), timestamp),
        )
        conn.commit()


def get_audit_log(session_id: str, specimen_id: str | None = None) -> list[dict]:
    """
    Return ordered list of audit log rows for session_id (ordered by id ASC).
    If specimen_id given, filter to rows where args_json contains that specimen_id.
    Each row: {"id", "tool", "args", "result", "timestamp"}
    """
    with _connect() as conn:
        if specimen_id is not None:
            rows = conn.execute(
                """
                SELECT id, tool, args_json, result_json, timestamp
                FROM audit_log
                WHERE session_id = ? AND args_json LIKE ?
                ORDER BY id ASC
                """,
                (session_id, f"%{specimen_id}%"),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, tool, args_json, result_json, timestamp
                FROM audit_log
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()

    return [
        {
            "id": row["id"],
            "tool": row["tool"],
            "args": json.loads(row["args_json"]),
            "result": json.loads(row["result_json"]),
            "timestamp": row["timestamp"],
        }
        for row in rows
    ]


def query_knowledge_was_called(session_id: str) -> bool:
    """Return True if audit_log contains a query_knowledge call for this session."""
    with _connect() as conn:
        count = conn.execute(
            """
            SELECT COUNT(*) FROM audit_log
            WHERE session_id = ? AND tool = 'query_knowledge'
            """,
            (session_id,),
        ).fetchone()[0]
    return count > 0


def get_all_decisions() -> list[dict]:
    """Return [{specimen_id, decision, contamination_score, swap_score}] for all specimens."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT specimen_id, decision, contamination_score, swap_score FROM specimens"
        ).fetchall()
    return [dict(row) for row in rows]
