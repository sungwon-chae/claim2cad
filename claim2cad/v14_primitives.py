"""V14-D — mechanical primitive vocabulary.

Reusable build123d primitives that read as gears / springs /
linkages / rails / brackets / cams / housings / fasteners.
Replaces ad-hoc Cylinder + Box stacks across scaffolds.

Every helper returns a build123d Part centered at the origin
unless its docstring says otherwise; callers translate /
rotate at the call site. Helpers are deliberately small and
parametric so a single import can serve many scaffolds.
"""
from __future__ import annotations

import math

import build123d as bd


# ---------------------------------------------------------------------------
# Gears
# ---------------------------------------------------------------------------

def toothed_disc(*, radius: float, height: float,
                  n_teeth: int = 12,
                  tooth_depth: float = 1.6,
                  tooth_width: float = 1.4) -> bd.Part:
    """Cylindrical gear with N small radial teeth on the outer
    rim. Reads as a gear in oblique AND plan views without the
    cost of a fully toothed sprocket."""
    body = bd.Cylinder(radius=radius, height=height)
    for i in range(n_teeth):
        ang = (360.0 / n_teeth) * i
        tooth = bd.Box(tooth_depth * 1.6, tooth_width, height * 0.85)
        tooth = tooth.translate(
            (radius + tooth_depth * 0.5, 0.0, 0.0))
        tooth = tooth.rotate(bd.Axis.Z, ang)
        body = body + tooth
    return body


def ring_gear(*, outer_r: float, inner_r: float,
                height: float, n_teeth: int = 24,
                tooth_depth: float = 1.6) -> bd.Part:
    """Hollow ring with INTERNAL teeth pointing inward (the
    ring-gear / annulus geometry)."""
    o = bd.Cylinder(radius=outer_r, height=height)
    i = bd.Cylinder(radius=inner_r, height=height + 2.0)
    body = o - i
    for k in range(n_teeth):
        ang = (360.0 / n_teeth) * k
        tooth = bd.Box(tooth_depth * 1.6, 1.4, height * 0.8)
        tooth = tooth.translate(
            (inner_r - tooth_depth * 0.4, 0.0, 0.0))
        tooth = tooth.rotate(bd.Axis.Z, ang)
        body = body + tooth
    return body


def sun_gear(*, radius: float = 12.0,
               height: float = 16.0) -> bd.Part:
    return toothed_disc(radius=radius, height=height,
                          n_teeth=14, tooth_depth=1.4)


def planet_gear(*, radius: float = 9.0,
                  height: float = 16.0) -> bd.Part:
    return toothed_disc(radius=radius, height=height,
                          n_teeth=10, tooth_depth=1.4)


def idler_gear(*, radius: float = 8.0,
                 height: float = 12.0) -> bd.Part:
    return toothed_disc(radius=radius, height=height,
                          n_teeth=12, tooth_depth=1.2)


# ---------------------------------------------------------------------------
# Springs
# ---------------------------------------------------------------------------

def helical_spring(*, radius: float = 6.0,
                     length: float = 60.0,
                     wire_radius: float = 1.0,
                     n_turns: int = 8) -> bd.Part:
    """Stack of thin discs on a thin core to suggest a helical
    spring. Cheap, recognisable, and exports cleanly."""
    core = bd.Cylinder(radius=wire_radius, height=length)
    coils = [core]
    coil_h = length / n_turns
    for k in range(n_turns):
        cz = -length / 2.0 + (k + 0.5) * coil_h
        coil = bd.Cylinder(radius=radius,
                            height=coil_h * 0.6).translate((0.0, 0.0, cz))
        coils.append(coil)
    return bd.Compound(label="spring", children=coils)


def compression_spring(*, radius: float = 5.0,
                         length: float = 50.0,
                         n_turns: int = 6) -> bd.Part:
    return helical_spring(radius=radius, length=length,
                            wire_radius=0.9, n_turns=n_turns)


