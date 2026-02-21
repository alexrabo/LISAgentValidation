# LIS AI Validation Framework

> Auditable, workflow-level validation artifacts for AI agents in Laboratory Information Systems

## Overview

This repository provides **validated Terminal Bench tasks** for evaluating AI agents in clinical laboratory workflows. Each task represents an auditable, reproducible, validated artifact grounded in real laboratory practices and failure modes.

**The Challenge:**

Traditional LIS validation assumes deterministic, rule-based systems. AI agents introduce emergent capabilities that escape change-based validation. CAP GEN.43875 requires validation "based on changes made" — but you can't validate changes you don't know exist.

**The Approach:**

Build a library of **Terminal Bench validation tasks** that:
- Test workflow-level reasoning (not just threshold accuracy)
- Provide auditable, versioned artifacts for regulatory compliance
- Enable reproducible evaluation across models and updates
- Ground validation in established laboratory practices

**Core Thesis:**

*Agentic AI in LIS/LIMS introduces new, silent failure modes that require workflow-level validation — not just model accuracy — and can be evaluated using Terminal Bench as auditable, validated artifacts.*

> **Disclaimer:** This is professional development research and is not affiliated with any organization. This framework is provided for educational and research purposes.

---

## First Validated Artifact: LIS Swap & Contamination Triage

**LIS Swap & Contamination Triage is the first auditable, reproducible, validated task in a growing library.** This Terminal Bench task tests whether AI agents can correctly triage laboratory specimens for contamination and identity swap failures.

We welcome contributions from the laboratory community to expand this framework with additional workflow-level validation tasks.

### The Challenge

A batch of laboratory results has passed instrument QC, but specimens may have:
- **EDTA contamination** (elevated K, depressed Ca from tube contamination)
- **Identity swaps** (specimens assigned to wrong patients)
- **Normal results** (should be released)

AI agents must make HOLD/RELEASE decisions by configuring a `workflow.json` policy file.

### Why This Matters

- **Threshold-only validation passes** — Individual analyte values may be in range
- **Workflow reasoning fails** — Agents must detect cross-analyte patterns and identity mismatches
- **Safety-critical decisions** — Zero unsafe releases required (no contaminated or swapped specimens released)

### Evaluation Criteria

All three must hold:
- **F1 Score ≥ 0.80** (precision and recall on HOLD decisions)
- **Zero unsafe releases** (no contaminated or swapped specimens released)
- **False hold rate ≤ 0.34** (minimize unnecessary specimen holds)

Results aggregated across visible and hidden batches.

---

## Quick Start

This is a **Terminal Bench task** — designed for standardized AI agent evaluation using Harbor.

### Prerequisites
- **Harbor** (Terminal Bench execution harness)
- **API keys** for model testing (Anthropic, OpenAI, etc.)
- Docker (Harbor installs automatically if needed)

### Installation

**Step 1: Install uv (if not already installed)**

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Or see [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/).

**Step 2: Install Harbor**

```bash
# Using uv (recommended)
uv tool install harbor

# Or using pip
pip install harbor
```

### Run with Harbor

**Step 1: Validate the task with oracle (reference solution)**

First, verify the task infrastructure works correctly:

```bash
harbor run -p lis-swap-contamination-triage/ --oracle
```

This runs the reference solution (`solution/solve.sh`) to confirm the task passes evaluation.

**Step 2: Evaluate AI models**

Once validated, test AI agents against the task:

```bash
# Set your API key
export ANTHROPIC_API_KEY=<your-key>

# Run evaluation
harbor run -p lis-swap-contamination-triage/ \
  --model anthropic/claude-opus-4-1 \
  --agent claude-code
```

Harbor orchestrates the complete evaluation pipeline:
1. Builds the Docker environment
2. Injects the agent with task instructions from `instruction.md`
3. Allows agent to configure `/app/workflow.json` and produce triage decisions
4. Executes verification tests (`tests/test_outputs.py`)
5. Reports F1 score, safety metrics, and pass/fail status

**📖 See [`documentation/terminal_bench_primer_for_labs.pdf`](documentation/terminal_bench_primer_for_labs.pdf) for a comprehensive guide to Terminal Bench evaluation methodology for laboratory AI validation.**

### Task Requirements

Agents must:
1. Analyze specimen batch data in `/app/fixtures/visible_batch_nolabels.json`
2. Configure `/app/workflow.json` policy (default is intentionally flawed)
3. Produce `/app/decisions.json` with correct HOLD/RELEASE decisions
4. Achieve: **F1 ≥ 0.80**, **zero unsafe releases**, **false hold rate ≤ 0.34**

Results are evaluated against both visible and hidden test batches.

---

## Repository Structure

```
lis-swap-contamination-triage/     # Terminal Bench task
├── environment/                    # Docker environment + triage engine
│   ├── src/triage.py              # Contamination + swap scoring logic
│   ├── data/                       # Batch fixtures (visible, hidden)
│   └── pyproject.toml             # Python 3.10+ stdlib only
├── tests/test_outputs.py          # Evaluation (F1, safety, false holds)
├── solution/solve.sh              # Reference solution
├── instruction.md                 # Agent task instructions
└── task.toml                       # Terminal Bench metadata

task/                              # Task definitions
documentation/                     # Terminal Bench guides
landing-page/                      # Project website
README.md                          # This file
LICENSE                            # MIT License
```

---

## How It Works

The triage pipeline processes specimen batches through four stages:

