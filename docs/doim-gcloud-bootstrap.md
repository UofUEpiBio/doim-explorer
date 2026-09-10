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

## Preview, then apply

The default is dry-run and makes no `gcloud` calls. It is safe to run locally or in code review:

```bash
bash infra/gcloud/bootstrap-doim.sh \
  --project YOUR_DOIM_PROJECT_ID \
  --github-owner UofUEpiBio \
  --github-repo doim-explorer
```

After reviewing the commands, apply them to an existing, billed project:

```bash
bash infra/gcloud/bootstrap-doim.sh \
  --project YOUR_DOIM_PROJECT_ID \
  --billing-account YOUR_BILLING_ACCOUNT_ID \
  --github-owner UofUEpiBio \
  --github-repo doim-explorer \
  --apply
```

To create the dedicated project in an organization and attach billing in the same run, add
`--create-project --organization YOUR_ORG_ID`. The billing account is required in that mode. Do
not use a shared project: the default Firestore database's location is immutable and cannot be
renamed to `doim-*`.

The script is idempotent. On a later run it describes uniquely named resources before creating
them and reasserts additive IAM grants. It never replaces a live Cloud Run image; an existing
`doim-ask` service is updated only with its safe shape and non-secret base configuration.

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
PROJECT=YOUR_DOIM_PROJECT_ID
REGION=us-central1

gcloud run services describe doim-ask --project="$PROJECT" --region="$REGION" \
  --format='value(metadata.name)'
gcloud artifacts repositories describe doim --project="$PROJECT" --location="$REGION" \
  --format='value(name)'
gcloud firestore databases describe --project="$PROJECT" --database='(default)' \
  --format='value(type)'
gcloud iam workload-identity-pools providers describe github --project="$PROJECT" \
  --location=global --workload-identity-pool=doim-github --format='value(name)'
```

The final output of the bootstrap script contains the `WIF_PROVIDER` and
`WIF_SERVICE_ACCOUNT` values needed in the next step. Configure those as GitHub Actions secrets,
then use the deployment workflow to publish the real image and its `IP_SALT`; do not paste either
value into tracked files.
