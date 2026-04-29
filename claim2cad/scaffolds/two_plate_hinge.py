"""V13-B — TwoPlateHingeScaffold.

Simpler than DoorHingeScaffold — just two flat plates joined by
a single hinge axis. Suitable for examples like
US4502185A_concealed_hinge_assembly which describes a plain
hinge without the spring-loaded mechanism complexity of
US4807331A.
"""
from __future__ import annotations

import build123d as bd

from claim2cad.demo_scaffold import _frame_panel, _pintle_pin, _hinge_knuckle, _feature_marker
from claim2cad.oblique_demo_scaffold import _door_side_leaf, _frame_side_bracket, _rotate_about_vertical_axis
from claim2cad.scaffolds.base import (
    Scaffold, ScaffoldInput, ScaffoldResult, register_scaffold,
)


@register_scaffold
class TwoPlateHingeScaffold(Scaffold):
    """Two flat plates + a single hinge axis. Door rotated 25°."""

    scaffold_id = "two_plate_hinge"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        cids = inputs.component_ids() or ["component_0"]
        pintle_xy = (0.0, 0.0)

        # Build plates + hinge.
        door = bd.Box(120.0, 5.0, 180.0).translate((-65.0, -8.0, 0.0))
        door.label = "door_plate"
        frame = bd.Box(80.0, 5.0, 180.0).translate((45.0, +8.0, 0.0))
        frame.label = "frame_plate"
        pin = _pintle_pin((0.0, 0.0, 0.0), length=180.0)
        pin.label = "hinge_pin"
        upper_leaf = _door_side_leaf((-8.0, -3.0, +60.0), label="upper_leaf")
        lower_leaf = _door_side_leaf((-8.0, -3.0, -60.0), label="lower_leaf")
        upper_brk = _frame_side_bracket((+8.0, +3.0, +60.0), label="upper_bracket")
        lower_brk = _frame_side_bracket((+8.0, +3.0, -60.0), label="lower_bracket")

        # Apply 25° door rotation
        for door_part in (door, upper_leaf, lower_leaf):
            pass  # mutating issue
        door = _rotate_about_vertical_axis(door, pivot_xy=pintle_xy, angle_deg=25.0)
        upper_leaf = _rotate_about_vertical_axis(upper_leaf, pivot_xy=pintle_xy, angle_deg=25.0)
        lower_leaf = _rotate_about_vertical_axis(lower_leaf, pivot_xy=pintle_xy, angle_deg=25.0)
        for p, lab in [(door, "door_plate"), (upper_leaf, "upper_leaf"),
                        (lower_leaf, "lower_leaf")]:
            p.label = lab

        meshes = {
            "door_plate": door, "frame_plate": frame, "hinge_pin": pin,
            "upper_leaf": upper_leaf, "lower_leaf": lower_leaf,
            "upper_bracket": upper_brk, "lower_bracket": lower_brk,
        }

        # Route each cid to the closest matching mesh.
        children: list[bd.Part] = []
        ordered: list[str] = []
        used: set[str] = set()
        for cid in cids:
            label = inputs.component_label(cid).lower()
            if any(k in label for k in ("pintle", "pin", "shaft")):
                target = "hinge_pin"
            elif "door" in label or "leaf" in label and "lower" not in label and "upper" not in label:
                target = "door_plate"
            elif "frame" in label or "fixed" in label:
                target = "frame_plate"
            elif "upper" in label and ("leaf" in label or "extension" in label):
                target = "upper_leaf"
            elif "lower" in label and ("leaf" in label or "extension" in label):
                target = "lower_leaf"
            elif "upper" in label:
                target = "upper_bracket"
            elif "lower" in label:
                target = "lower_bracket"
            else:
                target = "frame_plate"
            mesh = meshes.get(target)
            if mesh is not None and target not in used:
                mesh.label = cid
                children.append(mesh)
                ordered.append(cid)
                used.add(target)
            else:
                bb = (mesh or frame).bounding_box()
                m = _feature_marker(
                    (bb.max.X + 4.0, (bb.min.Y + bb.max.Y) / 2, bb.max.Z + 4.0),
                    label=cid, radius_mm=1.0,
                )
                children.append(m); ordered.append(cid)

        for name, mesh in meshes.items():
            if name in used: continue
            mesh.label = name
            children.append(mesh); ordered.append(name)

        compound = bd.Compound(label="assembly", children=children)
        return ScaffoldResult(
            compound=compound, ordered_ids=ordered,
            scaffold_id=self.scaffold_id,
            diagnostics={"n_components": len(cids), "door_angle_deg": 25.0},
            quality_tier="good",
        )