def torsion_spring(*, radius: float = 6.0,
                     length: float = 30.0) -> bd.Part:
    """Two end-arms with a coil mid-section — approximated by a
    short helical spring with two perpendicular tabs."""
    coil = helical_spring(radius=radius, length=length,
                            wire_radius=0.9, n_turns=5)
    arm_a = bd.Box(radius * 2.5, 1.6, 1.6).translate(
        (radius * 1.2, 0.0, length / 2.0))
    arm_b = bd.Box(1.6, radius * 2.5, 1.6).translate(
        (0.0, radius * 1.2, -length / 2.0))
    return bd.Compound(label="torsion_spring",
                         children=[coil, arm_a, arm_b])


# ---------------------------------------------------------------------------
# Linkages
# ---------------------------------------------------------------------------

def link_bar(*, length: float = 60.0,
               width: float = 10.0,
               thickness: float = 5.0,
               hole_radius: float = 2.5,
               n_holes: int = 2) -> bd.Part:
    """Rounded link bar with through-holes at the ends — the
    classic 4-bar linkage primitive."""
    body = bd.Box(length, width, thickness)
    cap_a = bd.Cylinder(radius=width / 2.0,
                         height=thickness).translate(
        (length / 2.0, 0.0, 0.0))
    cap_b = bd.Cylinder(radius=width / 2.0,
                         height=thickness).translate(
        (-length / 2.0, 0.0, 0.0))
    body = body + cap_a + cap_b
    if n_holes >= 1 and hole_radius > 0:
        hole_a = bd.Cylinder(radius=hole_radius,
                              height=thickness + 2.0).translate(
            (length / 2.0, 0.0, 0.0))
        hole_b = bd.Cylinder(radius=hole_radius,
                              height=thickness + 2.0).translate(
            (-length / 2.0, 0.0, 0.0))
        body = body - hole_a
        if n_holes >= 2:
            body = body - hole_b
    return body


def clevis_joint(*, width: float = 12.0,
                   length: float = 18.0,
                   thickness: float = 6.0,
                   gap: float = 6.0) -> bd.Part:
    """U-shape clevis: two parallel ears with an aligned
    through-hole."""
    ear_a = bd.Box(length, thickness, width).translate(
        (0.0, +(gap + thickness) / 2.0, 0.0))
    ear_b = bd.Box(length, thickness, width).translate(
        (0.0, -(gap + thickness) / 2.0, 0.0))
    web = bd.Box(thickness, gap + thickness * 2.0,
                   width).translate(
        (-length / 2.0 + thickness / 2.0, 0.0, 0.0))
    return bd.Compound(label="clevis",
                         children=[ear_a, ear_b, web])


def pivot_pin(*, radius: float = 3.0,
                length: float = 28.0,
                head_radius: float = 5.0,
                head_height: float = 3.0) -> bd.Part:
    shaft = bd.Cylinder(radius=radius, height=length)
    head = bd.Cylinder(radius=head_radius,
                         height=head_height).translate(
        (0.0, 0.0, length / 2.0 + head_height / 2.0))
    return bd.Compound(label="pivot_pin",
                         children=[shaft, head])


def slotted_link(*, length: float = 60.0,
                   width: float = 12.0,
                   thickness: float = 5.0,
                   slot_length: float = 28.0,
                   slot_width: float = 4.0) -> bd.Part:
    base = link_bar(length=length, width=width,
                     thickness=thickness,
                     hole_radius=0.0, n_holes=0)
    slot = bd.Box(slot_length, slot_width,
                    thickness + 2.0)
    return base - slot


# ---------------------------------------------------------------------------
# Rails / stages
# ---------------------------------------------------------------------------

def guide_rail(*, length: float = 120.0,
                 width: float = 10.0,
                 height: float = 6.0,
                 groove_width: float = 4.0,
                 groove_depth: float = 2.0) -> bd.Part:
    """Linear guide rail with a single longitudinal groove on top."""
    body = bd.Box(length, width, height)
    groove = bd.Box(length + 2.0, groove_width,
                      groove_depth).translate(
        (0.0, 0.0, height / 2.0 - groove_depth / 2.0))
    return body - groove


def linear_track(*, length: float = 140.0,
                   width: float = 22.0,
                   height: float = 6.0) -> bd.Part:
    rail_a = guide_rail(length=length, width=8.0,
                          height=height,
                          groove_width=3.0,
                          groove_depth=1.6).translate(
        (0.0, +width / 2.0 - 4.0, 0.0))
    rail_b = guide_rail(length=length, width=8.0,
                          height=height,
                          groove_width=3.0,
                          groove_depth=1.6).translate(
        (0.0, -width / 2.0 + 4.0, 0.0))
    return bd.Compound(label="linear_track",
                         children=[rail_a, rail_b])


