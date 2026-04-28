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
from claim2cad.figure_crops import FigureCrop, crop_all_components, crops_by_component_id
from claim2cad.glb_naming import rename_glb_root_children
from claim2cad.ir_schema import ClaimIR, Component as IRComponent
from claim2cad.llm_vision import vision_completion
from claim2cad.vlm_codegen import CodegenResult, generate_component_code

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


def _registered_names_doc() -> str:
    """Render a per-library schema block: each entry gets its name, aliases,
    description, and the **exact** param names + units the constructor
    accepts. Built dynamically so registering a new component automatically
    surfaces in the prompt."""
    lines = [
        "Registered library parts. Use the EXACT name in `library_part`,",
        "and use the EXACT param names listed below in `params` (units are mm",
        "unless the schema says otherwise). Wrong param names are silently",
        "dropped, so the part defaults to a placeholder size.",
        "",
    ]
    for entry in library.all_entries():
        aliases = f" (aliases: {', '.join(entry.aliases)})" if entry.aliases else ""
        lines.append(f"- `{entry.name}`{aliases}: {entry.description}")
        for pname, pdesc in entry.param_schema.items():
            lines.append(f"    * {pname} — {pdesc}")
        if entry.param_aliases:
            alias_pairs = [f"{k} → {v}" for k, v in entry.param_aliases.items()]
            lines.append(f"    (also accepted: {', '.join(alias_pairs)})")
    lines.extend(
        [
            "",
            "If a claim component is a *whole* assembly (e.g. a leaf hinge",
            "covers two leaves + a pin), use ONE library_part for the assembly",
            "and mark the now-redundant child components with",
            'library_part: null and notes: "covered by <library_part>".',
            "If no library part fits, set library_part: null and pass the",
            "component to the VLM-codegen fallback by including a brief",
            'features: ["build123d"] hint with what shape you have in mind.',
        ]
    )
    return "\n".join(lines)


_REGISTERED_NAMES_DOC = ""  # filled in lazily inside analyze_figure()

_ANALYZE_SYSTEM_PROMPT = (
    "You are a senior mechanical CAD engineer translating patent drawings "
    "into a parameterised build123d assembly. You will be given the figure "
    "and the list of components from the claim IR. For each component, "
    "decide which library part to use, estimate dimensions in millimetres "
    "from the figure, and place it relative to the assembly origin. Be "
    "decisive. Always return valid JSON."
)

_ANALYZE_USER_TEMPLATE = """Patent: {patent_id} — {title}

Figure: {figure_id}. The figure is a patent line drawing with numbered
callouts. Each claim component is bound to one of those numbers
(see `fig#` below) and to an approximate (x, y) position on the figure
in normalised image coordinates `fig_xy=(x, y)` where x in [0, 1] is
left-to-right and y in [0, 1] is top-to-bottom. Use those positions to
locate the component in the drawing before deciding its parameters.

{registered_doc}

Claim components — id | label | kind | category | fig# | fig_xy | parent | constraints:
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
  ],
  "scale_anchor_mm": <number — what real-world length the longest visible
                     feature on the figure represents, in mm>,
  "assembly_notes": "<2-3 sentences on how the parts fit together,
                     referencing claim language>"
}}

Rules:
- Cover EVERY component in the list above. Do not invent extra components.
- Use the param names from the schema EXACTLY. Wrong names are dropped
  silently and the part will default to a small placeholder.
- Pick a consistent scale anchored on `scale_anchor_mm`. Sub-component
  dimensions should be sensibly proportional (e.g. a leaf is shorter
  than the assembly's overall length).
- For LeafHinge, use ONE library_part="leaf_hinge" covering the whole
  hinge; mark the redundant child components (individual leaves, pin)
  with library_part:null and notes:"covered by leaf_hinge".
- For abstract IR concepts (an axis, a sub-assembly with no geometry of
  its own, a "hole" feature, a "guide surface", a "stop means" that is
  really a feature of another part, a vehicle body / housing / context
  body that is NOT the focus of the claim), set library_part:null and
  notes:"abstract; no standalone geometry".
- The CAD output should focus on the *claimed* components — the hinge,
  the linkage, the gear train, etc. — NOT contextual bodies the
  components mount to. Mark contextual bodies as abstract.
- Position components so their *spatial relationship matches the figure*:
  the pintle pin must pass through the leaf-flange holes; the U-bracket's
  open face should align with the corresponding leg.
- "thickness" for a plate is always the SMALLEST dimension (sheet
  thickness), typically 2-5 mm. NEVER set thickness > 10 mm for a plate.
- All distances in mm; no unit suffixes; no math expressions.
- Component positions should cluster near the origin — keep magnitudes
  under |100| mm. The whole assembly should fit in roughly a 200 mm cube.
- If a component's required geometry cannot be expressed by any library
  part (e.g. it has a non-standard profile visible in the figure), set
  library_part:null and notes:"codegen" — the pipeline will then ask
  a code-generation pass to write build123d for it from a figure crop.
"""


