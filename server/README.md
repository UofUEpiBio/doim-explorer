# DOIM Ask service

A Cloud Run container that answers one narrow question — *which University of Utah Department of
Internal Medicine faculty members can help with topic X* — from the retrieval index committed in
`data/rag/`.

There is **no API key anywhere**. Vertex AI is reached through Application Default Credentials, which on Cloud Run means the service account itself, and in GitHub Actions means a short-lived credential from Workload Identity Federation.

## Layout

| File | Role |
| --- | --- |
| `main.py` | FastAPI app: `POST /ask` (SSE), `GET /healthz`, `GET /readyz` |
| `prompts.py` | System instruction and document rendering |
| `budget.py` | Rate limits, spend accounting, answer cache |
| `config.py` | Every limit and price, read from the environment |

Retrieval is provided by the pinned `research-explorer-core` package and shared with the index
builder, so the ranking built by `doim-rag` is the ranking visitors get. The builder accepts only
the generated DOIM directory and publication contracts; the runtime refuses a legacy index.

## Running locally

The service needs a real index. Build one first (this calls the embedding API):

```bash
GOOGLE_CLOUD_PROJECT=YOUR_DOIM_PROJECT_ID uv run --locked --extra server doim-rag
```

Then:

```bash
ENVIRONMENT=dev uv run --extra server uvicorn server.main:create_app --factory --port 8080
```

`ENVIRONMENT=dev` adds `http://localhost:8000` to the CORS allowlist and swaps Firestore for an in-process ledger, so no database is required.

```bash
curl -N -X POST http://localhost:8080/ask -H 'content-type: application/json' -d '{"question":"who studies infectious diseases?"}'
```

## Configuration

All optional; defaults are in `config.py`.

| Variable | Default | Notes |
| --- | --- | --- |
| `GOOGLE_CLOUD_PROJECT` | — | Required in production |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | |
| `DOIM_MODEL` | `gemini-2.5-flash-lite` | Change without a rebuild |
| `DOIM_EMBED_MODEL` | `gemini-embedding-001` | Change without a rebuild |
| `DOIM_INDEX_DIR` | `data/rag` | Baked into the image |
| `ALLOWED_ORIGINS` | `https://uofuepibio.github.io` | Comma-separated |
| `ENVIRONMENT` | `production` | `dev` relaxes CORS and skips Firestore |
| `IP_MINUTE_LIMIT` | `5` | |
| `IP_DAY_LIMIT` | `40` | |
| `TRUSTED_PROXIES` | — | Comma-separated IPs/CIDRs. Only set it when a proxy you control fronts the service; see below |
| `DAILY_QUERY_CAP` | `400` | Global; returns 503 with `fallback: "keyword"` |
| `MONTHLY_BUDGET_MICROS` | `5000000` | $5. Charged from reported token usage |
| `PRICE_IN_MICROS_PER_MTOK` | `100000` | **Verify against current Vertex AI pricing** |
| `PRICE_OUT_MICROS_PER_MTOK` | `400000` | **Verify against current Vertex AI pricing** |
| `IP_SALT` | `doim-explorer` | Set to the GitHub Actions secret in production |

### Which address the rate limiter counts

Cloud Run *appends* the connecting address to any `X-Forwarded-For` the caller sent, so
`_client_address()` reads the header from the right. The leftmost entry is whatever the caller
typed; trusting it let one client rotate through a fresh rate-limit bucket per request.

`TRUSTED_PROXIES` is for the case where something you operate — an external load balancer, a WAF —
appends an entry of its own, which would otherwise be the address counted. Entries are IPs or CIDRs
(`34.96.0.0/20,10.0.0.0/8`), and the walk skips over addresses matching them until it reaches one
that does not. Naming the hops rather than counting them is what keeps this safe: `--ingress=all`
leaves the `run.app` URL publicly reachable, and a request straight to it arrives as
`<forged>, <real peer>`, so a trusted *count* of two would have selected the forged value. A
forged address is never in the trusted set unless it happens to fall inside a configured range, and
even then the platform-appended peer to its right is checked first. Unparseable entries are logged
and dropped, so a typo narrows trust instead of widening it.

Set it to the edge's egress ranges and restrict ingress to `internal-and-cloud-load-balancing` in
the same change, so the direct URL stops being an alternative path. Leave it unset otherwise.

## Cost controls, in order of how hard they bite

1. `--max-instances=3` on the service — bounds spend even under a flood.
2. The Firestore counters above — fail closed, counted before the model runs.
3. **Vertex AI quota** in *IAM & Admin → Quotas* — the only true hard stop, enforced at Google's edge.
4. A Cloud Billing budget — **alerts, does not stop spend**. Item 3 is the real cap.

`thinking_config.thinking_budget = 0` is set on every request. Gemini 2.5 models think by default and bill thinking at the output rate; leaving it unset roughly triples cost. Thinking tokens are still charged against the budget if the model reports any.

## Reproducing the GCP setup

Use [`docs/doim-gcloud-bootstrap.md`](../docs/doim-gcloud-bootstrap.md) and
[`infra/gcloud/bootstrap-doim.sh`](../infra/gcloud/bootstrap-doim.sh). The archived Terraform
configuration is InsightNet-only and must not be applied to the DOIM project.

## Deploying

[`deploy-doim-ask.yml`](../.github/workflows/deploy-doim-ask.yml) builds the image on the runner,
pushes it straight to Artifact Registry, and deploys with `gcloud run deploy`, authenticating
through Workload Identity Federation. Cloud Build is deliberately not used: `gcloud builds submit`
stages the source in a bucket and needs storage and serviceusage permissions on top, which defeats a
least-privilege deploy identity. The workflow refuses to deploy when `data/rag/` is missing,
vector-free, or derived from legacy data.

Two identities, least privilege:

| Account | Used by | Roles |
| --- | --- | --- |
| `doim-ask@` | Cloud Run runtime | `aiplatform.user`, `datastore.user` |
| `doim-deploy@` | GitHub Actions | `run.admin`, `artifactregistry.writer` on the repo, `iam.serviceAccountUser` on the runtime account, `aiplatform.user` for the index build |

Required GitHub configuration:

- Secret: `IP_SALT`
- Variables: `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`, `GCP_PROJECT`, `GCP_REGION`, `ALLOWED_ORIGINS`

Every workflow that touches Google must declare `permissions: {contents: read, id-token: write}`.
