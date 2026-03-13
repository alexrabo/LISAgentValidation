#!/usr/bin/env bash
# =============================================================================
# LIS Demo — stop script
# Stops the Streamlit dashboard and the docker-compose MCP server stack.
# =============================================================================
set -euo pipefail

DEMO_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Stop Streamlit (by port, not by name) ---
STREAMLIT_PORT=8501
STREAMLIT_PID=$(lsof -ti tcp:${STREAMLIT_PORT} 2>/dev/null || true)

if [[ -n "${STREAMLIT_PID}" ]]; then
  kill "${STREAMLIT_PID}"
  echo "Streamlit stopped (pid ${STREAMLIT_PID})"
else
  echo "Streamlit not running on port ${STREAMLIT_PORT}"
fi

# --- Stop docker-compose stack ---
if docker-compose -f "${DEMO_DIR}/docker-compose.yml" ps -q 2>/dev/null | grep -q .; then
  docker-compose -f "${DEMO_DIR}/docker-compose.yml" down
  echo "Docker stack stopped"
else
  echo "Docker stack not running"
fi
