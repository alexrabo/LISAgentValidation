"""
Service layer — the only code that touches lims_db directly.
Handlers never import lims_db. They call services.

Four services, four domains:
  LimsService        — specimen lifecycle (create, advance, record, query)
  KnowledgeService   — clinical knowledge graph (load, serve)
  ComplianceService  — provenance guard (was query_knowledge called first?)
  AuditService       — audit trail reads (what did the agent do?)
"""
import sys
from pathlib import Path

_server_root = str(Path(__file__).parent)
if _server_root not in sys.path:
    sys.path.insert(0, _server_root)

import lims_db
from settings import load_knowledge_graph


# ── LimsService ───────────────────────────────────────────────────────────────

class LimsService:
    """Specimen lifecycle. All SQLite specimen operations go through here."""

    def __init__(self, db):
        self._db = db

    def create_specimen(
        self,
        specimen_id: str,
        patient_id: str,
        values: dict,
        patient_prior: dict,
    ) -> dict:
        return self._db.create_specimen(specimen_id, patient_id, values, patient_prior)

    def advance_status(self, specimen_id: str, to_status: str) -> dict:
        return self._db.update_specimen_status(specimen_id, to_status)

    def record_decision(
        self,
        specimen_id: str,
        decision: str,
        contamination_score: float,
        swap_score: float,
        workflow_params: dict,
    ) -> None:
        self._db.record_decision(
            specimen_id, decision, contamination_score, swap_score, workflow_params
        )

    def get_all_specimens(self) -> list[dict]:
        """Return all specimen rows for full-batch triage call."""
        import sqlite3
        conn = sqlite3.connect(self._db.DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM specimens").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_specimen(self, specimen_id: str) -> dict | None:
        return self._db.get_specimen(specimen_id)


# ── KnowledgeService ──────────────────────────────────────────────────────────

class KnowledgeService:
    """Clinical knowledge graph. Abstracts env var loading from handlers."""

    def get_knowledge_map(self) -> dict:
        """Load KG from KG_JSON_B64 env var or KG_PATH file."""
        return load_knowledge_graph()


# ── ComplianceService ─────────────────────────────────────────────────────────

class ComplianceService:
    """
    Provenance guard. Answers: did the agent follow the required call order?
    query_knowledge MUST appear in the audit log before apply_autoverification.
    Future: check_workflow_order(), validate_session_integrity(), ...
    """

    def __init__(self, db):
        self._db = db

    def knowledge_was_queried(self, session_id: str) -> bool:
        return self._db.query_knowledge_was_called(session_id)


# ── AuditService ──────────────────────────────────────────────────────────────

class AuditService:
    """
    Audit trail reads. Answers: what did the agent do, in what order?
    Future: export_audit_trail(), generate_cap_report(), ...
    """

    def __init__(self, db):
        self._db = db

    def get_log(self, session_id: str, specimen_id: str | None = None) -> list[dict]:
        return self._db.get_audit_log(session_id, specimen_id)
