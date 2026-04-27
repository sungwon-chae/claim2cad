"""IR → build123d source synthesis (Phase 3 minimal version).

Given a :class:`ClaimIR`, this module:

1. Synthesizes a ``generator.py`` whose ``gen_step()`` returns the standard
   build123d envelope used by the upstream ``gen_step_part`` skill (see
   ``docs/ARCHITECTURE_NOTES.md`` section 4).
2. Executes that ``gen_step()`` in-process to produce ``model.step`` and
   ``model.glb``, and post-processes the GLB so each component name becomes
   the GLB node name.

The Phase-3 shape dispatch is deliberately crude: every component becomes one
of {Box, Cylinder, Sphere}, laid out in a line along the X axis with a
fixed spacing. Phase 5 replaces the dispatch with type-aware shapes and a
relation-driven layout.
"""
from __future__ import annotations

import logging
from pathlib import Path

import build123d as bd

from claim2cad.glb_naming import rename_glb_root_children
from claim2cad.ir_schema import ClaimIR, Component
from claim2cad.layout import DEFAULT_SPACING, Placement, layout_components

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shape dispatch
# ---------------------------------------------------------------------------


_AXIS_ROTATIONS = {
    0: (0.0, 90.0, 0.0),  # cylinder along X
    1: (90.0, 0.0, 0.0),  # cylinder along Y
    2: (0.0, 0.0, 0.0),  # cylinder along Z (default)
}


def _rotated_cylinder(radius: float, height: float, axis_index: int) -> bd.Shape:
    rx, ry, rz = _AXIS_ROTATIONS[axis_index % 3]
    return bd.Cylinder(radius, height, rotation=(rx, ry, rz))


def _primitive_for(component: Component, axis_index: int = 2) -> bd.Shape:
    """Return a build123d Shape representing the component, oriented to
    match its primary axis."""
    kind = (component.kind or "").lower()
    category = component.category

    if category == "connection":
        if kind == "revolute_joint":
            # Joint axis is *perpendicular* to the link axis it serves.
            joint_axis = (axis_index + 1) % 3
            return _rotated_cylinder(8, 18, joint_axis)
        if kind == "spherical_joint":
            return bd.Sphere(9)
        if kind == "prismatic_joint":
            return bd.Box(28, 14, 14)
        if kind == "fastener":
            return _rotated_cylinder(3, 14, axis_index)
        if kind == "fixed_joint":
            return bd.Box(14, 14, 14)
        return bd.Sphere(7)

    if category == "structural":
        if kind in {"rod", "shaft", "link"}:
            return _rotated_cylinder(6, 50, axis_index)
        if kind == "plate":
            return bd.Box(60, 60, 4)
        if kind == "shell":
            return bd.Box(50, 50, 8)
        if kind == "frame":
            return bd.Box(80, 80, 16)
        if kind == "housing":
            return bd.Box(60, 50, 30)
        return bd.Box(40, 40, 20)  # block / unknown

    if category == "functional":
        if kind == "sensor":
            return bd.Sphere(6)
        if kind == "actuator":
            return _rotated_cylinder(10, 30, axis_index)
        if kind == "end_effector":
            # A wedge-ish gripper silhouette.
            outer = bd.Box(22, 32, 14)
            slot = bd.Box(18, 6, 14).translate((4, 0, 0))
            return outer - slot
        if kind == "controller":
            return bd.Box(30, 24, 10)
        return bd.Sphere(8)

    return bd.Box(20, 20, 20)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def _ordered_components(ir: ClaimIR) -> list[Component]:
    """Stable component order for layout and naming.

    Sort by (claim_id, char_start, id) so the layout is deterministic across
    runs and matches the order a reader would encounter the components in
    the claim text.
    """
    return sorted(
        ir.components,
        key=lambda c: (c.source_span.claim_id, c.source_span.char_start, c.id),
    )


# ---------------------------------------------------------------------------
# In-process build
# ---------------------------------------------------------------------------


