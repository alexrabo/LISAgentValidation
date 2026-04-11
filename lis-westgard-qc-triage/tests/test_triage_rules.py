"""
Unit tests for Westgard QC triage engine rule logic.

Tests each rule in isolation using apply_rules() directly — independent of
fixture files, batch structure, or the invocation counter.

Coverage map:
  test_fast_exit_accept              → 1₂s gate: all in control → ACCEPT, skip all rules
  test_1_2s_warning_only             → 1₂s gate: exceeds ±2s but no rejection rule → WARNING
  test_1_3s_reject_random            → 1₃s: single observation > ±3s → REJECT, random
  test_1_3s_boundary_below           → 1₃s: exactly at 3s → does NOT reject (strict >)
  test_R_4s_reject_random            → R₄s: opposite directions within event, range > 4s → REJECT, random
  test_R_4s_same_direction_no_fire   → R₄s: same direction (not R₄s pattern) → no R₄s
  test_R_4s_not_cross_event          → R₄s: does not fire across consecutive events
  test_2_2s_within_level             → 2₂s within level: two consecutive events same side → REJECT, systematic
  test_2_2s_within_level_no_fire_opp → 2₂s within level: opposite directions → no fire
  test_2_2s_cross_level_enabled      → 2₂s cross-level: both levels same direction, policy enabled → REJECT, systematic, high
  test_2_2s_cross_level_disabled     → 2₂s cross-level: policy disabled → no cross-level detection
  test_2_2s_cross_level_opposite_dir → 2₂s cross-level: opposite directions → no 2₂s (R₄s instead)
  test_4_1s_within_level             → 4₁s within: 4 consecutive same level > +1s → REJECT, systematic
  test_4_1s_within_level_below       → 4₁s within: 4 consecutive same level < -1s → REJECT, systematic
  test_4_1s_not_enough_history       → 4₁s: only 3 consecutive → no fire
  test_4_1s_cross_level              → 4₁s cross: 2 events × 2 levels all > +1s → REJECT, systematic
  test_4_1s_cross_level_mixed_dir    → 4₁s cross: mixed directions → no fire
  test_10x_within_level              → 10×: 10 consecutive same level all positive → REJECT, systematic
  test_10x_not_enough                → 10×: only 9 consecutive → no fire
  test_10x_cross_level               → 10× cross: 5 events × 2 levels all positive → REJECT, systematic
  test_multiple_rules_fire           → multiple rules can fire simultaneously
  test_multilevel_confidence_high    → 2₂s cross-level yields confidence='high'
  test_workflow_defaults_safe        → engine does not crash on minimal workflow.json
"""

import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

# Allow import from src/ directory
sys.path.insert(0, str(Path(__file__).parent.parent / "environment" / "src"))
from triage import apply_rules, z_score, same_direction

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WF_STANDARD = {
    "rules": {
        "warning_threshold_sd":        2.0,
        "rejection_1_3s_threshold_sd": 3.0,
        "rejection_2_2s_threshold_sd": 2.0,
        "rejection_R_4s_range_sd":     4.0,
        "rejection_4_1s_consecutive":  4,
        "rejection_4_1s_threshold_sd": 1.0,
        "rejection_10x_consecutive":   10,
    },
    "multi_level_policy": {
        "enabled":            True,
        "scope":              "same_QC_event",
        "direction_required": True,
    }
}

WF_ML_DISABLED = {
    **WF_STANDARD,
    "multi_level_policy": {
        "enabled":            False,
        "scope":              "same_QC_event",
        "direction_required": True,
    }
}


def make_event_z(entries: List[Tuple[str, int, float]]) -> Dict[Tuple[str, int], float]:
    """Build event_z dict from (analyte, level, z) triples."""
    return {(a, lv): z for a, lv, z in entries}


def make_history(entries: List[Tuple[str, int, List[float]]]) -> Dict[Tuple[str, int], List[float]]:
    """Build history dict from (analyte, level, [z_scores]) triples."""
    h = defaultdict(list)
    for a, lv, zs in entries:
        h[(a, lv)] = list(zs)
    return h


def run(event_z, history=None, wf=None):
    """Convenience wrapper for apply_rules."""
    if history is None:
        # Default: history has exactly the current event's z-scores as last entry
        history = defaultdict(list)
        for (a, lv), z in event_z.items():
            history[(a, lv)].append(z)
    if wf is None:
        wf = WF_STANDARD
    return apply_rules("test_event", event_z, history, wf)


# ---------------------------------------------------------------------------
# Fast-exit / 1₂s gate
# ---------------------------------------------------------------------------

