# V1.2 — Visual reconstruction

Design notes for the v1.2 phase. The goal was to replace v1.1's
"central pile of bars" with an assembly a human accepts as a
patent-figure-grounded mechanical model.

## Starting point (V12-A — visual truth audit)

The v1.1 pipeline shipped a working data backbone:
* claim → IR (verified spans),
* IR → per-component shape inference,
* shape inference → constraint solver → STEP/GLB,
* GLB-naming contract preserved end-to-end,
* leader-line hotspot detection at 95% on US4807331A.

But the geometry was wrong. The audit
(`examples/real_patents/US4807331A_spring_loaded_hinge/VISUAL_TRUTH_AUDIT.md`)
identified six concrete failures:

1. No curved or angled door panel.
2. No spatial separation between upper and lower hinge clusters.
3. Pintle shaft not visible as a distinct long-thin feature.
4. Brackets float in front of panels; no attachment.
5. `figure_projection.json` group anchors collapsed to a single
   X column because most callouts cluster on the right half.
6. Viewer defaults to `golden_robot_arm`, not US4807331A; render
   mode is edge-shaded wireframe, not shaded solid.

## V12-B — Figure-first projection layout lock

`claim2cad/figure_layout_lock.py` reads
`<example>/figure_layout_lock.json` — a hand-traced map of UV
regions per group (door_panel, fixed_frame, upper_hinge,
lower_hinge, pintle_axis, power_mechanism, fasteners). Each
region has:

* `center_uv` — visual centroid in normalised image coords.
* `bbox_uv` — tight rectangle around the visible silhouette.
* `depth_mm` — centre depth on the projection's depth axis.

`apply_layout_lock()` overrides every group_anchor with its
locked region centre and clamps every component_anchor to the
region bbox. Components whose original UV is far outside the
bbox snap to the region centre with a `note: "snapped to region
centre"`.

Effect on US4807331A:
* before: every group_anchor X in `[-2, +57]` mm (61 mm spread)
* after: door X = -69, frame X = +71 (140 mm spread); upper Z =
  +90, lower Z = -24 (114 mm spread).

## V12-C — Demo-quality scaffold

`claim2cad/demo_scaffold.py` constructs hinge geometry directly
with build123d primitives, instead of deriving each component
from per-component shape inference (which produced bars).

| Mesh | Built from | Purpose |
| --- | --- | --- |
| `_curved_door_panel` | 5-vertex polygon extruded along Y | Door with the angled bottom corner |
| `_frame_panel` | Box + L-bend lip | Vehicle body frame |
| `_pintle_pin` | Cylinder, length spans upper-Z to lower-Z + 60 mm | Vertical hinge axis |
| `_hinge_bracket` | Leaf + two coaxial knuckles | C-bracket on the door |
| `_hinge_knuckle` | Block with through-hole | Knuckle on the frame |
| `_spring_link` | U-shaped link | Power-mechanism arm |
| `_spring_coil` | Cylinder annulus | Visual representation of the spring |
| `_mounting_wall` | Plate | Behind the lower hinge |
| `_fastener` | Bolt head + shaft | Fastener × 4 |
| `_feature_marker` | Tiny sphere | Holes / abstract IR nodes |

Claim component_ids map onto these via
`US4807331A_MESH_SPECS`:
* `primary` — owns a real demo mesh.
* `alias` — gets a tiny marker placed JUST OUTSIDE the parent's
  +X / +Z bbox face. This odd offset is the workaround for a
  build123d STEP-export bug that drops one of two children when
  their bboxes coincide. (Discovered 2026-04-29.)
* `feature` — same workaround, with optional pose_offset_mm.

Always-emitted meshes: door_panel, fixed_frame, pintle_pin, both
brackets, both knuckles, spring_link, spring_coil, mounting_wall,
4 × fasteners. So the demo render shows a complete hinge even
when the claim_map doesn't reference every mesh.

## V12-D — Readable rendering

`claim2cad/readable_render.py` adds per-mesh styling to the
matplotlib renderer. The key trick is **layered alpha**:

* Layer 4 (paint last, on top): `door_panel`, α = 0.45, blue.
* Layer 3: `fixed_frame`, α = 0.55, tan.
* Layer 2: hinge brackets, knuckles, pintle, spring (opaque).
* Layer 1: marker spheres (α = 0.5, no edges).

