#!/usr/bin/env bash
# Bootstrap the Google Cloud resources for DOIM Explorer.
#
# This script deliberately uses gcloud rather than Terraform.  Its only mutable
# inputs are flags; it does not read credentials or secrets from the repository.
# Run it with --dry-run first and --apply only after reviewing the generated commands.
set -euo pipefail

readonly DEFAULT_REGION="us-central1"
readonly DEFAULT_FIRESTORE_LOCATION="nam5"
readonly DEFAULT_GITHUB_OWNER="UofUEpiBio"
readonly DEFAULT_GITHUB_REPO="doim-explorer"
readonly DEFAULT_ALLOWED_ORIGIN="https://uofuepibio.github.io"
readonly SERVICE_NAME="doim-ask"
readonly RUNTIME_ACCOUNT_ID="doim-ask"
readonly DEPLOY_ACCOUNT_ID="doim-deploy"
readonly REGISTRY_NAME="doim"
readonly WIF_POOL_ID="doim-github"
readonly WIF_PROVIDER_ID="github"
readonly PLACEHOLDER_IMAGE="us-docker.pkg.dev/cloudrun/container/hello"

project_id=""
region="$DEFAULT_REGION"
firestore_location="$DEFAULT_FIRESTORE_LOCATION"
github_owner="$DEFAULT_GITHUB_OWNER"
github_repo="$DEFAULT_GITHUB_REPO"
allowed_origin="$DEFAULT_ALLOWED_ORIGIN"
billing_account=""
organization_id=""
create_project=false
apply=false

