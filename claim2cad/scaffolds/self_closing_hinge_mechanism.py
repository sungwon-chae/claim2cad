"""V13-L — SelfClosingHingeMechanismScaffold.

A self-closing hinge mechanism is NOT a flat door + frame +
pintle (that's `door_hinge`). It is a vertical cam-and-spring
assembly: a long base rail, a vertical post rising from the
base, a hinge body / cam mounted on the post, a horizontal
lever extending from the cam, a cylinder + rod inside the post
for the spring or hydraulic damper, an upper stop block, and
flanking mounting blocks.

Used by US4470181A_self_closing_hinge.
"""
from __future__ import annotations

import logging

import build123d as bd

from claim2cad.scaffolds.base import (
    Scaffold,
    ScaffoldInput,
    ScaffoldResult,
    register_scaffold,
)

logger = logging.getLogger(__name__)


_ROUTING: list[tuple[str, tuple[str, ...]]] = [
    ("base_rail", ("base", "base rail", "platform", "ground rail",
                    "support rail", "frame")),
    ("post", ("post", "column", "vertical support",
               "stand", "upright")),
    ("hinge_body", ("hinge body", "cam", "hinge cam",
                     "mechanism body", "rotating body",
                     "inserting mechanism", "transferring mechanism",
                     "transporting mechanism")),
    ("lever", ("lever", "closing arm", "closer arm",
                "operating handle", "handle",
                "drive mechanism")),
    ("cylinder", ("cylinder", "spring cylinder",
                   "hydraulic cylinder", "damper")),
    ("rod", ("rod", "piston rod", "piston", "spring rod",
              "drive rod")),
    ("spring", ("spring", "torsion spring", "compression spring",
                "coil spring")),
    ("stop_block", ("stop", "upper stop", "stop block",
                     "limit block", "upper block",
                     "control means", "escapement mechanism")),
    ("mount_left", ("first mount", "left mount",
                     "first mounting", "first bracket",
                     "left bracket")),
    ("mount_right", ("second mount", "right mount",
                      "second mounting", "second bracket",
                      "right bracket")),
    ("connector", ("connector", "electrical connector",
                    "connector half", "interface")),
    ("wire_array", ("wire array", "array of wires", "wires",
                     "color-coded wires")),
    ("sensor", ("sensor", "detector", "limit switch")),
    ("locating_means", ("locating means", "alignment means",
                         "aligning means", "guide means")),
    ("position_set", ("color-coded positions",
                       "position set", "rows of contacts")),
]


