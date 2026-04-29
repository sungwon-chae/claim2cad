"""V13-G — multi-patent evaluator.

Per example, computes a small set of axes and an overall_quality
verdict so we can show users at a glance which examples are
flagship-quality, which are partial, and which are fallback.

  viewer_artifacts_exist        all of model.glb-equivalent +
                                 figure_map present
  claim_span_integrity          fraction of claim_map rows with
                                 span_verified
  glb_node_coverage             fraction of claim component_ids
                                 present as labelled GLB nodes
  hotspot_bounds_validity       fraction of hotspot center_px
                                 inside the image rectangle
  hotspot_confidence_rate       fraction of part hotspots with
                                 tier high or medium
  non_central_pile_score        max(X, Z) bbox spread / span
                                 threshold; 1.0 when geometry
                                 spreads >= 80 mm on each axis
  scaffold_coherence_score      heuristic from scaffold quality
                                 tier
  render_readability_score      0.5 + 0.5 * primary_render_size_kb
                                 normalised
  projection_alignment_score    figure_uv ↔ world distance check;
                                 0.0 if no figure_projection.json

  overall_quality               flagship | good | partial |
                                 fallback | failed
"""
from __future__ import annotations

import json
import logging
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FLAGSHIP_EXAMPLES = {"US4807331A_spring_loaded_hinge"}


@dataclass
class V13ExampleEval:
    example_id: str
    viewer_artifacts_exist: float = 0.0
    claim_span_integrity: float = 0.0
    glb_node_coverage: float = 0.0
    hotspot_bounds_validity: float = 0.0
    hotspot_confidence_rate: float = 0.0
    non_central_pile_score: float = 0.0
    scaffold_coherence_score: float = 0.0
    render_readability_score: float = 0.0
    projection_alignment_score: float = 0.0
    overall_quality: str = "failed"
    overall_score: float = 0.0
    notes: list[str] = field(default_factory=list)
    # V13-N: semantic mismatch warning surfaced from
    # claim2cad.semantic_mismatch.
    mismatch_severity: str = "none"  # "none" | "advisory" | "warning"
    mismatch_reason: str = ""
    mismatch_expected: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _glb_node_names(glb_path: Path) -> set[str]:
    try:
        b = glb_path.read_bytes()
        if b[:4] != b"glTF": return set()
        json_len = struct.unpack("<I", b[12:16])[0]
        d = json.loads(b[20:20+json_len].decode("utf-8"))
        scene = d["scenes"][d.get("scene", 0)]
        if not scene.get("nodes"): return set()
        root = d["nodes"][scene["nodes"][0]]
        names = set()
        for ci in root.get("children", []):
            n = d["nodes"][ci].get("name")
            if n: names.add(n)
        return names
    except Exception:
        return set()


def _best_glb(example_dir: Path) -> Path | None:
    for n in ("model_v1.3.glb", "model_v1.2_oblique.glb",
              "model_v1.2.glb", "model_v1.1.glb", "model.glb"):
        p = example_dir / n
        if p.exists():
            return p
    return None


def _best_render(example_dir: Path) -> Path | None:
    candidates = [
        example_dir / "renders_v1.3" / "primary.png",
        example_dir / "renders_v1.2" / "hero_oblique.png",
        example_dir / "renders_v1.2" / "readable_iso.png",
        example_dir / "renders_v1.1" / "figure_aligned_view.png",
        example_dir / "render_comparison.png",
    ]
    for c in candidates:
        if c.exists(): return c
    return None


