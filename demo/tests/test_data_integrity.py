"""
Data integrity guards for scenarios.csv and expected_outcomes.csv.

These tests do NOT verify scoring logic — they guard against accidental
edits to ground truth data: wrong HOLD/RELEASE labels, ground truth
leakage into the agent-visible file, broken swap pairs, missing columns.

Scoring correctness is tested in the end-to-end run (Task 06).

Run from demo/ with: uv run pytest tests/test_data_integrity.py
"""
import csv
from pathlib import Path

HARNESS = Path(__file__).parent.parent / "harness"
SCENARIOS_PATH = HARNESS / "scenarios.csv"
EXPECTED_PATH = HARNESS / "expected_outcomes.csv"

SPECIMEN_IDS = {f"S{i}" for i in range(100, 111)}
CONTAMINATION_IDS = {"S101", "S107"}
SWAP_IDS = {"S105", "S106"}
NORMAL_IDS = {"S100", "S102", "S103", "S104", "S108", "S109"}
CKD_IDS = {"S110"}


def _load_scenarios() -> list[dict]:
    with open(SCENARIOS_PATH) as f:
        return list(csv.DictReader(f))


def _load_outcomes() -> dict[str, dict]:
    with open(EXPECTED_PATH) as f:
        return {r["specimen_id"]: r for r in csv.DictReader(f)}


def test_scenarios_has_11_rows():
    assert len(_load_scenarios()) == 11


def test_all_specimen_ids_present():
    ids = {r["specimen_id"] for r in _load_scenarios()}
    assert ids == SPECIMEN_IDS


def test_expected_outcomes_has_11_rows():
    assert len(_load_outcomes()) == 11


def test_ckd_specimen_is_release():
    outcomes = _load_outcomes()
    assert outcomes["S110"]["expected_decision"] == "RELEASE", (
        "S110 (CKD) must be RELEASE — elevated K is chronic, not EDTA artifact"
    )


def test_contamination_specimens_are_safety_critical():
    outcomes = _load_outcomes()
    for sid in CONTAMINATION_IDS:
        assert outcomes[sid]["safety_critical"] == "true", (
            f"{sid} (CONTAMINATION) must be safety_critical=true"
        )
        assert outcomes[sid]["expected_decision"] == "HOLD", (
            f"{sid} (CONTAMINATION) must be HOLD"
        )


def test_swap_specimens_are_hold():
    outcomes = _load_outcomes()
    for sid in SWAP_IDS:
        assert outcomes[sid]["expected_decision"] == "HOLD", (
            f"{sid} (SWAP) must be HOLD"
        )
        assert outcomes[sid]["safety_critical"] == "true", (
            f"{sid} (SWAP) must be safety_critical=true"
        )


def test_normal_specimens_are_release():
    outcomes = _load_outcomes()
    for sid in NORMAL_IDS:
        assert outcomes[sid]["expected_decision"] == "RELEASE", (
            f"{sid} (NORMAL) must be RELEASE"
        )
        assert outcomes[sid]["safety_critical"] == "false", (
            f"{sid} (NORMAL) must be safety_critical=false"
        )


def test_scenario_types_match_between_files():
    scenarios = {r["specimen_id"]: r["scenario_type"] for r in _load_scenarios()}
    outcomes = _load_outcomes()
    for sid, stype in scenarios.items():
        assert outcomes[sid]["scenario_type"] == stype, (
            f"{sid}: scenario_type mismatch — scenarios.csv={stype}, "
            f"expected_outcomes.csv={outcomes[sid]['scenario_type']}"
        )


def test_no_expected_decision_column_in_scenarios():
    rows = _load_scenarios()
    assert rows, "scenarios.csv is empty"
    assert "expected_decision" not in rows[0], (
        "scenarios.csv must NOT contain expected_decision — agent must not see ground truth"
    )


def test_swap_pair_consistency():
    """S105 and S106 must both be HOLD — they are a matched swap pair."""
    outcomes = _load_outcomes()
    assert outcomes["S105"]["expected_decision"] == "HOLD"
    assert outcomes["S106"]["expected_decision"] == "HOLD"
    assert outcomes["S105"]["scenario_type"] == "SWAP"
    assert outcomes["S106"]["scenario_type"] == "SWAP"


def test_all_required_columns_present_in_scenarios():
    rows = _load_scenarios()
    required = {
        "specimen_id", "patient_id", "scenario_type",
        "K", "Ca", "Na", "Cl", "HCO3", "Glucose",
        "prior_K_mean", "prior_K_sd", "prior_Ca_mean", "prior_Ca_sd",
    }
    assert required.issubset(rows[0].keys()), (
        f"Missing columns: {required - rows[0].keys()}"
    )


def test_all_required_columns_present_in_expected_outcomes():
    outcomes = _load_outcomes()
    first = next(iter(outcomes.values()))
    required = {"specimen_id", "expected_decision", "safety_critical", "scenario_type"}
    assert required.issubset(first.keys()), (
        f"Missing columns: {required - first.keys()}"
    )
