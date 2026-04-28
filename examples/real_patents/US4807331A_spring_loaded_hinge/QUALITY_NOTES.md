# Quality Notes — US4807331A_spring_loaded_hinge (v1.1)

This is the first patent the v1.1 pipeline was applied to. The notes
below are the honest assessment, not a sales pitch.

## Score

| Pipeline | Overall | Silhouette | Proportion | Feature | Arrangement |
|---------:|--------:|-----------:|-----------:|--------:|------------:|
| v1.0 baseline | **0/10** | 0 | 0 | 0 | 0 |
| v1.1 (this) | **3/10** | 3 | 4 | 2 | 3 |

Scoring is from a Claude-Opus-4.7 vision call comparing renders of the
CAD model to the original patent figure (`figures/figure_1.png`). 0/10
means "unrelated"; 5/10 means "recognisable but obviously approximate";
8-10 is the design target. We did not reach 7. We documented why instead
of faking the number.

## What got better visually

- **The model now has a hinge.** v1.0 produced 25 boxes laid out in a
  line (rendered as dots when the camera framed the whole bbox); v1.1
  produces a `LeafHinge` (two leaves joined by a pin) at the centre,
  flanked by mounting plates. See `render_comparison.png`.
- **Recognisable mechanical components.** The U-shaped link member
  (`u_bracket`), the pintle pin (`pin`), and the leaves (`leaf` plates)
  are all instantiated from the v1.1 component library. The library
  parts are correctly placed for the hinge cluster, even if the broader
  arrangement is off.
- **Component IDs preserved end-to-end.** All 25 IR component IDs survive
  into both `model_v1.1.step` and `model_v1.1.glb` as labels / GLB node
  names. The viewer can still highlight components by claim id.

## What is still wrong

These are the issues the iter00 SimilarityReport flagged that we could
not fix in 2 iterations:

- **U-shape not visible.** The `u_bracket` is in the assembly but
  rotated so its open face points along an axis where the renders cannot
  see it. Needs view-aware rotation or an explicit "U opens toward
  +X" hint in the figure-to-spec prompt.
- **Pintle pin not aligned with leaf-flange holes.** The pin is placed
  near the hinge cluster but does not pass through both leaf flange
  holes the way figure_1 shows. The current generator treats each
  component's position_mm independently; it needs a constraint ("pin
  axis = hinge axis") to make this come out right.
- **Two outsized plates dominate the silhouette.** The VLM gave
  `vehicle_body` and `door_half_member` dimensions of 250-300 mm while
  the hinge itself is ~80 mm. From the iso view the hinge looks tiny
  next to two huge sheets. v1.1's prompt asks for consistent scale but
  doesn't provide a hard rescale step.
- **Abstract claim concepts have no geometry.** `hinge_axis`,
  `body_half_sub_assembly`, and a few other IR entries are conceptual,
  not parts. They get stub primitives (small boxes) that add visual
  noise without contributing to the figure's mechanical content.

## Refinement loop behaviour (be honest)

Two refinement iterations were run after the initial assembly. Both
made the score *worse*, not better:

- iter00 (initial): 3/10
- iter01 (after refining 5 components): 2/10
- iter02 (after refining 5 more components): 2/10

The loop correctly halted on "no improvement for 2 iterations" and
promoted the iter00 model to `model_v1.1.step` / `model_v1.1.glb`. This
is the right behaviour, but it means the refinement step did not earn
its cost on this example.

Why the regression: the VLM's revised `position_mm` values for one
component frequently broke alignment with neighbours that were not
flagged. A whole-assembly re-score then penalised the new arrangement
even though the targeted local issue was sometimes addressed.

Concrete improvements queued for Session 2:

1. **Per-component rendering** — crop around the component instead of
   re-rendering the whole assembly. Lets the VLM judge it in isolation.
2. **Constraint-aware revisions** — pass the VLM a list of "must not
   move" anchor points (shared pin axes, mounting walls).
3. **Multi-figure context** — figures 2 and 3 of US4807331A show the
   lifted-off state; the current single-figure prompt cannot resolve
   that geometry.
4. **Library upgrades** — the current library has a `pin` and a `leaf`
   but no "leaf hinge with offset knuckle pattern matching figure 1's
   counted knuckles". Adding more specialised entries reduces how much
   the VLM has to invent.

## Render and runtime numbers

- Initial generation (V11-3): 1 vision call, ~13 s wall time, $0.111.
- Refinement loop (2 iterations): 5 vision calls (3 validations +
  2 refinements), ~50 s wall time, $0.18.
- Total cost for this example: **$0.31**.
- Final STEP: 512 KB. Final GLB: 400 KB. Both within the bar.

## Honest answer to "is this 70% of text-to-cad video quality?"

No.

The text-to-cad demo video produces CAD that, on a casual look, can
pass for a clean engineering model — surfaces are smooth, proportions
are right, fillets are tasteful. v1.1 of Claim2CAD produces something
that a reviewer would correctly call "a topology sketch, with hinge
parts identifiable but proportions wrong and smaller features missing".

A fairer frame: this is **maybe 30-40% of text-to-cad-video quality on
this single example**. v1.0 was effectively 0%. The gap that remains
is mostly in (a) component placement precision, (b) handling of
abstract claim concepts, and (c) loop instability. Sessions 2 and 3
target those gaps directly.
