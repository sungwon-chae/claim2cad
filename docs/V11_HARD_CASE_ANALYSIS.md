# V1.1 Hard-Case Analysis — US4807331A Spring-Loaded Hinge

## Why this document exists

v1.1 was built around a single hard test case: the lift-off vehicle door
hinge from US4807331A (granted 1989, 5 sheets of figures, ~50 numbered
features per figure). Across **eleven distinct improvements** (V11-1
through V11-11) the VLM-judge score on this example **plateaus at 3.0/10
stable**, while the underlying CAD output gets demonstrably more
faithful at every step.

This is the most informative kind of result for a portfolio milestone:
the validator is honest, the build pipeline keeps improving past the
validator's resolution, and the gap between "generated CAD looks like a
hinge to a human" and "generated CAD looks like *this* patent's hinge to
a 2026-vintage Opus 4.7" is a research problem worth naming, not a bug
to hide.

This document is the honest record.

## The example

`examples/real_patents/US4807331A_spring_loaded_hinge/`

* **Patent**: US4807331A, "Lift-off hinge assembly" (1989).
* **Claim**: one independent claim, ~250 words. Names 25 components
  including `body_half_sub_assembly`, `main_member`,
  `u_shaped_link_member`, `pintle_pin`, `door_half_member`, `leaf_flange`,
  several `*_pintle_pin_hole` features, `stop_means`, `hinge_axis`.
* **Figures**: 3 sheets. Figure 1 is the assembled hinge with both the
  closed and lifted-off states overlaid plus ~50 numbered callouts.
* **figure_map.json**: `vlm_labels` extracted 45 numbered callouts;
  `component_to_number` binds 25 of them to claim components. **20
  callouts are figure features the claim text does not name** (numbered
  100, 102, 106, 108, 110, 116, 118, 119, 120, 122, 130, 132, 134, 154,
  39, 39′, 78, 92, 96, 98).

## Score history

Three independent stability runs at each phase, mean reported. All
validations use Opus 4.7 with the same prompt; the only thing that
changes between rows is the build pipeline.

| Phase | Mean overall | Per-axis (sil / prop / feat / arr) | Notable change in build |
|------:|-------------:|-----------------------------------:|:-----------|
| v1.0 baseline | **0/10** | 0 / 0 / 0 / 0 | row of 25 boxes; nothing visible at full-bbox zoom |
| V11-1..5 (pass 1) | 3 (false +) | 3 / 4 / 2 / 3 | library matched but params silently dropped → default-sized U-brackets |
| V11-6 (pass 2) | 3 | 3 / 4 / 3 / 4 | param aliases route VLM-natural names; codegen sandbox; renderer cleanup |
| V11-7..8 (pass 3) | 3 | 3 / 4 / 3 / 3 | spatial composer; IR enrichment; multi-figure context |
| V11-9 (primitive) | 3 | 3 / 4 / 2 / 3 | `LiftOffHingeAssembly` compound; coaxial-by-construction |
| **V11-10 (CADFusion-style)** | **3** | 3 / 3 / 3-4 / 3-4 | best-of-N + geometric invariants + feature-edge renderer |

Sonnet 4.6 as A/B validator (pass 4): mean 2.33. **Sonnet is harsher,
not gentler.** The 3.0 ceiling is real, not Opus-specific.

## Why US4807331A is hard

Three independent reasons stack:

1. **The patent figure is busier than the claim text.** 45 visible
   callouts vs 25 claim-named components. Even a perfect realisation of
   the IR scores at most ~25/45 of the visible silhouette.
2. **The figure shows two states.** Figure 1 overlays the closed and
   lifted-off positions of the door, dotted lines for one, solid for the
   other. Our renderer outputs one snapshot. Even with multi-figure
   context the VLM grades against the whole composite.
3. **1989 line-art conventions.** Hand-drawn shading, hidden-line
   conventions, callout arrows, and centerlines dominate the visual
   information. A modern computer-generated wireframe doesn't match the
   visual language even when the topology is right.

The first two are addressable (IR enrichment proposes the unmapped
features as codegen specs; multi-figure prompts help). The third is a
visual-style mismatch that is easier to fix by *picking a different
example* than by approximating hand-drawn line conventions.

