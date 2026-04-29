"""V13-L / V13-Q — PositioningApparatusScaffold.

V13-Q rebuild. The first cut (V13-L) put the four arms on the
edges of a rectangle which read as a flat plate with thin
sticks. The actual US5180955A figure is much more specific:

  * a CENTRAL PIVOT DISC at the origin, with an internal X-spoke
    pattern (the "20" hub with the cross-bracing visible in
    figs 2A/B/C),
  * a LONG VERTICAL ARM LEG extending in -Y from the pivot
    (items 30/40/46) with a rectangular housing block at its
    far end,
  * a LONG HORIZONTAL ARM LEG extending in +X from the pivot
    (item 31) with a cylindrical-front housing (item 56) at
    its far end,
  * a PARALLELOGRAM SUB-ASSEMBLY at the top-left of the pivot —
    two small disc pivots (items 32, 39) joined by short link
    bars, with a triangular pointer (item 66) capping it,
  * guide RAILS / SLOTTED TRACKS on the base plate,
  * an EM ACTUATOR (coil + magnets + iron core) in the optional
    actuator block at the rear.

This produces a recognizable T-shape articulated positioning
apparatus, not a rectangle of bars. Distinct from `linkage`
(chain-of-links), `rotary_shaft` (coaxial), and
`bracket_mount` (base + flange).
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


# ---- Footprint constants (mm) -------------------------------------------
_BASE_X = 170.0
_BASE_Y = 130.0
_BASE_THICKNESS = 10.0

_PIVOT_R = 26.0
_PIVOT_H = 22.0
_HUB_RING_R_INNER = 9.0

_VARM_LEN = 84.0   # vertical arm leg length (along -Y)
_VARM_W = 30.0
_VARM_H = 22.0

_HARM_LEN = 80.0   # horizontal arm leg length (along +X)
_HARM_W = 26.0
_HARM_H = 22.0

_END_HOUSING_X = 32.0
_END_HOUSING_Y = 28.0
_END_HOUSING_Z = 30.0

_RAIL_W = 10.0
_RAIL_H = 8.0


_ROUTING: list[tuple[str, tuple[str, ...]]] = [
    ("base_plate", ("base structure", "base plate", "base",
                     "platform", "ground", "support frame")),
    ("rail_left", ("first rail", "left rail", "first guide",
                    "left guide")),
    ("rail_right", ("second rail", "right rail", "second guide",
                     "right guide")),
    ("rail_generic", ("rail", "guide", "track")),
    ("pivot_hub", ("center shaft", "central shaft",
                    "pivot shaft", "central pivot", "main pivot",
                    "central pin", "hub")),
    ("vertical_arm", ("first arm", "vertical arm",
                       "primary arm", "main arm")),
    ("vertical_end_housing", ("first arm second end",
                                "vertical arm end")),
    ("horizontal_arm", ("second arm", "horizontal arm",
                         "secondary arm")),
    ("horizontal_end_housing", ("second arm second end",
                                  "horizontal arm end",
                                  "end-effector",
                                  "end effector",
                                  "tool", "gripper", "wrist")),
    ("parallel_arm_a", ("third arm",)),
    ("parallel_arm_b", ("fourth arm",)),
    ("parallel_pivot_a", ("first arm first end",
                            "third arm first end")),
    ("parallel_pivot_b", ("second arm first end",
                            "fourth arm first end")),
    ("parallelogram_frame", ("parallelogram structure",
                               "parallelogram linkage",
                               "parallelogram frame",
                               "parallelogram",
                               "linkage frame",
                               "positioning linkage")),
    ("arm_section_a", ("first arm first section",
                        "arm first section",
                        "third arm first section")),
    ("arm_section_b", ("first arm second section",
                        "arm second section",
                        "third arm second section")),
    ("arm_section_c", ("second arm first section",
                        "fourth arm first section")),
    ("arm_section_d", ("second arm second section",
                        "fourth arm second section")),
    ("end_pointer", ("pointer", "indicator", "tip", "stylus")),
    ("coil", ("electromagnetic coil", "coil",
               "drive coil", "stator coil")),
    ("magnet", ("magnet", "permanent magnet")),
    ("iron_core", ("iron structure", "iron core",
                    "stationary iron", "yoke", "pole piece")),
    ("actuator_means", ("means for moving",
                         "actuator means", "drive means")),
]


def _spoke_at(angle_deg: float, r: float, length: float,
               width: float, thickness: float) -> bd.Part:
    """One radial spoke from origin, oriented at angle_deg."""
    bar = bd.Box(length, width, thickness)
    bar = bar.translate((length / 2.0, 0.0, 0.0))
    return bar.rotate(bd.Axis.Z, angle_deg)


def _hub_with_spokes() -> bd.Part:
    """Central pivot disc with an X-pattern of four spokes inside.
    Captures the figure's cross-bracing on the central pivot."""
    disc_outer = bd.Cylinder(radius=_PIVOT_R, height=_PIVOT_H)
    disc_bore = bd.Cylinder(radius=_HUB_RING_R_INNER,
                              height=_PIVOT_H + 2.0)
    hub = disc_outer - disc_bore
    # Add four short spokes inside the disc rim (X-pattern in XY).
    for ang in (45.0, 135.0, 225.0, 315.0):
        spoke = bd.Box(_PIVOT_R * 1.1, 4.0, _PIVOT_H * 0.6)
        spoke = spoke.rotate(bd.Axis.Z, ang)
        spoke = spoke.translate((0.0, 0.0, 0.0))
        hub = hub + spoke
    return hub


