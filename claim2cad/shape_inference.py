"""Per-component 3D shape inference from a patent figure crop.

The outline-first pipeline (V11-12) gave us the *silhouette* per
component but no depth and no inter-component constraints. The result
was a flat collage of 2.5D plates lying on one plane.

This module asks the VLM for the *3D mechanical reading* of each
component crop:

  * shape_family — one of a curated list (plate, bracket, hinge_leaf,
    knuckle, pin, shaft, washer, boss, spring, fastener, link,
    housing, slot, hole, tab, flange).
  * dims — (width, height, depth, diameter, thickness) in mm with
    optional uncertainty.
  * pose — (x, y, z) in mm plus axis rotations.
  * constraints — relations to other components: coaxial_with,
    attached_to, nested_in, passes_through, parallel_to,
    perpendicular_to, coplanar_with.

The constraints are what give the assembly real depth. When the VLM
says "pintle_pin coaxial_with knuckle_top, knuckle_middle,
knuckle_bottom and passes_through leaf_flange", the assembly solver
can place all of those parts on the same Z axis at the same XY, with
different Z extents — producing a hinge that *actually works*, not a
flat collage.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from claim2cad.figure_crops import FigureCrop
from claim2cad.figure_view_classifier import FigureViewReport
from claim2cad.llm_vision import vision_completion

logger = logging.getLogger(__name__)


SHAPE_FAMILIES = (
    "plate",
    "bracket",
    "hinge_leaf",
    "knuckle",
    "pin",
    "shaft",
    "washer",
    "boss",
    "spring",
    "fastener",
    "link",
    "housing",
    "slot",
    "hole",
    "tab",
    "flange",
    "other",
)


CONSTRAINT_KINDS = (
    "coaxial_with",
    "attached_to",
    "nested_in",
    "passes_through",
    "parallel_to",
    "perpendicular_to",
    "coplanar_with",
    "above",
    "below",
)


@dataclass
class ComponentShape:
    component_id: str
    figure_number: str
    shape_family: str = "other"
    width_mm: float = 0.0
    height_mm: float = 0.0
    depth_mm: float = 0.0
    diameter_mm: float = 0.0
    thickness_mm: float = 0.0
    pose_xyz_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    main_axis: str = "Z"
    constraints: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.5
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ComponentShape":
        return cls(
            component_id=d["component_id"],
            figure_number=d.get("figure_number", ""),
            shape_family=d.get("shape_family", "other"),
            width_mm=float(d.get("width_mm", 0.0)),
            height_mm=float(d.get("height_mm", 0.0)),
            depth_mm=float(d.get("depth_mm", 0.0)),
            diameter_mm=float(d.get("diameter_mm", 0.0)),
            thickness_mm=float(d.get("thickness_mm", 0.0)),
            pose_xyz_mm=tuple(d.get("pose_xyz_mm", (0.0, 0.0, 0.0))),  # type: ignore[arg-type]
            rotation_deg=tuple(d.get("rotation_deg", (0.0, 0.0, 0.0))),  # type: ignore[arg-type]
            main_axis=d.get("main_axis", "Z"),
            constraints=list(d.get("constraints", [])),
            confidence=float(d.get("confidence", 0.5)),
            notes=str(d.get("notes", "")),
        )


@dataclass
class ShapeInferenceSet:
    figure_id: str
    view_kind: str
    figure_scale_mm: float
    shapes: list[ComponentShape] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "figure_id": self.figure_id,
            "view_kind": self.view_kind,
            "figure_scale_mm": self.figure_scale_mm,
            "shapes": [s.to_dict() for s in self.shapes],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ShapeInferenceSet":
        return cls(
            figure_id=d["figure_id"],
            view_kind=d.get("view_kind", "isometric"),
            figure_scale_mm=float(d.get("figure_scale_mm", 200.0)),
            shapes=[ComponentShape.from_dict(s) for s in d.get("shapes", [])],
        )

    def by_id(self) -> dict[str, ComponentShape]:
        return {s.component_id: s for s in self.shapes}


_SYSTEM = (
    "You are reading a CROP of a patent line drawing showing ONE "
    "mechanical component. Decide its 3D shape family, estimate its "
    "millimetre-scale dimensions, give its pose in the assembly "
    "frame, and name its mechanical RELATIONSHIPS to neighbouring "
    "components (coaxial pins through holes, parts nested in brackets, "
    "etc.). Always return strict JSON. Estimate generously when "
    "uncertain — the downstream solver tolerates small errors."
)


_USER_TEMPLATE = """Patent: {patent_title}
Figure view: {view_kind} (page-out axis = {main_axis}, scale ≈ {scale_mm} mm).

