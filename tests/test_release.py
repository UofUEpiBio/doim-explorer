"""Release-boundary tests without live network calls."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from doim_explorer.release import (
    ReleaseCheckError,
    validate_local_release,
    validate_public_release,
    validate_release_documents,
    validate_static_documents,
)

ROOT = Path(__file__).resolve().parents[1]


def test_committed_release_artifacts_are_internally_consistent() -> None:
    _documents, summary = validate_local_release(ROOT)

    assert summary.divisions == summary.sources == 12
    assert summary.faculty > 0
    assert summary.publications >= 0
    assert summary.chunks > 0
    assert summary.index_generated_at


def test_release_rejects_source_health_that_is_not_complete_and_ok() -> None:
    documents, _summary = validate_local_release(ROOT)
    directory, publications, details = deepcopy(documents)
    directory["health"][0]["status"] = "blocked"

    with pytest.raises(ReleaseCheckError, match="sources need attention"):
        validate_release_documents((directory, publications, details))


def test_release_rejects_publication_identity_outside_the_directory() -> None:
    documents, _summary = validate_local_release(ROOT)
    directory, publications, details = deepcopy(documents)
    publications["works"] = [
        {
            "id": "doi:10.1/example",
            "title": "Example publication",
            "url": "https://example.test/publication",
            "faculty_ids": ["not-a-doim-faculty-id"],
            "division_ids": [directory["divisions"][0]["id"]],
        }
    ]
    publications["stats"]["works"] = 1

    with pytest.raises(ReleaseCheckError, match="unknown faculty"):
        validate_release_documents((directory, publications, details))


def test_release_rejects_static_documents_that_differ_from_canonical_artifacts() -> None:
    canonical, _summary = validate_local_release(ROOT)
    static = deepcopy(canonical)
    static[0]["faculty"][0]["title"] = "Unreviewed static edit"

    with pytest.raises(ReleaseCheckError, match="static-site documents differ"):
        validate_static_documents(canonical, static)


def test_public_release_requires_current_documents_readiness_and_cors() -> None:
    canonical, summary = validate_local_release(ROOT)
    site_url = "https://pages.example/doim/"
    ask_url = "https://ask.example"
    responses = {
        f"{site_url}data/directory.json": canonical[0],
        f"{site_url}data/publications.json": canonical[1],
        f"{site_url}data/publication-details.json": canonical[2],
        f"{ask_url}/readyz": {
            "ready": True,
            "chunks": summary.chunks,
            "indexGeneratedAt": summary.index_generated_at,
        },
    }
    preflights: list[tuple[str, str]] = []

    result = validate_public_release(
        canonical,
        summary,
        site_url=site_url,
        ask_url=ask_url,
        load_json=responses.__getitem__,
        check_cors=lambda url, origin: preflights.append((url, origin)),
    )

    assert result == summary
    assert preflights == [("https://ask.example/", "https://pages.example")]
