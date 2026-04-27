# Design Decisions

The eight non-obvious choices that shaped Claim2CAD v0.1.0, why they were
made, and what would change if the constraints were different.

## 1. Pydantic v2 for the IR, not dataclasses or attrs

**Decision.** The IR (`claim2cad/ir_schema.py`) is pydantic v2 models with
a discriminated union for dimensions and a root validator for referential
integrity.

**Why.** The IR is the contract between four parties: the parser (which
may be an LLM), the CAD generator, the mapping writer, and the viewer.
We need three things at every boundary: validation, JSON
serialization, and JSON-Schema export (for the LLM's response_format).
Pydantic gives all three for free; rolling our own dataclasses would
reimplement validation poorly. The v2 cost (slightly slower import) is
irrelevant for a CLI tool.

**What would change with different constraints.** If we needed
streaming or no-Python clients, we'd switch to a `protobuf` /
`pydantic_to_protobuf` bridge. That's overkill for v0.1.

## 2. OpenRouter as the LLM gateway, not direct provider SDKs

**Decision.** `claim2cad/llm_client.py` posts to OpenRouter's
`/chat/completions` with `response_format: {type: "json_object"}`.

**Why.** Three reasons: (1) one API key works for Claude, GPT-4, Gemini,
Mistral, and Llama variants; switching models is a single env-var
change; (2) OpenRouter normalizes JSON-mode and tool-use across
providers, so the parser doesn't need provider-specific shims; (3)
billing and rate limits live in one place. This matters when iterating
prompt-engineering across models.

**What would change.** If we wanted to use Anthropic's *prompt caching*
(which OpenRouter exposes inconsistently), we'd switch to the Anthropic
SDK directly. For v0.1's prompt sizes (~3 KB), caching is irrelevant.

## 3. Hybrid rule + LLM parser, not LLM-only

**Decision.** `claim2cad/claim_segmenter.py` does a deterministic
preamble/elements/wherein split before the LLM sees the text, and a
rule-based stub parser is the unconditional fallback when the LLM is
unavailable or never produces valid JSON.

**Why.** Patent claims have a regular surface form. An LLM staring at
an opaque blob is wasteful; an LLM staring at a structured breakdown
plus the original text produces better, faster, cheaper IR. The stub
also makes the demo runnable offline — critical for a portfolio piece
that should not require an API key.

**What would change.** With access to a fine-tuned patent-claim LLM,
the rule-based pre-processing might become noise. v0.1 doesn't have
that, and the head-noun-classifier in the stub does measurable work
(see `tests/test_parser.py::test_hinge_stub_extracts_links_and_joints`).

## 4. Source-controlled CAD over imperative scripts

**Decision.** Every example ships a `pipeline_generator.py` (or a
hand-crafted `generator.py`) — a runnable build123d script — alongside
the binary STEP and GLB files. Editing the generator and re-running
gives a different model; the binaries are derived.

**Why.** Mirrors text-to-cad's harness pattern. STEP files are
~100 KB; not painful in git, but the generator is the auditable source
of truth when a model is wrong. A reviewer can read 60 lines of Python
and immediately see what shape was placed where.

**What would change.** If models grew to thousands of components,
caching would matter and we'd add a content-hash check to skip
unchanged subtrees. v0.1's largest example has 9 parts.

## 5. Post-processing the GLB JSON chunk to inject names

**Decision.** `claim2cad/glb_naming.py` rewrites the JSON chunk of the
GLB to set the root scene's children's `name` fields to component IDs.

**Why.** build123d's `export_gltf` emits OCAF refs like `=>[0:1:1:2]`
as node names. Without renaming, the viewer's `mesh.name` lookup is
useless. Forking build123d's exporter is heavyweight; per-component
GLB files would balloon the artifact count. Rewriting the JSON chunk
in place is ~80 lines of Python and survives any build123d release as
long as the GLB binary chunk is left alone.

**What would change.** If build123d adds label round-tripping, the
post-processor becomes a no-op and stays harmless.

## 6. Component IDs are the only string shared between IR, CAD, and viewer

**Decision.** `Component.id` (regex `^[a-z][a-z0-9_]*$`) is used as
`Shape.label`, GLB node name, `claim_map.glb_node_name`, and viewer
`mesh.name` lookup key. There is no remapping table.

**Why.** A remapping table is a thing that goes out of date. One
identifier means one source of confusion when something doesn't
highlight: either the post-processor failed, the IR is malformed, or
the GLB is missing.

**What would change.** If we added an upstream renaming step (e.g.
human curation), we'd need a `renamed_from` field and a migration
helper. Not in v0.1.

## 7. Custom viewer, not a fork of upstream text-to-cad's viewer

**Decision.** `viewer/` is a hand-scaffolded Vite + React + TypeScript +
react-three-fiber app, ~700 lines total. It does not import any
text-to-cad source.

**Why.** Upstream's `CadViewer.js` is ~2000 lines optimised for
geometry inspection: drawing overlays, clipping planes, lighting
presets, axis gizmos. None of that matters here. The portfolio value
of Claim2CAD is the *ClaimPanel* and *bidirectional highlighting*; a
generic CAD viewer would dilute the demo. A custom viewer is also
easier to read and review.

**What would change.** If we needed dimension annotations, section
views, or assembly explosion, we'd reach back to upstream. v0.1 stops
at "click → highlight → camera frame".

## 8. Examples as the unit of distribution

**Decision.** `examples/<name>/` bundles `claim.txt`, `claim_ir.json`,
`claim_map.json`, `model.step`, `model.glb`, and a generator. Three
examples ship: golden_robot_arm, hinge_assembly, planetary_gear.

**Why.** Each example is the smallest reviewable unit: one folder,
five files, and a one-line command (`python -m claim2cad.pipeline
--claim examples/<name>/claim.txt --out examples/<name>`) regenerates
everything. The viewer's example dropdown is a literal listing of this
directory.

**What would change.** With more examples, we'd add a tagging system
(industry, mechanism type, complexity tier). Three is the right number
for v0.1: enough to show variety, not enough to hide a regression.