Component: id={component_id}, label={label!r}, kind={kind!r},
category={category!r}, figure_number={figure_number}, parent={parent_id}.
Claim constraints describing this component:
{claim_constraints}

Other components in the same assembly (so you can reference them in
constraints):
{neighbour_list}

Return JSON with EXACTLY this shape:
{{
  "shape_family": "<one of: plate|bracket|hinge_leaf|knuckle|pin|shaft|washer|boss|spring|fastener|link|housing|slot|hole|tab|flange|other>",
  "width_mm": <float>,
  "height_mm": <float>,
  "depth_mm": <float, the dimension perpendicular to width and height>,
  "diameter_mm": <float, for cylindrical parts; 0 if not cylindrical>,
  "thickness_mm": <float, sheet thickness for plate-like parts>,
  "pose_xyz_mm": [<x>, <y>, <z>],
  "rotation_deg": [<rx>, <ry>, <rz>],
  "main_axis": "<X|Y|Z — the part's natural long axis in the assembly frame>",
  "constraints": [
    {{"kind": "coaxial_with|attached_to|nested_in|passes_through|parallel_to|perpendicular_to|coplanar_with|above|below",
      "target": "<component_id of the related component>"}}
  ],
  "confidence": <float 0-1>,
  "notes": "<one sentence on the geometry you read>"
}}

Rules:
- Coordinate frame: Z is up; X is right; Y is into the page. Place the
  hinge axis along Z whenever the figure shows a vertical pintle.
- Whole assembly fits in roughly a 200 mm cube centred on origin.
- Pin / shaft components: depth_mm = pin length along its main axis,
  diameter_mm = pin OD; width/height/thickness = 0.
- Plate / leaf / flange: thickness_mm > 0 (typically 2–5 mm),
  width_mm and height_mm > 0.
- Bracket / knuckle / housing: width_mm, height_mm, depth_mm all > 0.
- A pintle pin running through several knuckles MUST list each
  knuckle in its constraints with kind=coaxial_with or
  passes_through.
- A leaf flange whose hole receives a pin MUST list the pin with
  passes_through.
- Use mm consistently; no unit suffixes.
- If the part is abstract (e.g. an axis or a no-geometry callout),
  set shape_family="other" and depth_mm=0 — the solver will skip it.
