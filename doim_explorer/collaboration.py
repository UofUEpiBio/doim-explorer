"""Co-authorship network derived from the published DOIM publication relations.

The publication collector already unions every DOIM faculty member it attributes to a
single work, so a work carrying two or more ``faculty_ids`` *is* a recorded internal
collaboration. This module turns those relations into an undirected, weighted graph and
precomputes its geometry, so the browser only draws a published document instead of
running a layout of its own.

Layout is deterministic on purpose: the same documents must produce byte-identical
coordinates, both so the published artifact diffs cleanly under review and so readers
keep a stable mental map between refreshes.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from typing import Any

# Twelve-slot categorical palette for the twelve official divisions.
#
# Validated with the data-visualization skill's checker against the *all-pairs* pairlist
# (a network is scatter-like: any two nodes can land beside each other), on both the white
# card and the `--brand-paper` page surface: worst-pair CVD delta-E 8.8 against an 8.0
# target, worst-pair normal-vision delta-E 15.8 against a 15.0 hard floor. Four fills sit
# below 3:1 contrast on white, so every node also carries `DIVISION_RINGS` - a darker step
# of its own hue, each clearing 3.4:1 - which discharges the checker's relief rule
# structurally rather than relying on labels alone. Colors are assigned to divisions in
# sorted-id order, so the legend reads as an even hue sweep and a division keeps its color
# when the roster changes. Re-run the checker before editing either tuple.
DIVISION_PALETTE = (
    "#ff7995", "#a83d00", "#9a8208", "#69bd25", "#057050", "#13bbbf",
    "#0180b6", "#3b43c3", "#8268f0", "#d87ffe", "#82108d", "#c53385",
)
DIVISION_RINGS = (
    "#dc5977", "#a63f08", "#9a8208", "#509b02", "#057050", "#09999c",
    "#0180b6", "#3b43c3", "#8268f0", "#be65e3", "#82108d", "#c53385",
)

LAYOUT_NAMES = ("organic", "divisions")
LAYOUT_SEED = 20260921
LAYOUT_ITERATIONS = 400
COORDINATE_PRECISION = 3


def derive_edges(works: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Accumulate one weighted edge per unordered pair of co-attributed faculty."""

    edges: dict[tuple[str, str], dict[str, Any]] = {}
    for work in works:
        faculty_ids = work.get("faculty_ids") or []
        if not isinstance(faculty_ids, list):
            continue
        unique = sorted({str(value) for value in faculty_ids if str(value)})
        if len(unique) < 2:
            continue
        year = work.get("year")
        year = int(year) if isinstance(year, int) and year > 0 else None
        for pair in itertools.combinations(unique, 2):
            edge = edges.get(pair)
            if edge is None:
                edges[pair] = {"weight": 1, "first_year": year, "last_year": year}
                continue
            edge["weight"] += 1
            if year is not None:
                first, last = edge["first_year"], edge["last_year"]
                edge["first_year"] = year if first is None else min(first, year)
                edge["last_year"] = year if last is None else max(last, year)
    return edges


def components(node_ids: Sequence[str], edges: Mapping[tuple[str, str], Any]) -> dict[str, int]:
    """Label connected components, largest first, so component 0 is the main body."""

    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for source, target in edges:
        adjacency[source].add(target)
        adjacency[target].add(source)
    seen: set[str] = set()
    groups: list[list[str]] = []
    for node_id in node_ids:
        if node_id in seen:
            continue
        stack, group = [node_id], []
        seen.add(node_id)
        while stack:
            current = stack.pop()
            group.append(current)
            for neighbour in sorted(adjacency[current]):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        groups.append(sorted(group))
    groups.sort(key=lambda group: (-len(group), group[0]))
    return {node_id: index for index, group in enumerate(groups) for node_id in group}