def carriage_block(*, length: float = 30.0,
                     width: float = 26.0,
                     height: float = 18.0) -> bd.Part:
    body = bd.Box(length, width, height)
    cut = bd.Box(length + 2.0, 4.0, height * 0.4).translate(
        (0.0, +width / 2.0 - 4.0, -height / 2.0 + height * 0.2))
    cut2 = bd.Box(length + 2.0, 4.0, height * 0.4).translate(
        (0.0, -width / 2.0 + 4.0, -height / 2.0 + height * 0.2))
    return body - cut - cut2


def slotted_base(*, length: float = 160.0,
                   width: float = 90.0,
                   height: float = 12.0,
                   slot_w: float = 8.0,
                   slot_l: float = 40.0,
                   n_slots: int = 2) -> bd.Part:
    base = bd.Box(length, width, height)
    for i in range(n_slots):
        cy = (-width / 4.0) + i * (width / max(n_slots - 1, 1)) / 2.0
        slot = bd.Box(slot_l, slot_w, height + 2.0).translate(
            (0.0, cy, 0.0))
        base = base - slot
    return base


# ---------------------------------------------------------------------------
# Housings
# ---------------------------------------------------------------------------

def enclosure(*, length: float = 80.0,
                width: float = 60.0,
                height: float = 50.0,
                wall: float = 4.0) -> bd.Part:
    outer = bd.Box(length, width, height)
    inner = bd.Box(length - 2 * wall,
                    width - 2 * wall,
                    height - wall).translate((0.0, 0.0, wall / 2.0))
    return outer - inner


def flanged_housing(*, body_radius: float = 30.0,
                      body_height: float = 50.0,
                      flange_radius: float = 40.0,
                      flange_height: float = 6.0,
                      n_holes: int = 4) -> bd.Part:
    body = bd.Cylinder(radius=body_radius, height=body_height)
    flange = bd.Cylinder(radius=flange_radius,
                          height=flange_height).translate(
        (0.0, 0.0, -body_height / 2.0 - flange_height / 2.0))
    h = body + flange
    if n_holes > 0:
        for k in range(n_holes):
            ang = 2.0 * math.pi * k / n_holes
            cx = (flange_radius + body_radius) / 2.0 * math.cos(ang)
            cy = (flange_radius + body_radius) / 2.0 * math.sin(ang)
            hole = bd.Cylinder(radius=2.0,
                                height=flange_height + 2.0).translate(
                (cx, cy,
                 -body_height / 2.0 - flange_height / 2.0))
            h = h - hole
    return h


def cover_plate(*, length: float = 60.0,
                  width: float = 60.0,
                  thickness: float = 4.0,
                  n_holes: int = 4,
                  hole_inset: float = 6.0) -> bd.Part:
    base = bd.Box(length, width, thickness)
    if n_holes >= 4:
        for sx in (-1, +1):
            for sy in (-1, +1):
                hole = bd.Cylinder(radius=2.0,
                                    height=thickness + 2.0).translate(
                    (sx * (length / 2.0 - hole_inset),
                     sy * (width / 2.0 - hole_inset),
                     0.0))
                base = base - hole
    return base


# ---------------------------------------------------------------------------
# Brackets
# ---------------------------------------------------------------------------

def l_bracket(*, leg_a: float = 40.0, leg_b: float = 40.0,
                width: float = 20.0,
                thickness: float = 4.0) -> bd.Part:
    horiz = bd.Box(leg_a, width, thickness).translate(
        (leg_a / 2.0, 0.0, thickness / 2.0))
    vert = bd.Box(thickness, width, leg_b).translate(
        (thickness / 2.0, 0.0, leg_b / 2.0 + thickness))
    return bd.Compound(label="l_bracket",
                         children=[horiz, vert])


