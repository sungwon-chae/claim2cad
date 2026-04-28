# Quality Notes — US4807331A_spring_loaded_hinge (v1.1)

Honest record of how close v1.1 is to the patent figure for this example,
and where the remaining gaps are. Numbers are not flattering — that is
the point. Faking them helps nobody.

## Score history

| Pipeline | Overall | Silhouette | Proportion | Feature | Arrangement | Notes |
|---------:|--------:|-----------:|-----------:|--------:|------------:|------|
| v1.0 baseline | **0/10** | 0 | 0 | 0 | 0 | row of 25 boxes |
| v1.1 first pass (Session 1) | **3/10** | 3 | 4 | 2 | 3 | library bug — params silently dropped |
| v1.1 fix-pass (param aliases + codegen) | **3/10** | 3 | 4 | 3 | 4 | params now flow; codegen built 4 parts |

Target was 5+/10. We did not reach it. Component-level geometry
improved meaningfully; whole-assembly *composition* did not. The
absolute-score plateau at 3 is real.

## The Session 1 bug, post-mortem

The V11-3 figure-to-spec call did pick library entries and emitted
sensible params. But `library.instantiate` was silently dropping any
param whose name didn't match a dataclass field — and `UBracket` /
`LBracket` use canonical names (`base_length`, `base_width`,
`side_height`, `leg_a_length`, `leg_b_length`) that the VLM has no way
to guess from the figure-to-cad prompt. The VLM emitted `length`,
`width`, `height`. Only `thickness` survived. Every U-bracket in
v1.1's first pass was therefore built with default 60×40×35 mm — a
small placeholder regardless of what the patent figure showed.

That was the root cause of "v1.1 still looks like primitives".

## Fixes shipped this pass (Fix-A through Fix-G)

1. **Fix-A — `param_aliases` on every library entry.** VLM-natural
   names (`length`/`width`/`height`/`od`/`bore`) now route to canonical
   dataclass fields. Dropped params are logged at WARNING.
2. **Fix-B — Param schemas inside the figure-to-cad prompt.** The
   library is documented inline so the VLM is told the exact field
   names + units it should use. Dynamic, not a hand-maintained list.
3. **Fix-C — Per-callout figure crops.** `claim2cad/figure_crops.py`
   reads `figure_map.json`'s `vlm_labels` (number → normalised
   position) and writes one PNG crop per numbered component, annotated
   with `fig#N -> <component_id>`. 45 crops produced for US4807331A.
4. **Fix-D — Sandboxed VLM build123d codegen.** New
   `claim2cad/vlm_codegen.py`: VLM is given a figure crop + IR fields +
   claim constraints and writes a build123d snippet that binds a
   `result` variable. AST-validated (no imports, no dunders, no try),
   exec'd in a curated namespace, output validated for non-empty
   bbox + sane size. 4 components on US4807331A built this way.
5. **Fix-E — Re-run + rescore.** Below.
6. **Fix-F — Renderer cleanup.** Removed the heavy black edges that
   were tessellating thin walls into "triangles" the VLM couldn't
   parse. Multi-light Lambertian shading replaces single-light setup.
7. **Fix-G — Codegen-first preserved through refinement.** When the
   refinement loop revises a codegen component, only `position_mm` and
   `rotation_deg` are accepted; geometry stays VLM-synthesised.

## What got better

- **Library parts now have correct geometry.** A `u_bracket` with
  `base_length=60, base_width=40, side_height=50, thickness=3,
  side_hole_diameter=6` produces an actual U-channel with side holes,
  not a 60×40×35 default placeholder.
- **The CAD now contains 3 nested U-brackets + a pintle pin.**
  `door_half_member`, `main_member`, `u_shaped_link_member` are placed
  along a vertical axis with `pintle_pin` running through their side
  holes. The pin's round head is visible at the top.
- **Codegen produces idiosyncratic shapes the library can't.**
  `door_half_member.py` builds a true outer-box-minus-inner-cavity
  U-channel; `main_member.py` extrudes a 9-vertex polyline profile
  that approximates the patent's L-shaped main member; `leaf_flange.py`
  is a holed plate. These are figure-faithful at the part level.
- **Vehicle body correctly excluded.** The prompt now flags
  contextual bodies as `abstract; no standalone geometry`. The CAD
  no longer wastes silhouette on a 200 mm panel that isn't claimed.
- **Renderer no longer manufactures triangle edges.** Removing the
  edge lines made the U-channel cavity visible in the iso render.

## What is still wrong (the real 7 → 3 gap)

These are the defects the VLM consistently flags across 8+ validation
calls in this fix-pass:

1. **Composition is broken.** Each codegen component has its own
   internal coordinate frame; the VLM-supplied `position_mm` /
   `rotation_deg` don't always align them so e.g. the pin actually
   passes through all three U-brackets' holes.
2. **Library U-bracket and codegen U-bracket disagree on origin.**
   Library `UBracket` puts the base plate top face at z=0 with sides
   rising in +Z; codegen variants center on origin. Mixing them in the
   same assembly is therefore badly composed.
3. **Patent figure has many small features not in the IR.** Stops
   (numbered 56, 57, 68 etc.), guide edge surfaces, retention grooves,
   sub-flanges — present in figure_1.png, absent from `claim_ir.json`.
   Even a perfect renderer of the IR can only get so close.
4. **VLM grading is harsh on stylised renders.** When the renderer
   produces a 3-light Lambertian view of a clean U-bracket, the VLM
   still flags it as "flat plate" because it expected the engineering
   line drawing's shading conventions. This is partly a renderer
   problem and partly a "what does the VLM consider a U-bracket?"
   problem.

## Concrete improvements queued for Session 2

- **Spatial composer pass.** After codegen produces individual solids,
  one VLM call reviews all of them in a 2D layout sketch and emits
  position/rotation revisions that align shared axes (the pin must
  thread through three holes; the leaf flange must sit on top of the
  link member).
- **IR enrichment from figure.** A pass that augments `claim_ir.json`
  with the small numbered features (stops, grooves, guides) the VLM
  can detect on the figure. Current IR only contains components that
  the claim text names; the figure shows more.
- **Multi-figure context.** US4807331A has three figures showing the
  closed and lifted-off states. We currently send only figure_1.
- **Engineering-style render.** A line-drawing renderer (silhouette
  edges only, hidden-line removal, no shading) would match the patent
  figure's visual language and likely score higher.

## Cost

- Fix-session vision calls: 20 — total $0.94.
- Cumulative across all sessions: $8.39.
- Cap remaining: ample. Cost is no longer the binding constraint.

## Bottom line

Underlying CAD is meaningfully better than Session 1's first pass
(real U-brackets, real holes, real pin, real channel + flange). Score
is the same number (3/10) because the score is dominated by composition,
which we did not crack this pass. The path to 5+/10 is the spatial
composer + IR enrichment described above — neither was attempted in
this fix-session. We should ship the fixes, document the gap, and
plan Session 2 around composition rather than around library breadth.
