"""Tests for the V11-20 scene scaffold."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from claim2cad.scene_scaffold import (
    SceneGroup,
    SceneScaffold,
    US4807331A_COMPONENT_GROUPS,
    _default_group_for_id,
    assign_scaffold_group,
    lift_off_door_hinge_scaffold_for_us4807331a,
    load_scaffold,
    make_lift_off_door_hinge_scaffold,
    save_scaffold,
)


def test_default_scaffold_has_expected_groups() -> None:
    sc = make_lift_off_door_hinge_scaffold()
    ids = {g.id for g in sc.groups}
    assert {
        "door_panel",
        "fixed_frame",
        "pintle_axis",
        "upper_hinge",
        "lower_hinge",
        "power_mechanism",
        "fasteners",
    } <= ids


def test_door_and_frame_on_different_planes() -> None:
    sc = make_lift_off_door_hinge_scaffold()
    door = sc.by_id()["door_panel"]
    frame = sc.by_id()["fixed_frame"]
    # Different X positions ⇒ visually-separated panels.
    assert abs(door.origin_mm[0] - frame.origin_mm[0]) >= 80.0


def test_upper_lower_hinges_are_z_separated() -> None:
    sc = make_lift_off_door_hinge_scaffold()
    upper = sc.by_id()["upper_hinge"]
    lower = sc.by_id()["lower_hinge"]
    # Hinges at different Z, separation > sum of half-bbox so their
    # bboxes don't overlap.
    z_dist = abs(upper.origin_mm[2] - lower.origin_mm[2])
    h_extent = max(upper.nominal_bbox_mm[2], lower.nominal_bbox_mm[2])
    assert z_dist >= h_extent


def test_us4807331a_mapping_covers_all_canonical_ids() -> None:
    sc = lift_off_door_hinge_scaffold_for_us4807331a()
    # Every canonical component_id should map to a known group id.
    valid_groups = {g.id for g in sc.groups}
    for cid, gid in sc.component_to_group.items():
        assert gid in valid_groups, f"{cid} → {gid} not a valid group"
    # Spot-check critical bindings.
    assert sc.component_to_group["pintle_pin"] == "pintle_axis"
    assert sc.component_to_group["main_member"] == "upper_hinge"
    assert sc.component_to_group["door_half_member"] == "door_panel"
    assert sc.component_to_group["vehicle_body"] == "fixed_frame"


def test_unknown_id_falls_through_default_heuristic() -> None:
    assert _default_group_for_id("upper_extension_extra") == "upper_hinge"
    assert _default_group_for_id("door_seal") == "door_panel"
    assert _default_group_for_id("retaining_screw") == "fasteners"
    assert _default_group_for_id("body_attachment_bracket") == "fixed_frame"


def test_scaffold_for_subset_of_ir_ids() -> None:
    """Restricting to the IR's component_ids should drop unmapped
    canonical ids and add per-id defaults for unfamiliar ones."""
    ir_ids = {"pintle_pin", "vehicle_body", "exotic_widget"}
    sc = lift_off_door_hinge_scaffold_for_us4807331a(ir_component_ids=ir_ids)
    assert sc.component_to_group["pintle_pin"] == "pintle_axis"
    assert sc.component_to_group["vehicle_body"] == "fixed_frame"
    # Unfamiliar id → fasteners by heuristic default
    assert "exotic_widget" in sc.component_to_group


def test_assign_scaffold_group() -> None:
    sc = lift_off_door_hinge_scaffold_for_us4807331a()
    assert assign_scaffold_group("pintle_pin", sc) == "pintle_axis"
    # Unknown id but matches a heuristic group
    assert assign_scaffold_group("upper_widget", sc) == "upper_hinge"


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    sc = lift_off_door_hinge_scaffold_for_us4807331a()
    p = save_scaffold(sc, tmp_path / "scaffold.json")
    assert p.exists()
    re = load_scaffold(p)
    assert re.name == sc.name
    assert {g.id for g in re.groups} == {g.id for g in sc.groups}
    assert re.component_to_group == sc.component_to_group


def test_group_ids_populated_on_groups_after_construction() -> None:
    sc = lift_off_door_hinge_scaffold_for_us4807331a()
    by_id = sc.by_id()
    # door_panel should own at least door_half_member.
    door_components = set(by_id["door_panel"].component_ids)
    assert "door_half_member" in door_components
    # pintle_axis should own pintle_pin.
    assert "pintle_pin" in by_id["pintle_axis"].component_ids
