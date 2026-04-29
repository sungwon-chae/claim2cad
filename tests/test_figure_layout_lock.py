"""V12-B — figure-first layout lock regression tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from claim2cad.figure_layout_lock import (
    FigureRegionMap,
    GroupRegion,
    apply_layout_lock,
    load_region_map,
)
from claim2cad.figure_projection import (
    FigureAnchor,
    FigureProjection,
    FigureProjectionLayout,
)
from claim2cad.scene_scaffold import lift_off_door_hinge_scaffold_for_us4807331a

REPO_ROOT = Path(__file__).resolve().parent.parent
US4807331A = REPO_ROOT / "examples/real_patents/US4807331A_spring_loaded_hinge"


def test_group_region_contains_uv() -> None:
    r = GroupRegion(
        group_id="x", center_uv=(0.5, 0.5), bbox_uv=(0.4, 0.3, 0.6, 0.7),
    )
    assert r.contains_uv((0.5, 0.5))
    assert r.contains_uv((0.4, 0.3))
    assert not r.contains_uv((0.7, 0.5))
    assert not r.contains_uv((0.5, 0.2))


@pytest.mark.skipif(
    not (US4807331A / "figure_layout_lock.json").exists(),
    reason="US4807331A layout lock JSON absent",
)
def test_us4807331a_lock_loads() -> None:
    rmap = load_region_map(US4807331A / "figure_layout_lock.json")
    assert rmap.family_id == "US4807331A_spring_loaded_hinge"
    ids = {r.group_id for r in rmap.regions}
    # The brief explicitly enumerates these groups.
    required = {"door_panel", "fixed_frame", "upper_hinge", "lower_hinge",
                "pintle_axis", "power_mechanism", "fasteners"}
    assert required.issubset(ids), f"missing groups: {required - ids}"


@pytest.mark.skipif(
    not (US4807331A / "figure_layout_lock.json").exists(),
    reason="US4807331A layout lock JSON absent",
)
def test_apply_layout_lock_separates_door_and_frame() -> None:
    """The lock must place door_panel on the LEFT (negative X in
    front projection) and fixed_frame on the RIGHT (positive X).
    Without this, the central pile cannot break."""
    rmap = load_region_map(US4807331A / "figure_layout_lock.json")
    proj = FigureProjection(
        figure_id="figure_1",
        view_type="front",
        projection_plane=("X", "Z"),
        figure_width_px=2320,
        figure_height_px=3408,
        scale_uv_to_mm=300.0,
        depth_axis="Y",
    )
    layout = FigureProjectionLayout(
        projection=proj,
        component_anchors=[],
        group_anchors=[
            FigureAnchor(id=g.group_id, figure_uv=(0.5, 0.5),
                          cad_anchor_mm=(0.0, 0.0, 0.0))
            for g in rmap.regions
        ],
    )
    scaffold = lift_off_door_hinge_scaffold_for_us4807331a()
    locked = apply_layout_lock(
        layout=layout, region_map=rmap,
        component_to_group=scaffold.component_to_group,
    )
    by_id = {a.id: a for a in locked.group_anchors}
    door_x = by_id["door_panel"].cad_anchor_mm[0]
    frame_x = by_id["fixed_frame"].cad_anchor_mm[0]
    assert door_x < frame_x, f"door {door_x} not left of frame {frame_x}"
    assert frame_x - door_x > 80.0, "door and frame too close — central pile risk"


@pytest.mark.skipif(
    not (US4807331A / "figure_layout_lock.json").exists(),
    reason="US4807331A layout lock JSON absent",
)
def test_apply_layout_lock_separates_upper_and_lower_hinge() -> None:
    rmap = load_region_map(US4807331A / "figure_layout_lock.json")
    proj = FigureProjection(
        figure_id="figure_1",
        view_type="front",
        projection_plane=("X", "Z"),
        figure_width_px=2320,
        figure_height_px=3408,
        scale_uv_to_mm=300.0,
        depth_axis="Y",
    )
    layout = FigureProjectionLayout(
        projection=proj,
        component_anchors=[],
        group_anchors=[
            FigureAnchor(id=g.group_id, figure_uv=(0.5, 0.5),
                          cad_anchor_mm=(0.0, 0.0, 0.0))
            for g in rmap.regions
        ],
    )
    scaffold = lift_off_door_hinge_scaffold_for_us4807331a()
    locked = apply_layout_lock(
        layout=layout, region_map=rmap,
        component_to_group=scaffold.component_to_group,
    )
    by_id = {a.id: a for a in locked.group_anchors}
    upper_z = by_id["upper_hinge"].cad_anchor_mm[2]
    lower_z = by_id["lower_hinge"].cad_anchor_mm[2]
    # Upper above lower (Z grows up; figure v=0.20 maps to higher Z).
    assert upper_z > lower_z, "upper hinge not above lower hinge"
    assert upper_z - lower_z > 50.0, "hinges not vertically separated"


@pytest.mark.skipif(
    not (US4807331A / "figure_layout_lock.json").exists(),
    reason="US4807331A layout lock JSON absent",
)
def test_apply_layout_lock_clamps_components_inside_region() -> None:
    """Every component whose group is locked must end up with its
    figure_uv inside the region bbox."""
    rmap = load_region_map(US4807331A / "figure_layout_lock.json")
    proj = FigureProjection(
        figure_id="figure_1",
        view_type="front",
        projection_plane=("X", "Z"),
        figure_width_px=2320,
        figure_height_px=3408,
        scale_uv_to_mm=300.0,
        depth_axis="Y",
    )
    scaffold = lift_off_door_hinge_scaffold_for_us4807331a()
    # Synthesize component anchors all at (0.99, 0.99) — the lock
    # must pull them back into their region.
    anchors = [
        FigureAnchor(id=cid, figure_uv=(0.99, 0.99),
                      cad_anchor_mm=(0.0, 0.0, 0.0))
        for cid in scaffold.component_to_group
    ]
    layout = FigureProjectionLayout(
        projection=proj,
        component_anchors=anchors,
        group_anchors=[
            FigureAnchor(id=g.group_id, figure_uv=(0.5, 0.5),
                          cad_anchor_mm=(0.0, 0.0, 0.0))
            for g in rmap.regions
        ],
    )
    locked = apply_layout_lock(
        layout=layout, region_map=rmap,
        component_to_group=scaffold.component_to_group,
    )
    by_region = rmap.by_id()
    for ca in locked.component_anchors:
        gid = scaffold.component_to_group.get(ca.id)
        if gid not in by_region:
            continue
        region = by_region[gid]
        assert region.contains_uv(ca.figure_uv, slack=0.01), (
            f"{ca.id} (group {gid}) UV {ca.figure_uv} outside {region.bbox_uv}"
        )
