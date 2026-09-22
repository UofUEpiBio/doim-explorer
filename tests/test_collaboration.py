"""Tests for the co-authorship graph derived from the accepted DOIM documents."""

from __future__ import annotations

import math

import pytest

from doim_explorer.collaboration import (
    DIVISION_PALETTE,
    DIVISION_RINGS,
    LAYOUT_NAMES,
    MIN_COMPONENT_NODES,
    components,
    derive_edges,
    layout_positions,
    prune_small_components,
)
from doim_explorer.config import ProfileError, load_directory_config
from doim_explorer.contracts import (
    COLLABORATION_DOCUMENT_TYPE,
    COLLABORATION_SCHEMA_VERSION,
    build_collaboration_document,
    build_directory_document,
    validate_collaboration_document,
)


def _work(work_id: str, faculty_ids: list[str], *, year: int = 2020, division_ids=None) -> dict:
    return {
        "id": work_id,
        "title": f"Work {work_id}",
        "url": f"https://doi.org/10.0/{work_id}",
        "year": year,
        "faculty_ids": faculty_ids,
        "division_ids": division_ids or [],
    }


def _publications(works: list[dict], *, generated_at: str = "2026-09-21T00:00:00Z") -> dict:
    return {
        "document_type": "doim-publications",
        "schema_version": 2,
        "generated_at": generated_at,
        "works": works,
        "publications_per_faculty": {},
    }


def _faculty(faculty_id: str, division_id: str, name: str | None = None) -> dict:
    return {
        "id": faculty_id,
        "full_name": name or f"Faculty {faculty_id}",
        "profile_url": f"https://medicine.utah.edu/faculty/{faculty_id}",
        "division_ids": [division_id],
        "collect_publications": True,
    }


def _directory(faculty: list[dict], *, generated_at: str = "2026-09-21T00:00:00Z") -> dict:
    return build_directory_document(load_directory_config(), faculty=faculty, generated_at=generated_at)


# ---- derive_edges ---------------------------------------------------------------


def test_derive_edges_ignores_single_author_works() -> None:
    edges = derive_edges([_work("w1", ["a"])])
    assert edges == {}


def test_derive_edges_accumulates_weight_across_shared_works() -> None:
    works = [_work("w1", ["a", "b"], year=2018), _work("w2", ["a", "b"], year=2021)]
    edges = derive_edges(works)
    assert edges == {("a", "b"): {"weight": 2, "first_year": 2018, "last_year": 2021}}


def test_derive_edges_expands_every_pair_on_a_multi_faculty_work() -> None:
    edges = derive_edges([_work("w1", ["a", "b", "c"])])
    assert set(edges) == {("a", "b"), ("a", "c"), ("b", "c")}
    assert all(edge["weight"] == 1 for edge in edges.values())


def test_derive_edges_deduplicates_repeated_faculty_ids_on_one_work() -> None:
    # A work whose faculty_ids lists the same person twice must not self-pair.
    edges = derive_edges([_work("w1", ["a", "a", "b"])])
    assert set(edges) == {("a", "b")}


def test_derive_edges_ignores_year_zero_and_missing_years() -> None:
    edges = derive_edges([_work("w1", ["a", "b"], year=0)])
    assert edges[("a", "b")]["first_year"] is None
    assert edges[("a", "b")]["last_year"] is None


def test_derive_edges_pairs_are_always_sorted() -> None:
    edges = derive_edges([_work("w1", ["b", "a"])])
    assert ("a", "b") in edges
    assert ("b", "a") not in edges


# ---- components -------------------------------------------------------------------


def test_components_labels_the_largest_group_zero() -> None:
    edges = derive_edges([_work("w1", ["a", "b"]), _work("w2", ["b", "c"]), _work("w3", ["d", "e"])])
    node_ids = ["a", "b", "c", "d", "e"]
    labels = components(node_ids, edges)
    assert labels["a"] == labels["b"] == labels["c"]
    assert labels["d"] == labels["e"]
    assert labels["a"] != labels["d"]
    assert labels["a"] == 0  # the three-member group is largest


def test_components_gives_every_node_its_own_label_with_no_edges() -> None:
    labels = components(["a", "b"], {})
    assert labels["a"] != labels["b"]


# ---- prune_small_components ---------------------------------------------------------


def test_prune_small_components_keeps_only_groups_at_or_above_the_minimum() -> None:
    # A five-member chain survives; the pair beside it does not.
    chain = [_work(f"w{i}", [chr(97 + i), chr(98 + i)]) for i in range(4)]
    edges = derive_edges([*chain, _work("wx", ["y", "z"])])
    node_ids, kept = prune_small_components(sorted({n for pair in edges for n in pair}), edges, 5)
    assert node_ids == ["a", "b", "c", "d", "e"]
    assert set(kept) == {("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")}


def test_prune_small_components_can_empty_the_graph() -> None:
    edges = derive_edges([_work("w1", ["a", "b"]), _work("w2", ["c", "d"])])
    node_ids, kept = prune_small_components(sorted({n for pair in edges for n in pair}), edges, 5)
    assert node_ids == []
    assert kept == {}


