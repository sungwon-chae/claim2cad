# Claim2CAD release notes

The condensed per-release story. Full per-phase detail lives in
`PROGRESS.md`; entry-level diffs live in `CHANGELOG.md`.

---

## v1.0.0 — 2026-04-28

The "real patents + Korean + multi-claim + offline demo" release.
Twelve V1-x phases delivered against a $80 LLM-cost cap and finished
under budget.

### Highlights

- **30 examples** ship in the repo and replay offline:
  - 3 hand-crafted synthetic claims (golden robot arm, hinge assembly,
    planetary gear).
  - 25 real expired US mechanical patents (USPC 074, 901, 414, 16).
  - 1 Korean (KIPO/KIPRIS-style) mechanical claim.
  - 1 multi-claim drone (5 claims, hierarchy depth 4).
- **Offline demo path**: `make demo-clean-checkout` produces the full
  3-pane viewer from a fresh clone with **no API key required**. The
  hosted demo replays cached `expected_ir.json` files instead of
  calling an LLM.
- **101 tests** pass. CI runs Python + viewer typecheck on every push.
- **Evaluation harness** (`make eval-stub`) gives precision / recall /
  F1 on component-kind, component-ID, and relation triples plus
  figure-coverage, span-coverage, and CAD-success metrics. Output as
  both JSON and Markdown.

### What's new since v0.1.0

| Phase | Summary |
|---|---|
| V1-0 | Branch hygiene, cost tracker, model router (Opus 4.7 / Sonnet 4.6 / vision Opus 4.7) |
| V1-1 | Real-patent collector (Google Patents direct fetch, 25 patents seeded) |
| V1-2 | Baseline structural validator — 25/25 graded `good` at iteration 0 |
| V1-3 | VLM-based figure parsing (25/25 maps, 8/25 fully resolved, $1.74 of $5 budget) |
| V1-4 | 3-pane viewer + manifest schema 0.2 (figure_map, figure_image, source, tags) |
| V1-5 | Prior-art comparison — bipartite-greedy matcher + LLM disambiguation (4 demo diffs) |
| V1-6 | URDF kinematic export + viewer joint sliders (golden + PUMA) |
| V1-7 | Korean (KIPO) claim support — head-final parser, romanisation table |
| V1-8 | Multi-claim hierarchy ops (`claim_chain`, `filter_ir_to_claim`) + 5-claim drone example + `--filter-claim` CLI |
| V1-9 | Deterministic dimension extractor (EN+KO; values, ranges, comparatives, qualifiers) |
| V1-10 | Hosted-demo readiness — `make demo-clean-checkout`, expected_ir.json everywhere, troubleshooting docs |
| V1-11 | Evaluation harness with JSON+Markdown reports; baseline numbers |

### Known limitations

See the `## Limitations` section of the README. The biggest gaps:

- Extracted dimensions don't yet flow into CAD shape sizes (queued for
  v1.1).
- Stub parser produces no relations (LLM path is needed for full
  fidelity).
- Korean OOV terms slug to `comp_<n>`; vocabulary is opt-in via
  `lang_ko.HEAD_TRANSLATIONS`.

### Migration from v0.1.0

The IR and viewer are backward-compatible. The two API additions are
opt-in:

- `Component.figure_number` / `Component.figure_references` (V1-3) —
  optional, default `None` / `[]`. Existing v0.1.0 IRs still validate.
- `--filter-claim N` and `claim_hierarchy.json` (V1-8) — both opt-in;
  pass `--no-hierarchy` to skip writing the summary.

The CLI gained:

- `--dry-run` — replays `expected_ir.json` next to the input claim.
- `--filter-claim N` — single-claim view (claim N + ancestors).
- `--no-hierarchy` — skip `claim_hierarchy.json`.

### Acknowledgments

Same as v0.1.0 — `build123d`, `text-to-cad` (read-only reference),
`react-three-fiber` + `drei`, OpenRouter. Plus, for v1.0 specifically:

- Google Patents for the 25 expired-patent corpus.
- Anthropic's Claude Sonnet 4.6 (parsing) + Opus 4.7 (vision figure
  labelling, prior-art disambiguation).

---

## v0.1.0 — 2026-04-27

The initial portfolio release. Hand-crafted examples (robot arm, hinge,
planetary gear), two-pane viewer with bidirectional highlighting,
hybrid LLM + rule-based claim parser, pydantic v2 IR with referential
integrity, build123d → STEP/GLB pipeline with GLB node-name
post-processor, 29 tests, CI.

See `CHANGELOG.md` for the full v0.1.0 entry.
