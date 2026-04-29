"""V13-D — batch regeneration pipeline.

For every example under ``examples/real_patents/``:

  1. Load classification + claim_map + figure_map.
  2. Look up scaffold in registry.
  3. Build the model (catch errors per-example so one failure
     doesn't kill the run).
  4. Export model_v1.3.glb + (best-effort) model_v1.3.step.
  5. Render renders_v1.3/primary.png + comparison.png.
  6. Write batch_status.json next to each example.

Per-example failures are logged but do NOT abort the run. The
final BATCH_REPORT.json/md tabulates status: ok | failed |
skipped (no claim_map).

Invocation:
  python -m claim2cad.batch_generate --all-real-patents
  python -m claim2cad.batch_generate --example US4807331A_spring_loaded_hinge
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import build123d as bd

from claim2cad.figure_topology_classifier import classify_example, save_classification
from claim2cad.glb_naming import rename_glb_root_children
from claim2cad.scaffolds import (
    ScaffoldInput,
    get_scaffold,
)

logger = logging.getLogger(__name__)

# US4807331A keeps its hand-built oblique scaffold output (better
# than the generic door_hinge template). The batch runner skips
# rebuilding it but still records its status.
FLAGSHIP_EXAMPLES = {"US4807331A_spring_loaded_hinge"}


@dataclass
class BatchStatus:
    example_id: str
    status: str = "skipped"  # ok | failed | skipped | flagship_preserved
    scaffold_id: str = ""
    quality_tier: str = ""
    n_components: int = 0
    n_glb_children: int = 0
    error: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _render_primary(
    *,
    step_path: Path,
    out_dir: Path,
    classification_view: str,
) -> tuple[Path | None, str]:
    """Render renders_v1.3/primary.png. Returns (path, error)."""
    try:
        from claim2cad.visual_validator import render_step_to_solid

        out_dir.mkdir(parents=True, exist_ok=True)
        # Camera by view type
        view_camera = {
            "oblique": (18.0, -55.0),
            "front": (0.0, -90.0),
            "iso": (25.0, -45.0),
            "top": (89.0, -90.0),
            "side": (0.0, 0.0),
            "exploded": (18.0, -55.0),
            "sectional": (0.0, -90.0),
            "schematic": (0.0, -90.0),
            "unknown": (18.0, -55.0),
        }
        elev, azim = view_camera.get(classification_view, (18.0, -55.0))
        out_path = out_dir / "primary.png"
        render_step_to_solid(step_path, out_path,
                              elev=elev, azim=azim, resolution=900)
        return out_path, ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def _render_comparison(
    *,
    figure_path: Path,
    primary_render: Path,
    out_path: Path,
    label_left: str,
    label_right: str,
) -> tuple[Path | None, str]:
    try:
        from claim2cad.figure_aligned_render import make_figure_aligned_comparison
        out = make_figure_aligned_comparison(
            figure_path=figure_path,
            figure_aligned_render=primary_render,
            out_path=out_path,
            label_left=label_left, label_right=label_right,
            panel_w=600,
        )
        return out, ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def regenerate_one(example_dir: Path) -> BatchStatus:
    status = BatchStatus(example_id=example_dir.name)

    # Skip examples without claim_map.
    cm_path = example_dir / "claim_map.json"
    fm_path = example_dir / "figure_map.json"
    if not cm_path.exists():
        status.status = "skipped"
        status.notes = "no claim_map.json"
        return status

    # Flagship — preserve V12 oblique output.
    if example_dir.name in FLAGSHIP_EXAMPLES:
        status.status = "flagship_preserved"
        status.scaffold_id = "oblique_demo_us4807331a"
        status.quality_tier = "flagship"
        if (example_dir / "model_v1.2_oblique.glb").exists():
            status.notes = "kept model_v1.2_oblique.glb as the demo model"
        else:
            status.notes = "flagship marker but no oblique GLB found"
        # Still classify + save
        try:
            cls = classify_example(example_dir)
            save_classification(cls, example_dir)
        except Exception as exc:  # noqa: BLE001
            status.notes += f"; classify failed: {exc}"
        return status

    try:
        cm = json.loads(cm_path.read_text("utf-8"))
        fm = json.loads(fm_path.read_text("utf-8")) if fm_path.exists() else None
        cls = classify_example(example_dir)
        save_classification(cls, example_dir)

        scaffold_cls = get_scaffold(cls.recommended_scaffold)
        if scaffold_cls is None:
            scaffold_cls = get_scaffold("fallback_grid")
        scaffold = scaffold_cls()
        result = scaffold.build(ScaffoldInput(
            example_dir=example_dir, example_id=example_dir.name,
            claim_map=cm, figure_map=fm,
            figure_classification=cls.to_dict(),
        ))
        status.scaffold_id = result.scaffold_id
        status.quality_tier = result.quality_tier
        status.n_components = len(cm.get("components", []))
        status.n_glb_children = len(result.ordered_ids)

        step_path = example_dir / "model_v1.3.step"
        glb_path = example_dir / "model_v1.3.glb"
        try:
            bd.export_step(result.compound, str(step_path))
        except Exception as exc:  # noqa: BLE001
            logger.warning("STEP export failed for %s: %s", example_dir.name, exc)
            step_path = None
        bd.export_gltf(result.compound, str(glb_path), binary=True)
        try:
            rename_glb_root_children(glb_path, result.ordered_ids)
        except Exception as exc:  # noqa: BLE001
            logger.warning("GLB rename failed for %s: %s", example_dir.name, exc)

        # Render
        if step_path and step_path.exists():
            rdir = example_dir / "renders_v1.3"
            primary, err = _render_primary(
                step_path=step_path, out_dir=rdir,
                classification_view=cls.view_type,
            )
            if primary is None:
                status.notes += f" render_primary failed: {err};"
            else:
                fig_path = example_dir / "figures" / "figure_1.png"
                if fig_path.exists():
                    out, cmp_err = _render_comparison(
                        figure_path=fig_path, primary_render=primary,
                        out_path=rdir / "comparison.png",
                        label_left=f"Patent figure ({example_dir.name})",
                        label_right=f"Claim2CAD v1.3 — {result.scaffold_id}",
                    )
                    if out is None:
                        status.notes += f" comparison failed: {cmp_err};"

        status.status = "ok"

    except Exception as exc:  # noqa: BLE001
        status.status = "failed"
        status.error = f"{type(exc).__name__}: {exc}"
        status.notes = traceback.format_exc()[:800]
        logger.exception("regenerate failed for %s", example_dir.name)

    # Persist per-example status sidecar.
    (example_dir / "batch_status.json").write_text(
        json.dumps(status.to_dict(), indent=2) + "\n", encoding="utf-8",
    )
    return status


def regenerate_all(real_patents_dir: Path,
                    *, only: list[str] | None = None) -> list[BatchStatus]:
    statuses: list[BatchStatus] = []
    for ex_dir in sorted(real_patents_dir.iterdir()):
        if not ex_dir.is_dir():
            continue
        if only and ex_dir.name not in only:
            continue
        s = regenerate_one(ex_dir)
        logger.info("[%s] %s scaffold=%s quality=%s",
                     s.status, s.example_id, s.scaffold_id, s.quality_tier)
        statuses.append(s)
    return statuses


def write_batch_report(statuses: list[BatchStatus],
                        report_dir: Path) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "BATCH_REPORT.json"
    md_path = report_dir / "BATCH_REPORT.md"
    json_path.write_text(json.dumps(
        {"n_examples": len(statuses),
         "examples": [s.to_dict() for s in statuses]},
        indent=2,
    ) + "\n", encoding="utf-8")

    md = []
    md.append("# V1.3 batch regeneration report\n")
    from collections import Counter
    counts = Counter(s.status for s in statuses)
    md.append(f"**{len(statuses)} examples** processed: " +
               ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) +
               "\n")
    md.append("| ID | status | scaffold | quality | components | glb children | notes |")
    md.append("|---|---|---|---|---:|---:|---|")
    for s in statuses:
        notes = (s.notes or s.error)[:80].replace("|", " ").replace("\n", " ")
        md.append(f"| `{s.example_id}` | **{s.status}** | {s.scaffold_id} | "
                   f"{s.quality_tier} | {s.n_components} | {s.n_glb_children} | {notes} |")
    md.append("")
    md_path.write_text("\n".join(md), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-real-patents", action="store_true")
    parser.add_argument("--example", action="append", default=[],
                        help="Process only specified example(s)")
    parser.add_argument("--report-dir", type=Path,
                         default=Path("examples/reports"))
    parser.add_argument("--real-patents-dir", type=Path,
                         default=Path("examples/real_patents"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                         format="%(levelname)-7s %(message)s")
    if not args.all_real_patents and not args.example:
        parser.error("specify --all-real-patents or --example NAME")
    only = args.example or None
    statuses = regenerate_all(args.real_patents_dir, only=only)
    json_p, md_p = write_batch_report(statuses, args.report_dir)
    print(f"\nWrote {json_p}\nWrote {md_p}")
    from collections import Counter
    counts = Counter(s.status for s in statuses)
    print(f"\nFinal status distribution: {dict(counts)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
