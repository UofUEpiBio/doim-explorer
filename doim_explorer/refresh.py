"""Incremental, reviewable refreshes of accepted DOIM data artifacts."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from research_explorer import rag
from research_explorer.works import merge_works_snapshot

from doim_explorer.config import ProfileError, load_directory_config, load_faculty_overrides
from doim_explorer.contracts import (
    build_collaboration_document,
    build_publications_snapshot,
    split_publications_snapshot,
    validate_directory_document,
    validate_publication_documents,
)
from doim_explorer.directory import (
    RefreshGuardError,
    assert_safe_directory_refresh,
    collect_directory_snapshot,
    refresh_selected_profiles,
)
from doim_explorer.release import validate_rag_index, validate_release_documents
from doim_explorer.update import read_snapshot, write_rag_index, write_snapshot

_FACULTY_ID = re.compile(r"u\d+\Z", re.IGNORECASE)
_PUBLICATION_INPUTS = ("orcid_id", "pubmed_query", "arxiv_query", "collect_publications")


class RefreshError(ValueError):
    """Raised before a staged refresh can publish any generated artifact."""


def parse_faculty_ids(value: str) -> list[str]:
    """Parse comma/whitespace separated stable U of U faculty identifiers."""

    values = [item.lower() for item in re.split(r"[\s,]+", value.strip()) if item]
    if not values:
        raise RefreshError("--faculty-ids must name at least one faculty id")
    invalid = sorted({item for item in values if not _FACULTY_ID.fullmatch(item)})
    if invalid:
        raise RefreshError(f"faculty ids must look like u1234567: {invalid}")
    return list(dict.fromkeys(values))


def _previous_documents(
    directory_path: Path, publications_path: Path, details_path: Path
) -> tuple[dict, dict]:
    directory = read_snapshot(directory_path)
    publications = read_snapshot(publications_path)
    details = read_snapshot(details_path)
    if directory is None or publications is None or details is None:
        raise RefreshError(
            "incremental refresh requires accepted directory and publication documents"
        )
    try:
        validate_directory_document(directory)
        validate_publication_documents(publications, details)
    except ProfileError as exc:
        raise RefreshError(f"accepted data is invalid: {exc}") from exc
    return directory, merge_works_snapshot(publications, details) or {"works": []}


def _changed_publication_faculty(previous: dict, current: dict) -> list[str]:
    old_by_id = {str(item["id"]): item for item in previous["faculty"]}
    changed = []
    for member in current["faculty"]:
        faculty_id = str(member["id"])
        before = old_by_id.get(faculty_id)
        if before is None or any(
            before.get(field) != member.get(field) for field in _PUBLICATION_INPUTS
        ):
            changed.append(faculty_id)
    return changed


def _require_pubmed_contact(directory: dict, targets: list[str]) -> None:
    configured = {str(member["id"]): member for member in directory["faculty"]}
    needs_contact = any(
        configured[faculty_id].get("collect_publications", True)
        and configured[faculty_id].get("pubmed_query", "")
        for faculty_id in targets
    )
    contact = os.getenv("RESEARCH_EXPLORER_CONTACT_EMAIL", "").strip()
    if needs_contact and ("@" not in contact or " " in contact):
        raise RefreshError(
            "RESEARCH_EXPLORER_CONTACT_EMAIL must be a monitored address before targeted PubMed collection"
        )


def _attention(health: list[dict[str, Any]], targets: list[str]) -> list[dict[str, Any]]:
    selected = set(targets)
    return [
        row
        for row in health
        if row.get("faculty_id") in selected and row.get("status") in {"blocked", "error"}
    ]


def _replace_rag(staged: Path, output: Path) -> None:
    """Replace the complete index only after every document has staged successfully."""

    backup = output.with_name(f".{output.name}.previous")
    if backup.exists():
        shutil.rmtree(backup)
    if output.exists():
        os.replace(output, backup)
    try:
        os.replace(staged, output)
    except BaseException:
        if backup.exists():
            os.replace(backup, output)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def refresh(
    *,
    mode: str,
    faculty_ids: list[str],
    config_path: Path,
    overrides_path: Path,
    directory_path: Path,
    publications_path: Path,
    details_path: Path,
    collaboration_path: Path,
    site_dir: Path,
    rag_dir: Path,
) -> tuple[dict, dict, dict, dict, dict]:
    """Stage and publish a targeted, roster-only, or full-profile refresh."""

    previous_directory, previous_publications = _previous_documents(
        directory_path, publications_path, details_path
    )
    manifest = load_directory_config(config_path)
    overrides = load_faculty_overrides(overrides_path)["faculty"]

    if mode == "targeted":
        directory = refresh_selected_profiles(
            manifest, previous_directory, faculty_ids, faculty_overrides=overrides
        )
        targets = faculty_ids
    elif mode == "roster":
        directory = collect_directory_snapshot(
            manifest,
            faculty_overrides=overrides,
            previous_snapshot=previous_directory,
            enrich_profiles=False,
        )
        try:
            assert_safe_directory_refresh(previous_directory, directory)
        except RefreshGuardError as exc:
            raise RefreshError(f"directory refresh guard failed: {exc}") from exc
        targets = _changed_publication_faculty(previous_directory, directory)
    else:
        directory = collect_directory_snapshot(
            manifest,
            faculty_overrides=overrides,
            previous_snapshot=previous_directory,
            enrich_profiles=True,
        )
        try:
            assert_safe_directory_refresh(previous_directory, directory)
        except RefreshGuardError as exc:
            raise RefreshError(f"directory refresh guard failed: {exc}") from exc
        targets = _changed_publication_faculty(previous_directory, directory)

    directory_attention = [row for row in directory["health"] if row.get("status") != "ok"]
    if directory_attention:
        raise RefreshError(f"{len(directory_attention)} directory source(s) need attention")
    _require_pubmed_contact(directory, targets)
    publication_snapshot = build_publications_snapshot(
        directory,
        previous_snapshot=previous_publications,
        target_faculty_ids=targets,
    )
    publication_attention = _attention(publication_snapshot["health"], targets)
    if publication_attention:
        raise RefreshError(
            f"{len(publication_attention)} targeted publication source(s) need attention"
        )
    publications, details = split_publications_snapshot(publication_snapshot)
    # Pure and cheap next to the RAG build below, so a bad graph fails before that work.
    collaboration = build_collaboration_document(directory, publications)

    chunks = rag.build_chunks(directory, publications, details)
    previous_index = rag.read_index(rag_dir)
    embedder = rag.vertex_embedder()
    result = rag.build_index(chunks, previous_index, embedder)

    with tempfile.TemporaryDirectory(prefix=".doim-refresh-", dir=rag_dir.parent) as temporary:
        staged_root = Path(temporary)
        staged_rag = staged_root / "rag"
        write_rag_index(result, staged_rag, directory, publications)
        summary = validate_release_documents((directory, publications, details))
        validate_rag_index(staged_rag, (directory, publications, details), summary)

        write_snapshot(directory, directory_path)
        write_snapshot(publications, publications_path)
        write_snapshot(details, details_path)
        write_snapshot(collaboration, collaboration_path)
        write_snapshot(directory, site_dir / directory_path.name)
        write_snapshot(publications, site_dir / publications_path.name)
        write_snapshot(details, site_dir / details_path.name)
        write_snapshot(collaboration, site_dir / collaboration_path.name)
        final_stage = rag_dir.parent / f".{rag_dir.name}.staged"
        if final_stage.exists():
            shutil.rmtree(final_stage)
        os.replace(staged_rag, final_stage)
        _replace_rag(final_stage, rag_dir)

    return (
        directory,
        publications,
        details,
        collaboration,
        {"embedded": result.embedded, "reused": result.reused},
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Incrementally refresh accepted DOIM data artifacts"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--faculty-ids", default=None, help="Comma/whitespace separated stable faculty ids"
    )
    group.add_argument(
        "--roster-only", action="store_true", help="Refresh rosters but retain profile text"
    )
    group.add_argument(
        "--all-profiles", action="store_true", help="Refresh rosters and every public profile"
    )
    parser.add_argument("--config", type=Path, default=Path("config/directory.toml"))
    parser.add_argument(
        "--faculty-overrides", type=Path, default=Path("config/faculty-overrides.toml")
    )
    parser.add_argument("--directory", type=Path, default=Path("data/directory.json"))
    parser.add_argument("--publications", type=Path, default=Path("data/publications.json"))
    parser.add_argument("--details", type=Path, default=Path("data/publication-details.json"))
    parser.add_argument("--collaboration", type=Path, default=Path("data/collaboration.json"))
    parser.add_argument("--site-dir", type=Path, default=Path("site/data"))
    parser.add_argument("--rag-dir", type=Path, default=Path("data/rag"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "targeted" if args.faculty_ids is not None else "roster" if args.roster_only else "all"
    try:
        faculty_ids = parse_faculty_ids(args.faculty_ids) if mode == "targeted" else []
        _directory, publications, _details, collaboration, index = refresh(
            mode=mode,
            faculty_ids=faculty_ids,
            config_path=args.config,
            overrides_path=args.faculty_overrides,
            directory_path=args.directory,
            publications_path=args.publications,
            details_path=args.details,
            collaboration_path=args.collaboration,
            site_dir=args.site_dir,
            rag_dir=args.rag_dir,
        )
    except (OSError, ProfileError, RefreshError, ValueError) as exc:
        print(f"Refresh failed: {exc}")
        return 1
    print(
        f"Refreshed {mode}: {len(faculty_ids) if mode == 'targeted' else 'automatic'} faculty targets; "
        f"{len(publications['works'])} publications; "
        f"{collaboration['stats']['nodes']} faculty in the collaboration network; "
        f"{index['embedded']} embedded, {index['reused']} reused"
    )
    return 0
