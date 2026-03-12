"""
Validation Report Generator — Layer 1 + Layer 2 combined output.

Generates the Markdown validation report from run results.
This report IS the CAP GEN.43875 validation documentation.
Imports nothing from demo/server/ — zero coupling to the live server.
"""
import argparse
import csv
import json
from pathlib import Path


def _compute_metrics(decisions: list[dict], expected_outcomes: list[dict]) -> dict:
    expected = {r["specimen_id"]: r["expected_decision"] for r in expected_outcomes}

    tp = fp = fn = tn = 0
    for d in decisions:
        sid = d["specimen_id"]
        decision = d.get("decision") or "RELEASE"
        exp = expected.get(sid, "RELEASE")
        if decision == "HOLD" and exp == "HOLD":
            tp += 1
        elif decision == "HOLD" and exp == "RELEASE":
            fp += 1
        elif decision == "RELEASE" and exp == "HOLD":
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)
    false_hold_rate = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    unsafe_release_count = fn
    passed = (unsafe_release_count == 0 and f1 >= 0.80 and false_hold_rate <= 0.34)

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "unsafe_release_count": unsafe_release_count,
        "false_hold_rate": false_hold_rate,
        "passed": passed,
    }


def _icon(condition: bool) -> str:
    return "✅" if condition else "❌"


def generate_report(
    run_date: str,
    agent_model: str,
    kg_version: str,
    scenario_set: str,
    decisions: list[dict],
    expected_outcomes: list[dict],
    evidence_pack: dict,
    audit_log: list[dict],
    output_path: str,
) -> dict:
    """Compute metrics, render report, write to output_path. Returns metrics dict."""
    m = _compute_metrics(decisions, expected_outcomes)
    n = len(decisions)

    # ── Decision Quality section ──────────────────────────────────────────────
    overall = "PASS" if m["passed"] else "FAIL"
    quality_rows = (
        f"| F1 | {m['f1']:.2f} | >= 0.80 | {_icon(m['f1'] >= 0.80)} |\n"
        f"| Unsafe releases | {m['unsafe_release_count']} | == 0 | {_icon(m['unsafe_release_count'] == 0)} |\n"
        f"| False hold rate | {m['false_hold_rate']:.2f} | <= 0.34 | {_icon(m['false_hold_rate'] <= 0.34)} |"
    )

    # ── Evidence Pack section ─────────────────────────────────────────────────
    params = evidence_pack.get("parameters", [])
    if params:
        ep_rows = "\n".join(
            f"| {p['param']} | {p['agent_value']} | {p['expected_value']} "
            f"| {p['kg_node']}.{p['kg_field']} | {p['verdict']} |"
            for p in params
        )
    else:
        ep_rows = "| — | — | — | — | No evidence pack data |"

    prov_verdict = evidence_pack.get("overall_verdict", "UNKNOWN")

    # ── Per-Specimen section ──────────────────────────────────────────────────
    exp_map = {r["specimen_id"]: r for r in expected_outcomes}
    dec_map = {d["specimen_id"]: d for d in decisions}

    specimen_rows = []
    for sid in sorted(set(list(exp_map.keys()) + list(dec_map.keys()))):
        d = dec_map.get(sid, {})
        e = exp_map.get(sid, {})
        decision = d.get("decision") or "—"
        expected = e.get("expected_decision", "—")
        correct = decision == expected
        c_score = d.get("contamination_score")
        s_score = d.get("swap_score")
        c_str = f"{c_score:.3f}" if c_score is not None else "—"
        s_str = f"{s_score:.3f}" if s_score is not None else "—"
        specimen_rows.append(
            f"| {sid} | {expected} | {decision} | {_icon(correct)} | {c_str} | {s_str} |"
        )
    specimen_table = "\n".join(specimen_rows)

    # ── Audit sequence section (first 3 entries) ──────────────────────────────
    if audit_log:
        audit_lines = "\n".join(
            f"  {i+1}. [{e.get('timestamp', '')}] {e.get('tool', '')}"
            for i, e in enumerate(audit_log[:3])
        )
    else:
        audit_lines = "  No audit log entries."

    # ── CKD section ───────────────────────────────────────────────────────────
    s110 = dec_map.get("S110", {})
    s110_decision = s110.get("decision", "not in decisions")
    ckd_ok = s110_decision == "RELEASE"
    ckd_line = (
        f"{_icon(ckd_ok)} CKD patient correctly released"
        if ckd_ok else
        f"{_icon(ckd_ok)} CKD patient incorrectly held (expected RELEASE)"
    )

    # ── Render ────────────────────────────────────────────────────────────────
    report = f"""# LIS MCP Validation Run — {run_date}

## Run Identity
- Agent model: {agent_model}
- Knowledge map: contamination_swap_map  version: {kg_version}
- Scenario set: {scenario_set}  ({n} specimens)

## Decision Quality
| Metric | Value | Pass threshold | Result |
|--------|-------|----------------|--------|
{quality_rows}

**Overall: {overall}**

## Evidence Pack — Reasoning Provenance

| Parameter | Agent value | Expected | Graph node | Verdict |
|-----------|-------------|----------|------------|---------|
{ep_rows}

**Provenance verdict: {prov_verdict}**

## Per-Specimen Decisions

| Specimen | Expected | Decision | Correct | Contamination score | Swap score |
|----------|----------|----------|---------|---------------------|------------|
{specimen_table}

## Tool Sequence Audit (first 3 entries)

{audit_lines}

## CKD False-Positive Test (S110)
Decision: {s110_decision}  Expected: RELEASE
{ckd_line}
"""

    Path(output_path).write_text(report)
    return {k: m[k] for k in
            ["f1", "precision", "recall", "unsafe_release_count", "false_hold_rate", "passed"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--evidence-pack", required=True)
    parser.add_argument("--audit-log", required=True)
    parser.add_argument("--model", default="unknown")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.decisions) as f:
        decisions = json.load(f)
    with open(args.expected) as f:
        expected_outcomes = list(csv.DictReader(f))
    with open(args.evidence_pack) as f:
        evidence_pack = json.load(f)
    with open(args.audit_log) as f:
        audit_log = json.load(f)

    metrics = generate_report(
        run_date=__import__("datetime").date.today().isoformat(),
        agent_model=args.model,
        kg_version=evidence_pack.get("kg_version", "unknown"),
        scenario_set="contamination_swap_v1",
        decisions=decisions,
        expected_outcomes=expected_outcomes,
        evidence_pack=evidence_pack,
        audit_log=audit_log,
        output_path=args.out,
    )
    print(f"Report written to {args.out}")
    print(f"F1: {metrics['f1']:.2f}  Unsafe releases: {metrics['unsafe_release_count']}  "
          f"Passed: {metrics['passed']}")


if __name__ == "__main__":
    main()
