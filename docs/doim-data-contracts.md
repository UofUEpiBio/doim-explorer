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
| `settings` | Publication limits supplied to the collector. |
| `divisions` | Flat `Division` records: stable `id`, `name`, `source_url`, `faculty_url`, and optional `summary`. |
| `faculty` | Flat `Faculty` records: stable `id`, `full_name`, `profile_url`, `division_ids`, profile text, identifiers, and collection choices. |
| `health` | Per-source collection reports. It is empty before the faculty adapters run. |
| `stats` | Counts for `divisions` and `faculty`. |

Faculty records may span divisions. Every entry in `faculty.division_ids` must name an
ID in `divisions`; IDs are unique in both collections. P3 supplies faculty and source
health through this document instead of reintroducing the old center/researcher shape.

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
