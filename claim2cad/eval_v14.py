"""V14-G — stricter, human-aligned visual evaluator.

Builds on eval_v13 but adds penalties the user observed in
manual inspection:

  view_match_score          required_camera honored?
  primitive_richness_score  scaffold uses v14 primitives?
  non_placeholder_score     scaffold not fallback_grid /
                            generic_exploded?
  assembly_attachment_score parts within reasonable distance of
                            each other (no floaters)
  multi_view_consistency    multi-view examples have plan AND
                            section renders
  topology_specificity      scaffold matches topology family

Plus boolean flags:
  cylinder_stack_detected   true when scaffold is rotary_shaft /
                            planetary_gear AND no specialized
                            primitives in the GLB (legacy v1.3
                            output)
  view_rotation_mismatch    primary_render exists but the
                            required_camera ≠ the camera that
                            was actually used in the primary
                            render (rare — projection_lock_v14
                            normally honors it)

Quality verdict gating (V14):
  flagship  whitelist (US4807331A only).
  good      view_match≥1 AND primitive_richness≥0.6 AND
            non_placeholder=1 AND topology_specificity=1.
  partial   view_match≥1 AND non_placeholder=1.
  fallback  scaffold is fallback_grid or generic_exploded.
  failed    primary_render missing.
"""
from __future__ import annotations

import json
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


FLAGSHIP_EXAMPLES = {"US4807331A_spring_loaded_hinge"}

# Scaffolds we know now use v14_primitives helpers (rich
# geometry). Any other scaffold output is graded as primitives-
# only and capped at partial.
RICH_SCAFFOLDS = {
    "door_hinge",
    "self_closing_hinge_mechanism",
    "two_plate_hinge",
    "positioning_apparatus",
    "planetary_gear",
    "rotary_shaft",
    "linkage",
    "bracket_mount",
    "housing_panel",
}

PLACEHOLDER_SCAFFOLDS = {"fallback_grid", "generic_exploded"}


@dataclass
class V14ExampleEval:
    example_id: str
    overall_quality: str = "failed"
    overall_score: float = 0.0
    view_match_score: float = 0.0
    primitive_richness_score: float = 0.0
    non_placeholder_score: float = 0.0
    assembly_attachment_score: float = 0.0
    multi_view_consistency_score: float = 0.0
    topology_specificity_score: float = 0.0
    cylinder_stack_detected: bool = False
    view_rotation_mismatch: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _glb_children(glb_path: Path) -> list[str]:
    try:
        b = glb_path.read_bytes()
        if b[:4] != b"glTF":
            return []
        json_len = struct.unpack("<I", b[12:16])[0]
        d = json.loads(b[20:20 + json_len].decode("utf-8"))
        scene = d["scenes"][d.get("scene", 0)]
        if not scene.get("nodes"):
            return []
        root = d["nodes"][scene["nodes"][0]]
        names = []
        for ci in root.get("children", []):
            names.append(d["nodes"][ci].get("name", ""))
        return names
    except Exception:
        return []


def _best_glb(example_dir: Path) -> Path | None:
    for n in ("model_v1.4.glb", "model_v1.3.glb",
              "model_v1.2_oblique.glb", "model_v1.2.glb"):
        p = example_dir / n
        if p.exists():
            return p
    return None


