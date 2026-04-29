# V1.3 — Semantic mismatch audit

V1.3 stopped the pipeline from crashing and got every example out
of the central origin pile. Manual inspection of the rendered
viewer afterwards exposed three examples whose **scaffold choice
is semantically wrong**: the geometry the user sees does not
match the topology of the patent figure or the claim text.

This document records — per example — the expected topology,
the current classifier output, what is wrong, the recommended
fix, and whether to reclassify now (V13-K/L) or mark it
explicitly as a fallback so the viewer warns the user.

## Summary

| Example | Current topology | Current scaffold | Verdict | Action in V1.3 |
|---|---|---|---|---|
| `US5180955A_positioning_apparatus_for_arm` | `rotary_shaft` | `rotary_shaft` | **WRONG** — figure shows a positioning apparatus with arms, parallelogram, rails, magnets; **not a rotary shaft** | reclassify → `positioning_apparatus` (new), new `positioning_apparatus` scaffold |
| `US4470181A_self_closing_hinge` | `door_hinge` | `door_hinge` | **MISLEADING** — figure shows a self-closing hinge **mechanism** (base rail, vertical post, hinge body/cam, lever, cylinder/spring), not a generic door hinge | reclassify → `self_closing_hinge_mechanism` (new), new `self_closing_hinge_mechanism` scaffold |
| `US3705522A_planetary_gear_with_idler` | `planetary_gear` | `rotary_shaft` | **PARTIAL** — topology label is correct, but `rotary_shaft` scaffold lays gears coaxially instead of arranging planets around the sun. Patent has multi-view (sectional + plan) figures that the current pipeline does not honor | reclassify → keep `planetary_gear`, route to new `planetary_gear` scaffold; mark example as `multi_view: ["sectional", "plan"]` |

---

## 1. US5180955A_positioning_apparatus_for_arm

### Expected topology
A four-arm parallelogram positioning apparatus driven by
electromagnetic coils acting on permanent magnets. The figure
shows:

* a base structure (`12`, `14`) with rails / guides (`16`, `60`),
* a parallelogram structure (the framework formed by the four
  arms `40`, `30`, `52`, `56` joined by sections),
* arm-end blocks / housings (`28`, `46`, `50`, `56`),
* a center shaft (`20`) about which the parallelogram pivots,
* electromagnetic coils + magnets at the rear of the unit.

There is **no shaft / gear assembly**. The visible "shaft" in the
claim is the central pivot of a planar parallelogram linkage,
not a rotating power-transmission shaft.

### Current classifier output
```
topology   = rotary_shaft
scaffold   = rotary_shaft
view_type  = sectional
confidence = 0.8
evidence   = ["topology:rotary_shaft:keyword:'shaft'",
              "view:sectional:keyword"]
```

### Why this is wrong
The classifier's keyword table tries `rotary_shaft` only after
several specialist topologies (door_hinge, planetary_gear,
robotic_arm, …). But the existing rules don't recognize
"positioning apparatus", "positioning linkage", or
"parallelogram" — so the first-match-wins fallthrough fires on
`shaft` (matching `center_shaft`). The high reported confidence
(0.8) is **misleading** because two keyword hits ≠ correct
classification.

The downstream `RotaryShaftScaffold` then builds a coaxial stack
of cylinders and rings — geometry that bears no resemblance to
the patent figure.

### Recommended fix
Add a finer topology label `positioning_apparatus` (V13-K) with
keywords:
```
positioning apparatus, positioning linkage, parallelogram structure,
parallelogram linkage, four-arm linkage, parallel-arm positioning
```
Place it BEFORE the generic `rotary_shaft` rule so that it wins
the first-match.

Add a `positioning_apparatus` scaffold (V13-L) that builds:
* a flat base block (`base_structure`),
* two upright support blocks (rails / guides),
* a horizontal parallelogram frame with four arm members
  positioned on a roughly square footprint,
* a central pivot shaft running vertically through the
  parallelogram center,
* an end-effector block at one corner,
* small coil + magnet markers at the rear of the base.

