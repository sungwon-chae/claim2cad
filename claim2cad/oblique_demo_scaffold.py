"""V12-J/K — oblique opened-door scaffold for US4807331A.

Replaces the flat front-facing v12-c scaffold with one that
captures the patent figure's *opened-door* composition:

  * door_panel rotated ~35° about the vertical pintle axis (open),
  * fixed_frame upright on its own plane,
  * each hinge has TWO plates — a `*_leaf` mounted on the door's
    inside face (inherits door rotation) and a `*_bracket`
    mounted on the frame (stays put),
  * pintle pin runs along the shared axis,
  * spring + link mechanism mounted on the frame near the lower
    hinge.

The geometry is constructed in two passes:

  pass 1 — build every mesh at its "closed" position (all panels
           parallel, axis-aligned).
  pass 2 — apply parent transforms by component class:
              door_side  → rotate +door_angle_deg about hinge Z
              frame_side → identity (or small frame_angle_deg)
              shared_axis → identity (pintle stays put)
              bridging → frame_side (spring follows the frame)

Output mapping retains the V12-C `US4807331A_MESH_SPECS` table so
every claim component_id is a labelled child of the resulting
GLB. Only the *positions* of those children change.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import build123d as bd

from claim2cad.demo_scaffold import (
    DemoMeshSpec,
    US4807331A_MESH_SPECS,
    _curved_door_panel,
    _frame_panel,
    _pintle_pin,
    _hinge_knuckle,
    _spring_link,
    _spring_coil,
    _mounting_wall,
    _fastener,
    _feature_marker,
)
from claim2cad.figure_projection import FigureProjectionLayout

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Component classification (V12-K)
# ---------------------------------------------------------------------------

# Each demo mesh name belongs to exactly one of these planes /
# transforms. The classification is consumed by ``_apply_class_transform``
# at the end of the build to swing door-side parts open with the
# door panel while leaving frame-side parts upright.
DOOR_SIDE_MESHES = {
    "door_panel",
    "upper_door_leaf",
    "lower_door_leaf",
    "upper_door_leaf_face",
    "lower_door_leaf_face",
}
FRAME_SIDE_MESHES = {
    "fixed_frame",
    "upper_frame_bracket",
    "lower_frame_bracket",
    "spring_link",
    "spring_coil",
    "mounting_wall",
    "fastener_0", "fastener_1", "fastener_2", "fastener_3",
}
SHARED_AXIS_MESHES = {
    "pintle_pin",
    "upper_hinge_knuckle",
    "lower_hinge_knuckle",
}


# ---------------------------------------------------------------------------
# Door-side & frame-side hinge plate builders (V12-K)
# ---------------------------------------------------------------------------


def _door_side_leaf(centre: tuple[float, float, float], *, label: str) -> bd.Part:
    """A flat plate that bolts to the door's inside face.

    Sized to match the leaf in the figure — narrow flange + a
    knuckle-mounting tab on the hinge edge. Modelled in the
    "closed" position (door parallel to frame); the rotation pass
    swings it open with the door.
    """
    cx, cy, cz = centre
    # Flange plate against the door (Y-thin).
    flange = bd.Box(36.0, 4.0, 50.0)
    # Knuckle-mounting tab that protrudes toward the pintle (+X).
    tab = bd.Box(14.0, 8.0, 18.0).translate((22.0, +2.0, 0.0))
    leaf = flange + tab
    leaf.label = label
    return leaf.translate((cx, cy, cz))


def _frame_side_bracket(centre: tuple[float, float, float], *, label: str) -> bd.Part:
    """A C-bracket that bolts to the frame and wraps the pintle.

    Sized larger than the door-side leaf because the figure shows
    the frame side as the dominant hinge plate (callouts 24, 34,
    38, 30). It has a flat back face against the frame plus an
    L-bend reaching the pintle.
    """
    cx, cy, cz = centre
    back = bd.Box(48.0, 4.0, 60.0)
    # L-bend reaching toward the pintle (-X direction since the
    # frame is on the +X side and the pintle is at smaller X).
    arm_top = bd.Box(40.0, 8.0, 14.0).translate((-22.0, +2.0, +18.0))
    arm_bot = bd.Box(40.0, 8.0, 14.0).translate((-22.0, +2.0, -18.0))
    bracket = back + arm_top + arm_bot
    bracket.label = label
    return bracket.translate((cx, cy, cz))


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------


def _rotate_about_vertical_axis(
    part: bd.Part,
    *,
    pivot_xy: tuple[float, float],
    angle_deg: float,
) -> bd.Part:
    """Rotate ``part`` about the vertical line passing through
    ``pivot_xy`` (X, Y) — Z up. Positive angle is CCW when looking
    down the +Z axis (standard right-hand rule).
    """
    if abs(angle_deg) < 1e-6:
        return part
    px, py = pivot_xy
    moved = part.translate((-px, -py, 0.0))
    rotated = moved.rotate(bd.Axis.Z, angle_deg)
    return rotated.translate((px, py, 0.0))


def _classify(mesh_name: str) -> str:
    if mesh_name in DOOR_SIDE_MESHES:
        return "door_side"
    if mesh_name in FRAME_SIDE_MESHES:
        return "frame_side"
    if mesh_name in SHARED_AXIS_MESHES:
        return "shared_axis"
    return "feature"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class ObliqueBuildResult:
    compound: bd.Compound
    ordered_ids: list[str]
    diagnostics: list[dict[str, Any]]
    door_angle_deg: float
    hinge_pivot_xy: tuple[float, float]


def build_oblique_demo_us4807331a(
    *,
    layout: FigureProjectionLayout,
    claim_component_ids: list[str],
    door_angle_deg: float = 35.0,
    frame_angle_deg: float = 0.0,
) -> ObliqueBuildResult:
    """Build the V12-J oblique opened-door demo for US4807331A.

    The hinge axis is the pintle pin's X/Y position. door_panel
    rotates +door_angle_deg around that axis (CCW from above);
    door-side hinge plates inherit the rotation. Frame stays put;
    frame-side plates stay glued to it.
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

    hinge_pivot_xy = (pintle_centre[0], pintle_centre[1])

    # ------------------------------------------------------------------
    # pass 1 — build closed-position meshes
    # ------------------------------------------------------------------
    meshes: dict[str, bd.Part] = {}

    meshes["door_panel"] = _curved_door_panel(door_centre)
    meshes["fixed_frame"] = _frame_panel(frame_centre)

    pin_z_top = upper_centre[2] + 30.0
    pin_z_bot = lower_centre[2] - 30.0
    pin_length = max(180.0, pin_z_top - pin_z_bot)
    pin_centre = (pintle_centre[0], pintle_centre[1],
                  (pin_z_top + pin_z_bot) / 2.0)
    meshes["pintle_pin"] = _pintle_pin(pin_centre, length=pin_length)

    # Upper hinge — door-side leaf + frame-side bracket.
    # Door-side leaf sits on the door's inside face at the upper
    # hinge Z, slightly inset from the hinge edge.
    upper_leaf_centre = (
        door_centre[0] + 86.0,         # near the door's right edge
        door_centre[1] + 6.0,           # on the door's inside (Y > door_centre[1])
        upper_centre[2],
    )
    meshes["upper_door_leaf"] = _door_side_leaf(upper_leaf_centre,
                                                  label="upper_door_leaf")
    upper_bracket_centre = (
        frame_centre[0] - 38.0,         # on the frame's left inside face
        frame_centre[1] - 6.0,
        upper_centre[2],
    )
    meshes["upper_frame_bracket"] = _frame_side_bracket(upper_bracket_centre,
                                                          label="upper_frame_bracket")
    upper_knuckle_centre = (pintle_centre[0], pintle_centre[1] + 4.0,
                             upper_centre[2])
    meshes["upper_hinge_knuckle"] = _hinge_knuckle(upper_knuckle_centre,
                                                     label="upper_hinge_knuckle")

    # Lower hinge — same pattern.
    lower_leaf_centre = (
        door_centre[0] + 86.0,
        door_centre[1] + 6.0,
        lower_centre[2],
    )
    meshes["lower_door_leaf"] = _door_side_leaf(lower_leaf_centre,
                                                  label="lower_door_leaf")
    lower_bracket_centre = (
        frame_centre[0] - 38.0,
        frame_centre[1] - 6.0,
        lower_centre[2],
    )
    meshes["lower_frame_bracket"] = _frame_side_bracket(lower_bracket_centre,
                                                          label="lower_frame_bracket")
    lower_knuckle_centre = (pintle_centre[0], pintle_centre[1] + 4.0,
                             lower_centre[2])
    meshes["lower_hinge_knuckle"] = _hinge_knuckle(lower_knuckle_centre,
                                                     label="lower_hinge_knuckle")

    # Spring + link on the frame side near the lower hinge.
    spring_link_centre = (
        frame_centre[0] - 50.0,
        frame_centre[1] + 4.0,
        lower_centre[2] - 10.0,
    )
    meshes["spring_link"] = _spring_link(spring_link_centre)
    spring_coil_centre = (
        frame_centre[0] - 38.0,
        frame_centre[1] + 4.0,
        lower_centre[2] - 18.0,
    )
    meshes["spring_coil"] = _spring_coil(spring_coil_centre)
    mounting_wall_centre = (
        frame_centre[0] - 60.0,
        frame_centre[1] + 6.0,
        lower_centre[2],
    )
    meshes["mounting_wall"] = _mounting_wall(mounting_wall_centre)

    # Fasteners along the frame edge.
    for i, dz in enumerate((+90.0, +30.0, -30.0, -90.0)):
        fc = (frame_centre[0] - 28.0, frame_centre[1] - 5.0,
              frame_centre[2] + dz)
        meshes[f"fastener_{i}"] = _fastener(fc, label=f"fastener_{i}")

    # ------------------------------------------------------------------
    # pass 2 — apply parent-class transforms
    # ------------------------------------------------------------------
    transformed: dict[str, bd.Part] = {}
    for name, mesh in meshes.items():
        cls = _classify(name)
        if cls == "door_side":
            mesh = _rotate_about_vertical_axis(
                mesh, pivot_xy=hinge_pivot_xy, angle_deg=door_angle_deg,
            )
        elif cls == "frame_side":
            mesh = _rotate_about_vertical_axis(
                mesh, pivot_xy=hinge_pivot_xy, angle_deg=frame_angle_deg,
            )
        # shared_axis + feature meshes stay put.
        mesh.label = name
        transformed[name] = mesh

    # ------------------------------------------------------------------
    # claim mapping (mirrors V12-C)
    # ------------------------------------------------------------------
    spec_by_cid = {s.component_id: s for s in US4807331A_MESH_SPECS}
    # V12-K — extend the spec table with the new door_side / frame_side
    # plate names so claim ids fall through to them when appropriate.
    plate_aliases = {
        "leaf_flange": "upper_door_leaf",
        "leaf_flange_pintle_pin_hole": "upper_door_leaf",
        "main_member": "upper_frame_bracket",
        "main_member_pintle_pin_hole": "upper_frame_bracket",
        "upper_extension": "upper_frame_bracket",
        "lower_extension": "lower_frame_bracket",
        "first_sidewall": "upper_frame_bracket",
        "second_sidewall": "upper_frame_bracket",
        "bight_wall": "upper_frame_bracket",
        "upper_leg": "upper_door_leaf",
        "hinge_body_half_assembly": "upper_frame_bracket",
        "body_half_sub_assembly": "lower_frame_bracket",
    }

    children: list[bd.Part] = []
    ordered: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    used_meshes: set[str] = set()

    for cid in claim_component_ids:
        spec = spec_by_cid.get(cid)
        # First, try the plate alias remap.
        parent_override = plate_aliases.get(cid)
        target_mesh_name = (
            parent_override or (spec.parent if spec else None)
        )
        if target_mesh_name and target_mesh_name in transformed and (
            spec is None or spec.role == "primary" or parent_override
        ):
            # Take ownership of the mesh (or a clone if already used).
            if target_mesh_name not in used_meshes:
                mesh = transformed[target_mesh_name]
                mesh.label = cid
                children.append(mesh)
                ordered.append(cid)
                used_meshes.add(target_mesh_name)
                diagnostics.append({"component_id": cid,
                                     "role": "primary_remap",
                                     "parent": target_mesh_name,
                                     "class": _classify(target_mesh_name)})
                continue
            # Mesh already owned — emit a marker just outside it.
            parent_mesh = transformed[target_mesh_name]
            try:
                bb = parent_mesh.bounding_box()
                marker_centre = (bb.max.X + 5.0,
                                  (bb.min.Y + bb.max.Y) / 2,
                                  bb.max.Z + 5.0)
            except Exception:  # noqa: BLE001
                marker_centre = (0.0, 0.0, 0.0)
            m = _feature_marker(marker_centre, label=cid, radius_mm=1.0)
            children.append(m)
            ordered.append(cid)
            diagnostics.append({"component_id": cid, "role": "feature_marker",
                                 "parent": target_mesh_name,
                                 "class": _classify(target_mesh_name)})
            continue
        # Fallback: feature marker at upper-hinge centre.
        m = _feature_marker(upper_centre, label=cid, radius_mm=1.5)
        children.append(m)
        ordered.append(cid)
        diagnostics.append({"component_id": cid, "role": "unmapped"})

    # Always emit the structural meshes that no claim_id mapped to,
    # so the demo has a complete hinge.
    for mesh_name in (
        "door_panel", "fixed_frame", "pintle_pin",
        "upper_door_leaf", "upper_frame_bracket", "upper_hinge_knuckle",
        "lower_door_leaf", "lower_frame_bracket", "lower_hinge_knuckle",
        "spring_link", "spring_coil", "mounting_wall",
    ):
        if mesh_name in used_meshes:
            continue
        mesh = transformed.get(mesh_name)
        if mesh is None:
            continue
        mesh.label = mesh_name
        children.append(mesh)
        ordered.append(mesh_name)
    for i in range(4):
        name = f"fastener_{i}"
        if name in used_meshes:
            continue
        mesh = transformed.get(name)
        if mesh is not None:
            children.append(mesh)
            ordered.append(name)

    if not children:
        raise RuntimeError("v12-j oblique scaffold produced 0 children")

    compound = bd.Compound(label="assembly", children=children)
    return ObliqueBuildResult(
        compound=compound,
        ordered_ids=ordered,
        diagnostics=diagnostics,
        door_angle_deg=door_angle_deg,
        hinge_pivot_xy=hinge_pivot_xy,
    )


__all__ = [
    "ObliqueBuildResult",
    "build_oblique_demo_us4807331a",
    "DOOR_SIDE_MESHES",
    "FRAME_SIDE_MESHES",
    "SHARED_AXIS_MESHES",
]
