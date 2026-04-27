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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shape dispatch
# ---------------------------------------------------------------------------


def _primitive_for(component: Component) -> bd.Shape:
    """Return a single build123d Shape representing the component.

    Phase-3 uses a coarse classifier:

    * connection-category components → small sphere or short cylinder
    * structural rod/link → cylinder along X
    * structural plate/block/frame/housing → box with sensible proportions
    * functional sensor/actuator/end_effector → sphere/capsule-ish

    Unknown kinds fall back to a labelled cube.
    """
    kind = (component.kind or "").lower()
    category = component.category

    if category == "connection":
        if kind in {"revolute_joint", "spherical_joint"}:
            return bd.Cylinder(8, 14)
        if kind == "prismatic_joint":
            return bd.Box(20, 12, 12)
        if kind == "fastener":
            return bd.Cylinder(3, 12)
        if kind == "fixed_joint":
            return bd.Sphere(6)
        return bd.Sphere(6)

    if category == "structural":
        if kind in {"rod", "shaft", "link"}:
            return bd.Cylinder(6, 50)
        if kind in {"plate"}:
            return bd.Box(60, 60, 4)
        # block / frame / housing / shell / unknown
        return bd.Box(40, 40, 20)

    if category == "functional":
        if kind == "sensor":
            return bd.Sphere(5)
        if kind == "actuator":
            return bd.Cylinder(8, 24)
        if kind == "end_effector":
            return bd.Box(20, 30, 14)
        if kind == "controller":
            return bd.Box(30, 24, 10)
        return bd.Sphere(8)

    # Unknown category — labelled cube.
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


def _layout_along_x(components: list[Component], spacing: float = 60.0) -> dict[str, tuple[float, float, float]]:
    """Place each component at (i * spacing, 0, 0)."""
    return {comp.id: (i * spacing, 0.0, 0.0) for i, comp in enumerate(components)}


# ---------------------------------------------------------------------------
# In-process build
# ---------------------------------------------------------------------------


def build_compound(ir: ClaimIR) -> tuple[bd.Compound, list[str]]:
    """Build a build123d Compound for the IR. Returns (compound, ordered_ids).

    ``ordered_ids`` is the list of component IDs in the order their primitives
    were added to the Compound — needed for GLB node renaming.
    """
    components = _ordered_components(ir)
    positions = _layout_along_x(components)

    children: list[bd.Shape] = []
    ordered_ids: list[str] = []
    for comp in components:
        primitive = _primitive_for(comp)
        x, y, z = positions[comp.id]
        placed = primitive.translate((x, y, z))
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
