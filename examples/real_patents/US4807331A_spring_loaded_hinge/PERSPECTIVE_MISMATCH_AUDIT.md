# Perspective mismatch audit — V12-I

Written 2026-04-29 against `v1.2-dev` head `b9f685a`. The v1.2
demo (V12-A through V12-H) fixed the central-pile failure mode
but the resulting CAD still reads as a **flat schematic with
parallel panels**, not as the **opened-door oblique drawing**
the patent figure actually shows. This audit calls out the gap
explicitly so V12-J onwards can close it.

## 1. What is the patent figure view type?

**Oblique / axonometric, three-quarter from upper-front-right.**
Not a pure ortho front view, not a true isometric, not a 1-point
perspective. The clues:

* Vertical lines stay VERTICAL on the page (no perspective
  convergence on the Z axis). So this is axonometric, not pure
  perspective.
* Horizontal edges that go INTO the page slope toward an
  upper-right "vanishing direction" but never meet — parallel
  lines stay parallel. Classic oblique projection.
* Both inside faces of the door panel AND the frame are visible.
  In a pure front view we'd see only one panel face; in this
  drawing we see the door's left-inside face AND the frame's
  right-inside face simultaneously, which only happens if the
  two planes are not parallel.
* The drawing intentionally shows depth: the upper hinge bracket
  (callouts 14, 24, 34, 38) is drawn ABOVE and SLIGHTLY BEHIND
  the lower hinge bracket. In our front-only render the two
  hinges are at the same X.

Camera estimate: elev ≈ 15–25°, azim ≈ -55° to -45°,
near-orthographic projection (very low FOV or true ortho with
oblique direction).

## 2. Which visual cues indicate the door is opened/angled?

* The door panel's TOP-LEFT corner is drawn closer (lower-left
  on the page) than its TOP-RIGHT corner (upper-middle). The
  page-X gradient on a single horizontal door edge means the
  door is rotated about a vertical axis.
* The door's INSIDE face is visible — that's the face that
  would be hidden if the door were closed against the frame.
* Frame and door clearly do NOT share a plane: they meet only
  along the pintle axis (the thin vertical line through callouts
  58, 28, 64, 60, 68).
