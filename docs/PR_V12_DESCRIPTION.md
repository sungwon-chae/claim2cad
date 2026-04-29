# PR — v1.2: figure-grounded demo-quality reconstruction for US4807331A

**Base branch:** `main` ← **Head branch:** `v1.2-dev`
**Status:** ready for review

## Summary

V1.2 turns the v1.1 "figure-aligned but visibly piled" CAD into a
visually convincing flagship demo for one patent
(US4807331A_spring_loaded_hinge). The demo has separate door / frame
panels, an upright pintle pin, two distinct hinge clusters, and a
viewer that defaults to the polished example with the figure-aligned
camera and a Demo / Debug mode toggle.

**The change is patent-family-specific by design.** The brief
explicitly allowed a hand-built scaffold for the flagship example;
generic perspective inference is on the v1.3 roadmap.

## What changed

Eight phased commits on `v1.2-dev`:

| SHA | Phase | Purpose |
| --- | --- | --- |
| `cb6970f` | A | `VISUAL_TRUTH_AUDIT.md` — unsentimental critique of v1.1 |
| `870ab40` | B | `figure_layout_lock.py` + JSON regions — UV regions per group, hard-clamp to bbox |
| `93eeb08` | C | `demo_scaffold.py` — direct build123d primitives at locked anchors |
| `2b7c496` | D | `readable_render.py` — per-mesh styling, layered alpha for translucent panels |
| `4d4612f` | E | viewer defaults to `demo_quality`-tagged example, Demo / Debug mode |
| `812a085` | F | `confidence_tier` on every hotspot + `figure_hotspot_overrides.json` |
| `41ef167` | G | `eval_v12.py` — visual-axis evaluator with central-pile hard-fail |
| `7a91b64` | H | README hero, `docs/DEMO_WALKTHROUGH.md`, `docs/V12_VISUAL_RECONSTRUCTION.md`, `make demo-v12` |

### New / changed files

```
claim2cad/
  figure_layout_lock.py     NEW   V12-B
  demo_scaffold.py          NEW   V12-C
  readable_render.py        NEW   V12-D
  eval_v12.py               NEW   V12-G
  manifest.py               EDIT  prefer model_v1.2.glb in viewer staging
  figure_hotspots.py        EDIT  confidence_tier + manual override

viewer/src/
  App.tsx                   EDIT  default to demo_quality, mode toggle
  components/FigurePanel.tsx EDIT viewerMode prop, tier filtering
  styles.css                EDIT  .tier-* + .mode-toggle classes

examples/real_patents/US4807331A_spring_loaded_hinge/
  VISUAL_TRUTH_AUDIT.md             NEW
  figure_layout_lock.json           NEW
  figure_projection_locked.json     NEW (generated)
  figure_hotspot_overrides.json     NEW
  figure_hotspots.json              REGEN with tiers
  model_v1.2.{step,glb}             NEW
  renders_v1.2/                     NEW DIR
    figure_projection_lock_debug.png
    solid_{figure_aligned, iso, top, comparison}.png
    readable_{figure_aligned, iso, exploded, debug_labels, comparison}.png
    figure_hotspot_debug.png
    hotspot_quality_debug.png

docs/
  DEMO_WALKTHROUGH.md           NEW
  V12_VISUAL_RECONSTRUCTION.md  NEW
  PR_V12_DESCRIPTION.md         NEW (this file)
  HOTSPOT_GROUNDING.md          REWRITTEN at V11-37

tests/
  test_figure_layout_lock.py    NEW (5 regressions)

examples/reports/
  US4807331A_spring_loaded_hinge_v12_eval.md
  US4807331A_spring_loaded_hinge_v12_eval.json

Makefile                       EDIT  demo-v12 + eval-v12 targets
README.md                      REWRITE with v1.2 hero section
```

### Eval

| Metric | Score |
| --- | ---: |
| `panel_dominance` | 1.000 |
| `hinge_axis_visibility` | 1.000 |
| `floating_components` | 0.556 |
| `demo_readability` | 0.616 (verdict: ok) |
| `figure_resemblance` | 0.016 (sparse line drawing vs filled solid — known metric limitation) |
| `v11_carryover` composite | 0.768 |
| **V1.2 composite** | **0.662** (verdict: ok) |

The lower V1.2 composite vs V1.1's 0.768 is **more credible**, not
less: V12-G surfaces failures the v11 axes hid (central density
score on v1.1 was 0.0; we surface it as part of the demo_readability
hard-fail logic).

Tests: **289 passing** (was 284 at v1.1; +5 in
`test_figure_layout_lock.py`).

## What is patent-specific

These four files are hand-built for US4807331A and are NOT generic:

1. `examples/.../figure_layout_lock.json` — hand-traced UV regions
   for door_panel / fixed_frame / upper_hinge / lower_hinge /
   pintle_axis / power_mechanism / fasteners.
