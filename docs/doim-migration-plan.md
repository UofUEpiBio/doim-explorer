# DOIM Explorer migration checklist

This is the canonical progress record for the migration from InsightNet Explorer to an unofficial
University of Utah Department of Internal Medicine explorer. Agents must update evidence in the same
commit as a completed item.

## 1. Project setup, reusable library, and progress tracking

- [x] **P0.1 Save the checklist.** Evidence: this document.
- [x] **P0.2 Update agent protocol.** Evidence: `AGENTS.md` requires checklist-first work and the
  existing Codex co-author trailer.
- [x] **P0.3 Repair the deterministic cache test.** Evidence: `MemoryLedger` receives the same
  injected clock as `Guard`; `uv run --locked pytest` passes.
- [x] **P1.1 Create reusable project.** Evidence: [research-explorer-core v0.2.1](https://github.com/UofUEpiBio/research-explorer-core/releases/tag/v0.2.1).
- [x] **P1.2 Extract site-independent code.** Evidence: the core package owns HTTP collection,
  publications, text normalization, and retrieval; this repository imports it as a pinned dependency.
- [x] **P1.3 Define stable interfaces.** Evidence: `research_explorer.models` exports directory,
  faculty, publication, health, and adapter records/protocols; v0.2.0 normalizes legacy snapshots
  at the boundary while the core pipeline uses flat `divisions` and `faculty` records.
- [x] **P1.4 Keep application concerns local.** Evidence: `doim_explorer` retains TOML loading,
  snapshot publication, and CLI orchestration; `server` retains FastAPI and budget policy.
- [x] **P1.5 Release and pin the core.** Evidence: `pyproject.toml` and `uv.lock` pin v0.2.1.
- [x] **P1.6 Rename internal package and commands.** Evidence: `doim_explorer` and the `doim-*`
  console commands replace the `insightnet` package and commands.

## 2. DOIM content and branding

- [x] **P2.1 Configure department, divisions, and faculty sources.** Evidence:
  [`config/directory.toml`](../config/directory.toml) is a versioned manifest for the official
  department and all 12 official division primary-faculty directories, cross-checked against the
  [department system summary](https://medicine.utah.edu/internal-medicine/about/system-summary);
  `uv run --locked pytest tests/test_config.py` passes its manifest coverage and validation tests.
- [x] **P2.2 Build versioned directory and publication contracts.** Evidence:
  [`doim_explorer/contracts.py`](../doim_explorer/contracts.py) publishes and validates the
  `doim-directory`, `doim-publications`, and `doim-publication-details` documents; the
  [`data-contract guide`](doim-data-contracts.md) records their fields and migration aliases;
  `uv run --locked pytest` passes the contract and full-suite coverage.
- [x] **P2.3 Replace InsightNet views with DOIM faculty, expertise, publications, Ask, and data status.**
  Evidence: [`site/index.html`](../site/index.html) and [`site/assets/app.js`](../site/assets/app.js)
  expose the six DOIM views and consume only the versioned directory/publication documents;
  `doim-directory` and `doim-publications` publish matching canonical/static documents; `uv run
  --locked pytest` passes the full UI, contract, and publication coverage.
- [x] **P2.4 Add configurable unofficial/official branding, CSS variables, assets, and analytics.** Evidence: [`config/branding.toml`](../config/branding.toml) and `doim-branding` publish the configurable site identity, official link, disclaimer, theme tokens, local assets, and opt-in GA4 setting; [`doim-branding.md`](doim-branding.md) records the University-mark approval boundary; `uv run --locked pytest` passes 145 tests.

## 3. Faculty scraper and publications

- [x] **P3.1 Implement all 12 primary-faculty source adapters.** Evidence:
  [`doim_explorer/directory.py`](../doim_explorer/directory.py) registers a
  `PrimaryFacultySourceAdapter` for every configured division and explicitly selects
  the primary-only layout (including the dedicated Infectious Diseases layout); `uv
  run --locked pytest tests/test_directory.py` passes primary/adjunct isolation and
  all-12 adapter coverage.
- [x] **P3.2 Extract public faculty profile text, stable IDs, and source health.** Evidence:
  [`doim_explorer/directory.py`](../doim_explorer/directory.py) enriches each public
  profile with biography, academic information, ORCID, and the University-maintained
  profile identifier while emitting one health record per division;
  [`data/directory.json`](../data/directory.json) is the initial profile-only
  pull with 500 faculty and 12 successful source rows; `uv run --locked pytest
  tests/test_directory.py` passes the enrichment and health fixtures.
- [x] **P3.3 Generate University of Utah-affiliation PubMed queries with overrides.** Evidence:
  `build_pubmed_query` scopes generated author queries to the configured University of
  Utah affiliation terms, while `apply_pubmed_queries` accepts exact per-faculty
  overrides; the query and override tests in `tests/test_directory.py` pass.
- [x] **P3.4 Add weekly guarded data pull requests and count/drop guardrails.** Evidence:
  [`refresh-doim-directory.yml`](../.github/workflows/refresh-doim-directory.yml) runs
  weekly and opens a reviewable pull request; `doim-directory --collect --strict`
  applies total/per-division 25% drop and minimum-count guards, covered by
  `tests/test_directory.py` and `tests/test_doim_refresh.py`.

## 4. Human-maintained faculty configuration

- [x] **P4.1 Define versioned faculty overrides.** Evidence:
  [`config/faculty-overrides.toml`](../config/faculty-overrides.toml) is a sparse,
  versioned TOML layer keyed by stable University faculty ID; `load_faculty_overrides`
  permits only documented editorial fields and rejects attempts to alter the official
  roster, profile URL, or division membership; `uv run --locked pytest tests/test_config.py`
  passes valid and invalid override coverage.
- [x] **P4.2 Apply overrides deterministically.** Evidence:
  [`doim_explorer/directory.py`](../doim_explorer/directory.py) overlays validated
  values after public-profile enrichment and before generated PubMed queries, preserves
  omitted values, honors cleared optional strings, and fails orphan IDs; the directory
  contract remains the JSON source for the browser and publication pipeline; `uv run
  --locked pytest tests/test_directory.py tests/test_contracts.py` passes precedence,
  clearing, expertise, and orphan coverage.
- [x] **P4.3 Make publication policy configurable.** Evidence:
  [`config/directory.toml`](../config/directory.toml) schema version 2 exposes validated
  `[publications]` limits, while `DIRECTORY_DOCUMENT_SCHEMA_VERSION` keeps the published
  `doim-directory` JSON schema at version 1; the legacy `pubmed.overrides` map is rejected
  in favor of faculty overrides; `uv run --locked pytest tests/test_config.py` passes policy
  validation coverage.
- [x] **P4.4 Verify and document the editing workflow.** Evidence:
  [`doim-faculty-overrides.md`](doim-faculty-overrides.md) and `README.md` explain
  TOML editing, regeneration, review, clearing, and strict-refresh behavior;
  `tests/test_static_site.py` confirms the browser continues to consume only JSON; `uv run
  --locked ruff check doim_explorer tests` and `uv run --locked pytest` pass (170 tests).

## 5. Google Cloud and GitHub Actions

- [x] **P5.1 Add the gcloud-first bootstrap runbook and idempotent script.** Evidence:
  [`doim-gcloud-bootstrap.md`](doim-gcloud-bootstrap.md) documents the preview/apply and
  verification procedure; [`bootstrap-doim.sh`](../infra/gcloud/bootstrap-doim.sh) idempotently
  provisions the private foundation without service-account keys; `uv run --locked pytest
  tests/test_gcloud_bootstrap.py` passes syntax and credential-free dry-run coverage.
- [x] **P5.2 Provision the separately named `doim-*` Cloud Run, Artifact Registry, Firestore, and WIF resources.** Evidence:
  the 2026-09-21 applied-project verification returned `doim-ask`, the `doim` Docker
  repository, `FIRESTORE_NATIVE`, and the repository-scoped `doim-github/github` provider;
  read-only IAM checks confirmed the `doim-ask` and `doim-deploy` accounts, runtime Vertex/
  Firestore roles, deploy Cloud Run/Artifact Registry roles, runtime-account impersonation, and
  the `UofUEpiBio/doim-explorer` WIF principal binding. The credential-free bootstrap coverage in
  `tests/test_gcloud_bootstrap.py` passes.
- [x] **P5.3 Configure GitHub variables/secrets and deploy the AI service.** Evidence:
  GitHub Actions has the five documented repository variables and the `IP_SALT` secret;
  [`deploy-doim-ask.yml`](../.github/workflows/deploy-doim-ask.yml) authenticates through WIF,
  rejects unsafe retrieval indexes, publishes an immutable image, and uses Cloud Run's
  service-scoped public-access setting. [Deployment run 35626983130](https://github.com/UofUEpiBio/doim-explorer/actions/runs/35626983130)
  passed every step; revision `doim-ask-00003-k7q` serves 100% of traffic with the invoker IAM
  check disabled, and its public `/readyz` response reported 512 indexed chunks. Artifact Registry
  resolved the deployed image to digest
  `sha256:dc6176cb408177cadaf11d599458eb791d00141456961fc89b41ad2e7c716e8e`;
  `uv run --locked pytest tests/test_deploy_doim_ask_workflow.py tests/test_gcloud_bootstrap.py`
  and the workflow YAML parse pass.
- [x] **P5.4 Replace existing workflows with CI, guarded refresh, Pages, deploy, and auth checks.**
  Evidence: [`ci.yml`](../.github/workflows/ci.yml) runs locked dependency installation, Ruff,
  and the full test suite for pull requests and `main`; [`refresh-doim-directory.yml`](../.github/workflows/refresh-doim-directory.yml)
  retains strict weekly collection and reviewable pull-request creation; and
  [`deploy-pages.yml`](../.github/workflows/deploy-pages.yml) publishes only reviewed `main`
  content. [`deploy-doim-ask.yml`](../.github/workflows/deploy-doim-ask.yml) supplies the
  deployment path, while [`verify-doim-auth.yml`](../.github/workflows/verify-doim-auth.yml)
  verifies WIF without a service-account key. On commit `052676b`, [CI run 35627818786](https://github.com/UofUEpiBio/doim-explorer/actions/runs/35627818786),
  [WIF check 35627833656](https://github.com/UofUEpiBio/doim-explorer/actions/runs/35627833656),
  and [Pages deployment 35627836876](https://github.com/UofUEpiBio/doim-explorer/actions/runs/35627836876)
  all passed; the Pages endpoint returned HTTP 200. `uv run --locked ruff check doim_explorer
  server tests`, `uv run --locked pytest` (178 passed), static workflow coverage, and YAML parsing
  pass.

## 6. Verification and release

- [ ] **P6.1 Add source, schema, publication-identity, UI, RAG, and cloud smoke coverage.**
- [ ] **P6.2 Review the initial data pull request and complete release acceptance.**