Polygons are sorted by `style.layer` ascending; opaque hinge
geometry paints first, then the semi-transparent panels overlay,
so the hinge mechanism is visible **through** the door without
z-fighting.

`render_exploded()` translates the panels along ±Y by 80 mm at
render time (not in the source geometry) so the hinge is fully
visible in the exploded view.

## V12-E — Productised viewer

* `_preferred_glb()` in `manifest.py` picks `model_v1.2.glb` >
  v1.1 > v1.0 when staging the canonical `model.glb` for the
  viewer.
* Examples that have v1.2 are tagged `demo_quality`.
* `App.tsx` defaults to the first `demo_quality`-tagged example
  (instead of the alphabetically-first synthetic).
* New `viewerMode` state: `demo` | `debug`. Persisted in the URL
  (`?mode=debug`). The Demo / Debug button is yellow / orange.

## V12-F — Hotspot confidence tiers

Each hotspot now carries `confidence_tier` ∈ `high | medium |
low`, computed by `_tier_for(source, confidence, kind)`:

| Tier | Source / condition |
| --- | --- |
| high | `leader_endpoint` && conf ≥ 0.75, OR `manual_override` |
| medium | `leader_endpoint` && conf < 0.75, OR `projection_anchor`, OR `median_label`, OR `crop_center` (conf ≥ 0.30) |
| low | `label_center`, OR any source with conf < 0.30 |

`figure_hotspot_overrides.json` lets the developer hand-tune
specific hotspots — center_px, bbox_px, confidence_tier — for a
named match (e.g. `{component_id: hinge_axis, hotspot_kind: part}`).

The viewer hides `low` tier in demo mode and applies tier-specific
CSS in debug mode (dashed border + reduced opacity for low).

## V12-G — Human-aligned eval

`claim2cad/eval_v12.py` adds five visual axes that look at the
rendered image / CAD geometry, not at JSON labels:

| Axis | What it measures |
| --- | --- |
| `figure_resemblance` | silhouette IoU between figure_1.png and the figure-aligned render |
| `panel_dominance` | fraction of the rendered foreground covered by panel meshes (door + frame) |
| `hinge_axis_visibility` | pintle_pin's CAD aspect ratio (long-axis / short-axis) |
| `floating_components` | count of large CAD children whose bbox doesn't intersect any other large child |
| `demo_readability` | composite, with HARD FAIL if 2 of 3 central-pile signals trigger |

Composite weight: 70 % visual + 30 % v11_carryover. Refusing
credit for a central pile is intentional — V11 metrics could
score 0.77 while the render still looked piled.

## V12-I — Perspective mismatch audit

After V12-H shipped, manual inspection showed the demo still
read as a flat schematic vs the patent figure's oblique
opened-door drawing. The audit
(`PERSPECTIVE_MISMATCH_AUDIT.md`) called out:

* The figure is axonometric / oblique, not pure ortho front.
  Camera estimate elev ≈ 18-25°, azim ≈ -55°.
* The door is OPEN at ~35-45° relative to the frame; both
  inside faces are visible.
* The figure shows two distinct plates per hinge (door-side
  leaf + frame-side bracket), not a single C-bracket.

## V12-J — Oblique opened-door scaffold

`claim2cad/oblique_demo_scaffold.py` builds geometry in two passes:

  1. Build every mesh in its CLOSED position (all panels parallel).
  2. Apply parent-class transforms:
       door_side    rotate +door_angle_deg about the vertical
                    pintle axis (default 35°).
       frame_side   rotate +frame_angle_deg (default 0°).
       shared_axis  identity (pintle stays on the axis).
       feature      identity.

New plate primitives:
  `_door_side_leaf`  flange + knuckle-mounting tab; bolts to
                      the door's inside face.
  `_frame_side_bracket`  back plate + L-bend reaching the
                          pintle; bolts to the frame.

## V12-K — Component-class attachment

The classification table:
  DOOR_SIDE_MESHES = {door_panel, upper/lower_door_leaf, ...}
  FRAME_SIDE_MESHES = {fixed_frame, upper/lower_frame_bracket,
                       spring_link, spring_coil, mounting_wall,
                       fasteners}
  SHARED_AXIS_MESHES = {pintle_pin, upper/lower_hinge_knuckle}

