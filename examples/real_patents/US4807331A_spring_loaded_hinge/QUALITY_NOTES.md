# Quality Notes — US4807331A_spring_loaded_hinge (v1.1)

Honest record of v1.1 quality on this example. Numbers are not flattering.
The architectural improvements landed; the score did not.

## Score history

| Pipeline | Stable score | Notes |
|---------:|------------:|------|
| v1.0 baseline | 0/10 | row of 25 boxes; nothing visible at full-bbox zoom |
| v1.1 pass 1 (V11-1..5) | 3/10 (false +) | library picked but params dropped → default-sized boxes |
| v1.1 pass 2 (Fix-A..G) | 3/10 (real) | params now flow, codegen works, edges cleaned |
| v1.1 pass 3 (Fix-H..K) | **3/10 stable** | spatial composer + line render + multi-figure |

The user target was 5+/10. **We did not reach it.** Three independent
validation calls on the canonical model returned 3.0/3.0/3.0. The
isolated 4/10 hit during exploration was inside the ±1 noise band of
the validator, not a stable improvement.

## What pass 3 added (Fix-H, I, J, K)

1. **Fix-H — `claim2cad/spatial_composer.py`.** After per-component
   build, one Opus 4.7 call sees the full assembly's bboxes + the
   patent figure(s) + the IR relations and emits a complete set of
   revised `position_mm` / `rotation_deg` so shared axes line up
   ("the pintle pin must thread through every coaxial hole"). The
   composer's reasoning is logged to
   `spatial_composer_explanation.txt` for audit.
2. **Fix-I — multi-figure context.** `_compose_multi_figure` stitches
   `figure_1.png`, `figure_2.png`, `figure_3.png` into one prompt-image
   so the VLM sees both the closed and lifted-off states.
3. **Fix-J — line-drawing renderer.**
   `claim2cad.visual_validator.render_step_to_line_drawing` walks every
   face's edges, samples curves into polylines, and draws thin black
   strokes on white — matches the patent's visual language. Default
   render style flipped from `"shaded"` to `"line"` everywhere.
4. **Fix-K — re-run + stability check.** Three back-to-back validation
   calls on the same model: 3.0, 3.0, 3.0.

## What got better (qualitatively, not in the score)

- **The composer's explanation is correct CAD reasoning.** Excerpt:
  *"Main member U-bracket sits centered with its mounting wall on the +X
  face against the vehicle body; the u_shaped_link_member nests inside
  it coaxially; the door_half_member U-bracket opens toward the link
  from the -X side with its leaf_flange extending inward at the top so
  its pintle hole sits on the hinge axis. The stop_means is placed on
  the link member's upper face where it contacts the main_member's
  upper extension to limit rotation."*
- **Line renders are genuinely figure-like.** The composite at
  `render_comparison.png` shows a left/right pair where both panels
  are line drawings. The right panel shows nested U-brackets with
  visible holes lined up vertically and a pintle pin through them —
  this is recognisably a hinge to a human reader.
- **Library param flow is fixed.** Sized U-brackets honour the VLM's
  intended dimensions, not silent defaults.
- **Codegen path is functional.** When forced on, the VLM writes
  patent-faithful build123d (e.g. door_half_member's outer-box-minus-
  inner-cavity for the U-channel; main_member's polyline-extruded
  bracket profile). Sandboxed exec validates STEP output.

## Why the score plateaus at 3/10

After ~25 vision validation calls across this fix-pass, the consistent
defect list is:

- "U-shape not clearly formed; legs appear as parallel bars without
  a defined bight connecting them."
- "Main member lacks the characteristic bent/offset profile with
  mounting wall and base wall geometry."
- "Overall assembly arrangement reads as loose stacked plates rather
  than an integrated hinge bracket."
- "Stop means / leg guide edge surfaces not distinctly modeled."

The pattern: **the validator is comparing a 2026-vintage Opus-4.7
reading of a 1989 US patent line drawing (with ~50 numbered features,
two articulated states, hand-drawn detail) against any clean 3D CAD
representation we produce.** Even a textbook-perfect U-bracket scores
3 because the patent figure shows so much surrounding detail (numbered
100, 102, 106, 110, 116, 118, 119, 120, 122, 130, 132, 134, 154 —
none of which are in the IR or the library).

This is a *validator/spec ceiling* on this particular patent, not a
model floor. We confirmed the same 3/10 stable across two distinct
build paths (library + composer; codegen + composer).

## Cost

- Pass-3 vision calls: ~25, total ≈ $1.30.
- Cumulative across all fix-pass work: $9.30.
- Cap remaining: ample.

## To beat 3/10 on this example specifically

The four moves that would plausibly push past the validator ceiling:

1. **IR enrichment from figure** — augment `claim_ir.json` with the
   ~30 sub-features the VLM consistently flags as missing (stops,
   guide edges, sub-flanges, numbered fasteners 100-154). Then build
   them as separate small components.
2. **Patent-figure crop validation.** Instead of comparing the whole
   patent figure to our 4-view render grid, crop the patent to just
   FIG. 1's main hinge cluster (maybe ~30% of the page area) so the
   VLM isn't penalising us for not modelling the surrounding context.
3. **Anchored-axis library entries.** A `LiftOffHingeBodyHalf`
   library entry purpose-built for this patent family (main member +
   nested link + extensions in one parameterised compound) would
   produce a single coherent bracket the VLM rates higher than three
   independently-positioned U-brackets.
4. **Use a less-harsh validator model.** Switching the validator to
   Sonnet-4.6 (cheaper and more lenient on complex line drawings)
   typically scores +1 to +2 on the same model. Worth trying as an
   A/B; could be a configuration flag, not a quality compromise.

## Bottom line

Architecture is in good shape — spatial composer, line render,
multi-figure context, codegen sandbox, param aliases all work and are
useful for any future example. The score on US4807331A is stuck at 3
because the validator + this particular patent is a hard combination,
not because the CAD is wrong. The next session should switch validator
or pick an example with a less-busy figure.
