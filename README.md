# DOIM Explorer

An unofficial, public-data explorer for the University of Utah Department of Internal
Medicine. It presents the department's official division directories, public faculty
profiles, and (after a separate collection step) scholarly publications.

## Refresh the public faculty directory

```bash
uv sync --locked --all-extras --dev
uv run --locked doim-directory --collect --strict
```

The command writes matching versioned documents to `data/directory.json` and
`site/data/directory.json`. It honours robots policies through
`research-explorer-core`, records source health for all 12 divisions, and refuses
an unsafe total or per-division count drop.

Faculty profiles are collected separately from publications. Review the directory diff
before running `doim-publications`; publication collection uses the generated,
University-of-Utah-affiliation PubMed queries in the directory document.

## Incremental faculty refresh

To refresh one or a few accepted faculty records without re-querying the whole department,
provide their stable U of U IDs. The command refetches only those public profiles, applies their
overrides, collects all supported publication sources for them, and rebuilds the complete retrieval
index while reusing vectors for unchanged chunks.

```bash
export RESEARCH_EXPLORER_CONTACT_EMAIL='you@utah.edu'
GOOGLE_CLOUD_PROJECT="$GCP_PROJECT" uv run --locked doim-refresh --faculty-ids u6039184,u0012345
```

The command requires accepted `data/directory.json`, publication documents, and `data/rag/` as its
base. It stages every generated artifact before publishing, retains prior active-faculty publications
until the normal retention limit, and refuses unknown IDs, a profile/source error, or a missing PubMed
contact address. Review and commit its directory, publication, static-site, and RAG changes together.

## Collect publications

PubMed's E-utilities identify every caller by a contact address, so export one before
collecting. Without it each PubMed source is recorded as `skipped` and the run reports
only the publications already retained in the snapshot.

```bash
export RESEARCH_EXPLORER_CONTACT_EMAIL='you@utah.edu'
uv run --locked doim-publications --strict
```

The command writes `data/publications.json`, `data/publication-details.json`, and their
`site/data` copies, merging newly collected works into the retained snapshot. Because the
published retrieval index records the directory and publication timestamps it was built
from, rebuild and commit it whenever either document is regenerated:

```bash
GOOGLE_CLOUD_PROJECT="$GCP_PROJECT" uv run --locked doim-rag
```

## Build the collaboration network

The Network view draws the co-authorship graph between DOIM faculty: an edge exists whenever
the publication pipeline attributes the same work to two of them. Regenerate it whenever the
directory or publications documents change:

```bash
uv run --locked doim-collaboration
```

The command reads the accepted `data/directory.json` and `data/publications.json`, and writes
matching versioned documents to `data/collaboration.json` and `site/data/collaboration.json`.
Only faculty with at least one internal collaborator become nodes; node color groups a division
using a palette validated for both color-vision-deficient and full-color readers (see
`doim_explorer/collaboration.py`). Layout is precomputed and deterministic, so regenerating from
unchanged inputs never moves a dot. `doim-refresh` (above) publishes this document automatically
as part of its own staged commit, so this command is normally only needed after running
`doim-directory`/`doim-publications` directly. See
[`docs/doim-data-contracts.md`](docs/doim-data-contracts.md) for the document's fields and
limitations, and [`site/assets/vendor/VENDOR.md`](site/assets/vendor/VENDOR.md) for the one
third-party library the site loads (vendored locally, not from a CDN) to draw it.

## Configuration

`config/directory.toml` is the active source manifest. It lists the official
department/division URLs, affiliation terms used for PubMed queries, and the publication
collection policy. `config/faculty-overrides.toml` holds sparse, reviewed corrections and
enrichment keyed by University faculty ID; it never duplicates the roster. See
[`docs/doim-faculty-overrides.md`](docs/doim-faculty-overrides.md) for the editing and
refresh workflow. `config/branding.toml` contains the public site identity.

The reusable collection, publication, and retrieval implementation is provided by
`research-explorer-core` v0.2.1. The local sibling checkout at
`../research-explorer-core` is the same release commit pinned by this project; keeping
the Git pin makes installs and GitHub Actions reproducible.

Historical InsightNet configuration and workflows are retained only under
`legacy/insightnet/`; they are not part of the active DOIM refresh.

## GitHub Actions

[`ci.yml`](.github/workflows/ci.yml) runs the locked environment, Ruff, and the full test suite on
pull requests and pushes to `main`. [`refresh-doim-directory.yml`](.github/workflows/refresh-doim-directory.yml)
reconciles division rosters weekly and refreshes every public profile on the first day of January,
March, May, July, September, and November. It queries publication sources only for faculty whose
publication inputs changed, rebuilds the RAG index incrementally, and opens one reviewable artifact
pull request. [`refresh-doim-faculty.yml`](.github/workflows/refresh-doim-faculty.yml) is the manual
equivalent: enter comma/whitespace-separated faculty IDs after their override is on `main`. Both
workflows require the non-secret `RESEARCH_EXPLORER_CONTACT_EMAIL` repository variable. Once a
generated pull request is merged, its `site/data` change starts
[`deploy-pages.yml`](.github/workflows/deploy-pages.yml) for the reviewed `main` content.

[`deploy-doim-ask.yml`](.github/workflows/deploy-doim-ask.yml) uses Workload Identity Federation
(WIF) to publish and deploy the DOIM Ask image when its application or retrieval-index inputs
change. Run [`verify-doim-auth.yml`](.github/workflows/verify-doim-auth.yml) manually whenever a
Google Cloud or GitHub Actions setting changes; it verifies that the WIF-backed deploy identity can
inspect the DOIM Artifact Registry repository and Cloud Run service without using a long-lived key.

After Pages and Cloud Run have rolled out the same accepted commit, run
[`verify-doim-release.yml`](.github/workflows/verify-doim-release.yml). It checks source health,
generated-document schema and publication identity, the committed retrieval-index provenance, the
public Pages documents, Cloud Run readiness, and the browser CORS preflight without sending an Ask
request to Vertex AI. The equivalent local command is:

```bash
uv run --locked doim-release-check
```