usage() {
  cat <<'USAGE'
Usage: infra/gcloud/bootstrap-doim.sh --project PROJECT_ID [options]

Creates or reconciles the Google Cloud foundation for DOIM Explorer. The default is a
dry run: it prints every gcloud mutation without contacting Google Cloud. Pass --apply
only after reviewing it.

Required:
  --project ID                 Dedicated Google Cloud project ID.

Options:
  --apply                      Run the commands. Without this, no gcloud call is made.
  --create-project             Create the project if it does not already exist.
  --organization ID            Organization parent for --create-project.
  --billing-account ID         Link this billing account (required with --create-project).
  --region REGION              Cloud Run and Artifact Registry region (default: us-central1).
  --firestore-location REGION  Firestore Native location (default: nam5; immutable).
  --github-owner OWNER         GitHub owner admitted by WIF (default: UofUEpiBio).
  --github-repo REPOSITORY     GitHub repository admitted by WIF (default: doim-explorer).
  --allowed-origin ORIGIN      Browser origin for Cloud Run CORS (default: https://uofuepibio.github.io).
  -h, --help                   Show this help.

The script creates a private Cloud Run placeholder. The deployment workflow makes the
service public only when the real DOIM image and its configuration are ready.
USAGE
}

die() {
  echo "error: $*" >&2
  exit 2
}

note() {
  echo "==> $*" >&2
}

run() {
  printf '+ '
  printf '%q ' "$@"
  printf '\n'
  if "$apply"; then
    "$@"
  fi
}

while (($#)); do
  case "$1" in
    --project)
      (($# >= 2)) || die "--project needs a value"
      project_id="$2"
      shift 2
      ;;
    --region)
      (($# >= 2)) || die "--region needs a value"
      region="$2"
      shift 2
      ;;
    --firestore-location)
      (($# >= 2)) || die "--firestore-location needs a value"
      firestore_location="$2"
      shift 2
      ;;
    --github-owner)
      (($# >= 2)) || die "--github-owner needs a value"
      github_owner="$2"
      shift 2
      ;;
    --github-repo)
      (($# >= 2)) || die "--github-repo needs a value"
      github_repo="$2"
      shift 2
      ;;
    --allowed-origin)
      (($# >= 2)) || die "--allowed-origin needs a value"
      allowed_origin="$2"
      shift 2
      ;;
    --billing-account)
      (($# >= 2)) || die "--billing-account needs a value"
      billing_account="$2"
      shift 2
      ;;
    --organization)
      (($# >= 2)) || die "--organization needs a value"
      organization_id="$2"
      shift 2
      ;;
    --create-project)
      create_project=true
      shift
      ;;
    --apply)
      apply=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ -n "$project_id" ]] || die "--project is required"
[[ "$project_id" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || die "invalid project ID: $project_id"
[[ "$region" =~ ^[a-z]+-[a-z]+[0-9]$ ]] || die "invalid region: $region"
[[ "$firestore_location" =~ ^[a-z0-9-]+$ ]] || die "invalid Firestore location: $firestore_location"
[[ "$github_owner" =~ ^[A-Za-z0-9-]+$ ]] || die "invalid GitHub owner: $github_owner"
[[ "$github_repo" =~ ^[A-Za-z0-9_.-]+$ ]] || die "invalid GitHub repository: $github_repo"
[[ "$allowed_origin" =~ ^https://[^/]+$ ]] || die "--allowed-origin must be an https origin without a path"

if "$create_project"; then
  [[ -n "$organization_id" ]] || die "--create-project requires --organization"
  [[ -n "$billing_account" ]] || die "--create-project requires --billing-account"
fi

if ! "$apply"; then
  note "dry run: no gcloud calls will be made"
fi

if "$apply"; then
  command -v gcloud >/dev/null || die "gcloud is not installed or not on PATH"
  gcloud auth list --filter='status:ACTIVE' --format='value(account)' | grep -q . \
    || die "no active gcloud account; run 'gcloud auth login' first"

  if ! gcloud projects describe "$project_id" --format='value(projectNumber)' >/dev/null 2>&1; then
    "$create_project" || die "project $project_id does not exist (use --create-project to create it)"
    run gcloud projects create "$project_id" --organization="$organization_id" --quiet
  fi
fi

if [[ -n "$billing_account" ]]; then
  run gcloud billing projects link "$project_id" --billing-account="$billing_account" --quiet
fi

run gcloud services enable \
  run.googleapis.com \
  aiplatform.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  --project="$project_id" --quiet

if "$apply"; then
  project_number="$(gcloud projects describe "$project_id" --format='value(projectNumber)')"
else
  project_number='<project-number>'
fi

runtime_sa="${RUNTIME_ACCOUNT_ID}@${project_id}.iam.gserviceaccount.com"
deploy_sa="${DEPLOY_ACCOUNT_ID}@${project_id}.iam.gserviceaccount.com"

ensure_service_account() {
  local account_id="$1"
  local display_name="$2"
  local email="${account_id}@${project_id}.iam.gserviceaccount.com"
  if "$apply" && gcloud iam service-accounts describe "$email" --project="$project_id" >/dev/null 2>&1; then
    note "service account exists: $email"
  else
    run gcloud iam service-accounts create "$account_id" --display-name="$display_name" \
      --project="$project_id" --quiet
  fi
}

ensure_service_account "$RUNTIME_ACCOUNT_ID" "DOIM Explorer Cloud Run runtime"
ensure_service_account "$DEPLOY_ACCOUNT_ID" "DOIM Explorer GitHub deployment"

ensure_project_role() {
  local member="$1"
  local role="$2"
  run gcloud projects add-iam-policy-binding "$project_id" --member="$member" --role="$role" --quiet
}

ensure_project_role "serviceAccount:$runtime_sa" roles/aiplatform.user
ensure_project_role "serviceAccount:$runtime_sa" roles/datastore.user
ensure_project_role "serviceAccount:$deploy_sa" roles/run.admin
ensure_project_role "serviceAccount:$deploy_sa" roles/aiplatform.user

if "$apply" && gcloud artifacts repositories describe "$REGISTRY_NAME" --location="$region" \
  --project="$project_id" >/dev/null 2>&1; then
  note "Artifact Registry repository exists: $REGISTRY_NAME"
else
  run gcloud artifacts repositories create "$REGISTRY_NAME" --repository-format=docker --location="$region" \
    --description="DOIM Explorer Cloud Run images" --project="$project_id" --quiet
fi

run gcloud artifacts repositories add-iam-policy-binding "$REGISTRY_NAME" --location="$region" \
  --project="$project_id" --member="serviceAccount:$deploy_sa" --role=roles/artifactregistry.writer --quiet

run gcloud iam service-accounts add-iam-policy-binding "$runtime_sa" \
  --member="serviceAccount:$deploy_sa" --role=roles/iam.serviceAccountUser --project="$project_id" --quiet

if "$apply" && gcloud firestore databases describe --database='(default)' --project="$project_id" \
  >/dev/null 2>&1; then
  note "Firestore database exists: (default)"
else
  run gcloud firestore databases create --database='(default)' --location="$firestore_location" \
    --type=firestore-native --project="$project_id" --quiet
fi

if "$apply" && gcloud iam workload-identity-pools describe "$WIF_POOL_ID" --location=global \
  --project="$project_id" >/dev/null 2>&1; then
  note "Workload Identity pool exists: $WIF_POOL_ID"
else
  run gcloud iam workload-identity-pools create "$WIF_POOL_ID" --location=global \
    --display-name="DOIM Explorer GitHub Actions" --project="$project_id" --quiet
fi

if "$apply" && gcloud iam workload-identity-pools providers describe "$WIF_PROVIDER_ID" \
  --workload-identity-pool="$WIF_POOL_ID" --location=global --project="$project_id" >/dev/null 2>&1; then
  note "Workload Identity provider exists: $WIF_PROVIDER_ID"
else
  run gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER_ID" \
    --workload-identity-pool="$WIF_POOL_ID" --location=global --project="$project_id" \
    --display-name="DOIM Explorer GitHub repository" \
    --issuer-uri=https://token.actions.githubusercontent.com \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository == '${github_owner}/${github_repo}'" --quiet
fi

run gcloud iam service-accounts add-iam-policy-binding "$deploy_sa" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${project_number}/locations/global/workloadIdentityPools/${WIF_POOL_ID}/attribute.repository/${github_owner}/${github_repo}" \
  --project="$project_id" --quiet

if "$apply" && gcloud run services describe "$SERVICE_NAME" --region="$region" \
  --project="$project_id" >/dev/null 2>&1; then
  note "Cloud Run service exists: $SERVICE_NAME"
  run gcloud run services update "$SERVICE_NAME" --region="$region" --project="$project_id" \
    --service-account="$runtime_sa" --ingress=all --min=0 --max=3 --concurrency=8 --timeout=60s \
    --cpu=1 --memory=1Gi \
    --update-env-vars="GOOGLE_CLOUD_PROJECT=${project_id},GOOGLE_CLOUD_LOCATION=${region},ALLOWED_ORIGINS=${allowed_origin}" \
    --quiet
else
  run gcloud run deploy "$SERVICE_NAME" --image="$PLACEHOLDER_IMAGE" --region="$region" \
    --project="$project_id" --service-account="$runtime_sa" --ingress=all --no-allow-unauthenticated \
    --min=0 --max=3 --concurrency=8 --timeout=60s --cpu=1 --memory=1Gi \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${project_id},GOOGLE_CLOUD_LOCATION=${region},ALLOWED_ORIGINS=${allowed_origin}" \
    --quiet
fi

cat <<EOF

Bootstrap complete.

Set these GitHub values for the deployment workflow (P5.3):
  GCP_PROJECT=$project_id
  GCP_REGION=$region
  ALLOWED_ORIGINS=$allowed_origin
  WIF_PROVIDER=projects/$project_number/locations/global/workloadIdentityPools/$WIF_POOL_ID/providers/$WIF_PROVIDER_ID
  WIF_SERVICE_ACCOUNT=$deploy_sa
  RESEARCH_EXPLORER_CONTACT_EMAIL=<monitored-contact@example.edu>

The Cloud Run service remains private until the deployment workflow publishes the real image.
EOF