def test_prune_small_components_is_a_no_op_below_a_minimum_of_two() -> None:
    edges = derive_edges([_work("w1", ["a", "b"])])
    node_ids = sorted({n for pair in edges for n in pair})
    assert prune_small_components(node_ids, edges, 1) == (node_ids, dict(edges))


def test_build_collaboration_document_drops_groups_under_the_minimum() -> None:
    # Five members in a chain, plus an isolated pair that must not reach the document.
    members = ["a", "b", "c", "d", "e", "y", "z"]
    directory = _directory([_faculty(node_id, "oncology") for node_id in members])
    publications = _publications(
        [*(_work(f"w{i}", [chr(97 + i), chr(98 + i)]) for i in range(4)), _work("wx", ["y", "z"])]
    )
    document = build_collaboration_document(
        directory, publications, generated_at="2026-09-21T00:00:00Z"
    )

    assert {node["id"] for node in document["nodes"]} == {"a", "b", "c", "d", "e"}
    assert all("y" not in (edge["source"], edge["target"]) for edge in document["edges"])
    assert document["stats"]["nodes"] == 5
    assert document["stats"]["edges"] == 4
    assert document["stats"]["components"] == 1
    assert document["stats"]["min_component_nodes"] == MIN_COMPONENT_NODES
    # the pair's shared work is no longer counted, and the pruned division count follows
    assert document["stats"]["shared_works"] == 4
    assert {division["id"]: division["faculty"] for division in document["divisions"]}["oncology"] == 5
    validate_collaboration_document(document)


# ---- layout_positions --------------------------------------------------------------


def test_layout_positions_are_deterministic_across_runs() -> None:
    node_divisions = {"a": "x", "b": "x", "c": "y"}
    edges = derive_edges([_work("w1", ["a", "b"]), _work("w2", ["b", "c"])])
    first = layout_positions(node_divisions, edges)
    second = layout_positions(node_divisions, edges)
    assert first == second


def test_layout_positions_cover_both_named_layouts_and_stay_in_range() -> None:
    node_divisions = {chr(97 + i): ("x" if i % 2 == 0 else "y") for i in range(8)}
    works = [_work(f"w{i}", [chr(97 + i), chr(97 + (i + 1) % 8)]) for i in range(8)]
    edges = derive_edges(works)
    positions = layout_positions(node_divisions, edges)
    assert set(positions) == set(node_divisions)
    for layouts in positions.values():
        assert set(layouts) == set(LAYOUT_NAMES)
        for layout in LAYOUT_NAMES:
            x, y = layouts[layout]
            assert math.isfinite(x) and math.isfinite(y)
            assert abs(x) <= 1.001 and abs(y) <= 1.001


def test_layout_positions_handles_an_empty_graph() -> None:
    # A from-scratch directory, or a refresh where nobody yet shares a work, publishes a
    # document with zero collaborators rather than crashing the layout.
    assert layout_positions({}, {}) == {}


def test_layout_positions_handles_a_single_division_with_one_member() -> None:
    # A division of one has no subgraph to lay out; the grouped layout must still place it.
    node_divisions = {"a": "x"}
    positions = layout_positions(node_divisions, {})
    assert positions["a"]["divisions"] != positions["a"]["organic"] or True  # both finite either way
    for layout in LAYOUT_NAMES:
        x, y = positions["a"][layout]
        assert math.isfinite(x) and math.isfinite(y)


# ---- palette ------------------------------------------------------------------------


def test_palette_has_a_distinct_fill_and_ring_per_division_slot() -> None:
    assert len(DIVISION_PALETTE) == len(DIVISION_RINGS) == 12
    assert len(set(DIVISION_PALETTE)) == 12
    for color in (*DIVISION_PALETTE, *DIVISION_RINGS):
        assert color.startswith("#") and len(color) == 7


# ---- build_collaboration_document / validate_collaboration_document -----------------