def _seed_positions(node_ids: Sequence[str]) -> dict[str, tuple[float, float]]:
    """Deterministic starting geometry, so no random number generator is in the loop.

    ``spring_layout`` would otherwise seed itself randomly. Handing it a fixed spiral
    keeps the published coordinates reproducible across interpreters and across the two
    ``networkx`` versions the lock file resolves for Python 3.11 and 3.12.
    """

    total = max(len(node_ids), 1)
    golden = math.pi * (3 - math.sqrt(5))
    return {
        node_id: (
            math.cos(golden * index) * math.sqrt((index + 0.5) / total),
            math.sin(golden * index) * math.sqrt((index + 0.5) / total),
        )
        for index, node_id in enumerate(node_ids)
    }


def _normalized(positions: Mapping[str, Any]) -> dict[str, tuple[float, float]]:
    """Center a layout on the origin and scale it into the [-1, 1] box."""

    if not positions:
        return {}
    xs = [float(value[0]) for value in positions.values()]
    ys = [float(value[1]) for value in positions.values()]
    mid_x = (min(xs) + max(xs)) / 2
    mid_y = (min(ys) + max(ys)) / 2
    extent = max(max(xs) - mid_x, max(ys) - mid_y, 1e-9)
    return {
        node_id: (
            round((float(value[0]) - mid_x) / extent, COORDINATE_PRECISION),
            round((float(value[1]) - mid_y) / extent, COORDINATE_PRECISION),
        )
        for node_id, value in positions.items()
    }


def layout_positions(
    node_divisions: Mapping[str, str],
    edges: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, dict[str, tuple[float, float]]]:
    """Precompute the organic and division-grouped layouts for every node.

    ``networkx`` is imported here rather than at module scope so the base install - which
    does not carry the ``graph`` extra - can still import this module and the contracts
    that reference it.
    """

    if not node_divisions:
        # An empty roster of collaborators is a legitimate document, not an error - a
        # from-scratch directory or a faculty-only refresh can have no shared works yet.
        # ``spring_layout`` itself raises on an empty ``pos`` mapping, so short-circuit.
        return {}

    import networkx as nx

    graph = nx.Graph()
    graph.add_nodes_from(sorted(node_divisions))
    for (source, target), edge in sorted(edges.items()):
        graph.add_edge(source, target, weight=edge["weight"])

    organic = nx.spring_layout(
        graph,
        pos=_seed_positions(sorted(node_divisions)),
        seed=LAYOUT_SEED,
        weight="weight",
        iterations=LAYOUT_ITERATIONS,
    )

    # Park each division on a ring and pack its members into a phyllotaxis spiral,
    # most-connected first, so hubs sit at the centre of their cluster. This is built
    # rather than simulated: a force layout over a dozen small, often disconnected
    # subgraphs sits close enough to degenerate that threaded BLAS reduction order moves
    # the result between runs, which would churn the published coordinates on every
    # refresh. The spiral is pure arithmetic, so it is stable everywhere.
    grouped: dict[str, tuple[float, float]] = {}
    division_ids = sorted(set(node_divisions.values()))
    golden = math.pi * (3 - math.sqrt(5))
    for index, division_id in enumerate(division_ids):
        members = sorted(
            (node_id for node_id, value in node_divisions.items() if value == division_id),
            key=lambda node_id: (-graph.degree(node_id), node_id),
        )
        angle = 2 * math.pi * index / len(division_ids)
        center_x, center_y = math.cos(angle) * 2.6, math.sin(angle) * 2.6
        radius = 0.34 * math.sqrt(len(members))
        for position, node_id in enumerate(members):
            spiral = math.sqrt((position + 0.5) / len(members)) * radius
            grouped[node_id] = (
                center_x + math.cos(golden * position) * spiral,
                center_y + math.sin(golden * position) * spiral,
            )

    organic_positions = _normalized(organic)
    grouped_positions = _normalized(grouped)
    return {
        node_id: {
            "organic": list(organic_positions[node_id]),
            "divisions": list(grouped_positions[node_id]),
        }
        for node_id in sorted(node_divisions)
    }