"""


def _format_constraints(constraints: list[str] | None) -> str:
    if not constraints:
        return "  (none)"
    return "\n".join(f"  - {c}" for c in constraints[:8])


def _format_neighbours(
    component_id: str,
    ir_components: dict[str, dict[str, Any]],
    max_n: int = 18,
) -> str:
    rows: list[str] = []
    for cid, info in ir_components.items():
        if cid == component_id:
            continue
        rows.append(
            f"  - {cid} (label={info.get('label', '')!r}, kind={info.get('kind', '')!r})"
        )
        if len(rows) >= max_n:
            break
    return "\n".join(rows) if rows else "  (no neighbours)"


def infer_shape_for_component(
    *,
    crop: FigureCrop,
    component_id: str,
    label: str,
    kind: str,
    category: str,
    parent_id: str | None,
    claim_constraints: list[str],
    ir_components: dict[str, dict[str, Any]],
    view_report: FigureViewReport,
    figure_scale_mm: float = 200.0,
    patent_title: str = "",
    task_type: str = "v11_shape_infer",
) -> ComponentShape:
    """One vision call per component. Cached by the caller."""
    user = _USER_TEMPLATE.format(
        patent_title=patent_title or "(unknown)",
        view_kind=view_report.view_kind,
        main_axis=view_report.main_axis,
        scale_mm=figure_scale_mm,
        component_id=component_id,
        label=label,
        kind=kind or "(unknown)",
        category=category or "(unknown)",
        figure_number=crop.figure_number,
        parent_id=parent_id or "(none)",
        claim_constraints=_format_constraints(claim_constraints),
        neighbour_list=_format_neighbours(component_id, ir_components),
    )
    raw = vision_completion(
        image_path=crop.crop_path,
        system_prompt=_SYSTEM,
        user_prompt=user,
        task_type=task_type,
    )
    sf = str(raw.get("shape_family", "other")).strip().lower()
    if sf not in SHAPE_FAMILIES:
        sf = "other"
    pose = raw.get("pose_xyz_mm") or [0.0, 0.0, 0.0]
    rot = raw.get("rotation_deg") or [0.0, 0.0, 0.0]
    constraints_raw = raw.get("constraints") or []
    constraints = []
    for c in constraints_raw:
        if not isinstance(c, dict):
            continue
        kind_c = str(c.get("kind", "")).strip().lower()
        target = str(c.get("target", "")).strip()
        if not kind_c or not target:
            continue
        if kind_c not in CONSTRAINT_KINDS:
            continue
        if target not in ir_components:
            continue
        constraints.append({"kind": kind_c, "target": target})
    return ComponentShape(
        component_id=component_id,
        figure_number=crop.figure_number,
        shape_family=sf,
        width_mm=float(raw.get("width_mm", 0.0) or 0.0),
        height_mm=float(raw.get("height_mm", 0.0) or 0.0),
        depth_mm=float(raw.get("depth_mm", 0.0) or 0.0),
        diameter_mm=float(raw.get("diameter_mm", 0.0) or 0.0),
        thickness_mm=float(raw.get("thickness_mm", 0.0) or 0.0),
        pose_xyz_mm=(
            float(pose[0] if len(pose) > 0 else 0.0),
            float(pose[1] if len(pose) > 1 else 0.0),
            float(pose[2] if len(pose) > 2 else 0.0),
        ),
        rotation_deg=(
            float(rot[0] if len(rot) > 0 else 0.0),
            float(rot[1] if len(rot) > 1 else 0.0),
            float(rot[2] if len(rot) > 2 else 0.0),
        ),
        main_axis=str(raw.get("main_axis", "Z")).strip().upper() or "Z",
        constraints=constraints,
        confidence=float(raw.get("confidence", 0.5) or 0.5),
        notes=str(raw.get("notes", "")),
    )


def infer_shapes_for_components(
    *,
    crops_by_id: dict[str, FigureCrop],
    ir_components: dict[str, dict[str, Any]],
    view_report: FigureViewReport,
    figure_scale_mm: float = 200.0,
    patent_title: str = "",
    cache_path: Path | None = None,
) -> ShapeInferenceSet:
    """Run shape inference per component. Cached aggregated to disk."""
    if cache_path is not None and cache_path.exists():
        try:
            data = json.loads(cache_path.read_text("utf-8"))
            cached = ShapeInferenceSet.from_dict(data)
            cached_ids = set(cached.by_id().keys())
            requested_ids = set(crops_by_id.keys())
            if cached_ids >= requested_ids:
                logger.info("Using cached shape inference at %s", cache_path)
                return cached
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not load shape cache at %s", cache_path)

    shapes: list[ComponentShape] = []
    for cid, crop in crops_by_id.items():
        info = ir_components.get(cid, {})
        try:
            shape = infer_shape_for_component(
                crop=crop,
                component_id=cid,
                label=info.get("label", cid),
                kind=info.get("kind", ""),
                category=info.get("category", ""),
                parent_id=info.get("parent_id"),
                claim_constraints=info.get("constraints", []) or [],
                ir_components=ir_components,
                view_report=view_report,
                figure_scale_mm=figure_scale_mm,
                patent_title=patent_title,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("shape inference failed for %s: %s", cid, exc)
            shape = ComponentShape(
                component_id=cid,
                figure_number=crop.figure_number,
                notes=f"failed: {exc}",
            )
        shapes.append(shape)

    out = ShapeInferenceSet(
        figure_id=view_report.figure_id,
        view_kind=view_report.view_kind,
        figure_scale_mm=figure_scale_mm,
        shapes=shapes,
    )
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(out.to_dict(), indent=2), encoding="utf-8")
    return out


__all__ = [
    "SHAPE_FAMILIES",
    "CONSTRAINT_KINDS",
    "ComponentShape",
    "ShapeInferenceSet",
    "infer_shape_for_component",
    "infer_shapes_for_components",
]