Plate alias remap so claim ids fall through to the correct side:
  leaf_flange*           → upper_door_leaf
  main_member*           → upper_frame_bracket
  upper_extension etc.   → upper_frame_bracket
  lower_extension        → lower_frame_bracket
  hinge_body_half_*      → upper_frame_bracket
  body_half_sub_*        → lower_frame_bracket

## V12-L — Patent figure camera preset

`camera_v12.json` records the grid-search best:
  matplotlib elev=22°, azim=-60°
  three.js direction = [0.80, 0.37, 0.46] (y-up)

Viewer (`Scene.tsx` + `App.tsx`):
  * New CameraPreset value `patent_figure`.
  * For demo_quality-tagged examples with camera_v12.json
    present, default cameraPreset = "patent_figure".
  * Added "patent fig." button at the front of the preset bar.

## V12-M — Readable oblique detailing

US4807331A_DEMO_STYLES updated:
  door_panel              cooler blue α=0.42  layer 4 (back)
  fixed_frame             warmer tan  α=0.55  layer 3
  *door_leaf*             cool steel  α=1.0   layer 2
  *frame_bracket*         warm steel  α=1.0   layer 2
  pintle_pin              bronze      α=1.0   layer 2

Renders generated:
  hero_oblique.png            README hero
  hero_oblique_comparison.png patent figure ↔ hero
  oblique_readable_iso.png    iso variant

The hero image is suitable for portfolio use: a translucent
blue door panel swung open on the left, translucent tan body
frame on the right, bronze pintle pin between them, steel
hinge plates bridging the two — the same composition as
figure_1.png within ~10° of the apparent opening angle.

## What's still patent-specific

`figure_layout_lock.json`, `demo_scaffold.py`'s
`US4807331A_MESH_SPECS`, the `US4807331A_DEMO_STYLES` table in
`readable_render.py`, and `figure_hotspot_overrides.json` are
all hand-built for US4807331A. The brief explicitly allows
this — the goal of v1.2 was to deliver a **convincing
flagship demo**, not a generic auto-builder.

A v1.3+ generic builder would need to:
1. Auto-detect group regions from the figure (would require
   panel-segmentation, e.g. SAM-style).
2. Map IR shape_family + claim phrasing to a procedural geometry
   library larger than the current 9 builders.
3. Tune transparency and colour per detected group automatically.

## Files that v1.2 added

```
claim2cad/
├── figure_layout_lock.py       # V12-B
├── demo_scaffold.py            # V12-C
├── readable_render.py          # V12-D + V12-M
├── oblique_demo_scaffold.py    # V12-J / K
└── eval_v12.py                 # V12-G + V12-O

examples/real_patents/US4807331A_spring_loaded_hinge/
├── VISUAL_TRUTH_AUDIT.md            # V12-A
├── PERSPECTIVE_MISMATCH_AUDIT.md    # V12-I
├── figure_layout_lock.json          # V12-B
├── figure_projection_locked.json    # V12-B output
├── model_v1.2.{step,glb}            # V12-C (flat, debug)
├── model_v1.2_oblique.{step,glb}    # V12-J / K (demo default)
├── figure_hotspot_overrides.json    # V12-F
├── camera_v12.json                  # V12-L
└── renders_v1.2/
    ├── figure_projection_lock_debug.png
    ├── solid_{figure_aligned, iso, top, comparison}.png
    ├── readable_{figure_aligned, iso, exploded, debug_labels, comparison}.png
    ├── oblique_{iso, figure_match, comparison}.png       # V12-J
    ├── patent_figure_{camera, comparison}.png            # V12-L
    ├── hero_oblique.png  hero_oblique_comparison.png     # V12-M
    ├── oblique_readable_iso.png                           # V12-M
    ├── figure_hotspot_debug.png
    └── hotspot_quality_debug.png

tests/
└── test_figure_layout_lock.py  # 5 regressions (V12-B)

docs/
├── DEMO_WALKTHROUGH.md
└── V12_VISUAL_RECONSTRUCTION.md (this file)

examples/reports/
└── US4807331A_spring_loaded_hinge_v12_eval.{md,json}
```
