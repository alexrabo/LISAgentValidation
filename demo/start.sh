#!/usr/bin/env bash
# =============================================================================
# LIS Demo — local start script
# Starts the full demo stack and opens the Streamlit dashboard.
#
# Usage:
#   ./demo/start.sh
# =============================================================================
set -euo pipefail

DEMO_DIR="$(cd "$(dirname "$0")" && pwd)"

# ---------------------------------------------------------------------------
# 1. Bootstrap .env
# ---------------------------------------------------------------------------
if [[ ! -f "${DEMO_DIR}/.env" ]]; then
  if [[ -f "${DEMO_DIR}/.env.example" ]]; then
    cp "${DEMO_DIR}/.env.example" "${DEMO_DIR}/.env"
    echo "Created .env from .env.example — edit it before running again."
    exit 1
  else
    echo "No .env or .env.example found in ${DEMO_DIR}. Cannot start."
    exit 1
  fi
fi

# Load .env into current shell
set -a
# shellcheck disable=SC1091
source "${DEMO_DIR}/.env"
set +a

# ---------------------------------------------------------------------------
# 2. Start MCP server via docker-compose
# ---------------------------------------------------------------------------
echo "--- Starting MCP server (docker-compose) ---"
docker-compose -f "${DEMO_DIR}/docker-compose.yml" up -d

# ---------------------------------------------------------------------------
# 3. Wait for /health
# ---------------------------------------------------------------------------
echo -n "--- Waiting for server health"
MAX_WAIT=60
ELAPSED=0
until curl -sf http://localhost:8000/health > /dev/null 2>&1; do
  echo -n "."
  sleep 2
  ELAPSED=$((ELAPSED + 2))
  if [[ ${ELAPSED} -ge ${MAX_WAIT} ]]; then
    echo ""
    echo "Server did not become healthy after ${MAX_WAIT}s. Check docker-compose logs."
    exit 1
  fi
done
echo " ready"

# ---------------------------------------------------------------------------
# 4. Seed specimens
# ---------------------------------------------------------------------------
echo "--- Seeding specimens ---"
python3 "${DEMO_DIR}/harness/run_validation.py" \
  --phase seed \
  --session-id demo-run-1

# ---------------------------------------------------------------------------
# 5. Launch Streamlit
# ---------------------------------------------------------------------------
echo "--- Starting Streamlit dashboard ---"
echo "    Open: http://localhost:8501"
echo "    Stop: Ctrl+C, then: docker-compose -f demo/docker-compose.yml down"
echo ""
streamlit run "${DEMO_DIR}/ui/app.py" \
  --server.port=8501 \
  --server.address=localhost \
  --browser.gatherUsageStats=false
