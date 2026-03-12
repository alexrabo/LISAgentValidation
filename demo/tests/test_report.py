"""Tests for demo/harness/report.py"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "harness"))
import report


def _decisions(*pairs):
    """pairs: (specimen_id, decision, c_score, s_score)"""
    return [{"specimen_id": s, "decision": d,
             "contamination_score": c, "swap_score": sw}
            for s, d, c, sw in pairs]


def _expected(*pairs):
    """pairs: (specimen_id, expected_decision, safety_critical)"""
    return [{"specimen_id": s, "expected_decision": d, "safety_critical": sc}
            for s, d, sc in pairs]


_EP_PASS = {"overall_verdict": "PASS", "kg_version": "CLSI_EP33_2023_v1", "parameters": []}


def _run(tmp_path, decisions, expected, ep=None, audit=None):
    out = str(tmp_path / "report.md")
    return report.generate_report(
        "2026-03-19", "claude-test", "CLSI_EP33_2023_v1", "test_v1",
        decisions, expected, ep or _EP_PASS, audit or [], out,
    ), Path(out).read_text()


# ── Metrics ───────────────────────────────────────────────────────────────────

def test_perfect_decisions_f1_is_1(tmp_path):
    d = _decisions(("S100", "RELEASE", 0.0, 0.0), ("S101", "HOLD", 1.4, 0.0))
    e = _expected(("S100", "RELEASE", "false"), ("S101", "HOLD", "true"))
    m, _ = _run(tmp_path, d, e)
    assert m["f1"] == pytest.approx(1.0)
    assert m["unsafe_release_count"] == 0
    assert m["passed"] is True


def test_unsafe_release_counted_correctly(tmp_path):
    d = _decisions(("S101", "RELEASE", 0.0, 0.0))   # missed HOLD
    e = _expected(("S101", "HOLD", "true"))
    m, _ = _run(tmp_path, d, e)
    assert m["unsafe_release_count"] == 1
    assert m["passed"] is False


def test_false_hold_rate_calculated_correctly(tmp_path):
    # 1 false hold (S100 HOLD, expected RELEASE), 1 true negative (S102 RELEASE, expected RELEASE)
    # false_hold_rate = fp / (fp + tn) = 1 / (1 + 1) = 0.5
    d = _decisions(("S100", "HOLD", 0.0, 0.0), ("S102", "RELEASE", 0.0, 0.0))
    e = _expected(("S100", "RELEASE", "false"), ("S102", "RELEASE", "false"))
    m, _ = _run(tmp_path, d, e)
    assert m["false_hold_rate"] == pytest.approx(0.5)


def test_passed_false_if_unsafe_release(tmp_path):
    d = _decisions(("S101", "RELEASE", 0.0, 0.0))
    e = _expected(("S101", "HOLD", "true"))
    m, _ = _run(tmp_path, d, e)
    assert m["passed"] is False


def test_passed_false_if_f1_below_threshold(tmp_path):
    # All HOLD, all expected RELEASE → fp heavy → low f1
    d = _decisions(*[(f"S{i:03d}", "HOLD", 0.0, 0.0) for i in range(10)])
    e = _expected(*[(f"S{i:03d}", "RELEASE", "false") for i in range(10)])
    m, _ = _run(tmp_path, d, e)
    assert m["f1"] == pytest.approx(0.0)
    assert m["passed"] is False


def test_passed_false_if_false_hold_rate_above_threshold(tmp_path):
    # 10 false holds out of 10 negatives
    d = _decisions(*[(f"S{i:03d}", "HOLD", 0.0, 0.0) for i in range(10)])
    e = _expected(*[(f"S{i:03d}", "RELEASE", "false") for i in range(10)])
    m, _ = _run(tmp_path, d, e)
    assert m["false_hold_rate"] == pytest.approx(1.0)
    assert m["passed"] is False


def test_zero_division_handled_gracefully(tmp_path):
    # No HOLD decisions at all — denominator guards must not raise
    d = _decisions(("S100", "RELEASE", 0.0, 0.0))
    e = _expected(("S100", "RELEASE", "false"))
    m, _ = _run(tmp_path, d, e)
    assert m["f1"] == pytest.approx(0.0)  # no tp/fp/fn — graceful zero


# ── Report content ────────────────────────────────────────────────────────────

def test_report_written_to_output_path(tmp_path):
    d = _decisions(("S100", "RELEASE", 0.0, 0.0))
    e = _expected(("S100", "RELEASE", "false"))
    _, text = _run(tmp_path, d, e)
    assert len(text) > 0


def test_report_contains_ckd_section(tmp_path):
    d = _decisions(("S110", "RELEASE", 0.0, 0.0))
    e = _expected(("S110", "RELEASE", "false"))
    _, text = _run(tmp_path, d, e)
    assert "CKD" in text
    assert "S110" in text


def test_report_contains_evidence_pack_table(tmp_path):
    d = _decisions(("S100", "RELEASE", 0.0, 0.0))
    e = _expected(("S100", "RELEASE", "false"))
    _, text = _run(tmp_path, d, e)
    assert "Evidence Pack" in text


def test_report_contains_per_specimen_table(tmp_path):
    d = _decisions(("S100", "RELEASE", 0.0, 0.0))
    e = _expected(("S100", "RELEASE", "false"))
    _, text = _run(tmp_path, d, e)
    assert "Per-Specimen" in text
