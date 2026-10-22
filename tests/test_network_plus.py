from __future__ import annotations

import pytest

pytest.importorskip("networkx")

from doim_explorer.contracts import ProfileError
from doim_explorer.network_plus import (
    TRAINEE_GROUP_ID,
    build_network_plus_document,
    network_plus_csv,
    validate_network_plus_document,
)


def _directory() -> dict:
    return {
        "generated_at": "2026-10-05T00:00:00Z",
        "divisions": [
            {"id": "epidemiology", "name": "Epidemiology"},
            {"id": "cardiology", "name": "Cardiology"},
        ],
        "faculty": [
            {
                "id": "f1",
                "full_name": "Fay One, MD",
                "division_ids": ["epidemiology"],
                "profile_url": "",
            },
            {
                "id": "f2",
                "full_name": "Fox Two, MD",
                "division_ids": ["cardiology"],
                "profile_url": "",
            },
            {
                "id": "f3",
                "full_name": "Fig Three, MD",
                "division_ids": ["cardiology", "epidemiology"],
                "profile_url": "",
            },
        ],
    }


def _publications() -> dict:
    works = [
        {"id": "w1", "year": 2024, "pmid": "1", "faculty_ids": ["f1", "f2"]},
        {"id": "w2", "year": 2025, "pmid": "2", "faculty_ids": ["f1"]},
        {"id": "w3", "year": 2026, "pmid": "3", "faculty_ids": ["f2", "f3"]},
        {"id": "w4", "year": 2026, "pmid": "4", "faculty_ids": ["f3"]},
    ]
    return {
        "generated_at": "2026-10-05T01:00:00Z",
        "works": works,
        "publications_per_faculty": {"f1": 2},
    }


def _trainee(id_: str, name: str, works: int, faculty_id: str | None = None) -> dict:
    return {
        "id": id_,
        "name": name,
        "degree": "MD",
        "program": "IM",
        "program_id": "im",
        "faculty_id": faculty_id,
        "works": works,
    }


def _trainee_publications() -> dict:
    # Trainee works carry their own ids; the shared ones are recognised by PMID.
    return {
        "document_type": "doim-trainee-publications",
        "generated_at": "2026-10-05T02:00:00Z",
        "method": {"query": "full author name"},
        "summary": {"roster": 4, "with_publications": 4, "by_program": []},
        "trainees": [
            _trainee("t-a", "Ann Alpha", 3),
            _trainee("t-b", "Bo Beta", 2),
            _trainee("t-c", "Cy Gamma", 1),
            _trainee("t-f3", "Fig Three", 1, "f3"),
        ],
        "works": [
            {"id": "x1", "year": 2024, "pmid": "1", "trainee_ids": ["t-a"]},
            {"id": "x2", "year": 2025, "pmid": "2", "trainee_ids": ["t-a", "t-f3"]},
            {"id": "x4", "year": 2026, "pmid": "4", "trainee_ids": ["t-b"]},
            # Only trainee searches found these: no faculty work shares an identifier.
            {"id": "x9", "year": 2026, "pmid": "9", "title": "Solo", "trainee_ids": ["t-a"]},
            {
                "id": "x8",
                "year": 2023,
                "pmid": "8",
                "title": "Pair",
                "url": "https://x/8",
                "trainee_ids": ["t-b", "t-c"],
            },
        ],
    }


def _build(trainee_publications: dict | None = None) -> dict:
    return build_network_plus_document(
        _directory(), _publications(), trainee_publications or _trainee_publications()
    )


def test_trainees_link_to_the_faculty_on_their_works_and_to_each_other() -> None:
    document = _build()
    weights = {(edge["source"], edge["target"]): edge["weight"] for edge in document["edges"]}

    assert weights[("f1", "f2")] == 1  # faculty-faculty, as in the faculty network
    assert weights[("f1", "t-a")] == 2  # t-a is on w1 and w2, and f1 is on both
    assert weights[("f2", "t-a")] == 1  # only w1
    assert weights[("f3", "t-b")] == 1
    # w2 carries f1 and two trainees (t-a, and f3 collapsed from t-f3): they link to each other.
    assert weights[("f3", "t-a")] == 1


def test_a_trainee_who_is_also_faculty_is_one_node_in_both_groups() -> None:
    document = _build()
    nodes = {node["id"]: node for node in document["nodes"]}

    assert "t-f3" not in nodes
    assert nodes["f3"]["kind"] == "both"
    assert set(nodes["f3"]["groups"]) == {"cardiology", "epidemiology", TRAINEE_GROUP_ID}
    assert nodes["f3"]["division_id"] == "cardiology"  # coloured by division, not by trainee group


def test_works_only_trainee_searches_found_link_trainees_and_are_published() -> None:
    document = _build()
    weights = {(edge["source"], edge["target"]): edge["weight"] for edge in document["edges"]}
    nodes = {node["id"]: node for node in document["nodes"]}

    assert weights[("t-b", "t-c")] == 1  # x8 has no faculty author
    assert nodes["t-c"]["work_ids"] == ["x8"]
    assert nodes["t-a"]["work_ids"] == ["w1", "w2", "x9"]  # faculty ids win when shared
    # x9 is listed (t-a is in the network); both trainee-only works are published.
    assert [work["id"] for work in document["trainee_works"]] == ["x8", "x9"]
    assert document["trainee_works"][0]["url"] == "https://x/8"
    assert document["stats"]["trainee_only_works"] == 2
    assert document["stats"]["trainee_nodes"] == 4


def test_group_member_counts_cover_trainees_and_multi_division_faculty() -> None:
    counts = {group["id"]: group["members"] for group in _build()["groups"]}

    assert counts == {"cardiology": 2, "epidemiology": 2, TRAINEE_GROUP_ID: 4}


def test_published_document_validates_and_is_deterministic() -> None:
    first, second = _build(), _build()
    first["generated_at"] = second["generated_at"] = "fixed"

    validate_network_plus_document(first)
    assert first == second


def test_trainee_works_naming_an_unknown_trainee_are_rejected() -> None:
    trainee_publications = _trainee_publications()
    trainee_publications["works"][0]["trainee_ids"].append("t-nobody")

    with pytest.raises(ProfileError, match="unknown trainee"):
        _build(trainee_publications)


def test_trainees_naming_unknown_faculty_are_rejected() -> None:
    trainee_publications = _trainee_publications()
    trainee_publications["trainees"][3]["faculty_id"] = "nobody"

    with pytest.raises(ProfileError, match="absent from the directory"):
        _build(trainee_publications)


def test_csv_export_covers_every_node_and_edge_with_names() -> None:
    import csv
    import io

    document = _build()
    nodes_csv, edges_csv = network_plus_csv(document)
    nodes = list(csv.DictReader(io.StringIO(nodes_csv)))
    edges = list(csv.DictReader(io.StringIO(edges_csv)))

    assert len(nodes) == len(document["nodes"]) and len(edges) == len(document["edges"])
    row = next(item for item in nodes if item["id"] == "f3")
    assert row["kind"] == "both" and row["groups"] == "Cardiology;Epidemiology;Fellows & residents"
    pair = next(item for item in edges if item["source_id"] == "f1" and item["target_id"] == "t-a")
    assert pair["target_name"] == "Ann Alpha" and pair["shared_works"] == "2"
