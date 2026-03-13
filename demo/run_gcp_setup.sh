#!/usr/bin/env bash
# Usage: ./demo/run_gcp_setup.sh <gcp-project-id> [github-repo]
#
# Examples:
#   ./demo/run_gcp_setup.sh lis-ai-validation-2026
#   ./demo/run_gcp_setup.sh lis-ai-validation-2026 alexrabo/LISAgentValidation

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <gcp-project-id> [github-repo]"
  echo ""
  echo "  gcp-project-id  Globally unique GCP project ID (must already exist)"
  echo "  github-repo     GitHub repo in owner/name format (default: alexrabo/LISAgentValidation)"
  exit 1
fi

GCP_PROJECT_ID="$1"
GITHUB_REPO="${2:-alexrabo/LISAgentValidation}"

GCP_PROJECT_ID="${GCP_PROJECT_ID}" \
GITHUB_REPO="${GITHUB_REPO}" \
  "$(dirname "$0")/gcp_setup.sh"
