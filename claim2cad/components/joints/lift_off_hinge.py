"""Lift-off hinge — purpose-built compound primitive for patent
US4807331A and the wider lift-off-hinge family.

The current generic library (`u_bracket`, `pin`, `leaf`) can produce all
the *parts* of a lift-off hinge but cannot guarantee the *axis alignment*
that makes it actually function: the pintle pin must thread coaxially
through the main member's upper extension, the inner U-link's upper leg,
the leaf flange, the inner U-link's lower leg, and the main member's
lower extension. With three independent `u_bracket` instances and a
free pin, the spatial composer kept getting one or more of those
alignments wrong.

This primitive builds all four sub-assemblies (body-half bracket, inner
U-link, door-half channel, pintle pin) in a single coordinate frame
where the hinge axis IS the Z axis. Every hole that's supposed to be
coaxial is drilled along Z. The pin passes through all of them by
construction.

The primitive is broken into named children so the GLB exporter still
preserves component-id labels for the viewer:

    LiftOffHingeAssembly
    ├── main_member         (Compound: mounting_wall + upper/lower extensions)
    ├── u_shaped_link       (Compound: base_wall + upper/lower legs)
    ├── door_half_member    (Compound: bight_wall + 2 sidewalls + leaf_flange)
    ├── pintle_pin          (cylindrical, through the hinge axis)
    └── stop_means          (small protrusion on the link, contacts main)

Children are also exported individually as STEP files when the
generator passes a ``components_dir`` so existing per-component lookup
still works.
"""
from __future__ import annotations

from dataclasses import dataclass

import build123d as bd

from claim2cad.components.base import Component, ComponentBuildError, _require_positive
from claim2cad.components.library import register