def _component_lines(ir: ClaimIR, figure_map: dict[str, Any] | None = None) -> str:
    """Render one row per claim component for the VLM prompt.

    Includes: id, label, kind, category, the patent figure number it carries,
    its approximate (x, y) on the figure (from figure_map.json or the IR
    fig_references), the parent_id (so child-of relations are obvious), and
    any wherein/constraint text the IR captured. The VLM uses figure
    numbers + positions to crop attention on the figure.
    """
    label_positions: dict[str, tuple[float, float]] = {}
    if figure_map and isinstance(figure_map.get("vlm_labels"), list):
        for lab in figure_map["vlm_labels"]:
            num = str(lab.get("number") or "").strip()
            pos = lab.get("approximate_position") or []
            if num and len(pos) >= 2:
                # If a number repeats, average the positions.
                if num in label_positions:
                    px, py = label_positions[num]
                    label_positions[num] = ((px + float(pos[0])) / 2, (py + float(pos[1])) / 2)
                else:
                    label_positions[num] = (float(pos[0]), float(pos[1]))

    rows: list[str] = []
    for c in ir.components:
        bits: list[str] = [f"id={c.id}", f"label={c.label!r}", f"kind={c.kind!r}", f"category={c.category}"]
        if c.figure_number:
            bits.append(f"fig#{c.figure_number}")
            pos = label_positions.get(str(c.figure_number))
            if pos:
                bits.append(f"fig_xy=({pos[0]:.2f},{pos[1]:.2f})")
        if c.parent_id:
            bits.append(f"parent={c.parent_id}")
        # bbox from IR's first figure reference, if any
        for ref in c.figure_references or []:
            if ref.bbox:
                bits.append(f"fig_bbox={tuple(round(v, 2) for v in ref.bbox)}")
                break
        if c.constraints:
            cs = "; ".join(c.constraints)[:160]
            bits.append(f"constraints=[{cs}]")
        rows.append("  - " + " | ".join(bits))
    return "\n".join(rows) if rows else "  (no components in IR)"


