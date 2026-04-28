"""Tests for claim2cad.visual_validator.

We avoid live VLM calls — those are exercised manually via the CLI to
generate the baseline report. The tests here verify the renderer and the
composite-image pipeline, plus the ``dry_run`` path of ``compare_to_figure``.
"""
from __future__ import annotations

from pathlib import Path

import build123d as bd
import pytest
from PIL import Image

from claim2cad.visual_validator import (
    DEFAULT_VIEWS,
    SimilarityReport,
    compare_to_figure,
    make_comparison_grid,
    render_shape_to_png,
    render_step_to_pngs,
)


def _make_step(tmp_path: Path) -> Path:
    box = bd.Box(20, 10, 5)
    step = tmp_path / "tiny.step"
    bd.export_step(box, str(step))
    return step


def _make_figure(tmp_path: Path) -> Path:
    img = Image.new("RGB", (400, 600), (240, 240, 240))
    figure = tmp_path / "figure.png"
    img.save(figure)
    return figure


def test_render_shape_to_png_writes_nonempty_png(tmp_path: Path) -> None:
    box = bd.Box(20, 10, 5)
    out = render_shape_to_png(box, tmp_path / "iso.png", elev=25, azim=45)
    assert out.exists()
    assert out.stat().st_size > 1000
    # PNG magic
    assert out.read_bytes()[:4] == b"\x89PNG"


def test_render_step_to_pngs_produces_one_per_view(tmp_path: Path) -> None:
    step = _make_step(tmp_path)
    out = render_step_to_pngs(step, tmp_path / "renders", views=DEFAULT_VIEWS)
    assert len(out) == len(DEFAULT_VIEWS)
    for p in out:
        assert p.exists() and p.stat().st_size > 500


def test_make_comparison_grid_sizes_correctly(tmp_path: Path) -> None:
    step = _make_step(tmp_path)
    figure = _make_figure(tmp_path)
    renders = render_step_to_pngs(step, tmp_path / "renders", views=DEFAULT_VIEWS)
    composite = make_comparison_grid(renders, figure, tmp_path / "composite.png", cell_px=256)
    assert composite.exists()
    img = Image.open(composite)
    # figure block (256*2) + grid (256*2) + paddings
    assert img.width >= 256 * 4
    assert img.height >= 256 * 2


def test_compare_to_figure_dry_run_returns_stub(tmp_path: Path) -> None:
    step = _make_step(tmp_path)
    figure = _make_figure(tmp_path)
    renders = render_step_to_pngs(step, tmp_path / "renders", views=DEFAULT_VIEWS)
    report = compare_to_figure(
        renders,
        figure,
        composite_path=tmp_path / "composite.png",
        component_list=["body: vehicle body", "pin: pintle pin"],
        dry_run=True,
    )
    assert isinstance(report, SimilarityReport)
    assert report.overall_score == 0.0
    assert report.notes == "dry-run stub"
    # Composite image is still produced even on dry-run.
    assert (tmp_path / "composite.png").exists()


def test_similarity_report_to_dict_round_trip() -> None:
    rep = SimilarityReport(
        overall_score=7.0,
        silhouette_score=8.0,
        proportion_score=6.0,
        feature_score=7.0,
        arrangement_score=7.0,
        defects=[{"component": "pin", "issue": "off-axis", "severity": "minor"}],
        notes="ok",
    )
    d = rep.to_dict()
    assert d["overall_score"] == 7.0
    assert len(d["defects"]) == 1
    assert d["defects"][0]["component"] == "pin"
