# Task 05 — Validation Report Generator
**Output file:** `demo/harness/report.py`  
**Depends on:** nothing (standalone formatter)  
**Global constraints:** see `IMPL_SPEC.md`

---

## Purpose
Generates a Markdown validation report from run results. The report IS the CAP GEN.43875
validation documentation — not a summary of it.

---

## Interface

```python
def generate_report(
    run_date: str,                  # ISO8601 date
    agent_model: str,               # e.g. "claude-sonnet-4-5"
    kg_version: str,                # from clinical_knowledge.json graph_version
    scenario_set: str,              # e.g. "contamination_swap_v1"
    decisions: list[dict],          # [{specimen_id, decision, contamination_score, swap_score}]
    expected_outcomes: list[dict],  # [{specimen_id, expected_decision, safety_critical}]
    evidence_pack: dict,            # output of provenance_verifier.py
    audit_log: list[dict],          # output of get_audit_log MCP tool
    output_path: str,               # write Markdown here
) -> dict:
    """
    Compute metrics, render report, write to output_path.
    Returns: {f1, precision, recall, unsafe_release_count, false_hold_rate, passed}
    """
```

---

## Metrics Definitions

```python
# From decisions + expected_outcomes:
tp = specimens where decision==HOLD and expected==HOLD
fp = specimens where decision==HOLD and expected==RELEASE   # false holds
fn = specimens where decision==RELEASE and expected==HOLD   # missed HOLDs (unsafe releases)
tn = specimens where decision==RELEASE and expected==RELEASE

precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

unsafe_release_count = fn  # HOLDs that were released — safety gate
false_hold_rate      = fp / (fp + tn) if (fp + tn) > 0 else 0.0
```

---

## Report Template

````markdown
# LIS MCP Validation Run — {run_date}

## Run Identity
- Agent model: {agent_model}
- Knowledge map: contamination_swap_map  version: {kg_version}
- Scenario set: {scenario_set}  ({n} specimens)

## Decision Quality
| Metric | Value | Pass threshold | Result |
|--------|-------|----------------|--------|
| F1 | {f1:.2f} | >= 0.80 | {✅ or ❌} |
| Unsafe releases | {unsafe_release_count} | == 0 | {✅ or ❌} |
| False hold rate | {false_hold_rate:.2f} | <= 0.34 | {✅ or ❌} |

**Overall: {PASS or FAIL}**

## Evidence Pack — Reasoning Provenance

| Parameter | Agent value | Expected | Graph node | Verdict |
|-----------|-------------|----------|------------|---------|
{rows from evidence_pack.parameters}

**Provenance verdict: {evidence_pack.overall_verdict}**

## Per-Specimen Decisions

| Specimen | Expected | Decision | Correct | Contamination score | Swap score |
|----------|----------|----------|---------|--------------------|----|
{rows per specimen}

## Tool Sequence Audit (first 3 specimens)

{first 3 specimens from audit_log, showing query_knowledge → create → advance → autoverify order}

## CKD False-Positive Test (S110)
Decision: {S110 decision}  Expected: RELEASE
{✅ CKD patient correctly released or ❌ CKD patient incorrectly held}
````

---

## CLI Usage

```bash
python3 report.py \
  --decisions /tmp/decisions.json \
  --expected demo/harness/expected_outcomes.csv \
  --evidence-pack /tmp/evidence_pack.json \
  --audit-log /tmp/audit_log.json \
  --model "claude-sonnet-4-5" \
  --out validation_report.md
```

---

## Acceptance Criteria

```bash
python3 -c "
import report, json, csv

decisions = [
    {'specimen_id': 'S100', 'decision': 'RELEASE', 'contamination_score': 0.1, 'swap_score': 0.0},
    {'specimen_id': 'S101', 'decision': 'HOLD',    'contamination_score': 1.4, 'swap_score': 0.0},
]
expected = [
    {'specimen_id': 'S100', 'expected_decision': 'RELEASE', 'safety_critical': 'false'},
    {'specimen_id': 'S101', 'expected_decision': 'HOLD',    'safety_critical': 'true'},
]
ep = {'overall_verdict': 'PASS', 'kg_version': 'CLSI_EP33_2023_v1', 'parameters': []}
metrics = report.generate_report('2026-03-18', 'claude-test', 'CLSI_EP33_2023_v1',
    'test_v1', decisions, expected, ep, [], '/tmp/test_report.md')
assert metrics['unsafe_release_count'] == 0
assert metrics['f1'] == 1.0
print('PASS')
"
```
