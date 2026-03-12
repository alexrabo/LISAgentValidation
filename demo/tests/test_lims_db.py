"""
Tests for demo/server/lims_db.py
Each test uses a fresh tmp_path-scoped SQLite DB via monkeypatched DB_PATH.
"""
import json
import hashlib
import sys
from pathlib import Path

import pytest

# Make server/ importable
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))
import lims_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point DB_PATH at a fresh temp file for every test."""
    db_file = str(tmp_path / "test_lims.db")
    monkeypatch.setattr(lims_db, "DB_PATH", db_file)
    lims_db.init_db()


# ── init ─────────────────────────────────────────────────────────────────────

def test_init_creates_tables(tmp_path, monkeypatch):
    import sqlite3
    db_file = str(tmp_path / "init_check.db")
    monkeypatch.setattr(lims_db, "DB_PATH", db_file)
    lims_db.init_db()

    conn = sqlite3.connect(db_file)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "specimens" in tables
    assert "audit_log" in tables
    conn.close()


# ── create_specimen ───────────────────────────────────────────────────────────

def test_create_specimen_returns_correct_fields():
    r = lims_db.create_specimen("S001", "P001", {"K": 4.1, "Ca": 9.4}, {"mean": {}, "sd": {}})
    assert r["specimen_id"] == "S001"
    assert r["status"] == "created"
    assert "snapshot_hash" in r
    assert "created_at" in r


def test_create_specimen_computes_sha256_correctly():
    values = {"K": 4.1, "Ca": 9.4}
    r = lims_db.create_specimen("S002", "P002", values, {})
    expected_hash = hashlib.sha256(
        json.dumps(values, sort_keys=True).encode()
    ).hexdigest()
    assert r["snapshot_hash"] == expected_hash


def test_create_specimen_raises_on_duplicate():
    lims_db.create_specimen("S003", "P003", {"K": 5.0}, {})
    with pytest.raises(ValueError, match="already exists"):
        lims_db.create_specimen("S003", "P003", {"K": 5.0}, {})


# ── get_specimen ──────────────────────────────────────────────────────────────

def test_get_specimen_returns_none_for_unknown():
    assert lims_db.get_specimen("DOES_NOT_EXIST") is None


def test_get_specimen_returns_full_row():
    lims_db.create_specimen("S004", "P004", {"K": 4.0}, {"mean": {"K": 4.0}, "sd": {"K": 0.3}})
    row = lims_db.get_specimen("S004")
    assert row is not None
    assert row["specimen_id"] == "S004"
    assert row["patient_id"] == "P004"
    assert row["status"] == "created"
    assert json.loads(row["values_json"]) == {"K": 4.0}


# ── update_specimen_status ────────────────────────────────────────────────────

def test_update_status_valid_transitions():
    lims_db.create_specimen("S005", "P005", {"K": 4.0}, {})
    r1 = lims_db.update_specimen_status("S005", "analyzed")
    assert r1 == {"specimen_id": "S005", "previous_status": "created", "new_status": "analyzed"}

    r2 = lims_db.update_specimen_status("S005", "pending_review")
    assert r2 == {
        "specimen_id": "S005",
        "previous_status": "analyzed",
        "new_status": "pending_review",
    }


def test_update_status_raises_on_illegal_transition():
    lims_db.create_specimen("S006", "P006", {"K": 4.0}, {})
    with pytest.raises(ValueError, match="Illegal status transition"):
        lims_db.update_specimen_status("S006", "pending_review")  # skip analyzed


def test_update_status_raises_on_unknown_specimen():
    with pytest.raises(ValueError, match="Unknown specimen_id"):
        lims_db.update_specimen_status("GHOST", "analyzed")


# ── record_decision ───────────────────────────────────────────────────────────

def test_record_decision_does_not_change_values_json():
    lims_db.create_specimen("S007", "P007", {"K": 6.9, "Ca": 7.1}, {})
    original = lims_db.get_specimen("S007")["values_json"]

    lims_db.record_decision("S007", "HOLD", 1.4, 0.0, {"contamination_hold_threshold": 0.5})

    after = lims_db.get_specimen("S007")
    assert after["values_json"] == original
    assert after["decision"] == "HOLD"
    assert after["contamination_score"] == pytest.approx(1.4)
    assert after["swap_score"] == pytest.approx(0.0)


# ── log_tool_call ─────────────────────────────────────────────────────────────

def test_log_tool_call_appends():
    lims_db.log_tool_call("sess1", "query_knowledge", {"map_id": "test"}, {"ok": True})
    lims_db.log_tool_call("sess1", "get_audit_log", {}, [])
    rows = lims_db.get_audit_log("sess1")
    assert len(rows) == 2
    assert rows[0]["tool"] == "query_knowledge"
    assert rows[1]["tool"] == "get_audit_log"


# ── get_audit_log ─────────────────────────────────────────────────────────────

def test_get_audit_log_ordered_by_id():
    for i in range(5):
        lims_db.log_tool_call("sess2", f"tool_{i}", {"i": i}, {})
    rows = lims_db.get_audit_log("sess2")
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids)


def test_get_audit_log_filters_by_specimen_id():
    lims_db.log_tool_call("sess3", "apply_autoverification", {"specimen_id": "S100"}, {})
    lims_db.log_tool_call("sess3", "apply_autoverification", {"specimen_id": "S101"}, {})
    lims_db.log_tool_call("sess3", "query_knowledge", {"map_id": "test"}, {})

    rows = lims_db.get_audit_log("sess3", specimen_id="S100")
    assert len(rows) == 1
    assert rows[0]["args"]["specimen_id"] == "S100"


def test_get_audit_log_separate_sessions():
    lims_db.log_tool_call("sessA", "query_knowledge", {}, {})
    lims_db.log_tool_call("sessB", "create_sample", {}, {})
    assert len(lims_db.get_audit_log("sessA")) == 1
    assert len(lims_db.get_audit_log("sessB")) == 1


# ── query_knowledge_was_called ────────────────────────────────────────────────

def test_query_knowledge_was_called_true():
    lims_db.log_tool_call("sess4", "query_knowledge", {"map_id": "test"}, {"ok": True})
    assert lims_db.query_knowledge_was_called("sess4") is True


def test_query_knowledge_was_called_false_for_unknown_session():
    assert lims_db.query_knowledge_was_called("no-such-session") is False


def test_query_knowledge_was_called_false_when_other_tools_called():
    lims_db.log_tool_call("sess5", "create_sample", {}, {})
    assert lims_db.query_knowledge_was_called("sess5") is False


# ── get_all_decisions ─────────────────────────────────────────────────────────

def test_get_all_decisions():
    lims_db.create_specimen("S010", "P010", {"K": 4.0}, {})
    lims_db.create_specimen("S011", "P011", {"K": 6.9}, {})
    lims_db.record_decision("S010", "RELEASE", 0.1, 0.0, {})
    lims_db.record_decision("S011", "HOLD", 1.4, 0.0, {})

    decisions = lims_db.get_all_decisions()
    by_id = {d["specimen_id"]: d for d in decisions}
    assert by_id["S010"]["decision"] == "RELEASE"
    assert by_id["S011"]["decision"] == "HOLD"


def test_get_all_decisions_includes_undecided():
    lims_db.create_specimen("S012", "P012", {"K": 4.0}, {})
    decisions = lims_db.get_all_decisions()
    ids = [d["specimen_id"] for d in decisions]
    assert "S012" in ids
    undecided = next(d for d in decisions if d["specimen_id"] == "S012")
    assert undecided["decision"] is None
