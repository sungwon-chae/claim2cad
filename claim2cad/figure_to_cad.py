"""Figure-driven CAD generator (v1.1).

Given a patent figure plus the existing claim IR, ask Claude-4.7 vision
which library component each claim component should map to, in what
dimensions, with what features, and at what position. Then compose the
assembly from library parts (with a primitive-shape fallback for parts
that the library does not cover yet).

The VLM call is a single round-trip per example: this is the cheap path.
The expensive iterative refinement is V11-4's job.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import build123d as bd

from claim2cad.components import library
from claim2cad.components.base import Component, ComponentBuildError
from claim2cad.glb_naming import rename_glb_root_children
from claim2cad.ir_schema import ClaimIR
from claim2cad.llm_vision import vision_completion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class ComponentSpec:
    """One row of the FigureSpec — what to build for one claim component."""

    component_id: str
    library_part: str | None  # registered library name, or None for fallback
    params: dict[str, Any] = field(default_factory=dict)
    position_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    features: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class FigureSpec:
    """Full per-figure recipe: how to build every claim component."""

    patent_id: str
    figure_id: str
    components: list[ComponentSpec] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "patent_id": self.patent_id,
            "figure_id": self.figure_id,
            "components": [asdict(c) for c in self.components],
            "raw": self.raw,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FigureSpec":
        comps = [ComponentSpec(**c) for c in d.get("components", [])]
        return cls(
            patent_id=d.get("patent_id", ""),
            figure_id=d.get("figure_id", ""),
            components=comps,
            raw=d.get("raw", {}),
        )


# ---------------------------------------------------------------------------
# Figure analysis (VLM)
# ---------------------------------------------------------------------------


_REGISTERED_NAMES_DOC = (
    "Registered library parts (use the EXACT name in `library_part`):\n"
    "  - plate, leaf, rod, l_bracket, u_bracket, pin\n"
    "  - leaf_hinge, revolute_joint, prismatic_joint\n"
    "  - spur_gear, ball_bearing, helical_spring\n"
    "If a component is best built as a leaf hinge (two leaves + pin), use "
    "`leaf_hinge` as a single library_part for the *whole* hinge assembly "
    "and leave its child components (the leaves and the pin) with "
    "`library_part: null` and `notes: \"covered by leaf_hinge\"`. If no "
    "library part fits, set `library_part: null`."
)

_ANALYZE_SYSTEM_PROMPT = (
    "You are a senior mechanical CAD engineer translating patent drawings "
    "into a parameterised build123d assembly. You will be given the figure "
    "and the list of components from the claim IR. For each component, "
    "decide which library part to use, estimate dimensions in millimetres "
    "from the figure, and place it relative to the assembly origin. Be "
    "decisive. Always return valid JSON."
)

_ANALYZE_USER_TEMPLATE = """Patent: {patent_id} — {title}

Figure: {figure_id}.

{registered_doc}

Claim components (id, label, kind, category, figure_number, figure bbox):
{component_lines}

Output JSON shape — return EXACTLY this structure (no extra keys):
{{
  "components": [
    {{
      "component_id": "<must match one of the IDs above>",
      "library_part": "<one of the registered names, or null>",
      "params": {{"<param_name>": <number_or_string>, ...}},
      "position_mm": [<x>, <y>, <z>],
      "rotation_deg": [<rx>, <ry>, <rz>],
      "features": ["<short feature description>", ...],
      "notes": "<optional 1-line note>"
    }}
  ]
}}

Rules:
- Cover EVERY component in the list above. Do not invent extra components.
- Pick a single overall scale: the longest visible dimension in the figure
  is roughly 200-400 mm. Stay consistent.
- For LeafHinge, prefer ONE entry with library_part="leaf_hinge" covering
  the whole hinge; mark the redundant pin/leaf components with
  library_part:null and a note.
- Use mm consistently; no unit suffixes.
- If unsure of an exact dimension, give a plausible round number (e.g. 6,
  10, 50, 80, 120).
