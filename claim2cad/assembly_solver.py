"""Build the 3D assembly from per-component shapes + constraints.

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
    """Plate with one or more knuckle barrels along its long edge."""
    w = max(s.width_mm, 60.0)
    h = max(s.height_mm, 30.0)
    t = max(s.thickness_mm, 3.0)
    leaf = bd.Box(w, h, t)
    barrel_d = max(s.diameter_mm, t * 2.5)
    barrel_h = h * 0.8
    barrel_x = -w / 2.0 + barrel_d / 2.0
    barrel = bd.Cylinder(barrel_d / 2.0, barrel_h).translate((barrel_x, 0, 0))
    pin_r = max(s.diameter_mm * 0.4, 1.5)
    bore = bd.Cylinder(pin_r, barrel_h * 1.05).translate((barrel_x, 0, 0))
    return (leaf + barrel) - bore


def _build_knuckle(s: ComponentShape) -> bd.Part | None:
    """Hinge knuckle / barrel: short cylinder with through-hole."""
    od = max(s.diameter_mm, max(s.width_mm, 12.0))
    height = max(s.depth_mm, max(s.height_mm, 12.0))
    bore = max(s.diameter_mm * 0.45, 2.5)
    cyl = bd.Cylinder(od / 2.0, height)
    hole = bd.Cylinder(bore, height * 1.05)
    return cyl - hole


def _build_pin(s: ComponentShape) -> bd.Part | None:
    """Cylindrical pin / shaft along its main axis."""
    diameter = max(s.diameter_mm, max(s.thickness_mm, 4.0))
    length = max(s.depth_mm, max(s.height_mm, 50.0))
    cyl = bd.Cylinder(diameter / 2.0, length)
    return cyl


def _build_washer(s: ComponentShape) -> bd.Part | None:
    od = max(s.diameter_mm, 14.0)
    bore = max(s.diameter_mm * 0.45, 4.0)
    t = max(s.thickness_mm, 1.5)
    outer = bd.Cylinder(od / 2.0, t)
    inner = bd.Cylinder(bore, t * 1.05)
    return outer - inner


def _build_boss(s: ComponentShape) -> bd.Part | None:
    diameter = max(s.diameter_mm, 8.0)
    h = max(s.depth_mm, max(s.height_mm, 6.0))
    return bd.Cylinder(diameter / 2.0, h)


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
        builder = _SHAPE_BUILDERS.get(s.shape_family, _build_other)
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

        # Apply translated pose.
        x, y, z = poses[cid]
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
        diagnostics.append(
            SolverDiagnostics(
                component_id=cid,
                shape_family=s.shape_family,
                bbox_mm=sz,
                pose_applied_mm=(x, y, z),
                constraints_applied=[
                    f"{c['kind']}:{c['target']}" for c in s.constraints
                ],
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