* The door-side leaves (#100, #108, #110, #112) sit on the
  door's inside surface — they swing OUT with the door.
* The frame-side brackets (#24, #34, #38, #54, #56) sit on the
  frame's vertical inside surface — they stay STILL.
* The two halves are connected only via the pintle pin running
  through the upper and lower knuckles.

The opening angle is roughly **45–55°**, judging by how much of
the door's inside face we see vs how much foreshortening is
visible on the door silhouette.

## 3. Which edges define the door panel plane?

The door panel's outer silhouette in the figure traces:

* Top edge — irregular wavy cut (decorative, indicates the door
  is a real fabricated panel, not a CAD primitive).
* Right edge — VERTICAL straight line at the hinge boundary;
  this is the door's HINGE EDGE. It coincides with the pintle
  pin axis line (callouts 26, 102, 132, 134) on the page.
* Bottom edge — angled diagonal cut up-and-to-the-right, like a
  truncated lower corner.
* Left edge — long vertical line that fades into the page
  border.

The door panel's PLANE in 3D is rotated around the right edge
(hinge edge). The hinge edge is the shared axis with the frame.

## 4. Which edges define the fixed frame plane?

The fixed frame draws an L-bend on the right side of the figure:

* Top edge — bends in toward the viewer, suggesting the body's
  upper roof rail.
* Right edge — vertical, far right of the figure.
* Bottom edge — folds inward at the bottom suggesting a rocker
  panel.
* Left edge — VERTICAL straight line at the hinge boundary,
  shared with the door's right edge.

The frame's plane in 3D is APPROXIMATELY parallel to the
viewer's screen but rotated slightly TOWARD the viewer (the
left-hand inside face is visible, with the upper-roof L-bend
clearly tilting into the scene).

## 5. What is the apparent hinge axis?

A single VERTICAL line running through the upper knuckle
(callouts 58, 28, 64) down through the lower knuckle (callouts
58, 28, 64 again) — same callout numbers because they refer to
the SAME design at upper and lower hinges. The axis is
vertical and offset from the door's centroid.

In our CAD this is `pintle_pin` at world X ≈ −1, Z ranging from
the lower-hinge centre (Z = −24) to the upper-hinge centre
(Z = +90). The axis position is correct; the rotation around
it is missing.

## 6. How should the door panel be rotated relative to the frame?

* **Rotation axis:** vertical (Z), located at the pintle pin's
  X / Y position.
* **Door rotation angle:** approximately +35° (open
  counter-clockwise looking down the +Z axis). This makes the
  door's inside face point toward the viewer's upper-front-left.
* **Frame rotation angle:** approximately +0° to +5° (mostly
  upright; a tiny rotation lets us see the inside face the way
  the figure does).

The door pivots ABOUT the hinge axis. The pivot is at the door's
hinge-edge mid-height, NOT at the door's centroid. After
rotation:
* the door's hinge edge stays at the pintle X.
* the door's far edge (left silhouette) moves +X toward the
  front and −Y toward the viewer.
* The door's inside face becomes visible.

## 7. Which current CAD choices make the output look flat?

Reviewing `model_v1.2.glb` and `solid_figure_aligned.png`:

1. **Door panel and fixed frame are parallel.** Both meshes are
   axis-aligned at Y = −50 / +35. They never intersect spatially.
   The figure shows them at ~35° to each other.
2. **Door pivots only by translation, not rotation.** The V12-B
   layout lock places the door at X = −69, but the door's plane
   normal still points along +Y (parallel to frame normal).
3. **Door-side hinge components are placed at hinge X, not on
   the door surface.** In our CAD the upper hinge bracket is at
   X ≈ +18, mid-air between the door and frame, not anchored
   to either. The figure shows the door-side leaf clearly mounted
   ON the door's inside face.
4. **Frame-side components don't share the frame's normal.**
   Same defect on the other side: the frame bracket sits at
   X ≈ +20, separately from the frame at X = +71.
5. **Default render camera is `elev=0, azim=-90`** — pure front
   view. Even if the geometry were correct, this camera projects
   it to a flat 2D layout. The patent drawing is oblique.
6. **No "Patent figure" camera preset.** The viewer offers
   `figure ★ · top · front · right · iso · free`. None of those
   match the drawing's specific oblique angle.
7. **No door-leaf / frame-bracket distinction in the demo
   scaffold.** `_hinge_bracket` builds a single C-bracket at
   the hinge axis. The figure clearly shows TWO separate
   plates: a door-side leaf (mounted ON the door) and a
   frame-side bracket (mounted ON the frame), connected only by
   the knuckles around the pintle.

## 8. What concrete transformations are needed?

A list, in implementation order:

1. **Define a hinge-axis local frame** at `(X_hinge, Y_hinge, 0)`
   with Z up. All door-side meshes pivot around this Z line.
2. **Rotate the door panel +35° around the hinge-axis Z** so
   its inside face is visible. After rotation the door's far
   edge moves to `(X_hinge − 90·cos35°, Y_hinge − 90·sin35°,
   z)` ≈ (X_hinge − 74, Y_hinge − 52, z).
3. **Split the hinge-bracket primitive** into two distinct
   meshes: `door_side_leaf` (stays glued to the door panel and
   inherits the +35° rotation) and `frame_side_bracket` (stays
   glued to the frame).
4. **Knuckle rings** wrap the pintle and pivot — for the demo
   they can stay at the hinge axis as small barrel solids; their
   role is to connect the leaf and bracket.
5. **Bridging components** — `u_shaped_link_member`,
   `mounting_wall`, `spring_coil` — sit between leaf and
   bracket near the lower hinge. They keep frame-side
   placement (the spring is mounted on the frame in the
   figure).
6. **Add a "Patent figure" camera preset** at
   `(elev=18, azim=-55, projection=ortho-ish)` so the default
   render shows the oblique view.
7. **Render: don't mix face_color** between door-side and
   frame-side parts at render time. The blue door (door-side)
   and tan frame (frame-side) should be visually distinct, and
   the door-side leaves should pick up the blue tint, frame-side
   brackets the tan tint. (Currently every leaf is steel-grey
   regardless of its parent.)

## Verdict

V12-A through V12-H delivered a **correct front-facing layout**.
V12-I through V12-O need to deliver an **oblique opened-door
composition** that visually resembles the patent figure. The
geometry is mostly right; what's missing is **rotation** (door
swing-out) and **inheritance** (door-side parts swinging with
the door, frame-side parts staying put).

The flat front model is still useful for debugging the layout
lock and for the figure_aligned eval metric, so we keep it as
`model_v1.2.glb` and add the oblique demo as
`model_v1.2_oblique.glb`. The viewer defaults to the oblique
when it exists.
