"""
run_validation.py — Harness orchestrator.

Phase 1 (seed):
  - Reads scenarios.csv
  - Creates and advances all specimens directly via lims_db
  - Generates agent/task_prompt_filled.md from agent/task_prompt.md template

Phase 3 (evaluate):
  - Reads decisions from lims_db (independent observation — never calls server)
  - Checks KnowledgeQueried ordering in audit log
  - Runs provenance_verifier.verify_provenance()
  - Generates validation_report.md via report.generate_report()
  - Prints pass/fail summary to stdout

Coupling rules (IMPL_SPEC.md):
  - NEVER imports lims_server.py
  - lims_db imported directly for all DB reads
  - expected_outcomes.csv never served through any MCP tool
"""
import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

# Make server/ importable for lims_db and settings
_SERVER = Path(__file__).parent.parent / "server"
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

# Make harness/ importable for provenance_verifier and report
_HARNESS = Path(__file__).parent
if str(_HARNESS) not in sys.path:
    sys.path.insert(0, str(_HARNESS))

import lims_db
import provenance_verifier
import report
from settings import settings

_HARNESS_DIR = Path(__file__).parent
_AGENT_DIR   = Path(__file__).parent.parent / "agent"
_SCENARIOS   = _HARNESS_DIR / "scenarios.csv"
_EXPECTED    = _HARNESS_DIR / "expected_outcomes.csv"
_TASK_PROMPT        = _AGENT_DIR / "task_prompt.md"
_TASK_PROMPT_FILLED = _AGENT_DIR / "task_prompt_filled.md"

# Analyte columns — order matches scenarios.csv and triage.py expectations
_VALUE_COLS    = ["K", "Ca", "Na", "Cl", "HCO3", "Glucose"]
_PRIOR_ANALYTES = ["K", "Ca", "Na", "Cl", "HCO3", "Glucose"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_scenarios() -> list[dict]:
    with open(_SCENARIOS) as f:
        return list(csv.DictReader(f))


def _build_values(row: dict) -> dict:
    return {a: float(row[a]) for a in _VALUE_COLS}


def _build_patient_prior(row: dict) -> dict:
    return {
        "mean": {a: float(row[f"prior_{a}_mean"]) for a in _PRIOR_ANALYTES},
        "sd":   {a: float(row[f"prior_{a}_sd"])   for a in _PRIOR_ANALYTES},
    }


def _specimen_table_md(rows: list[dict]) -> str:
    """Markdown table — specimen values only, no label columns."""
    cols = ["specimen_id", "patient_id"] + _VALUE_COLS
    header = "| " + " | ".join(cols) + " |"
    sep    = "| " + " | ".join(["---"] * len(cols)) + " |"
    lines  = [header, sep]
    for row in rows:
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines)


def _icon(ok: bool) -> str:
    return "✅" if ok else "❌"


# ── Phase 1 — Seed ────────────────────────────────────────────────────────────

def phase_seed(session_id: str) -> None:
    lims_db.DB_PATH = settings.db_path
    lims_db.init_db()

    rows = _read_scenarios()
    created = skipped = 0

    print(f"Seeding {len(rows)} specimens for session {session_id!r}...")

    for row in rows:
        sid = row["specimen_id"]
        try:
            lims_db.create_specimen(
                sid,
                row["patient_id"],
                _build_values(row),
                _build_patient_prior(row),
            )
            lims_db.update_specimen_status(sid, "analyzed")
            created += 1
        except ValueError:
            print(f"  ⚠  {sid} already exists — skipping")
            skipped += 1

    print(f"  Created: {created}  Skipped: {skipped}")

    # Generate filled agent prompt
    if not _TASK_PROMPT.exists():
        print(f"  ⚠  {_TASK_PROMPT} not found — skipping task_prompt_filled.md")
        return

    template = _TASK_PROMPT.read_text()
    filled = (template
              .replace("{SESSION_ID}", session_id)
              .replace("{SPECIMEN_TABLE}", _specimen_table_md(rows)))
    _AGENT_DIR.mkdir(parents=True, exist_ok=True)
    _TASK_PROMPT_FILLED.write_text(filled)
    print(f"  Agent prompt → {_TASK_PROMPT_FILLED}")


# ── Phase 3 — Evaluate ────────────────────────────────────────────────────────

