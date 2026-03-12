# LIS AI Validation Demo

An end-to-end validation framework that tests whether an AI agent can correctly
triage laboratory specimens for contamination and identity swap failures —
and prove that its decisions were grounded in a clinical knowledge standard,
not fitted to the data.

---

## The Problem

Clinical autoverification systems make HOLD/RELEASE decisions on lab specimens.
Validating that an AI agent makes those decisions correctly is Layer 1.
Proving the agent *derived its thresholds from CLSI EP33* rather than from the
data is Layer 2 — and most validation frameworks stop at Layer 1.

This demo implements both layers independently.

---

## Two-Layer Evaluation

```
Layer 1 — Decision Quality          Layer 2 — Reasoning Provenance
─────────────────────────           ───────────────────────────────
unsafe_release_count == 0  ← gate   contamination_hold_threshold: within 0.05 of KG
F1 >= 0.80                          identity_swap_hold_threshold: within 0.05 of KG
false_hold_rate <= 0.34             delta_check_sd_threshold:     within 0.20 of KG
```

Layer 2 runs on the agent's `workflow.json` **independently**, after the agent
finishes. An agent can pass Layer 1 by fitting the data and fail Layer 2.
Both layers must pass for the run to be valid.

---

## Audit Trail — ALCOA+ Compliant

The audit log enforces ALCOA+ data integrity principles (CAP GEN.43875):

| ALCOA+ Principle | Implementation |
|---|---|
| **Attributable** | Every tool call recorded with session ID |
| **Legible** | Structured JSON log, ordered by ID ASC |
| **Contemporaneous** | UTC timestamp on every audit entry |
| **Original** | `values_json` write-once on `create_sample` — never updated |
| **Accurate** | Append-only audit log — no DELETE or UPDATE |
| **Consistent** | `query_knowledge` must appear before `apply_autoverification` — enforced by `ComplianceService` |

---

## Quick Start

```bash
# 1. Copy and fill environment file
cp .env.example .env
# Set KG_JSON_B64: base64 -i config/clinical_knowledge.json | tr -d '\n'

# 2. Start server
docker-compose up -d
curl http://localhost:8000/health
# → {"status": "ok", "kg_version": "CLSI_EP33_2023_v1", "port": 8000}

# 3. Seed specimens
python harness/run_validation.py --phase seed --session-id run-001

# 4. Run the agent
# Give the agent: agent/task_prompt_filled.md
# Agent writes: agent/workflow.json

# 5. Evaluate
python harness/run_validation.py --phase evaluate \
  --session-id run-001 \
  --workflow agent/workflow.json \
  --out validation_report.md

# 6. View Streamlit dashboard
streamlit run ui/app.py
```

---

## Architecture

```
agent/task_prompt_filled.md
        │
        ▼ (agent calls MCP tools)
lims_server.py          ← FastMCP + FastAPI, port 8000
    │
    ├── ComplianceService  ← query_knowledge must precede apply_autoverification
    ├── LimsService        ← specimen lifecycle (SQLite via lims_db)
    ├── KnowledgeService   ← clinical_knowledge.json (CLSI EP33)
    ├── AuditService       ← audit trail reads
    └── EventStore         ← append-only domain event log
        │
        ▼ (harness reads after agent finishes)
run_validation.py --phase evaluate
    ├── provenance_verifier.py  ← Layer 2: KG threshold comparison
    ├── report.py               ← validation_report.md
    └── ui/app.py               ← Streamlit dashboard
```

### MCP Tools (5 total)

| Tool | Purpose | Sequence |
|---|---|---|
| `query_knowledge` | Retrieve CLSI EP33 knowledge graph | **Must be first** |
| `create_sample` | Register specimen | Optional — harness pre-seeds |
| `advance_sample` | Advance workflow status | Optional — harness pre-seeds |
| `apply_autoverification` | Run triage decision | After `query_knowledge` |
| `get_audit_log` | Retrieve tool call history | After all specimens |

### Server Architecture Patterns

| Pattern | Component | Status |
|---|---|---|
| Service layer | `LimsService`, `KnowledgeService`, `ComplianceService`, `AuditService` | Implemented |
| Event Store | `EventStore` — append-only audit ledger | Implemented |
| Circuit Breaker | Wraps `run_triage()` ProcessPoolExecutor | Implemented |
| Middleware | Throttling → OpenID → Request logging | Implemented |
| OpenID auth | `OpenIDMiddleware` | Stub — passthrough when `OPENID_ENABLED=false` |

---

## Knowledge Graph — Clinical Rules (CLSI EP33)

The clinical knowledge graph (`clinical_knowledge.json`) drives all triage decisions.
It is **not baked into the image** — injected at runtime via `KG_JSON_B64`.
Updating clinical rules requires only a server restart, not a rebuild.

```bash
# Encode KG for injection
export KG_JSON_B64=$(base64 -i config/clinical_knowledge.json | tr -d '\n')

# Verify decode
echo "$KG_JSON_B64" | base64 --decode | python3 -m json.tool | head -5
```

| Deployment | KG injection method |
|---|---|
| Local dev | `KG_PATH` → `config/clinical_knowledge.json` |
| Docker | `KG_JSON_B64` in `.env` |
| GitHub Actions | `KG_JSON_B64` as encrypted secret |
| GCP Cloud Run | `KG_JSON_B64` from Secret Manager |

---

## Phase 2 — Allotrope ADM Integration

In production, `create_sample` receives **Allotrope Foundation Data Model (ADM)**
documents directly from lab analyzers — not manually seeded CSV rows.

Allotrope ADM adds to every specimen record:

| Field | Value | Clinical significance |
|---|---|---|
| `container_type` | `"EDTA"` | Direct contamination flag before any delta check |
| `instrument_id` | `"Cobas8000-3"` | Chain of custody |
| `reagent_lot` | `"LOT-2026-001"` | Lot traceability |
| `method` | `"ISE"` | Method flag for K/Ca |

An EDTA tube flagged at the container level, confirmed by delta check, traced to
a specific instrument lot is a qualitatively different clinical finding than a value
anomaly with no provenance. This demo shows the decision framework. Allotrope ADM
is the data layer that makes it production-grade.

---

## Test Specimens

11 specimens (S100–S110) covering:

| Scenario | Specimens | Expected |
|---|---|---|
| Normal result | S100, S102, S103, S104, S108, S109 | Pass autoverification |
| EDTA contamination (K↑ Ca↓) | S101, S107 | Hold — safety critical |
| Specimen identity swap | S105, S106 | Hold — identity concern |
| CKD interference guard | S110 | Pass — K elevated, Ca preserved |

S110 is the critical interference guard: a CKD patient with chronically elevated K.
The knowledge graph distinguishes EDTA contamination (acute K rise + Ca depression)
from CKD hyperkalemia (chronic stable K, Ca preserved) via the patient's own delta
check. An agent that hard-codes absolute thresholds fails S110. An agent that reads
CLSI EP33 correctly releases it.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `KG_JSON_B64` | Production | Base64-encoded `clinical_knowledge.json` |
| `KG_PATH` | Local dev | Path to KG file (default: `config/clinical_knowledge.json`) |
| `DB_PATH` | Optional | SQLite path (default: `lims.db`) |
| `OPENID_ENABLED` | Optional | Enable OpenID auth (default: `false`) |
| `THROTTLE_RPM` | Optional | Rate limit per session (default: `60`) |

---

## Running Tests

```bash
uv run pytest tests/ -v
# 96 tests — all passing
```
