# DOIM data contracts

The Department of Internal Medicine explorer has two primary, versioned JSON documents.
They use the stable flat records in `research_explorer.models`; application-specific
metadata belongs here rather than in the reusable package.

## Directory document

`doim-directory` writes `data/directory.json` (and optionally its static-site copy).
The document has `document_type: "doim-directory"` and `schema_version: 1`.

| Field | Contract |
|---|---|
| `generated_at` | UTC ISO-8601 timestamp for this document. |
| `department` | Official name, URL, and public summary. |
| `settings` | Publication limits supplied from the versioned TOML manifest. |
| `divisions` | Flat `Division` records: stable `id`, `name`, `source_url`, `faculty_url`, and optional `summary`. |
| `faculty` | Flat `Faculty` records: stable public U of U profile `id`, `full_name`, `profile_url`, `division_ids`, source/profile text, optional curated `expertise`, ORCID, generated/overridden `pubmed_query`, and collection choices. |
| `health` | One report per primary-faculty source after collection: `division_id`, source URL/label, `status` (`ok`, `partial`, `blocked`, or `error`), message, faculty count, and UTC `checked_at`. It is empty before the faculty adapters run. |
| `stats` | Counts for `divisions` and `faculty`. |

Faculty records may span divisions. Every entry in `faculty.division_ids` must name an
ID in `divisions`; IDs are unique in both collections. P3 supplies faculty and source
health through this document instead of reintroducing the old center/researcher shape.
`expertise` is additive and optional for existing schema-version-1 consumers; new
documents publish an empty list when no curator supplies it.

## Publications index and details

The publication builder consumes `directory.json` directly. It emits a
`document_type: "doim-publications"` index, currently at core schema version 2, and a
matching `document_type: "doim-publication-details"` document. The index holds each
publication's public citation fields and canonical `faculty_ids` / `division_ids`;
legacy `researcher_ids` / `organization_ids` remain read-only migration aliases. The
detail document is keyed by publication ID and holds abstracts and full author lists so
the browser can load it only when needed.

`doim_explorer.contracts` validates both documents before they are published. An
incompatible change requires a new schema version and an explicit migration; consumers
must reject a document type or version they do not understand.

## Collaboration network document

`doim-collaboration` reads the accepted `directory.json` and `publications.json` and writes
`data/collaboration.json` (and its static-site copy). The document has
`document_type: "doim-collaboration"` and `schema_version: 1`.

A co-authorship edge exists between two faculty when the publication pipeline attributes the
same work to both of them — that is, when a work's `faculty_ids` (see the publications section
above) names both people. This is the same attribution the Faculty and Publications views
already read; the collaboration document only aggregates it into a graph. Only faculty with at
least one such collaborator become nodes — an isolated dot with no edges belongs to the Faculty
view, not this one — and only where their connected group holds at least
`MIN_COMPONENT_NODES` (5) members. A pair or a triangle floating off the side of the canvas
shows no structure worth reading while costing the main body of the graph the room it is drawn
in, so those groups are pruned before layout. Integrity checks run on the unpruned graph, so a
faculty id the directory does not know is still rejected rather than quietly dropped.

| Field | Contract |
|---|---|
| `generated_at` | UTC ISO-8601 timestamp for this document. |
| `sources` | `directory_generated_at` and `publications_generated_at`, the exact timestamps of the documents this graph was built from. A release check rejects a graph whose `sources` do not match the accepted directory and publications, so a stale graph is caught rather than silently shipped. |
| `stats` | `nodes`, `edges`, `shared_works` (works with ≥2 published faculty), `faculty` (directory total), `components`, `largest_component`, `cross_division_edges`, `capped_faculty` (faculty at the publication collection cap), `max_publications_per_faculty`, `min_component_nodes` (the group-size floor applied to this graph). Every count describes the published graph, after pruning. |
| `divisions` | One entry per division actually present in the directory: `id`, `name`, `color`, `ring`, `faculty` (member count). `color`/`ring` are a validated 12-slot categorical palette (see `doim_explorer/collaboration.py`) assigned in sorted-division-id order, so a division keeps its color across refreshes. |
| `nodes` | One per faculty member with ≥1 collaborator in a surviving group: `id`, `name`, `division_id`, `profile_url`, `publications`, `collaborators` (degree), `shared_works` (sum of edge weights), `component` (0 is the largest connected group), `positions` — `{organic, divisions}`, each an `[x, y]` pair in `[-1, 1]`. |
| `edges` | One per unordered faculty pair with ≥1 shared work: `source`, `target`, `weight` (shared work count), `first_year`, `last_year` (nullable when every shared work lacks a year). |

Layout is precomputed and deterministic: regenerating from the same directory and publications
documents produces byte-identical coordinates, both so the published artifact diffs cleanly
under review and so a refresh does not silently move every dot the browser has already drawn.
`organic` lays the whole graph out with a seeded, weight-aware spring layout; `divisions`
arranges each division's members around a ring so the browser can animate between a
structure-revealing and a roster-revealing view. Neither layout depends on a random number
generator, so the two networkx releases the lock file resolves for Python 3.11 and 3.12 produce
the same output.

The browser vendors the rendering library — see `site/assets/vendor/VENDOR.md` — since it is
the site's one third-party script; loading it stays local, matching the rest of the site's
no-CDN posture.

**A missing edge does not mean two people have not collaborated.** Attribution comes from each
faculty member's own University-of-Utah-affiliation PubMed query (see the publications section
above), not from matching full author lists — that would need author disambiguation this
project does not yet do reliably (only one faculty record carries an ORCID, and the roster
already contains a surname-and-initials collision). `max_publications_per_faculty` also caps
collection per person, which biases the most prolific faculty's `collaborators` count downward.
The Network view states both limits next to the graph.
