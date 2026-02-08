#!/usr/bin/env python3
"""
LIS Triage System - Scored Decision Logic

This system uses NUMERIC SCORES with THRESHOLDS for HOLD decisions.
Simply detecting a signal is NOT sufficient - the signal must be strong enough.

Key parameters in workflow.json:
- contamination_hold_threshold: minimum contamination_score to trigger HOLD
- swap_hold_threshold: minimum swap improvement score to trigger HOLD

If scores are below thresholds, the specimen is RELEASED even if weak signals exist.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

Json = Dict[str, Any]


def zscore(x: float, mean: float, sd: float) -> float:
    """Calculate z-score for a value given mean and standard deviation."""
    if sd is None or sd == 0:
        return 0.0
    return (x - mean) / sd


def contamination_score(values: Json, wf: Json) -> Tuple[float, str]:
    """
    Calculate contamination strength score (0.0 to 1.0+).
    
    Score is based on how strongly the values match contamination signatures.
    A score of 0.0 means no contamination signal.
    Higher scores indicate stronger evidence of contamination.
    
    Returns: (score, reason_string)
    """
    max_score = 0.0
    best_reason = ""
    
    for sig in wf.get("contamination_signatures", []):
        rule = sig.get("rule", {}) or {}
        k_min = rule.get("K_min")
        ca_max = rule.get("Ca_max")
        k_range = rule.get("K_range", 1.0)  # Expected range above K_min
        ca_range = rule.get("Ca_range", 1.0)  # Expected range below Ca_max
        
        k_val = values.get("K", 0)
        ca_val = values.get("Ca", 99)
        
        # Calculate individual component scores
        k_score = 0.0
        ca_score = 0.0
        
        if k_min is not None and k_val >= k_min:
            # How far above the minimum? Normalized by expected range
            k_score = min((k_val - k_min) / max(k_range, 0.1), 1.5)
        
        if ca_max is not None and ca_val <= ca_max:
            # How far below the maximum? Normalized by expected range
            ca_score = min((ca_max - ca_val) / max(ca_range, 0.1), 1.5)
        
        # Both conditions must be met, combined score is geometric mean
        if k_score > 0 and ca_score > 0:
            combined = (k_score * ca_score) ** 0.5
            if combined > max_score:
                max_score = combined
                best_reason = sig.get("hold_reason", "CONTAMINATION_SUSPECTED")
    
    return max_score, best_reason


def mismatch_score(spec_values: Json, patient: Json, analytes: List[str], 
                   weights: Json, zthr: float) -> float:
    """Calculate weighted mismatch score between specimen values and patient prior."""
    mean = patient["prior"]["mean"]
    sd = patient["prior"]["sd"]
    score = 0.0
    for a in analytes:
        if a not in spec_values:
            continue
        w = float(weights.get(a, 1.0))
        z = abs(zscore(float(spec_values[a]), float(mean[a]), float(sd[a])))
        score += w * min(z / max(zthr, 1e-6), 3.0)
    return score


def compute_swap_scores(specimens: List[Json], patients_idx: Dict[str, Json], 
                        wf: Json) -> Dict[str, float]:
    """
    Compute swap improvement scores for all specimens.
    
    Returns dict mapping specimen_id -> best_improvement_score.
    Score represents how much better the fit is if swapped with another specimen.
    A score of 0.0 means no swap benefit detected.
    Higher scores indicate stronger evidence of a swap.
    """
    sd = wf.get("swap_detection", {}) or {}
    if not sd.get("enabled", False):
        return {}
    
    analytes = wf.get("analytes", [])
    weights = sd.get("analyte_weights", {}) or {}
    zthr = float(wf.get("zscore_threshold", 3.0))
    
    # Track best improvement score for each specimen
    scores: Dict[str, float] = {s["specimen_id"]: 0.0 for s in specimens}
    
    n = len(specimens)
    for i in range(n):
        for j in range(i + 1, n):
            si, sj = specimens[i], specimens[j]
            pi = patients_idx.get(si["patient_id"])
            pj = patients_idx.get(sj["patient_id"])
            if not pi or not pj:
                continue
            
            # Original assignment mismatch
            base = (mismatch_score(si["values"], pi, analytes, weights, zthr) + 
                    mismatch_score(sj["values"], pj, analytes, weights, zthr))
            
            # Swapped assignment mismatch
            swapped = (mismatch_score(si["values"], pj, analytes, weights, zthr) + 
                       mismatch_score(sj["values"], pi, analytes, weights, zthr))
            
            if base <= 1e-9:
                continue
            
            # Improvement score: positive means swap is better
            improvement = (base - swapped) / base
            
            # Update best score for both specimens
            if improvement > scores[si["specimen_id"]]:
                scores[si["specimen_id"]] = improvement
            if improvement > scores[sj["specimen_id"]]:
                scores[sj["specimen_id"]] = improvement
    
    return scores


def make_decision(contam_score: float, swap_score: float, 
                  contam_threshold: float, swap_threshold: float,
                  contam_reason: str) -> Tuple[str, List[str]]:
    """
    Make HOLD/RELEASE decision based on scores and thresholds.
    
    Rules:
    1. If both scores below threshold -> RELEASE
    2. If only contamination above threshold -> HOLD for contamination
    3. If only swap above threshold -> HOLD for swap
    4. If both above threshold -> HOLD for the stronger signal
    """
    contam_triggered = contam_score >= contam_threshold
    swap_triggered = swap_score >= swap_threshold
    
    if not contam_triggered and not swap_triggered:
        # Neither signal strong enough - RELEASE even if weak signals exist
        return "RELEASE", []
    
    if contam_triggered and not swap_triggered:
        return "HOLD", [contam_reason or "CONTAMINATION_SUSPECTED"]
    
    if swap_triggered and not contam_triggered:
        return "HOLD", ["IDENTITY_SUSPECTED"]
    
    # Both triggered - use priority or stronger signal
    # Normalize scores relative to their thresholds for comparison
    contam_strength = contam_score / max(contam_threshold, 0.01)
    swap_strength = swap_score / max(swap_threshold, 0.01)
    
    if contam_strength >= swap_strength:
        return "HOLD", [contam_reason or "CONTAMINATION_SUSPECTED"]
    else:
        return "HOLD", ["IDENTITY_SUSPECTED"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", type=Path, default=Path("/app/workflow.json"))
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("/app/decisions.json"))
    args = ap.parse_args()

    wf = json.loads(args.workflow.read_text(encoding="utf-8"))
    batch = json.loads(args.batch.read_text(encoding="utf-8"))
    patients_idx = {p["patient_id"]: p for p in batch.get("patients", [])}
    specimens = batch.get("specimens", []) or []

    # Get batch constraints
    batch_constraints = batch.get("batch_constraints", {}) or {}
    max_holds = int(batch_constraints.get("max_holds", 999999))

    # Get thresholds from workflow (these are the key parameters agents must tune)
    decision_policy = wf.get("decision_policy", {})
    contam_threshold = float(decision_policy.get("contamination_hold_threshold", 0.5))
    swap_threshold = float(decision_policy.get("swap_hold_threshold", 0.3))
    
    # Compute all swap scores upfront
    swap_scores = compute_swap_scores(specimens, patients_idx, wf)

    decisions: List[Json] = []
    internal_scores: Dict[str, Tuple[float, float]] = {}  # sid -> (contam, swap)
    
    for s in specimens:
        sid = s["specimen_id"]
        pid = s["patient_id"]
        values = s["values"]
        
        # Calculate scores
        contam_score, contam_reason = contamination_score(values, wf)
        swap_score = swap_scores.get(sid, 0.0)
        internal_scores[sid] = (contam_score, swap_score)
        
        # Make thresholded decision
        action, reasons = make_decision(
            contam_score, swap_score,
            contam_threshold, swap_threshold,
            contam_reason
        )
        
        decisions.append({
            "specimen_id": sid, 
            "patient_id": pid, 
            "action": action, 
            "reasons": reasons
        })

    # Enforce HOLD budget constraint (prioritize strongest evidence)
    holds = [d for d in decisions if d["action"] == "HOLD"]

    if len(holds) > max_holds:
        # Rank HOLDs by strongest signal (max of contamination or swap score)
        holds_sorted = sorted(
            holds,
            key=lambda d: max(internal_scores[d["specimen_id"]]),
            reverse=True
        )

        # Keep only the top-N strongest HOLDs
        allowed = set(d["specimen_id"] for d in holds_sorted[:max_holds])

        # Downgrade weaker HOLDs to RELEASE
        for d in decisions:
            if d["action"] == "HOLD" and d["specimen_id"] not in allowed:
                d["action"] = "RELEASE"
                d["reasons"] = []

    args.out.write_text(
        json.dumps({"batch_id": batch.get("batch_id"), "decisions": decisions}, indent=2), 
        encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