"""


def _component_lines(ir: ClaimIR) -> str:
    rows: list[str] = []
    for c in ir.components:
        bbox = ""
        for ref in c.figure_references or []:
            if ref.figure_id and ref.bbox:
                bbox = f" fig_bbox={tuple(round(v, 2) for v in ref.bbox)}"
                break
        rows.append(
            f"  - {c.id} | label={c.label!r} | kind={c.kind!r} | category={c.category}"
            f" | fig#{c.figure_number or '-'}{bbox}"
        )
    return "\n".join(rows) if rows else "  (no components in IR)"


def analyze_figure(
    figure_path: Path,
    ir: ClaimIR,
    *,
    figure_id: str = "figure_1",
    task_type: str = "v11_figure_to_spec",
) -> FigureSpec:
    """Send the figure + IR to Opus 4.7 and parse the response into a FigureSpec."""
    user_prompt = _ANALYZE_USER_TEMPLATE.format(
        patent_id=ir.title or "(untitled patent)",
        title=ir.title or "",
        figure_id=figure_id,
        registered_doc=_REGISTERED_NAMES_DOC,
        component_lines=_component_lines(ir),
    )
    raw = vision_completion(
        image_path=figure_path,
        system_prompt=_ANALYZE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        task_type=task_type,
    )
    spec = _parse_figure_spec(raw, ir, figure_id=figure_id)
    return spec


def _parse_figure_spec(raw: dict[str, Any], ir: ClaimIR, *, figure_id: str) -> FigureSpec:
    components_raw = raw.get("components") or []
    component_specs: list[ComponentSpec] = []
    valid_ids = {c.id for c in ir.components}
    for row in components_raw:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("component_id", "")).strip()
        if cid not in valid_ids:
            logger.debug("Skipping unknown component_id %r from VLM response", cid)
            continue
        try:
            pos = tuple(float(v) for v in row.get("position_mm", (0, 0, 0)))[:3]
            if len(pos) < 3:
                pos = pos + (0.0,) * (3 - len(pos))
        except (TypeError, ValueError):
            pos = (0.0, 0.0, 0.0)
        try:
            rot = tuple(float(v) for v in row.get("rotation_deg", (0, 0, 0)))[:3]
            if len(rot) < 3:
                rot = rot + (0.0,) * (3 - len(rot))
        except (TypeError, ValueError):
            rot = (0.0, 0.0, 0.0)
        spec = ComponentSpec(
            component_id=cid,
            library_part=row.get("library_part") or None,
            params=row.get("params") if isinstance(row.get("params"), dict) else {},
            position_mm=pos,  # type: ignore[arg-type]
            rotation_deg=rot,  # type: ignore[arg-type]
            features=[str(f) for f in (row.get("features") or []) if f],
            notes=str(row.get("notes", "")),
        )
        component_specs.append(spec)
    # Add stubs for any IR components the VLM forgot — keep the IR contract.
    seen_ids = {s.component_id for s in component_specs}
    for c in ir.components:
        if c.id not in seen_ids:
            component_specs.append(
                ComponentSpec(
                    component_id=c.id,
                    library_part=None,
                    notes="missing from VLM response — fallback to primitive",
                )
            )
    return FigureSpec(
        patent_id=ir.title or "",
        figure_id=figure_id,
        components=component_specs,
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Assembly construction
# ---------------------------------------------------------------------------


def _fallback_primitive(comp_id: str, kind: str, category: str) -> bd.Part:
    """Cheap primitive when the library has no match. Mirrors v1.0's
    primitive dispatch to keep things deterministic."""
    kind = (kind or "").lower()
    category = (category or "").lower()
    if category == "connection" or "pin" in kind or "fastener" in kind:
        return bd.Cylinder(3.0, 14.0)
    if "rod" in kind or "shaft" in kind or "link" in kind:
        return bd.Cylinder(6.0, 50.0)
    if "plate" in kind or "wall" in kind:
        return bd.Box(60, 40, 4)
    if "spring" in kind:
        return bd.Cylinder(7.0, 30.0)
    if "spherical" in kind or "ball" in kind:
        return bd.Sphere(8.0)
    if category == "functional":
        return bd.Sphere(8.0)
    return bd.Box(20, 20, 20)


def _instantiate_component(
    spec: ComponentSpec,
    ir_component_kind: str,
    ir_component_category: str,
) -> bd.Part | bd.Compound:
    """Resolve ``spec`` to a build123d solid. Library lookup first; then
    primitive fallback. Returns the solid unmoved, with no label set."""
    if spec.library_part:
        entry = library.get(spec.library_part)
        if entry is None:
            entry = library.lookup(
                spec.library_part,
                hints={"params": spec.params},
            )
        if entry is not None:
            try:
                comp = library.instantiate(
                    entry.name,
                    params=spec.params,
                    hints={"params": spec.params},
                )
                if comp is not None:
                    return comp.build()
            except ComponentBuildError as exc:
                logger.warning(
                    "Library factory %s rejected for %s: %s — falling back",
                    entry.name,
                    spec.component_id,
                    exc,
                )
    # Fallback path.
    return _fallback_primitive(spec.component_id, ir_component_kind, ir_component_category)


def _apply_pose(solid: bd.Part | bd.Compound, spec: ComponentSpec) -> bd.Part | bd.Compound:
    rx, ry, rz = spec.rotation_deg
    if abs(rx) > 1e-6:
        solid = solid.rotate(bd.Axis.X, rx)
    if abs(ry) > 1e-6:
        solid = solid.rotate(bd.Axis.Y, ry)
    if abs(rz) > 1e-6:
        solid = solid.rotate(bd.Axis.Z, rz)
    return solid.translate(spec.position_mm)


def generate_assembly(
    figure_spec: FigureSpec,
    ir: ClaimIR,
    *,
    components_dir: Path | None = None,
    skip_redundant_when_covered: bool = True,
) -> tuple[bd.Compound, list[str]]:
    """Build a ``Compound`` from ``figure_spec``. Returns (compound, ordered_ids).

    If ``components_dir`` is provided, each individual component is also
    written as a STEP file under that directory.
    """
    ir_kinds = {c.id: (c.kind or "", c.category or "") for c in ir.components}
    spec_by_id = {s.component_id: s for s in figure_spec.components}

    # Determine which IR components are already represented by a "compound"
    # library entry (e.g. leaf_hinge covers leaves + pin). The VLM is asked
    # to mark redundant ones with library_part=null + a note containing
    # "covered by ...". We respect that.
    covered_ids: set[str] = set()
    if skip_redundant_when_covered:
        for s in figure_spec.components:
            note_lower = (s.notes or "").lower()
            if s.library_part is None and "covered by" in note_lower:
                covered_ids.add(s.component_id)

    children: list[bd.Part | bd.Compound] = []
    ordered_ids: list[str] = []
    for c in ir.components:
        if c.id in covered_ids:
            logger.info("Skipping %s (marked as covered by another part)", c.id)
            continue
        spec = spec_by_id.get(c.id) or ComponentSpec(
            component_id=c.id,
            library_part=None,
            notes="missing-from-spec",
        )
        kind, category = ir_kinds[c.id]
        try:
            solid = _instantiate_component(spec, kind, category)
        except Exception as exc:  # noqa: BLE001 — last-resort fallback
            logger.warning("Build failed for %s: %s — using primitive", c.id, exc)
            solid = _fallback_primitive(c.id, kind, category)
        solid = _apply_pose(solid, spec)
        solid.label = c.id
        children.append(solid)
        ordered_ids.append(c.id)
        if components_dir is not None:
            try:
                components_dir.mkdir(parents=True, exist_ok=True)
                bd.export_step(solid, str(components_dir / f"{c.id}.step"))
            except Exception as exc:  # noqa: BLE001 — per-component export is best effort
                logger.warning("Could not export %s: %s", c.id, exc)
    if not children:
        raise RuntimeError("generate_assembly produced 0 components")
    compound = bd.Compound(label="assembly", children=children)
    return compound, ordered_ids


# ---------------------------------------------------------------------------
# Driver: example_dir → STEP/GLB on disk
# ---------------------------------------------------------------------------


def run_generator(
    example_dir: Path | str,
    *,
    figure_filename: str = "figures/figure_1.png",
    ir_filename: str = "claim_ir.json",
    out_step: str = "model_v1.1.step",
    out_glb: str = "model_v1.1.glb",
    spec_out: str = "figure_spec.json",
    use_cached_spec: bool = False,
) -> dict[str, Path]:
    """Main entry: run the figure-to-CAD pipeline on a single example."""
    example_dir = Path(example_dir)
    figure_path = example_dir / figure_filename
    ir_path = example_dir / ir_filename
    if not figure_path.exists():
        raise FileNotFoundError(f"Figure not found: {figure_path}")
    if not ir_path.exists():
        raise FileNotFoundError(f"claim_ir.json not found: {ir_path}")

    ir = ClaimIR.model_validate_json(ir_path.read_text("utf-8"))

    spec_path = example_dir / spec_out
    figure_spec: FigureSpec
    if use_cached_spec and spec_path.exists():
        logger.info("Using cached figure spec at %s", spec_path)
        figure_spec = FigureSpec.from_dict(json.loads(spec_path.read_text("utf-8")))
    else:
        logger.info("Calling VLM to analyse %s", figure_path.name)
        figure_spec = analyze_figure(figure_path, ir, figure_id=figure_path.stem)
        spec_path.write_text(json.dumps(figure_spec.to_dict(), indent=2), encoding="utf-8")
        logger.info("Wrote figure spec to %s", spec_path)

    components_dir = example_dir / "components"
    compound, ordered_ids = generate_assembly(figure_spec, ir, components_dir=components_dir)

    step_path = example_dir / out_step
    glb_path = example_dir / out_glb
    bd.export_step(compound, str(step_path))
    bd.export_gltf(compound, str(glb_path), binary=True)
    try:
        rename_glb_root_children(glb_path, ordered_ids)
    except Exception as exc:  # noqa: BLE001 — naming is best-effort
        logger.warning("GLB rename failed: %s", exc)

    logger.info("Wrote %s and %s with %d components", step_path, glb_path, len(ordered_ids))
    return {
        "spec": spec_path,
        "step": step_path,
        "glb": glb_path,
        "components_dir": components_dir,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run the v1.1 figure-driven CAD generator on an example.")
    p.add_argument("example_dir", type=Path)
    p.add_argument("--figure", default="figures/figure_1.png")
    p.add_argument("--ir", default="claim_ir.json")
    p.add_argument("--out-step", default="model_v1.1.step")
    p.add_argument("--out-glb", default="model_v1.1.glb")
    p.add_argument(
        "--use-cached-spec",
        action="store_true",
        help="Skip the VLM call and use the existing figure_spec.json.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("CLAIM2CAD_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)-22s :: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    args = _build_argparser().parse_args(argv)
    out = run_generator(
        args.example_dir,
        figure_filename=args.figure,
        ir_filename=args.ir,
        out_step=args.out_step,
        out_glb=args.out_glb,
        use_cached_spec=args.use_cached_spec,
    )
    print(json.dumps({k: str(v) for k, v in out.items()}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