def test_fast_exit_accept():
    """All observations within ±2s → ACCEPT immediately, no rules evaluated."""
    ez = make_event_z([("K", 1, 1.5), ("K", 2, -1.0)])
    action, triggered, error_type, confidence = run(ez)
    assert action == "ACCEPT"
    assert triggered == []
    assert error_type is None


def test_1_2s_warning_only():
    """1₂s triggers (one obs > 2s) but no rejection rule fires → WARNING."""
    # z=2.1 exceeds 2s warning, but < 3s (1₃s), not two consecutive (2₂s), etc.
    ez = make_event_z([("K", 1, 2.1), ("K", 2, 0.5)])
    # History: only one event, so no consecutive rules can fire
    action, triggered, error_type, confidence = run(ez)
    assert action == "WARNING"
    assert error_type is None
    assert "1_3s" not in triggered


# ---------------------------------------------------------------------------
# 1₃s
# ---------------------------------------------------------------------------

def test_1_3s_reject_random():
    """Single observation exceeds ±3s → REJECT, random error."""
    ez = make_event_z([("K", 1, 3.5), ("K", 2, 0.5)])
    action, triggered, error_type, _ = run(ez)
    assert action == "REJECT"
    assert "1_3s" in triggered
    assert error_type == "random"


def test_1_3s_boundary_below():
    """Exactly at 3.0s does NOT trigger 1₃s (strict > comparison)."""
    ez = make_event_z([("K", 1, 3.0), ("K", 2, 0.5)])
    action, triggered, _, _ = run(ez)
    # 3.0 exceeds 2s warning → WARNING, but 1₃s requires > 3.0
    assert "1_3s" not in triggered


# ---------------------------------------------------------------------------
# R₄s
# ---------------------------------------------------------------------------

def test_R_4s_reject_random():
    """L1 > +2s, L2 < -2s within same event, range > 4s → REJECT, random."""
    ez = make_event_z([("K", 1, 2.2), ("K", 2, -2.2)])
    action, triggered, error_type, _ = run(ez)
    assert action == "REJECT"
    assert "R_4s" in triggered
    assert error_type == "random"


def test_R_4s_same_direction_no_fire():
    """Both L1 and L2 > +2s (same direction) — not R₄s pattern."""
    ez = make_event_z([("K", 1, 2.2), ("K", 2, 2.3)])
    action, triggered, _, _ = run(ez)
    assert "R_4s" not in triggered


def test_R_4s_not_cross_event():
    """R₄s should NOT fire across consecutive events — within-run only."""
    # Event 1: K L1 was +2.5, Event 2: K L1 is -2.5
    # These are different events — R₄s must NOT fire
    ez = make_event_z([("K", 1, -2.5), ("K", 2, 0.5)])
    history = make_history([
        ("K", 1, [2.5, -2.5]),  # prev event was +2.5, current is -2.5
        ("K", 2, [0.5, 0.5]),
    ])
    action, triggered, _, _ = apply_rules("test", ez, history, WF_STANDARD)
    assert "R_4s" not in triggered


# ---------------------------------------------------------------------------
# 2₂s within level
# ---------------------------------------------------------------------------

def test_2_2s_within_level():
    """Two consecutive events same level both > +2s → REJECT, systematic."""
    ez = make_event_z([("K", 1, 2.3), ("K", 2, 0.5)])
    history = make_history([
        ("K", 1, [2.1, 2.3]),   # prev=2.1, curr=2.3 — both > 2s
        ("K", 2, [0.5, 0.5]),
    ])
    action, triggered, error_type, _ = apply_rules("test", ez, history, WF_STANDARD)
    assert action == "REJECT"
    assert "2_2s_within_level" in triggered
    assert error_type == "systematic"


def test_2_2s_within_level_no_fire_opposite():
    """Previous event > +2s, current < -2s — opposite directions, no 2₂s."""
    ez = make_event_z([("K", 1, -2.3), ("K", 2, 0.5)])
    history = make_history([
        ("K", 1, [2.1, -2.3]),  # prev=+2.1, curr=-2.3 — opposite
        ("K", 2, [0.5, 0.5]),
    ])
    action, triggered, _, _ = apply_rules("test", ez, history, WF_STANDARD)
    assert "2_2s_within_level" not in triggered


# ---------------------------------------------------------------------------
# 2₂s cross-level (multi-level synthesis — the L2 trap)
# ---------------------------------------------------------------------------

def test_2_2s_cross_level_enabled():
    """Both L1 and L2 > +2s in same event, policy enabled → REJECT, systematic, high confidence."""
    ez = make_event_z([("K", 1, 2.3), ("K", 2, 2.4)])
    action, triggered, error_type, confidence = run(ez, wf=WF_STANDARD)
    assert action == "REJECT"
    assert "2_2s_cross_level" in triggered
    assert error_type == "systematic"
    assert confidence == "high"


