# Figure projection diagnosis — US4807331A_spring_loaded_hinge

## What view is `figure_1.png`?

* `figure_view.json` says `view_kind = isometric`, `main_axis = Z`,
  `states_shown = ["upper hinge", "lower hinge"]`.
* The figure visibly shows two hinge instances mounted on the same
  vertical door panel, with the body / frame on the right and the
  door member on the left. It is best read as a **perspective view
  whose dominant projection plane is X–Z**: figure-horizontal axis
  corresponds to the world X axis (door on the left, frame on the
  right), figure-vertical axis corresponds to the world Z axis
  (upper hinge at top, lower hinge at bottom). Out-of-plane Y is
  the mounting depth (door thickness, frame thickness).

## Which CAD canonical view should match?

* `front` (camera looks along +Y, sees X–Z plane) is the primary
  match. After `v11-22` the projection-fit selector picked `right`,
  which is geometrically a 90° error.
* The CAD's `iso` view should ALSO read as the figure when the
  scene is composed in X–Z and the camera is placed at +Y, +X, +Z
  octant.

## Why does the current CAD view fail to match?

1. **No figure-coordinate constraint.** The
   `LiftOffDoorHingeScaffold` (v11-20) places groups at
   *canonical* origins (`door_panel = (-120, 0, 0)`,
   `fixed_frame = (60, 0, 0)`, `pintle_axis = (0, 0, 0)`,
   `upper_hinge = (0, 0, +90)`, `lower_hinge = (0, 0, -90)`), but
   these positions don't reference the figure's actual layout.
   The figure-horizontal door-to-frame axis happens to align (door
   left of frame), but everything else is fixed by template, not by
   the figure.

2. **Component poses ignore figure anchors.** `figure_map.json`
   provides per-callout `approximate_position` in normalised image
   coordinates for all 25 IR components. The current solver doesn't
   read this file — it places each component at its *group origin
   plus a tiny within-group offset*. Hence many components share
   the same X (= group-origin X), explaining the collage.

3. **Projection-fit scoring runs after the fact.** `projection_compare`
   renders the canonical CAD views and picks the one whose
   silhouette aspect ratio best matches the figure's. That is a
   post-hoc rank, not a constraint applied during layout.

4. **Crop-local interpretation.** `figure_to_sketch` (v11-12) and
   `shape_inference` (v11-14) interpret each crop in *local*
   coordinates. The crop tells us the part's shape, but the
   downstream pipeline drops the figure-global (u, v) and falls
   back to scaffold defaults.

## Where are component positions actually coming from?

| Component class | Position source | Reflects figure? |
|---|---|---|
| Pin / shaft | scaffold `pintle_axis.origin_mm = (0, 0, 0)` | partial — y, z right; x not read from figure |
| Plates / flanges / brackets | scaffold group origin + heuristic offset by id substring | NO — same X for everything in `upper_hinge` |
| Holes (markers) | snap to pin axis via constraint walk | partial — only XY snapped, not figure-driven |
| Vehicle body / frame | scaffold `fixed_frame.origin_mm = (60, 0, 0)` | NO — fixed by template |
| Door panel components | scaffold `door_panel.origin_mm = (-120, 0, 0)` | NO — fixed by template |

## Anchor mismatch (figure vs CAD)

Excerpts (figure (u, v) ∈ [0, 1] vs CAD (x, y, z) in mm):

| component | figure (u, v) | CAD (x, y, z) |
|---|---|---|
| `pintle_pin` | (0.35, 0.22) | ( 0,  0,    3) |
| `main_member` | (0.66, 0.55) | (18,  0,   90) |
| `lower_extension` | (0.73, 0.40) | ( 0,  0, -106) |
| `vehicle_body` | (0.72, 0.22) | (60,  0,    0) |
| `door_half_member` | (0.80, 0.22) | (-91, 0,    0) |
| `upper_extension` | (0.55, 0.61) | ( 0,  0,  102) |

The figure spreads components from `u = 0.35` to `u = 0.80` (45 % of
image width) and `v = 0.22` to `v = 0.62` (40 % of image height).
The CAD currently has only **6 distinct X values** (-132, -120, -91,
0, 18, 60, 88) and most components share `x = 0`. The figure is
genuinely 2-D laid out; the CAD is laid out in stripes.

## Why the output is a central pile

The user's complaint is the *visual* density at the centre of any
canonical render. Three causes, in priority order:

1. **All hinge components collapse to `x ≈ 0` and `y = 0`** because
   `upper_hinge.origin_mm = (0, 0, +90)` and the within-group
   offsets are tiny (≤ 30 mm). The figure clearly puts these
   components at varying X positions.

2. **The "fixed_frame" and "door_panel" panels are far from the
   hinge components in CAD** (X = −120 vs +60), but are
   *projection-correct* in figure space (door panel at
   `u ≈ 0.45..0.50`, frame at `u ≈ 0.62..0.80`). The CAD
   exaggerates panel separation while squashing component
   separation — the opposite of what the figure shows.

3. **Camera framing centres on the dense hinge cluster.** Because
   the renderer uses bbox-fit, the panels (which are far away) get
   small frame area while the cluster fills the centre.

## Major structures: are they where the figure shows them?

| Structure | Figure position | CAD position | Match |
|---|---|---|---|
| Door panel | `u ≈ 0.45` (left band) | `x = -120` | partial (left, but constant X) |
| Fixed frame | `u ≈ 0.65` (right band) | `x = +60` | partial |
| Upper hinge cluster | `(u ≈ 0.55, v ≈ 0.60)` | `(0, 0, +90)` | NO — should be at non-zero X tied to figure u |
| Lower hinge cluster | `(u ≈ 0.55, v ≈ 0.40)` | `(0, 0, -90)` | NO — same X issue |
| Hinge axis | `(u ≈ 0.49, v ≈ 0.51)` (vertical line) | `(0, 0, 0)` (vertical Z axis) | partial — vertical OK, X drifted |

## What the central pile is caused by

Not group transform; not camera framing alone.

The root cause is **missing projection constraint during layout**.
The pipeline never reads the per-callout figure anchors and never
maps them into CAD-space anchors, so the assembly_solver places
every component at its group origin + a small jitter, regardless of
how the figure spreads them. v11-19 / v11-20 / v11-21 / v11-22
helped by adding scene groups and Z-separation, but only for the
group as a whole — components within a group stay piled up.

## Plan implemented in v11-23 through v11-27

1. `claim2cad/figure_projection.py` defines a `FigureProjection`
   model with view_type, projection_plane, scale, origin, and per-
   group/per-component figure anchors.
2. `claim2cad/projection_layout_solver.py` reads `figure_map.json`'s
   per-callout positions, classifies them into scene groups, and
   converts (u, v) → CAD (x, z) (or whichever plane the view dictates).
3. The scaffold's group origins are *re-anchored* from the median
   figure position of their members; component poses sit at their
   own figure anchor (mapped to CAD), not the group origin.
4. `render_step_to_solid` adds a **figure-aligned camera** that
   matches the figure's projection plane and frames the full
   anchor bbox, not the dense hinge cluster.
5. New eval metrics: projection_anchor_error,
   group_projected_separation, central_visual_density,
   non_collage_score.
6. Viewer default for US4807331A switches to the figure-aligned
   preset.

The honest framing: the patent-family scaffold in v11-20 is
*template-based* (canonical positions). v11-23+ replaces those
canonical positions with **figure-grounded anchors** so the
projection of the CAD literally tracks the figure.
