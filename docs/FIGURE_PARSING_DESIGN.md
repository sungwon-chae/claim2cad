# V1-3 — Figure Parsing Design

## Goal

Stamp every IR `Component` with a `figure_number` field whose value is the
numeric label visible on the patent's drawing. Adds optional
`figure_references[*].bbox` for the viewer's hotspot overlays.

## Why this is non-trivial

The original v1.0 brief assumed claim-1 text contains inline numbered
references like `"a base 10"`. **Empirically, this is wrong for our
dataset.** Across all 25 collected patents in `examples/real_patents/`,
**zero** had inline numbered references in claim 1. Only two had
parenthesised numbers, mostly figure-name references rather than
component pointers.

This matches a known characteristic of US patent practice:

- The **specification** describes components by reference to the figures
  with numbered callouts.
- The **claims** describe the same components but typically *omit* the
  figure numbers, since claim scope shouldn't depend on how the figure
  was drawn.

So matching components to figure numbers can't be done from the claim
text alone — the figure itself is the only place the numbers appear.

## Pipeline

```mermaid
flowchart LR
    A[claim.txt] -->|regex| B[NumberedPhrase[]]
    C[figure_1.png] -->|VLM Opus 4.7| D[VLMLabel[] = {number, description, bbox}]
    E[claim_ir.json] -->|component labels| F[Pass A: phrase match]
    D --> F
    B --> F
    F -->|unmatched| G[Pass B: rule-based VLM-desc match]
    G -->|unmatched| H[Pass C: LLM rematch Sonnet 4.6]
    F & G & H --> I[component_to_number dict]
    I --> J[figure_map.json]
    I -->|merge| K[claim_ir.json with figure_number stamps]
    I -->|mirror| L[claim_map.json with figure_number]
```

### Pass A — Numbered phrases from claim text

`extract_numbered_phrases(claim_text)` runs a single regex looking for
`<noun phrase> <1-4 digit number>` patterns, with article and parenthesis
variants. For our 25-patent dataset this yields zero hits, but it stays
in the pipeline because it's free and *will* matter for older / European
patents where the convention differs.

### Pass B — Rule-based VLM description match

`_best_vlm_label_for(component, vlm_labels)`:

- `SequenceMatcher` ratio between `component.label` and
  `vlm_label.description`
- Substring boost (`label in description` or vice versa → 0.85 floor)
- Word-overlap boost (3-letter-or-longer words; each shared word adds
  0.15)
- Threshold 0.55

Catches obvious cases like:
- IR `housing` ↔ VLM `{description: "housing", number: "10"}`
- IR `first ring gear` ↔ VLM `{description: "ring gear", number: "18"}`

### Pass C — LLM rematch (Sonnet 4.6)

`llm_rematch(unmapped_components, vlm_labels)` sends both lists to a
text-only Sonnet call:

```
Components: [{"id": "first_planet_pinion", "label": "first planet pinion", "kind": "rod"}, ...]
Figure labels: [{"number": "32", "description": "planet gear"}, ...]
Return: {"mappings": [{"component_id": "...", "number": "..."}, ...]}
```

This handles ambiguous cases where Pass B can't decide:

- Three IR components labelled `first/second/third planet pinion`, all
  matching VLM `gear` labels (#32, #42, #52). Pass B picks the first
  greedily; Pass C reasons globally and assigns each component to a
  distinct number.
- Components whose claim labels are abstract (e.g.
  `planet_carrier_means`) but whose figure equivalent is concrete
  (`carrier`).

Cost: ~$0.005 per patent (Sonnet, ~2K tokens round-trip). Skipped when
2 or fewer components remain unmapped.

## VLM prompt (current)

```
SYSTEM:
You are a patent-figure analyser. Given an image of a US-patent figure,
return a single JSON object describing every numbered component label
visible on the drawing.

Rules:
- Only return labels that are explicitly drawn on the figure with a number
  (1-4 digits) typically connected to a part by a leadline.
- Skip figure titles, axis labels, dimension callouts, and equation
  numbers.
- "approximate_position" is an array [x, y] in normalised image
  coordinates (0..1, with origin at top-left).
- "bbox" (optional) is [x, y, w, h] in the same coordinates.
- Output exactly one JSON object. No prose, no markdown fences.

USER:
Return JSON of the form:
{"labels": [{"number": "10", "description": "rectangular base", ...}, ...]}
```

Model: `anthropic/claude-opus-4.7` via OpenRouter (override with
`OPENROUTER_VISION_MODEL`).

## Observed failure modes

| Mode | Frequency | Example | Mitigation |
|---|---|---|---|
| Claim has no inline figure numbers | 25/25 | All patents | Pass B + Pass C compensate |
| Figure has very generic labels (gear/element/bearing × N) | ~5 patents | US4575297A 31 IR comps × 30 generic VLM labels | Partial mapping (~22%); LLM rematch pushes coverage but can't disambiguate identical descriptions |
| Figure quality poor (low DPI, complex schematic) | ~3 patents | US5239246A — VLM returned only 2 labels | Mapping rate plummets; figure may need a different page |
| Component label too abstract ("means for X") | varies | "planet_carrier_means" | LLM rematch sometimes misclassifies these as the closest concrete part |

## Results on 25 real patents

```
total                       = 25
with_vlm_labels             = 25 / 25 (100%)
with_at_least_one_mapping   = 23 / 25 (92%)
with_full_mapping           =  8 / 25 (32%)
mean coverage across all    = ~58%
```

Brief's targets:
- ≥12 with figure_map.json: ✅ (25/25)
- ≥5 with full mapping: ✅ (8/25)
- VLM cost <$5: ✅ ($1.74 — vision $1.56 + rematch $0.18)

## When the labels disagree with claim text

VLM labels are *figure-truth*; claim labels are *claim-truth*. They can
diverge in three legitimate ways:

1. **Synonyms.** Claim says "first link", figure says "upper arm". The
   LLM rematch handles these because it can read both lists.
2. **Aggregation.** Claim says "drive assembly", figure shows it as 5
   numbered sub-components. We currently map the assembly to whichever
   number the LLM picks (often the highest-level one). A future
   `figure_references[]` extension could attach multiple numbers per
   component.
3. **Specification-only parts.** A figure may show parts (gaskets,
   leadwires) that the claim never mentions. We discard these silently.

When in doubt, trust the IR (claim-truth). The figure_map only
*decorates* the IR; it never overrides component identity or
relationships.

## Future work (V1-13: figure-aware CAD generation)

The `figure_map.json` produced here is the input for V1-13:

- Use `bbox` data to estimate component aspect ratios.
- Use spatial proximity in the figure to refine `attached_to` relations.
- Use multiple figures (figure_2, figure_3) jointly when figure_1 is
  ambiguous — currently we only call the VLM on figure_1.
