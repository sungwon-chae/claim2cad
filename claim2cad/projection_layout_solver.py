"""Projection-layout solver — build assembly using figure-grounded anchors.

Given:
  * a ShapeInferenceSet from V11-14 (per-component shape_family + dims)
  * a SceneScaffold from V11-20 (the named-group structure)
  * a FigureProjectionLayout from V11-23b (per-component (u, v) anchors
    in the figure, projected into CAD coords)

…this solver places each component at its figure-projected anchor (with
small per-component depth offsets) instead of at its scene-group origin.
The chosen camera's projection of the resulting CAD then literally
tracks the patent figure: components that are far apart in the figure
end up far apart in the rendered view.

Compared to ``assembly_solver.build_assembly_scaffold_first``:

  * scaffold groups still exist, but their origins are *re-anchored*
    from the figure: the door panel's X is the median X of door-group
    components (mapped from figure u), not a hard-coded -120 mm.
  * each component's CAD pose is its figure_anchor.cad_anchor_mm plus
    a small depth offset (per shape_family) — no more pile-up at the
    group origin.
  * pin/shaft components keep their scaffold-aligned vertical Z extent
    so the pintle pin still spans the upper and lower hinge clusters.
  * synthetic context panels (door_panel, fixed_frame) are sized from
    the figure-projected bbox of their member components, not a fixed
    template.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import build123d as bd

from claim2cad.assembly_solver import (
    SolverDiagnostics,
    _SHAPE_BUILDERS,
    _build_bracket_c_from_shape,
    _build_other,
    _orient_for_axis,
)
from claim2cad.figure_projection import (
    FigureAnchor,
    FigureProjection,
    FigureProjectionLayout,
)
from claim2cad.scene_scaffold import SceneScaffold
from claim2cad.shape_inference import ShapeInferenceSet

logger = logging.getLogger(__name__)


def _depth_for_family(shape_family: str) -> float:
    """How far in front/behind the projection plane the part sits.

    The projection_plane is two of (X, Y, Z); the third is the
    'depth' axis. Different shape_families occupy different depth
    bands so they don't all collapse into the same depth."""
    table = {
        "plate": 5.0,
        "tab": 5.0,
        "flange": 8.0,
        "bracket": 12.0,
        "link": 10.0,
        "housing": 14.0,
        "hinge_leaf": 10.0,
        "knuckle": 16.0,
        "pin": 0.0,
        "shaft": 0.0,
        "washer": 4.0,
        "boss": 8.0,
        "spring": 6.0,
        "fastener": 4.0,
        "slot": 2.0,
        "hole": 0.0,
        "other": 0.0,
    }
    return table.get(shape_family, 0.0)


def _orient_part(solid: bd.Part, s) -> bd.Part:  # type: ignore[no-untyped-def]
    if s.shape_family in {"pin", "shaft"}:
        solid = _orient_for_axis(solid, "Z")
    rx, ry, rz = s.rotation_deg
    if abs(rx) > 1e-6:
        solid = solid.rotate(bd.Axis.X, rx)
    if abs(ry) > 1e-6:
        solid = solid.rotate(bd.Axis.Y, ry)
    if abs(rz) > 1e-6:
        solid = solid.rotate(bd.Axis.Z, rz)
    return solid


def _stretch_pin_to_axis(solid: bd.Part, s, axis_extent_mm: float) -> bd.Part:  # type: ignore[no-untyped-def]
    """Stretch a pin/shaft along Z to span ``axis_extent_mm``."""
    bb = solid.bounding_box()
    cur_z = bb.max.Z - bb.min.Z
    if axis_extent_mm > cur_z * 1.2 and cur_z > 0:
        scale = axis_extent_mm / cur_z
        try:
            return solid.scale((1.0, 1.0, scale))  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            from claim2cad.components.joints.hinge_primitives import HingeShaft
            new = HingeShaft(
                diameter=max(s.diameter_mm or s.thickness_mm or 4.0, 3.0),
                length=axis_extent_mm,
                head_style="round",
                chamfer_mm=0.5,
            ).build()
            return _orient_for_axis(new, "Z")
    return solid


