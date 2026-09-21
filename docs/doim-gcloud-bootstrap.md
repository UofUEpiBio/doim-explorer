# DOIM Explorer Google Cloud bootstrap

`infra/gcloud/bootstrap-doim.sh` is the gcloud-first, repeatable foundation for the DOIM Explorer
AI service. It provisions a dedicated project's APIs, two service accounts, Artifact Registry,
Firestore Native, Workload Identity Federation (WIF), and a **private** `doim-ask` Cloud Run
placeholder. It does not create a service-account key, collect any secret, or make the endpoint
public.

The legacy InsightNet Terraform configuration under `infra/terraform/` is not a DOIM deployment
mechanism. Do not apply it to a DOIM project: it names old `insightnet-*` resources and trusts the
wrong GitHub repository.

## Before you run it

Use a dedicated project, because Firestore's required `(default)` database and public-access
policy have project-wide consequences. Install the Google Cloud CLI, authenticate as an operator,
and select the intended billing account:

```bash
gcloud auth login
gcloud billing accounts list
gcloud organizations list
```

The operator needs permission to enable services; create service accounts, Artifact Registry,
Firestore, Cloud Run, WIF, and the listed project IAM bindings. A newly created project also needs
project-creation permission in its organization and permission to attach the billing account. The
script deliberately does not attempt an organization-level Domain Restricted Sharing exception;
ask the organization administrator to approve that separately before P5.3 makes the service
public.

Choose the precise GitHub repository before continuing. WIF accepts only that repository's OIDC
claims, so changing an owner or repository later means updating the provider condition and
impersonation binding deliberately.

## Project identifiers and local variables

`--project` always takes the **project ID**: the lowercase, hyphenated identifier chosen when
the project is created (for example, `my-doim-explorer-2026`). It does not accept the numeric
project number. The project number is a different identifier used internally by Google Cloud;
seeing it in the canonical Workload Identity Federation provider name is expected.

Keep account, organization, and project values in the current shell instead of adding them to
tracked files:

```bash
export PROJECT_ID='YOUR_DOIM_PROJECT_ID'
export REGION='us-central1'

printf 'Billing account ID: ' >&2
read -r -s ACCOUNT_ID
printf '\n' >&2
export ACCOUNT_ID

printf 'Organization ID: ' >&2
read -r ORGANIZATION_ID
export ORGANIZATION_ID
```

The interactive entry avoids placing the billing-account value in shell history. These exports
disappear when the shell closes. Do not commit them, put them in a tracked `.env` file, or use
the project number as `PROJECT_ID`.

## Preview, then apply

The default is dry-run and makes no `gcloud` calls. It is safe to run locally or in code review:

```bash
bash infra/gcloud/bootstrap-doim.sh \
  --project "$PROJECT_ID" \
  --github-owner UofUEpiBio \
  --github-repo doim-explorer
```

After reviewing the commands, apply them to an existing, billed project:

```bash
bash infra/gcloud/bootstrap-doim.sh \
  --project "$PROJECT_ID" \
  --billing-account "$ACCOUNT_ID" \
  --github-owner UofUEpiBio \
  --github-repo doim-explorer \
  --apply
```

To create the dedicated project in an organization and attach billing in the same run, use:

```bash
bash infra/gcloud/bootstrap-doim.sh \
  --project "$PROJECT_ID" \
  --create-project \
  --organization "$ORGANIZATION_ID" \
  --billing-account "$ACCOUNT_ID" \
  --github-owner UofUEpiBio \
  --github-repo doim-explorer \
  --apply
```

The billing account is required in that mode. Do not use a shared project: the default Firestore
database's location is immutable and cannot be renamed to `doim-*`.

The script is idempotent. On a later run it describes uniquely named resources before creating
them and reasserts additive IAM grants. It never replaces a live Cloud Run image; an existing
`doim-ask` service is updated only with its safe shape and non-secret base configuration.

Immediately after creating a project or enabling Google APIs, Artifact Registry creation can
briefly return `PERMISSION_DENIED` even when the operator has the required role. Wait for IAM and
API propagation, then rerun the exact same `--apply` command; the idempotent checks resume from
the resources already created. If the failure persists, confirm the active account and project
roles before asking an organization administrator to check organization policies:

```bash
gcloud auth list --filter=status:ACTIVE --format='value(account)'
gcloud projects get-iam-policy "$PROJECT_ID" \
  --flatten='bindings[].members' \
  --filter="bindings.members:user:$(gcloud auth list --filter=status:ACTIVE --format='value(account)')" \
  --format='table(bindings.role)'
```

## What it creates

