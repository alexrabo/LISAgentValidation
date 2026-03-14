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


_GLUCOSE_WEIGHTS = {"swap_detection": {"analyte_weights": {"Glucose": 3.0}}}


def _full_pass_workflow(**overrides) -> dict:
    """Base workflow with all four KG-required parameters passing."""
    wf = {
        "contamination_hold_threshold": 0.5,
        "swap_hold_threshold": 0.25,
        "delta_check_sd_threshold": 3.0,
        "swap_detection": {"analyte_weights": {"Glucose": 3.0}},
    }
    wf.update(overrides)
    return wf


# ── PASS cases ────────────────────────────────────────────────────────────────

def test_pass_with_correct_workflow(tmp_path):
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, _full_pass_workflow()), KG_PATH)
    assert ep["overall_verdict"] == "PASS"
    assert all(p["verdict"] == "graph-derived" for p in ep["parameters"])


def test_tolerance_boundary_pass(tmp_path):
    # swap KG value = 0.3, agent = 0.25 → |diff| = 0.05 exactly at tolerance → PASS
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, _full_pass_workflow()), KG_PATH)
    swap_p = next(p for p in ep["parameters"] if p["param"] == "swap_hold_threshold")
    assert swap_p["verdict"] == "graph-derived"


def test_pass_glucose_weight_exact(tmp_path):
    # KG glucose_recommended_weight = 3.0, agent = 3.0 → PASS
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, _full_pass_workflow()), KG_PATH)
    g_p = next(p for p in ep["parameters"] if "Glucose" in p["param"])
    assert g_p["verdict"] == "graph-derived"


# ── FAIL cases ────────────────────────────────────────────────────────────────

def test_fail_with_wrong_contamination_threshold(tmp_path):
    ep = provenance_verifier.verify_provenance(
        _write_workflow(tmp_path, _full_pass_workflow(contamination_hold_threshold=0.3)), KG_PATH)
    assert ep["overall_verdict"] == "FAIL"
    c_p = next(p for p in ep["parameters"] if p["param"] == "contamination_hold_threshold")
    assert c_p["verdict"] == "data-fitted"


def test_fail_with_wrong_swap_threshold(tmp_path):
    # |0.1 - 0.3| = 0.2 > 0.05
    ep = provenance_verifier.verify_provenance(
        _write_workflow(tmp_path, _full_pass_workflow(swap_hold_threshold=0.1)), KG_PATH)
    assert ep["overall_verdict"] == "FAIL"


def test_fail_with_wrong_zscore_threshold(tmp_path):
    # |1.5 - 3.0| = 1.5 > 0.20
    ep = provenance_verifier.verify_provenance(
        _write_workflow(tmp_path, _full_pass_workflow(delta_check_sd_threshold=1.5)), KG_PATH)
    assert ep["overall_verdict"] == "FAIL"


def test_fail_with_wrong_glucose_weight(tmp_path):
    # hJQzBJW-style: Glucose weight 1.0 never read from KG → |1.0 - 3.0| = 2.0 > 0.05 → FAIL
    wf = _full_pass_workflow()
    wf["swap_detection"]["analyte_weights"]["Glucose"] = 1.0
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, wf), KG_PATH)
    assert ep["overall_verdict"] == "FAIL"
    g_p = next(p for p in ep["parameters"] if "Glucose" in p["param"])
    assert g_p["verdict"] == "data-fitted"


def test_fail_with_guessed_glucose_weight(tmp_path):
    # HsPAVBJ step-3-style: agent guessed 0.5, KG specifies 3.0 → FAIL
    wf = _full_pass_workflow()
    wf["swap_detection"]["analyte_weights"]["Glucose"] = 0.5
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, wf), KG_PATH)
    assert ep["overall_verdict"] == "FAIL"
    g_p = next(p for p in ep["parameters"] if "Glucose" in p["param"])
    assert g_p["verdict"] == "data-fitted"


def test_tolerance_boundary_fail(tmp_path):
    # swap KG = 0.3, agent = 0.24 → |diff| = 0.06 > 0.05 → FAIL
    ep = provenance_verifier.verify_provenance(
        _write_workflow(tmp_path, _full_pass_workflow(swap_hold_threshold=0.24)), KG_PATH)
    swap_p = next(p for p in ep["parameters"] if p["param"] == "swap_hold_threshold")
    assert swap_p["verdict"] == "data-fitted"


def test_overall_verdict_fail_if_any_param_fails(tmp_path):
    ep = provenance_verifier.verify_provenance(
        _write_workflow(tmp_path, _full_pass_workflow(swap_hold_threshold=0.1)), KG_PATH)
    assert ep["overall_verdict"] == "FAIL"


# ── Missing param ─────────────────────────────────────────────────────────────

def test_missing_param_verdict_is_missing(tmp_path):
    wf = _full_pass_workflow()
    del wf["delta_check_sd_threshold"]
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, wf), KG_PATH)
    z_p = next(p for p in ep["parameters"] if p["param"] == "delta_check_sd_threshold")
    assert z_p["verdict"] == "missing"
    assert ep["overall_verdict"] == "FAIL"


def test_missing_glucose_weight_is_missing(tmp_path):
    # No swap_detection key at all — agent never wrote it
    wf = {"contamination_hold_threshold": 0.5, "swap_hold_threshold": 0.25, "delta_check_sd_threshold": 3.0}
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, wf), KG_PATH)
    g_p = next(p for p in ep["parameters"] if "Glucose" in p["param"])
    assert g_p["verdict"] == "missing"
    assert ep["overall_verdict"] == "FAIL"


# ── Output structure ──────────────────────────────────────────────────────────

def test_output_contains_all_four_params(tmp_path):
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, _full_pass_workflow()), KG_PATH)
    assert len(ep["parameters"]) == 4


def test_evidence_pack_includes_kg_version(tmp_path):
    ep = provenance_verifier.verify_provenance(_write_workflow(tmp_path, _full_pass_workflow()), KG_PATH)
    assert ep["kg_version"] == "CLSI_EP33_2023_v1"
