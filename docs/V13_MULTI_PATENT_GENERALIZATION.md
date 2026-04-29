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

## Scaffold registry (V13-B)

`claim2cad/scaffolds/` is a package whose modules each register
one Scaffold subclass via the `@register_scaffold` decorator:

| Scaffold | Used for | Quality tier |
| --- | --- | --- |
| `door_hinge` | door hinges (generalised from V12-J) | good |
| `two_plate_hinge` | simpler concealed hinges | good |
| `rotary_shaft` | gears, transmissions, planetary, harmonic, differential | partial |
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

## Topology classifier (V13-C)

`claim2cad/figure_topology_classifier.py` is keyword-based
and deterministic. Inputs: claim_map labels + claim.txt + the
example's id. Outputs: `figure_classification.json` with
view_type, topology, recommended_scaffold, confidence, evidence.

10 topology rules covering door_hinge, two_plate_hinge,
planetary_gear, harmonic_gear, differential_gear, rotary_shaft,
robotic_arm, linkage, bracket_mount, housing_panel.

Run on the corpus:
```
{'planetary_gear': 8, 'robotic_arm': 7, 'rotary_shaft': 4,
 'door_hinge': 3, 'harmonic_gear': 1, 'housing_panel': 1,
 'unknown': 1}
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

## Eval (V13-G)

`MULTI_PATENT_EVAL.md` ranks each example by 9 axes and
assigns an overall_quality verdict. On the corpus:

| Verdict | Count |
| --- | ---: |
| flagship | 1 |
| good | 2 |
| partial | 20 |
| fallback | 2 |
| failed | 0 |

Mean overall_score: **0.796**.

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
