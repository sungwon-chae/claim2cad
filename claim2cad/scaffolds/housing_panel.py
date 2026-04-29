"""V13-B + V14-E — HousingPanelScaffold."""
from __future__ import annotations

import build123d as bd

from claim2cad.scaffolds.base import (
    Scaffold, ScaffoldInput, ScaffoldResult, register_scaffold,
)
from claim2cad import v14_primitives as v14p


@register_scaffold
class HousingPanelScaffold(Scaffold):
    """Hollow enclosure + bolted cover plate. V14-E uses
    ``enclosure`` + ``cover_plate`` so the box has visible
    walls and bolt-hole pattern instead of a solid cube."""

    scaffold_id = "housing_panel"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        cids = inputs.component_ids() or ["component_0"]
        children: list[bd.Part] = []
        ordered: list[str] = []
        for i, cid in enumerate(cids):
            label = inputs.component_label(cid).lower()
            if any(k in label for k in ("housing", "case",
                                          "enclosure", "body")):
                solid = v14p.enclosure(length=120.0, width=80.0,
                                         height=60.0, wall=4.0)
            elif any(k in label for k in ("cover", "lid", "top")):
                solid = v14p.cover_plate(length=120.0, width=80.0,
                                           thickness=5.0, n_holes=4,
                                           hole_inset=8.0)
                solid = solid.translate((0.0, 0.0, +33.0))
            elif any(k in label for k in ("fastener", "bolt",
                                            "screw")):
                solid = v14p.bolt(head_radius=2.5,
                                    head_height=2.0,
                                    shaft_radius=1.4,
                                    shaft_length=10.0)
                solid = solid.translate(
                    (-50.0 + (i * 25.0) % 100.0, 35.0, +35.0))
            elif "washer" in label:
                solid = v14p.washer()
                solid = solid.translate(
                    (-50.0 + (i * 25.0) % 100.0, +30.0, +33.0))
            elif "port" in label or "opening" in label:
                solid = v14p.flanged_housing(body_radius=10.0,
                                               body_height=22.0,
                                               flange_radius=14.0,
                                               flange_height=3.0,
                                               n_holes=4)
                solid = solid.translate((45.0, 30.0, 10.0))
            elif any(k in label for k in ("bracket", "flange",
                                            "tab")):
                solid = v14p.l_bracket(leg_a=24.0, leg_b=24.0,
                                         width=18.0, thickness=3.0)
                solid = solid.translate((-65.0, -30.0,
                                            -28.0 + (i // 3) * 22.0))
            else:
                solid = v14p.chamfered_plate(length=22.0,
                                               width=22.0,
                                               thickness=12.0,
                                               chamfer=2.0)
                solid = solid.translate(
                    (40.0 + (i * 10.0 % 30.0), -30.0,
                     -25.0 + (i // 3) * 20.0))
            solid.label = cid
            children.append(solid); ordered.append(cid)
        compound = bd.Compound(label="assembly", children=children)
        return ScaffoldResult(
            compound=compound, ordered_ids=ordered,
            scaffold_id=self.scaffold_id,
            diagnostics={"n_components": len(cids)},
            # V14-E: hollow enclosure with cover-plate bolt
            # pattern → good.
            quality_tier="good",
        )