### Minimum acceptable improvement
* The four arms must lie in a rectangular layout, not stacked
  coaxially.
* `base_structure` must be visibly below all other components.
* `center_shaft` must be a vertical pin at the parallelogram
  center, not a long horizontal cylinder.
* `end_effector` must be at a non-coincident location.

### Decision
**Reclassify now** in V13-K and route to new scaffold in V13-L.

---

## 2. US4470181A_self_closing_hinge

### Expected topology
The patent figure (figure_1) shows a self-closing hinge
mechanism: a **base rail** (`10`), a **vertical post / column**
(`18`, `2`) rising from the base, a **hinge body / cam**
assembly seated on the post (`14`, `2A`, `12`), a **lever /
closing arm** (`14G`) extending from the hinge body, a
**cylinder + rod / spring** running vertically inside the post
(`6`, `8`, `4`), and an **upper block / stop** (`16`, `2D`)
above. Auxiliary mounting blocks (`8B`, `10E`, `18D`, `18E`,
`18F`) anchor the assembly.

Note: the corpus claim_map for this example talks about
electrical-connector inserting machinery, NOT the hinge in the
figure. The corpus appears to have mislabeled a wire-insertion
patent's claim against a self-closing-hinge figure (or vice
versa). For V1.3 we honor the EXAMPLE NAME (`self_closing_hinge`)
and the FIGURE — that is what the user will see in the viewer.
The mismatch between claim_map and figure is recorded as a
project caveat in `notes`.

### Current classifier output
```
topology   = door_hinge
scaffold   = door_hinge
view_type  = oblique
confidence = 0.55
evidence   = ["topology:door_hinge:keyword:'self closing hinge'",
              "view:oblique:default_for_mechanical_patent"]
```

### Why this is misleading
The keyword `self closing hinge` correctly identifies the family,
but the recommended scaffold is `door_hinge` — which builds a
flat door panel + frame panel + pintle pin geometry. That layout
does not exist in the figure: there is no door, no frame panel,
no pintle leaves. Users who click through the viewer will see
two flat panels connected by a vertical pin — they have no way
to tell that the actual patent is a self-closing **mechanism**
with a spring and cam, not a door swing.

### Recommended fix
Split the `door_hinge` topology into two:

* `door_hinge` — flat door panel + frame panel hinges
  (US4807331A and similar);
* `self_closing_hinge_mechanism` — base rail + post + cam-and-
  spring closing assembly (US4470181A and similar).

Add keywords for the new label:
```
self closing hinge, self-closing mechanism, spring loaded closer,
door closer, hinge closer, hydraulic hinge
```

Add a `self_closing_hinge_mechanism` scaffold (V13-L) that builds:
* a long, low base rail (`base`),
* a vertical post block rising from the base (`post`),
* a hinge body / cam mounted on top of the post (`hinge_body`),
* a lever / closing arm extending laterally from the hinge body
  (`lever`),
* a cylinder + rod inside the post for the closing mechanism
  (`cylinder`, `rod`),
* an upper stop block above the hinge body (`stop_block`),
* small mounting blocks flanking the post (`mounting_blocks`).

### Minimum acceptable improvement
* The geometry must NOT look like a flat-panel door hinge.
* A clearly vertical post must dominate the silhouette.
* A horizontal lever must extend from the top.
* The base must be a wide, flat rail underneath everything.

### Decision
**Reclassify now** in V13-K and route to new scaffold in V13-L.
Note the claim_map / figure mismatch as a project-level caveat
in the audit so users understand why some component IDs map to
visually unrelated parts.

---

## 3. US3705522A_planetary_gear_with_idler

### Expected topology
Classic planetary gear with an idler. The patent shows:

* Fig. 1 — a **sectional / cross-section** view: the ring gear,
  carrier, sun gear, planet pinions, input + output shafts seen
  in side cut.
* Fig. 2 — a **plan / end** view: the ring gear as an outer
  annulus, the sun gear at the center, **multiple planet
  pinions distributed around the sun**, an idler.

The figure is a **multi-view** patent; both views must be honored.