def _vertical_arm_leg(z_top: float) -> bd.Part:
    """Long vertical arm extending in -Y from the pivot, with
    light cross-ribbing visible on its top face."""
    body = bd.Box(_VARM_W, _VARM_LEN, _VARM_H)
    body = body.translate((0.0, -_VARM_LEN / 2.0,
                            z_top - _VARM_H / 2.0))
    # Two cross-ribs on the top face for visual interest.
    rib_y = -_VARM_LEN * 0.35
    for sign in (-1.0, +1.0):
        rib = bd.Box(_VARM_W * 0.9, 3.0, 3.0).translate(
            (0.0, rib_y * sign, z_top + 1.0))
        body = body + rib
    return body


def _horizontal_arm_leg(z_top: float) -> bd.Part:
    body = bd.Box(_HARM_LEN, _HARM_W, _HARM_H)
    body = body.translate((_HARM_LEN / 2.0, 0.0,
                            z_top - _HARM_H / 2.0))
    rib_x = _HARM_LEN * 0.35
    for sign in (-1.0, +1.0):
        rib = bd.Box(3.0, _HARM_W * 0.9, 3.0).translate(
            (rib_x * sign + _HARM_LEN / 2.0, 0.0, z_top + 1.0))
        body = body + rib
    return body


def _vertical_end_housing(z_top: float) -> bd.Part:
    """Block at the far end of the vertical arm leg (item 46
    in the figure)."""
    h = bd.Box(_END_HOUSING_X * 0.7, _END_HOUSING_Y, _END_HOUSING_Z)
    return h.translate((0.0, -_VARM_LEN - _END_HOUSING_Y / 2.0,
                          z_top + _END_HOUSING_Z / 2.0 - _VARM_H / 2.0))


def _horizontal_end_housing(z_top: float) -> bd.Part:
    """Cylindrical-front housing at the far end of the horizontal
    arm leg (item 56 in the figure: rectangular block with a
    rounded nose)."""
    block = bd.Box(_END_HOUSING_X, _END_HOUSING_Y, _END_HOUSING_Z)
    block = block.translate((_HARM_LEN + _END_HOUSING_X / 2.0,
                               0.0,
                               z_top + _END_HOUSING_Z / 2.0
                               - _HARM_H / 2.0))
    nose = bd.Cylinder(radius=_END_HOUSING_Y * 0.5,
                        height=_END_HOUSING_Z)
    nose = nose.translate(
        (_HARM_LEN, 0.0,
         z_top + _END_HOUSING_Z / 2.0 - _HARM_H / 2.0))
    return block + nose


