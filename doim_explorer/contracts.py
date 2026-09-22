"""Versioned documents exchanged by the DOIM directory, publications, and UI.

The core library owns the portable faculty and publication records.  This module owns
the application documents that add Department of Internal Medicine identity, generated
timestamps, source health, and compatibility checks at the repository boundary.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from research_explorer.works import SCHEMA_VERSION as CORE_PUBLICATIONS_SCHEMA_VERSION
from research_explorer.works import build_works_snapshot, split_works_snapshot

from doim_explorer.collaboration import (
    DIVISION_PALETTE,
    DIVISION_RINGS,
    LAYOUT_NAMES,
    components,
    derive_edges,
    layout_positions,
)
from doim_explorer.config import (
    DIRECTORY_CONFIG_VERSION,
    DIRECTORY_DOCUMENT_SCHEMA_VERSION,
    ProfileError,
)

DIRECTORY_SCHEMA_VERSION = DIRECTORY_DOCUMENT_SCHEMA_VERSION
PUBLICATIONS_SCHEMA_VERSION = CORE_PUBLICATIONS_SCHEMA_VERSION
DIRECTORY_DOCUMENT_TYPE = "doim-directory"
PUBLICATIONS_DOCUMENT_TYPE = "doim-publications"
PUBLICATION_DETAILS_DOCUMENT_TYPE = "doim-publication-details"
COLLABORATION_DOCUMENT_TYPE = "doim-collaboration"
COLLABORATION_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{field} must be a non-empty string")
    return value.strip()


def _require_list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProfileError(f"{field} must be a list")
    return value


def _settings(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Publish the human-maintained publication policy with the directory contract."""

    department = manifest["department"]
    publications = manifest["publications"]
    return {
        "name": department["name"],
        "description": department.get("summary", ""),
        "website": department["official_url"],
        "max_publications_per_faculty": publications["max_publications_per_faculty"],
        "publication_retention_years": publications["publication_retention_years"],
        "abstract_max_chars": publications["abstract_max_chars"],
    }


def _validate_faculty(faculty: Mapping[str, Any], division_ids: set[str]) -> dict[str, Any]:
    """Validate one flat faculty record before it reaches an on-disk document."""

    raw_expertise = faculty.get("expertise", [])
    if not isinstance(raw_expertise, list) or not all(
        isinstance(value, str) and value.strip() for value in raw_expertise
    ):
        raise ProfileError("faculty.expertise must be a list of non-empty strings")
    record = {
        "id": _required_string(faculty.get("id"), "faculty.id"),
        "full_name": _required_string(faculty.get("full_name"), "faculty.full_name"),
        "profile_url": _required_string(faculty.get("profile_url"), "faculty.profile_url"),
        "division_ids": list(faculty.get("division_ids") or []),
        "title": str(faculty.get("title", "")),
        "bio": str(faculty.get("bio", "")),
        "academic_information": str(faculty.get("academic_information", "")),
        "expertise": list(dict.fromkeys(value.strip() for value in raw_expertise)),
        "orcid_id": str(faculty.get("orcid_id", "")),
        "pubmed_query": str(faculty.get("pubmed_query", "")),
        "arxiv_query": str(faculty.get("arxiv_query", "")),
        "collect_publications": bool(faculty.get("collect_publications", True)),
    }
    if not record["profile_url"].startswith(("https://", "http://")):
        raise ProfileError("faculty.profile_url must be an http(s) URL")
    if not record["division_ids"] or not all(isinstance(value, str) for value in record["division_ids"]):
        raise ProfileError("faculty.division_ids must contain at least one division id")
    unknown = set(record["division_ids"]) - division_ids
    if unknown:
        raise ProfileError(f"faculty.division_ids references unknown division(s): {sorted(unknown)}")
    record["division_ids"] = list(dict.fromkeys(record["division_ids"]))
    return record