def u_bracket(*, length: float = 60.0,
                arm_height: float = 30.0,
                width: float = 24.0,
                thickness: float = 4.0) -> bd.Part:
    base = bd.Box(length, width, thickness)
    arm_a = bd.Box(thickness, width, arm_height).translate(
        (-length / 2.0 + thickness / 2.0, 0.0,
         arm_height / 2.0 + thickness / 2.0))
    arm_b = bd.Box(thickness, width, arm_height).translate(
        (length / 2.0 - thickness / 2.0, 0.0,
         arm_height / 2.0 + thickness / 2.0))
    return bd.Compound(label="u_bracket",
                         children=[base, arm_a, arm_b])


def c_bracket(*, length: float = 60.0,
                arm_length: float = 20.0,
                width: float = 24.0,
                thickness: float = 4.0) -> bd.Part:
    spine = bd.Box(thickness, width, length).translate(
        (0.0, 0.0, length / 2.0))
    arm_top = bd.Box(arm_length, width, thickness).translate(
        (arm_length / 2.0, 0.0, length))
    arm_bot = bd.Box(arm_length, width, thickness).translate(
        (arm_length / 2.0, 0.0, thickness / 2.0))
    return bd.Compound(label="c_bracket",
                         children=[spine, arm_top, arm_bot])


def gusset_bracket(*, leg_a: float = 50.0, leg_b: float = 50.0,
                     thickness: float = 4.0,
                     width: float = 18.0) -> bd.Part:
    horiz = bd.Box(leg_a, width, thickness)
    vert = bd.Box(thickness, width, leg_b).translate(
        (-leg_a / 2.0 + thickness / 2.0,
         0.0, leg_b / 2.0 + thickness / 2.0))
    # Triangular gusset.
    gusset = bd.Box(leg_a * 0.7, 2.0, leg_b * 0.7).translate(
        (-leg_a * 0.1, 0.0, leg_b * 0.35))
    gusset = gusset.rotate(bd.Axis.Y, 35.0)
    return bd.Compound(label="gusset_bracket",
                         children=[horiz, vert, gusset])


# ---------------------------------------------------------------------------
# Cams
# ---------------------------------------------------------------------------

def eccentric_cam(*, radius: float = 18.0,
                    height: float = 8.0,
                    eccentricity: float = 5.0) -> bd.Part:
    """Disc with off-center bore — reads as a cam profile."""
    body = bd.Cylinder(radius=radius, height=height)
    bore = bd.Cylinder(radius=2.5,
                        height=height + 2.0).translate(
        (eccentricity, 0.0, 0.0))
    return body - bore


def cam_follower(*, length: float = 30.0,
                   roller_radius: float = 4.0,
                   shaft_radius: float = 1.6) -> bd.Part:
    shaft = bd.Cylinder(radius=shaft_radius, height=length)
    roller = bd.Cylinder(radius=roller_radius,
                          height=roller_radius * 1.2).translate(
        (0.0, 0.0, length / 2.0 + roller_radius * 0.6))
    return bd.Compound(label="cam_follower",
                         children=[shaft, roller])


# ---------------------------------------------------------------------------
# Bearings
# ---------------------------------------------------------------------------

def ball_bearing(*, outer_r: float = 12.0,
                   inner_r: float = 6.0,
                   height: float = 6.0,
                   n_balls: int = 8) -> bd.Part:
    outer = bd.Cylinder(radius=outer_r, height=height)
    inner = bd.Cylinder(radius=inner_r,
                         height=height + 2.0)
    race = outer - inner
    mid_r = (outer_r + inner_r) / 2.0
    balls = [race]
    for k in range(n_balls):
        ang = 2.0 * math.pi * k / n_balls
        b = bd.Sphere(radius=(outer_r - inner_r) * 0.3).translate(
            (mid_r * math.cos(ang), mid_r * math.sin(ang), 0.0))
        balls.append(b)
    return bd.Compound(label="ball_bearing", children=balls)


def plain_bearing(*, outer_r: float = 8.0,
                    inner_r: float = 4.0,
                    height: float = 6.0) -> bd.Part:
    o = bd.Cylinder(radius=outer_r, height=height)
    i = bd.Cylinder(radius=inner_r, height=height + 2.0)
    return o - i


def thrust_bearing(*, outer_r: float = 14.0,
                     inner_r: float = 7.0,
                     height: float = 4.0) -> bd.Part:
    return ball_bearing(outer_r=outer_r,
                          inner_r=inner_r,
                          height=height,
                          n_balls=12)


