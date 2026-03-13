#!/usr/bin/env bash
# =============================================================================
# LIS Demo — GCP Infrastructure Setup
# Run once to provision all GCP resources for the Streamlit demo on Cloud Run.
#
# What this creates:
#   - Service account (lis-demo-sa) with GCS read access
#   - Artifact Registry repository for Docker images
#   - Private GCS bucket for recording.cast
#   - Workload Identity Federation for GitHub Actions (keyless auth)
#   - Local SA key for development use (gitignored)
#
# Prerequisites:
#   gcloud CLI installed and authenticated:
#     gcloud auth login
#     gcloud auth application-default login
#
# Usage:
#   GCP_PROJECT_ID=your-project-id \
#   GITHUB_REPO=alexrabo/LISAgentValidation \
#   ./demo/gcp_setup.sh
# =============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID env var before running}"
GITHUB_REPO="${GITHUB_REPO:-alexrabo/LISAgentValidation}"
REGION="us-central1"

SA_NAME="lis-demo-sa"
SA_DISPLAY="LIS Demo Service Account"
BUCKET_NAME="${PROJECT_ID}-lis-demo-assets"
AR_REPO="lis-demo"
CLOUD_RUN_SERVICE="lis-demo-ui"
WIF_POOL="github-pool"
WIF_PROVIDER="github-provider"

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")

echo "=== LIS Demo GCP Setup ==="
echo "Project : ${PROJECT_ID} (${PROJECT_NUMBER})"
echo "Region  : ${REGION}"
echo "Bucket  : gs://${BUCKET_NAME}"
echo "SA      : ${SA_EMAIL}"
echo "GitHub  : ${GITHUB_REPO}"
echo ""

# ---------------------------------------------------------------------------
# 1. Set active project + enable APIs
# ---------------------------------------------------------------------------
echo "--- [1/6] Enabling APIs ---"
gcloud config set project "${PROJECT_ID}"
gcloud services enable \
  run.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  --project="${PROJECT_ID}"

# ---------------------------------------------------------------------------
# 2. Create service account
# ---------------------------------------------------------------------------
echo "--- [2/6] Service account ---"
if gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" &>/dev/null; then
  echo "    Already exists — skipping"
else
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="${SA_DISPLAY}" \
    --project="${PROJECT_ID}"
  echo "    Created ${SA_EMAIL}"
fi

# Roles needed by Cloud Run at runtime: read recording.cast from GCS
for ROLE in \
  "roles/storage.objectViewer" \
  "roles/run.invoker"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --condition=None \
    --quiet
  echo "    Granted ${ROLE}"
done

# ---------------------------------------------------------------------------
# 3. Artifact Registry repository
# ---------------------------------------------------------------------------
echo "--- [3/6] Artifact Registry ---"
if gcloud artifacts repositories describe "${AR_REPO}" \
     --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  echo "    Repository already exists — skipping"
else
  gcloud artifacts repositories create "${AR_REPO}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="LIS demo Docker images" \
    --project="${PROJECT_ID}"
  echo "    Created ${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}"
fi

# Allow the SA to push images (needed by GitHub Actions)
gcloud artifacts repositories add-iam-policy-binding "${AR_REPO}" \
  --location="${REGION}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/artifactregistry.writer" \
  --project="${PROJECT_ID}" \
  --quiet

# ---------------------------------------------------------------------------
# 4. Private GCS bucket for recording.cast
# ---------------------------------------------------------------------------
echo "--- [4/6] GCS bucket ---"
if gsutil ls -b "gs://${BUCKET_NAME}" &>/dev/null; then
  echo "    Already exists — skipping"
else
  gsutil mb -p "${PROJECT_ID}" -l "${REGION}" "gs://${BUCKET_NAME}"
  echo "    Created gs://${BUCKET_NAME}"
fi

# Remove any public access
gsutil iam ch -d allUsers "gs://${BUCKET_NAME}" 2>/dev/null || true
gsutil iam ch -d allAuthenticatedUsers "gs://${BUCKET_NAME}" 2>/dev/null || true

