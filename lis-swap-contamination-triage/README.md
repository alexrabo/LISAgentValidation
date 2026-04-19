# LIS Specimen Integrity Triage — Pre-Analytical Gate

**Autoverification gate:** Pre-analytical specimen integrity — contamination and identity swap detection, upstream of all six nodes in the sequential autoverification chain.

---

## What this validates

Before any result enters the autoverification pipeline, the laboratory must confirm the specimen is analytically valid and assigned to the correct patient. This task tests whether an AI agent can correctly identify two distinct pre-analytical failures — EDTA tube contamination and specimen identity swap — using electrolyte signatures encoded in the lab's own verification policy.

The two failure modes:

| Failure | Signature | Action if detected |
|---------|-----------|-------------------|
| EDTA contamination | Elevated K, depressed Ca — EDTA anticoagulant leaches from tube | HOLD — result is analytically invalid |
| Identity swap | Patient chemistry fits a different patient's historical profile better than their own | HOLD — result may be reported to the wrong patient |

The critical constraint: **zero unsafe releases.** A contaminated specimen reported as a real K of 7.2 mmol/L triggers a nephrology consult that should never have happened. A swapped specimen means a patient receives results from someone else's blood draw.

---

## Regulatory grounding

- **CLSI GP41-Ed7 (2017)** — specimen collection and handling requirements; pre-analytical variables that invalidate results
- **CAP checklist COM.30450** — laboratory must have a written policy for specimen rejection criteria
- **CLIA 42 CFR §493.1232** — pre-analytic systems must ensure specimen integrity before processing

---

## What passing means clinically

- `unsafe_release_count == 0` — no contaminated or swapped specimen released. A contaminated K result in the chart is a patient safety event. A swapped specimen triggers treatment decisions based on another patient's chemistry.
- `f1 >= 0.80` — the agent correctly classifies hold vs. release across the specimen panel.
- `false_hold_rate <= 0.34` — valid specimens with unusual but authentic chemistry are not incorrectly held. Over-holding increases redraws and delays care.

---

## What the agent must do

Read the knowledge graph encoding the lab's contamination detection policy and patient-prior matching thresholds. Configure the triage engine with correct scoring parameters for both failure modes. Run. The knowledge graph is the source of truth — parameters derived from general clinical training data will fail on the boundary cases this task is designed around.

---

## Part of a larger framework

This task is the pre-analytical gate upstream of a 6-node sequential autoverification chain. A specimen that fails this gate never reaches the delta check (Node 3), QC evaluation (Node 1), or reportable range check (Node 4). The sequential dependency is what no existing benchmark tests.

[labintrace.com](https://labintrace.com)

---

## Intellectual Property Notice

The knowledge graphs, fixture data, evaluation methodology, and provenance verification approach embodied in these tasks are the subject of a pending patent application (U.S. Provisional Application No. 64/032,766). All rights reserved — © 2026 LabInTrace LLC.

This repository is licensed under the [PolyForm Noncommercial License 1.0.0](../LICENSE). Noncommercial use and learning are permitted. Commercial use requires a separate written license.

For licensing inquiries: alex.openstone@labintrace.net
