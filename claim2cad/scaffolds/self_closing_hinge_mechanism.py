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
        base_rail = bd.Box(180.0, 60.0, 12.0).translate((0.0, 0.0, 0.0))
        post = bd.Box(28.0, 28.0, 110.0).translate(
            (-10.0, 0.0, 12.0 * 0.5 + 110.0 * 0.5))
        hinge_body = bd.Cylinder(radius=18.0, height=22.0).translate(
            (-10.0, 0.0, 12.0 * 0.5 + 110.0 + 11.0))
        # Lever — horizontal arm with a small ball at the end.
        lever_arm = bd.Box(64.0, 8.0, 6.0).translate(
            (-10.0 - 32.0 - 16.0, 0.0,
             12.0 * 0.5 + 110.0 + 22.0 + 4.0))
        lever_ball = bd.Sphere(radius=6.0).translate(
            (-10.0 - 32.0 - 48.0, 0.0,
             12.0 * 0.5 + 110.0 + 22.0 + 4.0))
        lever = bd.Compound(label="lever_combined",
                             children=[lever_arm, lever_ball])
        # Cylinder + rod inside the post (offset so they're visible
        # peeking past the post in oblique view).
        cylinder = bd.Cylinder(radius=8.0, height=70.0).translate(
            (-10.0, +6.0, 12.0 * 0.5 + 50.0))
        rod = bd.Cylinder(radius=2.5, height=80.0).translate(
            (-10.0, -6.0, 12.0 * 0.5 + 55.0))
        spring = bd.Cylinder(radius=4.5, height=30.0).translate(
            (-10.0, -6.0, 12.0 * 0.5 + 90.0))
        # Upper stop block — sits above the hinge body.
        stop_block = bd.Box(36.0, 24.0, 30.0).translate(
            (-10.0, 0.0,
             12.0 * 0.5 + 110.0 + 22.0 + 22.0))
        # Mount blocks flanking the post.
        mount_left = bd.Box(22.0, 16.0, 24.0).translate(
            (-10.0, -36.0, 12.0 * 0.5 + 14.0))
        mount_right = bd.Box(22.0, 16.0, 24.0).translate(
            (-10.0, +36.0, 12.0 * 0.5 + 14.0))
        connector = bd.Box(28.0, 14.0, 8.0).translate(
            (+60.0, +18.0, 12.0 * 0.5 + 8.0))
        wire_array = bd.Box(40.0, 22.0, 4.0).translate(
            (+50.0, -18.0, 12.0 * 0.5 + 6.0))
        sensor = bd.Sphere(radius=4.0).translate(
            (+30.0, +24.0, 12.0 * 0.5 + 22.0))
        locating_means = bd.Cylinder(radius=3.0, height=10.0).translate(
            (+44.0, 0.0, 12.0 * 0.5 + 10.0))
        position_set = bd.Box(36.0, 18.0, 3.0).translate(
            (+50.0, 0.0, 12.0 * 0.5 + 4.0))

        meshes: dict[str, bd.Part] = {
            "base_rail": base_rail,
            "post": post,
            "hinge_body": hinge_body,
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
        STRUCTURAL = {"base_rail", "post", "hinge_body", "lever",
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