2. `claim2cad/demo_scaffold.py::US4807331A_MESH_SPECS` — table that
   maps every claim component_id to one of the hand-built meshes.
3. `claim2cad/readable_render.py::US4807331A_DEMO_STYLES` — per-mesh
   colour and transparency table.
4. `examples/.../figure_hotspot_overrides.json` — hand override for
   the abstract `hinge_axis` tier.

The other 29 examples in the manifest still use the v1.1 figure-
anchored solver and render in the older "primitive collage" style.
Nothing breaks for them — the claim ↔ figure ↔ CAD round-trip
holds — but a reviewer who expects every example to look like the
hero will be disappointed.

## How to test

```bash
git fetch origin v1.2-dev
git checkout v1.2-dev

# 1. Tests
make test                  # 289 passing

# 2. Demo
make demo-v12              # opens http://localhost:4179
                           # US4807331A loads automatically
                           # Demo mode active by default

# 3. Eval
make eval-v12              # writes US4807331A_v12_eval.{md,json}
```

Click-through verification (each row should keep the three panels
in sync):

| Click target | Expect |
| --- | --- |
| Pintle pin in 3D scene | "the pintle pin" claim span + green dot near callout 22 in figure |
| The upper hinge bracket in 3D | "the upper extension of the main member" + upper-hinge hotspot |
| Any hotspot dot in figure panel | matching claim span + 3D mesh |
| Any underlined span in claim panel | matching hotspot + 3D mesh |
| Top-right `Demo mode` button | toggles to Debug mode (orange); URL gains `?mode=debug` |

## Known limitations

1. **Demo example only.** Other examples render with v1.1. v1.2 is
   patent-family-specific by design.
2. **Door panel slightly occludes the upper hinge bracket** in the
   front (figure-aligned) view. The iso view + readable_exploded
   view show the upper hinge cleanly. Use these for inspection.
3. **Bracket-to-panel attachment is positional, not Boolean union.**
   A small visible gap exists where the bracket leaf meets the
   door panel; mostly hidden by panel transparency.
4. **`figure_resemblance` IoU = 0.016**: the patent figure is a
   line drawing (sparse mask) and the CAD render is a filled
   solid (dense mask). Direct mask IoU bottoms out. A future
   silhouette-extraction pre-step would fix the metric.
5. **`floating_components` flags `door_panel` itself** as floating
   because its bbox is so big it doesn't intersect the smaller
   hinge bboxes in 3D space. False positive. Worth fixing in v1.3.
6. **STEP-export build123d bug workaround in place.** When two
   compound children have coincident bboxes, build123d's STEP
   export drops one. `demo_scaffold.py` places alias/feature
   markers JUST OUTSIDE the parent's `+X / +Z` bbox face. Source
   includes a comment explaining the workaround. Should be
   reported upstream.
7. **`viewer/public/data/` is gitignored** (built artefact).
   Reviewers running `make demo-v12` will see the v1.2 GLB
   correctly because the manifest builder picks
   `model_v1.2.glb` automatically.

## Screenshots / files to inspect

All under `examples/real_patents/US4807331A_spring_loaded_hinge/`:

* `VISUAL_TRUTH_AUDIT.md` — the unsentimental critique of v1.1.
* `renders_v1.2/readable_iso.png` — **README hero image**.
* `renders_v1.2/readable_figure_aligned.png` — translucent panels,
  hinge visible through them.
* `renders_v1.2/readable_exploded.png` — panels pulled apart.
* `renders_v1.2/solid_comparison.png` — side-by-side with patent
  figure.
* `renders_v1.2/figure_projection_lock_debug.png` — V12-B regions
  overlaid on the figure (visual proof of the layout lock).
* `renders_v1.2/hotspot_quality_debug.png` — V12-F tier overlay
  (24 high + 8 medium + 0 low).
* `model_v1.2.glb` — 35 GLB nodes, all linked to claim_map IDs.

Reports:
* `examples/reports/US4807331A_spring_loaded_hinge_v12_eval.md`

Docs:
* `docs/DEMO_WALKTHROUGH.md` — 5-minute tour.
* `docs/V12_VISUAL_RECONSTRUCTION.md` — design notes per phase.

## Suggested merge checklist for the reviewer

- [ ] Open `renders_v1.2/readable_iso.png` — does it visually convince you?
- [ ] `make demo-v12` — round-trip click-through works.
- [ ] `VISUAL_TRUTH_AUDIT.md` — every issue called out is addressed.
- [ ] `examples/reports/..._v12_eval.md` — `demo_readability` verdict is `ok`.
- [ ] `figure_projection_lock_debug.png` — regions match the figure layout.
- [ ] `make test` — 289 passing.