def analyze_figure(
    figure_path: Path,
    ir: ClaimIR,
    *,
    figure_id: str = "figure_1",
    task_type: str = "v11_figure_to_spec",
    figure_map: dict[str, Any] | None = None,
) -> FigureSpec:
    """Send the figure + IR to Opus 4.7 and parse the response into a FigureSpec."""
    user_prompt = _ANALYZE_USER_TEMPLATE.format(
        patent_id=ir.title or "(untitled patent)",
        title=ir.title or "",
        figure_id=figure_id,
        registered_doc=_registered_names_doc(),
        component_lines=_component_lines(ir, figure_map=figure_map),
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
    ir_component: IRComponent,
    *,
    figure_crop: FigureCrop | Path | None = None,
    code_cache_dir: Path | None = None,
    enable_codegen: bool = False,
) -> tuple[bd.Part | bd.Compound, str]:
    """Resolve ``spec`` to a build123d solid.

    Resolution order:
      1. library_part set → library.instantiate (with VLM-natural param
         aliases applied).
      2. library_part is None AND ``enable_codegen`` AND a figure_crop
         exists → ask the VLM for a build123d snippet (cached on disk
         under ``code_cache_dir``).
      3. Fallback: primitive shape based on the IR kind/category.

    Returns (solid, source_tag) where source_tag is one of
    ``"library:<name>"``, ``"codegen"``, ``"primitive"``.
    """
    kind = ir_component.kind or ""
    category = ir_component.category or ""
    cid = spec.component_id

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
                    return comp.build(), f"library:{entry.name}"
            except ComponentBuildError as exc:
                logger.warning(
                    "Library factory %s rejected for %s: %s — falling back",
                    entry.name,
                    cid,
                    exc,
                )

    # Codegen path. Triggered when:
    #   - the VLM explicitly requested it via notes:"codegen", OR
    #   - the spec has library_part=None and the component is NOT marked
    #     abstract/covered (i.e. the VLM thought it has geometry but no
    #     library entry fits).
    note_lower = (spec.notes or "").lower()
    is_abstract = "abstract" in note_lower or "covered by" in note_lower
    is_codegen_requested = "codegen" in note_lower or (
        spec.library_part is None and not is_abstract
    )
    if enable_codegen and figure_crop is not None and is_codegen_requested:
        cached_code: str | None = None
        cache_path: Path | None = None
        if code_cache_dir is not None:
            cache_path = code_cache_dir / f"{cid}.py"
            if cache_path.exists():
                try:
                    cached_code = cache_path.read_text(encoding="utf-8")
                except OSError:
                    cached_code = None
        if cached_code:
            from claim2cad.vlm_codegen import _exec_snippet, _solid_is_valid

            solid, err = _exec_snippet(cached_code)
            if err == "" and _solid_is_valid(solid):
                logger.info("Using cached codegen for %s", cid)
                return solid, "codegen-cached"
            logger.warning("Cached codegen invalid for %s (%s) — regenerating", cid, err)
        cg = generate_component_code(
            component_id=cid,
            label=ir_component.label,
            kind=kind,
            category=category,
            figure_number=ir_component.figure_number or "",
            parent_id=ir_component.parent_id,
            constraints=ir_component.constraints or [],
            features=spec.features,
            notes=spec.notes,
            position_mm=spec.position_mm,
            rotation_deg=spec.rotation_deg,
            figure_crop=figure_crop,
        )
        if cg.success and cg.solid is not None:
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(cg.code, encoding="utf-8")
            return cg.solid, "codegen"
        logger.warning(
            "Codegen failed for %s: %s — falling back to primitive", cid, cg.error
        )

    return _fallback_primitive(cid, kind, category), "primitive"


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
    figure_crops: dict[str, FigureCrop] | None = None,
    code_cache_dir: Path | None = None,
    enable_codegen: bool = False,
) -> tuple[bd.Compound, list[str], dict[str, str]]:
    """Build a ``Compound`` from ``figure_spec``.

    Returns (compound, ordered_ids, source_tags). ``source_tags`` maps
    component_id → which path produced it: ``library:<name>``,
    ``codegen``, ``codegen-cached``, ``primitive``.

    If ``components_dir`` is provided, each individual component is also
    written as a STEP file under that directory. If ``figure_crops`` and
    ``enable_codegen`` are set, components without library coverage call
    the VLM codegen path (cached under ``code_cache_dir``).
    """
    ir_components = {c.id: c for c in ir.components}
    spec_by_id = {s.component_id: s for s in figure_spec.components}

    # Components marked as covered by a parent compound (e.g. leaf_hinge
    # covers individual leaves + pin) get skipped.
    covered_ids: set[str] = set()
    if skip_redundant_when_covered:
        for s in figure_spec.components:
            note_lower = (s.notes or "").lower()
            if s.library_part is None and "covered by" in note_lower:
                covered_ids.add(s.component_id)
            # IR concepts that are pure abstractions (an axis, a sub-assembly
            # that has no own geometry) — skip rather than ship a stub box.
            if s.library_part is None and "abstract" in note_lower:
                covered_ids.add(s.component_id)

    children: list[bd.Part | bd.Compound] = []
    ordered_ids: list[str] = []
    source_tags: dict[str, str] = {}

    for c in ir.components:
        if c.id in covered_ids:
            logger.info("Skipping %s (covered/abstract)", c.id)
            continue
        spec = spec_by_id.get(c.id) or ComponentSpec(
            component_id=c.id,
            library_part=None,
            notes="missing-from-spec",
        )
        crop = (figure_crops or {}).get(c.id)
        try:
            solid, tag = _instantiate_component(
                spec,
                c,
                figure_crop=crop,
                code_cache_dir=code_cache_dir,
                enable_codegen=enable_codegen,
            )
        except Exception as exc:  # noqa: BLE001 — last-resort fallback
            logger.warning("Build failed for %s: %s — using primitive", c.id, exc)
            solid = _fallback_primitive(c.id, c.kind or "", c.category or "")
            tag = "primitive"
        solid = _apply_pose(solid, spec)
        solid.label = c.id
        children.append(solid)
        ordered_ids.append(c.id)
        source_tags[c.id] = tag
        if components_dir is not None:
            try:
                components_dir.mkdir(parents=True, exist_ok=True)
                bd.export_step(solid, str(components_dir / f"{c.id}.step"))
            except Exception as exc:  # noqa: BLE001 — per-component export is best effort
                logger.warning("Could not export %s: %s", c.id, exc)
    if not children:
        raise RuntimeError("generate_assembly produced 0 components")
    compound = bd.Compound(label="assembly", children=children)
    return compound, ordered_ids, source_tags


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
    enable_codegen: bool = True,
    crop_radius: float = 0.12,
    enable_spatial_composer: bool = True,
    multi_figure: bool = True,
    render_style: str = "line",
    patent_context: str = "",
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
    figure_map_path = example_dir / "figure_map.json"
    figure_map: dict[str, Any] | None = None
    if figure_map_path.exists():
        try:
            figure_map = json.loads(figure_map_path.read_text("utf-8"))
        except json.JSONDecodeError:
            figure_map = None
    if use_cached_spec and spec_path.exists():
        logger.info("Using cached figure spec at %s", spec_path)
        figure_spec = FigureSpec.from_dict(json.loads(spec_path.read_text("utf-8")))
    else:
        logger.info("Calling VLM to analyse %s", figure_path.name)
        figure_spec = analyze_figure(
            figure_path, ir, figure_id=figure_path.stem, figure_map=figure_map
        )
        spec_path.write_text(json.dumps(figure_spec.to_dict(), indent=2), encoding="utf-8")
        logger.info("Wrote figure spec to %s", spec_path)

    components_dir = example_dir / "components"
    code_cache_dir = example_dir / "codegen_cache"

    # Per-component figure crops (if figure_map.json is present).
    crops_dir = example_dir / "crops"
    figure_crops_dict: dict[str, FigureCrop] = {}
    if figure_map and figure_path.exists():
        try:
            crops = crop_all_components(
                figure_path,
                figure_map,
                out_dir=crops_dir,
                crop_radius=crop_radius,
            )
            figure_crops_dict = crops_by_component_id(crops)
            logger.info("Cropped %d component regions into %s", len(crops), crops_dir)
        except Exception as exc:  # noqa: BLE001 — cropping is auxiliary
            logger.warning("Figure cropping failed: %s", exc)

    compound, ordered_ids, source_tags = generate_assembly(
        figure_spec,
        ir,
        components_dir=components_dir,
        figure_crops=figure_crops_dict,
        code_cache_dir=code_cache_dir,
        enable_codegen=enable_codegen,
    )

    # --- Spatial composer pass --------------------------------------------
    # The first build is the VLM's per-component guess at where things go.
    # Now ask the VLM to look at the *whole rendered assembly* against the
    # figure(s) and revise every pose so shared axes line up. One call.
    if enable_spatial_composer and len(ordered_ids) >= 2:
        from claim2cad.visual_validator import render_step_to_pngs

        try:
            tmp_step = example_dir / "_pre_compose.step"
            bd.export_step(compound, str(tmp_step))
            tmp_renders_dir = example_dir / "renders_pre_compose"
            tmp_renders = render_step_to_pngs(
                tmp_step, tmp_renders_dir, style=render_style
            )
            composer_figure = _compose_multi_figure(
                example_dir, primary=figure_path, multi=multi_figure
            )
            from claim2cad.spatial_composer import compose_spatial

            ir_constraints = {c.id: list(c.constraints or []) for c in ir.components}
            id_to_solid: dict[str, bd.Part | bd.Compound] = {}
            for child in compound.children:
                if getattr(child, "label", None):
                    id_to_solid[child.label] = child
            revised_spec, explanation = compose_spatial(
                spec=figure_spec,
                component_solids=id_to_solid,
                figure_path=composer_figure,
                rendered_pngs=tmp_renders,
                ir_constraints=ir_constraints,
                relations=ir.relations or [],
                composite_path=example_dir / "composer_composite.png",
                patent_context=patent_context,
            )
            # Persist revised spec.
            spec_path.write_text(
                json.dumps(revised_spec.to_dict(), indent=2), encoding="utf-8"
            )
            (example_dir / "spatial_composer_explanation.txt").write_text(
                explanation, encoding="utf-8"
            )
            # Rebuild assembly with revised poses.
            figure_spec = revised_spec
            compound, ordered_ids, source_tags = generate_assembly(
                figure_spec,
                ir,
                components_dir=components_dir,
                figure_crops=figure_crops_dict,
                code_cache_dir=code_cache_dir,
                enable_codegen=enable_codegen,
            )
            tmp_step.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 — composer is best-effort
            logger.warning("Spatial composer failed: %s — keeping un-composed assembly", exc)

    step_path = example_dir / out_step
    glb_path = example_dir / out_glb
    bd.export_step(compound, str(step_path))
    bd.export_gltf(compound, str(glb_path), binary=True)
    try:
        rename_glb_root_children(glb_path, ordered_ids)
    except Exception as exc:  # noqa: BLE001 — naming is best-effort
        logger.warning("GLB rename failed: %s", exc)

    # Provenance log — which path built each component.
    sources_path = example_dir / "component_sources.json"
    sources_path.write_text(json.dumps(source_tags, indent=2), encoding="utf-8")

    src_summary: dict[str, int] = {}
    for v in source_tags.values():
        key = v.split(":", 1)[0]
        src_summary[key] = src_summary.get(key, 0) + 1
    logger.info(
        "Wrote %s and %s with %d components — sources: %s",
        step_path,
        glb_path,
        len(ordered_ids),
        src_summary,
    )
    return {
        "spec": spec_path,
        "step": step_path,
        "glb": glb_path,
        "components_dir": components_dir,
        "sources": sources_path,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _compose_multi_figure(
    example_dir: Path, *, primary: Path, multi: bool
) -> Path:
    """Compose figure_1, figure_2, figure_3 (if present) into one PNG so
    the VLM sees all view states at once. Returns the path to the composite
    (or just ``primary`` if no extras exist or multi is False)."""
    if not multi:
        return primary
    figures_dir = example_dir / "figures"
    extras: list[Path] = []
    for name in ("figure_2.png", "figure_3.png"):
        p = figures_dir / name
        if p.exists():
            extras.append(p)
    if not extras:
        return primary
    try:
        from PIL import Image

        all_figures = [primary] + extras
        loaded = [Image.open(p).convert("RGB") for p in all_figures]
        # Letterbox each to a max 1024 wide canvas.
        target_w = 1024
        items: list[Image.Image] = []
        for im in loaded:
            ratio = im.height / im.width
            new_h = int(target_w * ratio)
            items.append(im.resize((target_w, new_h), Image.LANCZOS))
        total_h = sum(im.height for im in items) + 8 * (len(items) - 1)
        canvas = Image.new("RGB", (target_w, total_h), (255, 255, 255))
        y = 0
        for im in items:
            canvas.paste(im, (0, y))
            y += im.height + 8
        out = example_dir / "_multi_figure.png"
        canvas.save(out)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Multi-figure composition failed: %s — using primary", exc)
        return primary


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
    p.add_argument(
        "--no-codegen",
        action="store_true",
        help="Disable VLM build123d codegen for unmatched components.",
    )
    p.add_argument(
        "--crop-radius",
        type=float,
        default=0.12,
        help="Radius (normalised) for per-component figure crops.",
    )
    p.add_argument(
        "--no-spatial-composer",
        action="store_true",
        help="Skip the spatial composer pass after initial build.",
    )
    p.add_argument(
        "--no-multi-figure",
        action="store_true",
        help="Use only figure_1 (skip composing figures 2 and 3).",
    )
    p.add_argument(
        "--render-style",
        choices=("shaded", "line"),
        default="line",
        help="Render style for composer + validation (default: line drawing).",
    )
    p.add_argument(
        "--patent-context",
        default="",
        help="Free-text context surfaced to the spatial composer.",
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
        enable_codegen=not args.no_codegen,
        crop_radius=args.crop_radius,
        enable_spatial_composer=not args.no_spatial_composer,
        multi_figure=not args.no_multi_figure,
        render_style=args.render_style,
        patent_context=args.patent_context,
    )
    print(json.dumps({k: str(v) for k, v in out.items()}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
