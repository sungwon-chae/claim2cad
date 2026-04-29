# Visual truth audit — US4807331A_spring_loaded_hinge

Written 2026-04-29 against `v1.1-dev` HEAD `b2261cc`. The audit
inspects six rendered artefacts and the underlying data, then
asks the eight questions the v1.2 brief demands. The verdict
is unsentimental: the hotspots are demo-quality, the CAD is not.

## Inspected artefacts

| Path                                            | What it shows                                                  |
| ----------------------------------------------- | -------------------------------------------------------------- |
| `renders_v1.1/solid_comparison.png`             | Patent figure ↔ figure-aligned CAD, side by side               |
| `renders_v1.1/figure_aligned_view.png`          | The "showcase" CAD render alone                                |
| `renders_v1.1/figure_hotspot_debug.png`         | Figure with leader-grounded hotspots                           |
| `renders_v1.1/leader_line_debug.png`            | Hough-detected leader lines + endpoints                        |
| `model_v1.1.glb` (in viewer)                    | Live 3D selection / claim-CAD-figure round-trip                |
| `figure_projection.json`                        | Per-component figure_uv anchors                                |

---

## 1. What still looks wrong to a human?

The patent figure is a clean engineering drawing of a **door
hinge assembly with two distinct hinges, a long vertical pintle
shaft, a curved door panel on the left, and a vertical body
panel on the right**.

The figure-aligned CAD render is a **central pile of overlapping
rectangular bars in front of a flat grey plate**. It doesn't read
as a hinge. It reads as: "boxy primitives generated from a list
of nouns, dropped near the origin, then projected onto a single
view." None of the visual cues that make the figure recognisable
as a *hinge* are present in the CAD:

* No curved or angled door panel — just a flat rectangle.
* No spatial separation between upper and lower hinges — bars
  from both clusters overlap in the same vertical band.
* No visible pintle shaft — the pin exists but is short, lies
  along an unexpected axis, and is occluded by other bars.
* No bracket-to-panel mounting visible — the `hinge_bracket`
  sub-meshes float *in front of* the panel, not *attached to* it.
* The "door panel" is **6 mm thick, 145 × 191 mm flat box**.
  Real door panels in this patent class wrap and curve — V11-12's
  outline-extrusion never fired here, so we got the bounding box.

## 2. Does the CAD actually resemble the patent figure from the selected view?

No. The selected view (`projection_plane: ['X', 'Z']` ≈ front)
captures the *intended* viewing direction. But the components'
world coordinates don't realise the figure's spatial layout.
Nearly every numeric anchor in `figure_projection.json` reads
`"world": None` — the per-component **figure_uv** position is
recorded, but the **CAD world position** is never assigned, so
the assembly solver places components by default group-stack
heuristics. The figure-projection layer is a UV-only artefact
masquerading as a 2-way mapping.

Concretely (from `assembly_diagnostics.json`):

| Component                  | World centre (X, Y, Z) mm   | Size (X, Y, Z) mm        |
| -------------------------- | --------------------------- | ------------------------ |
| `_scaffold_door_panel`     | (28.6, −30.0, 28.5)         | 145 × 6 × 191            |
| `_scaffold_fixed_frame`    | similar X range             | similar                  |
| `pintle_pin`               | (−2.0, 0.0, 36.2)           | 9.6 × 9.6 × 111.8        |
| `hinge_body_half_assembly` | (28.5, 14.0, 84.0)          | 63 × 60 × 180 (huge)     |
| `body_half_sub_assembly`   | (53.0, 44.0, 84.0)          | 63 × 80 × 120            |

Every X centre sits in `[-2, +53]` mm. Y and Z spread, but X
doesn't — so projecting onto the X-Z plane stacks everything in
roughly the same column. That is the central pile.

## 3. Are panels, hinge groups, pin axis, brackets, and mechanism recognisable?

| Feature           | Recognisable in CAD?                                               |
| ----------------- | ------------------------------------------------------------------ |
| Door panel        | Barely. A flat 6 mm grey rectangle with no contour.                |
| Fixed frame       | Same — flat rectangle behind the pile.                             |
| Upper hinge group | No. No spatial cluster; parts are interleaved with the lower hinge.|
| Lower hinge group | No.                                                                |
| Pintle pin axis   | Partially. The pin is present but only 112 mm long and runs along Z, occluded.|
| Brackets          | Present as bars; orientation mostly correct; not attached to a panel face.|
| Mechanism         | Absent visually. The IR has it; the geometry is just bars.         |

## 4. Which components are still centrally clustered?

Within `|world centre| < 30 mm` on at least two axes:

* `pintle_pin`
* `hinge_axis` (the abstract IR node)
* `main_member`, `body_half_sub_assembly`, `hinge_body_half_assembly`
* `upper_extension`, `lower_extension`
* `first_sidewall`, `second_sidewall`
* `pintle_pin_hole`, `main_member_pintle_pin_hole`,
  `leaf_flange_pintle_pin_hole`
* `power_mechanism` parts (`u_shaped_link_member`,
  `mounting_wall`, `link_member_pivot_pin`)

This is most of the assembly. The only components that escape
the central column are `_scaffold_door_panel`, `_scaffold_fixed_frame`,
and `vehicle_body`/`door_half_member` (which are themselves
flat plates).