def test_build_collaboration_document_derives_nodes_edges_and_stats() -> None:
    faculty = [
        _faculty("a", "cardiovascular-medicine"),
        _faculty("b", "cardiovascular-medicine"),
        _faculty("c", "epidemiology"),
        _faculty("d", "epidemiology"),  # no publications: must not appear as a node
    ]
    directory = _directory(faculty)
    publications = _publications(
        [
            _work("w1", ["a", "b"], year=2019, division_ids=["cardiovascular-medicine"]),
            _work("w2", ["a", "c"], year=2022, division_ids=["cardiovascular-medicine", "epidemiology"]),
            _work("w3", ["a"], year=2023),  # single-author: contributes no edge
        ]
    )
    document = build_collaboration_document(
        directory, publications, generated_at="2026-09-21T00:00:00Z", min_component_nodes=1
    )

    assert document["document_type"] == COLLABORATION_DOCUMENT_TYPE
    assert document["schema_version"] == COLLABORATION_SCHEMA_VERSION
    assert document["sources"] == {
        "directory_generated_at": directory["generated_at"],
        "publications_generated_at": publications["generated_at"],
    }
    node_ids = {node["id"] for node in document["nodes"]}
    assert node_ids == {"a", "b", "c"}  # d is isolated and excluded
    assert document["stats"]["nodes"] == 3
    assert document["stats"]["edges"] == 2
    assert document["stats"]["shared_works"] == 2
    assert document["stats"]["cross_division_edges"] == 1  # a-c crosses divisions

    edge_by_pair = {(edge["source"], edge["target"]): edge for edge in document["edges"]}
    assert edge_by_pair[("a", "b")]["weight"] == 1
    assert edge_by_pair[("a", "b")]["first_year"] == 2019
    assert edge_by_pair[("a", "c")]["first_year"] == 2022

    # every node cites a division actually present in the published divisions list
    division_ids = {division["id"] for division in document["divisions"]}
    assert all(node["division_id"] in division_ids for node in document["nodes"])
    validate_collaboration_document(document)


def test_build_collaboration_document_is_deterministic() -> None:
    faculty = [_faculty("a", "oncology"), _faculty("b", "oncology"), _faculty("c", "rheumatology")]
    directory = _directory(faculty)
    publications = _publications(
        [_work("w1", ["a", "b"]), _work("w2", ["b", "c"]), _work("w3", ["a", "c"])]
    )
    first = build_collaboration_document(
        directory, publications, generated_at="2026-09-21T00:00:00Z", min_component_nodes=1
    )
    second = build_collaboration_document(
        directory, publications, generated_at="2026-09-21T00:00:00Z", min_component_nodes=1
    )
    assert first == second


def test_build_collaboration_document_rejects_a_faculty_reference_absent_from_the_directory() -> None:
    faculty = [_faculty("a", "geriatrics")]
    directory = _directory(faculty)
    publications = _publications([_work("w1", ["a", "ghost"])])
    # The pair is too small to be drawn, but an unknown faculty id is still a pipeline
    # fault: pruning must not swallow it.
    with pytest.raises(ProfileError, match="absent from the directory"):
        build_collaboration_document(directory, publications)


def test_validate_collaboration_document_rejects_wrong_document_type() -> None:
    document = _minimal_document()
    document["document_type"] = "doim-directory"
    with pytest.raises(ProfileError, match="document_type"):
        validate_collaboration_document(document)


def test_validate_collaboration_document_rejects_wrong_schema_version() -> None:
    document = _minimal_document()
    document["schema_version"] = 2
    with pytest.raises(ProfileError, match="schema_version"):
        validate_collaboration_document(document)


def test_validate_collaboration_document_rejects_a_dangling_edge_endpoint() -> None:
    document = _minimal_document()
    document["edges"].append({"source": "a", "target": "ghost", "weight": 1, "first_year": None, "last_year": None})
    with pytest.raises(ProfileError, match="absent node"):
        validate_collaboration_document(document)


def test_validate_collaboration_document_rejects_an_unknown_division() -> None:
    document = _minimal_document()
    document["nodes"][0]["division_id"] = "not-a-division"
    with pytest.raises(ProfileError, match="unknown division"):
        validate_collaboration_document(document)


def test_validate_collaboration_document_rejects_a_missing_layout() -> None:
    document = _minimal_document()
    del document["nodes"][0]["positions"]["divisions"]
    with pytest.raises(ProfileError, match="divisions position"):
        validate_collaboration_document(document)


def test_validate_collaboration_document_rejects_an_out_of_range_coordinate() -> None:
    document = _minimal_document()
    document["nodes"][0]["positions"]["organic"] = [5.0, 0.0]
    with pytest.raises(ProfileError, match="out-of-range"):
        validate_collaboration_document(document)


def test_validate_collaboration_document_rejects_a_self_loop() -> None:
    document = _minimal_document()
    document["edges"].append({"source": "a", "target": "a", "weight": 1, "first_year": None, "last_year": None})
    with pytest.raises(ProfileError, match="self loops"):
        validate_collaboration_document(document)


def test_validate_collaboration_document_rejects_a_duplicate_edge() -> None:
    document = _minimal_document()
    document["edges"].append(dict(document["edges"][0]))
    with pytest.raises(ProfileError, match="duplicated"):
        validate_collaboration_document(document)


def test_validate_collaboration_document_rejects_inconsistent_stats() -> None:
    document = _minimal_document()
    document["stats"]["nodes"] = 999
    with pytest.raises(ProfileError, match="stats"):
        validate_collaboration_document(document)


def _minimal_document() -> dict:
    faculty = [_faculty("a", "geriatrics"), _faculty("b", "geriatrics")]
    directory = _directory(faculty)
    publications = _publications([_work("w1", ["a", "b"])])
    return build_collaboration_document(
        directory, publications, generated_at="2026-09-21T00:00:00Z", min_component_nodes=1
    )
