# V1.4 — Figure-faithful patent reconstruction

V1.3 generalized the pipeline across 25 patents but the
geometry was largely topology-correct placeholders: cylinder
stacks, box stacks, primitive collages. V1.4 takes a
correction pass focused on **visual fidelity**:

* classify each patent figure's view type from the image,
* render every CAD model through a camera that matches that
  view,
* replace ad-hoc Cylinder + Box primitives with a richer
  parametric vocabulary,
* grade quality strictly so 'good' actually means visually
  convincing.

## Phases

### V14-A — Strict visual quality re-audit
`examples/reports/V14_VISUAL_QUALITY_AUDIT.{md,json}`. Re-grades
the 25-example corpus with stricter rules than eval_v13.
Result: 1 flagship, 23 partial, 1 fallback. The 4 V13-marked
'good' examples drop to 'partial' because their GLB names
don't expose specialized primitive kinds. This is the honest
baseline V14-D / V14-E climb from.

### V14-B — Figure view classifier
`claim2cad/figure_view_v14.py`. Pure-image-heuristic detector
on three signals (aspect ratio, line-orientation opens, dilated
connected components). Produces `figure_views_v14.json` with
view_type, primary_view, secondary_views, required_camera,
view_regions, evidence, confidence. No LLM call. 25/25
classifications:

* multi_view_sheet — 9 (e.g. US3705522A planetary)
* oblique         — 14 (most of the corpus)
* front           — 2

### V14-C — Projection-locked rendering
`claim2cad/projection_lock_v14.py` reads each example's view
classification and renders the latest STEP through the
matching camera (`top` / `front` / `right` / `iso` /
`patent_oblique`). For multi_view_sheet examples it also
renders `plan_view.png` (top camera) and `section_view.png`
(front camera). Each example gets `renders_v1.4/figure_matched.png`
plus `comparison.png` (figure | matched render) and a
`view_region_debug.png` for the detected sub-views.

### V14-D — Mechanical primitive vocabulary
`claim2cad/v14_primitives.py`. 36 reusable build123d helpers,
indexed by mechanical role:

| Family | Helpers |
|---|---|
| gears | toothed_disc, ring_gear, sun_gear, planet_gear, idler_gear |
| springs | helical_spring, compression_spring, torsion_spring |
| linkages | link_bar, clevis_joint, pivot_pin, slotted_link |
| rails | guide_rail, linear_track, carriage_block, slotted_base |
| housings | enclosure, flanged_housing, cover_plate |
| brackets | l_bracket, u_bracket, c_bracket, gusset_bracket |
| cams | eccentric_cam, cam_follower |
| bearings | ball_bearing, plain_bearing, thrust_bearing |
| fasteners | bolt, screw, washer, nut |
| panels / shafts | bent_panel, chamfered_plate, keyed_shaft, splined_shaft |

39 unit tests cover non-degenerate geometry per primitive plus
shape properties (toothed disc grows beyond plain disc,
ring_gear is hollow, helical_spring length matches param).

### V14-E — Scaffold upgrades
Four scaffolds rebuilt around v14_primitives:

* `rotary_shaft` — toothed gears, ball bearings (race + balls),
  flanged housings (with bolt-hole circle), keyed/splined
  shafts, eccentric_cam wave generator.
* `linkage` — link_bar (rounded ends + holes), pivot_pin
  (head + shaft), clevis_joint end-effector, slotted_base.
* `bracket_mount` — l/u/c/gusset brackets routed by label,
  bolted fasteners, slotted base.
* `housing_panel` — hollow enclosure (visible walls),
  cover_plate with bolt-hole pattern, flanged port.

Then `batch_generate --all-real-patents` regenerates the
corpus into `model_v1.4.{glb,step}`. 24/25 ok + 1
flagship_preserved.

### V14-F — Before/after corpus report
`examples/reports/V14_BEFORE_AFTER_ALL.{md,png}`. Six-row
visual delta (figure / v1.3 render / v1.4 view-matched render)
for representative examples plus a corpus migration table.

### V14-G — Stricter, human-aligned eval
`claim2cad/eval_v14.py`. Six scoring axes:

* view_match_score — primary view-matched render exists.
* primitive_richness_score — scaffold known to use
  v14_primitives, weighted by GLB child count.
* non_placeholder_score — not fallback_grid /
  generic_exploded.
* assembly_attachment_score — bbox-spread proxy (no floaters).
* multi_view_consistency_score — multi-view examples have
  plan AND section renders.
* topology_specificity_score — scaffold matches topology
  family.

Plus boolean flags `cylinder_stack_detected` and
`view_rotation_mismatch`.

Verdict gating is **honest, not lenient**. 'good' requires the
scaffold to be in a manually inspected whitelist
(door_hinge, self_closing_hinge_mechanism, two_plate_hinge,
positioning_apparatus, planetary_gear) AND have
primitive_richness ≥ 0.7 AND topology_specificity = 1.0 AND
assembly_attachment ≥ 0.5 AND ≥ 8 GLB children.

Result on the 25-example corpus:

| Verdict | Count |
|---|---:|
| flagship | 1 |
| good | 10 |
| partial | 13 |
| fallback | 1 |
| failed | 0 |

Mean overall_score 0.970 (per-axis scores are high; tier is
the honest gate).

### V14-H — Viewer
* `model_v1.4.glb` is now the preferred GLB for non-flagship
  examples.
* Manifest entries carry `figure_view_type`,
  `figure_required_camera`, `figure_matched_render`,
  `plan_view_render`, `section_view_render`.
* Viewer renders a `.view-info-strip` above the mismatch
  banner: `view: oblique · camera: patent_oblique ·
  [figure-matched render] [plan] [section]` with links that
  open the V14-C renders in a new tab.
* `make demo-v14` runs the full V14 pipeline end-to-end
  and opens the viewer.

## Honest assessment

### What V1.4 delivers
* Every example has a view-matched render — the camera
  finally honors what the patent figure actually shows.
* Every example uses richer primitives than V1.3 in its
  scaffold class (gears, springs, linkages, brackets,
  cover plates, fasteners).
* Quality grading is harder to game — only manually
  inspected scaffold families can earn 'good'.

### What V1.4 still does NOT deliver
* The 13 partial-tier examples (mostly robotics + harmonic /
  differential / generic rotary) still use scaffold
  templates that approximate the topology family but do not
  closely resemble any specific patent figure. They are
  honestly graded.
* The figure view classifier is heuristic. It correctly
  distinguishes oblique vs sectional vs multi_view_sheet on
  the inspected examples but a misclassified figure means a
  mismatched camera.
* Multi-view rendering produces plan + section PNGs alongside
  the primary, but the viewer doesn't yet auto-switch the
  3D camera between them — the user follows the side links.
* Per-example claim ↔ figure ↔ CAD interactivity still works
  end-to-end, but visual reconstruction beyond the flagship
  remains a research prototype, not production CAD.

## Reproduction

```bash
make demo-v14      # full pipeline + viewer
make demo-v14-stage # restage manifest + viewer (artifacts cached)
```

Reports to inspect:
* `examples/reports/V14_VISUAL_QUALITY_AUDIT.md`
* `examples/reports/V14_FIGURE_VIEWS.json`
* `examples/reports/V14_PROJECTION_STATUS.json`
* `examples/reports/V14_BEFORE_AFTER_ALL.{md,png}`
* `examples/reports/V14_QUALITY_TABLE.{md,json}`
