# V1.1 Design — Figure-Driven CAD

This is the design document for v1.1, the photorealistic-figure-aware
generation pass that lives on `v1.1-dev`. It captures *why* the v1.1
architecture is shaped the way it is, what it inherits from v1.0, and
the boundary between "shipped this session" and "Session 2 / Session 3
work".

## Why figure-driven, not claim-driven

v1.0 generated CAD from claim text alone. Each IR component became a
primitive (Box / Cylinder / Sphere) laid out in a deterministic line
along X. That worked for *topology* — claim_map.json bound 25/25
components for US4807331A, the GLB carried the right node names, and
the viewer could highlight components by claim ID — but it produced
models that didn't *look* like the patent figures. v1.0's
`render_v1.0_vs_figure.png` for the spring-loaded-hinge example is the
most honest illustration: 25 grey dots in a line vs. a detailed
mechanical drawing.

The fix v1.1 commits to is treating the **figure** as ground truth for
geometry, while keeping the **claim** as ground truth for which
components must exist and how they're identified. Concretely:

- The IR is unchanged. It still owns component IDs, kinds, categories,
  source spans, and figure references. v1.0's tests still pass
  (101 baseline tests in `tests/test_*` continue green).
- A new **figure_to_cad** stage runs after the parser. It takes the IR
  + the primary figure and asks Claude-Opus-4.7 vision for one
  per-component spec row: *which library part, which dimensions, which
  position, which rotation, which features*. The result is
  `figure_spec.json` — a JSON file the user can hand-edit if they
  disagree with the VLM's read.
- A new **component library** (`claim2cad/components/`) provides
  parameterised mechanical parts. The figure-to-cad stage picks one
  per component. There is a primitive fallback for components the
  library doesn't cover (e.g. abstract IR concepts like `hinge_axis`
  that are not actually a part).
- A new **refinement loop** renders the assembly, asks the VLM to
  compare it to the figure, and rewrites the worst component specs.
  Loop until target score, max iterations, or no improvement.

## Component library architecture

The library lives under `claim2cad/components/` and is structured as:

```
components/
├── base.py            # Component ABC: build(), bbox(), tag(), export_step(), export_glb()
├── library.py         # registry, register() decorator, lookup(), instantiate()
├── primitives/        # plate, rod, l_bracket, u_bracket, pin
├── joints/            # leaf_hinge, revolute_joint, prismatic_joint
├── transmission/      # spur_gear, ball_bearing
└── fasteners/         # helical_spring
```

Design choices that are deliberate:

1. **Each library entry is a `@dataclass` Component subclass** with
   `_build_solid()` returning a build123d Part / Compound. Parameters
   are mm-scaled floats validated in `__post_init__`. No class
   constructs anything in `__init__`; all geometry is in `_build_solid`
   so users can introspect parameters without paying the build cost.
2. **The library registry uses string names with aliases.** The VLM
   emits a `library_part` string from a known list; alias matches
   allow patent-vocabulary terms (e.g. `pintle_pin`, `dowel`,
   `hinge_pin` all match `pin`). When a name doesn't match any
   registered entry, `lookup()` returns `None` and the generator falls
   back to a v1.0 primitive. This is preferable to forcing the VLM to
   guess from a closed list — no-match is a clean signal.
3. **Components composing multiple sub-parts return a `Compound`** with
   labelled children (e.g. `LeafHinge` → `leaf_a`, `leaf_b`, `pin`). The
   GLB-naming postprocess (`glb_naming.rename_glb_root_children`) names
   the root-child slot by component_id; the sub-parts keep their own
   labels for downstream tooling that may want to highlight them.
4. **Material colour is a hint, not a render style.** Each Component
   sets `solid.color = bd.Color(r,g,b)` from a material name. The
   matplotlib renderer in V11-2 uses neutral Lambertian shading and
   ignores the colour — but a future GLB-native renderer can read it.

