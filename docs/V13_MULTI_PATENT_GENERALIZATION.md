# V1.3 — Multi-patent generalization

V1.2 produced a flagship demo for a single patent
(US4807331A_spring_loaded_hinge). V1.3 extends the pipeline so
every real-patent example in `examples/real_patents/` produces
at least a coherent, inspectable baseline. Polishing the other
24 examples to flagship quality is OUT OF SCOPE.

## What "coherent baseline" means

For every real-patent example:

* the viewer loads without crashing,
* claim spans are clickable when claim_map data exists,
* figure hotspots are within image bounds and not random,
* CAD components are not all stacked at origin,
* at least one canonical or figure-aligned view is readable,
* a per-example quality badge tells the user what to expect.

## Pipeline overview

```
examples/real_patents/<patent>/
  ├── claim.txt
  ├── claim_map.json                ── classifier input
  ├── figure_map.json               ── classifier input
  └── figures/figure_1.png
                                            │
              V13-C  classify topology      ▼
              ──────────────────────  figure_classification.json
                                            │
              V13-B  scaffold registry      ▼
              ──────────────────────  Scaffold subclass selected
                                            │
              V13-D  batch_generate         ▼
              ──────────────────────  model_v1.3.{step,glb}
                                       renders_v1.3/{primary,
                                                       comparison}.png
                                       batch_status.json
                                            │
              V13-F  hotspot batch          ▼
              ──────────────────────  leader_lines.json
                                       figure_hotspots.json
                                            │
              V13-G  eval_v13               ▼
              ──────────────────────  MULTI_PATENT_EVAL.{json,md}
                                       overall_quality verdict
                                            │
              V13-H  viewer staging         ▼
              ──────────────────────  viewer/public/data/
                                       quality badge in dropdown
```

## Scaffold registry (V13-B + V13-L)

`claim2cad/scaffolds/` is a package whose modules each register
one Scaffold subclass via the `@register_scaffold` decorator:

| Scaffold | Used for | Quality tier |
| --- | --- | --- |
| `door_hinge` | door hinges (generalised from V12-J) | good |
| `two_plate_hinge` | simpler concealed hinges | good |
| `self_closing_hinge_mechanism` (V13-L) | self-closing / spring-loaded closers (US4470181A) — vertical post + cam + lever, NOT a flat door panel | good |
| `rotary_shaft` | transmissions, rotors, generic shaft assemblies | partial |
| `planetary_gear` (V13-L) | planetary / epicyclic gears (US3705522A) — sun + N planets distributed on an orbit, NOT coaxial stack | good |
| `positioning_apparatus` (V13-L) | parallelogram-arm positioners (US5180955A) — four arms in a 2D rectangular footprint with central pivot | good |
| `linkage` | robotic arms, four-bar linkages | partial |
| `bracket_mount` | base + bracket + fasteners | partial |
| `housing_panel` | enclosures, covers | partial |
| `generic_exploded` | exploded views | fallback |
| `fallback_grid` | unknown topology — never central pile | fallback |

`FallbackGridScaffold` is the safety net. It pulls components
toward their figure_uv anchors when figure_map is present;
otherwise lays them out on a grid biased by component-label
shape hints. Smoke-tested on US3279624A (8 components, no
figure data): X span 163 mm, Z span 84 mm — coherent, not piled.

## Topology classifier (V13-C + V13-K)

`claim2cad/figure_topology_classifier.py` is keyword-based
and deterministic. Inputs: claim_map labels + claim.txt + the
example's id. Outputs: `figure_classification.json` with
view_type, topology, recommended_scaffold, confidence,
evidence, and (V13-K) a `multi_view` hint listing additional
canonical views to render — e.g. ``["sectional", "plan"]`` for
planetary gears.

V13-K rules cover door_hinge, self_closing_hinge_mechanism,
two_plate_hinge, planetary_gear, harmonic_gear,
differential_gear, rotary_shaft, positioning_apparatus,
robotic_arm, linkage, bracket_mount, housing_panel. **Order
matters** — specific topologies (positioning_apparatus,
self_closing_hinge_mechanism) come before broader ones
(rotary_shaft, door_hinge) so a generic 'shaft' or
'self closing hinge' substring no longer swallows the
specific case.

Run on the corpus (post-V13-K):
```
{'planetary_gear': 8, 'robotic_arm': 7, 'rotary_shaft': 3,
 'door_hinge': 2, 'self_closing_hinge_mechanism': 1,
 'positioning_apparatus': 1, 'harmonic_gear': 1,
 'housing_panel': 1, 'unknown': 1}
```

The 1 'unknown' falls through to FallbackGridScaffold by
design — better than pretending we know what it is.

## Batch generate (V13-D + V13-E)

`python -m claim2cad.batch_generate --all-real-patents` runs
the whole pipeline over every example. Per-example failures
write `batch_status.json` and continue; one bad example doesn't
abort the run.

Result on the 25-example corpus:
* `flagship_preserved`: 1 (US4807331A keeps V12-J output)
* `ok`: 24
* `failed`: 0
* `skipped`: 0

## Hotspot batch (V13-F)

OpenCV Hough leader-line detection ran across all 25 examples:

