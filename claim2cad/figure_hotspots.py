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
    """One viewer hotspot, in raw image-pixel coordinates."""

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
    source: str = "label"  # "figure_projection" | "median_label" | "label"
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["center_px"] = list(self.center_px)
        d["bbox_px"] = list(self.bbox_px)
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
        hs = [
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
                source=h.get("source", "label"),
                debug=h.get("debug", {}),
            )
            for h in d.get("hotspots", [])
        ]
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

    Sources, in priority order, per claim component:
      1. ``figure_projection.json`` component_anchor (figure_uv) —
         the median over all label occurrences for this component,
         which dampens the duplicate-label problem.
      2. The median (u, v) of all `vlm_labels` whose number maps to
         this component (handles duplicates by averaging).
      3. The single `vlm_labels[i].approximate_position` if only one
         occurrence exists.

    Returns ``None`` when the figure or claim_map is missing.
    """
    figure_path = example_dir / figure_filename
    fmap_path = example_dir / "figure_map.json"
    cmap_path = example_dir / "claim_map.json"
    fproj_path = example_dir / "figure_projection.json"
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
    labels = fmap.get("vlm_labels", []) or []
    label_positions: dict[str, list[tuple[float, float]]] = {}
    for lab in labels:
        num = str(lab.get("number") or "").strip()
        pos = lab.get("approximate_position") or []
        if not num or len(pos) < 2:
            continue
        try:
            uv = (float(pos[0]), float(pos[1]))
        except (TypeError, ValueError):
            continue
        label_positions.setdefault(num, []).append(uv)

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

    def _label_for(cid: str) -> str:
        for r in rows:
            if r.get("component_id") == cid:
                return r.get("label", cid)
        return cid

    label_label_text: dict[str, str] = {
        str(lab.get("number") or "").strip(): str(lab.get("description") or "")
        for lab in labels
    }

    hotspots: list[FigureHotspot] = []
    seen_pairs: set[tuple[str, tuple[float, float]]] = set()
    for cid, num in component_to_number.items():
        num = str(num).strip()
        # Source 1 — figure_projection anchor
        source = "label"
        confidence = 0.5
        debug: dict[str, Any] = {}
        if cid in proj_anchors:
            u, v = proj_anchors[cid]
            source = "figure_projection"
            confidence = 0.85
            debug["origin"] = "figure_projection.json component_anchors"
        else:
            occ = label_positions.get(num, [])
            if len(occ) >= 2:
                # Source 2 — median of duplicates
                u = sum(p[0] for p in occ) / len(occ)
                v = sum(p[1] for p in occ) / len(occ)
                source = "median_label"
                confidence = 0.6
                debug["origin"] = f"median of {len(occ)} label occurrences"
            elif len(occ) == 1:
                # Source 3 — single label
                u, v = occ[0]
                source = "label"
                confidence = 0.45
                debug["origin"] = "single label occurrence"
            else:
                continue
        # Validate within image bounds.
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            logger.debug("Hotspot %s out of bounds: (%.2f, %.2f)", cid, u, v)
            u = max(0.0, min(1.0, u))
            v = max(0.0, min(1.0, v))
        if (cid, (round(u, 3), round(v, 3))) in seen_pairs:
            continue
        seen_pairs.add((cid, (round(u, 3), round(v, 3))))
        centre_px = _norm_to_px((u, v), W, H)
        bbox_px = _bbox_around_centre(centre_px, W, H, radius_frac=0.04)
        hotspots.append(
            FigureHotspot(
                hotspot_id=f"{cid}_{num}",
                figure_id=fmap.get("primary_figure", "figure_1"),
                component_id=cid,
                callout_number=num,
                label=_label_for(cid) or label_label_text.get(num, ""),
                coord_space=COORD_SPACE_IMAGE_PIXEL,
                image_width_px=W,
                image_height_px=H,
                center_px=centre_px,
                bbox_px=bbox_px,
                confidence=confidence,
                source=source,
                debug=debug,
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
            "top-left). The viewer should multiply by displayed_size/"
            "natural_size at render time."
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
        "figure_projection": (40, 80, 220),  # blue
        "median_label": (180, 60, 200),      # purple
        "label": (220, 60, 60),              # red
    }
    r = 6
    for h in hotspots.hotspots:
        cx = h.center_px[0] * sx
        cy = h.center_px[1] * sy
        col = color_by_source.get(h.source, (90, 90, 90))
        draw.ellipse(
            (cx - r, cy - r, cx + r, cy + r),
            outline=col,
            width=2,
        )
        draw.text((cx + 8, cy - 6), h.component_id or h.callout_number,
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