### Current classifier output
```
topology   = planetary_gear
scaffold   = rotary_shaft
view_type  = oblique
confidence = 0.55
evidence   = ["topology:planetary_gear:keyword:'planetary gear'",
              "view:oblique:default_for_mechanical_patent"]
```

### Why this is partial
The TOPOLOGY label is correct. The problem is two-fold:

1. The recommended scaffold `rotary_shaft` lays gears
   **coaxially** along Z. A planetary gear's defining geometry
   is that the planet pinions orbit the sun gear AROUND a shared
   axis — they are **not** stacked on the axis. The current
   render shows three planet pinions stacked along the same line
   as the sun gear, which is mechanically nonsensical.

2. `view_type = oblique` is the default. The patent has a
   sectional + plan combination; rendering the GLB from a single
   oblique camera only echoes one view at a time. The plan view
   is the one that visually proves "this is a planetary gear",
   so we should also produce a top-view render and a default
   camera that shows the planetary geometry from above.

### Recommended fix
Keep topology = `planetary_gear`. Route to a new
`planetary_gear` scaffold (V13-L) that builds:
* an outer ring/housing (`housing`) — large hollow cylinder
  centered on Z;
* a thinner ring gear inside (`first_ring_gear`,
  `second_ring_gear` — stacked along Z if both present);
* a sun gear (`sun_gear` if named, else implicit) at the origin;
* `N` planet pinions distributed at angles `2π·k/N` around the
  sun, at radius `r_orbit`;
* a carrier disc connecting the planet centers
  (`planet_carrier_means`);
* input + output shafts protruding along Z from the housing
  ends;
* mounting bosses flanking the housing.

Mark the example with `multi_view = ["sectional", "plan"]` in
the figure_classification.json so V13-N's mismatch detector and
the eval harness know to verify both a sectional render and a
plan render exist.

### Minimum acceptable improvement
* Planet pinions must lie at distinct (X, Y) positions — not all
  at (0, 0, ·).
* Planet pinions' XY centers must form a regular polygon around
  the origin.
* The plan-view render (top camera) must show the orbital
  layout.

### Decision
**Reclassify scaffold now** (planetary_gear scaffold replaces
rotary_shaft). Topology label stays. View handling
(`multi_view`) is added as a structured field — V13-K.

---

## Cross-cutting observations

1. **First-match-wins keyword tables are fragile.** The
   `rotary_shaft` rule's broad `shaft` keyword swallowed
   US5180955A. We must order specific-before-general AND ensure
   each new specific topology comes before the broader ones.

2. **High reported confidence is not the same as correct.**
   US5180955A reported 0.8 confidence with a wrong answer.
   V13-N's mismatch detector should not rely on confidence
   alone; it must compare the example's TITLE TOKENS and FIGURE
   COMPONENT KINDS against the scaffold's geometry primitives.

3. **The corpus contains at least one mislabeled example**
   (US4470181A: claim_map describes a wire-insertion machine but
   the figure_1 + example name describes a self-closing hinge).
   For V1.3 we treat the figure as ground truth and add a
   project-level note. A future pass should re-derive the
   claim_map from the correct claim text.

4. **Multi-view patents** (US3705522A) are not handled by a
   single oblique camera. The `multi_view` field opens the door
   to per-figure cameras and per-view scaffold positioning — out
   of scope for V1.3 except to record the field.

## Next steps (V13-K → V13-P)

* V13-K: classifier — add `positioning_apparatus`,
  `self_closing_hinge_mechanism` topology rules; refine
  `planetary_gear` to write `multi_view`. Regression tests for
  the three target patents.
* V13-L: scaffolds — `positioning_apparatus`,
  `self_closing_hinge_mechanism`, `planetary_gear`.
* V13-M: regenerate the three examples with new classifier +
  scaffolds; produce before/after comparison render.
* V13-N: lightweight mismatch detector; emits warnings into
  eval_v13.json and a viewer banner.
* V13-O: viewer ⚠ semantic mismatch tier; banner shows expected
  vs selected scaffold.
* V13-P: docs.
