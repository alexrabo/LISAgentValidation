# Task 08 — Docker + README
**Output files:** `demo/docker-compose.yml`, `demo/README.md`  
**Depends on:** Tasks 01–07 complete  
**Global constraints:** see `IMPL_SPEC.md`

---

## Purpose
Runnable demo packaging. docker-compose starts the MCP LIMS server.
README is the public-facing "how to run this demo" document.

---

## docker-compose.yml

```yaml
version: "3.9"

services:
  lims-server:
    build:
      context: ./server
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data          # lims.db persists here
      - ../../lis-swap-contamination-triage/environment:/app/triage:ro
    environment:
      - TRIAGE_PY_PATH=/app/triage/src/triage.py
      - KG_PATH=/app/triage/data/clinical_knowledge.json
    command: uvicorn lims_server:app --host 0.0.0.0 --port 8000
```

---

## demo/server/Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY lims_server.py lims_db.py ./
CMD ["uvicorn", "lims_server:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## README.md content

````markdown
# LIS MCP Validation Demo

Demonstrates an AI agent that must derive clinical decision thresholds from a knowledge
graph before validating laboratory specimens — not from fitting the data in front of it.

**What this shows:**
1. Agent queries a CLSI EP33-grounded knowledge graph via MCP
2. Agent derives thresholds from graph paths (auditable, not guessed)
3. Validation harness verifies both decision quality and reasoning provenance
4. Every decision traces to a published clinical standard

## Prerequisites
- Docker + docker-compose
- Python 3.10+
- Claude API key (for running the agent)
- uv (package manager)

## Quick Start

```bash
# 1. Start the MCP LIMS server
cd demo
docker-compose up -d

# 2. Seed the specimen batch
python3 harness/run_validation.py --phase seed --session-id demo-run-1

# 3. Run the agent
#    Open agent/task_prompt_filled.md
#    Give it to Claude with MCP server access at http://localhost:8000
#    Agent writes its workflow.json to agent/workflow.json

# 4. Evaluate
python3 harness/run_validation.py --phase evaluate \
  --session-id demo-run-1 \
  --workflow agent/workflow.json \
  --out validation_report.md

# 5. Read the report
cat validation_report.md
```

## Pass Criteria
- Unsafe releases: 0 (safety gate)
- F1: >= 0.80
- False hold rate: <= 0.34
- Provenance: PASS (thresholds from knowledge graph, not data)

## Architecture
See `docs_main/LIS_MCP_DEMO_DESIGN_v2.md` for full architecture documentation.

## Key Files
| File | Purpose |
|------|---------|
| `server/lims_server.py` | FastAPI MCP server (5 tools) |
| `harness/scenarios.csv` | 11 test specimens |
| `harness/expected_outcomes.csv` | Ground truth labels |
| `harness/provenance_verifier.py` | Checks agent derived thresholds from KG |
| `agent/task_prompt.md` | System prompt for the agent under test |
| `../../lis-swap-contamination-triage/environment/src/triage.py` | Deterministic scorer |
| `../../lis-swap-contamination-triage/environment/data/clinical_knowledge.json` | CLSI knowledge graph |
````

---

## Acceptance Criteria

```bash
cd demo
docker-compose up -d
sleep 3
curl -s http://localhost:8000/health | python3 -m json.tool
# Expected: {"status": "ok", "kg_version": "CLSI_EP33_2023_v1"}
docker-compose down
```

Add a `/health` endpoint to `lims_server.py` that returns:
```json
{"status": "ok", "kg_version": "<from clinical_knowledge.json>", "port": 8000}
```
