import json
from pathlib import Path

import pytest

from doim_explorer.config import ProfileError, load_directory_config
from doim_explorer.contracts import (
    DIRECTORY_DOCUMENT_TYPE,
    PUBLICATION_DETAILS_DOCUMENT_TYPE,
    PUBLICATIONS_DOCUMENT_TYPE,
    build_directory_document,
    build_publications_snapshot,
    split_publications_snapshot,
    validate_directory_document,
    validate_publication_documents,
)
from doim_explorer.update import directory_main


def test_directory_contract_preserves_the_manifest_and_accepts_collected_faculty() -> None:
    document = build_directory_document(
        load_directory_config(),
        faculty=[
            {
                "id": "jane-doe",
                "full_name": "Jane Doe, MD",
                "profile_url": "https://medicine.utah.edu/faculty/jane-doe",
                "division_ids": ["epidemiology"],
                "title": "Professor of Medicine",
                "bio": "Studies clinical epidemiology.",
                "collect_publications": True,
            }
        ],
        health=[{"source": "epidemiology", "status": "ok"}],
        generated_at="2026-09-09T00:00:00Z",
    )

    assert document["document_type"] == DIRECTORY_DOCUMENT_TYPE
    assert document["schema_version"] == 1
    assert document["stats"] == {"divisions": 12, "faculty": 1}
    assert document["settings"]["max_publications_per_faculty"] == 100
    assert document["faculty"][0]["division_ids"] == ["epidemiology"]
    validate_directory_document(document)


def test_directory_contract_rejects_faculty_outside_the_configured_divisions() -> None:
    with pytest.raises(ProfileError, match="unknown division"):
        build_directory_document(
            load_directory_config(),
            faculty=[
                {
                    "id": "jane-doe",
                    "full_name": "Jane Doe",
                    "profile_url": "https://medicine.utah.edu/faculty/jane-doe",
                    "division_ids": ["not-a-division"],
                }
            ],
        )


def test_publication_index_and_detail_documents_keep_canonical_relations() -> None:
    snapshot = {
        "document_type": PUBLICATIONS_DOCUMENT_TYPE,
        "schema_version": 2,
        "generated_at": "2026-09-09T00:00:00Z",
        "works": [
            {
                "id": "doi:10.1/example",
                "title": "Clinical example",
                "url": "https://doi.org/10.1/example",
                "faculty_ids": ["jane-doe"],
                "division_ids": ["epidemiology"],
                "researcher_ids": ["jane-doe"],
                "organization_ids": ["epidemiology"],
                "abstract": "A durable abstract.",
                "authors": [{"name": "Jane Doe", "orcid": ""}],
            }
        ],
    }

    index, details = split_publications_snapshot(snapshot)

    assert index["document_type"] == PUBLICATIONS_DOCUMENT_TYPE
    assert details["document_type"] == PUBLICATION_DETAILS_DOCUMENT_TYPE
    assert index["works"][0]["faculty_ids"] == ["jane-doe"]
    assert "abstract" not in index["works"][0]
    assert details["details"]["doi:10.1/example"]["abstract"] == "A durable abstract."
    validate_publication_documents(index, details)


def test_publication_builder_accepts_the_directory_contract_before_faculty_collection() -> None:
    directory = build_directory_document(
        load_directory_config(), generated_at="2026-09-09T00:00:00Z"
    )

    snapshot = build_publications_snapshot(directory, client=object())

    assert snapshot["document_type"] == PUBLICATIONS_DOCUMENT_TYPE
    assert snapshot["works"] == []
    assert snapshot["stats"]["faculty_with_publications"] == 0


def test_directory_command_publishes_a_versioned_document_and_static_copy(tmp_path: Path) -> None:
    output = tmp_path / "data" / "directory.json"
    site_dir = tmp_path / "site-data"

    assert directory_main(["--output", str(output), "--site-dir", str(site_dir)]) == 0

    canonical = json.loads(output.read_text(encoding="utf-8"))
    static = json.loads((site_dir / "directory.json").read_text(encoding="utf-8"))
    assert canonical == static
    assert canonical["document_type"] == DIRECTORY_DOCUMENT_TYPE
    assert canonical["stats"] == {"divisions": 12, "faculty": 0}
