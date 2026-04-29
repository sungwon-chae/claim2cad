"""V13-L — PositioningApparatusScaffold.

Builds geometry for parallelogram-arm positioning apparatuses
(US5180955A class). The figure shows:

  * a low base block with rails / guides on either side,
  * a parallelogram framework formed by four arms in a roughly
    rectangular footprint,
  * a vertical center pivot shaft at the parallelogram center,
  * an end-effector block at one corner of the framework,
  * an electromagnetic actuator (coil + magnets + iron) at the
    rear of the base.

Distinct from `rotary_shaft` (which stacks parts coaxially) and
`linkage` (which strings parts in a chain) — this scaffold lays
the four arms in a 2D rectangular footprint so the
parallelogram is recognizable from above.
"""
from __future__ import annotations

import logging
import math

import build123d as bd

from claim2cad.scaffolds.base import (
    Scaffold,
    ScaffoldInput,
    ScaffoldResult,
    register_scaffold,
)

logger = logging.getLogger(__name__)


# Footprint of the parallelogram (mm).
_PARA_HALF_X = 80.0
_PARA_HALF_Y = 50.0
_BASE_THICKNESS = 12.0
_ARM_HEIGHT = 18.0
_PIVOT_RADIUS = 5.0


_ROUTING: list[tuple[str, tuple[str, ...]]] = [
    ("base_block", ("base structure", "base", "platform",
                    "support frame", "ground")),
    ("rail_left", ("first rail", "left rail", "first guide",
                   "left guide", "rail 1", "guide 1")),
    ("rail_right", ("second rail", "right rail", "second guide",
                    "right guide", "rail 2", "guide 2")),
    ("rail_generic", ("rail", "guide", "track")),
    ("parallelogram_frame", ("parallelogram structure",
                              "parallelogram linkage",
                              "parallelogram frame",
                              "parallelogram",
                              "linkage frame", "positioning linkage")),
    ("arm_1", ("first arm", "arm 1")),
    ("arm_2", ("second arm", "arm 2")),
    ("arm_3", ("third arm", "arm 3")),
    ("arm_4", ("fourth arm", "arm 4")),
    ("arm_section_a", ("first arm first section", "arm first section")),
    ("arm_section_b", ("first arm second section",
                       "arm second section")),
    ("arm_section_c", ("second arm first section",)),
    ("arm_section_d", ("second arm second section",)),
    ("arm_end_a", ("first arm first end", "arm first end")),
    ("arm_end_b", ("first arm second end",
                    "arm second end")),
    ("arm_end_c", ("second arm first end",)),
    ("arm_end_d", ("second arm second end",)),
    ("center_shaft", ("center shaft", "central shaft",
                       "pivot shaft", "central pivot",
                       "main pivot", "central pin")),
    ("end_effector", ("end-effector", "end effector",
                       "tool", "gripper", "wrist")),
    ("coil", ("electromagnetic coil", "coil",
               "drive coil", "stator coil")),
    ("magnet", ("magnet", "permanent magnet")),
    ("iron_core", ("iron structure", "iron core",
                    "stationary iron", "yoke", "pole piece")),
    ("actuator_means", ("means for moving",
                         "actuator means", "drive means")),
]


def _arm_at(corner_index: int) -> tuple[bd.Part, tuple[float, float, float]]:
    """Return (mesh, world position) for one of the four arms.
    Corners: 0=+X+Y, 1=+X-Y, 2=-X+Y, 3=-X-Y. Each arm is a thin
    rectangular bar oriented along ±X (top/bottom of parallelogram)
    or ±Y (left/right). For variety: corners 0,3 are X-aligned;
    corners 1,2 are Y-aligned. Together this forms the closed
    parallelogram outline."""
    if corner_index in (0, 3):
        # Long bars along X — top (+Y) and bottom (-Y).
        sx = _PARA_HALF_X * 1.6
        sy = 8.0
        sz = _ARM_HEIGHT
        cy = +_PARA_HALF_Y if corner_index == 0 else -_PARA_HALF_Y
        cx = 0.0
    else:
        # Bars along Y — right (+X) and left (-X).
        sx = 8.0
        sy = _PARA_HALF_Y * 1.6
        sz = _ARM_HEIGHT
        cx = +_PARA_HALF_X if corner_index == 1 else -_PARA_HALF_X
        cy = 0.0
    bar = bd.Box(sx, sy, sz)
    cz = _ARM_HEIGHT * 0.5 + _BASE_THICKNESS * 0.5 + 6.0
    return bar.translate((cx, cy, cz)), (cx, cy, cz)


