"""V14-C — projection-locked rendering.

Reads figure_views_v14.json (from V14-B) and renders the example's
model_v1.4 / model_v1.3 / model_v1.2_oblique GLB through a camera
that matches the detected patent-figure view. Saves three outputs
under renders_v1.4/:

  figure_matched.png   — primary CAD render in the matched
                         camera (top / front / right / iso /
                         patent_oblique).
  comparison.png       — figure | matched render side-by-side.
  view_debug.png       — figure with the detected view-region
                         bboxes drawn (V14-B already writes this
                         as view_region_debug.png — projection-
                         lock copies / refreshes it).

For multi_view_sheet examples, additionally renders:

  plan_view.png        — top camera render (kept from V13-S
                         where applicable).
  section_view.png     — front camera render that approximates a
                         section through the assembly's centroid.

If the detected camera does not exist in the renderer, falls back
to iso. Per-example success / failure is recorded in the status
returned by ``project_one``.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# Camera presets shared by V13/V14 renders. Tuples are
# (elevation_deg, azimuth_deg) for matplotlib's mpl_toolkits.mplot3d.
CAMERA_PRESETS = {
    "top":            (89.0, -90.0),
    "front":          (5.0,  -90.0),
    "right":          (5.0,    0.0),
    "iso":           (25.0,  -45.0),
    "patent_oblique": (22.0,  -60.0),  # V12-L flagship preset
    "custom":         (22.0,  -60.0),
}


@dataclass
class ProjectionStatus:
    example_id: str
    view_type: str = ""
    camera_used: str = ""
    primary_render: str = ""
    plan_render: str = ""
    section_render: str = ""
    comparison_render: str = ""
    error: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _best_step(example_dir: Path) -> Path | None:
    for n in ("model_v1.4.step", "model_v1.3.step",
              "model_v1.2.step", "model.step"):
        p = example_dir / n
        if p.exists():
            return p
    return None


def _render(step_path: Path, out_path: Path,
             elev: float, azim: float,
             resolution: int = 900) -> None:
    from claim2cad.visual_validator import render_step_to_solid
    out_path.parent.mkdir(parents=True, exist_ok=True)
    render_step_to_solid(step_path, out_path,
                          elev=elev, azim=azim,
                          resolution=resolution)


def _comparison(figure_path: Path, render_path: Path,
                 out_path: Path, *, label_left: str,
                 label_right: str) -> Path | None:
    try:
        from claim2cad.figure_aligned_render import \
            make_figure_aligned_comparison
        return make_figure_aligned_comparison(
            figure_path=figure_path,
            figure_aligned_render=render_path,
            out_path=out_path,
            label_left=label_left, label_right=label_right,
            panel_w=600,
        )
    except Exception as exc:  # noqa: BLE001
        return None


def project_one(example_dir: Path) -> ProjectionStatus:
    s = ProjectionStatus(example_id=example_dir.name)
    views_path = example_dir / "figure_views_v14.json"
    if not views_path.exists():
        s.error = "no figure_views_v14.json"
        return s
    views = json.loads(views_path.read_text("utf-8"))
    s.view_type = views.get("view_type", "unknown")
    cam_name = views.get("required_camera", "iso")
    cam = CAMERA_PRESETS.get(cam_name, CAMERA_PRESETS["iso"])
    s.camera_used = cam_name

    step = _best_step(example_dir)
    if step is None:
        s.error = "no STEP available"
        return s

    out_dir = example_dir / "renders_v1.4"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Primary view-matched render.
    primary = out_dir / "figure_matched.png"
    try:
        _render(step, primary, elev=cam[0], azim=cam[1],
                  resolution=900)
        s.primary_render = str(primary)
    except Exception as exc:  # noqa: BLE001
        s.error = f"primary render failed: {exc}"
        s.notes.append(s.error)

    # Multi-view extras.
    if s.view_type == "multi_view_sheet":
        try:
            plan = out_dir / "plan_view.png"
            _render(step, plan, *CAMERA_PRESETS["top"],
                      resolution=900)
            s.plan_render = str(plan)
        except Exception as exc:  # noqa: BLE001
            s.notes.append(f"plan render failed: {exc}")
        try:
            sect = out_dir / "section_view.png"
            _render(step, sect, *CAMERA_PRESETS["front"],
                      resolution=900)
            s.section_render = str(sect)
        except Exception as exc:  # noqa: BLE001
            s.notes.append(f"section render failed: {exc}")

    # Comparison.
    fig = example_dir / "figures" / "figure_1.png"
    if fig.exists() and primary.exists():
        cmp_out = out_dir / "comparison.png"
        out = _comparison(
            fig, primary, cmp_out,
            label_left=f"Patent figure ({example_dir.name})",
            label_right=f"v1.4 — view={s.view_type} cam={cam_name}")
        if out is not None:
            s.comparison_render = str(cmp_out)
        else:
            s.notes.append("comparison render failed")
    return s


def project_all(real_patents_dir: Path,
                 *, only: set[str] | None = None) -> list[ProjectionStatus]:
    out = []
    for ex in sorted(real_patents_dir.iterdir()):
        if not ex.is_dir():
            continue
        if only and ex.name not in only:
            continue
        s = project_one(ex)
        out.append(s)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--all-real-patents", action="store_true")
    p.add_argument("--example", action="append", default=[])
    p.add_argument("--real-patents-dir", type=Path,
                    default=Path("examples/real_patents"))
    p.add_argument("--report-dir", type=Path,
                    default=Path("examples/reports"))
    args = p.parse_args(argv)
    only = set(args.example) if args.example else None
    statuses = project_all(args.real_patents_dir, only=only)
    args.report_dir.mkdir(exist_ok=True)
    out_path = args.report_dir / "V14_PROJECTION_STATUS.json"
    out_path.write_text(json.dumps({
        "n": len(statuses),
        "examples": [s.to_dict() for s in statuses],
    }, indent=2) + "\n")
    n_ok = sum(1 for s in statuses if s.primary_render and not s.error)
    print(f"\nWrote {out_path}")
    print(f"{n_ok}/{len(statuses)} examples got a view-matched render.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
