#!/usr/bin/env python3
"""
LIS Reportable Range Triage Engine

Applies a three-tier limit-check policy to laboratory results:

  Tier 1 — AMR (Analytical Measurement Range): instrument-verified per CLIA §493.1253(b)(1).
            Outside AMR → HOLD (amr_exceeded). Result is not analytically valid.
            High-end AMR overshoot may trigger dilution reflex annotation.

  Tier 2 — Manual Review Limits: 2nd–98th percentile of the laboratory's patient population.
            Outside manual review → HOLD (manual_review_exceeded). Pathologist review required.

  Tier 3 — Reference Interval: 2.5th–97.5th percentile of the healthy reference population.
            Outside reference interval → RELEASE with flag annotation (reference_exceeded).
            This tier does NOT trigger a HOLD.

  Otherwise → RELEASE (no flag).

Evaluation order is mandatory: Tier 1 first, then Tier 2, then Tier 3. Stop at first match.

Input:
  workflow.json   — agent-configured three-tier bounds per analyte + dilution_reflex section
  results_batch.json — specimen results: {specimen_id, analyte, value, unit}

Output:
  decisions.json  — per-specimen HOLD/RELEASE with hold_reason, flag, dilution_reflex_ordered
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

Json = Dict[str, Any]

# ---------------------------------------------------------------------------
# Invocation self-monitoring
# ---------------------------------------------------------------------------

RUN_LOG_PATH = Path("/tmp/range_runs.json")
MAX_RUNS = 5


def _load_run_log() -> List[Json]:
    if RUN_LOG_PATH.exists():
        try:
            return json.loads(RUN_LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _extract_numeric_params(wf: Json) -> Dict[str, float]:
    flat: Dict[str, float] = {}

    def _walk(obj: Any, pfx: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                _walk(v, f"{pfx}.{k}" if pfx else k)
        elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
            flat[pfx] = float(obj)

    _walk(wf, "")
    return flat


def _record_run(decisions: List[Json], run_log: List[Json], wf: Json) -> None:
    current = {d["specimen_id"]: d["action"] for d in decisions}
    hold_count    = sum(1 for a in current.values() if a == "HOLD")
    release_count = sum(1 for a in current.values() if a == "RELEASE")
    n = len(current)

    probs = [hold_count / n, release_count / n] if n > 0 else [0.5, 0.5]
    entropy = -sum(p * math.log2(p) for p in probs if p > 0)

    entry: Json = {
        "run_index":        len(run_log),
        "hold_count":       hold_count,
        "release_count":    release_count,
        "decision_entropy": round(entropy, 4),
        "decisions":        current,
    }

    if run_log:
        prev = run_log[-1]["decisions"]
        delta = sum(1 for sid, action in current.items() if action != prev.get(sid))
        entry["delta_from_prev"]     = delta
        entry["log_delta_from_prev"] = math.log(delta + 1)

        prev_params = run_log[-1].get("workflow_params", {})
        curr_params = _extract_numeric_params(wf)
        common = set(prev_params) & set(curr_params)
        if common:
            sq = sum((curr_params[k] - prev_params[k]) ** 2 for k in common)
            entry["param_velocity"] = round(math.sqrt(sq), 6)

    entry["workflow_params"] = _extract_numeric_params(wf)
    run_log.append(entry)
    RUN_LOG_PATH.write_text(json.dumps(run_log, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tier evaluation
# ---------------------------------------------------------------------------

def evaluate_specimen(
    specimen_id: str,
    analyte: str,
    value: float,
    unit: str,
    wf: Json,
) -> Json:
    analyte_cfg = wf.get("analytes", {}).get(analyte, {})
    dilution_cfg = wf.get("dilution_reflex", {})

    amr_lower = analyte_cfg.get("amr_lower")
    amr_upper = analyte_cfg.get("amr_upper")
    mr_lower  = analyte_cfg.get("manual_review_lower")
    mr_upper  = analyte_cfg.get("manual_review_upper")
    ref_lower = analyte_cfg.get("reference_lower")
    ref_upper = analyte_cfg.get("reference_upper")

    # Tier 1: AMR check
    amr_violated = False
    amr_high = False
    if amr_lower is not None and value < amr_lower:
        amr_violated = True
    if amr_upper is not None and value > amr_upper:
        amr_violated = True
        amr_high = True

    if amr_violated:
        dilution_ordered = False
        if (amr_high
                and dilution_cfg.get("enabled", False)
                and dilution_cfg.get("trigger") == "amr_exceeded_high"
                and analyte in dilution_cfg.get("amr_overshoot_analytes", [])):
            dilution_ordered = True
        return {
            "specimen_id": specimen_id,
            "analyte": analyte,
            "value": value,
            "unit": unit,
            "action": "HOLD",
            "hold_reason": "amr_exceeded",
            "flag": None,
            "dilution_reflex_ordered": dilution_ordered,
        }

    # Tier 2: Manual review check
    mr_violated = False
    if mr_lower is not None and value < mr_lower:
        mr_violated = True
    if mr_upper is not None and value > mr_upper:
        mr_violated = True

    if mr_violated:
        return {
            "specimen_id": specimen_id,
            "analyte": analyte,
            "value": value,
            "unit": unit,
            "action": "HOLD",
            "hold_reason": "manual_review_exceeded",
            "flag": None,
            "dilution_reflex_ordered": False,
        }

    # Tier 3: Reference interval (flag only — no HOLD)
    ref_exceeded = False
    if ref_lower is not None and value < ref_lower:
        ref_exceeded = True
    if ref_upper is not None and value > ref_upper:
        ref_exceeded = True

    return {
        "specimen_id": specimen_id,
        "analyte": analyte,
        "value": value,
        "unit": unit,
        "action": "RELEASE",
        "hold_reason": None,
        "flag": "reference_exceeded" if ref_exceeded else None,
        "dilution_reflex_ordered": False,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Reportable Range Triage Engine")
    ap.add_argument("--workflow", type=Path, default=Path("/app/workflow.json"))
    ap.add_argument("--batch",   type=Path, required=True)
    ap.add_argument("--out",     type=Path, default=Path("/app/decisions.json"))
    args = ap.parse_args()

    # Invocation guard
    run_log = _load_run_log()
    if len(run_log) >= MAX_RUNS:
        sys.stderr.write(
            f"triage: invocation limit ({MAX_RUNS}) reached.\n"
            f"Derive all limit values from /app/amr_knowledge.json — "
            f"do not iterate numerically toward a passing score.\n"
        )
        sys.exit(1)

    wf    = json.loads(args.workflow.read_text(encoding="utf-8"))
    batch = json.loads(args.batch.read_text(encoding="utf-8"))

    specimens: List[Json] = batch.get("specimens", [])
    decisions: List[Json] = []

    for spec in specimens:
        specimen_id = spec["specimen_id"]
        analyte     = spec["analyte"]
        value       = float(spec["value"])
        unit        = spec.get("unit", "")

        decision = evaluate_specimen(specimen_id, analyte, value, unit, wf)
        decisions.append(decision)

    _record_run(decisions, run_log, wf)

    output = {
        "batch_id":  batch.get("batch_id"),
        "decisions": decisions,
    }
    args.out.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
