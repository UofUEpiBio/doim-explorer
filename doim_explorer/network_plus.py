"""Co-authorship network over faculty *and* matched fellows/residents ("Networks +").

Faculty are linked exactly as in :mod:`doim_explorer.collaboration` (works the publication
collector attributes to two or more of them). Fellows and residents are not in the
directory: they are matched to publication authors by name, outside this package, and
arrive here as ``data/trainee-matches.json``. A matched trainee is linked to every faculty
member attributed to a work they authored, and to every other matched trainee on it.

Because names alone cannot disambiguate people, each trainee carries the certainty of
their best match (``certainty``) and the page can hide the uncertain ones. A trainee who
is also in the faculty directory is one person: they become a single node that belongs to
both groups.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
from typing import Any

from doim_explorer.collaboration import (
    DIVISION_PALETTE,
    DIVISION_RINGS,
    components,
    layout_positions,
)
from doim_explorer.contracts import ProfileError, _now

NETWORK_PLUS_DOCUMENT_TYPE = "doim-network-plus"
NETWORK_PLUS_SCHEMA_VERSION = 1
TRAINEE_MATCHES_DOCUMENT_TYPE = "doim-trainee-matches"

TRAINEE_GROUP_ID = "fellows-residents"
TRAINEE_GROUP_NAME = "Fellows & residents"
# Trainees are told apart from faculty by shape (a diamond), not by hue: the twelve-slot
# division palette was validated as a closed set, and a thirteenth fill is not.
TRAINEE_COLOR, TRAINEE_RING = "#2b2b2b", "#111111"
# A match at or above this is a full first-name match; below it the match is initials only.
CERTAIN_SCORE = 0.8
# Connected groups smaller than this are not part of the force layout (it flings them far
# from the main body and shrinks everything else); they are parked on a ring around it.
SATELLITE_BELOW_NODES = 5
SATELLITE_RING_RADIUS = 1.0


def build_network_plus_document(
    directory: Mapping[str, Any],
    publications: Mapping[str, Any],
    matches: Mapping[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if matches.get("document_type") != TRAINEE_MATCHES_DOCUMENT_TYPE:
        raise ProfileError("trainee matches document_type is not supported")

    divisions = list(directory["divisions"])
    if len(divisions) > len(DIVISION_PALETTE):
        raise ProfileError("the division palette has too few slots; add validated colors")
    faculty_by_id = {str(item["id"]): item for item in directory["faculty"]}
    works = list(publications["works"])
    works_by_id = {str(work["id"]): work for work in works}
    colors = {
        str(division["id"]): (DIVISION_PALETTE[index], DIVISION_RINGS[index])
        for index, division in enumerate(sorted(divisions, key=lambda item: str(item["id"])))
    }

    trainees = {str(item["id"]): item for item in matches["trainees"]}
    if len(trainees) != len(matches["trainees"]):
        raise ProfileError("trainee ids must be unique")
    # Trainees who are also faculty collapse onto the faculty node.
    node_of: dict[str, str] = {}
    for trainee_id, trainee in trainees.items():
        faculty_id = trainee.get("faculty_id")
        if faculty_id is not None and str(faculty_id) not in faculty_by_id:
            raise ProfileError(
                f"trainee {trainee_id} names faculty {faculty_id} absent from the directory"
            )
        node_of[trainee_id] = str(faculty_id) if faculty_id else trainee_id

    members_by_work: dict[str, set[str]] = {}
    for work in works:
        ids = {str(value) for value in work.get("faculty_ids") or [] if str(value)}
        unknown = sorted(ids - set(faculty_by_id))
        if unknown:
            raise ProfileError(
                f"work {work['id']} references faculty absent from the directory: {unknown}"
            )
        members_by_work[str(work["id"])] = ids
    for link in matches["links"]:
        work_id, trainee_id = str(link["work_id"]), str(link["trainee_id"])
        if work_id not in works_by_id:
            raise ProfileError(
                f"trainee match references work {work_id} absent from the publications; "
                "re-run the matching against the current publications"
            )
        if trainee_id not in trainees:
            raise ProfileError(f"trainee link names unknown trainee {trainee_id}")
        members_by_work[work_id].add(node_of[trainee_id])

    edges: dict[tuple[str, str], dict[str, Any]] = {}
    for work_id, members in members_by_work.items():
        if len(members) < 2:
            continue
        year = works_by_id[work_id].get("year")
        year = int(year) if isinstance(year, int) and year > 0 else None
        for pair in itertools.combinations(sorted(members), 2):
            edge = edges.setdefault(pair, {"weight": 0, "first_year": year, "last_year": year})
            edge["weight"] += 1
            if year is not None:
                edge["first_year"] = (
                    year if edge["first_year"] is None else min(edge["first_year"], year)
                )
                edge["last_year"] = (
                    year if edge["last_year"] is None else max(edge["last_year"], year)
                )

    node_ids = sorted({node_id for pair in edges for node_id in pair})
    trainee_node_ids = set(node_of.values())

    def groups_for(node_id: str) -> list[str]:
        groups: list[str] = []
        if node_id in faculty_by_id:
            groups.extend(str(value) for value in faculty_by_id[node_id].get("division_ids") or [])
        if node_id in trainee_node_ids:
            groups.append(TRAINEE_GROUP_ID)
        return groups

    trainee_by_node = {node_of[tid]: item for tid, item in trainees.items()}
    node_divisions: dict[str, str] = {}
    for node_id in node_ids:
        groups = groups_for(node_id)
        unknown = [value for value in groups if value != TRAINEE_GROUP_ID and value not in colors]
        if unknown:
            raise ProfileError(f"node {node_id} names unknown divisions: {unknown}")
        # The primary group colours the dot: a faculty member's first division, otherwise
        # the trainee group. A trainee-faculty member is coloured by their division.
        node_divisions[node_id] = groups[0] if groups else TRAINEE_GROUP_ID

    node_components = components(node_ids, edges)
    positions = _positions_with_satellites(node_divisions, edges, node_components)
    degrees = {node_id: 0 for node_id in node_ids}
    shared = {node_id: 0 for node_id in node_ids}
    for (source, target), edge in edges.items():
        degrees[source] += 1
        degrees[target] += 1
        shared[source] += edge["weight"]
        shared[target] += edge["weight"]
    per_faculty = publications.get("publications_per_faculty") or {}

    nodes = []
    for node_id in node_ids:
        faculty = faculty_by_id.get(node_id)
        trainee = trainee_by_node.get(node_id)
        is_faculty, is_trainee = faculty is not None, trainee is not None
        nodes.append(
            {
                "id": node_id,
                "name": str(faculty["full_name"]) if is_faculty else str(trainee["name"]),
                "kind": "both"
                if is_faculty and is_trainee
                else "faculty"
                if is_faculty
                else "trainee",
                "division_id": node_divisions[node_id],
                "groups": groups_for(node_id),
                "profile_url": str(faculty.get("profile_url", "")) if is_faculty else "",
                "program": str(trainee.get("program", "")) if is_trainee else "",
                "degree": str(trainee.get("degree", "")) if is_trainee else "",
                "certainty": float(trainee["best_score"]) if is_trainee else None,
                "publications": int(per_faculty.get(node_id, 0) or 0)
                if is_faculty
                else int(trainee["works"]),
                "collaborators": degrees[node_id],
                "shared_works": shared[node_id],
                "component": node_components[node_id],
                "positions": positions[node_id],
            }
        )

    group_counts = {value: 0 for value in [*colors, TRAINEE_GROUP_ID]}
    for node in nodes:
        for value in node["groups"]:
            group_counts[value] += 1
    groups = [
        {
            "id": str(division["id"]),
            "name": str(division["name"]),
            "color": colors[str(division["id"])][0],
            "ring": colors[str(division["id"])][1],
            "members": group_counts[str(division["id"])],
        }
        for division in divisions
    ] + [
        {
            "id": TRAINEE_GROUP_ID,
            "name": TRAINEE_GROUP_NAME,
            "color": TRAINEE_COLOR,
            "ring": TRAINEE_RING,
            "members": group_counts[TRAINEE_GROUP_ID],
        }
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
    document = {
        "document_type": NETWORK_PLUS_DOCUMENT_TYPE,
        "schema_version": NETWORK_PLUS_SCHEMA_VERSION,
        "generated_at": generated_at or _now(),
        "sources": {
            "directory_generated_at": directory["generated_at"],
            "publications_generated_at": publications["generated_at"],
            "trainee_matches_generated_at": matches["generated_at"],
            "trainee_matches_publications_generated_at": matches["sources"][
                "publications_generated_at"
            ],
        },
        "stats": {
            "nodes": len(nodes),
            "edges": len(published_edges),
            "faculty_nodes": sum(1 for node in nodes if node["kind"] != "trainee"),
            "trainee_nodes": sum(1 for node in nodes if node["kind"] != "faculty"),
            "certain_trainee_nodes": sum(
                1
                for node in nodes
                if node["kind"] != "faculty" and (node["certainty"] or 0) >= CERTAIN_SCORE
            ),
            "components": len(set(node_components.values())),
            "certain_score": CERTAIN_SCORE,
        },
        "groups": groups,
        "matching": {"method": matches["method"], "summary": matches["summary"]},
        "nodes": nodes,
        "edges": published_edges,
    }
    validate_network_plus_document(document)
    return document


def _positions_with_satellites(
    node_divisions: Mapping[str, str],
    edges: Mapping[tuple[str, str], Mapping[str, Any]],
    node_components: Mapping[str, int],
) -> dict[str, dict[str, list[float]]]:
    """Lay out the large components; seat each small one on a ring around them.

    The result is rescaled into [-1, 1] so it satisfies the same coordinate contract as the
    faculty network. Everything here is arithmetic on deterministic inputs.
    """

    sizes: dict[int, int] = {}
    for label in node_components.values():
        sizes[label] = sizes.get(label, 0) + 1
    main = {
        node_id
        for node_id, label in node_components.items()
        if sizes[label] >= SATELLITE_BELOW_NODES
    }
    if not main:  # a tiny roster: nothing worth separating
        return layout_positions(node_divisions, edges)
    main_positions = layout_positions(
        {node_id: node_divisions[node_id] for node_id in main},
        {pair: edge for pair, edge in edges.items() if pair[0] in main},
    )
    satellites = sorted(
        {label for label in node_components.values() if sizes[label] < SATELLITE_BELOW_NODES}
    )
    result: dict[str, dict[str, list[float]]] = {
        node_id: {layout: list(point) for layout, point in main_positions[node_id].items()}
        for node_id in main
    }
    for index, label in enumerate(satellites):
        members = sorted(node_id for node_id, value in node_components.items() if value == label)
        angle = 2 * math.pi * (index + 0.5) / len(satellites)
        for position, node_id in enumerate(members):
            local = 2 * math.pi * position / len(members)
            radius = 0.05 * len(members)
            point = [
                SATELLITE_RING_RADIUS * math.cos(angle) + radius * math.cos(local),
                SATELLITE_RING_RADIUS * math.sin(angle) + radius * math.sin(local),
            ]
            result[node_id] = {"organic": list(point), "divisions": list(point)}
    scale = max(
        abs(value) for item in result.values() for point in item.values() for value in point
    )
    return {
        node_id: {
            layout: [round(value / scale, 3) for value in point] for layout, point in item.items()
        }
        for node_id, item in result.items()
    }


def validate_network_plus_document(document: Mapping[str, Any]) -> None:
    if document.get("document_type") != NETWORK_PLUS_DOCUMENT_TYPE:
        raise ProfileError("network-plus document_type is not supported")
    if document.get("schema_version") != NETWORK_PLUS_SCHEMA_VERSION:
        raise ProfileError(f"network-plus schema_version must be {NETWORK_PLUS_SCHEMA_VERSION}")
    group_ids = {str(group["id"]) for group in document["groups"]}
    if len(group_ids) != len(document["groups"]):
        raise ProfileError("network-plus group ids must be unique")
    if len({group["color"] for group in document["groups"]}) != len(document["groups"]):
        raise ProfileError("network-plus groups must not share a color")
    node_ids: set[str] = set()
    for node in document["nodes"]:
        if node["id"] in node_ids:
            raise ProfileError("network-plus node ids must be unique")
        node_ids.add(node["id"])
        if node["division_id"] not in group_ids or not set(node["groups"]) <= group_ids:
            raise ProfileError(f"network-plus node {node['id']} names an unknown group")
        for layout in ("organic", "divisions"):
            point = node["positions"].get(layout)
            if not point or len(point) != 2 or any(abs(value) > 1.0001 for value in point):
                raise ProfileError(f"network-plus node {node['id']} has a bad {layout} position")
    seen: set[tuple[str, str]] = set()
    for edge in document["edges"]:
        pair = (edge["source"], edge["target"])
        if pair[0] == pair[1] or not set(pair) <= node_ids or pair in seen:
            raise ProfileError(f"network-plus edge {pair} is invalid or duplicated")
        seen.add(pair)
