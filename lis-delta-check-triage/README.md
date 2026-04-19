# LIS Delta Check Triage — Node 3

**Autoverification gate:** Patient-relative result validation — Node 3 of 6 in the sequential autoverification chain.

---

## What this validates

Before a patient result can be autoverified, the laboratory must compare it against the patient's own prior results. A change that exceeds the patient's biological variation — adjusted for analytical imprecision — is a clinical signal that requires review before release. This task tests whether an AI agent can correctly implement that SD-relative threshold policy, distinguishing genuine acute changes from stable chronic patterns, using thresholds sourced from the lab's own verification study.

The two reasoning paths:

| Pattern | Scenario | Action |
|---------|----------|--------|
| Acute delta violation | Change exceeds the patient's SD-relative threshold | HOLD — result may represent a real clinical event or a pre-analytical error |
| Stable chronic baseline | Change is within the patient's expected biological variation | RELEASE — result is consistent with the patient's history |

The critical distinction: **the population reference interval is not the delta check threshold.** A CKD patient whose potassium moves from 5.4 to 5.7 mmol/L has not violated their delta check — that change is within their chronic SD range — even though 5.7 mmol/L is above the population reference interval upper bound. An autoverification system using population norms as delta thresholds over-holds stable chronic patients and under-detects genuine acute events in normal-range patients.

---

## Regulatory grounding

- **CLSI EP33-A (2012)** — delta check methodology: SD-relative thresholds, CVI-based threshold derivation, new patient fallback policy
- **CLSI AUTO10-A (2006)** — autoverification acceptance criteria must be derived from the laboratory's own patient population, not general reference intervals
- **CLIA 42 CFR §493.1256** — laboratory must establish and follow written criteria for autoverification of patient test results

---

## What passing means clinically

- `unsafe_release_count == 0` — no result with a genuine acute delta violation released. A post-transfusion K spike released without review is a missed clinical event. A creatinine jump consistent with acute kidney injury requires a physician to see it, not an algorithm to silently pass it.
- `f1 >= 0.80` — the agent correctly classifies hold vs. release across the specimen panel.
- `false_hold_rate <= 0.34` — stable CKD and CHF patients whose results move within their chronic baseline are not incorrectly held. A lab that holds every result outside the population reference interval re-reviews 20–30% of its panels manually — negating the throughput benefit of autoverification.

---

## What the agent must do

Read the knowledge graph encoding the lab's SD-relative delta check policy, including chronic stability thresholds, new patient fallback criteria, and multi-analyte combination rules. Configure the triage engine with correct per-analyte thresholds. Run. The knowledge graph is the source of truth — thresholds approximated from published CVI tables will fail on the boundary specimens this task is designed around.

Analytes: K (potassium), Na (sodium), Creatinine. Includes a new-patient fallback scenario and a chronic-stable CKD trap.

---

## Part of a larger framework

This task is Node 3 of a 6-node sequential autoverification chain. Node 3 requires Node 1 (Westgard QC evaluation) to have cleared first — a result that passed QC may still show an acute patient-relative change. The sequential dependency is what no existing benchmark tests.

[labintrace.com](https://labintrace.com)

---

## Intellectual Property Notice

The knowledge graphs, fixture data, evaluation methodology, and provenance verification approach embodied in these tasks are the subject of a pending patent application (U.S. Provisional Application No. 64/032,766). All rights reserved — © 2026 LabInTrace LLC.

This repository is licensed under the [PolyForm Noncommercial License 1.0.0](../LICENSE). Noncommercial use and learning are permitted. Commercial use requires a separate written license.

For licensing inquiries: alex.openstone@labintrace.net
