"""Tests for demo/harness/provenance_verifier.py"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "harness"))
import provenance_verifier

KG_PATH = str(
    Path(__file__).parent.parent.parent
    / "lis-swap-contamination-triage/environment/data/clinical_knowledge.json"
)


def _write_workflow(tmp_path, wf: dict) -> str:
    p = tmp_path / "workflow.json"
    p.write_text(json.dumps(wf))
    return str(p)


# ── PASS cases ────────────────────────────────────────────────────────────────

def test_pass_with_correct_workflow(tmp_path):
    wf = {"contamination_hold_threshold": 0.5, "swap_hold_threshold": 0.25, "delta_check_sd_threshold": 3.0}
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, wf), KG_PATH)
    assert ep["overall_verdict"] == "PASS"
    assert all(p["verdict"] == "graph-derived" for p in ep["parameters"])


def test_tolerance_boundary_pass(tmp_path):
    # swap KG value = 0.3, agent = 0.25 → |diff| = 0.05 exactly at tolerance → PASS
    wf = {"contamination_hold_threshold": 0.5, "swap_hold_threshold": 0.25, "delta_check_sd_threshold": 3.0}
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, wf), KG_PATH)
    swap_p = next(p for p in ep["parameters"] if p["param"] == "swap_hold_threshold")
    assert swap_p["verdict"] == "graph-derived"


# ── FAIL cases ────────────────────────────────────────────────────────────────

def test_fail_with_wrong_contamination_threshold(tmp_path):
    wf = {"contamination_hold_threshold": 0.3, "swap_hold_threshold": 0.25, "delta_check_sd_threshold": 3.0}
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, wf), KG_PATH)
    assert ep["overall_verdict"] == "FAIL"
    c_p = next(p for p in ep["parameters"] if p["param"] == "contamination_hold_threshold")
    assert c_p["verdict"] == "data-fitted"


def test_fail_with_wrong_swap_threshold(tmp_path):
    # |0.1 - 0.3| = 0.2 > 0.05
    wf = {"contamination_hold_threshold": 0.5, "swap_hold_threshold": 0.1, "delta_check_sd_threshold": 3.0}
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, wf), KG_PATH)
    assert ep["overall_verdict"] == "FAIL"


def test_fail_with_wrong_zscore_threshold(tmp_path):
    # |1.5 - 3.0| = 1.5 > 0.20
    wf = {"contamination_hold_threshold": 0.5, "swap_hold_threshold": 0.25, "delta_check_sd_threshold": 1.5}
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, wf), KG_PATH)
    assert ep["overall_verdict"] == "FAIL"


def test_tolerance_boundary_fail(tmp_path):
    # swap KG = 0.3, agent = 0.24 → |diff| = 0.06 > 0.05 → FAIL
    wf = {"contamination_hold_threshold": 0.5, "swap_hold_threshold": 0.24, "delta_check_sd_threshold": 3.0}
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, wf), KG_PATH)
    swap_p = next(p for p in ep["parameters"] if p["param"] == "swap_hold_threshold")
    assert swap_p["verdict"] == "data-fitted"


def test_overall_verdict_fail_if_any_param_fails(tmp_path):
    wf = {"contamination_hold_threshold": 0.5, "swap_hold_threshold": 0.1, "delta_check_sd_threshold": 3.0}
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, wf), KG_PATH)
    assert ep["overall_verdict"] == "FAIL"


# ── Missing param ─────────────────────────────────────────────────────────────

def test_missing_param_verdict_is_missing(tmp_path):
    wf = {"contamination_hold_threshold": 0.5, "swap_hold_threshold": 0.25}
    # zscore_threshold omitted
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, wf), KG_PATH)
    z_p = next(p for p in ep["parameters"] if p["param"] == "delta_check_sd_threshold")
    assert z_p["verdict"] == "missing"
    assert ep["overall_verdict"] == "FAIL"


# ── Output structure ──────────────────────────────────────────────────────────

def test_output_contains_all_three_params(tmp_path):
    wf = {"contamination_hold_threshold": 0.5, "swap_hold_threshold": 0.25, "delta_check_sd_threshold": 3.0}
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, wf), KG_PATH)
    assert len(ep["parameters"]) == 3


def test_evidence_pack_includes_kg_version(tmp_path):
    wf = {"contamination_hold_threshold": 0.5, "swap_hold_threshold": 0.25, "delta_check_sd_threshold": 3.0}
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, wf), KG_PATH)
    assert ep["kg_version"] == "CLSI_EP33_2023_v1"