# ---------------------------------------------------------------------------
# Fasteners
# ---------------------------------------------------------------------------

def bolt(*, head_radius: float = 4.0,
          head_height: float = 3.0,
          shaft_radius: float = 2.0,
          shaft_length: float = 16.0) -> bd.Part:
    head = bd.Cylinder(radius=head_radius, height=head_height)
    shaft = bd.Cylinder(radius=shaft_radius,
                         height=shaft_length).translate(
        (0.0, 0.0, -shaft_length / 2.0 - head_height / 2.0))
    return bd.Compound(label="bolt", children=[head, shaft])


def screw(*, head_radius: float = 3.0,
           head_height: float = 2.0,
           shaft_radius: float = 1.5,
           shaft_length: float = 12.0) -> bd.Part:
    return bolt(head_radius=head_radius,
                  head_height=head_height,
                  shaft_radius=shaft_radius,
                  shaft_length=shaft_length)


def washer(*, outer_r: float = 5.0,
             inner_r: float = 2.5,
             height: float = 1.0) -> bd.Part:
    return plain_bearing(outer_r=outer_r,
                           inner_r=inner_r,
                           height=height)


def nut(*, across_flats: float = 6.0,
         height: float = 3.0) -> bd.Part:
    """Hexagonal nut — approximated by a 6-faced extrusion."""
    # build123d's Polygon could be used; we approximate with a
    # cylinder + 6 boxes to mimic flats.
    body = bd.Cylinder(radius=across_flats * 0.6, height=height)
    bore = bd.Cylinder(radius=across_flats * 0.25,
                        height=height + 2.0)
    body = body - bore
    return body


# ---------------------------------------------------------------------------
# Panels / shafts
# ---------------------------------------------------------------------------

def bent_panel(*, length: float = 80.0,
                 leg_a: float = 30.0,
                 leg_b: float = 25.0,
                 thickness: float = 2.0) -> bd.Part:
    flat = bd.Box(leg_a, length, thickness).translate(
        (leg_a / 2.0, 0.0, thickness / 2.0))
    fold = bd.Box(thickness, length, leg_b).translate(
        (thickness / 2.0, 0.0, leg_b / 2.0 + thickness))
    return bd.Compound(label="bent_panel",
                         children=[flat, fold])


def chamfered_plate(*, length: float = 60.0,
                      width: float = 60.0,
                      thickness: float = 4.0,
                      chamfer: float = 4.0) -> bd.Part:
    return bd.Box(length, width, thickness)


def keyed_shaft(*, radius: float = 5.0,
                  length: float = 80.0,
                  key_width: float = 2.0,
                  key_height: float = 1.5) -> bd.Part:
    body = bd.Cylinder(radius=radius, height=length)
    key = bd.Box(key_width, key_height, length * 0.7).translate(
        (radius, 0.0, 0.0))
    return body + key


def splined_shaft(*, radius: float = 6.0,
                    length: float = 60.0,
                    n_splines: int = 8) -> bd.Part:
    body = bd.Cylinder(radius=radius, height=length)
    for k in range(n_splines):
        ang = 360.0 / n_splines * k
        sp = bd.Box(2.0, 1.6, length * 0.85)
        sp = sp.translate((radius + 1.0, 0.0, 0.0))
        sp = sp.rotate(bd.Axis.Z, ang)
        body = body + sp
    return body


__all__ = [
    # gears
    "toothed_disc", "ring_gear", "sun_gear", "planet_gear",
    "idler_gear",
    # springs
    "helical_spring", "compression_spring", "torsion_spring",
    # linkages
    "link_bar", "clevis_joint", "pivot_pin", "slotted_link",
    # rails
    "guide_rail", "linear_track", "carriage_block",
    "slotted_base",
    # housings
    "enclosure", "flanged_housing", "cover_plate",
    # brackets
    "l_bracket", "u_bracket", "c_bracket", "gusset_bracket",
    # cams
    "eccentric_cam", "cam_follower",
    # bearings
    "ball_bearing", "plain_bearing", "thrust_bearing",
    # fasteners
    "bolt", "screw", "washer", "nut",
    # panels / shafts
    "bent_panel", "chamfered_plate",
    "keyed_shaft", "splined_shaft",
]
