"""V13-B + V14-E — BracketMountScaffold.

Base plate + vertical bracket + mounted block with fasteners.
V14-E swaps in v14_primitives so the geometry reads as a real
mount instead of stacked boxes.
"""
from __future__ import annotations

import build123d as bd

from claim2cad.scaffolds.base import (
    Scaffold, ScaffoldInput, ScaffoldResult, register_scaffold,
)
from claim2cad import v14_primitives as v14p


@register_scaffold
class BracketMountScaffold(Scaffold):
    """Bracket-and-mount layout — base + L/U/gusset bracket +
    bolted mounted block."""

    scaffold_id = "bracket_mount"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        cids = inputs.component_ids() or ["component_0"]
        children: list[bd.Part] = []
        ordered: list[str] = []
        bracket_used = False
        for i, cid in enumerate(cids):
            label = inputs.component_label(cid).lower()
            if any(k in label for k in ("base", "plate", "ground")):
                solid = v14p.slotted_base(length=140.0, width=90.0,
                                            height=8.0,
                                            slot_w=6.0, slot_l=30.0,
                                            n_slots=2)
                solid = solid.translate((0.0, 0.0, -40.0))
            elif any(k in label for k in ("u-bracket", "u bracket")):
                solid = v14p.u_bracket(length=70.0, arm_height=40.0,
                                         width=28.0, thickness=5.0)
                solid = solid.translate((0.0, 0.0, -30.0))
                bracket_used = True
            elif any(k in label for k in ("c-bracket", "c bracket",
                                            "channel")):
                solid = v14p.c_bracket(length=60.0, arm_length=24.0,
                                         width=24.0, thickness=5.0)
                solid = solid.translate((0.0, 0.0, -30.0))
                bracket_used = True
            elif any(k in label for k in ("gusset",)):
                solid = v14p.gusset_bracket(leg_a=60.0, leg_b=50.0,
                                              thickness=5.0,
                                              width=20.0)
                solid = solid.translate((0.0, 0.0, -30.0))
                bracket_used = True
            elif any(k in label for k in ("bracket", "mount",
                                            "flange", "post")):
                if not bracket_used:
                    solid = v14p.l_bracket(leg_a=50.0, leg_b=50.0,
                                              width=24.0,
                                              thickness=5.0)
                    bracket_used = True
                else:
                    solid = v14p.gusset_bracket(leg_a=40.0,
                                                  leg_b=40.0,
                                                  thickness=4.0,
                                                  width=18.0)
                solid = solid.translate((0.0, 0.0, -30.0))
            elif any(k in label for k in ("fastener", "bolt",
                                            "screw", "stud")):
                solid = v14p.bolt(head_radius=3.0, head_height=2.5,
                                    shaft_radius=1.4,
                                    shaft_length=12.0)
                solid = solid.translate(
                    (-40.0 + (i % 5) * 18.0, 0.0, -32.0))
            elif any(k in label for k in ("washer",)):
                solid = v14p.washer()
                solid = solid.translate(
                    (-30.0 + (i % 4) * 14.0, +14.0, -32.0))
            elif any(k in label for k in ("nut",)):
                solid = v14p.nut()
                solid = solid.translate(
                    (-22.0 + (i % 4) * 14.0, -14.0, -32.0))
            else:
                # Mounted block as a chamfered plate.
                solid = v14p.chamfered_plate(length=22.0,
                                               width=22.0,
                                               thickness=14.0,
                                               chamfer=2.0)
                solid = solid.translate(
                    (40.0 + (i * 10.0 % 30.0), 0.0,
                     +10.0 + (i // 3) * 22.0))
            solid.label = cid
            children.append(solid); ordered.append(cid)
        compound = bd.Compound(label="assembly", children=children)
        return ScaffoldResult(
            compound=compound, ordered_ids=ordered,
            scaffold_id=self.scaffold_id,
            diagnostics={"n_components": len(cids)},
            # V14-E: l/u/c/gusset brackets + bolt-headed
            # fasteners → good.
            quality_tier="good",
        )