def test_2_2s_cross_level_disabled():
    """Policy disabled → cross-level 2₂s not detected, even with both levels > 2s."""
    ez = make_event_z([("K", 1, 2.3), ("K", 2, 2.4)])
    action, triggered, _, _ = run(ez, wf=WF_ML_DISABLED)
    assert "2_2s_cross_level" not in triggered


def test_2_2s_cross_level_opposite_direction():
    """L1 > +2s, L2 < -2s — opposite directions, no 2₂s cross-level (R₄s fires instead)."""
    ez = make_event_z([("K", 1, 2.3), ("K", 2, -2.4)])
    action, triggered, _, _ = run(ez, wf=WF_STANDARD)
    assert "2_2s_cross_level" not in triggered
    assert "R_4s" in triggered


# ---------------------------------------------------------------------------
# 4₁s
# ---------------------------------------------------------------------------

def test_4_1s_within_level_above():
    """4 consecutive same level all > +1s → REJECT, systematic.

    Current event must exceed ±2s to pass the 1₂s gate — then 4₁s checks
    the last 4 including current. Previous 3 need only exceed ±1s.
    """
    ez = make_event_z([("K", 1, 2.1), ("K", 2, 0.5)])  # 2.1 triggers 1₂s AND > 1s
    history = make_history([
        ("K", 1, [1.1, 1.2, 1.3, 2.1]),  # last 4 all > 1s
        ("K", 2, [0.5, 0.5, 0.5, 0.5]),
    ])
    action, triggered, error_type, _ = apply_rules("test", ez, history, WF_STANDARD)
    assert action == "REJECT"
    assert "4_1s_within_level" in triggered
    assert error_type == "systematic"


def test_4_1s_within_level_below():
    """4 consecutive same level all < -1s → REJECT, systematic."""
    ez = make_event_z([("K", 1, -2.1), ("K", 2, 0.5)])  # -2.1 triggers 1₂s AND < -1s
    history = make_history([
        ("K", 1, [-1.2, -1.1, -1.3, -2.1]),  # last 4 all < -1s
        ("K", 2, [0.5, 0.5, 0.5, 0.5]),
    ])
    action, triggered, error_type, _ = apply_rules("test", ez, history, WF_STANDARD)
    assert action == "REJECT"
    assert "4_1s_within_level" in triggered


def test_4_1s_not_enough_history():
    """Only 3 consecutive observations — 4₁s does not fire."""
    ez = make_event_z([("K", 1, 1.3), ("K", 2, 0.5)])
    history = make_history([
        ("K", 1, [1.1, 1.2, 1.3]),  # only 3
        ("K", 2, [0.5, 0.5, 0.5]),
    ])
    action, triggered, _, _ = apply_rules("test", ez, history, WF_STANDARD)
    assert "4_1s_within_level" not in triggered


def test_4_1s_cross_level():
    """2 events × 2 levels (4 observations total) all > +1s → 4₁s cross-level fires.

    Current event must have at least one obs > 2s to pass the 1₂s gate.
    """
    ez = make_event_z([("K", 1, 2.1), ("K", 2, 1.3)])  # L1 triggers 1₂s
    history = make_history([
        ("K", 1, [1.1, 2.1]),   # prev=1.1, curr=2.1 — both > 1s
        ("K", 2, [1.4, 1.3]),   # prev=1.4, curr=1.3 — both > 1s
    ])
    action, triggered, error_type, _ = apply_rules("test", ez, history, WF_STANDARD)
    assert action == "REJECT"
    assert ("4_1s_within_level" in triggered or "4_1s_cross_level" in triggered)
    assert error_type == "systematic"


def test_4_1s_cross_level_mixed_direction():
    """Cross-level observations in mixed directions → 4₁s cross-level does not fire."""
    ez = make_event_z([("K", 1, 1.2), ("K", 2, -1.3)])
    history = make_history([
        ("K", 1, [1.1, 1.2]),
        ("K", 2, [-1.4, -1.3]),   # opposite direction to L1
    ])
    action, triggered, _, _ = apply_rules("test", ez, history, WF_STANDARD)
    assert "4_1s_cross_level" not in triggered


# ---------------------------------------------------------------------------
# 10×
# ---------------------------------------------------------------------------