## 5. Which components are floating or disconnected?

By "floating" I mean: bounding box doesn't intersect any panel
or larger structural part, and there's no joint constraint.

* `link_member_pivot_pin` — sits inside the central pile but its
  pin axis is not coincident with any link knuckle.
* `lubricant_passage` — abstract; rendered as a small bar with
  no host body.
* `boss_assembly` — exists as a tiny solid not on the bracket face.
* `hinge_axis` — abstract IR node rendered as a bar; should be
  invisible (it's a centreline, not a part).
* Every hole component (`*_pintle_pin_hole`) is rendered as its
  own solid; they should be Boolean subtractions on the parent,
  not separate parts.

## 6. Which hotspots are still wrong despite leader-line detection?

`figure_hotspots.json` has 32 part hotspots; 31 are leader-grounded.
The remaining 1 falls back to `projection_anchor`. Reviewing
`figure_hotspot_debug.png` against the figure (`figures/figure_1.png`):

* **Mostly correct.** The green leader-endpoint markers cluster
  into two recognisable bands — upper hinge (≈ y/H ≈ 0.18) and
  lower hinge (≈ y/H ≈ 0.55) — which matches the figure.
* **Still suspect**:
  * `hinge_axis` callout 12 lands on a label digit, not a part
    centroid (acceptable — it's a centreline, not a physical
    feature, but the viewer should treat it specially).
  * Three `vlm_labels` had no Hough match (`method: "none"` in
    `leader_lines.json`) — those callouts fall back to the label
    centre and the marker sits on the digit text rather than the
    part region. Numbers vary by run; on this build they include
    callout 12 and two of the small-bracket numbers around
    y/H ≈ 0.45.
  * Components with `instance_id ≥ 1` (the lower-hinge duplicates)
    correctly land in the lower band. But the viewer currently
    binds the click to the same `component_id` — so selecting
    the upper-hinge instance highlights the same CAD mesh as the
    lower-hinge instance. That's the v1.1-dev behaviour by
    design, but it visually conflates two physical occurrences.

## 7. Does the viewer default to the right camera and render mode?

Open `viewer/` and pick `US4807331A_spring_loaded_hinge`:

* **Default example**: it loads whichever example sorted first
  in the dropdown — not US4807331A. A first-time visitor sees
  `golden_robot_arm` instead.
* **Default render mode**: edge-shaded with thick crease lines
  — looks like a wireframe + ghost-shaded mesh. The "is this a
  hinge?" question is answered with "is this a wireframe of a
  cluster?".
* **Default camera**: the camera respects `figure_aligned` if
  the projection_report named one, but for this example the
  initial framing zooms past the door panel and fills the screen
  with the central pile.
* **Hotspot click → highlight**: works. Stable.
* **Claim span click → CAD highlight**: works. Stable.
* **Hover-sync**: works.
* **Three.js material**: flat grey for everything. No
  group-coloration to distinguish door / frame / upper / lower.

## 8. What is the shortest path to a convincing demo?

Ranked by impact-per-effort:

1. **Give every component a real world position from
   `figure_projection.json`** (V1.2-B). Today the JSON has UV
   anchors with `"world": None`. Fix the solver so figure UV
   *projects to* world XY and the assembly inherits it. This
   alone breaks the central pile.
2. **Build a patent-family-specific scaffold** (V1.2-C) that
   *constructs* `door_panel`, `fixed_frame`, `upper_hinge_cluster`,
   `lower_hinge_cluster`, `pintle_axis`, `power_mechanism` as real
   build123d solids with correct relative scale, then attaches
   each claim component as a child of its group. This produces
   a hinge that *looks* like a hinge.
3. **Replace edge-render with shaded solid + silhouette**
   (V1.2-D). The current edge-only render is the second-biggest
   "this looks bad" lever after the layout. A shaded render of
   even the existing geometry would score 60 % of the way to
   "convincing".
4. **Default the viewer to US4807331A + figure_aligned camera +
   shaded mode + Demo mode** (V1.2-E). Tiny code change, huge
   impression delta.
5. **Tier hotspots by confidence + manual-override the 3 misses**
   (V1.2-F). Cheap; eliminates the only remaining hotspot
   credibility issue.
6. **Penalise central-pile in the eval composite** (V1.2-G). The
   v1.1 metric `assembly_coherence` scored 0.59; that's already
   reflective. v1.2 needs `figure_resemblance` and
   `panel_dominance` to refuse credit when the render still
   looks like a heap.
7. **README with the new shaded render + a 4-frame demo GIF**
   (V1.2-H). Once 1–4 are real, the README is the easy part.

Items 1 and 2 alone — figure-locked layout + a scripted
patent-specific scaffold — fix the demo. Items 3 and 4 are
multipliers. Items 5–7 are polish.

## Honest verdict

V1.1's diagnostic plumbing is good. Hotspots are real, leader
lines are real, claim spans verify, GLB ↔ claim_map is intact.
But the geometry the viewer renders is not yet a hinge. A
visitor opening the demo today sees a wireframe mesh of bars
and concludes "early prototype". V1.2 has to deliver the
geometry, not more diagnostics about the geometry.
