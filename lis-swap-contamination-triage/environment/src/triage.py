#!/usr/bin/env python3
"""
LIS Triage System - Scored Decision Logic

This system uses NUMERIC SCORES with THRESHOLDS for HOLD decisions.
Simply detecting a signal is NOT sufficient - the signal must be strong enough.

Key parameters in workflow.json:
- contamination_hold_threshold: minimum contamination_score to trigger HOLD
- swap_hold_threshold: minimum swap improvement score to trigger HOLD

If scores are below thresholds, the specimen is RELEASED even if weak signals exist.

--- Clinical Background ---

CONTAMINATION DETECTION:
  Uses analyte signature matching (e.g., EDTA-like: elevated K, depressed Ca).
  Score reflects how strongly the current values match a known contamination pattern.

SWAP DETECTION (Specimen Identity Verification):
  Uses the Delta Check approach — the standard laboratory method for detecting
  specimen identity errors. A delta check flags a result when the difference
  between the current value and the patient's prior result exceeds a threshold.

  Here, the delta check is STANDARDIZED by the patient's prior biological
  variability (SD), making the threshold patient-independent:

      delta_check(x) = |x - prior_mean| / prior_SD

  This is equivalent to a z-score relative to the patient's own history,
  also called the "standardized difference" or "delta check divisor" in
  clinical lab informatics.

  For swap detection, we compare the delta check mismatch score under the
  ORIGINAL assignment vs. a SWAPPED assignment. If swapping two specimens
  between their patients produces a substantially better fit (lower combined
  delta check score), both specimens are flagged as likely swapped.

  Key workflow.json parameter:
  - zscore_threshold: the delta check divisor threshold — how many SDs of
    deviation from a patient's prior is considered anomalous
  - swap_hold_threshold: minimum improvement ratio (original/swapped mismatch)
    required to trigger a HOLD for identity concern
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

Json = Dict[str, Any]


def zscore(x: float, mean: float, sd: float) -> float:
    """Compute the standardized delta check value for a single analyte.

    In clinical laboratory practice, a delta check compares a patient's current
    result against their prior result. When normalized by the patient's prior
    biological variability (SD), this becomes the standardized delta check —
    a patient-independent measure of how anomalous the current value is.

        standardized_delta_check = (current - prior_mean) / prior_SD

    Values with |delta_check| > zscore_threshold are considered anomalous
    and contribute to the specimen's swap mismatch score.
    """
    if sd is None or sd == 0:
        return 0.0
    return (x - mean) / sd


def contamination_score(values: Json, wf: Json,
                        patient: Optional[Json] = None) -> Tuple[float, str]:
    """
    Calculate contamination strength score (0.0 to 1.5).

    Supports two scoring modes controlled by the ``"mode"`` field of each
    contamination signature in workflow.json:

    ``"absolute"`` (default when ``"mode"`` is absent)
        Compares raw analyte values against population-level thresholds.
        Parameters: ``K_min``, ``Ca_max``, ``K_range``, ``Ca_range``.
        Used as the primary mode when no patient prior is available (new
        patient, first encounter).

    ``"prior_relative"``
        Compares each analyte against the *patient's own* prior mean and SD
        (standardized delta check). This is the preferred clinical approach
        when a prior exists: it distinguishes a CKD patient's chronically
        elevated K (small delta from baseline) from an EDTA artifact's
        acutely elevated K (many SDs above the patient's own history).

        Parameters:
          - ``K_delta_min``  : K must exceed this many SDs above prior mean
          - ``Ca_delta_max`` : Ca must fall below this many SDs (negative value)
          - ``fallback_K_min``, ``fallback_Ca_max``, ``fallback_K_range``,
            ``fallback_Ca_range``: used automatically when no patient prior
            is available in the batch.

        Scoring formula (prior_relative):
          k_score  = clamp(k_zscore  / K_delta_min,  0, 1.5)
          ca_score = clamp(ca_zscore / Ca_delta_max, 0, 1.5)   # both negative
          combined = geometric_mean(k_score, ca_score)

        A score of 1.0 means both analytes are exactly at their respective
        delta thresholds; >1.0 means the contamination signal is stronger.

    Returns: (score, reason_string)
    """
    max_score = 0.0
    best_reason = ""

    for sig in wf.get("contamination_signatures", []):
        rule = sig.get("rule", {}) or {}
        mode = sig.get("mode", "absolute")
        k_val = float(values.get("K", 0))
        ca_val = float(values.get("Ca", 99))

        k_score = 0.0
        ca_score = 0.0

        if mode == "prior_relative" and patient is not None and "prior" in patient:
            # --- Prior-relative delta check (preferred when history exists) ---
            prior_mean = patient["prior"]["mean"]
            prior_sd = patient["prior"]["sd"]
            k_zscore = zscore(k_val, float(prior_mean["K"]), float(prior_sd["K"]))
            ca_zscore = zscore(ca_val, float(prior_mean["Ca"]), float(prior_sd["Ca"]))

            k_delta_min = float(rule.get("K_delta_min", 3.0))
            ca_delta_max = float(rule.get("Ca_delta_max", -2.5))  # negative

            if k_delta_min > 0:
                k_score = min(max(0.0, k_zscore / k_delta_min), 1.5)
            if ca_delta_max < 0:
                ca_score = min(max(0.0, ca_zscore / ca_delta_max), 1.5)

        elif mode == "prior_relative" and (patient is None or "prior" not in patient):
            # --- Fallback: no prior available, use absolute population thresholds ---
            k_min = rule.get("fallback_K_min")
            ca_max = rule.get("fallback_Ca_max")
            k_range = float(rule.get("fallback_K_range", 1.0))
            ca_range = float(rule.get("fallback_Ca_range", 1.0))

            if k_min is not None and k_val >= float(k_min):
                k_score = min((k_val - float(k_min)) / max(k_range, 0.1), 1.5)
            if ca_max is not None and ca_val <= float(ca_max):
                ca_score = min((float(ca_max) - ca_val) / max(ca_range, 0.1), 1.5)

        else:
            # --- Absolute mode (default) ---
            k_min = rule.get("K_min")
            ca_max = rule.get("Ca_max")
            k_range = float(rule.get("K_range", 1.0))
            ca_range = float(rule.get("Ca_range", 1.0))

            if k_min is not None and k_val >= float(k_min):
                k_score = min((k_val - float(k_min)) / max(k_range, 0.1), 1.5)
            if ca_max is not None and ca_val <= float(ca_max):
                ca_score = min((float(ca_max) - ca_val) / max(ca_range, 0.1), 1.5)

        # Both analyte conditions must be met; combined score is geometric mean
        if k_score > 0 and ca_score > 0:
            combined = (k_score * ca_score) ** 0.5
            if combined > max_score:
                max_score = combined
                best_reason = sig.get("hold_reason", "CONTAMINATION_SUSPECTED")

    return max_score, best_reason


def mismatch_score(spec_values: Json, patient: Json, analytes: List[str],
                   weights: Json, zthr: float) -> float:
    """Compute the weighted delta check mismatch score for a specimen against a patient.

    For each analyte, calculates the standardized delta check (deviation from the
    patient's prior mean, normalized by prior SD). Deviations exceeding zthr
    (the delta check threshold) contribute proportionally to the mismatch score.

    A low score means the specimen values are consistent with this patient's history.
    A high score means the values are anomalous for this patient — possible identity error.

    Used in swap detection: if specimen A scores low against patient B (but was
    assigned to patient A), that is evidence of a swap.
    """
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
    """Compute pairwise delta check swap scores for all specimens in the batch.

    This implements the standard laboratory specimen identity verification method:
    for each pair of specimens, compare the combined delta check mismatch score
    under the ORIGINAL patient assignments vs. a HYPOTHETICAL SWAP.

    If swapping two specimens between their patients produces a substantially
    better combined delta check fit, both are flagged with an elevated swap score.

    The improvement ratio is:
        improvement = (original_mismatch - swapped_mismatch) / original_mismatch

    A positive improvement means the swapped assignment fits the patients' prior
    histories better — indicating a likely specimen identity error.

    Returns dict mapping specimen_id -> best_improvement_score across all pairs.
    Score of 0.0 means no swap signal detected for that specimen.
    Score approaching 1.0 means the swapped assignment is dramatically better fit.
    """
    sd = wf.get("swap_detection", {}) or {}
    if not sd.get("enabled", False):
        return {}
    
    analytes = wf.get("analytes", [])
    weights = sd.get("analyte_weights", {}) or {}
    zthr = float(wf.get("delta_check_threshold", 3.0))
    
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
            # Skip swap check if either patient has no prior history — delta check
            # requires a prior baseline; new patients cannot be evaluated for swaps.
            if "prior" not in pi or "prior" not in pj:
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
        patient = patients_idx.get(pid)
        contam_score, contam_reason = contamination_score(values, wf, patient)
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