@register_scaffold
class SelfClosingHingeMechanismScaffold(Scaffold):
    """Vertical cam-and-spring hinge mechanism.

    Builds: base rail (long, flat, low) → post (vertical) →
    hinge body / cam (atop the post) → lever (horizontal) →
    cylinder + rod inside the post → upper stop block →
    flanking mount blocks. The silhouette is dominated by the
    vertical post; nothing in the result looks like a flat door
    panel + pintle hinge.
    """

    scaffold_id = "self_closing_hinge_mechanism"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        cids = inputs.component_ids() or ["component_0"]
        n = len(cids)

        # ---- Geometry ----
        # V13-R: thicker base + visible rail channels, fatter post,
        # explicit cam wheel between hinge body and lever, much
        # bigger spring (visible coils), prominent lever.
        BASE_X, BASE_Y, BASE_Z = 200.0, 78.0, 16.0
        base_rail = bd.Box(BASE_X, BASE_Y, BASE_Z).translate(
            (0.0, 0.0, BASE_Z / 2.0))
        # Two visible rail channels on the top face.
        rail_channel_a = bd.Box(BASE_X * 0.95, 8.0, 3.0).translate(
            (0.0, -BASE_Y / 2.0 + 12.0, BASE_Z + 1.5))
        rail_channel_b = bd.Box(BASE_X * 0.95, 8.0, 3.0).translate(
            (0.0, +BASE_Y / 2.0 - 12.0, BASE_Z + 1.5))
        base_rail = base_rail + rail_channel_a + rail_channel_b

        POST_X, POST_Y, POST_Z = 36.0, 36.0, 130.0
        post_cx = -16.0
        post = bd.Box(POST_X, POST_Y, POST_Z).translate(
            (post_cx, 0.0, BASE_Z + POST_Z / 2.0))

        hinge_body_z = BASE_Z + POST_Z + 14.0
        hinge_body = bd.Cylinder(radius=24.0, height=28.0).translate(
            (post_cx, 0.0, hinge_body_z))

        # Cam wheel — a slightly larger thin disc just below the
        # hinge body, visible cam profile (eccentric to suggest
        # a cam contour).
        cam_wheel = bd.Cylinder(radius=20.0, height=8.0).translate(
            (post_cx + 4.0, 0.0, hinge_body_z - 18.0))

        # Lever — long horizontal arm with a ball end. Made
        # noticeably thicker than V13-L.
        LEVER_LEN = 90.0
        lever_arm = bd.Box(LEVER_LEN, 14.0, 12.0).translate(
            (post_cx - 24.0 - LEVER_LEN / 2.0, 0.0,
             hinge_body_z + 4.0))
        lever_ball = bd.Sphere(radius=10.0).translate(
            (post_cx - 24.0 - LEVER_LEN, 0.0,
             hinge_body_z + 4.0))
        lever = bd.Compound(label="lever_combined",
                             children=[lever_arm, lever_ball])

        # Cylinder + rod inside the post — offset so they peek
        # past the post in oblique view.
        cylinder = bd.Cylinder(radius=10.0, height=POST_Z * 0.7).translate(
            (post_cx + POST_X / 2.0 + 2.0, +10.0,
             BASE_Z + POST_Z * 0.45))
        rod = bd.Cylinder(radius=3.0, height=POST_Z * 0.85).translate(
            (post_cx + POST_X / 2.0 + 2.0, -10.0,
             BASE_Z + POST_Z * 0.5))

        # Spring — explicit coil profile via a stack of thin discs
        # on a thin core. The compound suggests visible coils.
        spring_core = bd.Cylinder(radius=2.5,
                                    height=POST_Z * 0.55).translate(
            (post_cx + POST_X / 2.0 + 16.0, 0.0,
             BASE_Z + POST_Z * 0.45))
        coil_parts = []
        n_coils = 7
        coil_h = POST_Z * 0.55 / n_coils
        for i in range(n_coils):
            cz = BASE_Z + POST_Z * 0.18 + (i + 0.5) * coil_h
            coil_parts.append(
                bd.Cylinder(radius=6.0, height=coil_h * 0.6).translate(
                    (post_cx + POST_X / 2.0 + 16.0, 0.0, cz)))
        spring = bd.Compound(label="spring_coils",
                              children=[spring_core, *coil_parts])

        # Upper stop block — chunkier than V13-L.
        stop_block = bd.Box(48.0, 36.0, 36.0).translate(
            (post_cx, 0.0, hinge_body_z + 32.0))

        # Mount blocks flanking the post — bigger feet so they
        # read as anchors, not pebbles.
        mount_left = bd.Box(POST_X * 1.15, 22.0, 30.0).translate(
            (post_cx, -POST_Y / 2.0 - 18.0, BASE_Z + 15.0))
        mount_right = bd.Box(POST_X * 1.15, 22.0, 30.0).translate(
            (post_cx, +POST_Y / 2.0 + 18.0, BASE_Z + 15.0))

        # Auxiliary fixtures on the +X half of the base (so they
        # don't crowd the main hinge silhouette).
        connector = bd.Box(28.0, 18.0, 10.0).translate(
            (+72.0, +20.0, BASE_Z + 5.0))
        wire_array = bd.Box(44.0, 24.0, 5.0).translate(
            (+62.0, -20.0, BASE_Z + 2.5))
        sensor = bd.Sphere(radius=5.0).translate(
            (+40.0, +28.0, BASE_Z + 26.0))
        locating_means = bd.Cylinder(radius=4.0, height=14.0).translate(
            (+52.0, 0.0, BASE_Z + 7.0))
        position_set = bd.Box(40.0, 20.0, 4.0).translate(
            (+62.0, 0.0, BASE_Z + 2.0))

        meshes: dict[str, bd.Part] = {
            "base_rail": base_rail,
            "post": post,
            "hinge_body": hinge_body,
            "cam_wheel": cam_wheel,
            "lever": lever,
            "cylinder": cylinder,
            "rod": rod,
            "spring": spring,
            "stop_block": stop_block,
            "mount_left": mount_left,
            "mount_right": mount_right,
            "connector": connector,
            "wire_array": wire_array,
            "sensor": sensor,
            "locating_means": locating_means,
            "position_set": position_set,
        }

        # ---- Route claim ids ----
        children: list[bd.Part] = []
        ordered: list[str] = []
        used: set[str] = set()
        for cid in cids:
            label = inputs.component_label(cid).lower()
            target = self._route(label)
            mesh = meshes.get(target) if target else None
            if mesh is not None and target not in used:
                mesh.label = cid
                children.append(mesh)
                ordered.append(cid)
                used.add(target)
            elif mesh is not None:
                bb = mesh.bounding_box()
                m = bd.Sphere(radius=2.0).translate(
                    (bb.max.X + 5.0,
                     (bb.min.Y + bb.max.Y) * 0.5,
                     bb.max.Z + 4.0))
                m.label = cid
                children.append(m)
                ordered.append(cid)
            else:
                idx = sum(1 for x in ordered) % 6
                m = bd.Sphere(radius=2.0).translate(
                    (+70.0, -32.0 + idx * 9.0, 12.0 * 0.5 + 4.0))
                m.label = cid
                children.append(m)
                ordered.append(cid)

        # Emit the structural meshes that nobody claimed.
        STRUCTURAL = {"base_rail", "post", "hinge_body",
                       "cam_wheel", "lever",
                       "cylinder", "rod", "spring", "stop_block",
                       "mount_left", "mount_right"}
        for name, mesh in meshes.items():
            if name in used or name not in STRUCTURAL:
                continue
            mesh.label = name
            children.append(mesh)
            ordered.append(name)

        compound = bd.Compound(label="assembly", children=children)
        return ScaffoldResult(
            compound=compound,
            ordered_ids=ordered,
            scaffold_id=self.scaffold_id,
            diagnostics={
                "n_components": n,
                "structural_meshes": sorted(STRUCTURAL),
            },
            quality_tier="good",
        )

    @staticmethod
    def _route(label: str) -> str | None:
        for target, kws in _ROUTING:
            if any(k in label for k in kws):
                return target
        return None