def build_compound(ir: ClaimIR) -> tuple[bd.Compound, list[str]]:
    """Build a build123d Compound for the IR. Returns (compound, ordered_ids).

    ``ordered_ids`` is the list of component IDs in the order their primitives
    were added to the Compound — needed for GLB node renaming.

    Layout is graph-driven (see :mod:`claim2cad.layout`); components without
    incoming edges are placed in a tail row.
    """
    ordered = _ordered_components(ir)
    if not ir.relations:
        # No relations → fall back to deterministic line-along-X.
        placements = {
            c.id: Placement(component_id=c.id, position=(i * DEFAULT_SPACING, 0.0, 0.0), axis_index=0)
            for i, c in enumerate(ordered)
        }
    else:
        placements = layout_components(ir)

    children: list[bd.Shape] = []
    ordered_ids: list[str] = []
    for comp in ordered:
        placement = placements.get(
            comp.id,
            Placement(component_id=comp.id, position=(0.0, 0.0, 0.0), axis_index=0),
        )
        primitive = _primitive_for(comp, axis_index=placement.axis_index)
        placed = primitive.translate(placement.position)
        placed.label = comp.id
        children.append(placed)
        ordered_ids.append(comp.id)

    root = bd.Compound(label=ir.title or "claim_model", children=children)
    return root, ordered_ids


def export_cad(
    ir: ClaimIR,
    out_dir: Path,
    *,
    linear_deflection: float = 0.5,
    angular_deflection: float = 0.5,
) -> dict[str, Path]:
    """Build, export, and rename. Returns the artifact paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    step_path = out_dir / "model.step"
    glb_path = out_dir / "model.glb"

    compound, ordered_ids = build_compound(ir)

    logger.info("Exporting STEP to %s", step_path)
    bd.export_step(compound, str(step_path))

    logger.info("Exporting GLB to %s", glb_path)
    ok = bd.export_gltf(
        compound,
        str(glb_path),
        binary=True,
        linear_deflection=linear_deflection,
        angular_deflection=angular_deflection,
    )
    if not ok:
        raise RuntimeError(f"Failed to export GLB: {glb_path}")

    rename_glb_root_children(glb_path, ordered_ids)
    return {"step": step_path, "glb": glb_path}


# ---------------------------------------------------------------------------
# Source-file synthesis
# ---------------------------------------------------------------------------


_GENERATOR_TEMPLATE = '''\
"""Auto-generated by claim2cad.ir_to_cad. Do not edit by hand."""
from __future__ import annotations

import sys
from pathlib import Path

import build123d as bd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from claim2cad.ir_schema import ClaimIR
from claim2cad.ir_to_cad import build_compound, export_cad


def gen_step():
    """text-to-cad-compatible envelope (see docs/ARCHITECTURE_NOTES.md §4)."""
    ir = ClaimIR.model_validate_json((HERE / "claim_ir.json").read_text("utf-8"))
    compound, _ = build_compound(ir)
    return {{"shape": compound, "step_output": "model.step"}}


def main() -> None:
    ir = ClaimIR.model_validate_json((HERE / "claim_ir.json").read_text("utf-8"))
    paths = export_cad(ir, HERE)
    for label, path in paths.items():
        print(f"Wrote {{path.name}} ({{path.stat().st_size:,}} B) [{{label}}]")


if __name__ == "__main__":
    main()
'''


def synthesize_generator(out_dir: Path, *, filename: str = "pipeline_generator.py") -> Path:
    """Write a synthesized generator next to the artifacts.

    Default filename is ``pipeline_generator.py`` so it doesn't collide with a
    hand-crafted ``generator.py`` that may already exist for an example
    (e.g. the Phase-2 golden_robot_arm). The synthesized generator is
    runnable directly: ``python pipeline_generator.py``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    generator_path = out_dir / filename
    generator_path.write_text(_GENERATOR_TEMPLATE, encoding="utf-8")
    return generator_path


__all__ = [
    "build_compound",
    "export_cad",
    "synthesize_generator",
]
