# LIS Reportable Range Triage — Node 4

**Autoverification gate:** Reference/Reportable Range limit check — Node 4 of 6 in the sequential autoverification chain.

---

## What this validates

Before a patient result can be autoverified and released, the laboratory must confirm it falls within three nested bounds — each with a different clinical and regulatory meaning. This task tests whether an AI agent can correctly implement that three-tier policy, sourced from lab-specific verified data, not general clinical knowledge.

The three tiers:

| Tier | Source | Action if exceeded |
|------|--------|-------------------|
| AMR (Analytical Measurement Range) | Instrument-verified per CLIA §493.1253(b)(1) | HOLD — result not analytically valid |
| Manual Review Limits | Lab's own 2nd–98th percentile patient population | HOLD — pathologist review required |
| Reference Interval | Healthy population 2.5th–97.5th percentile | RELEASE with flag — clinically notable, not a hold |

The critical distinction: **manual review limits are not the reference interval.** In a CKD-heavy population, a potassium of 6.2 mmol/L is above the reference interval upper (5.0) but within the lab's verified manual review range (7.5). An autoverification system using the reference interval as a hold threshold over-holds stable chronic patients — degrading throughput without improving safety.

---

## Regulatory grounding

- **CLIA 42 CFR §493.1253(b)(1)** — laboratory must verify the manufacturer's stated AMR before reporting patient results. The manufacturer's claim alone is not sufficient.
- **CLSI AUTO10-A (2006)** — autoverification hold criteria must be grounded in the laboratory's own patient population, not general reference intervals.
- **CLSI EP28-A3c (2010)** — reference interval methodology (2.5th–97.5th percentile of healthy reference population).

---

## What passing means clinically

- `unsafe_release_count == 0` — no result outside the verified reportable range or manual review limits was released. A K=10.5 mmol/L (above AMR) reported as a number is analytically invalid. A Lipase=650 U/L released without pathologist review in a pancreatitis-suspected patient is a clinical risk.
- `f1 >= 0.80` — the agent correctly classifies hold vs. release across the analyte panel.
- `false_hold_rate <= 0.34` — stable patients with results above the reference interval but within manual review are not incorrectly held. Over-holding is a throughput and patient care problem.

---

## What the agent must do

Read the knowledge graph encoding the lab's verified limit-check policy. Configure the triage engine with correct three-tier bounds for each analyte. Run. The knowledge graph is the source of truth — bounds derived from general clinical training data will fail.

Analytes: K (potassium), Na (sodium), Lipase. Includes a dilution reflex scenario for AMR overshoot.

---

## Part of a larger framework

This task is Node 4 of a 6-node sequential autoverification chain. Node 4 requires Node 3 (delta check) to have cleared — a result that passed the delta check may still be outside the lab's verified reportable range. The sequential dependency is what no existing benchmark tests.

[labintrace.com](https://labintrace.com)
