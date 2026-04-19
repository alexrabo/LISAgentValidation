# LIS Westgard QC Triage — Node 1

**Autoverification gate:** Internal quality control evaluation — Node 1 of 6 in the sequential autoverification chain.

---

## What this validates

Before any patient result can be autoverified, the laboratory must confirm that internal quality control materials passed on the same analytical run. A QC failure means the instrument's accuracy and precision cannot be assumed — patient results from that run are suspect regardless of whether they look clinically plausible. This task tests whether an AI agent can correctly implement Westgard rule-based QC evaluation, including multi-level synthesis, using a policy sourced from the lab's own QC configuration.

The decision structure:

| QC outcome | Interpretation | Action |
|------------|---------------|--------|
| All controls within limits | Run in statistical control | ACCEPT — patient results may proceed |
| Single warning rule triggered | Possible random error — monitor | WARNING — review required before release |
| Rejection rule triggered | Systematic or random error confirmed | REJECT — patient results cannot be released |

The critical constraint: **a WARNING on an out-of-control run is clinically unsafe.** Under CLSI C24-Ed4, a QC run that meets a rejection criterion must be rejected — a system that classifies it as WARNING still allows patient results to be reported. That is the failure mode this task is designed to catch.

---

## Regulatory grounding

- **CLIA 42 CFR §493.1256(f)** — control materials must meet acceptability criteria **before** reporting patient test results. QC failure cannot be overridden by autoverification heuristics passing — they test different objects.
- **CLSI C24-Ed4 (2016)** — statistical QC for quantitative measurement procedures: Westgard rule definitions, multi-level synthesis criteria, QC event temporal scope
- **Westgard et al., Clin Chem 27:493–501 (1981)** — original multi-rule Shewhart chart methodology; primary citation for all six rule definitions used in this task

---

## What passing means clinically

- `unsafe_release_count == 0` — no out-of-control QC run accepted or passed as warning. Patient results from a rejected run that were released represent a potential systematic error affecting every result on that instrument in that analytical session.
- `f1 >= 0.80` — the agent correctly classifies accept, warning, and reject across the QC run panel.
- `false_reject_rate <= 0.34` — in-control QC runs are not over-rejected. A lab that rejects 30% of valid QC runs reruns controls constantly, delays patient reporting, and degrades confidence in its own QC system.

---

## What the agent must do

Read the knowledge graph encoding the lab's Westgard rule configuration — six rules, error classification routing, and multi-level synthesis criteria. Configure the triage engine with correct rule thresholds and multi-level policy. Run. The knowledge graph is the source of truth — rule parameters approximated from published Westgard tables will fail on the temporal and directional constraints this task encodes.

QC levels: two (low normal, high normal). Analytes: K, Creatinine. Includes a multi-level synthesis scenario where the temporal scope constraint — not the rule threshold — determines the correct classification.

---

## Part of a larger framework

This task is Node 1 of a 6-node sequential autoverification chain. Node 1 is the first gate — a QC failure blocks all downstream nodes. An agent that passes Node 3 (delta check) without having cleared Node 1 fails under CLIA §493.1256(f), regardless of whether the patient result looks analytically correct. That regulatory gate is what no existing benchmark tests.

[labintrace.com](https://labintrace.com)

---

## Intellectual Property Notice

The knowledge graphs, fixture data, evaluation methodology, and provenance verification approach embodied in these tasks are the subject of a pending patent application (U.S. Provisional Application No. 64/032,766). All rights reserved — © 2026 LabInTrace LLC.

This repository is licensed under the [PolyForm Noncommercial License 1.0.0](../LICENSE). Noncommercial use and learning are permitted. Commercial use requires a separate written license.

For licensing inquiries: alex.openstone@labintrace.net
