"""Tests for demo/harness/run_validation.py"""
import csv
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SERVER  = Path(__file__).parent.parent / "server"
_HARNESS = Path(__file__).parent.parent / "harness"
for p in [str(_SERVER), str(_HARNESS)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import lims_db
import run_validation
from run_validation import phase_seed, phase_evaluate


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_rv.db")
    monkeypatch.setattr(lims_db, "DB_PATH", db_file)
    import settings as s
    monkeypatch.setattr(s.settings, "db_path", db_file)
    lims_db.init_db()


@pytest.fixture()
def mock_scenarios(tmp_path, monkeypatch):
    """Write a minimal scenarios.csv and patch the path."""
    rows = [
        {"specimen_id": "S100", "patient_id": "P001", "scenario_type": "NORMAL",
         "K": "4.15", "Ca": "9.42", "Na": "140.3", "Cl": "103.2",
         "HCO3": "24.1", "Glucose": "94",
         "prior_K_mean": "4.1", "prior_K_sd": "0.25",
         "prior_Ca_mean": "9.4", "prior_Ca_sd": "0.35",
         "prior_Na_mean": "140", "prior_Na_sd": "2.5",
         "prior_Cl_mean": "103", "prior_Cl_sd": "2.0",
         "prior_HCO3_mean": "24", "prior_HCO3_sd": "2.0",
         "prior_Glucose_mean": "92", "prior_Glucose_sd": "12"},
        {"specimen_id": "S101", "patient_id": "P002", "scenario_type": "CONTAMINATION",
         "K": "6.9", "Ca": "7.1", "Na": "137.5", "Cl": "100.8",
         "HCO3": "21.8", "Glucose": "112",
         "prior_K_mean": "4.1", "prior_K_sd": "0.25",
         "prior_Ca_mean": "9.4", "prior_Ca_sd": "0.35",
         "prior_Na_mean": "140", "prior_Na_sd": "2.5",
         "prior_Cl_mean": "103", "prior_Cl_sd": "2.0",
         "prior_HCO3_mean": "24", "prior_HCO3_sd": "2.0",
         "prior_Glucose_mean": "92", "prior_Glucose_sd": "12"},
    ]
    csv_file = tmp_path / "scenarios.csv"
    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(run_validation, "_SCENARIOS", csv_file)
    return rows


@pytest.fixture()
def mock_expected(tmp_path, monkeypatch):
    rows = [
        {"specimen_id": "S100", "expected_decision": "RELEASE",
         "safety_critical": "false", "scenario_type": "NORMAL", "notes": ""},
        {"specimen_id": "S101", "expected_decision": "HOLD",
         "safety_critical": "true", "scenario_type": "CONTAMINATION", "notes": ""},
    ]
    csv_file = tmp_path / "expected_outcomes.csv"
    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(run_validation, "_EXPECTED", csv_file)
    return rows


@pytest.fixture()
def agent_dir(tmp_path, monkeypatch):
    ad = tmp_path / "agent"
    ad.mkdir()
    monkeypatch.setattr(run_validation, "_AGENT_DIR", ad)
    monkeypatch.setattr(run_validation, "_TASK_PROMPT", ad / "task_prompt.md")
    monkeypatch.setattr(run_validation, "_TASK_PROMPT_FILLED", ad / "task_prompt_filled.md")
    return ad


# ── Phase seed ────────────────────────────────────────────────────────────────

def test_seed_creates_and_advances_all_specimens(mock_scenarios, agent_dir):
    phase_seed("sess-seed")
    decisions = lims_db.get_all_decisions()
    ids = {d["specimen_id"] for d in decisions}
    assert "S100" in ids
    assert "S101" in ids
    # Verify status was advanced to analyzed
    s100 = lims_db.get_specimen("S100")
    assert s100["status"] == "analyzed"


def test_seed_skips_duplicate_without_failing(mock_scenarios, agent_dir):
    phase_seed("sess-dup")
    # Second seed should not raise
    phase_seed("sess-dup")
    decisions = lims_db.get_all_decisions()
    assert len([d for d in decisions if d["specimen_id"] == "S100"]) == 1


def test_seed_generates_task_prompt_filled(mock_scenarios, agent_dir):
    (agent_dir / "task_prompt.md").write_text(
        "Session: {SESSION_ID}\n{SPECIMEN_TABLE}"
    )
    phase_seed("run-001")
    filled = (agent_dir / "task_prompt_filled.md").read_text()
    assert "run-001" in filled
    assert "{SESSION_ID}" not in filled
    assert "{SPECIMEN_TABLE}" not in filled


def test_task_prompt_filled_contains_no_ground_truth_labels(mock_scenarios, agent_dir):
    (agent_dir / "task_prompt.md").write_text(
        "Session: {SESSION_ID}\n{SPECIMEN_TABLE}"
    )
    phase_seed("run-002")
    filled = (agent_dir / "task_prompt_filled.md").read_text()
    assert "NORMAL" not in filled
    assert "CONTAMINATION" not in filled
    assert "SWAP" not in filled
    assert "expected_decision" not in filled


def test_task_prompt_filled_contains_session_id(mock_scenarios, agent_dir):
    (agent_dir / "task_prompt.md").write_text("{SESSION_ID}")
    phase_seed("my-session-99")
    filled = (agent_dir / "task_prompt_filled.md").read_text()
    assert "my-session-99" in filled


# ── Phase evaluate ────────────────────────────────────────────────────────────

def test_evaluate_handles_missing_workflow_json(
    mock_scenarios, mock_expected, agent_dir, tmp_path
):
    phase_seed("sess-eval")
    lims_db.record_decision("S100", "RELEASE", 0.0, 0.0, {})
    lims_db.record_decision("S101", "HOLD",    1.4, 0.0, {})

    out = str(tmp_path / "report.md")
    phase_evaluate("sess-eval", "/nonexistent/workflow.json", out)
    text = Path(out).read_text()
    assert "Unsafe releases" in text


def test_evaluate_handles_zero_autoverification_calls(
    mock_scenarios, mock_expected, agent_dir, tmp_path
):
    phase_seed("sess-zero")
    # No decisions recorded — 0 autoverification calls
    out = str(tmp_path / "report.md")
    phase_evaluate("sess-zero", None, out)
    assert Path(out).exists()


def test_evaluate_checks_query_knowledge_order(
    mock_scenarios, mock_expected, agent_dir, tmp_path, capsys
):
    phase_seed("sess-order")
    # Log in wrong order: autoverification before query_knowledge
    lims_db.log_tool_call("sess-order", "AutoverificationApplied", {}, {})
    lims_db.log_tool_call("sess-order", "KnowledgeQueried", {}, {})
    lims_db.record_decision("S100", "RELEASE", 0.0, 0.0, {})
    lims_db.record_decision("S101", "HOLD",    1.4, 0.0, {})

    out = str(tmp_path / "report.md")
    phase_evaluate("sess-order", None, out)
    captured = capsys.readouterr()
    # Ordering check icon should show failure
    assert "❌" in captured.out