def phase_evaluate(
    session_id: str,
    workflow_path: str | None,
    output_path: str,
    agent_model: str = "unknown",
) -> None:
    lims_db.DB_PATH = settings.db_path
    lims_db.init_db()

    # ── Audit log ordering check ──────────────────────────────────────────────
    audit_log = lims_db.get_audit_log(session_id)
    tools     = [e["tool"] for e in audit_log]

    kg_first    = next((i for i, t in enumerate(tools) if t == "KnowledgeQueried"), None)
    autov_first = next((i for i, t in enumerate(tools) if t == "AutoverificationApplied"), None)

    if kg_first is not None and autov_first is not None:
        ordering_ok = kg_first < autov_first
    elif kg_first is not None:
        ordering_ok = True
        print("  ⚠  No AutoverificationApplied events found in audit log")
    else:
        ordering_ok = False
        print("  ⚠  KnowledgeQueried not found — provenance order cannot be verified")

    # ── Decisions + expected outcomes ─────────────────────────────────────────
    decisions = lims_db.get_all_decisions()

    with open(_EXPECTED) as f:
        expected_outcomes = list(csv.DictReader(f))

    # ── Provenance verification ───────────────────────────────────────────────
    kg_path = settings.kg_path

    if workflow_path and Path(workflow_path).exists():
        evidence_pack = provenance_verifier.verify_provenance(workflow_path, kg_path)
    else:
        msg = workflow_path or "no --workflow provided"
        print(f"  ⚠  workflow.json not found ({msg}) — provenance verdict = FAIL")
        evidence_pack = {
            "overall_verdict": "FAIL",
            "kg_version": "unknown",
            "parameters": [],
        }

    # ── KG version for report ─────────────────────────────────────────────────
    try:
        kg_version = json.loads(Path(kg_path).read_text()).get(
            "graph_version", evidence_pack.get("kg_version", "unknown")
        )
    except Exception:
        kg_version = evidence_pack.get("kg_version", "unknown")

    # ── Generate report ───────────────────────────────────────────────────────
    metrics = report.generate_report(
        run_date=date.today().isoformat(),
        agent_model=agent_model,
        kg_version=kg_version,
        scenario_set="contamination_swap_v1",
        decisions=decisions,
        expected_outcomes=expected_outcomes,
        evidence_pack=evidence_pack,
        audit_log=audit_log,
        output_path=output_path,
    )

    # ── Stdout summary ────────────────────────────────────────────────────────
    l1_pass = (
        metrics["unsafe_release_count"] == 0
        and metrics["f1"] >= 0.80
        and metrics["false_hold_rate"] <= 0.34
    )
    l2_pass = evidence_pack["overall_verdict"] == "PASS"

    print("\n=== Validation Summary ===")
    print("Layer 1 — Decision Quality:")
    print(f"  F1:               {metrics['f1']:.2f}  {_icon(metrics['f1'] >= 0.80)}")
    print(f"  Unsafe releases:  {metrics['unsafe_release_count']}     "
          f"{_icon(metrics['unsafe_release_count'] == 0)}")
    print(f"  False hold rate:  {metrics['false_hold_rate']:.2f}  "
          f"{_icon(metrics['false_hold_rate'] <= 0.34)}")
    print(f"  Audit order:      {_icon(ordering_ok)}")
    print(f"  Overall: {'PASS' if l1_pass else 'FAIL'}")

    print("\nLayer 2 — Reasoning Provenance:")
    for p in evidence_pack["parameters"]:
        print(f"  {p.get('display_name', p['param'])}: "
              f"{p['agent_value']} (expected {p['expected_value']}) "
              f"→ {p['verdict']} {_icon(p['verdict'] == 'graph-derived')}")
    print(f"  Overall: {evidence_pack['overall_verdict']}")

    final = "PASS" if (l1_pass and l2_pass) else "FAIL"
    print(f"\nFINAL RESULT: {final} {_icon(final == 'PASS')}")
    print(f"Report written to: {output_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="LIS MCP Validation Harness")
    parser.add_argument("--phase",      required=True, choices=["seed", "evaluate"])
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--workflow",   default=None,
                        help="Path to agent workflow.json (evaluate only)")
    parser.add_argument("--out",        default="validation_report.md")
    parser.add_argument("--model",      default="unknown",
                        help="Agent model name for report")
    args = parser.parse_args()

    if args.phase == "seed":
        phase_seed(args.session_id)
    elif args.phase == "evaluate":
        phase_evaluate(
            session_id=args.session_id,
            workflow_path=args.workflow,
            output_path=args.out,
            agent_model=args.model,
        )


if __name__ == "__main__":
    main()
