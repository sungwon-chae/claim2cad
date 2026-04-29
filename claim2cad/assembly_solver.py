"""Build the 3D assembly from per-component shapes + constraints.

V11-18 update: shape-family builders for ``knuckle``, ``hinge_leaf``,
``pin``, ``shaft``, ``washer`` and ``boss`` route to the genuine 3D
hinge primitives in :mod:`claim2cad.components.joints.hinge_primitives`
(``HingeKnuckle``, ``HingeLeafWithKnuckles``, ``HingeShaft``,
``Washer``, ``Boss``). The solver also runs an *auto-drill* pass that
adds a real cylindrical bore to plate / bracket / flange / tab parts
whose constraint list contains ``passes_through`` or ``coaxial_with``
to a pin/shaft — that single change converts most of the previously-
flat parts into solids with at least one curved face.


Inputs from :mod:`claim2cad.shape_inference`:

* per-component ``shape_family`` + dimensions
* per-component VLM-suggested pose
* per-component constraint list (coaxial_with, passes_through, etc.)

The solver:

1. Picks a ``build123d`` Solid factory per ``shape_family``.
2. Applies *constraints* to override the VLM-suggested pose where the
   constraint is more reliable than the pose:
   - ``coaxial_with`` / ``passes_through`` snaps both parts to share an
     XY position along the shared main axis.
   - ``nested_in`` snaps the inner part's XY centre to its parent's.
   - ``above`` / ``below`` adjusts Z by stacking.
3. Applies the (possibly-adjusted) pose to each Solid.
4. Returns a flat ``Compound`` with each component as a top-level
   labelled child — so the v1.0 GLB-naming contract holds.

The solver is intentionally simple: a single pass over the constraint
graph, no iterative SAT. For the common patent-figure cases (a
pintle-pin coaxial with N hinge knuckles + a leaf flange) this is
sufficient. More complex constraints can be added per shape_family.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import build123d as bd

from claim2cad.shape_inference import ComponentShape, ShapeInferenceSet

logger = logging.getLogger(__name__)


@dataclass
class SolverDiagnostics:
    component_id: str
    shape_family: str
    bbox_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    pose_applied_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    constraints_applied: list[str] = field(default_factory=list)
    fell_back_to_box: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# Per-shape-family solid construction
# ---------------------------------------------------------------------------


def _build_plate(s: ComponentShape) -> bd.Part | None:
    """Plate / leaf / tab / flange / housing shells: rectangular slab."""
    w = max(s.width_mm, 8.0)
    h = max(s.height_mm, 8.0)
    t = max(s.thickness_mm, max(s.depth_mm, 2.0))
    return bd.Box(w, h, t)


def _build_bracket(s: ComponentShape) -> bd.Part | None:
    """Bracket / link: U-channel from a base + two sides."""
    w = max(s.width_mm, 30.0)
    h = max(s.height_mm, 30.0)
    d = max(s.depth_mm, 25.0)
    t = max(s.thickness_mm, 3.0)
    base = bd.Box(w, t, h).translate((0, -d / 2.0 + t / 2.0, 0))
    side_l = bd.Box(t, d, h).translate((-w / 2.0 + t / 2.0, 0, 0))
    side_r = bd.Box(t, d, h).translate((+w / 2.0 - t / 2.0, 0, 0))
    return base + side_l + side_r


def _build_hinge_leaf(s: ComponentShape) -> bd.Part | None:
    """Plate with one or more integrated knuckle barrels along its
    hinge edge — uses ``HingeLeafWithKnuckles`` for real cylindrical
    barrel geometry, not a flat extrusion."""
    from claim2cad.components.joints.hinge_primitives import HingeLeafWithKnuckles
    w = max(s.width_mm, 50.0)
    h = max(s.height_mm, max(s.depth_mm, 60.0))
    t = max(s.thickness_mm, 3.0)
    od = max(s.diameter_mm, t * 2.5)
    bore = max(s.diameter_mm * 0.45 if s.diameter_mm else 2.5, 2.0)
    if bore >= od:
        bore = od * 0.4
    knuckle_count = max(1, min(5, int(round(h / max(od * 1.4, 12.0)))))
    leaf = HingeLeafWithKnuckles(
        leaf_width=w,
        leaf_height=h,
        leaf_thickness=t,
        barrel_outer_diameter=od,
        barrel_inner_diameter=bore,
        knuckle_count=knuckle_count,
    )
    return leaf.build()


def _build_knuckle(s: ComponentShape) -> bd.Part | None:
    """Hinge knuckle / barrel via ``HingeKnuckle`` — chamfered hollow
    cylinder."""
    from claim2cad.components.joints.hinge_primitives import HingeKnuckle
    od = max(s.diameter_mm, max(s.width_mm, 12.0))
    bore = max(s.diameter_mm * 0.45 if s.diameter_mm else 2.5, 2.0)
    if bore >= od:
        bore = od * 0.45
    height = max(s.depth_mm, max(s.height_mm, max(s.thickness_mm, 12.0)))
    k = HingeKnuckle(
        barrel_outer_diameter=od,
        barrel_inner_diameter=bore,
        barrel_height=height,
        chamfer_mm=min(0.6, height * 0.05, (od - bore) * 0.45),
    )
    return k.build()


def _build_pin(s: ComponentShape) -> bd.Part | None:
    """Cylindrical hinge pin / pintle / shaft via ``HingeShaft`` — the
    body has chamfered ends and an optional rounded head; never just a
    bare cylinder anymore."""
    from claim2cad.components.joints.hinge_primitives import HingeShaft
    diameter = max(s.diameter_mm, max(s.thickness_mm, 4.0))
    length = max(s.depth_mm, max(s.height_mm, 50.0))
    pin = HingeShaft(
        diameter=diameter,
        length=length,
        head_style="round",
        chamfer_mm=min(0.5, diameter * 0.1),
        groove=False,
    )
    return pin.build()


def _build_washer(s: ComponentShape) -> bd.Part | None:
    """Annular washer via ``Washer``."""
    from claim2cad.components.joints.hinge_primitives import Washer
    od = max(s.diameter_mm, max(s.width_mm, 12.0))
    bore = max(s.diameter_mm * 0.45 if s.diameter_mm else 4.0, 3.0)
    if bore >= od:
        bore = od * 0.45
    t = max(s.thickness_mm, max(s.depth_mm, 1.5))
    w = Washer(outer_diameter=od, inner_diameter=bore, thickness=t)
    return w.build()


def _build_boss(s: ComponentShape) -> bd.Part | None:
    """Cylindrical boss via ``Boss`` — has a top chamfer, not a bare
    cylinder."""
    from claim2cad.components.joints.hinge_primitives import Boss
    diameter = max(s.diameter_mm, max(s.width_mm, 8.0))
    h = max(s.depth_mm, max(s.height_mm, max(s.thickness_mm, 6.0)))
    boss = Boss(diameter=diameter, height=h, chamfer_mm=min(0.5, h * 0.1))
    return boss.build()


def _build_spring(s: ComponentShape) -> bd.Part | None:
    od = max(s.diameter_mm, 14.0)
    wire_d = max(s.thickness_mm, 1.4)
    free_l = max(s.height_mm, max(s.depth_mm, 30.0))
    coil_r = od / 2.0 - wire_d / 2.0
    pitch = max(free_l / 5.0, wire_d * 1.6)
    helix = bd.Helix(pitch=pitch, height=free_l, radius=coil_r)
    with bd.BuildPart() as part:
        with bd.BuildSketch(bd.Plane(origin=helix @ 0, z_dir=helix % 0)):
            bd.Circle(wire_d / 2.0)
        bd.sweep(path=helix)
    bb = part.part.bounding_box()
    dz = -(bb.min.Z + bb.max.Z) / 2.0
    return part.part.translate((0, 0, dz))


def _build_link(s: ComponentShape) -> bd.Part | None:
    return _build_bracket(s)


def _build_slot(s: ComponentShape) -> bd.Part | None:
    """Slot is a feature, not a body — render as a thin elongated disc."""
    w = max(s.width_mm, 10.0)
    h = max(s.height_mm, 4.0)
    t = max(s.thickness_mm, max(s.depth_mm, 2.0))
    return bd.Box(w, h, t)


def _build_hole_marker(s: ComponentShape) -> bd.Part | None:
    """Hole as a feature — show as a small annulus to mark the location."""
    od = max(s.diameter_mm, 6.0)
    bore = max(s.diameter_mm * 0.5, od * 0.5)
    t = max(s.thickness_mm, 1.5)
    outer = bd.Cylinder(od / 2.0, t)
    inner = bd.Cylinder(bore / 2.0, t * 1.05)
    return outer - inner


def _build_fastener(s: ComponentShape) -> bd.Part | None:
    """Bolt/screw — short cylinder with a head disc."""
    diameter = max(s.diameter_mm, 4.0)
    length = max(s.depth_mm, max(s.height_mm, 14.0))
    shaft = bd.Cylinder(diameter / 2.0, length)
    head_d = diameter * 1.6
    head_h = diameter * 0.6
    head = bd.Cylinder(head_d / 2.0, head_h).translate((0, 0, length / 2.0 + head_h / 2.0))
    return shaft + head


def _build_other(s: ComponentShape) -> bd.Part | None:
    """Fallback: a small box. The solver flags ``fell_back_to_box=True``."""
    w = max(s.width_mm, 8.0)
    h = max(s.height_mm, 8.0)
    d = max(s.depth_mm, 8.0)
    return bd.Box(w, h, d)


def _build_bracket_c_from_shape(s: ComponentShape) -> bd.Part | None:
    """V11-18: HingeBracketC for bracket/link/housing parts that share
    a pin axis. Real cylindrical barrels at the pin axis, not a hollow
    U-channel."""
    from claim2cad.components.joints.hinge_primitives import HingeBracketC
    w = max(s.width_mm, 30.0)
    h = max(s.height_mm, 60.0)
    d = max(s.depth_mm, 25.0)
    t = max(s.thickness_mm, 3.0)
    # Pin diameter heuristic (the actual pin's diameter is checked
    # later by _pin_axis_for, but we don't want to over-couple here).
    pin_d = max(s.diameter_mm or 6.0, 4.0)
    # Choose hole_offset_x to place barrel inside the extension length.
    hole_x = min(d * 0.6, max(d * 0.45, 18.0))
    barrel_d = min(max(pin_d * 2.2, t * 2.5), w * 0.45, h * 0.35)
    if barrel_d <= pin_d:
        barrel_d = pin_d * 1.6
    bracket = HingeBracketC(
        mounting_wall_width=w,
        mounting_wall_height=h,
        mounting_wall_thickness=t,
        extension_length=d,
        extension_width=w * 0.5,
        extension_thickness=t,
        extension_gap=h * 0.5,
        pin_diameter=pin_d,
        hole_offset_x=hole_x,
        barrel_diameter=barrel_d,
    )
    return bracket.build()


_SHAPE_BUILDERS = {
    "plate": _build_plate,
    "bracket": _build_bracket,
    "hinge_leaf": _build_hinge_leaf,
    "knuckle": _build_knuckle,
    "pin": _build_pin,
    "shaft": _build_pin,
    "washer": _build_washer,
    "boss": _build_boss,
    "spring": _build_spring,
    "fastener": _build_fastener,
    "link": _build_link,
    "housing": _build_bracket,
    "slot": _build_slot,
    "hole": _build_hole_marker,
    "tab": _build_plate,
    "flange": _build_plate,
    "other": _build_other,
}


# ---------------------------------------------------------------------------
# Constraint application
# ---------------------------------------------------------------------------


def _apply_constraints(
    shapes: dict[str, ComponentShape],
) -> dict[str, tuple[float, float, float]]:
    """Compute per-component poses (mm, world frame) by applying
    constraints on top of the VLM-suggested poses.

    Greedy single pass: for each component with ``coaxial_with`` /
    ``passes_through``, snap the dependent component to share the
    target's XY (so the pin actually goes through the hole). For
    ``nested_in``, snap to the target's XY centre.
    """
    poses: dict[str, tuple[float, float, float]] = {
        cid: tuple(s.pose_xyz_mm) for cid, s in shapes.items()  # type: ignore[misc]
    }

    def _xy(cid: str) -> tuple[float, float]:
        x, y, _ = poses[cid]
        return (x, y)

    # First pass: rotational alignment for pins / shafts that should be
    # coaxial with vertical hinge knuckles. Set their rotation_deg to
    # (0, 0, 0) and main_axis to Z so the cylinder stands vertical.
    for cid, s in shapes.items():
        if s.shape_family in {"pin", "shaft"} and any(
            c["kind"] in ("coaxial_with", "passes_through") for c in s.constraints
        ):
            s.rotation_deg = (0.0, 0.0, 0.0)
            s.main_axis = "Z"

    # Second pass: snap XY for coaxial/passes-through pairs.
    # Process components in order of constraint count (fewer first) so
    # primary load-bearing parts (the pin) drag dependents along.
    for cid, s in shapes.items():
        for c in s.constraints:
            if c["kind"] not in ("coaxial_with", "passes_through"):
                continue
            tgt = c["target"]
            if tgt not in poses:
                continue
            # If THIS component is the pin/shaft, it stays put and the
            # target should snap to it. If THIS is a knuckle/hole, snap
            # to the target (which may be the pin).
            if s.shape_family in {"pin", "shaft"}:
                tx, ty, tz = poses[tgt]
                sx, sy, _ = poses[cid]
                poses[tgt] = (sx, sy, tz)
            else:
                tx, ty, _ = poses[tgt]
                _, _, sz = poses[cid]
                poses[cid] = (tx, ty, sz)

    # Third pass: nested_in / above / below
    for cid, s in shapes.items():
        for c in s.constraints:
            if c["kind"] == "nested_in":
                tgt = c["target"]
                if tgt in poses:
                    tx, ty, tz = poses[tgt]
                    _, _, sz = poses[cid]
                    poses[cid] = (tx, ty, sz)
            elif c["kind"] == "above":
                tgt = c["target"]
                if tgt in poses and tgt in shapes:
                    tx, ty, tz = poses[tgt]
                    target_h = max(
                        shapes[tgt].depth_mm, shapes[tgt].thickness_mm, 5.0
                    )
                    own_h = max(s.depth_mm, s.thickness_mm, 5.0)
                    poses[cid] = (tx, ty, tz + target_h / 2.0 + own_h / 2.0)
            elif c["kind"] == "below":
                tgt = c["target"]
                if tgt in poses and tgt in shapes:
                    tx, ty, tz = poses[tgt]
                    target_h = max(
                        shapes[tgt].depth_mm, shapes[tgt].thickness_mm, 5.0
                    )
                    own_h = max(s.depth_mm, s.thickness_mm, 5.0)
                    poses[cid] = (tx, ty, tz - target_h / 2.0 - own_h / 2.0)

    return poses


# ---------------------------------------------------------------------------
# Solid construction + pose application
# ---------------------------------------------------------------------------


def _orient_for_axis(part: bd.Part, axis: str) -> bd.Part:
    """Rotate a part whose natural axis is +Z onto a different world axis."""
    a = (axis or "Z").upper()
    if a == "Z":
        return part
    if a == "X":
        return part.rotate(bd.Axis.Y, 90)
    if a == "Y":
        return part.rotate(bd.Axis.X, 90)
    return part


# V11-18: which shape families are "drillable" (we'll cut a pin-axis
# hole in their solid when the constraint graph says they share a pin
# axis with a pin/shaft component).
_DRILLABLE_FAMILIES = frozenset(
    {"plate", "bracket", "tab", "flange", "link", "housing", "hinge_leaf"}
)


def _pin_axis_for(
    cid: str,
    shapes_by_id: dict[str, ComponentShape],
    poses: dict[str, tuple[float, float, float]],
) -> tuple[float, float, float, float] | None:
    """Return ``(x, y, axis_z_low, axis_z_high, pin_diameter)`` for the
    pin axis this component shares, or None.

    A part shares a pin axis if it has a ``passes_through`` /
    ``coaxial_with`` constraint to a pin/shaft component (or a
    transitive: a hole that itself passes_through a pin).
    """
    s = shapes_by_id.get(cid)
    if s is None:
        return None
    pin_id: str | None = None
    pin_diameter: float = 0.0
    seen: set[str] = set()
    queue: list[str] = [cid]
    while queue:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        cs = shapes_by_id.get(cur)
        if cs is None:
            continue
        if cs.shape_family in {"pin", "shaft"} and cur != cid:
            pin_id = cur
            pin_diameter = cs.diameter_mm or cs.thickness_mm or 4.0
            break
        for c in cs.constraints:
            if c["kind"] in ("passes_through", "coaxial_with"):
                tgt = c["target"]
                if tgt not in seen:
                    queue.append(tgt)
    if pin_id is None:
        return None
    px, py, _pz = poses[pin_id]
    # Pin diameter heuristic: shape_inference gives `diameter_mm`; if
    # missing, infer from `thickness_mm` or default to 4 mm.
    return (
        px,
        py,
        -1e6,
        1e6,
        max(pin_diameter, 2.0),
    )


def _auto_drill_part(
    solid: bd.Part,
    cid: str,
    pose: tuple[float, float, float],
    shapes_by_id: dict[str, ComponentShape],
    poses: dict[str, tuple[float, float, float]],
) -> tuple[bd.Part, bool]:
    """If the part should have a pin-axis hole, drill it. Returns
    (possibly-modified solid, drilled-flag)."""
    s = shapes_by_id.get(cid)
    if s is None or s.shape_family not in _DRILLABLE_FAMILIES:
        return solid, False
    axis_info = _pin_axis_for(cid, shapes_by_id, poses)
    if axis_info is None:
        return solid, False
    px, py, _zlo, _zhi, pin_d = axis_info
    # The drill happens AFTER pose translation, so we need the hole's
    # XY in the part's local frame, which is the world XY (px, py)
    # minus the part's own (pose.x, pose.y).
    local_x = px - pose[0]
    local_y = py - pose[1]
    # Don't drill if the pin axis sits outside this part's bbox.
    bb = solid.bounding_box()
    margin = 1.0
    if not (
        bb.min.X - margin <= local_x <= bb.max.X + margin
        and bb.min.Y - margin <= local_y <= bb.max.Y + margin
    ):
        return solid, False
    # Drill a vertical bore through the part.
    z_extent = max(bb.max.Z - bb.min.Z, 5.0)
    bore_radius = pin_d / 2.0 * 1.05
    if bore_radius * 2 >= min(bb.size.X, bb.size.Y) * 0.9:
        # The bore would consume the whole part — skip.
        return solid, False
    try:
        bore = bd.Cylinder(bore_radius, z_extent * 1.5).translate(
            (local_x, local_y, (bb.min.Z + bb.max.Z) / 2.0)
        )
        return solid - bore, True
    except Exception:  # noqa: BLE001
        return solid, False


def build_assembly(
    inference: ShapeInferenceSet,
) -> tuple[bd.Compound, list[str], list[SolverDiagnostics]]:
    """Build a flat assembly from a ShapeInferenceSet.

    Returns (compound, ordered_ids, diagnostics).
    """
    shapes_by_id = {s.component_id: s for s in inference.shapes}
    poses = _apply_constraints(shapes_by_id)

    children: list[bd.Part | bd.Compound] = []
    ordered: list[str] = []
    diagnostics: list[SolverDiagnostics] = []

    for cid, s in shapes_by_id.items():
        # V11-18 auto-upgrade: a bracket / link / housing whose
        # constraint list says it passes_through or is coaxial_with a
        # pin/shaft is mechanically a HINGE bracket — rebuild it via
        # HingeBracketC so the bracket has a real cylindrical barrel
        # at the pin axis (not just a hollow U-channel that the bore
        # subtraction misses).
        builder = _SHAPE_BUILDERS.get(s.shape_family, _build_other)
        if s.shape_family in {"bracket", "link", "housing"}:
            shares_pin = _pin_axis_for(cid, shapes_by_id, poses)
            if shares_pin is not None:
                builder = _build_bracket_c_from_shape  # type: ignore[assignment]
        try:
            solid = builder(s)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Shape build failed for %s (%s): %s", cid, s.shape_family, exc)
            solid = _build_other(s)
        if solid is None:
            continue
        # Validate non-degenerate.
        try:
            bb = solid.bounding_box()
            sz = (bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z)
            if min(sz) < 0.5:
                solid = _build_other(s)
        except Exception:  # noqa: BLE001
            solid = _build_other(s)

        # Apply main-axis orientation for pin/shaft.
        if s.shape_family in {"pin", "shaft"}:
            solid = _orient_for_axis(solid, s.main_axis)

        # Apply rotation_deg.
        rx, ry, rz = s.rotation_deg
        if abs(rx) > 1e-6:
            solid = solid.rotate(bd.Axis.X, rx)
        if abs(ry) > 1e-6:
            solid = solid.rotate(bd.Axis.Y, ry)
        if abs(rz) > 1e-6:
            solid = solid.rotate(bd.Axis.Z, rz)

        # V11-18 auto-drill: if this part is a plate / bracket / etc.
        # that shares a pin axis with a pin/shaft component (per the
        # constraint graph), drill a real cylindrical bore at the pin
        # axis. This is the single biggest source of curved faces in
        # the assembly.
        x, y, z = poses[cid]
        drilled = False
        try:
            solid, drilled = _auto_drill_part(
                solid, cid, (x, y, z), shapes_by_id, poses
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto-drill failed on %s: %s", cid, exc)
            drilled = False

        # Apply translated pose.
        solid = solid.translate((x, y, z))
        solid.label = cid
        children.append(solid)
        ordered.append(cid)

        bb = solid.bounding_box()
        sz = (
            bb.max.X - bb.min.X,
            bb.max.Y - bb.min.Y,
            bb.max.Z - bb.min.Z,
        )
        constraint_descs = [f"{c['kind']}:{c['target']}" for c in s.constraints]
        if drilled:
            constraint_descs.append("auto_drilled:pin_axis")
        diagnostics.append(
            SolverDiagnostics(
                component_id=cid,
                shape_family=s.shape_family,
                bbox_mm=sz,
                pose_applied_mm=(x, y, z),
                constraints_applied=constraint_descs,
                fell_back_to_box=(s.shape_family == "other"),
                notes=s.notes[:120],
            )
        )

    if not children:
        raise RuntimeError("Solver produced 0 components")
    return bd.Compound(label="assembly", children=children), ordered, diagnostics


__all__ = [
    "SolverDiagnostics",
    "build_assembly",
]