# SA read access
gsutil iam ch "serviceAccount:${SA_EMAIL}:objectViewer" "gs://${BUCKET_NAME}"
echo "    SA granted objectViewer"

echo ""
echo "    Upload recording.cast:"
echo "    gsutil cp ~/DevProjects/snorkel_tasks/jobs/2026-02-21__13-52-18/lis-swap-contamination-triage__HsPAVBJ/agent/recording.cast \\"
echo "              gs://${BUCKET_NAME}/recording.cast"
echo ""

# ---------------------------------------------------------------------------
# 5. Workload Identity Federation for GitHub Actions (keyless)
# ---------------------------------------------------------------------------
echo "--- [5/6] Workload Identity Federation ---"

# Create pool
if gcloud iam workload-identity-pools describe "${WIF_POOL}" \
     --location=global --project="${PROJECT_ID}" &>/dev/null; then
  echo "    Pool already exists — skipping"
else
  gcloud iam workload-identity-pools create "${WIF_POOL}" \
    --location=global \
    --display-name="GitHub Actions pool" \
    --project="${PROJECT_ID}"
fi

# Create provider
if gcloud iam workload-identity-pools providers describe "${WIF_PROVIDER}" \
     --workload-identity-pool="${WIF_POOL}" \
     --location=global --project="${PROJECT_ID}" &>/dev/null; then
  echo "    Provider already exists — skipping"
else
  gcloud iam workload-identity-pools providers create-oidc "${WIF_PROVIDER}" \
    --workload-identity-pool="${WIF_POOL}" \
    --location=global \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository=='${GITHUB_REPO}'" \
    --project="${PROJECT_ID}"
fi

# Allow GitHub Actions to impersonate the SA
WIF_MEMBER="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/attribute.repository/${GITHUB_REPO}"

gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="${WIF_MEMBER}" \
  --project="${PROJECT_ID}" \
  --quiet

# Also allow SA to deploy Cloud Run and push images
for ROLE in \
  "roles/run.admin" \
  "roles/artifactregistry.writer" \
  "roles/iam.serviceAccountUser"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --condition=None \
    --quiet
  echo "    Granted ${ROLE} (for CI/CD)"
done

WIF_PROVIDER_FULL="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/providers/${WIF_PROVIDER}"
echo ""
echo "    Add these GitHub Actions secrets to alexrabo/LISAgentValidation:"
echo "    GCP_PROJECT_ID               = ${PROJECT_ID}"
echo "    GCP_SERVICE_ACCOUNT          = ${SA_EMAIL}"
echo "    GCP_WORKLOAD_IDENTITY_PROVIDER = ${WIF_PROVIDER_FULL}"
echo "    GCS_BUCKET                   = ${BUCKET_NAME}"
echo ""

# ---------------------------------------------------------------------------
# 6. Local SA key for development
# ---------------------------------------------------------------------------
echo "--- [6/6] Local dev SA key ---"
KEY_PATH="$(dirname "$0")/config/sa_key.json"

if [[ -f "${KEY_PATH}" ]]; then
  echo "    Already exists — skipping"
else
  mkdir -p "$(dirname "${KEY_PATH}")"
  gcloud iam service-accounts keys create "${KEY_PATH}" \
    --iam-account="${SA_EMAIL}" \
    --project="${PROJECT_ID}"
  echo "    Written to ${KEY_PATH} (gitignored)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Setup complete."
echo ""
echo "Resources:"
echo "  SA           : ${SA_EMAIL}"
echo "  AR repo      : ${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}"
echo "  GCS bucket   : gs://${BUCKET_NAME}"
echo "  WIF provider : ${WIF_PROVIDER_FULL}"
echo "  Local SA key : ${KEY_PATH}"
echo ""
echo "Next steps:"
echo "  1. Upload recording.cast (command above)"
echo "  2. Add GitHub Actions secrets (values above)"
echo "  3. Push to master — deploy.yml handles the rest"
echo "============================================"
