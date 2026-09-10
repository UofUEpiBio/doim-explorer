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
department/division URLs, affiliation terms used for PubMed queries, and any
hand-reviewed query overrides. `config/branding.toml` contains the public site identity.

The reusable collection, publication, and retrieval implementation is provided by
`research-explorer-core` v0.2.1. The local sibling checkout at
`../research-explorer-core` is the same release commit pinned by this project; keeping
the Git pin makes installs and GitHub Actions reproducible.

Historical InsightNet configuration and workflows are retained only under
`legacy/insightnet/`; they are not part of the active DOIM refresh.
