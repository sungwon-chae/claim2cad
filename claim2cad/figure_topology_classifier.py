"""V13-C / V13-K — deterministic figure / topology classifier.

Reads claim_map.json + figure_map.json + claim.txt and classifies
the example into:

  view_type   front | side | top | oblique | exploded |
              sectional | schematic | unknown
  topology    door_hinge | self_closing_hinge_mechanism |
              two_plate_hinge | planetary_gear | harmonic_gear |
              differential_gear | rotary_shaft |
              positioning_apparatus | robotic_arm | linkage |
              bracket_mount | housing_panel | unknown
  recommended_scaffold   one of the registered scaffold ids

Pure-keyword + pure-structural rules; no LLM calls. Saves
``figure_classification.json`` next to the example.

V13-K refinement: more specific topologies (positioning
apparatus, self-closing hinge mechanism) come BEFORE the
broader rotary_shaft / door_hinge rules so first-match-wins
no longer swallows them. The classifier now also writes a
``multi_view`` field for examples whose figure obviously
combines sectional + plan views (e.g. planetary gears).
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
    # V13-K: multi-view patents (sectional + plan, etc).
    # Empty list when the example is single-view.
    multi_view: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Keyword tables
# ---------------------------------------------------------------------------

# Order matters — first match wins. Keep more SPECIFIC topologies
# above BROADER ones so a generic 'shaft' or 'door hinge' keyword
# does not swallow a positioning apparatus or self-closing hinge.
_TOPOLOGY_RULES: list[tuple[str, list[str], str]] = [
    # (topology, keywords, recommended_scaffold)
    # ---- V13-K specific topologies (must precede broader rules) ----
    ("self_closing_hinge_mechanism",
     ["self closing hinge", "self-closing hinge",
      "self closing mechanism", "self-closing mechanism",
      "spring loaded closer", "door closer", "hinge closer",
      "hydraulic hinge", "automatic closing hinge"],
     "self_closing_hinge_mechanism"),
    ("positioning_apparatus",
     ["positioning apparatus", "positioning linkage",
      "positioning mechanism",
      "parallelogram structure", "parallelogram linkage",
      "four-arm linkage", "four arm linkage",
      "parallel arm positioning", "parallel-arm positioning",
      "x-y positioner", "xy positioning stage",
      "linear stage"],
     "positioning_apparatus"),
    # ---- V13-C original specific rules ----
    ("door_hinge",
     ["spring loaded hinge", "lift off hinge",
      "pintle pin", "hinge leaf", "hinge bracket",
      "door hinge", "hinge knuckle"],
     "door_hinge"),
    ("two_plate_hinge",
     ["two leaf hinge", "two plate hinge", "concealed hinge"],
     "two_plate_hinge"),
    # planetary now routes to its own scaffold (was rotary_shaft).
    ("planetary_gear",
     ["planetary gear", "epicyclic", "ring gear", "sun gear",
      "planet gear", "planet pinion", "planet carrier",
      "carrier", "annulus"],
     "planetary_gear"),
    ("harmonic_gear",
     ["harmonic gear", "harmonic drive", "wave generator",
      "flexspline"],
     "rotary_shaft"),
    ("differential_gear",
     ["differential gear", "spider gear"],
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
    # ---- Broad fallthrough — must stay LAST so it does not win
    #      against more specific matches ----
    ("rotary_shaft",
     ["transmission", "drive shaft", "rotor", "spindle",
      "bearing assembly", "shaft assembly"],
     "rotary_shaft"),
]


# Topologies whose figures are typically multi-view (sectional +
# plan, sectional + side, etc). Recorded in the classification so
# downstream renders can produce both views.
_MULTI_VIEW_HINTS: dict[str, list[str]] = {
    "planetary_gear": ["sectional", "plan"],
    "harmonic_gear": ["sectional", "plan"],
    "differential_gear": ["sectional", "plan"],
}

# V13-K: phrases must be specific. "section" alone matches
# arm-section-style component labels and incorrectly classified
# US5180955A as sectional, so we require the explicit "view" /
# "cross-section" anchors.
_VIEW_KEYWORDS = {
    "exploded": ["exploded view", "exploded perspective"],
    "sectional": ["sectional view", "cross-section", "cross section",
                   "in section", "sectioned view"],
    "top": ["plan view", "top view", "top plan view"],
    "side": ["side view", "side elevation", "elevation view"],
    "oblique": ["isometric view", "perspective view",
                 "oblique view", "perspective drawing"],
    "schematic": ["schematic view", "schematic diagram"],
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
    # V13-K: record multi-view hint when applicable.
    rep.multi_view = list(_MULTI_VIEW_HINTS.get(matched_topology, []))

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
