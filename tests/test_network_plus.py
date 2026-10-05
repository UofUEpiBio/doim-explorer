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
        {"id": "w1", "year": 2024, "faculty_ids": ["f1", "f2"]},
        {"id": "w2", "year": 2025, "faculty_ids": ["f1"]},
        {"id": "w3", "year": 2026, "faculty_ids": ["f2", "f3"]},
        {"id": "w4", "year": 2026, "faculty_ids": ["f3"]},
    ]
    return {
        "generated_at": "2026-10-05T01:00:00Z",
        "works": works,
        "publications_per_faculty": {"f1": 2},
    }


def _matches() -> dict:
    return {
        "document_type": "doim-trainee-matches",
        "generated_at": "2026-10-05T02:00:00Z",
        "sources": {"publications_generated_at": "2026-10-05T01:00:00Z"},
        "method": {"scores": {}},
        "summary": {"roster": 3},
        "trainees": [
            {
                "id": "t-a",
                "name": "Ann Alpha",
                "degree": "MD",
                "program": "IM",
                "faculty_id": None,
                "best_score": 0.95,
                "works": 2,
            },
            {
                "id": "t-b",
                "name": "Bo Beta",
                "degree": "MD",
                "program": "IM",
                "faculty_id": None,
                "best_score": 0.6,
                "works": 1,
            },
            {
                "id": "t-f3",
                "name": "Fig Three",
                "degree": "MD",
                "program": "IM",
                "faculty_id": "f3",
                "best_score": 0.95,
                "works": 1,
            },
        ],
        "links": [
            {"trainee_id": "t-a", "work_id": "w2", "score": 0.95, "match_type": "given_full"},
            {"trainee_id": "t-a", "work_id": "w1", "score": 0.95, "match_type": "given_full"},
            {"trainee_id": "t-b", "work_id": "w4", "score": 0.6, "match_type": "given_initial"},
            {"trainee_id": "t-f3", "work_id": "w2", "score": 0.95, "match_type": "given_full"},
        ],
    }


def _build(matches: dict | None = None) -> dict:
    return build_network_plus_document(_directory(), _publications(), matches or _matches())


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


def test_trainee_certainty_is_published_so_the_page_can_hide_weak_matches() -> None:
    nodes = {node["id"]: node for node in _build()["nodes"]}

    assert nodes["t-a"]["certainty"] == 0.95
    assert nodes["t-b"]["certainty"] == 0.6
    assert nodes["f1"]["certainty"] is None
    stats = _build()["stats"]
    assert stats["trainee_nodes"] == 3 and stats["certain_trainee_nodes"] == 2


def test_group_member_counts_cover_trainees_and_multi_division_faculty() -> None:
    counts = {group["id"]: group["members"] for group in _build()["groups"]}

    assert counts == {"cardiology": 2, "epidemiology": 2, TRAINEE_GROUP_ID: 3}


def test_published_document_validates_and_is_deterministic() -> None:
    first, second = _build(), _build()
    first["generated_at"] = second["generated_at"] = "fixed"

    validate_network_plus_document(first)
    assert first == second


def test_stale_matches_naming_a_missing_work_are_rejected() -> None:
    matches = _matches()
    matches["links"].append(
        {"trainee_id": "t-a", "work_id": "gone", "score": 0.95, "match_type": "given_full"}
    )

    with pytest.raises(ProfileError, match="re-run the matching"):
        _build(matches)


def test_matches_naming_unknown_faculty_are_rejected() -> None:
    matches = _matches()
    matches["trainees"][2]["faculty_id"] = "nobody"

    with pytest.raises(ProfileError, match="absent from the directory"):
        _build(matches)


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