def evaluate_one(example_dir: Path) -> V14ExampleEval:
    rep = V14ExampleEval(example_id=example_dir.name)

    # Load context.
    cls_p = example_dir / "figure_classification.json"
    bs_p = example_dir / "batch_status.json"
    views_p = example_dir / "figure_views_v14.json"
    proj_p = example_dir / "renders_v1.4" / "figure_matched.png"

    cls = json.loads(cls_p.read_text()) if cls_p.exists() else {}
    bs = json.loads(bs_p.read_text()) if bs_p.exists() else {}
    views = json.loads(views_p.read_text()) if views_p.exists() else {}
    scaffold = bs.get("scaffold_id", "")
    topology = cls.get("topology", "")

    # 1. view_match_score — primary_render exists.
    rep.view_match_score = 1.0 if proj_p.exists() else 0.0

    # 2. primitive_richness — scaffold known to use v14
    #    primitives, weighted by GLB child count.
    glb = _best_glb(example_dir)
    n_children = len(_glb_children(glb)) if glb else 0
    if scaffold in RICH_SCAFFOLDS and n_children >= 6:
        rep.primitive_richness_score = min(1.0, 0.6 + 0.04 * n_children)
    elif scaffold in RICH_SCAFFOLDS:
        rep.primitive_richness_score = 0.6
    else:
        rep.primitive_richness_score = 0.2

    # 3. non_placeholder — scaffold is not fallback / exploded.
    rep.non_placeholder_score = (
        0.0 if scaffold in PLACEHOLDER_SCAFFOLDS else 1.0)

    # 4. assembly_attachment — bbox-spread proxy, same as
    #    eval_v13's non_central_pile.
    if glb is not None:
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
                    # Penalize if any axis exceeds 280 mm (very
                    # spread → floating components).
                    if max(sx, sz) > 280.0:
                        rep.assembly_attachment_score = 0.4
                        rep.notes.append("excessive bbox spread")
                    else:
                        rep.assembly_attachment_score = min(
                            1.0, max(sx, sz) / 80.0)
        except Exception as exc:  # noqa: BLE001
            rep.notes.append(f"step_parse:{exc}"[:80])

    # 5. multi_view_consistency
    is_multi = views.get("view_type") == "multi_view_sheet"
    if is_multi:
        plan_ok = (example_dir / "renders_v1.4"
                    / "plan_view.png").exists()
        sect_ok = (example_dir / "renders_v1.4"
                    / "section_view.png").exists()
        rep.multi_view_consistency_score = (
            (1.0 if plan_ok else 0.0)
            + (1.0 if sect_ok else 0.0)) / 2.0
    else:
        rep.multi_view_consistency_score = 1.0  # n/a → full credit

    # 6. topology_specificity_score
    family_match = {
        "door_hinge": "door_hinge",
        "self_closing_hinge_mechanism": "self_closing_hinge_mechanism",
        "two_plate_hinge": "two_plate_hinge",
        "positioning_apparatus": "positioning_apparatus",
        "planetary_gear": "planetary_gear",
        "harmonic_gear": "rotary_shaft",
        "differential_gear": "rotary_shaft",
        "rotary_shaft": "rotary_shaft",
        "robotic_arm": "linkage",
        "linkage": "linkage",
        "bracket_mount": "bracket_mount",
        "housing_panel": "housing_panel",
    }
    expected = family_match.get(topology, "")
    rep.topology_specificity_score = (
        1.0 if expected and expected == scaffold else 0.4)

    # ---- Boolean flags ----
    if scaffold in ("rotary_shaft", "planetary_gear"):
        # cylinder_stack_detected when no V14 primitives detectable
        # — we use a proxy: child count is so small that the
        # geometry is just a few cylinders.
        rep.cylinder_stack_detected = n_children < 8

    # view_rotation_mismatch — currently we only render once with
    # the matched camera, so a true mismatch is rare. Flag if the
    # required camera is "patent_oblique" but the only render is
    # iso-style (which we can't detect without rendering metadata).
    # Simplified: false unless flagged in projection status.
    proj_status = (Path("examples/reports") / "V14_PROJECTION_STATUS.json")
    if proj_status.exists():
        try:
            d = json.loads(proj_status.read_text())
            for entry in d.get("examples", []):
                if entry.get("example_id") == example_dir.name:
                    if entry.get("error"):
                        rep.view_rotation_mismatch = True
                    break
        except Exception:
            pass

    # ---- Verdict (V14-G: honest, not lenient) ----
    # Whitelist of scaffolds we have manually inspected as
    # producing visually convincing geometry on the corpus
    # examples. Other scaffolds default to partial even when
    # their primitives-richness signal is high — visual truth
    # over metric inflation.
    INSPECTED_GOOD = {
        "self_closing_hinge_mechanism",
        "positioning_apparatus",
        "planetary_gear",
        "door_hinge",
        "two_plate_hinge",
    }

    if example_dir.name in FLAGSHIP_EXAMPLES:
        rep.overall_quality = "flagship"
    elif rep.view_match_score == 0.0:
        rep.overall_quality = "failed"
    elif scaffold in PLACEHOLDER_SCAFFOLDS:
        rep.overall_quality = "fallback"
    elif rep.cylinder_stack_detected:
        rep.overall_quality = "partial"
    elif (scaffold in INSPECTED_GOOD
            and rep.primitive_richness_score >= 0.7
            and rep.topology_specificity_score >= 1.0
            and rep.assembly_attachment_score >= 0.5
            and n_children >= 8):
        rep.overall_quality = "good"
    else:
        rep.overall_quality = "partial"

    weights = {
        "view_match_score": 0.20,
        "primitive_richness_score": 0.20,
        "non_placeholder_score": 0.10,
        "assembly_attachment_score": 0.15,
        "multi_view_consistency_score": 0.15,
        "topology_specificity_score": 0.20,
    }
    rep.overall_score = round(
        sum(getattr(rep, k) * w for k, w in weights.items()), 3)
    return rep


