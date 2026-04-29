"""Scene-level scaffold for assembly-first reconstruction.

The V11-14 / V11-18 pipeline built each component independently from
its VLM-suggested pose, which gave geometrically-correct parts but a
visual collage: 15-of-25 hinge components stacked at the same origin,
no door panel, no hinge cluster separation.

This module introduces a *scaffold-first* layer:

1. **SceneGroup** — a named subassembly (door_panel, fixed_frame,
   upper_hinge, lower_hinge, pintle_axis, power_mechanism, fasteners)
   with its own origin / orientation / nominal bbox / parent group.
2. **SceneScaffold** — a graph of SceneGroups + a mapping from claim
   ``component_id`` → scene_group.
3. **LiftOffDoorHingeScaffold** — a patent-family-specific template
   for US4807331A and US4470181A and US4502185A class hinges. It
   knows the canonical scene composition (large door, larger frame,
   two hinge clusters, vertical pintle axis) and the typical
   component-to-group mapping (e.g. ``mounting_wall`` →
   ``fixed_frame``, ``main_member`` → ``upper_hinge``, etc.).

The solver in :mod:`claim2cad.assembly_solver` consumes the scaffold
in a new ``build_assembly_scaffold_first`` entry point: it places each
SceneGroup's origin first, then builds each component subordinated
to its group's origin and orientation. Components without a group
fall back to the V11-14 path so the existing 30-example corpus keeps
working.

Patent-family scaffolds are explicit and heuristic. The ``README``
makes it clear that automatic generic scaffold inference is future
work; for now the user gets visibly-coherent output on the targeted
hard example and the architecture supports adding more patent
families as needed.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data shape
# ---------------------------------------------------------------------------


@dataclass
class SceneGroup:
    """One subassembly node in the scaffold graph.

    ``origin_mm`` is the group's centre in world coordinates.
    ``orientation_axis`` says which world axis is the group's "up"
    (defaults to +Z).
    ``nominal_bbox_mm`` is the rough envelope this group occupies —
    used by render-time auto-fit and by the solver to clamp component
    poses.
    ``parent_id`` lets groups nest (e.g. an ``upper_hinge`` may be
    a child of ``door_panel`` so moving the door drags both hinges).
    ``component_ids`` is the list of claim component_ids this group
    owns. The solver subordinates each component's pose to the group.
    """

    id: str
    label: str
    origin_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    orientation_axis: str = "Z"
    nominal_bbox_mm: tuple[float, float, float] = (50.0, 50.0, 50.0)
    parent_id: str | None = None
    component_ids: list[str] = field(default_factory=list)
    attaches_to: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class SceneScaffold:
    """A graph of SceneGroups + IR-id → group lookup."""

    name: str
    groups: list[SceneGroup] = field(default_factory=list)
    component_to_group: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "groups": [asdict(g) for g in self.groups],
            "component_to_group": dict(self.component_to_group),
            "notes": self.notes,
        }

    def by_id(self) -> dict[str, SceneGroup]:
        return {g.id: g for g in self.groups}

    def group_for_component(self, component_id: str) -> SceneGroup | None:
        gid = self.component_to_group.get(component_id)
        if gid is None:
            return None
        return self.by_id().get(gid)


# ---------------------------------------------------------------------------
# Patent-family scaffold: lift-off door hinge
# ---------------------------------------------------------------------------


# Canonical component-id → group mapping for the US4807331A claim
# vocabulary. Keys are claim component_ids; values are scene_group
# ids. Components named in the IR but not in this mapping fall back
# to a default group based on their kind / category — see
# :func:`assign_scaffold_group`.
US4807331A_COMPONENT_GROUPS: dict[str, str] = {
    # Vehicle / context panels
    "vehicle_body": "fixed_frame",
    "door_half_member": "door_panel",
    "bight_wall": "door_panel",
    "first_sidewall": "door_panel",
    "second_sidewall": "door_panel",
    "leaf_flange": "door_panel",
    "leaf_flange_pintle_pin_hole": "door_panel",
    # Body-half (frame side) bracket assembly
    "body_half_sub_assembly": "fixed_frame",
    "hinge_body_half_assembly": "upper_hinge",
    "main_member": "upper_hinge",
    "mounting_wall": "fixed_frame",
    "main_member_pintle_pin_hole": "upper_hinge",
    "upper_extension": "upper_hinge",
    "lower_extension": "lower_hinge",
    # Inner U-link (the swinging linkage between the body and the door)
    "u_shaped_link_member": "upper_hinge",
    "base_wall": "upper_hinge",
    "base_wall_exterior_guide_surface": "upper_hinge",
    "upper_leg": "upper_hinge",
    "lower_leg": "lower_hinge",
    "leg_guide_edge_surface": "upper_hinge",
    "link_member_pintle_pin_holes": "upper_hinge",
    # Pintle axis components
    "pintle_pin": "pintle_axis",
    "hinge_axis": "pintle_axis",
    "pintle_pin_stop_means": "pintle_axis",
    # Stop / power mechanism
    "stop_means": "power_mechanism",
}


def make_lift_off_door_hinge_scaffold(
    *,
    name: str = "LiftOffDoorHingeScaffold",
    component_to_group: dict[str, str] | None = None,
    door_offset_x: float = -120.0,
    frame_offset_x: float = +60.0,
    upper_hinge_z: float = +90.0,
    lower_hinge_z: float = -90.0,
    door_size: tuple[float, float, float] = (180.0, 6.0, 240.0),
    frame_size: tuple[float, float, float] = (140.0, 6.0, 240.0),
    hinge_size: tuple[float, float, float] = (90.0, 60.0, 80.0),
    pintle_length_mm: float = 220.0,
    pintle_x: float = 0.0,
) -> SceneScaffold:
    """Build the canonical scaffold for a lift-off door hinge claim
    (US4807331A and similar). Geometry parameters describe the
    nominal placement of each scene group; defaults reproduce the
    ~door-on-vehicle proportions of figure 1.

    The default arrangement (looking down the +Y axis):

    ::

           Z up                          Z up
            ^                             ^
            |   upper hinge cluster ───┐  |
            |                          |  |
            |   pintle axis ─────────────┐
            |                          | ||
            |   lower hinge cluster ───┘  |
            |                             |
        door panel                  fixed_frame
          (-X side)                    (+X side)

    """
    door = SceneGroup(
        id="door_panel",
        label="Vehicle door panel",
        origin_mm=(door_offset_x, 0.0, 0.0),
        orientation_axis="Z",
        nominal_bbox_mm=door_size,
        notes="Large vertical sheet representing the vehicle door.",
    )
    frame = SceneGroup(
        id="fixed_frame",
        label="Body / frame side",
        origin_mm=(frame_offset_x, 0.0, 0.0),
        orientation_axis="Z",
        nominal_bbox_mm=frame_size,
        notes="Vertical panel representing the body to which the hinge mounts.",
    )
    pintle_axis = SceneGroup(
        id="pintle_axis",
        label="Vertical pintle axis",
        origin_mm=(pintle_x, 0.0, 0.0),
        orientation_axis="Z",
        nominal_bbox_mm=(8.0, 8.0, pintle_length_mm),
        notes="Shared pin axis the hinges rotate about.",
        attaches_to=["upper_hinge", "lower_hinge"],
    )
    upper_hinge = SceneGroup(
        id="upper_hinge",
        label="Upper hinge cluster",
        origin_mm=(pintle_x, 0.0, upper_hinge_z),
        orientation_axis="Z",
        nominal_bbox_mm=hinge_size,
        attaches_to=["door_panel", "fixed_frame", "pintle_axis"],
        notes="Upper hinge — main member + U-link + leaf flange + extensions.",
    )
    lower_hinge = SceneGroup(
        id="lower_hinge",
        label="Lower hinge cluster",
        origin_mm=(pintle_x, 0.0, lower_hinge_z),
        orientation_axis="Z",
        nominal_bbox_mm=hinge_size,
        attaches_to=["door_panel", "fixed_frame", "pintle_axis"],
        notes="Mirror of upper_hinge at the lower position.",
    )
    power_mechanism = SceneGroup(
        id="power_mechanism",
        label="Stop / spring mechanism",
        origin_mm=(pintle_x, 30.0, upper_hinge_z * 0.7),
        orientation_axis="Z",
        nominal_bbox_mm=(40.0, 30.0, 30.0),
        notes="Stop or spring at the rotation limit.",
        attaches_to=["upper_hinge"],
    )
    fasteners = SceneGroup(
        id="fasteners",
        label="Fasteners and small features",
        origin_mm=(0.0, 30.0, 0.0),
        orientation_axis="Z",
        nominal_bbox_mm=(30.0, 20.0, 30.0),
        notes="Bolts, washers, or other small fixture features.",
    )
    sc = SceneScaffold(
        name=name,
        groups=[door, frame, pintle_axis, upper_hinge, lower_hinge, power_mechanism, fasteners],
        component_to_group=dict(component_to_group or {}),
        notes=(
            "Patent-family scaffold for lift-off door hinges "
            "(US4807331A et al.). Heuristic; not auto-inferred."
        ),
    )
    # Populate component_ids on each group.
    by_group: dict[str, list[str]] = {g.id: [] for g in sc.groups}
    for cid, gid in sc.component_to_group.items():
        if gid in by_group:
            by_group[gid].append(cid)
        else:
            logger.debug("Scaffold has no group %r for component %s", gid, cid)
    for g in sc.groups:
        g.component_ids = sorted(by_group.get(g.id, []))
    return sc


def lift_off_door_hinge_scaffold_for_us4807331a(
    *, ir_component_ids: Iterable[str] | None = None,
) -> SceneScaffold:
    """Build the LiftOffDoorHingeScaffold pre-populated with the
    canonical US4807331A component → group mapping. ``ir_component_ids``
    optionally restricts the mapping to only ids present in the IR
    (the V11-13 enricher may have added extras)."""
    mapping = dict(US4807331A_COMPONENT_GROUPS)
    if ir_component_ids is not None:
        wanted = set(ir_component_ids)
        mapping = {
            cid: gid
            for cid, gid in mapping.items()
            if cid in wanted
        }
        # Add IR ids that aren't in the canonical mapping. Use a
        # default-bucket heuristic on the id text.
        for cid in wanted:
            if cid in mapping:
                continue
            mapping[cid] = _default_group_for_id(cid)
    return make_lift_off_door_hinge_scaffold(
        component_to_group=mapping,
    )


# ---------------------------------------------------------------------------
# Default heuristics (for IR ids that aren't in the canonical map)
# ---------------------------------------------------------------------------


def _default_group_for_id(component_id: str) -> str:
    """Heuristic: classify an IR id by substring."""
    cid = component_id.lower()
    if any(t in cid for t in ("pintle", "shaft", "axis", "pin")):
        return "pintle_axis"
    if any(t in cid for t in ("door", "leaf", "bight", "sidewall")):
        return "door_panel"
    if any(t in cid for t in ("vehicle", "body", "frame", "mount")):
        return "fixed_frame"
    if any(t in cid for t in ("upper", "main_member", "extension")):
        return "upper_hinge"
    if any(t in cid for t in ("lower",)):
        return "lower_hinge"
    if any(t in cid for t in ("stop", "spring", "detent")):
        return "power_mechanism"
    if any(t in cid for t in ("washer", "bolt", "screw", "nut", "fastener", "head")):
        return "fasteners"
    if any(t in cid for t in ("link", "leg", "knuckle", "barrel")):
        return "upper_hinge"
    return "fasteners"


def assign_scaffold_group(component_id: str, scaffold: SceneScaffold) -> str | None:
    """Look up the scaffold group for a component_id."""
    gid = scaffold.component_to_group.get(component_id)
    if gid is not None:
        return gid
    fallback = _default_group_for_id(component_id)
    if fallback in {g.id for g in scaffold.groups}:
        return fallback
    return None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_scaffold(scaffold: SceneScaffold, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scaffold.to_dict(), indent=2), encoding="utf-8")
    return path


def load_scaffold(path: Path) -> SceneScaffold:
    raw = json.loads(path.read_text("utf-8"))
    groups = [SceneGroup(**g) for g in raw.get("groups", [])]
    return SceneScaffold(
        name=raw.get("name", "scaffold"),
        groups=groups,
        component_to_group=dict(raw.get("component_to_group", {})),
        notes=raw.get("notes", ""),
    )


__all__ = [
    "SceneGroup",
    "SceneScaffold",
    "US4807331A_COMPONENT_GROUPS",
    "make_lift_off_door_hinge_scaffold",
    "lift_off_door_hinge_scaffold_for_us4807331a",
    "assign_scaffold_group",
    "save_scaffold",
    "load_scaffold",
]