def build_directory_document(
    manifest: Mapping[str, Any],
    faculty: Sequence[Mapping[str, Any]] = (),
    health: Sequence[Mapping[str, Any]] = (),
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the flat, versioned directory document from the source manifest.

    P2.1 supplies the twelve configured divisions. P3 will pass collected faculty and
    per-source health records into this same builder; until then, the document honestly
    has no faculty rather than inventing profiles from the division pages.
    """

    if manifest.get("schema_version") != DIRECTORY_CONFIG_VERSION:
        raise ProfileError(
            f"Directory manifest schema_version must be {DIRECTORY_CONFIG_VERSION}"
        )
    divisions = deepcopy(_require_list(manifest.get("divisions"), "divisions"))
    division_ids = {str(division.get("id", "")) for division in divisions}
    if not division_ids or "" in division_ids:
        raise ProfileError("divisions must contain stable ids")
    normalized_faculty = [_validate_faculty(item, division_ids) for item in faculty]
    faculty_ids = [item["id"] for item in normalized_faculty]
    if len(faculty_ids) != len(set(faculty_ids)):
        raise ProfileError("faculty ids must be unique")

    document = {
        "document_type": DIRECTORY_DOCUMENT_TYPE,
        "schema_version": DIRECTORY_SCHEMA_VERSION,
        "generated_at": generated_at or _now(),
        "department": deepcopy(dict(manifest["department"])),
        "settings": _settings(manifest),
        "stats": {"divisions": len(divisions), "faculty": len(normalized_faculty)},
        "divisions": divisions,
        "faculty": normalized_faculty,
        "health": [deepcopy(dict(item)) for item in health],
    }
    validate_directory_document(document)
    return document


def validate_directory_document(document: Mapping[str, Any]) -> None:
    """Reject a directory document that cannot safely feed collection or the UI."""

    if document.get("document_type") != DIRECTORY_DOCUMENT_TYPE:
        raise ProfileError("directory document_type is not supported")
    if document.get("schema_version") != DIRECTORY_SCHEMA_VERSION:
        raise ProfileError(f"directory schema_version must be {DIRECTORY_SCHEMA_VERSION}")
    _required_string(document.get("generated_at"), "directory.generated_at")
    department = document.get("department")
    if not isinstance(department, Mapping):
        raise ProfileError("directory.department must be a table")
    _required_string(department.get("name"), "directory.department.name")
    _required_string(department.get("official_url"), "directory.department.official_url")
    divisions = _require_list(document.get("divisions"), "directory.divisions")
    faculty = _require_list(document.get("faculty"), "directory.faculty")
    division_ids = set()
    for division in divisions:
        if not isinstance(division, Mapping):
            raise ProfileError("directory.divisions must contain tables")
        division_id = _required_string(division.get("id"), "division.id")
        if division_id in division_ids:
            raise ProfileError("directory division ids must be unique")
        division_ids.add(division_id)
        for field in ("name", "source_url", "faculty_url"):
            _required_string(division.get(field), f"division.{field}")
    normalized = [_validate_faculty(item, division_ids) for item in faculty if isinstance(item, Mapping)]
    if len(normalized) != len(faculty):
        raise ProfileError("directory.faculty must contain tables")
    if len({item["id"] for item in normalized}) != len(normalized):
        raise ProfileError("directory faculty ids must be unique")


def build_publications_snapshot(
    directory: Mapping[str, Any], **kwargs: Any
) -> dict[str, Any]:
    """Collect publications using the canonical directory contract.

    The core collector performs identifier-first attribution and emits canonical
    ``faculty_ids`` and ``division_ids`` relation fields. This wrapper stamps the
    application document type and refuses malformed directory input first.
    """

    validate_directory_document(directory)
    snapshot = build_works_snapshot(dict(directory), **kwargs)
    snapshot["document_type"] = PUBLICATIONS_DOCUMENT_TYPE
    validate_publications_snapshot(snapshot)
    return snapshot


def split_publications_snapshot(snapshot: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a publications snapshot into its index and lazy-loaded detail document."""

    validate_publications_snapshot(snapshot)
    index, details = split_works_snapshot(dict(snapshot))
    index["document_type"] = PUBLICATIONS_DOCUMENT_TYPE
    details["document_type"] = PUBLICATION_DETAILS_DOCUMENT_TYPE
    validate_publication_documents(index, details)
    return index, details


def validate_publications_snapshot(snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("document_type") != PUBLICATIONS_DOCUMENT_TYPE:
        raise ProfileError("publications document_type is not supported")
    if snapshot.get("schema_version") != PUBLICATIONS_SCHEMA_VERSION:
        raise ProfileError(f"publications schema_version must be {PUBLICATIONS_SCHEMA_VERSION}")
    _required_string(snapshot.get("generated_at"), "publications.generated_at")
    for work in _require_list(snapshot.get("works"), "publications.works"):
        if not isinstance(work, Mapping):
            raise ProfileError("publications.works must contain tables")
        for field in ("id", "title", "url"):
            _required_string(work.get(field), f"publication.{field}")
        for field in ("faculty_ids", "division_ids"):
            _require_list(work.get(field), f"publication.{field}")


def validate_publication_documents(index: Mapping[str, Any], details: Mapping[str, Any]) -> None:
    """Validate the published index/detail pair as one contract."""

    validate_publications_snapshot(index)
    if details.get("document_type") != PUBLICATION_DETAILS_DOCUMENT_TYPE:
        raise ProfileError("publication details document_type is not supported")
    if details.get("schema_version") != PUBLICATIONS_SCHEMA_VERSION:
        raise ProfileError(f"publication details schema_version must be {PUBLICATIONS_SCHEMA_VERSION}")
    _required_string(details.get("generated_at"), "publication details.generated_at")
    raw_details = details.get("details")
    if not isinstance(raw_details, Mapping):
        raise ProfileError("publication details.details must be a table")
    work_ids = {str(work["id"]) for work in index["works"]}
    if not set(raw_details) <= work_ids:
        raise ProfileError("publication details reference a publication absent from the index")


def build_collaboration_document(
    directory: Mapping[str, Any],
    publications: Mapping[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the published co-authorship network from the accepted documents.

    Only faculty with at least one internal collaborator become nodes: an isolated dot
    says nothing a reader can act on, and the roster is already the Faculty view's job.
    """

    validate_directory_document(directory)
    validate_publications_snapshot(publications)

    divisions = list(directory["divisions"])
    if len(divisions) > len(DIVISION_PALETTE):
        raise ProfileError(
            f"collaboration palette has {len(DIVISION_PALETTE)} slots for "
            f"{len(divisions)} divisions; add validated colors rather than reusing one"
        )
    faculty_by_id = {str(item["id"]): item for item in directory["faculty"]}
    works = list(publications["works"])
    edges = derive_edges(works)

    node_ids = sorted({node_id for pair in edges for node_id in pair})
    unknown = [node_id for node_id in node_ids if node_id not in faculty_by_id]
    if unknown:
        raise ProfileError(f"collaboration references faculty absent from the directory: {unknown}")

    colors = {
        str(division["id"]): (DIVISION_PALETTE[index], DIVISION_RINGS[index])
        for index, division in enumerate(sorted(divisions, key=lambda item: str(item["id"])))
    }
    node_divisions = {
        node_id: str((faculty_by_id[node_id].get("division_ids") or [""])[0])
        for node_id in node_ids
    }
    missing = sorted({value for value in node_divisions.values() if value not in colors})
    if missing:
        raise ProfileError(f"collaboration references unknown divisions: {missing}")

    node_components = components(node_ids, edges)
    positions = layout_positions(node_divisions, edges)
    per_faculty = publications.get("publications_per_faculty") or {}
    degrees: dict[str, int] = {node_id: 0 for node_id in node_ids}
    shared: dict[str, int] = {node_id: 0 for node_id in node_ids}
    for (source, target), edge in edges.items():
        degrees[source] += 1
        degrees[target] += 1
        shared[source] += edge["weight"]
        shared[target] += edge["weight"]

    nodes = [
        {
            "id": node_id,
            "name": str(faculty_by_id[node_id].get("full_name", "")),
            "division_id": node_divisions[node_id],
            "profile_url": str(faculty_by_id[node_id].get("profile_url", "")),
            "publications": int(per_faculty.get(node_id, 0) or 0),
            "collaborators": degrees[node_id],
            "shared_works": shared[node_id],
            "component": node_components[node_id],
            "positions": positions[node_id],
        }
        for node_id in node_ids
    ]
    published_edges = [
        {
            "source": source,
            "target": target,
            "weight": edge["weight"],
            "first_year": edge["first_year"],
            "last_year": edge["last_year"],
        }
        for (source, target), edge in sorted(edges.items())
    ]
    node_counts: dict[str, int] = {str(division["id"]): 0 for division in divisions}
    for value in node_divisions.values():
        node_counts[value] += 1
    cap = int(directory["settings"].get("max_publications_per_faculty", 0) or 0)

    document = {
        "document_type": COLLABORATION_DOCUMENT_TYPE,
        "schema_version": COLLABORATION_SCHEMA_VERSION,
        "generated_at": generated_at or _now(),
        "sources": {
            "directory_generated_at": directory["generated_at"],
            "publications_generated_at": publications["generated_at"],
        },
        "stats": {
            "nodes": len(nodes),
            "edges": len(published_edges),
            "shared_works": sum(1 for work in works if len(set(work.get("faculty_ids") or [])) > 1),
            "faculty": len(faculty_by_id),
            "components": len(set(node_components.values())),
            "largest_component": max(
                (
                    sum(1 for value in node_components.values() if value == group)
                    for group in set(node_components.values())
                ),
                default=0,
            ),
            "cross_division_edges": sum(
                1
                for source, target in edges
                if node_divisions[source] != node_divisions[target]
            ),
            "capped_faculty": sum(1 for value in per_faculty.values() if cap and int(value) >= cap),
            "max_publications_per_faculty": cap,
        },
        "divisions": [
            {
                "id": str(division["id"]),
                "name": str(division["name"]),
                "color": colors[str(division["id"])][0],
                "ring": colors[str(division["id"])][1],
                "faculty": node_counts[str(division["id"])],
            }
            for division in divisions
        ],
        "nodes": nodes,
        "edges": published_edges,
    }
    validate_collaboration_document(document)
    return document


def validate_collaboration_document(document: Mapping[str, Any]) -> None:
    """Reject a network document the browser could draw incorrectly or misleadingly."""

    if document.get("document_type") != COLLABORATION_DOCUMENT_TYPE:
        raise ProfileError("collaboration document_type is not supported")
    if document.get("schema_version") != COLLABORATION_SCHEMA_VERSION:
        raise ProfileError(f"collaboration schema_version must be {COLLABORATION_SCHEMA_VERSION}")
    _required_string(document.get("generated_at"), "collaboration.generated_at")
    sources = document.get("sources")
    if not isinstance(sources, Mapping):
        raise ProfileError("collaboration.sources must be a table")
    for field in ("directory_generated_at", "publications_generated_at"):
        _required_string(sources.get(field), f"collaboration.sources.{field}")

    divisions = _require_list(document.get("divisions"), "collaboration.divisions")
    colors: set[str] = set()
    division_ids: set[str] = set()
    for division in divisions:
        if not isinstance(division, Mapping):
            raise ProfileError("collaboration.divisions must contain tables")
        division_id = _required_string(division.get("id"), "collaboration.division.id")
        if division_id in division_ids:
            raise ProfileError("collaboration division ids must be unique")
        division_ids.add(division_id)
        _required_string(division.get("name"), "collaboration.division.name")
        color = _required_string(division.get("color"), "collaboration.division.color")
        _required_string(division.get("ring"), "collaboration.division.ring")
        if color in colors:
            raise ProfileError("collaboration divisions must not share a color")
        colors.add(color)

    nodes = _require_list(document.get("nodes"), "collaboration.nodes")
    node_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, Mapping):
            raise ProfileError("collaboration.nodes must contain tables")
        node_id = _required_string(node.get("id"), "collaboration.node.id")
        if node_id in node_ids:
            raise ProfileError("collaboration node ids must be unique")
        node_ids.add(node_id)
        _required_string(node.get("name"), "collaboration.node.name")
        if _required_string(node.get("division_id"), "collaboration.node.division_id") not in division_ids:
            raise ProfileError(f"collaboration node {node_id} names an unknown division")
        positions = node.get("positions")
        if not isinstance(positions, Mapping):
            raise ProfileError(f"collaboration node {node_id} has no positions")
        for layout in LAYOUT_NAMES:
            point = positions.get(layout)
            if not isinstance(point, list) or len(point) != 2:
                raise ProfileError(f"collaboration node {node_id} has no {layout} position")
            for value in point:
                if not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1.001:
                    raise ProfileError(
                        f"collaboration node {node_id} has an out-of-range {layout} coordinate"
                    )

    seen_pairs: set[tuple[str, str]] = set()
    for edge in _require_list(document.get("edges"), "collaboration.edges"):
        if not isinstance(edge, Mapping):
            raise ProfileError("collaboration.edges must contain tables")
        source = _required_string(edge.get("source"), "collaboration.edge.source")
        target = _required_string(edge.get("target"), "collaboration.edge.target")
        if source == target:
            raise ProfileError("collaboration edges must not be self loops")
        if source not in node_ids or target not in node_ids:
            raise ProfileError(f"collaboration edge {source}-{target} names an absent node")
        pair = (source, target) if source < target else (target, source)
        if pair in seen_pairs:
            raise ProfileError(f"collaboration edge {source}-{target} is duplicated")
        seen_pairs.add(pair)
        weight = edge.get("weight")
        if not isinstance(weight, int) or weight < 1:
            raise ProfileError(f"collaboration edge {source}-{target} needs a positive weight")

    stats = document.get("stats")
    if not isinstance(stats, Mapping):
        raise ProfileError("collaboration.stats must be a table")
    if stats.get("nodes") != len(nodes) or stats.get("edges") != len(document["edges"]):
        raise ProfileError("collaboration.stats do not match the published graph")
