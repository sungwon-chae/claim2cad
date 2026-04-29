"""Figure hotspot — canonical viewer-grounding artefact.

The viewer's figure-panel hotspots are part of the
``claim ↔ figure ↔ CAD`` contract: clicking a claim span should
highlight the matching figure region AND the matching CAD mesh,
and vice-versa. v11-29a's diagnosis identified that the existing
hotspots are in the wrong places because the pipeline used the
**callout-label** position (where the digit text sits) rather than
the **part** position, and because ``claim_map.json`` rows didn't
carry ``figure_number`` so the viewer's primary lookup silently
fell through.

This module ships:

  * :class:`FigureHotspot` — the canonical schema. Coordinates are
    **raw image pixels** (origin top-left) so the viewer just needs
    to multiply by ``displayed_size / natural_size`` at render time.
    Both a ``center_px`` and a ``bbox_px`` are stored.
  * :class:`FigureHotspotSet` — the per-figure container, persisted
    as ``figure_hotspots.json``.
  * :func:`build_hotspots_for_example` — generator. Reads
    ``figure_map.json``, ``claim_map.json`` and (optionally)
    ``figure_projection.json``. For each claim component, prefers
    the figure-projection anchor (mapped from normalised UV to
    pixel) when it exists, falls back to the median callout label
    position over duplicate occurrences, falls back to the single
    label position. Always validates the hotspot is within image
    bounds and tags the source for the audit overlay.
  * :func:`render_hotspot_debug_overlay` — annotated PNG showing
    where each hotspot lands on ``figure_1.png``, with one colour
    per source (figure_projection / median_label / label).

The viewer reads ``figure_hotspots.json`` (V11-31) instead of
recomputing from ``vlm_labels``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# Canonical coordinate space tag.
COORD_SPACE_IMAGE_PIXEL = "image_pixel"
COORD_SPACE_NORMALISED = "normalised"


@dataclass
class FigureHotspot:
    """One viewer hotspot, in raw image-pixel coordinates.

    V11-35/36 additions:
      * ``hotspot_kind`` distinguishes a *part* hotspot (default
        viewer marker) from a *label* hotspot (the digit text); the
        viewer can render label hotspots in a debug overlay.
      * ``instance_id`` preserves repeated callout occurrences (the
        same component_id can have N hotspots, one per geographic
        instance like upper/lower hinge).
      * ``label_center_px`` and ``label_bbox_px`` are kept on the
        record so the viewer can show "label vs part" toggles
        without reloading other artefacts.
      * ``source`` enumerates: ``leader_endpoint`` |
        ``projection_anchor`` | ``crop_center`` | ``median_label`` |
        ``label_center`` | ``manual_override``.
    """

    hotspot_id: str
    figure_id: str
    component_id: str | None
    callout_number: str
    label: str
    coord_space: str = COORD_SPACE_IMAGE_PIXEL
    image_width_px: int = 0
    image_height_px: int = 0
    center_px: tuple[float, float] = (0.0, 0.0)
    bbox_px: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    confidence: float = 0.5
    source: str = "label_center"
    hotspot_kind: str = "part"  # "part" | "label"
    instance_id: int = 0
    label_center_px: tuple[float, float] | None = None
    label_bbox_px: tuple[float, float, float, float] | None = None
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["center_px"] = list(self.center_px)
        d["bbox_px"] = list(self.bbox_px)
        if self.label_center_px is not None:
            d["label_center_px"] = list(self.label_center_px)
        if self.label_bbox_px is not None:
            d["label_bbox_px"] = list(self.label_bbox_px)
        return d


@dataclass
class FigureHotspotSet:
    figure_id: str
    image_width_px: int
    image_height_px: int
    figure_path: str
    hotspots: list[FigureHotspot] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "figure_id": self.figure_id,
            "figure_path": self.figure_path,
            "image_width_px": self.image_width_px,
            "image_height_px": self.image_height_px,
            "hotspots": [h.to_dict() for h in self.hotspots],
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FigureHotspotSet":
        hs: list[FigureHotspot] = []
        for h in d.get("hotspots", []):
            label_center = h.get("label_center_px")
            label_bbox = h.get("label_bbox_px")
            hs.append(
                FigureHotspot(
                    hotspot_id=h["hotspot_id"],
                    figure_id=h["figure_id"],
                    component_id=h.get("component_id"),
                    callout_number=h.get("callout_number", ""),
                    label=h.get("label", ""),
                    coord_space=h.get("coord_space", COORD_SPACE_IMAGE_PIXEL),
                    image_width_px=int(h.get("image_width_px", 0)),
                    image_height_px=int(h.get("image_height_px", 0)),
                    center_px=tuple(h.get("center_px", (0.0, 0.0))),  # type: ignore[arg-type]
                    bbox_px=tuple(h.get("bbox_px", (0.0, 0.0, 0.0, 0.0))),  # type: ignore[arg-type]
                    confidence=float(h.get("confidence", 0.5)),
                    source=h.get("source", "label_center"),
                    hotspot_kind=h.get("hotspot_kind", "part"),
                    instance_id=int(h.get("instance_id", 0)),
                    label_center_px=tuple(label_center) if label_center else None,  # type: ignore[arg-type]
                    label_bbox_px=tuple(label_bbox) if label_bbox else None,  # type: ignore[arg-type]
                    debug=h.get("debug", {}),
                )
            )
        return cls(
            figure_id=d["figure_id"],
            image_width_px=int(d["image_width_px"]),
            image_height_px=int(d["image_height_px"]),
            figure_path=d.get("figure_path", ""),
            hotspots=hs,
            notes=d.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _norm_to_px(
    uv: tuple[float, float],
    image_width_px: int,
    image_height_px: int,
) -> tuple[float, float]:
    return (
        max(0.0, min(image_width_px - 1.0, uv[0] * image_width_px)),
        max(0.0, min(image_height_px - 1.0, uv[1] * image_height_px)),
    )


def _bbox_around_centre(
    centre_px: tuple[float, float],
    image_width_px: int,
    image_height_px: int,
    *,
    radius_frac: float = 0.04,
) -> tuple[float, float, float, float]:
    rx = image_width_px * radius_frac
    ry = image_height_px * radius_frac
    cx, cy = centre_px
    return (
        max(0.0, cx - rx),
        max(0.0, cy - ry),
        min(image_width_px - 1.0, cx + rx),
        min(image_height_px - 1.0, cy + ry),
    )


def build_hotspots_for_example(
    *,
    example_dir: Path,
    figure_filename: str = "figures/figure_1.png",
) -> FigureHotspotSet | None:
    """Build a ``FigureHotspotSet`` for an example.

    V11-35/36 strategy — produce one hotspot per **callout instance**
    (preserving repeats so upper/lower hinge occurrences are
    separate), with both a part hotspot and a label hotspot per
    instance:

      * Each `vlm_labels[i]` becomes one (or two) hotspots tied to
        the component_id its number maps to.
      * The **part** hotspot's source is the leader endpoint when
        leader_lines.json provides one; otherwise it falls back to
        the figure_projection anchor (only for the first instance
        per component, since the projection collapses repeats),
        then to the label center as a last resort.
      * The **label** hotspot is always emitted with source
        ``label_center`` so debug overlays can show both.

    Returns ``None`` when figure or claim_map is missing.
    """
    figure_path = example_dir / figure_filename
    fmap_path = example_dir / "figure_map.json"
    cmap_path = example_dir / "claim_map.json"
    fproj_path = example_dir / "figure_projection.json"
    leaders_path = example_dir / "leader_lines.json"
    if not figure_path.exists() or not fmap_path.exists() or not cmap_path.exists():
        return None
    try:
        from PIL import Image

        img = Image.open(figure_path)
        W, H = img.size
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not open figure %s: %s", figure_path, exc)
        return None

    fmap = json.loads(fmap_path.read_text("utf-8"))
    cmap = json.loads(cmap_path.read_text("utf-8"))
    rows = cmap.get("components", [])

    component_to_number = fmap.get("component_to_number", {}) or {}
    number_to_components: dict[str, list[str]] = {}
    for cid, num in component_to_number.items():
        number_to_components.setdefault(str(num).strip(), []).append(cid)
    labels = fmap.get("vlm_labels", []) or []

    proj_anchors: dict[str, tuple[float, float]] = {}
    if fproj_path.exists():
        try:
            fproj = json.loads(fproj_path.read_text("utf-8"))
            for a in fproj.get("component_anchors", []) or []:
                cid = a.get("id")
                uv = a.get("figure_uv") or []
                if cid and len(uv) >= 2:
                    proj_anchors[cid] = (float(uv[0]), float(uv[1]))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load figure_projection.json: %s", exc)

    # Index leader lines by label_index.
    leader_by_label_index: dict[int, dict[str, Any]] = {}
    if leaders_path.exists():
        try:
            ld = json.loads(leaders_path.read_text("utf-8"))
            for l in ld.get("leaders", []) or []:
                idx = int(l.get("label_index", -1))
                if idx >= 0 and l.get("method") == "hough":
                    leader_by_label_index[idx] = l
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load leader_lines.json: %s", exc)

    def _label_for(cid: str) -> str:
        for r in rows:
            if r.get("component_id") == cid:
                return r.get("label", cid)
        return cid

    hotspots: list[FigureHotspot] = []
    instance_counter: dict[str, int] = {}  # per component_id
    fp_anchor_used: set[str] = set()  # don't reuse projection anchor across instances

    for label_index, lab in enumerate(labels):
        num = str(lab.get("number") or "").strip()
        pos = lab.get("approximate_position") or []
        if not num or len(pos) < 2:
            continue
        cids = number_to_components.get(num, [])
        if not cids:
            continue  # no claim component bound to this callout
        try:
            label_uv = (float(pos[0]), float(pos[1]))
        except (TypeError, ValueError):
            continue
        label_uv = (max(0.0, min(1.0, label_uv[0])), max(0.0, min(1.0, label_uv[1])))
        label_center_px = _norm_to_px(label_uv, W, H)
        leader_record = leader_by_label_index.get(label_index)
        if leader_record and leader_record.get("line_end_px"):
            label_bbox_px = tuple(
                leader_record.get("label_bbox_px") or (0, 0, 0, 0)
            )
        else:
            label_bbox_px = _bbox_around_centre(label_center_px, W, H, radius_frac=0.022)

        for cid in cids:
            instance_counter[cid] = instance_counter.get(cid, 0) + 1
            instance_id = instance_counter[cid] - 1
            label_text = _label_for(cid) or str(lab.get("description") or "")

            # PART hotspot — leader endpoint if available, else
            # projection anchor (first time only), else label centre.
            part_centre_px: tuple[float, float]
            part_source: str
            part_confidence: float
            part_debug: dict[str, Any] = {"label_index": label_index}
            if leader_record and leader_record.get("line_end_px"):
                end = leader_record["line_end_px"]
                part_centre_px = (float(end[0]), float(end[1]))
                part_source = "leader_endpoint"
                part_confidence = float(leader_record.get("confidence", 0.7))
                part_debug["leader_length_px"] = leader_record.get("length_px")
            elif cid in proj_anchors and cid not in fp_anchor_used:
                u, v = proj_anchors[cid]
                part_centre_px = _norm_to_px((u, v), W, H)
                part_source = "projection_anchor"
                part_confidence = 0.65
                fp_anchor_used.add(cid)
                part_debug["origin"] = "figure_projection.json"
            else:
                part_centre_px = label_center_px
                part_source = "label_center"
                part_confidence = 0.4
                part_debug["origin"] = "fallback to label centre"

            part_bbox_px = _bbox_around_centre(part_centre_px, W, H, radius_frac=0.035)
            hotspots.append(
                FigureHotspot(
                    hotspot_id=f"{cid}__{num}__{instance_id}__part",
                    figure_id=fmap.get("primary_figure", "figure_1"),
                    component_id=cid,
                    callout_number=num,
                    label=label_text,
                    coord_space=COORD_SPACE_IMAGE_PIXEL,
                    image_width_px=W,
                    image_height_px=H,
                    center_px=part_centre_px,
                    bbox_px=part_bbox_px,
                    confidence=part_confidence,
                    source=part_source,
                    hotspot_kind="part",
                    instance_id=instance_id,
                    label_center_px=label_center_px,
                    label_bbox_px=label_bbox_px,
                    debug=part_debug,
                )
            )
            # LABEL hotspot — always emitted at the digit text
            # position so the viewer can show "label vs part" toggles.
            hotspots.append(
                FigureHotspot(
                    hotspot_id=f"{cid}__{num}__{instance_id}__label",
                    figure_id=fmap.get("primary_figure", "figure_1"),
                    component_id=cid,
                    callout_number=num,
                    label=label_text,
                    coord_space=COORD_SPACE_IMAGE_PIXEL,
                    image_width_px=W,
                    image_height_px=H,
                    center_px=label_center_px,
                    bbox_px=label_bbox_px,
                    confidence=0.6,
                    source="label_center",
                    hotspot_kind="label",
                    instance_id=instance_id,
                    label_center_px=label_center_px,
                    label_bbox_px=label_bbox_px,
                    debug={"label_index": label_index},
                )
            )

    return FigureHotspotSet(
        figure_id=fmap.get("primary_figure", "figure_1"),
        figure_path=str(figure_path.relative_to(example_dir)),
        image_width_px=W,
        image_height_px=H,
        hotspots=hotspots,
        notes=(
            "Hotspots are in raw image-pixel coordinates (origin "
            "top-left). Each callout instance gets a part hotspot "
            "(leader endpoint when available) AND a label hotspot. "
            "Repeated callouts (e.g. upper/lower hinge) are preserved "
            "as separate instance_id rows."
        ),
    )


def save_hotspots(hs: FigureHotspotSet, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hs.to_dict(), indent=2), encoding="utf-8")
    return path


def load_hotspots(path: Path) -> FigureHotspotSet:
    return FigureHotspotSet.from_dict(json.loads(path.read_text("utf-8")))


# ---------------------------------------------------------------------------
# Debug overlay
# ---------------------------------------------------------------------------


def render_hotspot_debug_overlay(
    *,
    figure_path: Path,
    hotspots: FigureHotspotSet,
    out_path: Path,
    resolution: int = 1280,
) -> Path:
    """Annotate the figure with the hotspot positions, colour-coded
    by source."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(figure_path).convert("RGB").copy()
    if img.size[0] > resolution:
        scale = resolution / img.size[0]
        img = img.resize(
            (int(img.size[0] * scale), int(img.size[1] * scale)), Image.LANCZOS
        )
    W, H = img.size
    sx = W / max(hotspots.image_width_px, 1)
    sy = H / max(hotspots.image_height_px, 1)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("Helvetica", 12)
    except OSError:
        font = ImageFont.load_default()

    color_by_source = {
        "leader_endpoint": (40, 180, 60),    # green
        "projection_anchor": (40, 80, 220),  # blue
        "median_label": (180, 60, 200),      # purple
        "label_center": (220, 60, 60),       # red
        "crop_center": (220, 140, 30),       # orange
        "manual_override": (140, 80, 200),   # violet
    }
    # Draw label hotspots (smaller, lighter)
    for h in hotspots.hotspots:
        if h.hotspot_kind != "label":
            continue
        cx = h.center_px[0] * sx
        cy = h.center_px[1] * sy
        draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3),
                      outline=(180, 180, 180), width=1)
    # Draw part hotspots (bigger, source-coloured)
    r = 6
    for h in hotspots.hotspots:
        if h.hotspot_kind != "part":
            continue
        cx = h.center_px[0] * sx
        cy = h.center_px[1] * sy
        col = color_by_source.get(h.source, (90, 90, 90))
        draw.ellipse((cx - r, cy - r, cx + r, cy + r),
                      outline=col, width=2)
        # Draw a thin line from label to part to make the leader
        # connection visible in the debug overlay.
        if h.label_center_px is not None:
            lx = h.label_center_px[0] * sx
            ly = h.label_center_px[1] * sy
            draw.line((lx, ly, cx, cy), fill=col + (90,), width=1)
        draw.text((cx + 8, cy - 6),
                  f"{h.component_id} #{h.callout_number}.{h.instance_id}",
                  fill=col, font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


__all__ = [
    "COORD_SPACE_IMAGE_PIXEL",
    "COORD_SPACE_NORMALISED",
    "FigureHotspot",
    "FigureHotspotSet",
    "build_hotspots_for_example",
    "save_hotspots",
    "load_hotspots",
    "render_hotspot_debug_overlay",
]
