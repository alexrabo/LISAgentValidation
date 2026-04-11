#!/usr/bin/env python3
"""
LIS Westgard QC Triage Engine

Evaluates a sequence of QC events against a multi-rule Shewhart procedure
(Westgard JO, Clin Chem 1981;27:493-501) configured via workflow.json.

Key design:
- QC runs are evaluated in temporal order — rules 4_1s and 10x are stateful
- The 1_2s warning rule is the fast-exit gate: if all controls within ±2s,
  ACCEPT immediately without applying remaining rules
- R_4s applies only within a single QC event (not across events)
- 2_2s applies within a single level across two consecutive events,
  OR across Level 1 and Level 2 within the same QC event (multi-level)
- Multi-level synthesis (2_2s across levels in same QC event) requires
  multi_level_policy.enabled = true and direction_required = true in workflow.json
- Actions: ACCEPT | WARNING | REJECT
  WARNING = 1_2s triggered but no rejection rule fired (hold patient results,
  investigate further)

Input:
  workflow.json  — agent-configured rule thresholds and multi-level policy
  qc_batch.json  — ordered QC events: {event_id, timestamp, measurements[]}

Output:
  decisions.json — per-event action, triggered_rules, error_type
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

Json = Dict[str, Any]

# ---------------------------------------------------------------------------
# Invocation self-monitoring
# ---------------------------------------------------------------------------

RUN_LOG_PATH = Path("/tmp/qc_runs.json")
MAX_RUNS = 5


def _load_run_log() -> List[Json]:
    if RUN_LOG_PATH.exists():
        try:
            return json.loads(RUN_LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _extract_numeric_params(wf: Json, prefix: str = "") -> Dict[str, float]:
    """Flatten workflow.json into dot-notation numeric key→value dict."""
    flat: Dict[str, float] = {}

    def _walk(obj: Any, pfx: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                _walk(v, f"{pfx}.{k}" if pfx else k)
        elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
            flat[pfx] = float(obj)

    _walk(wf, prefix)
    return flat


def _record_run(decisions: List[Json], run_log: List[Json], wf: Json) -> None:
    """Append convergence snapshot to run log."""
    current = {d["event_id"]: d["action"] for d in decisions}
    reject_count = sum(1 for a in current.values() if a == "REJECT")
    warn_count   = sum(1 for a in current.values() if a == "WARNING")
    accept_count = sum(1 for a in current.values() if a == "ACCEPT")
    n = len(current)

    # Shannon entropy over three outcomes
    probs = [reject_count / n, warn_count / n, accept_count / n] if n > 0 else [0, 0, 0]
    entropy = -sum(p * math.log2(p) for p in probs if p > 0)

    entry: Json = {
        "run_index":       len(run_log),
        "reject_count":    reject_count,
        "warn_count":      warn_count,
        "accept_count":    accept_count,
        "decision_entropy": round(entropy, 4),
        "decisions":       current,
    }

    if run_log:
        prev = run_log[-1]["decisions"]
        delta = sum(1 for eid, action in current.items() if action != prev.get(eid))
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
# Z-score helpers
# ---------------------------------------------------------------------------

def z_score(value: float, mean: float, sd: float) -> float:
    """Signed z-score: (value - mean) / sd. Returns 0 if sd <= 0."""
    return (value - mean) / sd if sd > 0 else 0.0


def same_direction(zscores: List[float], threshold: float) -> Optional[str]:
    """Return 'above' or 'below' if all z-scores exceed threshold in same direction, else None."""
    if all(z > threshold for z in zscores):
        return "above"
    if all(z < -threshold for z in zscores):
        return "below"
    return None


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------

def apply_rules(
    event_id: str,
    event_z: Dict[Tuple[str, int], float],       # (analyte, level) -> z for THIS event
    history:  Dict[Tuple[str, int], List[float]], # (analyte, level) -> all z-scores so far (incl. current)
    wf: Json,
) -> Tuple[str, List[str], Optional[str], str]:
    """
    Evaluate all Westgard rules for one QC event.

    Returns: (action, triggered_rules, error_type, confidence)
      action        — 'ACCEPT' | 'WARNING' | 'REJECT'
      triggered_rules — list of rule notation strings
      error_type    — 'random' | 'systematic' | None
      confidence    — 'high' | 'standard' | ''
    """
    rules = wf.get("rules", {})
    ml    = wf.get("multi_level_policy", {})

    warn_thr  = float(rules.get("warning_threshold_sd",      2.0))
    thr_1_3s  = float(rules.get("rejection_1_3s_threshold_sd", 3.0))
    thr_2_2s  = float(rules.get("rejection_2_2s_threshold_sd", 2.0))
    thr_R_4s  = float(rules.get("rejection_R_4s_range_sd",    4.0))
    n_4_1s    = int(  rules.get("rejection_4_1s_consecutive",  4))
    thr_4_1s  = float(rules.get("rejection_4_1s_threshold_sd", 1.0))
    n_10x     = int(  rules.get("rejection_10x_consecutive",   10))
    ml_enabled = bool(ml.get("enabled", False))
    ml_dir_req = bool(ml.get("direction_required", True))

    triggered: List[str] = []
    error_types: List[str] = []
    confidence = "standard"

    # ── 1₂s WARNING GATE ────────────────────────────────────────────────────
    # Fast exit: if ALL controls within ±warn_thr → ACCEPT immediately
    any_exceeds_warning = any(abs(z) > warn_thr for z in event_z.values())
    if not any_exceeds_warning:
        return "ACCEPT", [], None, ""

    # 1₂s triggered — inspect further with rejection rules
    # (WARNING is the fallback if no rejection rule fires below)

    analytes = set(a for (a, _) in event_z.keys())

    # ── 1₃s ─────────────────────────────────────────────────────────────────
    # Reject if any single observation exceeds ±3s
    for (analyte, level), z in event_z.items():
        if abs(z) > thr_1_3s:
            triggered.append("1_3s")
            error_types.append("random")
            break

    # ── R₄s ─────────────────────────────────────────────────────────────────
    # Reject if range between Level 1 and Level 2 WITHIN THIS EVENT exceeds 4s
    # (one above +2s, other below -2s — opposite directions)
    # R_4s is NOT applied across consecutive events (Westgard 1981 p. 500)
    for analyte in analytes:
        level_keys = [(analyte, lv) for (a, lv) in event_z.keys() if a == analyte]
        if len(level_keys) < 2:
            continue
        zvals = [event_z[k] for k in level_keys]
        max_z = max(zvals)
        min_z = min(zvals)
        # Opposite directions, total span > thr_R_4s, each out by >= thr_2_2s
        if (max_z > thr_2_2s and min_z < -thr_2_2s and
                (max_z - min_z) > thr_R_4s):
            triggered.append("R_4s")
            error_types.append("random")
            break

    # ── 2₂s within level (consecutive events, same analyte+level) ───────────
    # Both current and previous event z-scores exceed same ±2s limit
    for (analyte, level), hist in history.items():
        if len(hist) < 2:
            continue
        curr_z = hist[-1]
        prev_z = hist[-2]
        if ((curr_z > thr_2_2s and prev_z > thr_2_2s) or
                (curr_z < -thr_2_2s and prev_z < -thr_2_2s)):
            triggered.append("2_2s_within_level")
            error_types.append("systematic")
            break

    # ── 2₂s across levels (multi-level synthesis — same QC event) ───────────
    # Both Level 1 and Level 2 for the same analyte in THIS event exceed ±2s
    # in the same direction. Requires multi_level_policy.enabled = true.
    # Source: CLSI C24-Ed4 Section 5.5.1 "across QC concentrations"
    if ml_enabled:
        for analyte in analytes:
            level_keys = [(analyte, lv) for (a, lv) in event_z.keys() if a == analyte]
            if len(level_keys) < 2:
                continue
            zvals = [event_z[k] for k in level_keys]
            all_above = all(z > thr_2_2s for z in zvals)
            all_below = all(z < -thr_2_2s for z in zvals)
            if not ml_dir_req:
                fires = any(abs(z) > thr_2_2s for z in zvals)
            else:
                fires = all_above or all_below
            if fires:
                triggered.append("2_2s_cross_level")
                error_types.append("systematic_multilevel")
                confidence = "high"
                break

    # ── 4₁s within level ────────────────────────────────────────────────────
    # Last n_4_1s consecutive z-scores for same analyte+level all exceed ±1s
    for (analyte, level), hist in history.items():
        if len(hist) < n_4_1s:
            continue
        last_n = hist[-n_4_1s:]
        if same_direction(last_n, thr_4_1s) is not None:
            triggered.append("4_1s_within_level")
            error_types.append("systematic")
            break

    # ── 4₁s across levels ───────────────────────────────────────────────────
    # Last 2 events × 2 levels = 4 observations, all exceeding ±1s same direction
    # Requires exactly 2 levels and at least 2 events of history
    for analyte in analytes:
        level_keys = [(analyte, lv) for (a, lv) in event_z.keys() if a == analyte]
        if len(level_keys) < 2:
            continue
        # Build interleaved sequence: prev_L1, prev_L2, curr_L1, curr_L2
        cross_z = []
        for key in level_keys:
            hist = history.get(key, [])
            if len(hist) >= 2:
                cross_z.extend([hist[-2], hist[-1]])
        if len(cross_z) == n_4_1s and same_direction(cross_z, thr_4_1s) is not None:
            if "4_1s_within_level" not in triggered:
                triggered.append("4_1s_cross_level")
                error_types.append("systematic")
            break

    # ── 10× within level ────────────────────────────────────────────────────
    # Last n_10x consecutive z-scores for same analyte+level all same side of mean
    for (analyte, level), hist in history.items():
        if len(hist) < n_10x:
            continue
        last_n = hist[-n_10x:]
        if same_direction(last_n, threshold=0.0) is not None:
            triggered.append("10x_within_level")
            error_types.append("systematic")
            break

    # ── 10× across levels ───────────────────────────────────────────────────
    # n_10x / 2 events × 2 levels — all same side of mean
    half = n_10x // 2
    for analyte in analytes:
        level_keys = [(analyte, lv) for (a, lv) in event_z.keys() if a == analyte]
        if len(level_keys) < 2:
            continue
        cross_z = []
        for key in level_keys:
            hist = history.get(key, [])
            if len(hist) >= half:
                cross_z.extend(hist[-half:])
        if len(cross_z) == n_10x and same_direction(cross_z, threshold=0.0) is not None:
            if "10x_within_level" not in triggered:
                triggered.append("10x_cross_level")
                error_types.append("systematic")
            break

    # ── Determine action and primary error type ──────────────────────────────
    if triggered:
        action = "REJECT"
        if "systematic_multilevel" in error_types:
            primary_error = "systematic"
        elif "systematic" in error_types:
            primary_error = "systematic"
            confidence = "standard"
        else:
            primary_error = "random"
            confidence = "standard"
    else:
        # 1₂s fired but no rejection rule — WARNING
        action = "WARNING"
        primary_error = None
        confidence = ""

    # Deduplicate triggered list preserving order
    seen: set = set()
    deduped = []
    for r in triggered:
        if r not in seen:
            seen.add(r)
            deduped.append(r)

    return action, deduped, primary_error, confidence


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Westgard QC Triage Engine")
    ap.add_argument("--workflow", type=Path, default=Path("/app/workflow.json"))
    ap.add_argument("--batch",    type=Path, required=True)
    ap.add_argument("--out",      type=Path, default=Path("/app/decisions.json"))
    args = ap.parse_args()

    # ── Invocation guard ────────────────────────────────────────────────────
    run_log = _load_run_log()
    if len(run_log) >= MAX_RUNS:
        sys.stderr.write(
            f"triage: invocation limit ({MAX_RUNS}) reached.\n"
            f"Derive all threshold values from /app/westgard_rules_knowledge.json — "
            f"do not iterate numerically toward a passing score.\n"
        )
        sys.exit(1)

    wf    = json.loads(args.workflow.read_text(encoding="utf-8"))
    batch = json.loads(args.batch.read_text(encoding="utf-8"))

    qc_events: List[Json] = batch.get("qc_events", [])

    # history[(analyte, level)] → ordered list of z-scores across all events
    history: Dict[Tuple[str, int], List[float]] = defaultdict(list)

    decisions: List[Json] = []

    for event in qc_events:
        event_id = event["event_id"]
        measurements: List[Json] = event.get("measurements", [])

        # Build z-scores for this event
        event_z: Dict[Tuple[str, int], float] = {}
        for m in measurements:
            analyte = m["analyte"]
            level   = int(m["level"])
            z = z_score(float(m["value"]), float(m["mean"]), float(m["sd"]))
            event_z[(analyte, level)] = z
            history[(analyte, level)].append(z)

        if not event_z:
            decisions.append({
                "event_id":       event_id,
                "action":         "ACCEPT",
                "triggered_rules": [],
                "error_type":     None,
                "confidence":     "",
                "note":           "no measurements in event"
            })
            continue

        action, triggered, error_type, confidence = apply_rules(
            event_id, event_z, history, wf
        )

        # Build z-score detail for transparency
        z_detail = {
            f"{analyte}_L{level}": round(z, 3)
            for (analyte, level), z in sorted(event_z.items())
        }

        decisions.append({
            "event_id":        event_id,
            "action":          action,
            "triggered_rules": triggered,
            "error_type":      error_type,
            "confidence":      confidence,
            "z_scores":        z_detail,
        })

    _record_run(decisions, run_log, wf)

    output = {
        "batch_id":  batch.get("batch_id"),
        "decisions": decisions,
    }
    args.out.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