Library coverage today is small but covers the US4807331A example and
handily extends. Session 2 will add: `harmonic_drive`, `cycloidal_drive`
(robotic transmissions), `gripper`, more bearing variants.

## Refinement loop design

The loop in `claim2cad/refinement_loop.py` is the core innovation of
v1.1. Pseudocode:

```
spec ← initial figure_spec
for iter in 0..max_iterations:
    build assembly from spec
    render → composite → SimilarityReport via vision call
    record iteration
    if score >= target_score → break
    if cumulative cost ≥ soft_cap → break
    if no improvement for 2 iterations → break
    flagged ← worst components by defect severity (cap 5)
    revisions ← VLM revises flagged spec rows (one vision call)
    spec ← merge revisions into spec
promote BEST iteration to model_v1.1.{step,glb}
```

Subtleties worth calling out:

- **Whole-assembly validation, per-component refinement.** The whole
  assembly is rendered + scored each iteration. The VLM is asked to
  revise only the flagged components (capped to 5 to keep prompt
  size bounded). This balances "see the whole picture" against
  "don't burn tokens on components that are fine".
- **The best iteration wins, not the last.** Refinement *can* regress
  — the VLM's revised positions may break alignment with non-flagged
  neighbours. We track the best score and copy that iteration's
  STEP/GLB to the canonical paths after the loop ends. This is the
  honest behaviour: v1.1 ships the best CAD it produced, not the most
  recent.
- **Each iteration is fully resumable.** We write
  `model_v1.1_iter{NN}.{step,glb}`, `composite_iter{NN}.png`, and
  `figure_spec_iter{NN+1}.json` to disk after every step. If the loop
  is interrupted mid-iteration the user can resume from the last
  spec on disk via `--use-cached-spec`.
- **Cost discipline.** Every vision call is logged via
  `cost_tracker.record_call(task_type="v11_*")` so the user can see
  exactly how much each phase spent. The loop halts at the
  soft cap (default $70).

## What we replicate from text-to-cad video

The text-to-cad demo video (DeepSeek-R1, OpenAI o3, et al.) generates
CAD by VLM-guided code synthesis. v1.1 replicates two of its key ideas:

1. **The VLM is the geometry author, not the developer.** No human
   writes per-patent CAD code; the VLM does. We call this the
   "figure_spec.json" handoff.
2. **Render → score → revise.** A vision-grounded loop catches errors
   that pure-text generation cannot (e.g. proportions, occlusions,
   missing features).

## What we don't replicate (yet)

- **Photorealistic rendering.** The text-to-cad demo uses Three.js /
  Keyshot-grade rendering. v1.1 uses matplotlib's 3D backend — solid
  Lambertian shading on a white background. Good enough for the VLM's
  scoring eye, not good enough for a marketing video.
- **Full code synthesis.** v1.1's "fallback to VLM-generated build123d"
  is documented but not implemented this session — the library + a
  primitive fallback covered every needed component for US4807331A.
  Session 2 will wire in a sandboxed `exec()` of VLM-generated code
  for parts the library doesn't have.
- **Multi-figure context.** US4807331A has three figures showing the
  closed and lifted-off states; v1.1 only sends figure_1 to the VLM.
  Adding figures 2-3 is an obvious Session 2 win.
- **Constraint-aware revisions.** When the VLM revises a pin's
  position, it doesn't know that two leaves' knuckle holes must remain
  aligned with that axis. This is the dominant cause of refinement
  regressions; Session 2 will add per-component "anchor" constraints.

## Honest comparison to text-to-cad video quality

For the one example we've shipped (US4807331A spring-loaded hinge),
v1.0 was effectively 0% of text-to-cad-video quality (a row of
indistinguishable boxes). v1.1 is ~30-40% — the central hinge cluster
is recognisable, library parts are placed in the right neighbourhood,
but proportions are off and many small features are missing. v1.1
ships a clear improvement over v1.0, not a competitive product.
Session 2 + 3 close the gap.
