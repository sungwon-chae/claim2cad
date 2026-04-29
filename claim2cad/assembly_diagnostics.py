"""Assembly diagnostics — measure how "collage-like" a built model is.

The V11-14 / V11-18 pipeline placed each component independently from
the VLM's per-component pose. Result on US4807331A: 15 of 25 components
end up with bbox centres within 30 mm of origin, the door panel and
fixed frame share Y space, no vertical separation between hinge
clusters. Visually it reads as a central pile, not a hinge-on-door
assembly.

This module quantifies the collage so we can A/B against scaffold-first
layouts. It is non-LLM, deterministic, runs from a STEP file alone.

Metrics:

* ``central_cluster_count`` — number of components whose bbox centres
  sit within ``central_radius_mm`` of origin (lower is better; a real
  door-hinge assembly has the door panel and frame far from origin).
* ``center_spread_mm`` — (stdev_x, stdev_y, stdev_z) of bbox centres.
  A coherent assembly has at least one large stdev (a door panel
  pulls X or Y way out).
* ``pairs_with_overlap`` — fraction of component pairs with bbox
  Jaccard overlap > 0.1. Real assemblies have nested parts but most
  pairs sit far apart.
* ``high_overlap_pairs`` — pairs with Jaccard > 0.5. Each is a likely
  duplicate or aliased sub-assembly.
* ``z_separation_score`` — 0 if all hinge components share the same
  Z range, 1 if there are at least two clusters separated by ≥
  half their largest extent.
* ``panel_separation_score`` — 1 if a "door panel" candidate (large,
  thin) sits on a different plane from a "frame" candidate; 0 if no
  such pair exists. Patterns the assembly against the door-hinge
  archetype.

The output is a ``CollageReport`` that the eval harness can consume
and that ``write_assembly_diagnostics_md`` renders as a human report.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import build123d as bd

logger = logging.getLogger(__name__)


@dataclass
class CollageReport:
    n_components: int
    centres: list[dict[str, Any]] = field(default_factory=list)
    central_cluster_count: int = 0
    central_radius_mm: float = 30.0
    center_spread_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    pairs_with_overlap: int = 0
    pair_overlap_fraction: float = 0.0
    high_overlap_pairs: list[dict[str, Any]] = field(default_factory=list)
    z_separation_score: float = 0.0
    panel_separation_score: float = 0.0
    largest_components: list[dict[str, Any]] = field(default_factory=list)
    collage_score: float = 0.0  # composite: lower is more coherent

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["center_spread_mm"] = list(self.center_spread_mm)
        return d


def _bbox_jaccard(a: dict[str, Any], b: dict[str, Any]) -> float:
    ix0 = max(a["min"][0], b["min"][0])
    iy0 = max(a["min"][1], b["min"][1])
    iz0 = max(a["min"][2], b["min"][2])
    ix1 = min(a["max"][0], b["max"][0])
    iy1 = min(a["max"][1], b["max"][1])
    iz1 = min(a["max"][2], b["max"][2])
    if ix1 <= ix0 or iy1 <= iy0 or iz1 <= iz0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0) * (iz1 - iz0)
    va = (a["max"][0] - a["min"][0]) * (a["max"][1] - a["min"][1]) * (a["max"][2] - a["min"][2])
    vb = (b["max"][0] - b["min"][0]) * (b["max"][1] - b["min"][1]) * (b["max"][2] - b["min"][2])
    union = va + vb - inter
    return inter / union if union > 0 else 0.0


def _z_separation_score(centres: list[dict[str, Any]]) -> float:
    """Return 1 if Z centres form ≥ 2 clusters separated by ≥ half the
    Z range; 0 if all squeezed together."""
    zs = sorted(c["center"][2] for c in centres)
    if len(zs) < 4:
        return 0.0
    z_range = zs[-1] - zs[0]
    if z_range < 1.0:
        return 0.0
    # Find largest gap.
    gaps = [zs[i + 1] - zs[i] for i in range(len(zs) - 1)]
    largest_gap = max(gaps)
    return min(1.0, largest_gap / (z_range * 0.5))


def _panel_separation_score(centres: list[dict[str, Any]]) -> float:
    """Score 1 when there's at least one pair of LARGE flat sheets
    (think door panel + body frame) separated in space by more than
    one panel-thickness."""
    panels = [
        c
        for c in centres
        if max(c["size"]) >= 80.0 and min(c["size"]) <= 15.0
    ]
    if len(panels) < 2:
        return 0.0
    # For each pair of panels, see if their normals (smallest-extent
    # axes) point in directions that put their centres on different
    # planes.
    best = 0.0
    for i in range(len(panels)):
        for j in range(i + 1, len(panels)):
            a = panels[i]
            b = panels[j]
            ai = a["size"].index(min(a["size"]))
            bi = b["size"].index(min(b["size"]))
            if ai != bi:
                continue
            # Distance along the normal axis.
            dist = abs(a["center"][ai] - b["center"][ai])
            min_thick = max(a["size"][ai], b["size"][ai], 1.0)
            score = min(1.0, dist / (min_thick * 4.0))
            if score > best:
                best = score
    return best


def _component_bboxes(shape: bd.Compound) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for child in shape.children:
        cid = getattr(child, "label", "") or ""
        if not cid:
            continue
        bb = child.bounding_box()
        out.append(
            {
                "id": cid,
                "min": (bb.min.X, bb.min.Y, bb.min.Z),
                "max": (bb.max.X, bb.max.Y, bb.max.Z),
                "center": (
                    (bb.min.X + bb.max.X) / 2.0,
                    (bb.min.Y + bb.max.Y) / 2.0,
                    (bb.min.Z + bb.max.Z) / 2.0,
                ),
                "size": (
                    bb.max.X - bb.min.X,
                    bb.max.Y - bb.min.Y,
                    bb.max.Z - bb.min.Z,
                ),
            }
        )
    return out


def evaluate_collage(
    shape: bd.Compound,
    *,
    central_radius_mm: float = 30.0,
) -> CollageReport:
    centres = _component_bboxes(shape)
    n = len(centres)
    rep = CollageReport(n_components=n, centres=centres, central_radius_mm=central_radius_mm)
    if n == 0:
        return rep
    # central_cluster_count
    near = [
        c
        for c in centres
        if math.sqrt(sum(x * x for x in c["center"])) < central_radius_mm
    ]
    rep.central_cluster_count = len(near)
    # center_spread_mm
    if n >= 2:
        rep.center_spread_mm = (
            statistics.stdev(c["center"][0] for c in centres),
            statistics.stdev(c["center"][1] for c in centres),
            statistics.stdev(c["center"][2] for c in centres),
        )
    # pairwise overlap
    high: list[dict[str, Any]] = []
    overlap_pairs = 0
    total_pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            total_pairs += 1
            jac = _bbox_jaccard(centres[i], centres[j])
            if jac > 0.10:
                overlap_pairs += 1
                if jac > 0.5:
                    high.append(
                        {
                            "a": centres[i]["id"],
                            "b": centres[j]["id"],
                            "jaccard": round(jac, 3),
                        }
                    )
    rep.pairs_with_overlap = overlap_pairs
    rep.pair_overlap_fraction = overlap_pairs / max(total_pairs, 1)
    rep.high_overlap_pairs = sorted(high, key=lambda h: -h["jaccard"])[:10]
    # z_separation
    rep.z_separation_score = _z_separation_score(centres)
    # panel_separation
    rep.panel_separation_score = _panel_separation_score(centres)
    # largest components
    largest = sorted(
        centres, key=lambda c: -max(c["size"]) * sum(c["size"]) / 3.0
    )[:5]
    rep.largest_components = largest

    # composite collage_score: lower is more coherent.
    # Heavy penalty for many components stuck near origin and for
    # absent panel/Z separation.
    central_pct = rep.central_cluster_count / n
    rep.collage_score = round(
        0.4 * central_pct
        + 0.2 * (1.0 - rep.z_separation_score)
        + 0.2 * (1.0 - rep.panel_separation_score)
        + 0.2 * rep.pair_overlap_fraction,
        3,
    )
    return rep


def write_assembly_diagnostics_md(rep: CollageReport, out_path: Path) -> Path:
    lines: list[str] = []
    lines.append("# Assembly diagnostics\n")
    lines.append(
        f"**collage_score: {rep.collage_score:.3f}** (lower = more coherent)\n"
    )
    lines.append("## Summary\n")
    lines.append(f"- components: **{rep.n_components}**")
    lines.append(
        f"- centres within {rep.central_radius_mm:.0f} mm of origin: "
        f"**{rep.central_cluster_count}/{rep.n_components}**"
    )
    sx, sy, sz = rep.center_spread_mm
    lines.append(
        f"- centre spread (stdev mm): X={sx:.1f}  Y={sy:.1f}  Z={sz:.1f}"
    )
    lines.append(
        f"- pair bbox overlap > 0.10: "
        f"**{rep.pairs_with_overlap}** pairs "
        f"({rep.pair_overlap_fraction*100:.1f}%)"
    )
    lines.append(
        f"- z_separation_score: {rep.z_separation_score:.3f}  "
        f"(1.0 = clusters separated, 0.0 = all squeezed together)"
    )
    lines.append(
        f"- panel_separation_score: {rep.panel_separation_score:.3f}  "
        f"(1.0 = door + frame on different planes)"
    )
    lines.append("")
    lines.append("## Largest components")
    lines.append("| id | size mm | centre mm |")
    lines.append("|---|---|---|")
    for c in rep.largest_components:
        size = "×".join(f"{v:.0f}" for v in c["size"])
        cen = ", ".join(f"{v:.1f}" for v in c["center"])
        lines.append(f"| `{c['id']}` | {size} | ({cen}) |")
    lines.append("")
    lines.append("## High-overlap pairs (Jaccard > 0.5)")
    if rep.high_overlap_pairs:
        for p in rep.high_overlap_pairs:
            lines.append(f"- `{p['a']}` ↔ `{p['b']}` (jaccard={p['jaccard']:.2f})")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## What a coherent door-hinge assembly looks like\n")
    lines.append(
        "- A door panel and a fixed-frame panel each ≥ 80 mm in two\n"
        "  axes and ≤ 15 mm thick, on **different planes** "
        "(panel_separation ≥ 0.5)."
    )
    lines.append(
        "- Two distinct hinge clusters (upper / lower) separated by\n"
        "  ≥ half the assembly Z range (z_separation ≥ 0.5)."
    )
    lines.append(
        "- Most components ≥ 30 mm from origin (central_cluster ≤ 0.4)."
    )
    lines.append(
        "- Pairwise bbox overlap < 25 %.\n"
    )
    lines.append("## Per-component centres\n")
    lines.append("| id | centre | size |")
    lines.append("|---|---|---|")
    for c in rep.centres:
        cen = "(" + ", ".join(f"{v:.1f}" for v in c["center"]) + ")"
        sz = "×".join(f"{v:.0f}" for v in c["size"])
        lines.append(f"| `{c['id']}` | {cen} | {sz} |")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def diagnose_step(step_path: Path) -> CollageReport:
    shape = bd.import_step(str(step_path))
    return evaluate_collage(shape)


__all__ = [
    "CollageReport",
    "evaluate_collage",
    "diagnose_step",
    "write_assembly_diagnostics_md",
]
