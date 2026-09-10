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
