"""V13-B + V14-E — LinkageScaffold.

For robotic arms, four-bar linkages, pivot mechanisms. Lays out
links in a chain with separation along Z (for arm-like
articulation) and labelled pivot pins.

V14-E: links are now ``link_bar`` (rounded ends + holes), pivots
are ``pivot_pin`` (head + shaft), and the base is a
``slotted_base`` so the result reads as an articulated machine
rather than a stack of boxes.
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
from claim2cad import v14_primitives as v14p

logger = logging.getLogger(__name__)


@register_scaffold
class LinkageScaffold(Scaffold):
    """Articulated linkage layout. Links chain along the X axis;
    each link is offset in Z so the chain reads as a kinematic
    arm rather than a stack."""

    scaffold_id = "linkage"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        cids = inputs.component_ids() or ["component_0"]
        n = len(cids)

        # Sort the components into LINKS / PIVOTS / BASE / END.
        link_cids: list[str] = []
        pivot_cids: list[str] = []
        base_cid: str | None = None
        end_cid: str | None = None
        other_cids: list[str] = []
        for cid in cids:
            label = inputs.component_label(cid).lower()
            if any(k in label for k in ("base", "frame", "ground", "platform")):
                if base_cid is None:
                    base_cid = cid
                else:
                    other_cids.append(cid)
            elif any(k in label for k in ("end", "wrist", "gripper", "tool", "effector")):
                if end_cid is None:
                    end_cid = cid
                else:
                    other_cids.append(cid)
            elif any(k in label for k in ("pivot", "joint", "shaft", "axis", "pin")):
                pivot_cids.append(cid)
            elif any(k in label for k in ("link", "arm", "extension", "lever")):
                link_cids.append(cid)
            else:
                other_cids.append(cid)

        # Mix unassigned into link_cids if nothing classified.
        if not link_cids:
            link_cids = other_cids
            other_cids = []

        children: list[bd.Part] = []
        ordered: list[str] = []

        # Base — slotted base plate at -Z (V14-E).
        if base_cid:
            base = v14p.slotted_base(length=140.0, width=90.0,
                                       height=10.0, slot_w=6.0,
                                       slot_l=30.0, n_slots=2)
            base = base.translate((0.0, 0.0, -100.0))
            base.label = base_cid
            children.append(base); ordered.append(base_cid)

        # Links — V14-E uses link_bar (rounded ends + through-
        # holes) so it reads as a kinematic link.
        link_x = -60.0
        link_z = -80.0
        for i, cid in enumerate(link_cids):
            link = v14p.link_bar(length=60.0, width=10.0,
                                   thickness=8.0,
                                   hole_radius=2.0, n_holes=2)
            cx = link_x + i * 30.0
            cz = link_z + i * 30.0
            link = link.translate((cx, 0.0, cz))
            link.label = cid
            children.append(link); ordered.append(cid)

        # Pivots — pivot_pin (head + shaft) at the joints.
        for i, cid in enumerate(pivot_cids):
            pin_x = link_x + i * 30.0 + 25.0
            pin_z = link_z + i * 30.0 + 15.0
            pin = v14p.pivot_pin(radius=2.5, length=18.0,
                                   head_radius=4.5, head_height=2.5)
            pin = pin.translate((pin_x, 0.0, pin_z))
            pin.label = cid
            children.append(pin); ordered.append(cid)

        # End effector — clevis joint at the end of the chain.
        if end_cid:
            end_x = link_x + len(link_cids) * 30.0 + 5.0
            end_z = link_z + len(link_cids) * 30.0 + 5.0
            ef = v14p.clevis_joint(width=18.0, length=22.0,
                                     thickness=5.0, gap=8.0)
            ef = ef.translate((end_x, 0.0, end_z))
            ef.label = end_cid
            children.append(ef); ordered.append(end_cid)

        # Other parts — small markers around the centroid so they're
        # at least selectable.
        for i, cid in enumerate(other_cids):
            m = bd.Sphere(radius=2.5)
            m = m.translate((20.0 + i * 8.0, +30.0, 0.0))
            m.label = cid
            children.append(m); ordered.append(cid)

        if not children:
            # extreme fallback
            m = bd.Sphere(radius=2.0); m.label = cids[0]
            children.append(m); ordered.append(cids[0])
        compound = bd.Compound(label="assembly", children=children)
        return ScaffoldResult(
            compound=compound, ordered_ids=ordered,
            scaffold_id=self.scaffold_id,
            diagnostics={
                "n_components": n,
                "n_links": len(link_cids),
                "n_pivots": len(pivot_cids),
                "has_base": base_cid is not None,
                "has_end_effector": end_cid is not None,
            },
            # V14-E: link_bar + clevis + pivot_pin + slotted_base
            # → good (reads as articulated linkage, not boxes).
            quality_tier="good",
        )
