"""V13-C — deterministic figure / topology classifier.

Reads claim_map.json + figure_map.json + claim.txt and classifies
the example into:

  view_type   front | side | top | oblique | exploded |
              sectional | schematic | unknown
  topology    door_hinge | rotary_shaft | linkage | bracket_mount |
              housing_panel | exploded | unknown
  recommended_scaffold   one of the registered scaffold ids

Pure-keyword + pure-structural rules; no LLM calls. Saves
``figure_classification.json`` next to the example.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FigureClassification:
    example_id: str
    view_type: str = "unknown"
    topology: str = "unknown"
    recommended_scaffold: str = "fallback_grid"
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Keyword tables
# ---------------------------------------------------------------------------

_TOPOLOGY_RULES: list[tuple[str, list[str], str]] = [
    # (topology, keywords, recommended_scaffold)
    ("door_hinge",
     ["spring loaded hinge", "self closing hinge", "lift off hinge",
      "concealed hinge", "pintle pin", "hinge leaf", "hinge bracket",
      "door hinge", "hinge knuckle"],
     "door_hinge"),
    ("two_plate_hinge",
     ["two leaf hinge", "two plate hinge", "concealed hinge"],
     "two_plate_hinge"),
    ("planetary_gear",
     ["planetary gear", "epicyclic", "ring gear", "sun gear",
      "planet gear", "carrier", "annulus"],
     "rotary_shaft"),
    ("harmonic_gear",
     ["harmonic gear", "harmonic drive", "wave generator",
      "flexspline"],
     "rotary_shaft"),
    ("differential_gear",
     ["differential gear", "spider gear"],
     "rotary_shaft"),
    ("rotary_shaft",
     ["transmission", "shaft", "rotor", "drive shaft", "spindle",
      "bearing assembly"],
     "rotary_shaft"),
    ("robotic_arm",
     ["robotic arm", "robot arm", "manipulator", "wrist",
      "elbow joint", "shoulder", "forearm", "industrial robot"],
     "linkage"),
    ("linkage",
     ["four-bar linkage", "linkage assembly", "pivot link",
      "lever arm"],
     "linkage"),
    ("bracket_mount",
     ["bracket assembly", "mounting bracket", "flange mount"],
     "bracket_mount"),
    ("housing_panel",
     ["housing", "enclosure", "case cover", "panel assembly"],
     "housing_panel"),
]

_VIEW_KEYWORDS = {
    "exploded": ["exploded", "exploded view"],
    "sectional": ["section", "cross-section", "sectional"],
    "top": ["plan view", "top view"],
    "side": ["side view", "elevation"],
    "oblique": ["isometric", "perspective", "oblique"],
    "schematic": ["schematic", "diagram"],
}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify(
    *,
    example_id: str,
    claim_map: dict[str, Any] | None,
    figure_map: dict[str, Any] | None,
    claim_text: str = "",
) -> FigureClassification:
    text_blob_parts = [example_id.replace("_", " "), claim_text]
    if claim_map:
        for r in claim_map.get("components", []):
            text_blob_parts.append(r.get("label", ""))
    text_blob = " ".join(text_blob_parts).lower()

    rep = FigureClassification(example_id=example_id)
    evidence: list[str] = []

    # Topology — first match wins.
    matched_topology: str | None = None
    matched_scaffold: str | None = None
    for topo, kws, scaffold in _TOPOLOGY_RULES:
        for k in kws:
            if k in text_blob:
                evidence.append(f"topology:{topo}:keyword:{k!r}")
                matched_topology = topo
                matched_scaffold = scaffold
                break
        if matched_topology is not None:
            break
    if matched_topology is None:
        matched_topology = "unknown"
        matched_scaffold = "fallback_grid"
        evidence.append("topology:unknown — no keyword match")

    rep.topology = matched_topology
    rep.recommended_scaffold = matched_scaffold or "fallback_grid"

    # View type from figure_map metadata, then keywords.
    view = "unknown"
    if figure_map:
        # Some pipelines record a view_kind field
        vk = figure_map.get("primary_view_kind") or figure_map.get("view_kind")
        if isinstance(vk, str) and vk:
            view = vk
            evidence.append(f"view:{vk}:from_figure_map")
    if view == "unknown":
        for v, kws in _VIEW_KEYWORDS.items():
            if any(k in text_blob for k in kws):
                view = v
                evidence.append(f"view:{v}:keyword")
                break
    if view == "unknown":
        # Default for mechanical patents — most are oblique line drawings
        view = "oblique"
        evidence.append("view:oblique:default_for_mechanical_patent")
    rep.view_type = view

    # Confidence
    n_kw_hits = sum(1 for e in evidence if "keyword" in e)
    rep.confidence = round(min(1.0, 0.3 + 0.25 * n_kw_hits), 3)
    rep.evidence = evidence

    # Notes
    if matched_topology == "unknown":
        rep.notes = "no topology keyword matched; using fallback_grid"
    elif rep.confidence < 0.5:
        rep.notes = "low confidence — single keyword match"

    return rep


def classify_example(example_dir: Path) -> FigureClassification:
    cm_path = example_dir / "claim_map.json"
    fm_path = example_dir / "figure_map.json"
    ct_path = example_dir / "claim.txt"
    cm = json.loads(cm_path.read_text("utf-8")) if cm_path.exists() else None
    fm = json.loads(fm_path.read_text("utf-8")) if fm_path.exists() else None
    ct = ct_path.read_text("utf-8") if ct_path.exists() else ""
    return classify(
        example_id=example_dir.name, claim_map=cm, figure_map=fm,
        claim_text=ct,
    )


def save_classification(rep: FigureClassification, example_dir: Path) -> Path:
    p = example_dir / "figure_classification.json"
    p.write_text(json.dumps(rep.to_dict(), indent=2) + "\n", encoding="utf-8")
    return p


__all__ = [
    "FigureClassification",
    "classify",
    "classify_example",
    "save_classification",
]
