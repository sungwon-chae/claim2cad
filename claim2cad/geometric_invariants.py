"""Geometric invariants — deterministic CADFusion-style reward signals.

The CADFusion paper (Wang et al., ICML 2025, arXiv:2501.19054) trains an
LLM with a Visual Feedback stage that rewards parametric sequences whose
RENDERS look correct. We can't retrain the LLM, but at inference time we
can compute *non-VLM* reward signals that are deterministic, free, and
catch obviously-wrong assemblies before they go to the VLM. These
signals also let us pick best-of-N candidates without burning a VLM
call per candidate.

Each invariant returns a float in [0, 1] (1 = pass, 0 = fail). The
composite reward is a weighted sum.

Implemented invariants:
  * ``pin_through_holes``     — pintle pin's central axis passes through
                                a numerical hole region in every "leg" /
                                "extension" / "leaf_flange" component
                                of the assembly.
  * ``link_nests_in_main``    — the link's bbox sits inside the main
                                member's extension gap.
  * ``door_wraps_assembly``   — the door-half U-channel encloses some of
                                the body-half (sidewalls bracket the
                                main bracket in Y).
  * ``bbox_sane``             — overall assembly fits a reasonable
                                envelope (≤ 250mm on any axis).
  * ``no_obvious_overlap``    — no two named children have >70% bbox
                                overlap (catches degenerate placements).

Each invariant is best-effort: if it cannot extract the components it
expects, it returns 0.5 (uncertain) rather than 0 or 1, so missing
labels don't penalise differently-built assemblies.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable

import build123d as bd

logger = logging.getLogger(__name__)


@dataclass
class InvariantReport:
    """Per-invariant result; the composite reward sums weighted scores."""

    pin_through_holes: float = 0.5
    link_nests_in_main: float = 0.5
    door_wraps_assembly: float = 0.5
    bbox_sane: float = 0.5
    no_obvious_overlap: float = 0.5
    notes: list[str] = field(default_factory=list)

    def composite(
        self,
        weights: dict[str, float] | None = None,
    ) -> float:
        """Weighted composite in [0, 1]. Default weights match the order
        in which invariants matter for hinge-like assemblies."""
        w = weights or {
            "pin_through_holes": 0.40,
            "link_nests_in_main": 0.15,
            "door_wraps_assembly": 0.10,
            "bbox_sane": 0.15,
            "no_obvious_overlap": 0.20,
        }
        total_w = sum(w.values()) or 1.0
        return (
            w["pin_through_holes"] * self.pin_through_holes
            + w["link_nests_in_main"] * self.link_nests_in_main
            + w["door_wraps_assembly"] * self.door_wraps_assembly
            + w["bbox_sane"] * self.bbox_sane
            + w["no_obvious_overlap"] * self.no_obvious_overlap
        ) / total_w

    def as_dict(self) -> dict[str, float | list[str]]:
        return {
            "pin_through_holes": self.pin_through_holes,
            "link_nests_in_main": self.link_nests_in_main,
            "door_wraps_assembly": self.door_wraps_assembly,
            "bbox_sane": self.bbox_sane,
            "no_obvious_overlap": self.no_obvious_overlap,
            "composite": round(self.composite(), 3),
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _label(s: bd.Part | bd.Compound) -> str:
    return getattr(s, "label", "") or ""


def _walk(solid: bd.Compound | bd.Part) -> Iterable[bd.Part | bd.Compound]:
    """Yield every part with a non-empty label, recursing into compounds."""
    if not _label(solid):
        # still recurse into children
        children = list(getattr(solid, "children", []) or [])
        for c in children:
            yield from _walk(c)
        return
    yield solid
    children = list(getattr(solid, "children", []) or [])
    for c in children:
        yield from _walk(c)


def _find_first(solid: bd.Compound, *needles: str) -> bd.Part | bd.Compound | None:
    """Find the first child (recursively) whose label contains ANY needle."""
    needles_l = [n.lower() for n in needles]
    for s in _walk(solid):
        lab = _label(s).lower()
        if any(n in lab for n in needles_l):
            return s
    return None


def _find_all(solid: bd.Compound, *needles: str) -> list[bd.Part | bd.Compound]:
    needles_l = [n.lower() for n in needles]
    out = []
    for s in _walk(solid):
        lab = _label(s).lower()
        if any(n in lab for n in needles_l):
            out.append(s)
    return out


def _bbox_overlap_ratio(a: bd.Part, b: bd.Part) -> float:
    """Return Jaccard-style intersection over UNION (so small-inside-big
    nesting only scores high if the volumes are similar size). This is
    much friendlier to intentionally nested CAD assemblies (pin inside
    bracket, link inside main) than the intersection-over-min variant."""
    ba = a.bounding_box()
    bb = b.bounding_box()
    ix0 = max(ba.min.X, bb.min.X)
    iy0 = max(ba.min.Y, bb.min.Y)
    iz0 = max(ba.min.Z, bb.min.Z)
    ix1 = min(ba.max.X, bb.max.X)
    iy1 = min(ba.max.Y, bb.max.Y)
    iz1 = min(ba.max.Z, bb.max.Z)
    if ix1 <= ix0 or iy1 <= iy0 or iz1 <= iz0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0) * (iz1 - iz0)
    va = (ba.max.X - ba.min.X) * (ba.max.Y - ba.min.Y) * (ba.max.Z - ba.min.Z)
    vb = (bb.max.X - bb.min.X) * (bb.max.Y - bb.min.Y) * (bb.max.Z - bb.min.Z)
    if va <= 0 or vb <= 0:
        return 0.0
    union = va + vb - inter
    return inter / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Individual invariants
# ---------------------------------------------------------------------------


def check_pin_through_holes(solid: bd.Compound) -> tuple[float, str]:
    """Score: fraction of "leg / extension / flange / leaf" components
    whose bbox the pin's central axis passes through.

    The pin is identified by a label containing "pin" or "pintle".
    Hole-bearing components are anything labelled "extension", "leg", or
    "leaf_flange". For each such component we check whether the line
    along the pin's long axis (Z) at the pin's (x, y) intersects the
    component's bbox in Z.
    """
    pin = _find_first(solid, "pintle_pin", "pin")
    if pin is None:
        return 0.5, "no pin labelled — invariant inconclusive"
    pin_bb = pin.bounding_box()
    # Identify pin axis: assume axial = the longest dimension.
    sx = pin_bb.max.X - pin_bb.min.X
    sy = pin_bb.max.Y - pin_bb.min.Y
    sz = pin_bb.max.Z - pin_bb.min.Z
    longest = max(sx, sy, sz)
    if longest == sx:
        axis = "X"
    elif longest == sy:
        axis = "Y"
    else:
        axis = "Z"
    cx = (pin_bb.min.X + pin_bb.max.X) / 2
    cy = (pin_bb.min.Y + pin_bb.max.Y) / 2
    cz = (pin_bb.min.Z + pin_bb.max.Z) / 2

    holes = _find_all(
        solid, "extension", "leg", "leaf_flange", "knuckle"
    )
    # De-dup pin from holes (a label might match both)
    holes = [h for h in holes if h is not pin]
    if not holes:
        return 0.5, "no hole-bearing components labelled — inconclusive"

    pin_radius = max(sx, sy, sz) - longest  # not great; use min instead
    pin_radius = min(sx, sy) / 2.0 if axis == "Z" else min(sx, sz) / 2.0
    # We treat the axis as a thin line (no radius check) — close enough.

    threaded = 0
    for h in holes:
        hb = h.bounding_box()
        if axis == "Z":
            # Pin axis is (cx, cy, *); the hole's bbox must contain (cx, cy)
            # in XY and span some range in Z that the pin also spans.
            if (hb.min.X - 1.0 <= cx <= hb.max.X + 1.0) and (
                hb.min.Y - 1.0 <= cy <= hb.max.Y + 1.0
            ):
                # Pin Z range overlaps hole Z range?
                if pin_bb.max.Z >= hb.min.Z and pin_bb.min.Z <= hb.max.Z:
                    threaded += 1
        elif axis == "X":
            if (hb.min.Y - 1.0 <= cy <= hb.max.Y + 1.0) and (
                hb.min.Z - 1.0 <= cz <= hb.max.Z + 1.0
            ):
                if pin_bb.max.X >= hb.min.X and pin_bb.min.X <= hb.max.X:
                    threaded += 1
        else:  # Y
            if (hb.min.X - 1.0 <= cx <= hb.max.X + 1.0) and (
                hb.min.Z - 1.0 <= cz <= hb.max.Z + 1.0
            ):
                if pin_bb.max.Y >= hb.min.Y and pin_bb.min.Y <= hb.max.Y:
                    threaded += 1
    score = threaded / len(holes)
    return score, f"pin axis {axis}; threaded {threaded}/{len(holes)} hole components"


def check_link_nests_in_main(solid: bd.Compound) -> tuple[float, str]:
    """Score 1 if the inner U-link's bbox sits inside the main member's
    extension gap (i.e. link Z extent < gap between main upper and lower
    extensions). 0 if the link is taller than the available slot."""
    link = _find_first(solid, "u_shaped_link", "link_member")
    main = _find_first(solid, "main_member", "main_bracket")
    if link is None or main is None:
        return 0.5, "link or main not labelled"
    lb = link.bounding_box()
    mb = main.bounding_box()
    link_z_span = lb.max.Z - lb.min.Z
    main_z_span = mb.max.Z - mb.min.Z
    if main_z_span <= 0:
        return 0.5, "main z span 0"
    ratio = link_z_span / main_z_span
    # A nicely-nested link has ratio ~ 0.5-0.85; way more than that means
    # it can't fit between extensions.
    if ratio < 0.95:
        return 1.0, f"link/main z ratio {ratio:.2f} (good)"
    return max(0.0, 1.0 - (ratio - 0.95) * 5), f"link/main z ratio {ratio:.2f} (tight)"


def check_door_wraps_assembly(solid: bd.Compound) -> tuple[float, str]:
    """Score 1 if door-half's bbox in Y wraps the main member's bbox in Y
    — i.e. the door channel encloses the body-half from outside."""
    door = _find_first(solid, "door_half", "bight_wall", "door_channel")
    main = _find_first(solid, "main_member", "main_bracket")
    if door is None or main is None:
        return 0.5, "door or main not labelled"
    db = door.bounding_box()
    mb = main.bounding_box()
    door_y_span = db.max.Y - db.min.Y
    main_y_span = mb.max.Y - mb.min.Y
    if door_y_span >= main_y_span * 0.9:
        return 1.0, f"door y {door_y_span:.1f} >= main y {main_y_span:.1f}"
    return main_y_span and (door_y_span / main_y_span) or 0.0, (
        f"door y {door_y_span:.1f} < main y {main_y_span:.1f}"
    )


def check_bbox_sane(solid: bd.Compound, *, max_extent_mm: float = 250.0) -> tuple[float, str]:
    """Score 1 if no axis exceeds ``max_extent_mm``, gracefully degrading."""
    bb = solid.bounding_box()
    sx = bb.max.X - bb.min.X
    sy = bb.max.Y - bb.min.Y
    sz = bb.max.Z - bb.min.Z
    longest = max(sx, sy, sz)
    if longest <= max_extent_mm:
        return 1.0, f"bbox {sx:.0f}x{sy:.0f}x{sz:.0f} OK"
    return max(0.0, 1.0 - (longest - max_extent_mm) / max_extent_mm), (
        f"bbox {sx:.0f}x{sy:.0f}x{sz:.0f} (longest {longest:.0f} > {max_extent_mm})"
    )


def check_no_obvious_overlap(
    solid: bd.Compound, *, threshold: float = 0.95
) -> tuple[float, str]:
    """Penalise two labelled top-level children whose bboxes are nearly
    identical (>95% overlap of the smaller bbox).

    Hinge-like assemblies *intentionally* nest parts inside each other
    (pin inside main, link inside main, door wrapping main), so a
    relaxed threshold is correct: only flag when two parts are so
    coincident they look like the same component duplicated.
    """
    children = [c for c in (solid.children or []) if _label(c)]
    if len(children) < 2:
        return 1.0, "fewer than 2 top-level children"
    pairs_checked = 0
    bad_pairs = 0
    bad_examples: list[tuple[str, str, float]] = []
    for i in range(len(children)):
        for j in range(i + 1, len(children)):
            pairs_checked += 1
            r = _bbox_overlap_ratio(children[i], children[j])
            if r > threshold:
                bad_pairs += 1
                if len(bad_examples) < 3:
                    bad_examples.append(
                        (_label(children[i]), _label(children[j]), r)
                    )
    if pairs_checked == 0:
        return 0.5, "no pairs checked"
    score = 1.0 - (bad_pairs / pairs_checked)
    if bad_examples:
        ex = "; ".join(f"{a}~{b}({r:.2f})" for a, b, r in bad_examples)
        return score, f"{bad_pairs}/{pairs_checked} pairs >{threshold:.0%}: {ex}"
    return score, f"{bad_pairs}/{pairs_checked} pairs > {threshold:.0%}"


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def evaluate_invariants(solid: bd.Compound) -> InvariantReport:
    rep = InvariantReport()
    try:
        rep.pin_through_holes, n1 = check_pin_through_holes(solid)
        rep.notes.append(f"pin_through_holes: {n1}")
    except Exception as exc:  # noqa: BLE001
        rep.notes.append(f"pin_through_holes errored: {exc}")
    try:
        rep.link_nests_in_main, n2 = check_link_nests_in_main(solid)
        rep.notes.append(f"link_nests_in_main: {n2}")
    except Exception as exc:  # noqa: BLE001
        rep.notes.append(f"link_nests_in_main errored: {exc}")
    try:
        rep.door_wraps_assembly, n3 = check_door_wraps_assembly(solid)
        rep.notes.append(f"door_wraps_assembly: {n3}")
    except Exception as exc:  # noqa: BLE001
        rep.notes.append(f"door_wraps_assembly errored: {exc}")
    try:
        rep.bbox_sane, n4 = check_bbox_sane(solid)
        rep.notes.append(f"bbox_sane: {n4}")
    except Exception as exc:  # noqa: BLE001
        rep.notes.append(f"bbox_sane errored: {exc}")
    try:
        rep.no_obvious_overlap, n5 = check_no_obvious_overlap(solid)
        rep.notes.append(f"no_obvious_overlap: {n5}")
    except Exception as exc:  # noqa: BLE001
        rep.notes.append(f"no_obvious_overlap errored: {exc}")
    return rep


__all__ = [
    "InvariantReport",
    "evaluate_invariants",
    "check_pin_through_holes",
    "check_link_nests_in_main",
    "check_door_wraps_assembly",
    "check_bbox_sane",
    "check_no_obvious_overlap",
]
