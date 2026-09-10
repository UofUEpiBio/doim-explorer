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
- [x] **P1.1 Create reusable project.** Evidence: [research-explorer-core v0.1.1](https://github.com/UofUEpiBio/research-explorer-core/releases/tag/v0.1.1).
- [x] **P1.2 Extract site-independent code.** Evidence: the core package owns HTTP collection,
  publications, text normalization, and retrieval; this repository imports it as a pinned dependency.
- [x] **P1.3 Define stable interfaces.** Evidence: `research_explorer.models` exports directory,
  faculty, publication, health, and adapter records/protocols.
- [x] **P1.4 Keep application concerns local.** Evidence: `doim_explorer` retains TOML loading,
  snapshot publication, and CLI orchestration; `server` retains FastAPI and budget policy.
- [x] **P1.5 Release and pin the core.** Evidence: `pyproject.toml` and `uv.lock` pin v0.1.1.
- [x] **P1.6 Rename internal package and commands.** Evidence: `doim_explorer` and the `doim-*`
  console commands replace the `insightnet` package and commands.

## 2. DOIM content and branding

- [ ] **P2.1 Configure department, divisions, and faculty sources.**
- [ ] **P2.2 Build versioned directory and publication contracts.**
- [ ] **P2.3 Replace InsightNet views with DOIM faculty, expertise, publications, Ask, and data status.**
- [ ] **P2.4 Add configurable unofficial/official branding, CSS variables, assets, and analytics.**

## 3. Faculty scraper and publications

- [ ] **P3.1 Implement all 12 primary-faculty source adapters.**
- [ ] **P3.2 Extract public faculty profile text, stable IDs, and source health.**
- [ ] **P3.3 Generate University of Utah-affiliation PubMed queries with overrides.**
- [ ] **P3.4 Add weekly guarded data pull requests and count/drop guardrails.**

## 4. Google Cloud and GitHub Actions

- [ ] **P4.1 Add the gcloud-first bootstrap runbook and idempotent script.**
- [ ] **P4.2 Provision the separately named `doim-*` Cloud Run, Artifact Registry, Firestore, and WIF resources.**
- [ ] **P4.3 Configure GitHub variables/secrets and deploy the AI service.**
- [ ] **P4.4 Replace existing workflows with CI, guarded refresh, Pages, deploy, and auth checks.**

## 5. Verification and release

- [ ] **P5.1 Add source, schema, publication-identity, UI, RAG, and cloud smoke coverage.**
- [ ] **P5.2 Review the initial data pull request and complete release acceptance.**