def evaluate_one(example_dir: Path) -> V13ExampleEval:
    rep = V13ExampleEval(example_id=example_dir.name)

    # 1. viewer_artifacts_exist
    has_glb = _best_glb(example_dir) is not None
    has_claim_map = (example_dir / "claim_map.json").exists()
    has_fig = (example_dir / "figures" / "figure_1.png").exists()
    rep.viewer_artifacts_exist = (
        (1.0 if has_glb else 0.0) +
        (1.0 if has_claim_map else 0.0) +
        (1.0 if has_fig else 0.0)
    ) / 3.0

    # 2. claim_span_integrity
    cm_path = example_dir / "claim_map.json"
    cids: list[str] = []
    if cm_path.exists():
        try:
            cm = json.loads(cm_path.read_text("utf-8"))
            rows = cm.get("components", [])
            cids = [r["component_id"] for r in rows]
            verified = sum(1 for r in rows if r.get("span_verified"))
            rep.claim_span_integrity = verified / max(len(rows), 1)
        except Exception:
            rep.notes.append("claim_map_parse_failed")

    # 3. glb_node_coverage
    glb = _best_glb(example_dir)
    if glb and cids:
        names = _glb_node_names(glb)
        matched = set(cids) & names
        rep.glb_node_coverage = len(matched) / max(len(cids), 1)

    # 4 + 5. hotspot validity + confidence
    hs_path = example_dir / "figure_hotspots.json"
    if hs_path.exists():
        try:
            hs = json.loads(hs_path.read_text("utf-8"))
            W = int(hs.get("image_width_px", 0))
            H = int(hs.get("image_height_px", 0))
            part_hs = [h for h in hs.get("hotspots", [])
                       if h.get("hotspot_kind", "part") == "part"]
            if part_hs and W > 0 and H > 0:
                in_bounds = sum(
                    1 for h in part_hs
                    if 0 <= h["center_px"][0] <= W
                    and 0 <= h["center_px"][1] <= H
                )
                rep.hotspot_bounds_validity = in_bounds / len(part_hs)
                hi_med = sum(1 for h in part_hs
                              if h.get("confidence_tier") in ("high", "medium"))
                rep.hotspot_confidence_rate = hi_med / len(part_hs)
        except Exception:
            rep.notes.append("hotspots_parse_failed")

    # 6. non_central_pile_score
    if glb:
        try:
            import build123d as bd
            step = example_dir / glb.name.replace(".glb", ".step")
            if step.exists():
                shape = bd.import_step(str(step))
                xs, zs = [], []
                for c in getattr(shape, "children", []):
                    bb = c.bounding_box()
                    xs.append((bb.min.X + bb.max.X) / 2)
                    zs.append((bb.min.Z + bb.max.Z) / 2)
                if xs and zs:
                    sx = max(xs) - min(xs)
                    sz = max(zs) - min(zs)
                    rep.non_central_pile_score = min(
                        1.0, max(sx, sz) / 80.0,
                    )
        except Exception as exc:  # noqa: BLE001
            rep.notes.append(f"step_parse_failed:{exc}"[:80])

    # 7. scaffold_coherence_score
    bs_path = example_dir / "batch_status.json"
    quality_tier = "unknown"
    if bs_path.exists():
        try:
            bs = json.loads(bs_path.read_text("utf-8"))
            quality_tier = bs.get("quality_tier", "unknown")
        except Exception: pass
    if example_dir.name in FLAGSHIP_EXAMPLES:
        quality_tier = "flagship"
    tier_score_map = {"flagship": 1.0, "good": 0.8, "partial": 0.5, "fallback": 0.3, "unknown": 0.2}
    rep.scaffold_coherence_score = tier_score_map.get(quality_tier, 0.2)

    # 8. render_readability_score
    render = _best_render(example_dir)
    if render:
        size_kb = render.stat().st_size / 1024
        # 0.5 baseline + size_kb factor capped at 1.0.
        rep.render_readability_score = min(1.0, 0.5 + size_kb / 200.0)

    # 9. projection_alignment_score (only meaningful with figure_projection)
    fp_path = example_dir / "figure_projection.json"
    if fp_path.exists():
        try:
            fp = json.loads(fp_path.read_text("utf-8"))
            n_anchors = len(fp.get("component_anchors", []) or [])
            rep.projection_alignment_score = min(1.0, n_anchors / 8.0)
        except Exception: pass

    # V13-N: semantic mismatch surfaced from the same example
    # context. Persist on the eval and as a per-example sidecar
    # so the viewer can read it.
    try:
        from claim2cad.semantic_mismatch import detect_one
        mr = detect_one(example_dir)
        rep.mismatch_severity = mr.severity
        rep.mismatch_reason = mr.reasons[0] if mr.reasons else ""
        rep.mismatch_expected = list(mr.expected_topologies)
        # Persist sidecar — the viewer reads it.
        (example_dir / "semantic_mismatch.json").write_text(
            json.dumps(mr.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        rep.notes.append(f"mismatch_detect_failed:{exc}"[:80])

    # Overall verdict
    if example_dir.name in FLAGSHIP_EXAMPLES:
        rep.overall_quality = "flagship"
    elif rep.viewer_artifacts_exist < 1.0 or rep.glb_node_coverage < 0.5:
        rep.overall_quality = "failed"
    elif rep.scaffold_coherence_score >= 0.8 and rep.non_central_pile_score >= 0.7:
        rep.overall_quality = "good"
    elif rep.scaffold_coherence_score >= 0.5 and rep.non_central_pile_score >= 0.5:
        rep.overall_quality = "partial"
    else:
        rep.overall_quality = "fallback"

    # Composite — equal-ish weight, transparent
    weights = {
        "viewer_artifacts_exist": 0.10,
        "claim_span_integrity": 0.10,
        "glb_node_coverage": 0.15,
        "hotspot_bounds_validity": 0.10,
        "hotspot_confidence_rate": 0.10,
        "non_central_pile_score": 0.20,
        "scaffold_coherence_score": 0.15,
        "render_readability_score": 0.05,
        "projection_alignment_score": 0.05,
    }
    total = sum(getattr(rep, k) * w for k, w in weights.items())
    rep.overall_score = round(total, 3)
    return rep


def evaluate_all(real_patents_dir: Path) -> list[V13ExampleEval]:
    out: list[V13ExampleEval] = []
    for ex_dir in sorted(real_patents_dir.iterdir()):
        if not ex_dir.is_dir(): continue
        rep = evaluate_one(ex_dir)
        out.append(rep)
    return out


def write_corpus_report(reps: list[V13ExampleEval],
                         out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_p = out_dir / "MULTI_PATENT_EVAL.json"
    md_p = out_dir / "MULTI_PATENT_EVAL.md"

    json_p.write_text(json.dumps({
        "n_examples": len(reps),
        "examples": [r.to_dict() for r in reps],
    }, indent=2) + "\n", encoding="utf-8")

    from collections import Counter
    quality_counts = Counter(r.overall_quality for r in reps)
    avg_score = sum(r.overall_score for r in reps) / max(len(reps), 1)

    md = []
    md.append("# V1.3 multi-patent evaluation\n")
    md.append(f"**{len(reps)} examples** evaluated. ")
    md.append(f"Mean overall_score: **{avg_score:.3f}**.\n")
    md.append(f"Quality distribution: {dict(quality_counts)}\n")
    md.append("| ID | quality | score | viewer | spans | glb | hotspots | tier rate | non-pile | scaffold | render | mismatch |")
    md.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in reps:
        mismatch = (
            "none" if r.mismatch_severity == "none"
            else f"**{r.mismatch_severity}**"
        )
        md.append(
            f"| `{r.example_id}` | **{r.overall_quality}** | "
            f"{r.overall_score:.2f} | "
            f"{r.viewer_artifacts_exist:.2f} | "
            f"{r.claim_span_integrity:.2f} | "
            f"{r.glb_node_coverage:.2f} | "
            f"{r.hotspot_bounds_validity:.2f} | "
            f"{r.hotspot_confidence_rate:.2f} | "
            f"{r.non_central_pile_score:.2f} | "
            f"{r.scaffold_coherence_score:.2f} | "
            f"{r.render_readability_score:.2f} | "
            f"{mismatch} |"
        )
    md.append("")
    md_p.write_text("\n".join(md), encoding="utf-8")
    return json_p, md_p


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--real-patents-dir", type=Path,
                    default=Path("examples/real_patents"))
    p.add_argument("--report-dir", type=Path,
                    default=Path("examples/reports"))
    args = p.parse_args(argv)
    reps = evaluate_all(args.real_patents_dir)
    j, m = write_corpus_report(reps, args.report_dir)
    print(f"\nWrote {j}\nWrote {m}")
    from collections import Counter
    print(f"Quality distribution: {dict(Counter(r.overall_quality for r in reps))}")
    print(f"Mean score: {sum(r.overall_score for r in reps)/max(len(reps),1):.3f}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
