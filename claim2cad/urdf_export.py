"""IR → URDF exporter.

URDF (Unified Robot Description Format) describes a kinematic chain as
a tree of *links* connected by *joints*. We map:

- IR structural components (block, rod, plate, link, shaft, frame, housing)
  → URDF ``<link>`` with a `<visual><geometry>` whose primitive matches
  the component kind.
- IR connection components (revolute_joint, prismatic_joint, fastener,
  fixed_joint, spherical_joint) → URDF ``<joint>``.

Parent/child wiring comes from the IR's `Relation` graph:

- ``connects(source, target, via=joint)`` → joint connects ``target``
  (parent) ↔ ``source`` (child) via ``joint``.
- ``attached_to(source, target)`` → an implicit fixed joint between
  ``target`` (parent) and ``source`` (child) when no explicit joint
  component is in the way.

The URDF root is the IR's layout root (preferring frame / base / housing
names; see :mod:`claim2cad.layout`). Components not reachable from the
root via a parent chain are emitted as floating-fixed children of the
root, which keeps `check_urdf` happy at the cost of a flat tree for
malformed IRs.
"""
from __future__ import annotations

import argparse
import json
import logging
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from xml.dom import minidom

from claim2cad.ir_schema import ClaimIR, Component
from claim2cad.layout import DEFAULT_SPACING, layout_components

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

# IR-kind → URDF-joint-type. Anything missing falls back to "fixed".
JOINT_TYPE_MAP = {
    "revolute_joint": "revolute",
    "prismatic_joint": "prismatic",
    "spherical_joint": "continuous",
    "fixed_joint": "fixed",
    "fastener": "fixed",
}


@dataclass
class URDFExport:
    xml: str
    n_links: int
    n_joints: int
    movable_joints: list[str]


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------


def _visual_for(component: Component) -> dict[str, object]:
    """Return URDF `<visual>` geometry parameters for a component.

    Uses simple primitives (box, cylinder, sphere). Sizes mirror the
    ones used by `claim2cad/ir_to_cad._primitive_for` so the URDF and
    GLB visuals are roughly compatible.
    """
    kind = (component.kind or "").lower()
    category = component.category

    if category == "structural":
        if kind in {"rod", "shaft", "link"}:
            return {"shape": "cylinder", "radius": 0.006, "length": 0.050}
        if kind == "plate":
            return {"shape": "box", "size": (0.060, 0.060, 0.004)}
        if kind == "shell":
            return {"shape": "box", "size": (0.050, 0.050, 0.008)}
        if kind == "frame":
            return {"shape": "box", "size": (0.080, 0.080, 0.016)}
        if kind == "housing":
            return {"shape": "box", "size": (0.060, 0.050, 0.030)}
        return {"shape": "box", "size": (0.040, 0.040, 0.020)}

    if category == "connection":
        if kind == "revolute_joint":
            return {"shape": "cylinder", "radius": 0.008, "length": 0.018}
        if kind == "prismatic_joint":
            return {"shape": "box", "size": (0.028, 0.014, 0.014)}
        if kind == "spherical_joint":
            return {"shape": "sphere", "radius": 0.009}
        if kind == "fastener":
            return {"shape": "cylinder", "radius": 0.003, "length": 0.014}
        return {"shape": "box", "size": (0.014, 0.014, 0.014)}

    if category == "functional":
        if kind == "sensor":
            return {"shape": "sphere", "radius": 0.006}
        if kind == "actuator":
            return {"shape": "cylinder", "radius": 0.010, "length": 0.030}
        if kind == "end_effector":
            return {"shape": "box", "size": (0.022, 0.032, 0.014)}
        if kind == "controller":
            return {"shape": "box", "size": (0.030, 0.024, 0.010)}
        return {"shape": "sphere", "radius": 0.008}

    return {"shape": "box", "size": (0.020, 0.020, 0.020)}


# ---------------------------------------------------------------------------
# Graph wiring
# ---------------------------------------------------------------------------


def _is_joint_component(c: Component) -> bool:
    return c.category == "connection" and c.kind in JOINT_TYPE_MAP


