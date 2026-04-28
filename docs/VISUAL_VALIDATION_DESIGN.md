# Visual Validation — Design

The visual validator is the eyes of v1.1's refinement loop. Without a
rendering and scoring pipeline that the VLM trusts, there is no way to
close the loop between generated CAD and the original patent figure.
This doc explains the choices made in `claim2cad/visual_validator.py`.

## Pipeline

```
STEP file ──▶ build123d.import_step ──▶ Compound
                                        │
                                        ▼
                                  tessellate(0.5)
                                        │
                                        ▼
                          (vertices Nx3, triangles Mx3)
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                               ▼                               ▼
  view = iso                      view = front                    view = top, right
  matplotlib 3D ax.view_init(elev=25, azim=45) → PNG @ 1024x1024
        │                               │                               │
        └─────────────┬─────────────────┴───────────────────────────────┘
                      ▼
              4× rendered PNGs
                      │
                      ▼
       make_comparison_grid(figure_png + 4 renders) ──▶ composite.png
                      │
                      ▼
       compare_to_figure → vision_completion(opus-4.7)
                      │
                      ▼
              SimilarityReport
                      │
                      ▼
              baseline_validation.json (V11-2)
              composite_iter{NN}.png   (V11-4)
```

## Why matplotlib

The natural choice would be a real renderer (trimesh + pyrender,
three.js + puppeteer, OCC viewer). We picked matplotlib's 3D backend
because:

1. **It's already installed.** `pyrender` and `trimesh` are not in this
   project's `.venv`, and the brief was clear that adding a heavy
   headless-GL dependency was a last-resort fallback.
2. **The output is good enough for the VLM.** Lambertian-shaded
   triangles on a white background, multi-view, edges drawn in thin
   black — this is close enough to a "shop drawing rendered as CAD"
   that the VLM can judge silhouette and proportion.
3. **It's deterministic and CI-friendly.** No GPU, no display, no race
   conditions. The renderer is called from tests in the standard
   `tmp_path` pattern with no special harness.

The trade-off is render fidelity: smooth surfaces look faceted, fine
features may be lost at default tolerance, and the lighting is flat.
We accept this — V11-2 isn't trying to win a render contest, it's
trying to give the VLM enough signal to score the geometry.

## Why a single composite image

The validator could send N+1 images per call (the figure + N CAD
renders) but Anthropic's vision API charges per-image-token. Instead
we compose ONE side-by-side composite: patent figure on the left, 2x2
render grid on the right, with text labels at the top.

Benefits:
- One image, predictable cost (~4 KB tokens of image content).
- The VLM sees both panels in the same prompt, so direct comparison is
  natural ("the left has X, the right is missing X").
- No prompt-engineering required to teach the VLM that image A is the
  reference and B-E are the candidate.

Trade-off: each individual CAD render is shrunk to ~512px. If a
component is small relative to the whole assembly (the spring-loaded
hinge example: pin is 6mm in a 250mm scene), it can vanish in the
shrunken render. We accept this; it's a known failure mode of
whole-assembly validation, and Session 2's per-component rendering
fixes it.

## SimilarityReport schema

```python
@dataclass
class SimilarityReport:
    overall_score: float          # 0-10 integer-valued
    silhouette_score: float       # 0-10
    proportion_score: float       # 0-10
    feature_score: float          # 0-10
    arrangement_score: float      # 0-10
    defects: list[dict]           # [{"component": id, "issue": str, "severity": minor|moderate|major}]
    notes: str
    raw: dict                     # full VLM response for audit
```

The four sub-scores let the refinement loop tell whether a regression
is in proportion vs. arrangement vs. feature presence — useful for
debugging instability. The `defects` list is the actionable bit: each
flagged item names a component_id we already know about (from the IR)
and a short prose issue. The loop's `_pick_components_to_refine`
filters by severity to choose which components to ask the VLM to
revise.

## What the prompt does and doesn't say

**Does say:**

- Be honest. 0 = unrelated, 5 = recognisable, 10 = visually
  indistinguishable.
- The CAD is allowed to be stylised. Match silhouette, proportion,
  feature presence, and arrangement.
- Always return JSON.

**Doesn't say:**

- Anything about the patent. We pass `patent_context` only when the
  caller provides it (the CLI takes `--patent-context`); otherwise the
  VLM sees only the figure + the component list.
- Anything about how the CAD was generated. The VLM doesn't know we
  used a library or a primitive fallback; it just judges what it sees.

## Cost

A single validation call is ~$0.03 with Opus 4.7 (≈4k input tokens
including the composite image, ≈400 output tokens for the JSON
report). The full V11-4 loop with 3 iterations costs ~$0.20-$0.30 per
example.

## Known issues / Session 2 work

1. **Whole-assembly only.** Per-component crops would let the VLM
   judge in isolation.
2. **No figure cropping.** When the patent figure has multiple sub-figures
   the renderer doesn't isolate the relevant one — we always send the
   raw figure_1.png. Session 2 will use the figure_map bounding boxes.
3. **Single view set.** The 4 default views (iso, front, right, top) are
   fixed. A view-aware optimiser ("which 4 views best showcase this
   geometry") is a research direction worth exploring.
4. **VLM is not deterministic.** Same composite, same prompt → different
   scores between runs. We accept ±1 point of noise; the refinement
   loop's "no improvement for 2 iterations" stop condition tolerates
   it.