@dataclass
class LiftOffHingeAssembly(Component):
    """Full lift-off hinge assembly with coaxial pintle axis (Z).

    Geometry summary:
      * Body-half (main_member) is a C-shaped bracket: mounting_wall at
        -X, upper extension at +Z, lower extension at -Z. Both extensions
        carry coaxial pintle pin holes on the Z axis.
      * Inner U-link nests between the extensions. Its base_wall is the
        outer (-X) face; its upper and lower legs sit just inside the
        main member's extensions and carry the same coaxial holes.
      * Door-half (door_half_member) is a U-channel offset to +X. Its
        first sidewall (the one nearer the hinge axis) carries an inward-
        projecting leaf_flange whose pin hole is also on the hinge axis,
        between the inner U-link's upper leg and the main member's
        upper extension.
      * Pintle pin is a single cylinder on the Z axis from below the
        lower extension to above the upper extension.
      * Stop means is a small cylinder on the link's upper face that
        contacts the main member's upper extension to limit rotation.

    Default parameters reproduce US4807331A's figure 1 proportions.
    """

    # --- pintle pin --------------------------------------------------------
    pin_diameter: float = 6.0
    pin_length: float = 90.0
    pin_head_style: str = "round"  # one of {none, flat, round}
    pin_head_diameter: float = 10.0
    pin_head_height: float = 3.0

    # --- main member (body-half) ------------------------------------------
    main_thickness: float = 3.0
    main_mounting_wall_width: float = 50.0   # extent in Y on the -X face
    main_mounting_wall_height: float = 80.0  # extent in Z on the -X face
    main_extension_length: float = 35.0      # how far each extension reaches in +X
    main_extension_width: float = 30.0       # extent in Y of each extension
    main_extension_gap: float = 50.0         # vertical gap between upper/lower extension inner faces (space for the link)
    main_hole_offset_x: float = 22.0         # along the extension, where the pin hole sits

    # --- inner U-link ------------------------------------------------------
    link_base_length: float = 25.0           # extent of base_wall in X (its thickness is `link_thickness`)
    link_thickness: float = 2.5
    link_base_width: float = 22.0            # extent in Y of the base_wall
    link_leg_length: float = 22.0            # how far each leg reaches in +X
    link_leg_width: float = 22.0             # extent in Y of each leg
    link_leg_gap: float = 36.0               # vertical gap between link's upper/lower legs

    # --- door-half member --------------------------------------------------
    door_offset_x: float = 32.0              # door bight offset from origin (door is at +X)
    door_bight_width: float = 50.0           # extent of bight wall in Y
    door_bight_height: float = 90.0          # extent in Z (height of channel)
    door_thickness: float = 3.0
    door_sidewall_depth: float = 24.0        # how far sidewalls extend in -X toward the hinge axis

    # --- leaf flange -------------------------------------------------------
    leaf_flange_length: float = 22.0         # extent of flange in X (perpendicular to sidewall)
    leaf_flange_width: float = 18.0          # extent in Y
    leaf_flange_thickness: float = 2.5
    leaf_flange_z: float = 18.0              # elevation above origin (between upper-link-leg and upper-extension)

    # --- stop means --------------------------------------------------------
    include_stop: bool = True
    stop_diameter: float = 4.0
    stop_height: float = 6.0
    stop_y_offset: float = 12.0              # offset in +Y from hinge axis where the stop contacts

    def validate(self) -> None:
        for name in (
            "pin_diameter",
            "pin_length",
            "main_thickness",
            "main_mounting_wall_width",
            "main_mounting_wall_height",
            "main_extension_length",
            "main_extension_width",
            "main_extension_gap",
            "main_hole_offset_x",
            "link_base_length",
            "link_thickness",
            "link_base_width",
            "link_leg_length",
            "link_leg_width",
            "link_leg_gap",
            "door_offset_x",
            "door_bight_width",
            "door_bight_height",
            "door_thickness",
            "door_sidewall_depth",
            "leaf_flange_length",
            "leaf_flange_width",
            "leaf_flange_thickness",
        ):
            _require_positive(name, getattr(self, name))
        if self.pin_diameter * 2 >= self.main_hole_offset_x:
            raise ComponentBuildError(
                "pin_diameter is too large relative to main_hole_offset_x"
            )
        if self.link_leg_gap >= self.main_extension_gap:
            raise ComponentBuildError(
                "link_leg_gap must be < main_extension_gap (link nests inside main)"
            )
        if self.pin_head_style not in {"none", "flat", "round"}:
            raise ComponentBuildError(
                f"pin_head_style={self.pin_head_style!r} not supported"
            )

    # ----------------------------------------------------------------------
    # Construction helpers
    # ----------------------------------------------------------------------

    def _build_main_member(self) -> bd.Compound:
        """Body-half bracket: mounting wall + 2 extensions, all sharing
        the hinge axis on Z. Returns a Compound with named children."""
        children: list[bd.Part] = []
        t = self.main_thickness
        mw_w = self.main_mounting_wall_width
        mw_h = self.main_mounting_wall_height
        ext_l = self.main_extension_length
        ext_w = self.main_extension_width
        gap = self.main_extension_gap
        hole_x = self.main_hole_offset_x
        pin_r = self.pin_diameter / 2.0

        # Mounting wall: thin slab at -X, centered on origin in Y/Z.
        with bd.BuildPart() as mw:
            with bd.Locations((-t / 2.0, 0, 0)):
                bd.Box(t, mw_w, mw_h)
        mw.part.label = "mounting_wall"
        children.append(mw.part)

        # Upper extension: at +Z, starts at mounting wall and reaches +X.
        # Has a coaxial hole at (hole_x, 0, +gap/2 + t/2).
        for sign, label in ((+1.0, "upper_extension"), (-1.0, "lower_extension")):
            z_center = sign * (gap / 2.0 + t / 2.0)
            with bd.BuildPart() as ext:
                with bd.Locations((ext_l / 2.0, 0, z_center)):
                    bd.Box(ext_l, ext_w, t)
                # Drill the pintle hole through the extension.
                with bd.Locations((hole_x, 0, z_center)):
                    bd.Cylinder(pin_r * 1.05, t * 1.5, mode=bd.Mode.SUBTRACT)
            ext.part.label = label
            children.append(ext.part)

        return bd.Compound(label="main_member", children=children)

    def _build_u_link(self) -> bd.Compound:
        """Inner U-link: base wall + 2 legs, nested between main extensions."""
        children: list[bd.Part] = []
        t = self.link_thickness
        base_l = self.link_base_length
        base_w = self.link_base_width
        leg_l = self.link_leg_length
        leg_w = self.link_leg_width
        gap = self.link_leg_gap
        hole_x = self.main_hole_offset_x  # share the same axis as main member
        pin_r = self.pin_diameter / 2.0

        # Base wall — thin slab in YZ, sitting just inside the main mounting
        # wall, at +X = base_offset_x.
        base_offset_x = t / 2.0
        with bd.BuildPart() as base:
            with bd.Locations((base_offset_x, 0, 0)):
                bd.Box(t, base_w, gap + 2 * t)
        base.part.label = "base_wall"
        children.append(base.part)

        # Two legs, each reaching from base_wall in +X. Holes at hole_x.
        for sign, label in ((+1.0, "upper_leg"), (-1.0, "lower_leg")):
            z_center = sign * (gap / 2.0 + t / 2.0)
            with bd.BuildPart() as leg:
                with bd.Locations((leg_l / 2.0 + t, 0, z_center)):
                    bd.Box(leg_l, leg_w, t)
                with bd.Locations((hole_x, 0, z_center)):
                    bd.Cylinder(pin_r * 1.05, t * 1.5, mode=bd.Mode.SUBTRACT)
            leg.part.label = label
            children.append(leg.part)

        return bd.Compound(label="u_shaped_link_member", children=children)

    def _build_door_half(self) -> bd.Compound:
        """Door-half: U-channel + leaf flange. The leaf flange's pin hole
        sits on the Z axis at z = leaf_flange_z."""
        children: list[bd.Part] = []
        t = self.door_thickness
        bight_w = self.door_bight_width
        bight_h = self.door_bight_height
        depth = self.door_sidewall_depth
        offset_x = self.door_offset_x

        # Bight wall — slab in YZ at +X.
        with bd.BuildPart() as bight:
            with bd.Locations((offset_x + t / 2.0, 0, 0)):
                bd.Box(t, bight_w, bight_h)
        bight.part.label = "bight_wall"
        children.append(bight.part)

        # Two sidewalls — slabs in XZ, on +Y and -Y faces, reaching back
        # toward the hinge axis (in -X direction).
        for sign, label in ((+1.0, "first_sidewall"), (-1.0, "second_sidewall")):
            x_center = offset_x - depth / 2.0
            with bd.BuildPart() as sw:
                with bd.Locations((x_center, sign * (bight_w / 2.0 - t / 2.0), 0)):
                    bd.Box(depth, t, bight_h)
            sw.part.label = label
            children.append(sw.part)

        # Leaf flange — small plate projecting from first_sidewall's inner
        # face toward the hinge axis. Its pin hole is on the Z axis at
        # z = leaf_flange_z.
        lf_x_center = self.main_hole_offset_x  # hole on the hinge axis
        # Flange is a plate centered such that its hole sits at (0, 0, z).
        # We place the flange so its hole is on the Z axis.
        flange_x_extent = self.leaf_flange_length
        flange_y_extent = self.leaf_flange_width
        flange_z = self.leaf_flange_z
        # Position the flange so it spans from sidewall (+Y) inward.
        flange_x_center = self.main_hole_offset_x  # pin axis
        flange_y_center = (
            self.door_bight_width / 2.0 - self.door_thickness - flange_y_extent / 2.0
        )
        with bd.BuildPart() as flange:
            with bd.Locations((flange_x_center, flange_y_center, flange_z)):
                bd.Box(flange_x_extent, flange_y_extent, self.leaf_flange_thickness)
            # Drill the pintle hole through the flange.
            with bd.Locations((self.main_hole_offset_x, 0, flange_z)):
                bd.Cylinder(
                    self.pin_diameter / 2.0 * 1.05,
                    self.leaf_flange_thickness * 1.5,
                    mode=bd.Mode.SUBTRACT,
                )
        flange.part.label = "leaf_flange"
        children.append(flange.part)

        return bd.Compound(label="door_half_member", children=children)

    def _build_pintle_pin(self) -> bd.Part:
        """Vertical pin on the Z axis at x = main_hole_offset_x."""
        with bd.BuildPart() as pin:
            with bd.Locations((self.main_hole_offset_x, 0, 0)):
                bd.Cylinder(self.pin_diameter / 2.0, self.pin_length)
            if self.pin_head_style != "none":
                head_d = self.pin_head_diameter
                head_h = self.pin_head_height
                with bd.Locations(
                    (self.main_hole_offset_x, 0, self.pin_length / 2.0 + head_h / 2.0)
                ):
                    if self.pin_head_style == "round":
                        bd.Sphere(head_d / 2.0)
                    else:
                        bd.Cylinder(head_d / 2.0, head_h)
        pin.part.label = "pintle_pin"
        return pin.part

    def _build_stop(self) -> bd.Part:
        """Small cylinder on the inner U-link's upper face contacting the
        main member's upper extension to limit rotation."""
        with bd.BuildPart() as stop:
            z_center = (
                self.link_leg_gap / 2.0
                + self.link_thickness
                + self.stop_height / 2.0
            )
            with bd.Locations(
                (self.main_hole_offset_x * 0.6, self.stop_y_offset, z_center)
            ):
                bd.Cylinder(self.stop_diameter / 2.0, self.stop_height)
        stop.part.label = "stop_means"
        return stop.part

    def _build_solid(self) -> bd.Compound:
        children: list[bd.Part | bd.Compound] = [
            self._build_main_member(),
            self._build_u_link(),
            self._build_door_half(),
            self._build_pintle_pin(),
        ]
        if self.include_stop:
            children.append(self._build_stop())
        return bd.Compound(label="lift_off_hinge_assembly", children=children)

    # ----------------------------------------------------------------------
    # Mounting / annotation
    # ----------------------------------------------------------------------

    def mounting_points(
        self, solid: bd.Compound | None = None
    ) -> dict[str, tuple[float, float, float]]:
        return {
            "hinge_axis_top": (self.main_hole_offset_x, 0.0, +self.pin_length / 2.0),
            "hinge_axis_bottom": (self.main_hole_offset_x, 0.0, -self.pin_length / 2.0),
            "main_mounting_wall_center": (-self.main_thickness / 2.0, 0.0, 0.0),
            "door_bight_center": (
                self.door_offset_x + self.door_thickness / 2.0,
                0.0,
                0.0,
            ),
            "leaf_flange_hole": (
                self.main_hole_offset_x,
                0.0,
                self.leaf_flange_z,
            ),
        }


