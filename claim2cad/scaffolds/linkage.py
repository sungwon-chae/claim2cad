"""V13-B — LinkageScaffold.

For robotic arms, four-bar linkages, pivot mechanisms. Lays out
links in a chain with separation along Z (for arm-like
articulation) and labelled pivot pins.
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

        # Base — large flat plate at -Z.
        if base_cid:
            base = bd.Box(120.0, 80.0, 8.0).translate((0.0, 0.0, -100.0))
            base.label = base_cid
            children.append(base); ordered.append(base_cid)

        # Links — each one is a 50 mm rectangular bar; chain along
        # X with vertical offset so the arm articulates upward.
        link_x = -60.0
        link_z = -80.0
        for i, cid in enumerate(link_cids):
            link = bd.Box(60.0, 8.0, 14.0)
            cx = link_x + i * 30.0
            cz = link_z + i * 30.0
            link = link.translate((cx, 0.0, cz))
            link.label = cid
            children.append(link); ordered.append(cid)

        # Pivots — small cylinders at the joints between consecutive
        # links.
        for i, cid in enumerate(pivot_cids):
            pin_x = link_x + i * 30.0 + 25.0
            pin_z = link_z + i * 30.0 + 15.0
            pin = bd.Cylinder(radius=3.0, height=18.0).translate((pin_x, 0.0, pin_z))
            pin.label = cid
            children.append(pin); ordered.append(cid)

        # End effector — block at the end of the chain.
        if end_cid:
            end_x = link_x + len(link_cids) * 30.0 + 5.0
            end_z = link_z + len(link_cids) * 30.0 + 5.0
            ef = bd.Box(20.0, 20.0, 20.0).translate((end_x, 0.0, end_z))
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
            quality_tier="partial",
        )
