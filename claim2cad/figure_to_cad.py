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
from claim2cad.figure_to_sketch import (
    ComponentOutline,
    OutlineSet,
    extract_outlines_for_components,
)
from claim2cad.figure_view_classifier import classify_figure, FigureViewReport
from claim2cad.shape_inference import (
    ShapeInferenceSet,
    infer_shapes_for_components,
)
from claim2cad.assembly_solver import (
    build_assembly as build_3d_assembly,
    build_assembly_scaffold_first,
)
from claim2cad.scene_scaffold import (
    SceneScaffold,
    lift_off_door_hinge_scaffold_for_us4807331a,
    save_scaffold,
)
from claim2cad.figure_projection import (
    FigureProjectionLayout,
    build_projection,
    figure_anchors_for_components,
    group_anchors_from_components,
    save_layout,
)
from claim2cad.projection_layout_solver import build_assembly_figure_anchored
from claim2cad.figure_aligned_render import (
    render_figure_aligned,
    render_anchor_debug_overlay,
    make_figure_aligned_comparison,
)
from claim2cad.projection_compare import render_canonical_views
from claim2cad.sketch_to_extrusion import (
    ExtrusionResult,
    build_assembly_from_outlines,
)
from claim2cad.geometric_invariants import InvariantReport, evaluate_invariants
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
    enable_ir_enrichment: bool = True,
    n_candidates: int = 1,
    outline_first: bool = True,
    figure_scale_mm: float = 200.0,
    mode: str = "3d",
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
    # If IR enrichment added components beyond what the IR knows about, we
    # need to skip the "missing-from-IR" check in generate_assembly. We
    # do that by adding stub IRComponents for the enriched ids below.

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
        logger.info(
            "Calling VLM to analyse %s (n_candidates=%d)",
            figure_path.name,
            n_candidates,
        )
        if n_candidates <= 1:
            figure_spec = analyze_figure(
                figure_path,
                ir,
                figure_id=figure_path.stem,
                figure_map=figure_map,
            )
        else:
            # CADFusion-style best-of-N: generate N parametric sequences,
            # rank by geometric invariants on the BUILT assembly, pick
            # the highest-scoring spec. Saves the per-candidate scores
            # for audit.
            figure_spec, candidate_scores = _best_of_n_spec(
                figure_path,
                ir,
                figure_id=figure_path.stem,
                figure_map=figure_map,
                n_candidates=n_candidates,
            )
            (example_dir / "best_of_n_scores.json").write_text(
                json.dumps(candidate_scores, indent=2),
                encoding="utf-8",
            )
        # IR enrichment: pull sub-features from figure callouts not bound to
        # any claim component. Adds them as codegen specs.
        if enable_ir_enrichment and figure_map:
            try:
                from claim2cad.ir_enricher import enrich_ir, merge_into_spec

                additions, skipped = enrich_ir(
                    figure_path=figure_path,
                    figure_map=figure_map,
                    spec=figure_spec,
                    patent_context=patent_context,
                )
                figure_spec = merge_into_spec(figure_spec, additions)
                (example_dir / "ir_enrichment.json").write_text(
                    json.dumps(
                        {
                            "additions": [
                                {
                                    "component_id": s.component_id,
                                    "notes": s.notes,
                                    "features": s.features,
                                }
                                for s in additions
                            ],
                            "skipped": skipped,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            except Exception as exc:  # noqa: BLE001 — best-effort
                logger.warning("IR enrichment failed: %s", exc)
        spec_path.write_text(json.dumps(figure_spec.to_dict(), indent=2), encoding="utf-8")
        logger.info("Wrote figure spec to %s", spec_path)

    components_dir = example_dir / "components"
    code_cache_dir = example_dir / "codegen_cache"

    # ----------------------------------------------------------------------
    # 3D figure-grounded reconstruction path (V11-14)
    # ----------------------------------------------------------------------
    # When mode="3d" we run figure_view_classifier + shape_inference +
    # assembly_solver and render canonical projections. The outline path
    # below is left as a fallback for environments without VLM access.
    if mode == "3d" and figure_map and figure_path.exists():
        try:
            crops_dir = example_dir / "crops"
            crops = crop_all_components(
                figure_path,
                figure_map,
                out_dir=crops_dir,
                crop_radius=crop_radius,
            )
            crops_by_id = crops_by_component_id(crops)
            view_report = classify_figure(
                figure_path=figure_path,
                patent_title=ir.title or "",
                figure_id=figure_path.stem,
                cache_path=example_dir / "figure_view.json",
            )
            ir_components_by_id = {
                c.id: {
                    "label": c.label,
                    "kind": c.kind,
                    "category": c.category,
                    "parent_id": c.parent_id,
                    "constraints": list(c.constraints or []),
                }
                for c in ir.components
            }
            inference = infer_shapes_for_components(
                crops_by_id=crops_by_id,
                ir_components=ir_components_by_id,
                view_report=view_report,
                figure_scale_mm=figure_scale_mm,
                patent_title=ir.title or "",
                cache_path=example_dir / "shape_inference.json",
            )
            # V11-23+: figure-projection-grounded build path. Patent
            # family scaffold (v11-20) gives us scene groups; the
            # figure_projection layout (v11-23b) gives us per-callout
            # (u, v) anchors mapped to CAD coords. The new solver
            # places each component at its figure-projected anchor —
            # the chosen camera projection of the CAD literally
            # tracks the patent figure. Falls back to scaffold-only
            # placement when no figure_map is available, and to the
            # V11-14 component-level path otherwise.
            scaffold = _maybe_build_scaffold(ir, example_dir)
            if scaffold is not None and figure_map and figure_path.exists():
                save_scaffold(scaffold, example_dir / "scene_scaffold.json")
                # Build the figure-projection layout once and persist it.
                from PIL import Image
                img = Image.open(figure_path)
                proj = build_projection(
                    figure_id=view_report.figure_id,
                    view_kind=view_report.view_kind,
                    figure_width_px=img.size[0],
                    figure_height_px=img.size[1],
                    scale_uv_to_mm=figure_scale_mm * 1.5,
                )
                # Per-group depth hints push door / frame / hinge to
                # different Y depths so the front-view projection
                # spreads them visibly.
                group_depth_hints = {
                    "door_panel": -30.0,
                    "fixed_frame": +30.0,
                    "upper_hinge": 0.0,
                    "lower_hinge": 0.0,
                    "pintle_axis": 0.0,
                    "power_mechanism": 10.0,
                    "fasteners": 5.0,
                }
                component_depth_hints = {
                    cid: group_depth_hints.get(gid, 0.0)
                    for cid, gid in scaffold.component_to_group.items()
                }
                anchors = figure_anchors_for_components(
                    figure_map=figure_map,
                    projection=proj,
                    component_depth_hints_mm=component_depth_hints,
                )
                g_anchors = group_anchors_from_components(
                    component_anchors=anchors,
                    component_to_group=scaffold.component_to_group,
                    projection=proj,
                    group_depth_hints_mm=group_depth_hints,
                    extra_groups=tuple(g.id for g in scaffold.groups),
                )
                layout = FigureProjectionLayout(
                    projection=proj,
                    component_anchors=anchors,
                    group_anchors=g_anchors,
                )
                save_layout(layout, example_dir / "figure_projection.json")
                # V12-B — apply patent-family-specific layout lock
                # if present. The lock overrides the median-derived
                # group anchors with hand-traced figure regions and
                # clamps each component to its group bbox so the
                # assembly cannot collapse to a central pile.
                lock_path = example_dir / "figure_layout_lock.json"
                if lock_path.exists():
                    try:
                        from claim2cad.figure_layout_lock import (
                            apply_layout_lock, load_region_map,
                        )
                        rmap = load_region_map(lock_path)
                        layout = apply_layout_lock(
                            layout=layout,
                            region_map=rmap,
                            component_to_group=scaffold.component_to_group,
                            enforce_bbox=True,
                        )
                        save_layout(layout, example_dir / "figure_projection_locked.json")
                        logger.info(
                            "v12-b: applied figure_layout_lock with %d regions",
                            len(rmap.regions),
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("v12-b layout lock failed: %s", exc)
                compound, ordered_ids, diagnostics = build_assembly_figure_anchored(
                    inference=inference, scaffold=scaffold, layout=layout,
                )
            elif scaffold is not None:
                save_scaffold(scaffold, example_dir / "scene_scaffold.json")
                compound, ordered_ids, diagnostics = build_assembly_scaffold_first(
                    inference, scaffold
                )
            else:
                compound, ordered_ids, diagnostics = build_3d_assembly(inference)
            step_path = example_dir / out_step
            glb_path = example_dir / out_glb
            bd.export_step(compound, str(step_path))
            bd.export_gltf(compound, str(glb_path), binary=True)
            try:
                rename_glb_root_children(glb_path, ordered_ids)
            except Exception as exc:  # noqa: BLE001
                logger.warning("GLB rename failed: %s", exc)

            # Per-component STEP files for the components/ dir.
            components_dir = example_dir / "components"
            components_dir.mkdir(parents=True, exist_ok=True)
            for child in compound.children:
                if not getattr(child, "label", None):
                    continue
                try:
                    bd.export_step(
                        child, str(components_dir / f"{child.label}.step")
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("per-component STEP for %s: %s", child.label, exc)

            (example_dir / "solver_diagnostics.json").write_text(
                json.dumps([d.__dict__ for d in diagnostics], indent=2),
                encoding="utf-8",
            )
            (example_dir / "component_sources.json").write_text(
                json.dumps(
                    {d.component_id: f"3d:{d.shape_family}" for d in diagnostics},
                    indent=2,
                ),
                encoding="utf-8",
            )

            # Render canonical views and a side-by-side comparison.
            try:
                proj_report = render_canonical_views(
                    step_path=step_path,
                    out_dir=example_dir / "renders_v1.1",
                    figure_path=figure_path,
                    view_names=("top", "front", "right", "iso"),
                )
                (example_dir / "projection_report.json").write_text(
                    json.dumps(proj_report.to_dict(), indent=2),
                    encoding="utf-8",
                )
                if proj_report.comparison_path is not None:
                    (example_dir / "render_comparison.png").write_bytes(
                        proj_report.comparison_path.read_bytes()
                    )
                # solid_*.png aliases.
                import shutil
                for view in ("iso", "top", "front", "right"):
                    src = example_dir / "renders_v1.1" / f"projection_{view}.png"
                    if src.exists():
                        shutil.copy(
                            src,
                            example_dir / "renders_v1.1" / f"solid_{view}.png",
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning("projection comparison failed: %s", exc)

            # V11-25 figure-aligned render (when a layout is available).
            fp_path = example_dir / "figure_projection.json"
            if fp_path.exists():
                try:
                    from claim2cad.figure_projection import load_layout
                    layout = load_layout(fp_path)
                    aligned = render_figure_aligned(
                        step_path=step_path,
                        out_path=example_dir / "renders_v1.1" / "figure_aligned_view.png",
                        projection=layout.projection,
                        resolution=1280,
                    )
                    import shutil
                    shutil.copy(
                        aligned,
                        example_dir / "renders_v1.1" / "figure_aligned_solid.png",
                    )
                    render_anchor_debug_overlay(
                        figure_path=figure_path,
                        layout=layout,
                        out_path=example_dir / "renders_v1.1" / "figure_anchor_debug.png",
                    )
                    comp = make_figure_aligned_comparison(
                        figure_path=figure_path,
                        figure_aligned_render=aligned,
                        out_path=example_dir / "renders_v1.1" / "figure_aligned_comparison.png",
                    )
                    # Promote the figure-aligned comparison as the canonical
                    # render_comparison so the viewer / portfolio shows it.
                    (example_dir / "render_comparison.png").write_bytes(
                        comp.read_bytes()
                    )
                    (example_dir / "renders_v1.1" / "solid_comparison.png").write_bytes(
                        comp.read_bytes()
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("figure-aligned render failed: %s", exc)

            logger.info(
                "3D mode wrote %s and %s with %d components (best view=%s)",
                step_path,
                glb_path,
                len(ordered_ids),
                getattr(proj, "best_view", "?") if "proj" in dir() else "?",
            )
            return {
                "spec": example_dir / "shape_inference.json",
                "step": step_path,
                "glb": glb_path,
                "components_dir": components_dir,
                "sources": example_dir / "component_sources.json",
                "view_report": example_dir / "figure_view.json",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "3D path failed (%s) — falling back to outline-first", exc
            )

    # Per-component figure crops (if figure_map.json is present).
    crops_dir = example_dir / "crops"
    figure_crops_dict: dict[str, FigureCrop] = {}
    crops_by_number: dict[str, FigureCrop] = {}
    if figure_map and figure_path.exists():
        try:
            crops = crop_all_components(
                figure_path,
                figure_map,
                out_dir=crops_dir,
                crop_radius=crop_radius,
            )
            figure_crops_dict = crops_by_component_id(crops)
            crops_by_number = {c.figure_number: c for c in crops}
            logger.info("Cropped %d component regions into %s", len(crops), crops_dir)
        except Exception as exc:  # noqa: BLE001 — cropping is auxiliary
            logger.warning("Figure cropping failed: %s", exc)

    # For IR-enrichment-added components, bind their figure crops via
    # `figure_number=N` in the spec's features list.
    for s in figure_spec.components:
        if s.component_id in figure_crops_dict:
            continue
        for feat in s.features or []:
            if not feat.startswith("figure_number="):
                continue
            num = feat.split("=", 1)[1].strip()
            crop = crops_by_number.get(num)
            if crop is not None:
                figure_crops_dict[s.component_id] = crop
            break

    # Add stub IR components for any spec entry whose component_id isn't in
    # the IR (the enricher will have added some). Without this stub,
    # generate_assembly skips them.
    ir = _augment_ir_with_enrichment(ir, figure_spec)

    # ----------------------------------------------------------------------
    # OUTLINE-FIRST PATH (V11-12)
    # ----------------------------------------------------------------------
    # The user's correct observation: when a 2D engineering drawing is
    # available, the right way to produce CAD that matches is to TRACE
    # the silhouette of each component in the drawing and EXTRUDE it
    # along Z. The library/codegen path picks generic primitives that
    # only loosely resemble what's actually drawn. This path traces the
    # actual silhouette per component crop.
    if outline_first and figure_crops_dict:
        try:
            ir_components_by_id = {
                c.id: {"label": c.label, "kind": c.kind, "category": c.category}
                for c in ir.components
            }
            outline_set = extract_outlines_for_components(
                figure_path=figure_path,
                component_crops=figure_crops_dict,
                ir_components=ir_components_by_id,
                patent_title=ir.title or "",
                figure_scale_mm=figure_scale_mm,
                use_vlm=True,
            )
            (example_dir / "outline_set.json").write_text(
                json.dumps(outline_set.to_dict(), indent=2),
                encoding="utf-8",
            )
            n_valid = sum(1 for o in outline_set.outlines if o.is_valid())
            logger.info(
                "Outline-first: extracted %d/%d valid outlines",
                n_valid,
                len(outline_set.outlines),
            )
            if n_valid >= 2:
                compound, ordered_ids, ext_results = build_assembly_from_outlines(
                    outline_set
                )
                # STEP per component for the components/ dir.
                components_dir.mkdir(parents=True, exist_ok=True)
                source_tags: dict[str, str] = {}
                for r in ext_results:
                    if r.solid is None:
                        continue
                    try:
                        bd.export_step(
                            r.solid, str(components_dir / f"{r.component_id}.step")
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "per-component STEP export failed for %s: %s",
                            r.component_id,
                            exc,
                        )
                    source_tags[r.component_id] = f"outline:{outline_set.outlines and 'vlm'}"
                # Skip the spatial composer entirely — outlines are
                # already positioned in figure-XY space, which is what
                # the user asked for.
                step_path = example_dir / out_step
                glb_path = example_dir / out_glb
                bd.export_step(compound, str(step_path))
                bd.export_gltf(compound, str(glb_path), binary=True)
                try:
                    rename_glb_root_children(glb_path, ordered_ids)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("GLB rename failed: %s", exc)
                sources_path = example_dir / "component_sources.json"
                sources_path.write_text(
                    json.dumps(source_tags, indent=2), encoding="utf-8"
                )
                logger.info(
                    "Outline-first wrote %s and %s with %d components",
                    step_path,
                    glb_path,
                    len(ordered_ids),
                )
                return {
                    "spec": spec_path,
                    "step": step_path,
                    "glb": glb_path,
                    "components_dir": components_dir,
                    "sources": sources_path,
                    "outline_set": example_dir / "outline_set.json",
                }
            else:
                logger.warning(
                    "Outline-first: only %d valid outlines — falling back to library path",
                    n_valid,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Outline-first path failed: %s — falling back", exc)

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


def _best_of_n_spec(
    figure_path: Path,
    ir: ClaimIR,
    *,
    figure_id: str,
    figure_map: dict[str, Any] | None,
    n_candidates: int,
) -> tuple[FigureSpec, list[dict[str, Any]]]:
    """Sample N candidate figure_specs, score each by trial-build +
    geometric invariants, return the highest-scoring spec.

    The CADFusion paper trains an LLM to prefer parametric sequences
    whose renders look correct. We can't retrain, but we can apply the
    inference-time analogue: sample multiple candidates, score by a
    cheap geometric invariant, and pick the best.

    Geometric invariants (claim2cad.geometric_invariants) catch the
    failure modes we know — pin missing some hole-bearing components,
    link too tall to nest, door not wrapping the body, etc. — without
    needing an extra VLM call per candidate.
    """
    candidates: list[tuple[float, FigureSpec, dict[str, Any]]] = []
    for i in range(n_candidates):
        try:
            spec = analyze_figure(
                figure_path, ir, figure_id=figure_id, figure_map=figure_map
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Candidate %d failed in analyze_figure: %s", i, exc)
            continue
        # Trial-build with no codegen / composer to keep this cheap
        # and deterministic. The geometric invariants can already tell
        # which candidate is going to compose well.
        try:
            ir_aug = _augment_ir_with_enrichment(ir, spec)
            compound, _, _ = generate_assembly(
                spec,
                ir_aug,
                components_dir=None,
                figure_crops=None,
                code_cache_dir=None,
                enable_codegen=False,
            )
            inv = evaluate_invariants(compound)
            score = inv.composite()
            entry = {
                "candidate": i,
                "score": round(score, 3),
                "invariants": inv.as_dict(),
                "n_components": len(spec.components),
                "library_parts_used": [
                    s.library_part
                    for s in spec.components
                    if s.library_part
                ],
            }
            candidates.append((score, spec, entry))
            logger.info(
                "Best-of-N candidate %d/%d: score=%.3f",
                i + 1,
                n_candidates,
                score,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Candidate %d trial-build failed: %s", i, exc)
            candidates.append(
                (
                    0.0,
                    spec,
                    {"candidate": i, "score": 0.0, "error": str(exc)},
                )
            )

    if not candidates:
        raise RuntimeError("Best-of-N failed for every candidate")
    # Sort highest first.
    candidates.sort(key=lambda t: -t[0])
    best_score, best_spec, _ = candidates[0]
    logger.info(
        "Best-of-N picked candidate with score %.3f (out of %d)",
        best_score,
        len(candidates),
    )
    return best_spec, [c[2] for c in candidates]


def _maybe_build_scaffold(ir: ClaimIR, example_dir: Path) -> SceneScaffold | None:
    """Pick a patent-family scaffold for the given IR. Returns None if
    no scaffold pattern matches; the caller falls back to the
    component-level placement.

    For now we only ship one scaffold (US4807331A-class lift-off door
    hinge). A claim is recognised when its IR contains a critical mass
    of the known component_ids (pintle_pin AND main_member AND
    door_half_member, etc.). The check is intentionally lenient —
    related patents (US4470181A self-closing hinge, US4502185A
    concealed hinge assembly) reuse much of the same vocabulary.
    """
    ir_ids = {c.id for c in ir.components}
    lift_off_signals = {
        "pintle_pin",
        "main_member",
        "door_half_member",
        "u_shaped_link_member",
        "leaf_flange",
        "vehicle_body",
    }
    if len(ir_ids & lift_off_signals) >= 3:
        return lift_off_door_hinge_scaffold_for_us4807331a(
            ir_component_ids=ir_ids
        )
    return None


def _augment_ir_with_enrichment(ir: ClaimIR, spec: FigureSpec) -> ClaimIR:
    """If ``spec`` references component_ids the IR doesn't know about (added
    by the IR enricher), splice stub IRComponents in so generate_assembly
    sees them. Stubs are kind="other", category="structural", with empty
    constraints — the enricher's notes/features carry the geometry hint."""
    from claim2cad.ir_schema import (
        Component as IRComponent,
        DimensionUnspecified,
        SourceSpan,
    )

    known = {c.id for c in ir.components}
    extras: list[IRComponent] = []
    for s in spec.components:
        if s.component_id in known:
            continue
        extras.append(
            IRComponent(
                id=s.component_id,
                label=s.component_id.replace("_", " "),
                category="structural",
                kind="sub_feature",
                parent_id=None,
                dimension=DimensionUnspecified(),
                constraints=[],
                source_span=SourceSpan(claim_id=ir.claims[0].id if ir.claims else "claim_1", char_start=0, char_end=1),
                figure_number=None,
                figure_references=[],
            )
        )
    if not extras:
        return ir
    return ir.model_copy(update={"components": list(ir.components) + extras})


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
    p.add_argument(
        "--no-ir-enrichment",
        action="store_true",
        help="Skip the IR enrichment pass (don't add features beyond claim text).",
    )
    p.add_argument(
        "--n-candidates",
        type=int,
        default=1,
        help="Best-of-N candidate sampling for the figure-to-spec stage.",
    )
    p.add_argument(
        "--no-outline-first",
        action="store_true",
        help="Skip the outline→extrusion path; use library/codegen instead.",
    )
    p.add_argument(
        "--figure-scale-mm",
        type=float,
        default=200.0,
        help="How many mm the longest figure axis represents (default 200).",
    )
    p.add_argument(
        "--mode",
        choices=("3d", "outline", "library"),
        default="3d",
        help=(
            "3d: figure_view + shape_inference + assembly_solver (default). "
            "outline: 2.5D outline-extrusion. "
            "library: legacy library/codegen path."
        ),
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
        enable_ir_enrichment=not args.no_ir_enrichment,
        n_candidates=args.n_candidates,
        outline_first=not args.no_outline_first,
        figure_scale_mm=args.figure_scale_mm,
        mode=args.mode,
    )
    print(json.dumps({k: str(v) for k, v in out.items()}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