def _build_kinematic_tree(ir: ClaimIR) -> tuple[str, dict[str, str], list[tuple[str, Optional[str], str]]]:
    """Return (root_id, parent_of, joint_edges) where:

    - ``parent_of[child_id] = parent_id`` for every child in the tree
    - ``joint_edges`` is a list of ``(joint_component_id_or_synthetic, child_id, parent_id)``
      tuples in BFS order.

    Synthetic fixed joints are emitted (with ``joint_component_id=None``)
    when an `attached_to` relation has no explicit joint between the two
    components.
    """
    components = {c.id: c for c in ir.components}

    # Use the same root-picker as the layout engine so the URDF and the
    # GLB share an interpretation of "what's the base".
    placements = layout_components(ir, spacing=DEFAULT_SPACING)
    if not placements:
        raise ValueError("IR has no components")

    # Pick root: minimum-distance from origin in the layout, or "base"-like
    # name if present.
    name_priority = ["base", "frame", "housing", "ground", "fixed_link"]
    root_id: Optional[str] = None
    for name in name_priority:
        if name in components:
            root_id = name
            break
    if root_id is None:
        root_id = min(placements, key=lambda cid: sum(abs(v) for v in placements[cid].position))

    # Build adjacency from relations (undirected for traversal but we keep
    # source / target context to know if there's a joint between them).
    edges_by_pair: dict[tuple[str, str], Optional[str]] = {}

    def _add_edge(a: str, b: str, joint_id: Optional[str]) -> None:
        if a == b or a not in components or b not in components:
            return
        key = (a, b)
        rev = (b, a)
        if key in edges_by_pair and edges_by_pair[key] is not None:
            return
        if rev in edges_by_pair and edges_by_pair[rev] is not None:
            return
        edges_by_pair[key] = joint_id

    for rel in ir.relations:
        if rel.kind == "connects":
            joint_id = rel.via if rel.via and _is_joint_component(components.get(rel.via, components[rel.source])) else None
            # The joint component is the via.
            _add_edge(rel.target, rel.source, joint_id)
        elif rel.kind == "attached_to":
            _add_edge(rel.target, rel.source, None)
        elif rel.kind == "rotates_about":
            # source rotates about target (the joint).
            joint_id = rel.target if _is_joint_component(components.get(rel.target, components[rel.source])) else None
            # Find the parent of the joint (something the joint connects to).
            # Heuristic: any component connected via attached_to or connects.
            _add_edge(rel.target, rel.source, joint_id)

    # Build adjacency for BFS.
    adj: dict[str, list[tuple[str, Optional[str]]]] = defaultdict(list)
    for (a, b), joint_id in edges_by_pair.items():
        adj[a].append((b, joint_id))
        adj[b].append((a, joint_id))

    parent_of: dict[str, str] = {}
    joint_edges: list[tuple[Optional[str], str, str]] = []
    visited = {root_id}
    from collections import deque
    q: deque[str] = deque([root_id])
    while q:
        cur = q.popleft()
        for nxt, joint_id in adj[cur]:
            if nxt in visited:
                continue
            visited.add(nxt)
            # Skip joint components themselves — they become URDF joints,
            # not links. (We collapse the joint into the link↔link edge.)
            if _is_joint_component(components[nxt]):
                # Walk one more step from joint to its other endpoint.
                for joint_neighbor, _ in adj[nxt]:
                    if joint_neighbor in visited:
                        continue
                    if joint_neighbor == cur:
                        continue
                    visited.add(joint_neighbor)
                    parent_of[joint_neighbor] = cur
                    joint_edges.append((nxt, joint_neighbor, cur))
                    q.append(joint_neighbor)
                continue
            parent_of[nxt] = cur
            joint_edges.append((joint_id, nxt, cur))
            q.append(nxt)

    # Orphans — connect them to the root with synthetic fixed joints.
    for cid, c in components.items():
        if cid == root_id or cid in parent_of or _is_joint_component(c):
            continue
        parent_of[cid] = root_id
        joint_edges.append((None, cid, root_id))

    return root_id, parent_of, joint_edges


# ---------------------------------------------------------------------------
# XML emission
# ---------------------------------------------------------------------------


def _xyz_str(t: tuple[float, float, float]) -> str:
    # build123d/our layout uses millimetres — convert to metres for URDF.
    return f"{t[0]/1000:.4f} {t[1]/1000:.4f} {t[2]/1000:.4f}"


