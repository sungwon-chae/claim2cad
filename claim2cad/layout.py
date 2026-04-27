"""Graph-based layout for IR components.

Builds a directed graph from the IR's `attached_to`, `connects`, and
`contains` relations, picks a root (largest in-/out-degree, with a name
preference for "base/frame/housing"), then BFS-places children with a
type-aware offset.

For Phase 5 the layout's job is *legibility*, not physical accuracy. We want
parts to be visually separated and adjacent components to actually touch
where the relation says they should.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass

from claim2cad.ir_schema import ClaimIR, Component

logger = logging.getLogger(__name__)


@dataclass
class Placement:
    component_id: str
    position: tuple[float, float, float]
    axis_index: int  # 0=x, 1=y, 2=z — used for orienting cylinders


# Magic numbers chosen to make 9-component examples fit in a ~300 mm-wide box.
DEFAULT_SPACING = 60.0


_ROOT_NAME_PREFERENCE = ["base", "frame", "housing", "ground", "fixed_link"]


def _children_graph(ir: ClaimIR) -> dict[str, list[str]]:
    """Build an adjacency list of "this component's children" using relations.

    `attached_to`/`connects` edges go source → target ("child attached to
    parent"); we reverse them so the parent points at the child.
    `contains` edges already point parent → child.
    """
    graph: dict[str, list[str]] = defaultdict(list)
    for rel in ir.relations:
        if rel.kind in {"attached_to", "connects"}:
            # "first_link attached_to base" → base is the parent of first_link.
            graph[rel.target].append(rel.source)
        elif rel.kind == "contains":
            graph[rel.source].append(rel.target)
        # rotates_about / translates_along / transmits_force_to are decorative.
    return graph


def _pick_root(ir: ClaimIR, graph: dict[str, list[str]]) -> str:
    """Heuristic: prefer base/frame/housing names; otherwise highest out-degree."""
    components = {c.id: c for c in ir.components}
    if not components:
        raise ValueError("IR has no components")

    for preferred in _ROOT_NAME_PREFERENCE:
        if preferred in components:
            return preferred

    # Highest out-degree (most children).
    best_id = max(components, key=lambda cid: len(graph.get(cid, [])))
    return best_id


def layout_components(ir: ClaimIR, *, spacing: float = DEFAULT_SPACING) -> dict[str, Placement]:
    """Return component_id → Placement.

    BFS from the chosen root: assign root to the origin, place its children
    in a row at +spacing along x; their children at +spacing along y; etc.
    Components not reachable from the root are placed in a tail row along x
    *below* the main BFS layout.
    """
    components = {c.id: c for c in ir.components}
    if not components:
        return {}

    graph = _children_graph(ir)
    root_id = _pick_root(ir, graph)

    placements: dict[str, Placement] = {}
    placements[root_id] = Placement(
        component_id=root_id, position=(0.0, 0.0, 0.0), axis_index=0
    )

    visited = {root_id}
    queue: deque[tuple[str, int]] = deque([(root_id, 0)])
    siblings_at_depth: dict[int, int] = defaultdict(int)

    while queue:
        parent_id, depth = queue.popleft()
        parent_pos = placements[parent_id].position
        children = graph.get(parent_id, [])
        # Spread children along the depth-axis: x, then y, then z, repeating.
        axis = (depth % 3)
        for i, child_id in enumerate(children):
            if child_id in visited or child_id not in components:
                continue
            visited.add(child_id)
            offset = [0.0, 0.0, 0.0]
            offset[axis] = spacing * (i + 1)
            new_pos = (
                parent_pos[0] + offset[0],
                parent_pos[1] + offset[1],
                parent_pos[2] + offset[2],
            )
            placements[child_id] = Placement(
                component_id=child_id,
                position=new_pos,
                axis_index=axis,
            )
            queue.append((child_id, depth + 1))
            siblings_at_depth[depth + 1] += 1

    # Orphans (no incoming edges from the root subtree).
    orphans = [c for c in ir.components if c.id not in visited]
    for i, comp in enumerate(orphans, start=1):
        placements[comp.id] = Placement(
            component_id=comp.id,
            position=(spacing * i, -spacing * 1.5, 0.0),
            axis_index=0,
        )
        logger.debug("Orphan %s placed in tail row (i=%d)", comp.id, i)

    return placements


def primary_axis_for(component: Component, placement: Placement) -> int:
    """Return 0/1/2 for x/y/z — the axis a rod-like component should align with."""
    return placement.axis_index


__all__ = [
    "DEFAULT_SPACING",
    "Placement",
    "layout_components",
    "primary_axis_for",
]
