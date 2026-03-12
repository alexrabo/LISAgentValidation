# Task 07 — Agent Task Prompt
**Output file:** `demo/agent/task_prompt.md`  
**Depends on:** Task 02 (server must be running to test)  
**Global constraints:** see `IMPL_SPEC.md`

---

## Purpose
The system prompt given to Claude (the agent under test). Must guide the agent to:
1. Call `query_knowledge` FIRST — before any other tool
2. Derive thresholds from the knowledge graph, not invent them
3. Write workflow.json with graph-derived thresholds
4. Process all 11 specimens in order
5. Call `get_audit_log` at the end

The prompt is a test instrument — it defines the task boundary.
It must NOT tell the agent what the correct thresholds are (that would defeat the test).
It must NOT show the agent the expected_outcomes.csv.

---

## task_prompt.md content to create:

````markdown
# LIS Autoverification Task

You are a laboratory informatics AI agent. Your task is to validate 11 specimens
for contamination and identity swap issues using a clinical knowledge graph and
a LIMS simulation server.

## Server
MCP LIMS Server: http://localhost:8000
Session ID: {SESSION_ID}  ← filled in at runtime

## Available Tools

- `query_knowledge(map_id)` — retrieves the clinical knowledge graph
- `create_sample(specimen_id, patient_id, values, patient_prior)` — registers a specimen
- `advance_sample(specimen_id, to_status)` — advances specimen workflow status
- `apply_autoverification(specimen_id, workflow_params)` — runs HOLD/RELEASE decision
- `get_audit_log(specimen_id?)` — retrieves tool call history

## Required Procedure

**Step 1 — Read the knowledge graph FIRST**
Call `query_knowledge("contamination_swap_map")`.
Read the response carefully. Identify:
- The delta check threshold for K acute rise (in standard deviations)
- The delta check threshold for Ca acute fall (in standard deviations)
- The hold thresholds for contamination detection and swap detection
- The zscore threshold used for delta check calculation

**Step 2 — Derive your decision thresholds**
From the knowledge graph, derive the parameter values you will use for autoverification.
Do NOT invent values. Do NOT use values from the specimen data.
Write these to a local workflow.json file showing your derivation.

**Step 3 — Process all 11 specimens**
For each specimen below, in order:
1. `create_sample(specimen_id, patient_id, values, patient_prior)`
2. `advance_sample(specimen_id, "analyzed")`
3. `apply_autoverification(specimen_id, workflow_params)` — use the params you derived

**Step 4 — Retrieve audit log**
Call `get_audit_log()` (no filter — full session log).
Report the sequence of tool calls.

## Specimens to Process

{SPECIMEN_TABLE}  ← filled in at runtime from scenarios.csv (no labels column)

## Output Required

1. Your workflow.json showing the thresholds you derived and the graph paths you used
2. The HOLD/RELEASE decision for each specimen with your reasoning
3. The full audit log confirming query_knowledge was called before autoverification

## Important
The provenance verifier will check whether your thresholds came from the knowledge graph.
If you use values not found in the graph, the validation will fail on provenance,
regardless of decision accuracy.
````

---

## Runtime Injection

`run_validation.py --phase seed` should also write a ready-to-use `demo/agent/task_prompt_filled.md`
with SESSION_ID and SPECIMEN_TABLE filled in from scenarios.csv (without the `expected_decision`
column — agent must not see ground truth labels).

Specimen table format (no labels):
```
| specimen_id | patient_id | K | Ca | Na | Cl | HCO3 | Glucose | prior_K_mean | prior_K_sd | prior_Ca_mean | prior_Ca_sd |
```

---

## Acceptance Criteria

Manual review:
1. Prompt does not contain any of: "HOLD", "RELEASE", expected thresholds, ground truth labels
2. Prompt explicitly requires `query_knowledge` before `apply_autoverification`
3. Prompt explicitly warns about provenance verification
4. The specimen table matches `scenarios.csv` rows with labels column removed