def _add_visual(link_el: ET.Element, component: Component) -> None:
    visual = ET.SubElement(link_el, "visual")
    geom = ET.SubElement(visual, "geometry")
    spec = _visual_for(component)
    if spec["shape"] == "box":
        sx, sy, sz = spec["size"]  # type: ignore[misc]
        ET.SubElement(geom, "box", size=f"{sx} {sy} {sz}")
    elif spec["shape"] == "cylinder":
        ET.SubElement(geom, "cylinder", radius=f"{spec['radius']}", length=f"{spec['length']}")
    elif spec["shape"] == "sphere":
        ET.SubElement(geom, "sphere", radius=f"{spec['radius']}")


def _joint_origin(component_id: str, parent_id: str, ir: ClaimIR) -> tuple[float, float, float]:
    placements = layout_components(ir, spacing=DEFAULT_SPACING)
    p_child = placements.get(component_id)
    p_parent = placements.get(parent_id)
    if p_child is None or p_parent is None:
        return (0.0, 0.0, 0.0)
    return (
        p_child.position[0] - p_parent.position[0],
        p_child.position[1] - p_parent.position[1],
        p_child.position[2] - p_parent.position[2],
    )


def export_urdf(ir: ClaimIR, *, robot_name: Optional[str] = None) -> URDFExport:
    components = {c.id: c for c in ir.components}
    name = robot_name or _safe_robot_name(ir.title or "claim_robot")

    root_id, parent_of, joint_edges = _build_kinematic_tree(ir)

    robot = ET.Element("robot", name=name)

    # Emit links — only for non-joint components, in deterministic order.
    link_ids = [cid for cid, c in components.items() if not _is_joint_component(c)]
    link_ids.sort()
    for cid in link_ids:
        link = ET.SubElement(robot, "link", name=cid)
        _add_visual(link, components[cid])

    # Emit joints. Stable order: by child id.
    movable: list[str] = []
    joint_edges.sort(key=lambda e: (e[2], e[1]))  # by parent then child for readability
    for joint_id, child_id, parent_id in joint_edges:
        if joint_id is None:
            # Synthetic fixed joint.
            joint_name = f"_attach_{parent_id}_to_{child_id}"
            urdf_type = "fixed"
            axis = (0.0, 0.0, 1.0)
            ir_kind = ""
        else:
            joint_comp = components[joint_id]
            joint_name = joint_id
            ir_kind = joint_comp.kind
            urdf_type = JOINT_TYPE_MAP.get(joint_comp.kind, "fixed")
            axis = (0.0, 0.0, 1.0)
        joint = ET.SubElement(robot, "joint", name=joint_name, type=urdf_type)
        ET.SubElement(joint, "parent", link=parent_id)
        ET.SubElement(joint, "child", link=child_id)
        origin_xyz = _joint_origin(child_id, parent_id, ir)
        ET.SubElement(joint, "origin", xyz=_xyz_str(origin_xyz), rpy="0 0 0")
        if urdf_type in {"revolute", "prismatic", "continuous"}:
            ET.SubElement(joint, "axis", xyz=f"{axis[0]} {axis[1]} {axis[2]}")
            if urdf_type == "revolute":
                ET.SubElement(joint, "limit", lower="-3.14", upper="3.14",
                              velocity="1.0", effort="100")
            elif urdf_type == "prismatic":
                ET.SubElement(joint, "limit", lower="0.0", upper="0.1",
                              velocity="0.5", effort="100")
            movable.append(joint_name)

    rough = ET.tostring(robot, encoding="unicode")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ")
    return URDFExport(
        xml=pretty,
        n_links=len(link_ids),
        n_joints=len(joint_edges),
        movable_joints=movable,
    )


def _safe_robot_name(name: str) -> str:
    out = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name.lower())
    return out.strip("_") or "claim_robot"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="claim2cad.urdf_export")
    p.add_argument("--ir", type=Path, required=True,
                   help="Path to claim_ir.json")
    p.add_argument("--out", type=Path, default=None,
                   help="Output path (default: <ir-dir>/model.urdf)")
    args = p.parse_args(argv)

    logging.getLogger("claim2cad").setLevel(logging.INFO)

    ir = ClaimIR.model_validate_json(args.ir.read_text(encoding="utf-8"))
    result = export_urdf(ir)

    out_path = args.out or args.ir.parent / "model.urdf"
    out_path.write_text(result.xml, encoding="utf-8")

    logger.info("Wrote %s (%d links, %d joints, %d movable)",
                out_path, result.n_links, result.n_joints, len(result.movable_joints))
    print(json.dumps({
        "out": str(out_path),
        "links": result.n_links,
        "joints": result.n_joints,
        "movable": result.movable_joints,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["URDFExport", "export_urdf"]
