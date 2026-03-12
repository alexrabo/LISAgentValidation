# Task 04 — Provenance Verifier
**Output file:** `demo/harness/provenance_verifier.py`  
**Depends on:** nothing (standalone)  
**Global constraints:** see `IMPL_SPEC.md`

---

## Purpose
Layer 2 validation. Given the agent's workflow.json and clinical_knowledge.json, verify
that the agent derived its thresholds from the knowledge graph — not from fitting specimen
data. Produces the Evidence Pack parameter table.

This is what separates knowledge-grounded reasoning from data-fitting.
If the agent reads the graph but writes wrong values, this catches it.

---

## Interface

```python
def verify_provenance(
    workflow_json_path: str,
    knowledge_json_path: str,
) -> dict:
    """
    Compare agent workflow.json params against knowledge graph expected values.
    Returns Evidence Pack dict.
    """
```

---

## Expected Parameters (hardcoded mapping)

```python
# (workflow_param, kg_node, kg_field, tolerance)
EXPECTED_PARAMS = [
    ("contamination_hold_threshold", "decision_rules", "contamination_hold_threshold", 0.05),
    ("swap_hold_threshold",          "decision_rules", "swap_hold_threshold",          0.05),
    ("zscore_threshold",             "K_acute_rise",   "threshold_SD",                 0.2),
]
```

For each entry: extract `workflow_params[workflow_param]` and compare to
`knowledge_graph["nodes"][kg_node][kg_field]` (or top-level if node is missing).

Tolerance: `abs(agent_value - expected_value) <= tolerance` → graph-derived.
Otherwise → data-fitted.

---

## Output Format (Evidence Pack)

```python
{
    "overall_verdict": "PASS",   # PASS if ALL params are graph-derived, FAIL otherwise
    "kg_version": "CLSI_EP33_2023_v1",
    "parameters": [
        {
            "param": "contamination_hold_threshold",
            "agent_value": 0.5,
            "kg_node": "decision_rules",
            "kg_field": "contamination_hold_threshold",
            "expected_value": 0.5,
            "within_tolerance": True,
            "verdict": "graph-derived"     # or "data-fitted" or "missing"
        },
        ...
    ]
}
```

---

## CLI Usage

```bash
python3 provenance_verifier.py \
  --workflow /path/to/workflow.json \
  --kg /path/to/clinical_knowledge.json \
  --out /path/to/evidence_pack.json
```

Prints summary to stdout:
```
Provenance check:
  contamination_hold_threshold: 0.5 (expected 0.5) → graph-derived ✅
  swap_hold_threshold: 0.25 (expected 0.25) → graph-derived ✅
  zscore_threshold: 3.0 (expected 3.0) → graph-derived ✅

Overall verdict: PASS
```

---

## Acceptance Criteria

```bash
cd demo/harness

# Test with a correct workflow.json
python3 -c "
import json
wf = {
    'contamination_hold_threshold': 0.5,
    'swap_hold_threshold': 0.25,
    'zscore_threshold': 3.0,
    'decision_policy': {'contamination_hold_threshold': 0.5, 'swap_hold_threshold': 0.25}
}
with open('/tmp/test_workflow.json', 'w') as f: json.dump(wf, f)
"

python3 provenance_verifier.py \
  --workflow /tmp/test_workflow.json \
  --kg ../../lis-swap-contamination-triage/environment/data/clinical_knowledge.json \
  --out /tmp/evidence_pack.json

python3 -c "
import json
ep = json.load(open('/tmp/evidence_pack.json'))
assert ep['overall_verdict'] == 'PASS', f'Expected PASS, got {ep[\"overall_verdict\"]}'
assert all(p['verdict'] == 'graph-derived' for p in ep['parameters'])
print('PASS')
"

# Test with a data-fitted workflow.json (wrong values)
python3 -c "
import json
wf = {'contamination_hold_threshold': 0.3, 'swap_hold_threshold': 0.1, 'zscore_threshold': 1.5}
with open('/tmp/bad_workflow.json', 'w') as f: json.dump(wf, f)
"
python3 provenance_verifier.py --workflow /tmp/bad_workflow.json \
  --kg ../../lis-swap-contamination-triage/environment/data/clinical_knowledge.json \
  --out /tmp/ep_bad.json
python3 -c "
import json
ep = json.load(open('/tmp/ep_bad.json'))
assert ep['overall_verdict'] == 'FAIL'
print('FAIL case correctly detected — PASS')
"
```
