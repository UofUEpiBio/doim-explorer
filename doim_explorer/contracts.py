"""Versioned documents exchanged by the DOIM directory, publications, and UI.

The core library owns the portable faculty and publication records.  This module owns
the application documents that add Department of Internal Medicine identity, generated
timestamps, source health, and compatibility checks at the repository boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from research_explorer.works import SCHEMA_VERSION as CORE_PUBLICATIONS_SCHEMA_VERSION
from research_explorer.works import build_works_snapshot, split_works_snapshot

from doim_explorer.config import DIRECTORY_CONFIG_VERSION, ProfileError

DIRECTORY_SCHEMA_VERSION = DIRECTORY_CONFIG_VERSION
PUBLICATIONS_SCHEMA_VERSION = CORE_PUBLICATIONS_SCHEMA_VERSION
DIRECTORY_DOCUMENT_TYPE = "doim-directory"
PUBLICATIONS_DOCUMENT_TYPE = "doim-publications"
PUBLICATION_DETAILS_DOCUMENT_TYPE = "doim-publication-details"


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
    department = manifest["department"]
    return {
        "name": department["name"],
        "description": department.get("summary", ""),
        "website": department["official_url"],
        # These limits deliberately have faculty/publication names.  The core accepts
        # its prior researcher/works names only as a migration alias.
        "max_publications_per_faculty": 100,
        "publication_retention_years": 15,
        "abstract_max_chars": 1500,
    }


def _validate_faculty(faculty: Mapping[str, Any], division_ids: set[str]) -> dict[str, Any]:
    """Validate one flat faculty record before it reaches an on-disk document."""

    record = {
        "id": _required_string(faculty.get("id"), "faculty.id"),
        "full_name": _required_string(faculty.get("full_name"), "faculty.full_name"),
        "profile_url": _required_string(faculty.get("profile_url"), "faculty.profile_url"),
        "division_ids": list(faculty.get("division_ids") or []),
        "title": str(faculty.get("title", "")),
        "bio": str(faculty.get("bio", "")),
        "academic_information": str(faculty.get("academic_information", "")),
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

    if manifest.get("schema_version") != DIRECTORY_SCHEMA_VERSION:
        raise ProfileError(
            f"Directory manifest schema_version must be {DIRECTORY_SCHEMA_VERSION}"
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
