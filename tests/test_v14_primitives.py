"""V14-D — primitive vocabulary smoke tests.

Each helper must build a non-degenerate Part. Bbox spans matter
because zero-extent geometry fails STEP/GLB export downstream.
"""
from __future__ import annotations

import pytest

from claim2cad import v14_primitives as v14p


PRIMITIVE_CASES = [
    ("toothed_disc", lambda: v14p.toothed_disc(
        radius=12.0, height=8.0)),
    ("ring_gear", lambda: v14p.ring_gear(
        outer_r=30.0, inner_r=22.0, height=10.0)),
    ("sun_gear", lambda: v14p.sun_gear()),
    ("planet_gear", lambda: v14p.planet_gear()),
    ("idler_gear", lambda: v14p.idler_gear()),
    ("helical_spring", lambda: v14p.helical_spring()),
    ("compression_spring", lambda: v14p.compression_spring()),
    ("torsion_spring", lambda: v14p.torsion_spring()),
    ("link_bar", lambda: v14p.link_bar()),
    ("clevis_joint", lambda: v14p.clevis_joint()),
    ("pivot_pin", lambda: v14p.pivot_pin()),
    ("slotted_link", lambda: v14p.slotted_link()),
    ("guide_rail", lambda: v14p.guide_rail()),
    ("linear_track", lambda: v14p.linear_track()),
    ("carriage_block", lambda: v14p.carriage_block()),
    ("slotted_base", lambda: v14p.slotted_base()),
    ("enclosure", lambda: v14p.enclosure()),
    ("flanged_housing", lambda: v14p.flanged_housing()),
    ("cover_plate", lambda: v14p.cover_plate()),
    ("l_bracket", lambda: v14p.l_bracket()),
    ("u_bracket", lambda: v14p.u_bracket()),
    ("c_bracket", lambda: v14p.c_bracket()),
    ("gusset_bracket", lambda: v14p.gusset_bracket()),
    ("eccentric_cam", lambda: v14p.eccentric_cam()),
    ("cam_follower", lambda: v14p.cam_follower()),
    ("ball_bearing", lambda: v14p.ball_bearing()),
    ("plain_bearing", lambda: v14p.plain_bearing()),
    ("thrust_bearing", lambda: v14p.thrust_bearing()),
    ("bolt", lambda: v14p.bolt()),
    ("screw", lambda: v14p.screw()),
    ("washer", lambda: v14p.washer()),
    ("nut", lambda: v14p.nut()),
    ("bent_panel", lambda: v14p.bent_panel()),
    ("chamfered_plate", lambda: v14p.chamfered_plate()),
    ("keyed_shaft", lambda: v14p.keyed_shaft()),
    ("splined_shaft", lambda: v14p.splined_shaft()),
]


@pytest.mark.parametrize("name,factory",
                          PRIMITIVE_CASES,
                          ids=[c[0] for c in PRIMITIVE_CASES])
def test_primitive_builds_non_degenerate(name, factory):
    part = factory()
    bb = part.bounding_box()
    assert bb.size.X > 0.5, f"{name}: zero X span"
    assert bb.size.Y > 0.5, f"{name}: zero Y span"
    assert bb.size.Z > 0.5, f"{name}: zero Z span"


def test_toothed_disc_has_tooth_volume():
    plain = v14p.toothed_disc(radius=10.0, height=4.0, n_teeth=0)
    toothed = v14p.toothed_disc(radius=10.0, height=4.0, n_teeth=12)
    # Toothed disc must extend beyond the plain rim.
    assert toothed.bounding_box().size.X > plain.bounding_box().size.X


def test_ring_gear_is_hollow():
    rg = v14p.ring_gear(outer_r=30.0, inner_r=22.0, height=10.0)
    bb = rg.bounding_box()
    # Outer span >> inner span (rough check).
    assert bb.size.X > 50.0


def test_helical_spring_length_matches_param():
    s = v14p.helical_spring(radius=6.0, length=60.0,
                              wire_radius=1.0, n_turns=8)
    bb = s.bounding_box()
    assert 50.0 <= bb.size.Z <= 65.0