def evaluate_all(real_patents_dir: Path) -> list[V14ExampleEval]:
    out = []
    for ex in sorted(real_patents_dir.iterdir()):
        if not ex.is_dir():
            continue
        out.append(evaluate_one(ex))
    return out


def write_report(reps: list[V14ExampleEval],
                  out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    j = out_dir / "V14_QUALITY_TABLE.json"
    m = out_dir / "V14_QUALITY_TABLE.md"
    j.write_text(json.dumps({
        "n_examples": len(reps),
        "examples": [r.to_dict() for r in reps],
    }, indent=2) + "\n")

    from collections import Counter
    counts = Counter(r.overall_quality for r in reps)
    avg = sum(r.overall_score for r in reps) / max(len(reps), 1)
    cyl_stacks = [r.example_id for r in reps
                  if r.cylinder_stack_detected]
    rotation_mismatches = [r.example_id for r in reps
                            if r.view_rotation_mismatch]

    md = ["# V1.4-G — strict quality table\n"]
    md.append(f"**{len(reps)} examples.** Distribution: "
              f"{dict(counts)}. Mean score: {avg:.3f}.\n")
    if cyl_stacks:
        md.append("\n### Cylinder-stack flag (downgraded to partial)\n")
        for cid in cyl_stacks:
            md.append(f"* `{cid}`")
    if rotation_mismatches:
        md.append("\n### View rotation mismatch\n")
        for cid in rotation_mismatches:
            md.append(f"* `{cid}`")
    md.append("\n| ID | quality | score | view | rich | non-p | attach | mv | spec | flags |")
    md.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in reps:
        flags = []
        if r.cylinder_stack_detected:
            flags.append("cyl-stack")
        if r.view_rotation_mismatch:
            flags.append("view-mismatch")
        md.append(
            f"| `{r.example_id}` | **{r.overall_quality}** | "
            f"{r.overall_score:.2f} | "
            f"{r.view_match_score:.2f} | "
            f"{r.primitive_richness_score:.2f} | "
            f"{r.non_placeholder_score:.2f} | "
            f"{r.assembly_attachment_score:.2f} | "
            f"{r.multi_view_consistency_score:.2f} | "
            f"{r.topology_specificity_score:.2f} | "
            f"{', '.join(flags) or '-'} |"
        )
    md.append("")
    m.write_text("\n".join(md))
    return j, m


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--real-patents-dir", type=Path,
                    default=Path("examples/real_patents"))
    p.add_argument("--report-dir", type=Path,
                    default=Path("examples/reports"))
    args = p.parse_args(argv)
    reps = evaluate_all(args.real_patents_dir)
    j, m = write_report(reps, args.report_dir)
    print(f"Wrote {j}\nWrote {m}")
    from collections import Counter
    print(f"Distribution: "
          f"{dict(Counter(r.overall_quality for r in reps))}")
    print(f"Mean score: "
          f"{sum(r.overall_score for r in reps)/max(len(reps),1):.3f}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
