"""
ApplyAutoverificationHandler.

Orchestrates: compliance guard → full-batch triage (cached) → record → event.
Session decision cache ensures run_triage() sees all specimens (pairwise swap
scoring requires full batch — partial batch gives incorrect swap scores).
"""
import asyncio
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

if str(Path(__file__).parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from circuit_breaker import CircuitBreaker, CircuitOpenError
from events.store import EventStore
from events.types import AutoverificationAppliedEvent
from services import ComplianceService, LimsService

from lis_triage_engine import run_triage


def _build_batch(specimens: list[dict]) -> dict:
    """
    Map DB rows → triage.py batch format.
    run_triage() expects:
      {
        "patients":  [{"patient_id": str, "prior": {"mean": {...}, "sd": {...}}}],
        "specimens": [{"specimen_id": str, "patient_id": str, "values": {...}}]
      }
    """
    seen: set = set()
    patients_out: list = []
    specimens_out: list = []

    for row in specimens:
        values = json.loads(row["values_json"])
        prior = json.loads(row["patient_prior_json"])
        specimens_out.append({
            "specimen_id": row["specimen_id"],
            "patient_id": row["patient_id"],
            "values": values,
        })
        if row["patient_id"] not in seen:
            seen.add(row["patient_id"])
            if prior:
                patients_out.append({"patient_id": row["patient_id"], "prior": prior})

    return {"specimens": specimens_out, "patients": patients_out}


def _build_workflow(wp: dict) -> dict:
    """
    Expand workflow_params → full triage.py workflow dict.
    Maps lab-facing field names to triage.py's internal keys:
      delta_check_sd_threshold → zscore_threshold  (CLSI EP33 Section 4.3 Table 2)
    """
    c_thresh = wp.get("contamination_hold_threshold", 0.5)
    s_thresh = wp.get("swap_hold_threshold", 0.3)
    z_thresh = wp.get("delta_check_sd_threshold", 3.0)  # lab name → internal key

    return {
        "zscore_threshold": z_thresh,
        "max_holds": 99,
        "contamination_signatures": [{
            "name": "EDTA",
            "mode": "prior_relative",
            "rule": {
                "K_delta_min": z_thresh,
                "Ca_delta_max": -2.5,
                "fallback_K_min": 6.5,
                "fallback_Ca_max": 7.2,
                "fallback_K_range": 1.0,
                "fallback_Ca_range": 0.5,
            },
            "analytes": ["K", "Ca"],
        }],
        "decision_policy": {
            "contamination_hold_threshold": c_thresh,
            "swap_hold_threshold": s_thresh,
        },
        "swap_detection": {
            "enabled": True,
            "pairwise": True,
            "analyte_weights": {
                "K": 1.0, "Ca": 1.0, "Na": 1.0,
                "Cl": 1.0, "HCO3": 1.0, "Glucose": 3.0,
            },
        },
        "analyte_weights": {
            "K": 1.0, "Ca": 1.0, "Na": 1.0,
            "Cl": 1.0, "HCO3": 1.0, "Glucose": 3.0,
        },
    }


class ApplyAutoverificationHandler:
    def __init__(
        self,
        service: LimsService,
        compliance: ComplianceService,
        events: EventStore,
        circuit: CircuitBreaker,
        executor: ProcessPoolExecutor,
    ):
        self._service = service
        self._compliance = compliance
        self._events = events
        self._circuit = circuit
        self._executor = executor
        # Session-scoped cache: {session_id: {specimen_id: decision_dict}}
        # Populated once per session on first apply_autoverification call.
        self._cache: dict[str, dict] = {}

    async def handle(self, payload: dict, session_id: str) -> dict:
        specimen_id = payload["specimen_id"]
        workflow_params = payload["workflow_params"]

        # ── Compliance guard ──────────────────────────────────────────────────
        # Do NOT emit event on block — audit must not record a failed attempt
        if not self._compliance.knowledge_was_queried(session_id):
            return {
                "error": "query_knowledge must be called before apply_autoverification",
                "code": "PROVENANCE_GUARD",
            }

        # ── Full-batch triage (cached per session) ────────────────────────────
        if session_id not in self._cache:
            all_specimens = self._service.get_all_specimens()
            batch = _build_batch(all_specimens)
            workflow = _build_workflow(workflow_params)

            loop = asyncio.get_event_loop()
            try:
                all_decisions = await self._circuit.call(
                    loop.run_in_executor(self._executor, run_triage, batch, workflow)
                )
            except CircuitOpenError as exc:
                return {"error": str(exc), "code": "TRIAGE_UNAVAILABLE"}

            self._cache[session_id] = all_decisions

        decision = self._cache[session_id].get(specimen_id)
        if decision is None:
            return {"error": f"Specimen {specimen_id!r} not found in triage results"}

        # ── Persist + audit ───────────────────────────────────────────────────
        self._service.record_decision(
            specimen_id,
            decision["decision"],
            decision["contamination_score"],
            decision["swap_score"],
            workflow_params,
        )
        self._events.append(AutoverificationAppliedEvent(
            aggregate_id=specimen_id,
            session_id=session_id,
            payload={
                "decision": decision["decision"],
                "contamination_score": decision["contamination_score"],
                "swap_score": decision["swap_score"],
            },
        ))
        return decision