def _scaffold_panel_solid(
    bbox_mm: tuple[float, float, float],
    *,
    label: str,
) -> bd.Part:
    sx, sy, sz = bbox_mm
    p = bd.Box(max(sx, 4.0), max(sy, 2.0), max(sz, 4.0))
    p.label = label
    return p


def _bbox_around_anchors(
    anchors: list[FigureAnchor],
    *,
    margin_mm: float = 30.0,
) -> tuple[float, float, float, float, float, float]:
    if not anchors:
        return (-50.0, -3.0, -50.0, 50.0, 3.0, 50.0)
    xs = [a.cad_anchor_mm[0] for a in anchors]
    ys = [a.cad_anchor_mm[1] for a in anchors]
    zs = [a.cad_anchor_mm[2] for a in anchors]
    return (
        min(xs) - margin_mm,
        min(ys) - margin_mm,
        min(zs) - margin_mm,
        max(xs) + margin_mm,
        max(ys) + margin_mm,
        max(zs) + margin_mm,
    )


def build_assembly_figure_anchored(
    *,
    inference: ShapeInferenceSet,
    scaffold: SceneScaffold,
    layout: FigureProjectionLayout,
    add_panel_meshes: bool = True,
) -> tuple[bd.Compound, list[str], list[SolverDiagnostics]]:
    """Build the assembly using figure-projected anchors as primary
    pose for every component."""
    shapes_by_id = {s.component_id: s for s in inference.shapes}
    component_anchor: dict[str, FigureAnchor] = {
        a.id: a for a in layout.component_anchors
    }
    group_anchor: dict[str, FigureAnchor] = {
        a.id: a for a in layout.group_anchors
    }
    component_to_group = scaffold.component_to_group

    # Pintle axis vertical extent — we want pins to span the figure
    # vertical extent of the assembly so they reach the upper and
    # lower hinge clusters.
    proj = layout.projection
    pintle_axis = group_anchor.get("pintle_axis")
    if pintle_axis is not None:
        # Use the V-spread of upper_hinge / lower_hinge groups as the
        # pin's vertical extent.
        upper = group_anchor.get("upper_hinge")
        lower = group_anchor.get("lower_hinge")
        if upper is not None and lower is not None:
            pin_v_extent = abs(
                upper.cad_anchor_mm[
                    {"X": 0, "Y": 1, "Z": 2}[proj.projection_plane[1]]
                ]
                - lower.cad_anchor_mm[
                    {"X": 0, "Y": 1, "Z": 2}[proj.projection_plane[1]]
                ]
            ) + 80.0
        else:
            pin_v_extent = max(
                proj.height_mm() * 0.6, 200.0
            )
    else:
        pin_v_extent = 200.0

    children: list[bd.Part | bd.Compound] = []
    ordered: list[str] = []
    diagnostics: list[SolverDiagnostics] = []

    # Step 1: synthesise context panels for door_panel + fixed_frame.
    # Size them from the figure-projected bbox of their members.
    if add_panel_meshes:
        for gid in ("door_panel", "fixed_frame"):
            ga = group_anchor.get(gid)
            if ga is None:
                continue
            members = [
                component_anchor[cid]
                for cid in scaffold.by_id().get(gid, scaffold.groups[0]).component_ids
                if cid in component_anchor
            ]
            if not members:
                continue
            bb = _bbox_around_anchors(members, margin_mm=40.0)
            sx = max(bb[3] - bb[0], 60.0)
            sz = max(bb[5] - bb[2], 60.0)
            sy = 6.0
            # Skip synthesis if any single member is already
            # panel-sized.
            already_panel = False
            for cid in scaffold.by_id().get(gid, scaffold.groups[0]).component_ids:
                sh = shapes_by_id.get(cid)
                if sh is None:
                    continue
                tagged = sorted(
                    [sh.width_mm, sh.height_mm, max(sh.depth_mm, sh.thickness_mm)]
                )
                if tagged[1] >= 100.0 and tagged[2] >= 100.0 and tagged[0] <= 15.0:
                    already_panel = True
                    break
            if already_panel:
                continue
            panel = _scaffold_panel_solid((sx, sy, sz), label=f"_scaffold_{gid}")
            # Centre panel at the median anchor of its members.
            cx = (bb[0] + bb[3]) / 2.0
            cz = (bb[2] + bb[5]) / 2.0
            panel = panel.translate((cx, ga.cad_anchor_mm[1], cz))
            panel.label = f"_scaffold_{gid}"
            children.append(panel)
            ordered.append(panel.label)
            diagnostics.append(
                SolverDiagnostics(
                    component_id=panel.label,
                    shape_family="panel",
                    bbox_mm=(sx, sy, sz),
                    pose_applied_mm=(cx, ga.cad_anchor_mm[1], cz),
                    constraints_applied=[f"figure_anchor:{gid}"],
                    fell_back_to_box=False,
                    notes=f"figure-anchored scaffold panel for {gid}",
                )
            )

    # Step 2: per-component build at figure-anchored pose.
    for cid, s in shapes_by_id.items():
        builder = _SHAPE_BUILDERS.get(s.shape_family, _build_other)
        if s.shape_family in {"bracket", "link", "housing"}:
            shares_pin = any(
                c["kind"] in ("passes_through", "coaxial_with")
                for c in s.constraints
            )
            if shares_pin:
                builder = _build_bracket_c_from_shape

        try:
            solid = builder(s)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Shape build failed for %s (%s): %s", cid, s.shape_family, exc)
            solid = _build_other(s)
        if solid is None:
            continue
        try:
            bb = solid.bounding_box()
            sz_test = (bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z)
            if min(sz_test) < 0.5:
                solid = _build_other(s)
        except Exception:  # noqa: BLE001
            solid = _build_other(s)

        solid = _orient_part(solid, s)
        if s.shape_family in {"pin", "shaft"}:
            solid = _stretch_pin_to_axis(solid, s, pin_v_extent)

        # Pose: figure-anchored if available, else group-anchored,
        # else origin.
        anchor = component_anchor.get(cid)
        gid = component_to_group.get(cid)
        if anchor is not None:
            pose = list(anchor.cad_anchor_mm)
            # Add per-family depth offset on the depth axis.
            depth_axis_idx = {"X": 0, "Y": 1, "Z": 2}[proj.depth_axis]
            pose[depth_axis_idx] += _depth_for_family(s.shape_family)
            pose_applied = tuple(pose)
            anchor_origin = "figure_anchor"
        elif gid is not None and gid in group_anchor:
            pose_applied = group_anchor[gid].cad_anchor_mm
            anchor_origin = f"group_anchor:{gid}"
        else:
            pose_applied = tuple(s.pose_xyz_mm)
            anchor_origin = "vlm_pose"

        # Pin/shaft snaps to pintle_axis anchor exactly.
        if s.shape_family in {"pin", "shaft"} and pintle_axis is not None:
            pose_applied = pintle_axis.cad_anchor_mm
            anchor_origin = "pintle_axis"

        solid = solid.translate(pose_applied)
        solid.label = cid
        children.append(solid)
        ordered.append(cid)

        bb = solid.bounding_box()
        applied_bbox = (
            bb.max.X - bb.min.X,
            bb.max.Y - bb.min.Y,
            bb.max.Z - bb.min.Z,
        )
        constraints_applied = [f"{c['kind']}:{c['target']}" for c in s.constraints]
        constraints_applied.append(f"anchor:{anchor_origin}")
        diagnostics.append(
            SolverDiagnostics(
                component_id=cid,
                shape_family=s.shape_family,
                bbox_mm=applied_bbox,
                pose_applied_mm=pose_applied,
                constraints_applied=constraints_applied,
                fell_back_to_box=(s.shape_family == "other"),
                notes=s.notes[:120],
            )
        )

    if not children:
        raise RuntimeError("Figure-anchored solver produced 0 components")
    return bd.Compound(label="assembly", children=children), ordered, diagnostics


__all__ = ["build_assembly_figure_anchored"]
