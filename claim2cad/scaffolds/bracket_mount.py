"""V13-B — BracketMountScaffold.

Base plate + vertical bracket + mounted block with fasteners.
"""
from __future__ import annotations

import build123d as bd

from claim2cad.scaffolds.base import (
    Scaffold, ScaffoldInput, ScaffoldResult, register_scaffold,
)


@register_scaffold
class BracketMountScaffold(Scaffold):
    """Bracket-and-mount layout."""

    scaffold_id = "bracket_mount"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        cids = inputs.component_ids() or ["component_0"]
        children: list[bd.Part] = []
        ordered: list[str] = []
        for i, cid in enumerate(cids):
            label = inputs.component_label(cid).lower()
            if any(k in label for k in ("base", "plate")):
                solid = bd.Box(120.0, 80.0, 6.0).translate((0.0, 0.0, -40.0))
            elif any(k in label for k in ("bracket", "mount")):
                v = bd.Box(8.0, 60.0, 50.0)
                h = bd.Box(50.0, 60.0, 8.0).translate((21.0, 0.0, -21.0))
                solid = (v + h).translate((0.0, 0.0, -10.0))
            elif "fastener" in label or "bolt" in label:
                head = bd.Cylinder(radius=2.5, height=2.0).translate((0, 0, 5.0))
                shaft = bd.Cylinder(radius=1.2, height=10.0)
                solid = (head + shaft).translate(
                    (-40.0 + i * 20.0, 0.0, -36.0))
            else:
                solid = bd.Box(20.0, 20.0, 20.0).translate(
                    (40.0 + (i * 10.0 % 30.0), 0.0, +10.0 + (i // 3) * 22.0))
            solid.label = cid
            children.append(solid); ordered.append(cid)
        compound = bd.Compound(label="assembly", children=children)
        return ScaffoldResult(
            compound=compound, ordered_ids=ordered,
            scaffold_id=self.scaffold_id,
            diagnostics={"n_components": len(cids)},
            quality_tier="partial",
        )
