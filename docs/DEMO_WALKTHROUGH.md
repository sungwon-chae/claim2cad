# Claim2CAD demo walkthrough

A 5-minute tour of what Claim2CAD v1.2 can do, using the
US4807331A spring-loaded door hinge example.

## 1. Run the demo

```bash
git clone https://github.com/sungwon-chae/claim2cad
cd claim2cad
make demo-v12
```

`make demo-v12` does three things:

1. Provisions the Python venv (build123d, OpenCV, matplotlib).
2. Re-stages the example artefacts into `viewer/public/data/`
   (the v1.2 demo GLB takes precedence over v1.1 / v1.0).
3. Starts the Vite dev server at <http://localhost:4179>.

## 2. What you see

The viewer opens with US4807331A_spring_loaded_hinge selected
automatically (it's the only example tagged `demo_quality`).

**Left pane — patent claim text.** Each underlined span is one
claim component. Hover a span → the matching figure hotspot and
3D mesh highlight. Click → the highlight stays put.

**Centre pane — 3D scene.**
* Camera defaults to the **patent_figure** preset (V12-L) — the
  oblique three-quarter view that matches the patent figure.
* Camera presets bar at the bottom:
  `patent fig. ★ · figure · top · front · right · iso · free`.
* The 3D model is the V12-J **oblique opened-door** geometry:
  the door is swung open ~35° on the pintle axis; the frame
  stays upright. The flat front model is still in the repo as
  `model_v1.2.glb` for debug.
* Click any face to select that component; the claim span and
  figure hotspot light up.

**Right pane — patent figure with hotspots.**
* Each callout is a coloured marker over the digit text.
* Demo mode shows only **high** and **medium** confidence
  hotspots (24 + 8 = 32 / 32 on this example).
* Click a hotspot → claim and 3D mesh highlight.

## 3. Demo mode vs Debug mode

Top-right header has a yellow **Demo mode** button.

Click it → **Debug mode** (orange):
* Shows label hotspots (the digit-text positions) as dashed grey
  squares with a "show labels" toggle.
* Shows low-tier hotspots (label_center fallbacks) — none on
  this example.
* The mode persists in the URL: `?mode=debug`.

## 4. Round-trip examples

Try these to see the claim ↔ figure ↔ CAD round-trip work:

| Action | What highlights |
| --- | --- |
| Click "the pintle pin" in the claim text | Pintle pin marker (figure) + pintle pin mesh (3D) |
| Click the green dot near callout 22 | Same |
| Click the brown vertical cylinder in 3D | Same |
| Click "the upper extension of the main member" | Upper extension marker (figure, top hinge area) + upper bracket mesh (3D) |
| Click the upper bracket mesh | Same |

The repeated callouts (numbers 116, 22, 60, etc. that appear
twice — once on the upper hinge, once on the lower) get
**separate hotspot instances** but both link to the same
component_id, so either one highlights the same mesh.

## 5. Keyboard / camera tips

* Drag — orbit the 3D camera.
* Scroll — zoom.
* `figure ★` button — snap back to the patent-figure projection.
* `iso` — diagonal view; the door panel and frame become
  obviously translucent here.

## 6. Inspecting the artefacts

If you want to see the data behind the demo, check:

```
examples/real_patents/US4807331A_spring_loaded_hinge/
├── claim.txt                          # input
├── claim_ir.json                      # parsed structure
├── claim_map.json                     # component → claim span
├── figure_map.json                    # callout extraction
├── leader_lines.json                  # OpenCV leader detection
├── figure_layout_lock.json            # V12-B hand-traced regions
├── figure_projection.json             # UV → world projection
├── figure_projection_locked.json      # after V12-B applied
├── figure_hotspots.json               # canonical hotspots + tiers
├── figure_hotspot_overrides.json      # V12-F manual fixes
├── model_v1.2.step                    # demo CAD (STEP)
├── model_v1.2.glb                     # demo CAD (GLB, viewer-ready)
├── VISUAL_TRUTH_AUDIT.md              # honest critique of v1.1
└── renders_v1.2/
    ├── readable_iso.png               # README hero image
    ├── readable_figure_aligned.png    # figure-projection-aligned
    ├── readable_exploded.png          # panels pulled apart
    ├── solid_comparison.png           # side-by-side with figure
    ├── figure_projection_lock_debug.png  # V12-B regions
    └── hotspot_quality_debug.png      # V12-F tier overlay
```

## 7. Running on a different patent

Today the v1.2 demo scaffold (`claim2cad/demo_scaffold.py`) is
patent-family-specific. To get the same demo quality on another
example you need:

1. A `figure_layout_lock.json` with hand-traced regions for the
   major groups (door / frame / hinges / etc — replace with the
   appropriate group set for that patent family).
2. A demo scaffold builder that produces the right geometry —
   for now, fork `build_demo_assembly_us4807331a` and write the
   per-family equivalent.

Generic scaffold inference is on the v1.3 roadmap. For v1.2,
the brief explicitly allows a hand-built scaffold for the
flagship example.

## 8. What's NOT yet polished

Read `examples/real_patents/US4807331A_spring_loaded_hinge/VISUAL_TRUTH_AUDIT.md`
for the unsentimental list. Honest summary:

* **Demo example only.** Other examples in the dropdown still
  use the v1.1 figure-anchored solver; their output is a more
  abstract "primitive collage" but the claim ↔ CAD ↔ figure
  contract still holds.
* **Door panel slightly occludes the upper hinge** in the
  figure-aligned view. Use the iso view (or the readable
  exploded render) to see the upper hinge cleanly.
* **Bracket-to-panel attachment is positional, not Boolean
  union.** A small visible gap at the bracket leaf where it
  meets the door panel is mostly hidden by the panel's
  transparency.
* **figure_resemblance IoU is low (0.02)** because the metric
  compares a line drawing to a filled solid render. The
  `panel_dominance`, `hinge_axis_visibility`, and human eyes
  all say the assembly reads correctly.

## 9. Where to read more

* `docs/V12_VISUAL_RECONSTRUCTION.md` — design notes on V12-B
  through V12-G.
* `docs/HOTSPOT_GROUNDING.md` — leader-line detection +
  confidence tier scheme.
* `docs/ARCHITECTURE.md` — the IR ↔ CAD ↔ viewer pipeline.
* `examples/reports/US4807331A_spring_loaded_hinge_v12_eval.md`
  — the v1.2 evaluation report.
