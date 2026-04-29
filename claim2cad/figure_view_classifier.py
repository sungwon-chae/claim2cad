"""Detect what kind of engineering view a patent figure is.

Patent figures aren't uniformly top views. Most assembled-mechanism
figures are isometric or "elevation" (front-like) views; some are
sectional cuts; some show two states (closed + lifted-off) overlaid.
The reconstruction strategy depends on this classification:

* **top** — extrude along +Z (out of page).
* **front / side** — extrude along the perpendicular world axis.
* **isometric / exploded** — combine multiple per-component view hints
  rather than trusting a single projection.
* **sectional** — silhouette is a half-section; mirror across the
  cutting plane.

This module makes one Opus 4.7 vision call per figure and caches the
result on disk so it never repeats. The classification then drives
:mod:`claim2cad.shape_inference` and :mod:`claim2cad.sketch_to_extrusion`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from claim2cad.llm_vision import vision_completion

logger = logging.getLogger(__name__)


@dataclass
class FigureViewReport:
    """One classification per figure."""

    figure_id: str
    view_kind: str = "isometric"  # top|front|side|isometric|exploded|sectional|other
    main_axis: str = "Z"  # "X" | "Y" | "Z" — which world axis is the figure's "page-out" direction
    states_shown: list[str] = field(default_factory=list)  # e.g. ["closed", "lifted-off"]
    confidence: float = 0.5
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FigureViewReport":
        return cls(
            figure_id=d.get("figure_id", ""),
            view_kind=d.get("view_kind", "isometric"),
            main_axis=d.get("main_axis", "Z"),
            states_shown=list(d.get("states_shown", [])),
            confidence=float(d.get("confidence", 0.5)),
            notes=str(d.get("notes", "")),
            raw=d.get("raw", {}),
        )


_SYSTEM_PROMPT = (
    "You are classifying a patent line drawing for downstream 3D "
    "reconstruction. Output strict JSON. The reconstructor needs to know "
    "WHICH axis is perpendicular to the page (so it knows which way to "
    "extrude), WHETHER the drawing is a section cut, and WHETHER multiple "
    "states are overlaid in the same image."
)


_USER_TEMPLATE = """Classify this patent figure for 3D reconstruction.

Patent: {patent_title}
Figure id: {figure_id}

Return JSON with EXACTLY this structure:
{{
  "view_kind": "<one of: top, front, side, isometric, exploded, sectional, other>",
  "main_axis": "<one of X, Y, Z — the axis perpendicular to the drawing plane>",
  "states_shown": ["<state name>", ...],
  "confidence": <float 0-1>,
  "notes": "<one short sentence on the reasoning>"
}}

Definitions:
- top: looking straight down. main_axis = Z.
- front / side: orthographic elevation. main_axis = Y or X.
- isometric: 3-axis perspective.
- exploded: components separated for clarity along an axis.
- sectional: a cutting plane is shown (hatched cross-section).
- states_shown: list any visible alternate positions, like
  ["closed", "lifted-off"] or ["assembled", "exploded"]. Empty list if
  only one state is shown.
"""


def classify_figure(
    *,
    figure_path: Path,
    patent_title: str = "",
    figure_id: str | None = None,
    cache_path: Path | None = None,
    task_type: str = "v11_figure_view_classify",
) -> FigureViewReport:
    """Classify the figure. Returns the cached report when ``cache_path``
    exists; otherwise calls the VLM and writes the cache."""
    figure_path = Path(figure_path)
    fid = figure_id or figure_path.stem
    if cache_path is not None and cache_path.exists():
        try:
            data = json.loads(cache_path.read_text("utf-8"))
            logger.info("Using cached figure-view classification at %s", cache_path)
            return FigureViewReport.from_dict(data)
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not load cache at %s — re-classifying", cache_path)

    user = _USER_TEMPLATE.format(
        patent_title=patent_title or "(unknown)",
        figure_id=fid,
    )
    raw = vision_completion(
        image_path=figure_path,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user,
        task_type=task_type,
    )
    report = FigureViewReport(
        figure_id=fid,
        view_kind=str(raw.get("view_kind", "isometric")).strip().lower() or "isometric",
        main_axis=str(raw.get("main_axis", "Z")).strip().upper() or "Z",
        states_shown=[str(s) for s in (raw.get("states_shown") or []) if s],
        confidence=float(raw.get("confidence", 0.5)),
        notes=str(raw.get("notes", "")),
        raw=raw,
    )
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report


__all__ = ["FigureViewReport", "classify_figure"]