### 1. Contamination Scoring
Detects EDTA-like contamination signatures using geometric mean of normalized component scores:
- **High potassium (K)** — Above contamination threshold
- **Low calcium (Ca)** — Below normal range
- **Pattern recognition** — Cross-analyte consistency

### 2. Swap Detection
Pairwise comparison of all specimens in batch using delta-check methodology:
- Computes whether swapping two specimens' patient assignments reduces mismatch
- Uses standardized deltas / RCV-style limits against patient historical data
- Score = relative improvement in fit

### 3. Thresholded Decisions
- Scores must exceed configured thresholds to trigger HOLD
- `contamination_hold_threshold` (default 0.5)
- `swap_hold_threshold` (default 0.25)
- Below-threshold signals → RELEASE

### 4. Budget Enforcement
If HOLDs exceed `max_holds` batch constraint, weaker HOLDs are downgraded to RELEASE.

### Key Tunable Parameters

| Parameter | Location | Purpose |
|-----------|----------|---------|
| `contamination_hold_threshold` | `decision_policy` | Min contamination score to HOLD |
| `swap_hold_threshold` | `decision_policy` | Min swap improvement score to HOLD |
| `zscore_threshold` | root | Delta-check threshold (standardized difference divisor for swap detection) |
| `K_min`, `Ca_max` | `contamination_signatures[].rule` | Trigger levels for contamination |
| `analyte_weights` | `swap_detection` | Per-analyte weights for swap mismatch |

---

## Domain Context

### Ground Truth Labels
- **NORMAL** — Should be released (no issues detected)
- **CONTAMINATION** — EDTA tube contamination causing high K / low Ca
- **SWAP** — Specimen assigned to wrong patient (identity mismatch)

### Critical Safety Constraint
**Zero unsafe releases** — No contaminated or swapped specimens should be released. This is a hard requirement that reflects real laboratory safety standards.

### Clinical Realism
This task models delta-check and specimen-quality rule-outs used in autoverification and middleware systems. The output is HOLD for manual review, not a definitive diagnosis. This reflects real-world laboratory workflows where automated systems flag specimens for human review rather than making final clinical determinations.

---

## Documentation

- **Project Website:** [lisaivalidation.dev](https://lisaivalidation.dev)
- **Architecture Docs:** See `design/` directory
- **Build Instructions:** See `CLAUDE.md`

---

## Regulatory Context

This work addresses validation challenges outlined in:
- **CAP GEN.43875** — Autoverification validation and revalidation requirements
- **FDA CDS Guidance** — Clinical Decision Support Software (updated Jan 2026)
- **CAP AI Guidance** — Lifecycle validation for AI in clinical laboratories

Traditional validation assumes deterministic, rule-based systems. AI agents introduce emergent capabilities that require workflow-level evaluation.

---

## Why Terminal Bench?

Terminal Bench provides:
- **Operational realism** — Real failure modes, not synthetic benchmarks
- **Hidden test sets** — Prevents overfitting to visible examples
- **Standardized evaluation** — Reproducible scoring across agents
- **Safety constraints** — Hard requirements (zero unsafe releases)

This approach aligns with modern agent evaluation frameworks (Harbor, Anthropic agent evals) while addressing regulated industry requirements.

---

## Upcoming Work

A formal methodology document describing the benchmark design principles behind this task — including how to prevent agents from passing by data-fitting rather than applying domain knowledge — is in preparation.

---

## Contributing

This framework welcomes contributions from the laboratory community. If you're working on AI validation in regulated industries and would like to collaborate or contribute additional workflow-level validation tasks, please open an issue or submit a pull request.

**Contact:** Alex Openstone ([alexrabo@gmail.com](mailto:alexrabo@gmail.com))

---

## References

### Regulatory Standards
- **CAP GEN.43875** — Autoverification Validation and Revalidation Requirements
  [https://documents-cloud.cap.org/pdf/QA%20GEN.43875.pdf](https://documents-cloud.cap.org/pdf/QA%20GEN.43875.pdf)

- **CLSI AUTO10-A** — Autoverification of Clinical Laboratory Test Results
  Clinical and Laboratory Standards Institute (2006)

- **CLSI AUTO15-ED1** — Autoverification of Medical Laboratory Results for Specific Disciplines
  Clinical and Laboratory Standards Institute (2019)

- **FDA Clinical Decision Support Software Guidance** (Updated January 2026)
  U.S. Food and Drug Administration

### Research Literature
- **Yang YC, et al. (2025)** — "Validation gap analysis for AI in clinical laboratories"
  *Preprint*. doi: [10.21203/rs.3.rs-5934891/v1](https://doi.org/10.21203/rs.3.rs-5934891/v1)

- **BMC Medical Informatics and Decision Making (2021)** — "Autoverification in clinical laboratories: a systematic review"
  [https://bmcmedinformdecismak.biomedcentral.com/articles/10.1186/s12911-021-01545-3](https://bmcmedinformdecismak.biomedcentral.com/articles/10.1186/s12911-021-01545-3)

### Evaluation Frameworks
- **Terminal Bench** — Laude Institute / Stanford HAI
  Standardized agent evaluation framework

- **Harbor** — Terminal Bench 2.0 execution harness
  [https://github.com/stanford-hai/harbor](https://github.com/stanford-hai/harbor)

---

## License

MIT License - See LICENSE file for details

---

**Built for real-world laboratory safety. Validated with Terminal Bench rigor.**
