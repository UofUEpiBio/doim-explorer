# Faculty metadata overrides

`config/faculty-overrides.toml` is the editable layer for sparse, reviewed corrections
and enrichment of the public University of Utah Department of Internal Medicine faculty
directory. The weekly collector remains the authority for which faculty appear, their
profile URL, and their division membership. Do not edit `data/directory.json` or
`site/data/directory.json`: both are generated and will be replaced on the next refresh.

## Add or update an override

Use the stable University profile ID from the collected faculty record or its profile
URL. For example, `/faculty/mddetail/u0012345` is configured as `u0012345`:

```toml
[faculty.u0012345]
full_name = "Primary Faculty, MD" # optional correction; cannot be blank
title = "Professor of Medicine"   # optional source-text correction
bio = "A reviewed public summary."
academic_information = "Departments Primary - Internal Medicine"
expertise = ["implementation science", "health equity"]
orcid_id = "0000-0002-1825-0097"
pubmed_query = "\"Faculty P\"[Author] AND \"University of Utah\"[Affiliation]"
arxiv_query = "au:\"Faculty, P\""
collect_publications = false
```

Every field is optional. Omit a field to retain its collected value; set an optional text
field to `""` to clear it, and set `expertise = []` to clear its tags. An empty
`pubmed_query` returns to generated affiliation-query behavior, while an empty
`arxiv_query` clears that optional query. Each ORCID must be a valid bare identifier, and
`collect_publications` must be a TOML boolean.

An override whose ID is not present in a collected refresh fails that refresh. This makes
a departed faculty member or changed profile identifier a reviewable event instead of a
silently stale correction.

## Refresh and review

After editing TOML, run:

```bash
uv run --locked doim-directory --collect --strict
```

The command validates both configuration files, collects the official pages, applies the
overrides after profile enrichment, generates any missing PubMed queries, and writes the
reviewable JSON snapshots. Review the resulting `data/directory.json` and
`site/data/directory.json` diff before committing. To validate a non-default override
file, pass `--faculty-overrides path/to/file.toml`; pass an empty value to disable the
editorial layer for a diagnostic run.

## Refresh only changed faculty

After an override is accepted, use the stable ID to update just that faculty rather than collecting
the entire directory and publication corpus:

```bash
export RESEARCH_EXPLORER_CONTACT_EMAIL='you@utah.edu'
GOOGLE_CLOUD_PROJECT="$GCP_PROJECT" uv run --locked doim-refresh --faculty-ids u0012345,u0076543
```

This refetches only the listed public profiles, applies their TOML rows, then queries their enabled
Europe PMC, ORCID, PubMed, and arXiv sources. Existing active-faculty publications and health rows
are retained; shared publications keep every known faculty relationship. The complete RAG index is
rewritten from accepted documents, but only new or changed chunks are embedded. The command fails
without an accepted prior snapshot, for an unknown ID, or when a requested profile/publication source
is blocked or errors.

For GitHub Actions, merge the TOML edit first, then use **Refresh selected DOIM faculty** and provide
the same comma/whitespace-separated IDs. It opens a review PR; merging it deploys Pages and the Ask
container through the existing main-branch workflows.

## Publication policy

`config/directory.toml` uses schema version 2. Its `[publications]` table controls the
values published with the directory and consumed by publication collection:

```toml
[publications]
max_publications_per_faculty = 100
publication_retention_years = 15
abstract_max_chars = 1500
```

All values must be positive integers. Exact PubMed queries no longer live in the directory
manifest's legacy `pubmed.overrides` map; put them in the corresponding faculty override.