| Resource | Name | Purpose |
| --- | --- | --- |
| Cloud Run | `doim-ask` | Private placeholder for the DOIM Ask service; 0–3 instances, 8 concurrency, 60-second timeout. |
| Artifact Registry | `doim` | Docker repository for immutable DOIM Ask images. |
| Firestore Native | `(default)` | Rate limits, spend ledger, and answer cache in the dedicated DOIM project. |
| Runtime service account | `doim-ask` | Vertex AI and Firestore access at runtime. |
| Deploy service account | `doim-deploy` | GitHub Actions deployment identity; it may push images and launch revisions as the runtime account. |
| WIF pool/provider | `doim-github` / `github` | Exchanges GitHub OIDC only for the selected `OWNER/REPOSITORY`. |

The deploy service account has `aiplatform.user` for a future index-build workflow. It does not
receive Firestore access. The runtime service account cannot deploy Cloud Run or write images.

## Verify the applied foundation

Run these after an `--apply`; each should return exactly the named DOIM resource:

```bash
PROJECT_ID='YOUR_DOIM_PROJECT_ID'
REGION='us-central1'

gcloud run services describe doim-ask --project="$PROJECT_ID" --region="$REGION" \
  --format='value(metadata.name)'
gcloud artifacts repositories describe doim --project="$PROJECT_ID" --location="$REGION" \
  --format='value(name)'
gcloud firestore databases describe --project="$PROJECT_ID" --database='(default)' \
  --format='value(type)'
gcloud iam workload-identity-pools providers describe github --project="$PROJECT_ID" \
  --location=global --workload-identity-pool=doim-github --format='value(name)'
```

The expected values are `doim-ask`, the `doim` repository path, `FIRESTORE_NATIVE`, and the
canonical WIF provider name. That final provider path contains the numeric project number; this
is normal and does not change the requirement to use `PROJECT_ID` with every `--project` flag.

The final output of the bootstrap script contains the `WIF_PROVIDER` and
`WIF_SERVICE_ACCOUNT` values needed in the next step. They are resource identifiers rather than
credentials, so configure them as GitHub Actions repository variables along with `GCP_PROJECT`,
`GCP_REGION`, and `ALLOWED_ORIGINS`. Only `IP_SALT` needs to be a repository secret.

The `doim-ask` placeholder runs on serverless Cloud Run, not a user-managed Compute Engine VM.
It can scale to zero and the bootstrap script limits it to three ephemeral instances.

## Configure GitHub Actions with `gh`

Authenticate `gh` with an account that can manage Actions settings for the repository, then run
the following from any Bash shell with an authenticated `gcloud` CLI. Change the values at the
top if the project, region, repository, or Pages origin differs:

```bash
set -euo pipefail

PROJECT_ID='YOUR_DOIM_PROJECT_ID'
REGION='us-central1'
GH_REPO='UofUEpiBio/doim-explorer'
ALLOWED_ORIGINS='https://uofuepibio.github.io'
DEPLOY_SERVICE_ACCOUNT="doim-deploy@${PROJECT_ID}.iam.gserviceaccount.com"

gh auth status
gh repo view "$GH_REPO" --json nameWithOwner --jq '.nameWithOwner'

WIF_PROVIDER="$(
  gcloud iam workload-identity-pools providers describe github \
    --project="$PROJECT_ID" \
    --location=global \
    --workload-identity-pool=doim-github \
    --format='value(name)'
)"
WIF_SERVICE_ACCOUNT="$(
  gcloud iam service-accounts describe "$DEPLOY_SERVICE_ACCOUNT" \
    --project="$PROJECT_ID" \
    --format='value(email)'
)"

test -n "$WIF_PROVIDER"
test -n "$WIF_SERVICE_ACCOUNT"

gh variable set GCP_PROJECT --repo "$GH_REPO" --body "$PROJECT_ID"
gh variable set GCP_REGION --repo "$GH_REPO" --body "$REGION"
gh variable set ALLOWED_ORIGINS --repo "$GH_REPO" --body "$ALLOWED_ORIGINS"
gh variable set WIF_PROVIDER --repo "$GH_REPO" --body "$WIF_PROVIDER"
gh variable set WIF_SERVICE_ACCOUNT --repo "$GH_REPO" --body "$WIF_SERVICE_ACCOUNT"

if [[ "$(gh secret list --repo "$GH_REPO" --json name \
  --jq '.[] | select(.name == "IP_SALT") | .name')" != 'IP_SALT' ]]; then
  openssl rand -hex 32 | tr -d '\n' | gh secret set IP_SALT --repo "$GH_REPO"
fi

gh variable list --repo "$GH_REPO"
gh secret list --repo "$GH_REPO"
```

Rerunning the block updates the five repository variables to match Google Cloud. It deliberately
preserves an existing `IP_SALT`; changing that salt would change the pseudonymous IP hashes used
for rate limiting. The final two commands show names and non-secret variable values for review,
but GitHub never returns the value of `IP_SALT`.