@register_scaffold
class PositioningApparatusScaffold(Scaffold):
    """Parallelogram-arm positioning apparatus.

    Lays the four arms in a 2D rectangular footprint so the
    parallelogram is recognizable. Base block sits below; rails
    flank the base; center shaft is a vertical pin at the
    parallelogram center; end-effector at one corner;
    electromagnetic actuator parts at the rear of the base.
    """

    scaffold_id = "positioning_apparatus"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        cids = inputs.component_ids() or ["component_0"]
        n = len(cids)

        # ---- Build the canonical structural meshes ----
        base = bd.Box(_PARA_HALF_X * 2.4, _PARA_HALF_Y * 2.4, _BASE_THICKNESS)
        base = base.translate((0.0, 0.0, 0.0))

        rail_left = bd.Box(_PARA_HALF_X * 2.0, 6.0, 6.0).translate(
            (0.0, -_PARA_HALF_Y - 8.0, _BASE_THICKNESS * 0.5 + 3.0))
        rail_right = bd.Box(_PARA_HALF_X * 2.0, 6.0, 6.0).translate(
            (0.0, +_PARA_HALF_Y + 8.0, _BASE_THICKNESS * 0.5 + 3.0))

        arm_meshes = [_arm_at(i) for i in range(4)]
        arm_centers = [m[1] for m in arm_meshes]

        para_frame = bd.Box(2.0, 2.0, 1.0).translate((0.0, 0.0, 0.0))
        # The parallelogram_frame is the symbolic union of the 4 arms;
        # we synthesise a thin diagonal cross-brace for it so it has a
        # distinct selectable mesh that hugs the framework.
        diag_len = math.hypot(_PARA_HALF_X, _PARA_HALF_Y) * 2.0
        para_frame = bd.Box(diag_len * 0.9, 4.0, 4.0)
        para_frame = para_frame.rotate(bd.Axis.Z, 30.0)
        para_frame = para_frame.translate(
            (0.0, 0.0, _BASE_THICKNESS * 0.5 + _ARM_HEIGHT + 8.0))

        # Center shaft — vertical pin standing at the parallelogram
        # center (NOT a long horizontal cylinder).
        center_shaft = bd.Cylinder(
            radius=_PIVOT_RADIUS,
            height=_ARM_HEIGHT * 2.5,
        )
        center_shaft = center_shaft.translate(
            (0.0, 0.0, _BASE_THICKNESS * 0.5 + _ARM_HEIGHT * 1.0))

        # End effector — block at one corner of the framework.
        end_effector = bd.Box(22.0, 22.0, 22.0).translate(
            (+_PARA_HALF_X + 14.0, +_PARA_HALF_Y + 14.0,
             _BASE_THICKNESS * 0.5 + _ARM_HEIGHT + 14.0))

        # Electromagnetic actuator — coil + magnets + iron core,
        # placed behind the base (-X face).
        coil = bd.Cylinder(radius=12.0, height=20.0).translate(
            (-_PARA_HALF_X - 30.0, 0.0,
             _BASE_THICKNESS * 0.5 + 10.0))
        magnet = bd.Box(20.0, 14.0, 8.0).translate(
            (-_PARA_HALF_X - 50.0, +14.0,
             _BASE_THICKNESS * 0.5 + 6.0))
        iron_core = bd.Box(24.0, 14.0, 18.0).translate(
            (-_PARA_HALF_X - 70.0, 0.0,
             _BASE_THICKNESS * 0.5 + 12.0))
        actuator_means = bd.Cylinder(radius=6.0, height=14.0).translate(
            (-_PARA_HALF_X - 30.0, +24.0,
             _BASE_THICKNESS * 0.5 + 8.0))

        meshes: dict[str, bd.Part] = {
            "base_block": base,
            "rail_left": rail_left,
            "rail_right": rail_right,
            "rail_generic": rail_left,  # alias to whichever rail wins
            "parallelogram_frame": para_frame,
            "arm_1": arm_meshes[0][0],
            "arm_2": arm_meshes[1][0],
            "arm_3": arm_meshes[2][0],
            "arm_4": arm_meshes[3][0],
            "center_shaft": center_shaft,
            "end_effector": end_effector,
            "coil": coil,
            "magnet": magnet,
            "iron_core": iron_core,
            "actuator_means": actuator_means,
        }

        # Arm sub-sections / arm-ends as small markers near the
        # respective arm midpoints / corners.
        for k, idx in (("arm_section_a", 0), ("arm_section_b", 0),
                       ("arm_section_c", 1), ("arm_section_d", 1)):
            cx, cy, cz = arm_centers[idx]
            offset = +18.0 if k.endswith("_a") or k.endswith("_c") else -18.0
            mk = bd.Sphere(radius=3.0).translate((cx + offset, cy, cz + 4.0))
            meshes[k] = mk
        for k, idx in (("arm_end_a", 0), ("arm_end_b", 0),
                       ("arm_end_c", 3), ("arm_end_d", 3)):
            cx, cy, cz = arm_centers[idx]
            sign = +1.0 if k.endswith("_a") or k.endswith("_c") else -1.0
            mk = bd.Sphere(radius=2.5).translate((cx + sign * 32.0,
                                                   cy + sign * 6.0,
                                                   cz + 6.0))
            meshes[k] = mk

        # ---- Route claim ids to the closest structural mesh ----
        children: list[bd.Part] = []
        ordered: list[str] = []
        used: set[str] = set()
        for cid in cids:
            label = inputs.component_label(cid).lower()
            target = self._route(label)
            mesh = meshes.get(target) if target else None
            if mesh is not None and target not in used:
                m = mesh
                m.label = cid
                children.append(m)
                ordered.append(cid)
                used.add(target)
            elif mesh is not None:
                # Already used — emit a small marker just outside.
                bb = mesh.bounding_box()
                m = bd.Sphere(radius=2.0).translate(
                    (bb.max.X + 6.0,
                     (bb.min.Y + bb.max.Y) * 0.5,
                     bb.max.Z + 4.0))
                m.label = cid
                children.append(m)
                ordered.append(cid)
            else:
                # No keyword match — drop it as a marker on the
                # base, biased away from the parallelogram so it
                # is visible.
                idx = sum(1 for x in ordered) % 5
                m = bd.Sphere(radius=2.0).translate(
                    (-_PARA_HALF_X + idx * 16.0, -_PARA_HALF_Y - 18.0,
                     _BASE_THICKNESS + 4.0))
                m.label = cid
                children.append(m)
                ordered.append(cid)

        # Always include the structural meshes that weren't claimed.
        for name, mesh in meshes.items():
            if name in used:
                continue
            if name in ("rail_generic",
                        "arm_section_a", "arm_section_b",
                        "arm_section_c", "arm_section_d",
                        "arm_end_a", "arm_end_b",
                        "arm_end_c", "arm_end_d"):
                continue  # markers — only emit if claim id requested
            mesh.label = name
            children.append(mesh)
            ordered.append(name)

        compound = bd.Compound(label="assembly", children=children)
        return ScaffoldResult(
            compound=compound,
            ordered_ids=ordered,
            scaffold_id=self.scaffold_id,
            diagnostics={
                "n_components": n,
                "footprint_xy": [_PARA_HALF_X * 2, _PARA_HALF_Y * 2],
                "structural_meshes": list(meshes.keys()),
            },
            quality_tier="good",
        )

    @staticmethod
    def _route(label: str) -> str | None:
        for target, kws in _ROUTING:
            if any(k in label for k in kws):
                return target
        return None