# Param aliases — let the VLM emit natural names.
_LIFT_OFF_PARAM_ALIASES = {
    # pin
    "pin_dia": "pin_diameter",
    "pin_d": "pin_diameter",
    "pintle_diameter": "pin_diameter",
    "pintle_pin_diameter": "pin_diameter",
    "pintle_length": "pin_length",
    # main member
    "mounting_wall_width": "main_mounting_wall_width",
    "mounting_wall_height": "main_mounting_wall_height",
    "extension_length": "main_extension_length",
    "extension_width": "main_extension_width",
    "extension_gap": "main_extension_gap",
    "hole_offset": "main_hole_offset_x",
    "hole_offset_x": "main_hole_offset_x",
    # link
    "link_base": "link_base_length",
    # door
    "door_width": "door_bight_width",
    "door_height": "door_bight_height",
    "door_offset": "door_offset_x",
    "sidewall_depth": "door_sidewall_depth",
    # leaf flange
    "flange_length": "leaf_flange_length",
    "flange_width": "leaf_flange_width",
    "flange_thickness": "leaf_flange_thickness",
    "flange_z": "leaf_flange_z",
    # stop
    "stop_dia": "stop_diameter",
}


_LIFT_OFF_PARAM_SCHEMA = {
    "pin_diameter": "float, mm — pintle pin diameter (typical 5-8)",
    "pin_length": "float, mm — total pin length along Z (typical 80-110)",
    "pin_head_style": "string in {none, flat, round}",
    "main_thickness": "float, mm — sheet thickness of body-half bracket (typical 2.5-4)",
    "main_mounting_wall_width": "float, mm — width of mounting wall in Y",
    "main_mounting_wall_height": "float, mm — height of mounting wall in Z",
    "main_extension_length": "float, mm — how far each extension reaches in +X",
    "main_extension_width": "float, mm — extension width in Y",
    "main_extension_gap": "float, mm — vertical gap between upper and lower extensions",
    "main_hole_offset_x": "float, mm — distance from mounting wall to pintle axis (= hinge axis x)",
    "link_base_length": "float, mm — link base wall extent in X",
    "link_thickness": "float, mm — link sheet thickness",
    "link_base_width": "float, mm — link base wall width in Y",
    "link_leg_length": "float, mm — length of each link leg in +X",
    "link_leg_width": "float, mm — width of each link leg in Y",
    "link_leg_gap": "float, mm — gap between link's upper/lower legs (must be < main_extension_gap)",
    "door_offset_x": "float, mm — distance from origin to door bight wall (typical 25-40)",
    "door_bight_width": "float, mm — width of door channel along Y",
    "door_bight_height": "float, mm — height of door channel along Z",
    "door_thickness": "float, mm — door sheet thickness",
    "door_sidewall_depth": "float, mm — how far the sidewalls reach back toward the hinge",
    "leaf_flange_length": "float, mm — flange extent in X",
    "leaf_flange_width": "float, mm — flange extent in Y",
    "leaf_flange_thickness": "float, mm — flange sheet thickness",
    "leaf_flange_z": "float, mm — vertical position of leaf flange (between link upper leg and main upper extension)",
    "include_stop": "bool — include the small stop cylinder",
    "stop_diameter": "float, mm",
    "stop_height": "float, mm",
    "stop_y_offset": "float, mm",
}


@register(
    "lift_off_hinge",
    aliases=(
        "lift_off_hinge_assembly",
        "lift_off_door_hinge",
        "vehicle_door_hinge",
        "pintle_hinge",
        "hinge_body_half_assembly",  # patent IR uses this name for the whole body-half
    ),
    description="Lift-off hinge assembly (US4807331A family): body-half bracket + nested U-link + door-half U-channel + leaf flange + pintle pin, all coaxial.",
    param_aliases=_LIFT_OFF_PARAM_ALIASES,
    param_schema=_LIFT_OFF_PARAM_SCHEMA,
)
def make_lift_off_hinge(**kwargs) -> LiftOffHingeAssembly:
    return LiftOffHingeAssembly(**kwargs)


__all__ = ["LiftOffHingeAssembly"]