def test_10x_within_level():
    """10 consecutive same level all positive → REJECT, systematic.

    Current obs must exceed ±2s to trigger 1₂s gate. Small positive values
    count toward 10× (same side of mean) but don't trigger 1₂s — so the
    last observation must be > 2s to enter the rejection rule checks.
    """
    ez = make_event_z([("K", 1, 2.1), ("K", 2, 0.5)])  # 2.1 triggers 1₂s, still positive
    history = make_history([
        ("K", 1, [0.1, 0.2, 0.3, 0.1, 0.2, 0.3, 0.1, 0.2, 0.3, 2.1]),  # 10 positive
        ("K", 2, [0.5] * 10),
    ])
    action, triggered, error_type, _ = apply_rules("test", ez, history, WF_STANDARD)
    assert action == "REJECT"
    assert "10x_within_level" in triggered
    assert error_type == "systematic"


def test_10x_not_enough_history():
    """Only 9 consecutive same-side — 10× does not fire."""
    ez = make_event_z([("K", 1, 0.3), ("K", 2, 0.5)])
    history = make_history([
        ("K", 1, [0.1, 0.2, 0.3, 0.1, 0.2, 0.3, 0.1, 0.2, 0.3]),  # only 9
        ("K", 2, [0.5] * 9),
    ])
    action, triggered, _, _ = apply_rules("test", ez, history, WF_STANDARD)
    assert "10x_within_level" not in triggered


def test_10x_cross_level():
    """5 events × 2 levels (10 total) all positive → 10× cross-level fires."""
    ez = make_event_z([("K", 1, 2.1), ("K", 2, 0.4)])  # L1 triggers 1₂s
    history = make_history([
        ("K", 1, [0.1, 0.2, 0.3, 0.2, 2.1]),   # 5 events, all positive
        ("K", 2, [0.2, 0.3, 0.1, 0.4, 0.4]),   # 5 events, all positive
    ])
    action, triggered, error_type, _ = apply_rules("test", ez, history, WF_STANDARD)
    assert action == "REJECT"
    assert ("10x_within_level" in triggered or "10x_cross_level" in triggered)
    assert error_type == "systematic"


# ---------------------------------------------------------------------------
# Multiple rules firing simultaneously
# ---------------------------------------------------------------------------

def test_multiple_rules_fire():
    """1₃s and 4₁s can fire on the same event — both appear in triggered_rules."""
    ez = make_event_z([("K", 1, 3.5), ("K", 2, 0.5)])
    history = make_history([
        ("K", 1, [1.1, 1.2, 1.3, 3.5]),  # 4 consecutive > 1s, last also > 3s
        ("K", 2, [0.5] * 4),
    ])
    action, triggered, error_type, _ = apply_rules("test", ez, history, WF_STANDARD)
    assert action == "REJECT"
    assert "1_3s" in triggered
    assert "4_1s_within_level" in triggered


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

def test_multilevel_confidence_high():
    """2₂s cross-level yields confidence='high'; single-level is 'standard'."""
    # Cross-level → high
    ez = make_event_z([("K", 1, 2.3), ("K", 2, 2.4)])
    _, _, _, confidence = run(ez, wf=WF_STANDARD)
    assert confidence == "high"

    # Single 1₃s → standard
    ez2 = make_event_z([("K", 1, 3.5), ("K", 2, 0.5)])
    _, _, _, confidence2 = run(ez2, wf=WF_STANDARD)
    assert confidence2 == "standard"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_workflow_defaults_safe():
    """Engine does not crash on minimal workflow.json (missing keys use defaults)."""
    ez = make_event_z([("K", 1, 3.5)])
    action, triggered, error_type, _ = run(ez, wf={})
    assert action == "REJECT"
    assert "1_3s" in triggered


def test_single_level_only():
    """Engine handles events with only one level (no cross-level rules fire)."""
    ez = make_event_z([("K", 1, 2.3)])
    action, triggered, _, _ = run(ez, wf=WF_STANDARD)
    assert "R_4s" not in triggered
    assert "2_2s_cross_level" not in triggered


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------

def test_z_score_positive():
    assert abs(z_score(5.0, 4.0, 1.0) - 1.0) < 1e-9


def test_z_score_negative():
    assert abs(z_score(3.0, 4.0, 1.0) - (-1.0)) < 1e-9


def test_z_score_zero_sd():
    assert z_score(5.0, 4.0, 0.0) == 0.0


def test_same_direction_above():
    assert same_direction([1.5, 1.2, 1.8], 1.0) == "above"


def test_same_direction_below():
    assert same_direction([-1.5, -1.2, -1.8], 1.0) == "below"


def test_same_direction_mixed():
    assert same_direction([1.5, -1.2, 1.8], 1.0) is None


def test_same_direction_at_threshold():
    """Values exactly at threshold do not satisfy strict > condition."""
    assert same_direction([1.0, 1.0], 1.0) is None
