"""V12-C — demo-quality, patent-family-specific assembly scaffold.

The v1.1 pipeline derives geometry from per-component
shape_inference (each IR node becomes a primitive solid). For
US4807331A this produces a heap of bars: every "wall", "leg",
"flange", "extension" becomes its own thin box, and the result
doesn't read as a hinge.

This module ships a *hand-built* scaffold that constructs the
assembly directly using build123d primitives at the locked figure
positions. Component IDs from claim_map.json are then ATTACHED to
the synthesised meshes (rather than driving them), so the
claim ↔ CAD ↔ figure round-trip still holds.

Allowed by the v1.2 brief: "This is allowed to be template-based
and semi-manual for US4807331A."

Output:
  build_demo_assembly_us4807331a(layout, claim_map) → bd.Compound
  with these named children, in this order:

    door_panel              large curved door (sweep)
    fixed_frame             vehicle body frame panel
    pintle_pin              tall vertical shaft
    upper_hinge_bracket     C-bracket on the door
    upper_hinge_knuckle     coaxial knuckle on the frame
    lower_hinge_bracket     C-bracket on the door
    lower_hinge_knuckle     coaxial knuckle on the frame
    spring_link             u-shaped link member
    spring_coil             helical spring
    mounting_wall           plate behind the lower hinge
    fasteners_*             4 small bolts

claim_map component_ids are mapped onto these child meshes via a
US4807331A-specific table. The mapping is the GLB-naming contract:
each child label is the component_id, and the viewer/claim panel
key into model_v1.2.glb by that name.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import build123d as bd

from claim2cad.figure_projection import FigureProjectionLayout

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Claim component → demo mesh mapping (US4807331A_spring_loaded_hinge)
# ---------------------------------------------------------------------------

# Each demo mesh listed here is built once and assigned the claim
# component_id as its label. When multiple component_ids should map
# to the same mesh (e.g. door_panel + door_half_member), the second
# entry becomes an ALIAS — a phantom child that is a translated copy
# at zero offset, so it has its own GLB node but visually overlaps.
US4807331A_DEMO_MESHES = [
    "door_panel",
    "fixed_frame",
    "vehicle_body",
    "door_half_member",
    "body_half_sub_assembly",
    "hinge_body_half_assembly",
    "main_member",
    "upper_extension",
    "lower_extension",
    "first_sidewall",
    "second_sidewall",
    "bight_wall",
    "upper_leg",
    "leaf_flange",
    "leaf_flange_pintle_pin_hole",
    "main_member_pintle_pin_hole",
    "pintle_pin_hole",
    "pintle_pin",
    "hinge_axis",
    "u_shaped_link_member",
    "link_member_pintle_pin_holes",
    "link_member_pivot_pin",
    "mounting_wall",
    "lubricant_passage",
    "boss_assembly",
]


# How each component_id "expresses" the assembly. Many components
# in the claim ARE structural sub-shapes of larger meshes (e.g.
# `pintle_pin_hole` is a Boolean subtraction on hinge_body, not a
# separate solid). For demo we represent each as a SHADED REGION on
# the parent mesh (achieved by giving each its own small marker
# solid co-located with the parent).
@dataclass
class DemoMeshSpec:
    component_id: str
    role: str          # "primary" | "alias" | "feature"
    parent: str        # parent mesh name (the "primary" component_id)
    pose_offset_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    note: str = ""


US4807331A_MESH_SPECS: list[DemoMeshSpec] = [
    # Primary panels
    DemoMeshSpec("door_panel", "primary", "door_panel"),
    DemoMeshSpec("door_half_member", "alias", "door_panel"),
    DemoMeshSpec("fixed_frame", "primary", "fixed_frame"),
    DemoMeshSpec("vehicle_body", "alias", "fixed_frame"),
    # Hinge body (the abstract assembly node) maps to the union of
    # upper + lower brackets; for demo we attach it to the upper.
    DemoMeshSpec("hinge_body_half_assembly", "primary", "upper_hinge_assembly"),
    DemoMeshSpec("body_half_sub_assembly", "alias", "lower_hinge_assembly"),
    DemoMeshSpec("main_member", "primary", "upper_hinge_bracket"),
    DemoMeshSpec("upper_extension", "feature", "upper_hinge_bracket",
                  pose_offset_mm=(0.0, 0.0, 18.0)),
    DemoMeshSpec("lower_extension", "feature", "lower_hinge_bracket",
                  pose_offset_mm=(0.0, 0.0, -18.0)),
    DemoMeshSpec("first_sidewall", "feature", "upper_hinge_bracket",
                  pose_offset_mm=(0.0, -8.0, 0.0)),
    DemoMeshSpec("second_sidewall", "feature", "upper_hinge_bracket",
                  pose_offset_mm=(0.0, 8.0, 0.0)),
    DemoMeshSpec("bight_wall", "feature", "upper_hinge_bracket",
                  pose_offset_mm=(-12.0, 0.0, 0.0)),
    DemoMeshSpec("upper_leg", "feature", "upper_hinge_bracket",
                  pose_offset_mm=(0.0, 0.0, 22.0)),
    DemoMeshSpec("leaf_flange", "feature", "upper_hinge_knuckle",
                  pose_offset_mm=(0.0, 0.0, 0.0)),
    # Holes — represented as small markers at their parent surface
    DemoMeshSpec("leaf_flange_pintle_pin_hole", "feature", "upper_hinge_knuckle"),
    DemoMeshSpec("main_member_pintle_pin_hole", "feature", "upper_hinge_bracket"),
    DemoMeshSpec("pintle_pin_hole", "feature", "lower_hinge_bracket"),
    DemoMeshSpec("link_member_pintle_pin_holes", "feature", "spring_link"),
    # Pintle pin
    DemoMeshSpec("pintle_pin", "primary", "pintle_pin"),
    DemoMeshSpec("hinge_axis", "alias", "pintle_pin"),  # abstract centreline
    # Power mechanism
    DemoMeshSpec("u_shaped_link_member", "primary", "spring_link"),
    DemoMeshSpec("link_member_pivot_pin", "feature", "spring_link",
                  pose_offset_mm=(0.0, 0.0, -8.0)),
    DemoMeshSpec("mounting_wall", "primary", "mounting_wall"),
    DemoMeshSpec("lubricant_passage", "feature", "upper_hinge_knuckle",
                  pose_offset_mm=(2.0, 0.0, 0.0)),
    DemoMeshSpec("boss_assembly", "feature", "mounting_wall",
                  pose_offset_mm=(0.0, 0.0, 6.0)),
]


# ---------------------------------------------------------------------------
# Geometry builders (build123d primitives)
# ---------------------------------------------------------------------------


def _curved_door_panel(center: tuple[float, float, float]) -> bd.Part:
    """A door panel with a curved (angled) bottom edge, like the
    figure shows. Built by extruding a 2-D outline along Y."""
    cx, cy, cz = center
    # 2-D outline (X, Z) — top is rectangular, bottom angles inward.
    pts = [
        (-90.0, +130.0),
        (+90.0, +130.0),
        (+90.0, -110.0),
        (+30.0, -160.0),  # angled bottom edge (curved-ish)
        (-90.0, -160.0),
    ]
    with bd.BuildSketch(bd.Plane.XZ) as sk:
        bd.Polygon(*pts, align=None)
    panel = bd.extrude(sk.sketch, amount=10.0)  # Y thickness
    panel = panel.translate((cx, cy, cz))
    panel.label = "door_panel"
    return panel


def _frame_panel(center: tuple[float, float, float]) -> bd.Part:
    """The vehicle body frame — flat plate with an L-bend at the
    top to suggest the body lip in the figure."""
    cx, cy, cz = center
    main = bd.Box(80.0, 14.0, 280.0)
    lip = bd.Box(40.0, 14.0, 30.0).translate((20.0, 0.0, 130.0))
    panel = main + lip
    panel = panel.translate((cx, cy, cz))
    panel.label = "fixed_frame"
    return panel


def _pintle_pin(center: tuple[float, float, float], length: float = 220.0) -> bd.Part:
    """Long vertical shaft along Z."""
    cx, cy, cz = center
    pin = bd.Cylinder(radius=4.5, height=length)
    pin.label = "pintle_pin"
    return pin.translate((cx, cy, cz))


def _hinge_bracket(center: tuple[float, float, float], *, label: str) -> bd.Part:
    """A C-bracket: U-shaped channel that wraps the pintle pin and
    bolts to the door panel."""
    cx, cy, cz = center
    # Three plates forming a C around the pintle.
    leaf = bd.Box(40.0, 8.0, 60.0)               # the leaf attached to door
    knuckle_a = bd.Box(8.0, 22.0, 16.0).translate((22.0, 0.0, 18.0))
    knuckle_b = bd.Box(8.0, 22.0, 16.0).translate((22.0, 0.0, -18.0))
    bracket = leaf + knuckle_a + knuckle_b
    bracket.label = label
    return bracket.translate((cx, cy, cz))


def _hinge_knuckle(center: tuple[float, float, float], *, label: str) -> bd.Part:
    """The mating knuckle on the frame — a single block with a
    hole for the pintle (we model the visual presence; the hole is
    feature-coded via the holes' demo markers)."""
    cx, cy, cz = center
    block = bd.Box(20.0, 18.0, 28.0)
    pin_hole = bd.Cylinder(radius=4.7, height=30.0)
    knuckle = block - pin_hole
    knuckle.label = label
    return knuckle.translate((cx, cy, cz))


def _spring_link(center: tuple[float, float, float]) -> bd.Part:
    """U-shaped spring link member."""
    cx, cy, cz = center
    base = bd.Box(28.0, 5.0, 8.0)
    arm_a = bd.Box(5.0, 5.0, 24.0).translate((-11.0, 0.0, 16.0))
    arm_b = bd.Box(5.0, 5.0, 24.0).translate((+11.0, 0.0, 16.0))
    link = base + arm_a + arm_b
    link.label = "spring_link"
    return link.translate((cx, cy, cz))


def _spring_coil(center: tuple[float, float, float]) -> bd.Part:
    """Visual representation of the helical spring — a thin
    cylinder annulus. We do not model true helix to keep the
    triangle count low."""
    cx, cy, cz = center
    outer = bd.Cylinder(radius=8.0, height=22.0)
    inner = bd.Cylinder(radius=6.5, height=24.0)
    spring = outer - inner
    spring.label = "spring_coil"
    return spring.translate((cx, cy, cz))


def _mounting_wall(center: tuple[float, float, float]) -> bd.Part:
    cx, cy, cz = center
    wall = bd.Box(18.0, 6.0, 30.0)
    wall.label = "mounting_wall"
    return wall.translate((cx, cy, cz))


def _fastener(center: tuple[float, float, float], *, label: str) -> bd.Part:
    cx, cy, cz = center
    head = bd.Cylinder(radius=2.4, height=2.0).translate((0.0, 0.0, 5.0))
    shaft = bd.Cylinder(radius=1.2, height=10.0)
    bolt = head + shaft
    bolt.label = label
    return bolt.translate((cx, cy, cz))


def _feature_marker(
    center: tuple[float, float, float],
    *,
    label: str,
    radius_mm: float = 2.5,
) -> bd.Part:
    """Small marker solid co-located with a parent mesh, used to
    give claim component_ids that map to FEATURES (holes, walls,
    extensions) their own selectable GLB node without adding
    visible geometry. Rendered as a tiny sphere INSIDE the parent
    so it doesn't visually clutter."""
    cx, cy, cz = center
    s = bd.Sphere(radius=radius_mm)
    s.label = label
    return s.translate((cx, cy, cz))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class DemoBuildResult:
    compound: bd.Compound
    ordered_ids: list[str]
    diagnostics: list[dict[str, Any]]


def build_demo_assembly_us4807331a(
    *,
    layout: FigureProjectionLayout,
    claim_component_ids: list[str],
) -> DemoBuildResult:
    """Build the US4807331A demo assembly at the locked group
    anchors.

    Pulls group_anchors from the *locked* layout (V12-B) so the
    door panel sits on the LEFT, the fixed frame on the RIGHT, and
    the upper / lower hinge clusters are vertically separated.

    `claim_component_ids` is the list of component_ids from
    claim_map.json. Every entry in that list MUST appear as a
    labelled child of the returned compound (the GLB-naming
    contract). Any claim id without an entry in
    `US4807331A_MESH_SPECS` is given a tiny marker at the closest
    group centre so the contract still holds.
    """
    by_id = {a.id: a for a in layout.group_anchors}

    def _grp(gid: str, default: tuple[float, float, float]) -> tuple[float, float, float]:
        a = by_id.get(gid)
        return a.cad_anchor_mm if a is not None else default

    door_centre = _grp("door_panel", (-70.0, -45.0, 0.0))
    frame_centre = _grp("fixed_frame", (+70.0, +35.0, 0.0))
    upper_centre = _grp("upper_hinge", (0.0, 0.0, 90.0))
    lower_centre = _grp("lower_hinge", (0.0, 0.0, -24.0))
    pintle_centre = _grp("pintle_axis", (0.0, 0.0, 30.0))
    power_centre = _grp("power_mechanism", (-15.0, 18.0, -30.0))

    # ------------------------------------------------------------------
    # 1. Build the demo meshes once.
    # ------------------------------------------------------------------
    meshes: dict[str, bd.Part] = {}

    meshes["door_panel"] = _curved_door_panel(door_centre)
    meshes["fixed_frame"] = _frame_panel(frame_centre)

    # Pintle pin spans upper and lower hinges (length from upper Z
    # to lower Z + margin).
    pin_z_top = upper_centre[2] + 30.0
    pin_z_bot = lower_centre[2] - 30.0
    pin_length = max(180.0, pin_z_top - pin_z_bot)
    pin_centre = (pintle_centre[0], pintle_centre[1],
                  (pin_z_top + pin_z_bot) / 2.0)
    meshes["pintle_pin"] = _pintle_pin(pin_centre, length=pin_length)

    # Upper hinge: bracket on the door (X negative-ish, near pintle),
    # knuckle on the frame.
    upper_bracket_centre = (
        max(door_centre[0] + 100.0, upper_centre[0] - 16.0),
        upper_centre[1] - 10.0,
        upper_centre[2],
    )
    meshes["upper_hinge_bracket"] = _hinge_bracket(upper_bracket_centre,
                                                    label="upper_hinge_bracket")
    upper_knuckle_centre = (
        upper_centre[0] + 8.0,
        upper_centre[1] + 8.0,
        upper_centre[2],
    )
    meshes["upper_hinge_knuckle"] = _hinge_knuckle(upper_knuckle_centre,
                                                    label="upper_hinge_knuckle")
    meshes["upper_hinge_assembly"] = _feature_marker(upper_centre,
                                                      label="upper_hinge_assembly",
                                                      radius_mm=4.0)

    # Lower hinge.
    lower_bracket_centre = (
        max(door_centre[0] + 100.0, lower_centre[0] - 16.0),
        lower_centre[1] - 10.0,
        lower_centre[2],
    )
    meshes["lower_hinge_bracket"] = _hinge_bracket(lower_bracket_centre,
                                                    label="lower_hinge_bracket")
    lower_knuckle_centre = (
        lower_centre[0] + 8.0,
        lower_centre[1] + 8.0,
        lower_centre[2],
    )
    meshes["lower_hinge_knuckle"] = _hinge_knuckle(lower_knuckle_centre,
                                                    label="lower_hinge_knuckle")
    meshes["lower_hinge_assembly"] = _feature_marker(lower_centre,
                                                      label="lower_hinge_assembly",
                                                      radius_mm=4.0)

    # Spring link + coil.
    meshes["spring_link"] = _spring_link(power_centre)
    meshes["spring_coil"] = _spring_coil(
        (power_centre[0] + 14.0, power_centre[1], power_centre[2] - 4.0)
    )
    meshes["mounting_wall"] = _mounting_wall(
        (power_centre[0] - 12.0, power_centre[1] + 6.0, power_centre[2])
    )

    # Fasteners along the frame edge.
    for i, dz in enumerate((+90.0, +30.0, -30.0, -90.0)):
        fc = (frame_centre[0] - 28.0, frame_centre[1] - 5.0, frame_centre[2] + dz)
        meshes[f"fastener_{i}"] = _fastener(fc, label=f"fastener_{i}")

    # ------------------------------------------------------------------
    # 2. Map every claim component_id onto the demo meshes.
    # ------------------------------------------------------------------
    spec_by_cid = {s.component_id: s for s in US4807331A_MESH_SPECS}
    children: list[bd.Part | bd.Compound] = []
    ordered: list[str] = []
    diagnostics: list[dict[str, Any]] = []

    used_meshes: set[str] = set()
    for cid in claim_component_ids:
        spec = spec_by_cid.get(cid)
        if spec is None:
            # Unmapped — drop a marker at the upper-hinge centre so
            # the GLB still has a node with this name.
            m = _feature_marker(upper_centre, label=cid, radius_mm=1.5)
            children.append(m)
            ordered.append(cid)
            diagnostics.append({"component_id": cid, "role": "unmapped"})
            continue

        parent_mesh = meshes.get(spec.parent)
        if parent_mesh is None:
            logger.warning("v12-c: parent mesh %s missing for %s", spec.parent, cid)
            continue

        if spec.role == "primary":
            mesh = parent_mesh
            mesh.label = cid
            children.append(mesh)
            ordered.append(cid)
            used_meshes.add(spec.parent)
        elif spec.role == "alias":
            # Place the alias marker at the parent's bbox CORNER + a
            # small outward offset so the marker's bbox does NOT
            # overlap the parent's bbox. Without this offset, STEP
            # export silently drops one of the two children when the
            # bboxes coincide (build123d roundtrip bug observed
            # 2026-04-29 on US4807331A).
            try:
                bb = parent_mesh.bounding_box()
                offset_x = (bb.max.X - bb.min.X) / 2 + 5.0
                offset_z = (bb.max.Z - bb.min.Z) / 2 + 5.0
                marker_centre = (
                    bb.max.X + 5.0,  # outside parent's +X face
                    (bb.min.Y + bb.max.Y) / 2,
                    bb.max.Z + 5.0,  # outside parent's +Z face
                )
            except Exception:  # noqa: BLE001
                marker_centre = (0.0, 0.0, 0.0)
            m = _feature_marker(marker_centre, label=cid, radius_mm=1.0)
            children.append(m)
            ordered.append(cid)
        else:  # feature
            try:
                bb = parent_mesh.bounding_box()
                centre = ((bb.min.X + bb.max.X) / 2,
                          (bb.min.Y + bb.max.Y) / 2,
                          (bb.min.Z + bb.max.Z) / 2)
                # Push marker just past the parent's +X face so it
                # has its own non-overlapping bbox (same STEP-export
                # workaround as aliases).
                centre = (bb.max.X + 4.0, centre[1], centre[2])
            except Exception:  # noqa: BLE001
                centre = (0.0, 0.0, 0.0)
            ox, oy, oz = spec.pose_offset_mm
            centre = (centre[0] + ox, centre[1] + oy, centre[2] + oz)
            m = _feature_marker(centre, label=cid, radius_mm=1.5)
            children.append(m)
            ordered.append(cid)

        diagnostics.append({
            "component_id": cid, "role": spec.role,
            "parent": spec.parent, "offset_mm": spec.pose_offset_mm,
        })

    # Always add unused primary meshes so the demo has the full
    # hinge geometry even if claim_map doesn't reference them.
    # door_panel + fixed_frame are mandatory — without them the
    # render is just hinge clusters floating in space.
    for mesh_name in (
        "door_panel", "fixed_frame", "pintle_pin",
        "upper_hinge_bracket", "upper_hinge_knuckle",
        "lower_hinge_bracket", "lower_hinge_knuckle",
        "spring_link", "spring_coil", "mounting_wall",
    ):
        if mesh_name in used_meshes:
            continue
        mesh = meshes.get(mesh_name)
        if mesh is None:
            continue
        mesh.label = mesh_name
        children.append(mesh)
        ordered.append(mesh_name)
    # Fasteners always emitted.
    for i in range(4):
        name = f"fastener_{i}"
        if name in used_meshes:
            continue
        mesh = meshes.get(name)
        if mesh is not None:
            children.append(mesh)
            ordered.append(name)

    if not children:
        raise RuntimeError("v12-c demo scaffold produced 0 children")

    compound = bd.Compound(label="assembly", children=children)
    return DemoBuildResult(compound=compound, ordered_ids=ordered, diagnostics=diagnostics)


__all__ = [
    "DemoBuildResult",
    "DemoMeshSpec",
    "US4807331A_MESH_SPECS",
    "build_demo_assembly_us4807331a",
]
