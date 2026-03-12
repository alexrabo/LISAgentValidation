"""
Provenance Verifier — Layer 2 validation.

Given the agent's workflow.json and clinical_knowledge.json, verifies that
thresholds were derived from the knowledge graph, not fitted to specimen data.

This is the separation between knowledge-grounded reasoning and data-fitting.
Imports nothing from demo/server/ — zero coupling to the live server.
"""
import argparse
import json


# (workflow_param, kg_node, kg_field, tolerance, display_name)
# workflow_param is the key the agent writes in workflow.json / WorkflowParams MCP field.
# display_name is the lab-standard term shown in reports and UI.
# Note: delta_check_sd_threshold maps to triage.py's internal key zscore_threshold —
# see _build_workflow() in apply_autoverification.py for the explicit mapping.
EXPECTED_PARAMS = [
    ("contamination_hold_threshold", "decision_policy", "contamination_hold_threshold", 0.05,
     "Contamination Hold Threshold"),
    ("swap_hold_threshold",          "decision_policy", "swap_hold_threshold",          0.05,
     "Identity Swap Hold Threshold"),
    ("delta_check_sd_threshold",     "K_acute_rise",    "threshold_SD",                 0.20,
     "Delta Check Divisor (SD)"),    # CLSI EP33 Section 4.3 Table 2
]


def verify_provenance(workflow_json_path: str, knowledge_json_path: str) -> dict:
    """
    Compare agent workflow.json params against knowledge graph expected values.
    Returns Evidence Pack dict.
    """
    with open(workflow_json_path) as f:
        workflow = json.load(f)
    with open(knowledge_json_path) as f:
        kg = json.load(f)

    parameters = []
    all_graph_derived = True

    for workflow_param, kg_node, kg_field, tolerance, display_name in EXPECTED_PARAMS:
        expected_value = kg["nodes"][kg_node][kg_field]

        if workflow_param not in workflow:
            all_graph_derived = False
            parameters.append({
                "param": workflow_param,
                "display_name": display_name,
                "agent_value": None,
                "kg_node": kg_node,
                "kg_field": kg_field,
                "expected_value": expected_value,
                "within_tolerance": False,
                "verdict": "missing",
            })
            continue

        agent_value = workflow[workflow_param]
        within = abs(agent_value - expected_value) <= tolerance
        verdict = "graph-derived" if within else "data-fitted"
        if not within:
            all_graph_derived = False

        parameters.append({
            "param": workflow_param,
            "display_name": display_name,
            "agent_value": agent_value,
            "kg_node": kg_node,
            "kg_field": kg_field,
            "expected_value": expected_value,
            "within_tolerance": within,
            "verdict": verdict,
        })

    return {
        "overall_verdict": "PASS" if all_graph_derived else "FAIL",
        "kg_version": kg.get("graph_version", "unknown"),
        "parameters": parameters,
    }


def _print_summary(evidence_pack: dict) -> None:
    print("Provenance check:")
    for p in evidence_pack["parameters"]:
        icon = "✅" if p["verdict"] == "graph-derived" else "❌"
        agent_val = p["agent_value"] if p["agent_value"] is not None else "MISSING"
        print(f"  {p['display_name']}: {agent_val} (expected {p['expected_value']}) "
              f"→ {p['verdict']} {icon}")
    print(f"\nOverall verdict: {evidence_pack['overall_verdict']}")


def main():
    parser = argparse.ArgumentParser(description="Verify workflow.json provenance against KG")
    parser.add_argument("--workflow", required=True, help="Path to agent workflow.json")
    parser.add_argument("--kg", required=True, help="Path to clinical_knowledge.json")
    parser.add_argument("--out", required=True, help="Path to write evidence_pack.json")
    args = parser.parse_args()

    evidence_pack = verify_provenance(args.workflow, args.kg)
    _print_summary(evidence_pack)

    with open(args.out, "w") as f:
        json.dump(evidence_pack, f, indent=2)
    print(f"\nEvidence pack written to {args.out}")


if __name__ == "__main__":
    main()
