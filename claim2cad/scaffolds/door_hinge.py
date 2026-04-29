"""V13-B — DoorHingeScaffold.

Generalises the V12 oblique opened-door scaffold into a
template that any door/hinge example can use. The flagship
US4807331A scaffold lives in
``claim2cad.oblique_demo_scaffold`` and stays the gold standard;
this template uses the same primitives but adapts to any
example's claim_map without the hand-built mesh-spec table.

Strategy:
  * Split components into door-side / frame-side / shared-axis /
    other by keyword inheritance from their labels.
  * Pick or synthesise the four "must-have" structural meshes:
    door panel, frame panel, pintle pin, one upper + one lower
    bracket pair.
  * Assign each claim component_id to the most-similar
    structural mesh by label.
  * Apply the V12-J door rotation (35°) so the result reads as
    an opened door.
"""
from __future__ import annotations

import logging
from typing import Any

import build123d as bd

from claim2cad.demo_scaffold import (
    _frame_panel,
    _pintle_pin,
    _hinge_knuckle,
    _feature_marker,
    _curved_door_panel,
)
from claim2cad.oblique_demo_scaffold import (
    _door_side_leaf,
    _frame_side_bracket,
    _rotate_about_vertical_axis,
)
from claim2cad.scaffolds.base import (
    Scaffold,
    ScaffoldInput,
    ScaffoldResult,
    register_scaffold,
)

logger = logging.getLogger(__name__)


# Keywords that route a claim id to one of the four structural
# meshes.
_ROUTING_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("pintle_pin", ("pintle", "pin", "shaft", "axis")),
    ("door_panel", ("door", "panel_member", "moving panel", "leaf member")),
    ("fixed_frame", ("frame", "body", "vehicle", "fixed", "post")),
    ("upper_door_leaf", ("upper leaf", "upper extension", "door leaf",
                          "leaf flange")),
    ("upper_frame_bracket", ("upper bracket", "main member", "upper hinge",
                              "first sidewall", "second sidewall", "bight")),
    ("lower_door_leaf", ("lower leaf", "lower extension")),
    ("lower_frame_bracket", ("lower bracket", "lower hinge", "body half")),
    ("upper_hinge_knuckle", ("upper knuckle", "upper barrel")),
    ("lower_hinge_knuckle", ("lower knuckle", "lower barrel")),
]


@register_scaffold
class DoorHingeScaffold(Scaffold):
    """Generic door hinge scaffold derived from US4807331A. The
    flagship example uses the more polished
    `oblique_demo_scaffold.build_oblique_demo_us4807331a` directly.
    Other door/hinge examples use this generic version.
    """

    scaffold_id = "door_hinge"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        # Build the structural meshes at canonical positions.
        door_centre = (-70.0, -45.0, 0.0)
        frame_centre = (+70.0, +35.0, 0.0)
        upper_z = +90.0
        lower_z = -24.0
        pintle_xy = (-1.0, 0.0)

        meshes: dict[str, bd.Part] = {
            "door_panel": _curved_door_panel(door_centre),
            "fixed_frame": _frame_panel(frame_centre),
            "pintle_pin": _pintle_pin((pintle_xy[0], pintle_xy[1], 30.0),
                                       length=200.0),
            "upper_door_leaf": _door_side_leaf(
                (door_centre[0] + 86.0, door_centre[1] + 6.0, upper_z),
                label="upper_door_leaf"),
            "upper_frame_bracket": _frame_side_bracket(
                (frame_centre[0] - 38.0, frame_centre[1] - 6.0, upper_z),
                label="upper_frame_bracket"),
            "upper_hinge_knuckle": _hinge_knuckle(
                (pintle_xy[0], pintle_xy[1] + 4.0, upper_z),
                label="upper_hinge_knuckle"),
            "lower_door_leaf": _door_side_leaf(
                (door_centre[0] + 86.0, door_centre[1] + 6.0, lower_z),
                label="lower_door_leaf"),
            "lower_frame_bracket": _frame_side_bracket(
                (frame_centre[0] - 38.0, frame_centre[1] - 6.0, lower_z),
                label="lower_frame_bracket"),
            "lower_hinge_knuckle": _hinge_knuckle(
                (pintle_xy[0], pintle_xy[1] + 4.0, lower_z),
                label="lower_hinge_knuckle"),
        }

        # Apply 35° door rotation.
        door_side = {"door_panel", "upper_door_leaf", "lower_door_leaf"}
        for name, mesh in list(meshes.items()):
            if name in door_side:
                meshes[name] = _rotate_about_vertical_axis(
                    mesh, pivot_xy=pintle_xy, angle_deg=35.0,
                )
            meshes[name].label = name

        # Route each claim component_id to the best-matching mesh.
        cids = inputs.component_ids()
        children: list[bd.Part] = []
        ordered: list[str] = []
        used: set[str] = set()
        for cid in cids:
            label = inputs.component_label(cid)
            target = self._route(label)
            mesh = meshes.get(target)
            if mesh is not None and target not in used:
                mesh.label = cid
                children.append(mesh)
                ordered.append(cid)
                used.add(target)
            elif mesh is not None:
                # Mesh already owned — emit a marker outside it.
                bb = mesh.bounding_box()
                m = _feature_marker(
                    (bb.max.X + 5.0,
                     (bb.min.Y + bb.max.Y) / 2.0,
                     bb.max.Z + 5.0),
                    label=cid, radius_mm=1.0,
                )
                children.append(m)
                ordered.append(cid)
            else:
                # Unmapped — feature marker at the upper hinge centre.
                m = _feature_marker((0.0, 0.0, upper_z),
                                     label=cid, radius_mm=1.5)
                children.append(m)
                ordered.append(cid)

        # Always emit the structural meshes (so the scene is
        # complete even if the claim map didn't cover everything).
        for name, mesh in meshes.items():
            if name in used:
                continue
            mesh.label = name
            children.append(mesh)
            ordered.append(name)

        compound = bd.Compound(label="assembly", children=children)
        return ScaffoldResult(
            compound=compound,
            ordered_ids=ordered,
            scaffold_id=self.scaffold_id,
            diagnostics={"n_components": len(cids),
                          "structural_meshes": list(meshes.keys()),
                          "door_angle_deg": 35.0},
            quality_tier="good",
        )

    @staticmethod
    def _route(label: str) -> str | None:
        low = label.lower()
        for target, kws in _ROUTING_KEYWORDS:
            if any(k in low for k in kws):
                return target
        return None