def _parallelogram_cluster(pivot_xy: tuple[float, float],
                            z_top: float) -> dict[str, bd.Part]:
    """Top-left parallelogram subassembly: two stacked disc
    pivots joined by a pair of link bars and capped by a small
    triangular pointer."""
    px, py = pivot_xy
    pivot_a = bd.Cylinder(radius=10.0, height=10.0).translate(
        (px, py, z_top + 5.0))
    pivot_b = bd.Cylinder(radius=10.0, height=10.0).translate(
        (px - 30.0, py, z_top + 5.0))
    bar_top = bd.Box(34.0, 5.0, 4.0).translate(
        (px - 15.0, py + 8.0, z_top + 7.0))
    bar_bot = bd.Box(34.0, 5.0, 4.0).translate(
        (px - 15.0, py - 8.0, z_top + 7.0))
    pointer = bd.Cone(top_radius=0.0, bottom_radius=8.0,
                       height=14.0)
    pointer = pointer.rotate(bd.Axis.Y, 90.0).translate(
        (px - 38.0, py, z_top + 7.0))
    return {
        "parallel_pivot_a": pivot_a,
        "parallel_pivot_b": pivot_b,
        "parallel_arm_a": bar_top,
        "parallel_arm_b": bar_bot,
        "end_pointer": pointer,
    }