| | Count |
| --- | ---: |
| vlm_labels processed | 874 |
| Hough leader segments detected | 618 |
| Detection rate | **70.7%** |
| Part hotspots (high tier) | 151 |
| Part hotspots (medium tier) | 31 |
| Part hotspots (low tier — label fallback) | 78 |

Demo mode hides low-tier hotspots; debug mode reveals them.

## Eval (V13-G + V13-N)

`MULTI_PATENT_EVAL.md` ranks each example by 9 axes and
assigns an overall_quality verdict. V13-N adds a 10th column
(`mismatch`) flagging examples whose classifier output
disagrees with the example slug or claim labels.

On the corpus, post-V13-K/L/M:

| Verdict | Count |
| --- | ---: |
| flagship | 1 |
| good | 4 |
| partial | 18 |
| fallback | 2 |
| failed | 0 |

Mean overall_score: **0.804**.

## Semantic mismatch correction pass (V13-J → V13-P)

Manual inspection of the v1.3 viewer surfaced three examples
whose pipeline ran cleanly but whose scaffold output was
semantically wrong:

* **US5180955A_positioning_apparatus_for_arm** — the
  classifier matched 'shaft' (in `center_shaft`) before it
  could match 'positioning apparatus', so it picked
  `rotary_shaft`. The downstream RotaryShaftScaffold built
  coaxial cylinders — nothing like the four-arm parallelogram
  in the figure.
* **US4470181A_self_closing_hinge** — classifier matched
  'self closing hinge' but recommended the generic
  `door_hinge` scaffold, which produces flat door + frame
  panels with a pintle. The actual figure shows a
  cam-and-spring closer mechanism dominated by a vertical
  post. This example also has a corpus-level caveat: its
  claim_map describes a wire-insertion machine that doesn't
  match its own figure_1, so we treat the figure as ground
  truth.
* **US3705522A_planetary_gear_with_idler** — topology was
  correct (`planetary_gear`) but routed to `rotary_shaft`,
  which stacked the planet pinions coaxially with the sun.
  Patent has multi-view (sectional + plan) figures the
  pipeline did not honor.

V13-J recorded these as
`examples/reports/V13_SEMANTIC_MISMATCH_AUDIT.md`. The fix
shipped in V13-K (classifier ordering, two new topology
labels, `multi_view` field), V13-L (three new scaffolds),
V13-M (regenerate the three examples + plan-view render for
the planetary gear), V13-N (mismatch detector that compares
classifier output against example slug + claim labels), V13-O
(viewer ⚠ banner) and V13-P (this docs pass).

**V13-Q/R/S — visual polish.** The K/L/M cycle picked the
right family, but the rendered geometry still read as 'flat
plate with sticks' (positioning) or 'a stick on a slab'
(self-closing hinge) or 'translucent rings on a shaft'
(planetary). V13-Q rebuilt the positioning_apparatus
scaffold with a central spoked pivot hub, vertical and
horizontal arm legs ending in distinct housings, and a
parallelogram cluster on the upper-left — mirroring fig 2A.
V13-R bulked the self-closing hinge with a wider base
(visible rail channels), a cam wheel below the hinge body,
and an explicit multi-coil spring profile so the spring
reads as a spring. V13-S added small radial teeth to the
planetary gear's sun / planets / ring gears via two
helpers (`_toothed_disc` / `_toothed_ring`) and halved the
housing height so the oblique view is no longer dominated
by a translucent tower. V13-T regenerated the before/after
composite at two sizes (compact for the audit body, large
for PR / README hero).

Before / after composite:
`examples/reports/V13_SEMANTIC_BEFORE_AFTER.png`. Per-example
side-by-side: `<example>/renders_v1.3/semantic_before_after.png`.

Mismatch detector status on the live corpus:
```
0 warnings, 1 advisory, 24 clean.
```
The single advisory (US4502185A_concealed_hinge_assembly:
`door_hinge` picked over the close-family
`two_plate_hinge`) is intentional — those two scaffolds are
geometrically near-neighbours and both build a recognizable
hinge. A user can spot the difference in the viewer banner
and decide whether to override.

## Honest assessment

### What v1.3 delivers
* End-to-end coverage across 25 examples — every patent has a
  v1.3 GLB, a topology classification, a scaffold-matched
  geometry, and figure hotspots in image bounds.
* No example is a central pile.
* No example crashes the viewer.
* Quality is honestly graded; users see the badge before they
  click.

### What v1.3 does NOT deliver
* The 20 'partial' examples use template-driven geometry that
  looks like the topology family (a planetary gear, an
  articulated arm, a hinge) but does NOT closely resemble the
  specific patent's figure. Polishing those to flagship
  quality requires per-family hand-built layouts, which the
  brief explicitly excludes.
* Hotspot detection rate is 70% corpus-wide vs 95% on the
  flagship. Some patent figures use leader styles the Hough
  threshold doesn't catch; tuning per-figure is future work.
* Generic auto-classification of view_type from the figure is
  not implemented — every example defaults to "oblique" unless
  figure_map records something specific.

## Public positioning

Claim2CAD is a research/prototype system, not a production
patent CAD engine. The flagship demonstrates what's achievable
when one patent gets engineering attention; the multi-patent
batch demonstrates the pipeline scales to a corpus without
hand-holding while honestly reporting per-example quality.

The README hero stays the V12-M oblique opened-door render;
the dropdown shows the rest of the corpus with quality badges
so a visitor understands the difference.
