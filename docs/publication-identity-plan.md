# Publication identity reconciliation plan

## Finding

The primary concern is already handled on the normal collection path. The pinned
`research-explorer-core` v0.3.0 normalizes DOI, PubMed, and arXiv identifiers, merges records that
share any of those identifiers, and unions their `faculty_ids` and `division_ids`. The DOIM browser
and retrieval index then consume one work record and retain all of those relationships.

The accepted data confirms that behavior:

- 7,146 work records have 7,146 unique internal IDs and PubMed IDs;
- 7,077 records have a DOI, with no repeated DOI;
- 1,535 records belong to more than one DOIM faculty member, including one record shared by 12;
- the 9,247 faculty-to-publication relationships intentionally exceed the 7,146 unique works; and
- the browser and RAG builder each create one publication card/chunk per work, not one per faculty
  relationship.

Therefore, a shared PubMed ID or DOI is not currently double-counted. A faculty-filtered count is a
relationship count, while the department-wide count is a unique-work count.

There is, however, a narrower integrity gap. `_merge_works_history()` indexes retained records by
identifier but stores them by their prior internal IDs. If a previous snapshot already contains two
different internal records with the same DOI or PMID, an incremental reconciliation preserves both.
The DOIM release check rejects repeated internal IDs but does not reject repeated DOI, PMID, or arXiv
identities. A malformed migration, manual edit, or future regression could consequently introduce a
duplicate that later refreshes would retain and publish. The current accepted artifacts do not
contain such a duplicate.

## Identity rules

The fix should preserve the existing conservative, identifier-first semantics:

1. Normalize DOI, PMID, and arXiv identifiers before comparison.
2. Treat records as one work when any authoritative identifier overlaps, including transitively.
   For example, a DOI-only record and a PMID-only record become one component when another record
   contains both identifiers.
3. Union `faculty_ids`, derive `division_ids` from the current faculty directory, and merge source
   provenance and the richest available metadata.
4. Preserve one existing internal work ID deterministically. Prefer the oldest `first_seen_at`, then
   the lexical ID as a tie-breaker; generate a new ID only when the component has no retained ID.
5. Do not merge two identified records by title alone. A preprint and journal article, corrections,
   replies, and parallel journal publications can legitimately share a title while having different
   DOI/PMID pairs.
6. Permit title fallback only when neither record has an authoritative identifier, matching the
   current policy.

## Implementation sequence

### 1. Make reconciliation a core invariant

Implement an institution-neutral coalescing pass in `research-explorer-core`, used both for newly
collected works and retained history before retention limits and per-faculty caps are applied. Model
identity as connected components over normalized identifier keys rather than relying on a single
dictionary lookup. Keep metadata merging and relation union deterministic so repeated runs are
byte-stable apart from timestamps.

Core tests must cover:

- the same DOI returned for two faculty;
- the same PMID returned for two faculty;
- DOI-only, PMID-only, and DOI+PMID bridge records in every input order;
- duplicate records already present in history;
- targeted refreshes that see only one member of a shared work;
- removal of departed faculty without dropping active coauthors;
- stable canonical IDs, `first_seen_at`, metadata, sources, and relationship unions; and
- distinct identified works with equal titles, including preprint/published pairs.

### 2. Add boundary validation and diagnostics

Expose the normalized authoritative identity keys as a small public core helper so applications do
not duplicate normalization rules. In DOIM contract/release validation, reject any two published
records that share a DOI, PMID, or arXiv identity. The error should name the identifier and both
internal work IDs.

Add a deterministic audit command or release-check summary reporting:

- unique works;
- faculty-to-work relationships;
- works shared by multiple faculty; and
- collisions by identifier type.

Document that relationship totals are expected to exceed unique-work totals. Do not treat shared
faculty attribution as duplication.

### 3. Release and pin the core fix

Run the core test, lint, and format suites, release the next core version, and pin both
`pyproject.toml` and `uv.lock` to the immutable release tag/commit. Add an application-level
regression test using the pinned package so the cross-faculty and retained-history behavior cannot
disappear behind a dependency update.

### 4. Reconcile accepted artifacts atomically

Run the upgraded reconciliation against the accepted full publication snapshot, split the canonical
index/details pair, rebuild the RAG index, and update the `site/data` copies in the same reviewed
change. Preserve the chosen canonical IDs so detail keys, citations, and reusable vectors remain
stable. Review every collapsed component; do not automatically merge title-only candidates.

The present audit predicts no DOI/PMID collapse in the accepted corpus, so any unexpected deletion
is a release blocker requiring manual review.

### 5. Verify before completing the checklist

Completion requires all of the following:

- core unit tests demonstrate fresh, historical, transitive, and targeted coalescing;
- DOIM contract/release tests reject duplicate authoritative identifiers;
- the accepted data audit reports zero DOI, PMID, and arXiv collisions;
- publication stats equal the number of unique work records;
- one RAG work chunk exists for every unique publication ID;
- canonical and static documents match; and
- the locked full test/lint suites and local release check pass.

Record the released core version, audit counts, and exact verification commands in
`docs/doim-migration-plan.md` in the same commit that marks each checklist item complete.