@register_scaffold
class PositioningApparatusScaffold(Scaffold):
    """T-shape articulated positioning apparatus — central
    spoked pivot hub, vertical and horizontal arm legs with
    end housings, parallelogram cluster on the upper-left,
    rails on the base, optional electromagnetic actuator at
    the rear of the base."""

    scaffold_id = "positioning_apparatus"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        cids = inputs.component_ids() or ["component_0"]
        n = len(cids)

        z_base_top = _BASE_THICKNESS
        z_arm_top = z_base_top + _PIVOT_H + 2.0

        # Base plate centered roughly under the T-arm assembly
        # (slightly biased toward +X so the horizontal arm stays
        # over the plate).
        base_cx = 26.0
        base_cy = -18.0
        base = bd.Box(_BASE_X, _BASE_Y, _BASE_THICKNESS).translate(
            (base_cx, base_cy, _BASE_THICKNESS / 2.0))

        # Side rails.
        rail_left = bd.Box(_BASE_X * 0.92, _RAIL_W, _RAIL_H).translate(
            (base_cx, base_cy - _BASE_Y / 2.0 + _RAIL_W / 2.0,
             z_base_top + _RAIL_H / 2.0))
        rail_right = bd.Box(_BASE_X * 0.92, _RAIL_W, _RAIL_H).translate(
            (base_cx, base_cy + _BASE_Y / 2.0 - _RAIL_W / 2.0,
             z_base_top + _RAIL_H / 2.0))

        # Central pivot hub with spokes.
        hub = _hub_with_spokes()
        hub = hub.translate((0.0, 0.0, z_base_top + _PIVOT_H / 2.0))

        # Two arm legs extending from the hub.
        v_arm = _vertical_arm_leg(z_arm_top)
        h_arm = _horizontal_arm_leg(z_arm_top)

        # End housings.
        v_end = _vertical_end_housing(z_arm_top)
        h_end = _horizontal_end_housing(z_arm_top)

        # Parallelogram cluster on the upper-left of the hub.
        para_cluster = _parallelogram_cluster(
            pivot_xy=(-30.0, +28.0), z_top=z_arm_top)

        # Parallelogram_frame symbolic mesh — diagonal cross-brace
        # spanning the cluster (visual cue for the X-pattern in
        # the figure's pivot disc).
        pf_a = bd.Box(60.0, 4.0, 5.0)
        pf_a = pf_a.rotate(bd.Axis.Z, 30.0)
        pf_a = pf_a.translate((-20.0, 28.0, z_arm_top + 8.0))
        pf_b = bd.Box(60.0, 4.0, 5.0)
        pf_b = pf_b.rotate(bd.Axis.Z, -30.0)
        pf_b = pf_b.translate((-20.0, 28.0, z_arm_top + 8.0))
        para_frame = pf_a + pf_b

        # EM actuator at the rear of the base (-X side).
        coil = bd.Cylinder(radius=14.0, height=22.0).translate(
            (-_BASE_X / 2.0 + 30.0, +30.0,
             z_base_top + 11.0))
        magnet = bd.Box(22.0, 14.0, 10.0).translate(
            (-_BASE_X / 2.0 + 60.0, +30.0,
             z_base_top + 5.0))
        iron_core = bd.Box(28.0, 16.0, 22.0).translate(
            (-_BASE_X / 2.0 + 22.0, -10.0,
             z_base_top + 11.0))
        actuator_means = bd.Cylinder(radius=6.0, height=12.0).translate(
            (-_BASE_X / 2.0 + 50.0, -10.0,
             z_base_top + 6.0))

        meshes: dict[str, bd.Part] = {
            "base_plate": base,
            "rail_left": rail_left,
            "rail_right": rail_right,
            "rail_generic": rail_left,
            "pivot_hub": hub,
            "vertical_arm": v_arm,
            "horizontal_arm": h_arm,
            "vertical_end_housing": v_end,
            "horizontal_end_housing": h_end,
            "parallelogram_frame": para_frame,
            **para_cluster,
            "coil": coil,
            "magnet": magnet,
            "iron_core": iron_core,
            "actuator_means": actuator_means,
        }

        # Sub-section markers placed along the relevant arm's
        # midline so they aren't coincident.
        for k, parent_name, sign_y, sign_x in (
            ("arm_section_a", "vertical_arm", -0.30, 0.0),
            ("arm_section_b", "vertical_arm", -0.65, 0.0),
            ("arm_section_c", "horizontal_arm", 0.0, +0.30),
            ("arm_section_d", "horizontal_arm", 0.0, +0.65),
        ):
            parent_bb = meshes[parent_name].bounding_box()
            cx = parent_bb.min.X + (parent_bb.max.X - parent_bb.min.X) * (
                0.5 + sign_x)
            cy = parent_bb.min.Y + (parent_bb.max.Y - parent_bb.min.Y) * (
                0.5 + sign_y)
            cz = parent_bb.max.Z + 5.0
            meshes[k] = bd.Sphere(radius=2.5).translate((cx, cy, cz))

        # Route claim ids → meshes.
        children: list[bd.Part] = []
        ordered: list[str] = []
        used: set[str] = set()
        for cid in cids:
            label = inputs.component_label(cid).lower()
            target = self._route(label)
            mesh = meshes.get(target) if target else None
            if mesh is not None and target not in used:
                mesh.label = cid
                children.append(mesh)
                ordered.append(cid)
                used.add(target)
            elif mesh is not None:
                bb = mesh.bounding_box()
                m = bd.Sphere(radius=2.0).translate(
                    (bb.max.X + 5.0,
                     (bb.min.Y + bb.max.Y) * 0.5,
                     bb.max.Z + 4.0))
                m.label = cid
                children.append(m)
                ordered.append(cid)
            else:
                idx = sum(1 for x in ordered) % 6
                m = bd.Sphere(radius=2.0).translate(
                    (-_BASE_X / 2.0 + 8.0 + idx * 12.0,
                     -_BASE_Y / 2.0 + 14.0,
                     z_base_top + 4.0))
                m.label = cid
                children.append(m)
                ordered.append(cid)

        # Always emit the structural meshes that nobody claimed.
        STRUCTURAL = {"base_plate", "rail_left", "rail_right",
                       "pivot_hub", "vertical_arm", "horizontal_arm",
                       "vertical_end_housing",
                       "horizontal_end_housing",
                       "parallelogram_frame",
                       "parallel_pivot_a", "parallel_pivot_b",
                       "parallel_arm_a", "parallel_arm_b",
                       "end_pointer"}
        for name, mesh in meshes.items():
            if name in used or name not in STRUCTURAL:
                continue
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
                "footprint_xy": [_BASE_X, _BASE_Y],
                "structural_meshes": sorted(STRUCTURAL),
            },
            quality_tier="good",
        )

    @staticmethod
    def _route(label: str) -> str | None:
        for target, kws in _ROUTING:
            if any(k in label for k in kws):
                return target
        return None
