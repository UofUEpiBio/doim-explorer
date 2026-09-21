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
collects the public faculty directory weekly and proposes its guarded snapshot in a pull request;
it never publishes an unreviewed refresh. Once that pull request is merged, its `site/data` change
starts [`deploy-pages.yml`](.github/workflows/deploy-pages.yml) for the reviewed `main` content.

[`deploy-doim-ask.yml`](.github/workflows/deploy-doim-ask.yml) uses Workload Identity Federation
(WIF) to publish and deploy the DOIM Ask image when its application or retrieval-index inputs
change. Run [`verify-doim-auth.yml`](.github/workflows/verify-doim-auth.yml) manually whenever a
Google Cloud or GitHub Actions setting changes; it verifies that the WIF-backed deploy identity can
inspect the DOIM Artifact Registry repository and Cloud Run service without using a long-lived key.