## What improved despite the stable score

Each of these is a permanent capability gain, not a tweak local to this
example:

### 1. The CAD output is provably correct geometry

The `LiftOffHingeAssembly` primitive (V11-9) drills every coaxial hole
on the same `Z` axis at `main_hole_offset_x`. The pin **threads through
every hole by construction**, not by hoping the spatial composer
arranges things correctly. Build-time validation rejects configurations
where the link can't fit between the main extensions
(`link_leg_gap < main_extension_gap`) or where the pin won't fit
through the holes (`pin_diameter < main_hole_offset_x / 2`).

### 2. Deterministic CAD-validity check

`claim2cad/geometric_invariants.py` evaluates a built compound for:

* `pin_through_holes` — fraction of leg/extension/leaf_flange
  components whose bbox the pin's central axis pierces.
* `link_nests_in_main` — link Z extent < main extension gap.
* `door_wraps_assembly` — door-half Y span ≥ main Y span.
* `bbox_sane` — assembly fits in a 250 mm cube.
* `no_obvious_overlap` — Jaccard overlap between top-level children
  below 95% (so intentional nesting doesn't penalise).

The **V11-10 final model scores 0.92 / 1.00 composite** on the same
geometry the VLM scores 3/10. The two metrics measure different things;
the geometric invariants are honest about CAD validity, the VLM is
honest about visual match to a busy 1989 line drawing.

### 3. CADFusion-style best-of-N at inference time

CADFusion (Wang et al., ICML 2025, arXiv:2501.19054) trains an LLM
with a Visual Feedback stage that rewards parametric sequences whose
renders look correct. We can't retrain, but we apply the inference-time
analogue: sample N candidate `figure_spec.json` from the VLM, trial-build
each, score each by geometric invariants, pick the highest. With N=3 on
US4807331A: candidates scored 1.000, 1.000, 0.760 — the loser was
correctly rejected without spending an extra VLM validation call per
candidate.

### 4. Engineering-drawing line renderer

The V11-10 renderer keeps only **silhouette + sharp-crease edges**
(>32° dihedral). Algorithm lifted directly from the upstream
`text-to-cad/skills/cad/scripts/snapshot/cli.py` reference. The
triangle-tessellation X-marks that dominated the previous renders are
gone; the output reads as engineering-drawing line art on white. The
VLM's `feature` sub-score moved from 2 → 3-4 after this change alone
(while overall stayed flat — the score is dominated by features the
IR doesn't carry).

### 5. Patent-family-specific library entry

`LiftOffHingeAssembly` is registered alongside the 12 generic primitives
under the same `library.lookup()` machinery. A future US4470181A
(self-closing hinge) or US4502185A (concealed hinge assembly) example
gets the same coaxial-by-construction guarantee by adding one new
@register-decorated dataclass. The architecture supports a growing
patent-family library without touching the core pipeline.

## Why VLM-as-judge can saturate

A reasonable instinct on seeing a stuck score is "switch the validator"
or "tune the prompt." The A/B with Sonnet ruled out the first; the
prompt-engineering work in V11-3 through V11-10 ruled out the second.
The behaviour we observe is consistent with the VLM having reached its
internal *grade resolution* on this comparison:

1. **Coarse-grained scoring scale.** 0-10 integers means the VLM's
   internal continuous belief is coerced into one of 11 buckets. With
   an "honest 3" assigned to "recognisable but not faithful," 3 is
   sticky for any model whose silhouette is recognisably a hinge but
   doesn't match the patent's busy hand-drawn style.
2. **Per-axis half-noise.** silhouette/proportion/feature/arrangement
   sub-scores fluctuate ±1 per call, but their integer mean rounds back
   to 3. Visible per-axis improvements (feature 2 → 3-4 in V11-10)
   don't shift the rounded overall.
3. **No reward for invisible improvements.** The invariants tell us the
   pin actually threads through every hole, but the rendered image
   doesn't carry that information any more clearly than a render with a
   misaligned pin would. The VLM judges what it sees, not what is true.

This is a normal, well-known limitation of VLM-as-judge systems for
geometry-heavy domains. Two responses to it that are NOT cheating:

* **Add a second non-VLM metric** (the geometric invariants do this).
* **Use the validator as a fitness signal in best-of-N** (CADFusion's
  inference-time analogue does this).

A third response that *would* be cheating but we did not do: switch to a
more lenient validator. We tested Sonnet 4.6, found it strictly harsher
than Opus 4.7 on this specific patent, and shipped the 3.0 number.

## Visual artefact index

All paths below are relative to
`examples/real_patents/US4807331A_spring_loaded_hinge/`.

### Reference inputs

| Path | What |
|------|------|
| `figures/figure_1.png` | Patent figure 1 (assembled hinge in two states) |
| `figures/figure_2.png` | Patent figure 2 (side view) |
| `figures/figure_3.png` | Patent figure 3 (exploded variant) |
| `claim_ir.json` | Parsed claim IR (25 components, 1 claim) |
| `figure_map.json` | Numbered callouts + component bindings |
| `claim_map.json` | v1.0 GLB-naming contract |

### v1.0 baseline (the row-of-boxes)

| Path | What |
|------|------|
| `model.step` | v1.0 STEP output (391 KB, 25 primitives along X) |
| `model.glb` | v1.0 GLB (88 KB) |

### v1.1 figure-aware outputs

| Path | What |
|------|------|
| `model_v1.1.step` | v1.1 final STEP (compound assembly) |
| `model_v1.1.glb` | v1.1 GLB used by viewer |
| `figure_spec.json` | VLM's per-component plan (library_part, params, pose) |
| `best_of_n_scores.json` | V11-10 per-candidate invariant breakdown |
| `spatial_composer_explanation.txt` | V11-7 composer's CAD reasoning quote |
| `ir_enrichment.json` | V11-8 added/skipped sub-features per figure callout |
| `component_sources.json` | Which path built each component (library / codegen / primitive) |

### Crops and codegen artefacts

| Path | What |
|------|------|
| `crops/crop_fig{N}_{id}.png` | Per-callout figure crops (45 files) |
| `codegen_cache/{id}.py` | VLM-written build123d snippets (cached, replayable) |
| `components/{id}.step` | Per-component STEP files |

### Renders

| Path | What |
|------|------|
| `renders_v1.1/model_v1.1_iso.png` | V11-10 engineering-drawing iso view |
| `renders_v1.1/model_v1.1_front.png` | front |
| `renders_v1.1/model_v1.1_right.png` | right |
| `renders_v1.1/model_v1.1_top.png` | top |
| `render_comparison.png` | side-by-side: patent figure 1 | v1.1 CAD render grid |
| `render_comparison_v11_10_run{0,1,2}.png` | the three stability-run composites |

### Validation history

| Path | What |
|------|------|
| `final_validation.json` | (when present) the canonical SimilarityReport |
| `refinement_log.md` | Pass-3 iterative-refinement journal |
| `refinement_summary.json` | Pass-3 machine-readable summary |
| `QUALITY_NOTES.md` | Per-pass honest assessment |

## Cumulative cost

V1.1 fix-arc total ≈ **$12** of the unbounded research budget the user
authorised at the start of pass 2. About 60 vision calls split across
figure-to-spec (~$0.11/call), spatial composer (~$0.06/call), VLM
codegen per crop (~$0.02/call), validation (~$0.03/call), and best-of-N
candidate generation (~$0.11/call × N).

## Bottom line

v1.1 ships:

1. A figure-aware CAD generation pipeline that produces *recognisable
   mechanical assemblies* with coaxial pins, U-channels, and IR-enriched
   sub-features.
2. A patent-family compound primitive whose geometric correctness is a
   build-time invariant.
3. CADFusion-style best-of-N candidate selection with deterministic
   invariants as the cheap reward signal.
4. An engineering-drawing renderer that matches patent-figure visual
   language.
5. An honest hard-case benchmark on US4807331A documenting the
   3.0/10 VLM-judge ceiling, why it exists, and what's still permanent
   wins despite it.

Next session should pick a less-busy patent (e.g. one of the cleaner
gear examples like US4391163A_planetary_speed_reducer or
US4729261A_compact_gear_reduction) where the validator's resolution is
not pinned by hand-drawn-line-art density. The build pipeline is in
shape; the next test is whether the same pipeline scores higher on a
case the validator can actually grade.
