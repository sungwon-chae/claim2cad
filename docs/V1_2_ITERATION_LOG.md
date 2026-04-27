# V1-2 — Iterative Parser Improvement Log

A living, append-only log of every iteration we ran during V1-2. Each
entry records: dataset state, what the validator told us, what we
hypothesised, what we changed, and the resulting eval delta.

---

## Iteration 0 — Baseline (LLM path enabled)

**Dataset:** 25 expired pre-2000 mechanical patents in
`examples/real_patents/`.
**Parser version:** v0.1.0 hybrid parser, with two V1-0 fixes applied:

1. `llm_client._extract_json` strips markdown code fences (`\`\`\`json
   ... \`\`\``) that some OpenRouter-routed providers wrap around the
   response despite `response_format: json_object`.
2. `max_retries` lowered from 3 → 2 (cost discipline; matched parser-
   level retry budget).

**Hypothesis going in:** The LLM will produce valid IR for ≥60 % of
patents straight away. The remainder will fail on schema-validation
issues that are addressable by improved prompts.

**Results:** see the table in
`examples/real_patents/COLLECTION_VALIDATION_REPORT.md` (regenerated
by every run; iteration 0 stays in git via this log's verbatim
copies of the headline numbers).

**Verbatim cost & grade summary at iteration 0 close:**

```
patents=25  good=25  partial=0  fail=0
cost_delta_iteration_0=$2.0201
cost_total_session=$5.127
mean_components_per_patent=13
median_components=13
range_components=5..31
mean_duration=34.0 s
```

**Top observed failure modes:** none. Every patent in the working
set produced a valid IR, a non-empty STEP+GLB pair, and a
claim_map whose count matched the IR's component count. The brief's
stop condition (≥80 % "good") is satisfied on iteration 0.

**Honest caveats** (per the "no fabrication" principle):

- Quality grading is *structural*, not *semantic*. Every `good` rating
  means "the pipeline produced a well-formed IR and a non-empty
  STEP+GLB". It does **not** mean "the geometry visually resembles
  the invention". V1-3 (figure parsing) and V1-13 (figure-aware CAD)
  in the longer brief are the right places to add semantic grading.
- The few-shot example used inside the parser is the
  `golden_robot_arm`, which biases the LLM toward
  link-and-joint-style decompositions. Spot-checks of the gear and
  hinge patents show the LLM still extracts gear-specific
  vocabulary (sun_gear, ring_gear, planet_gear, pintle_pin), so the
  bias is mild but not zero.
- The IR's `kind` field is open-ended (per v0.1.0 schema design).
  The LLM emits some kind strings outside the closed enums declared
  in `ir_schema.py` (e.g. `interposer`, `servo_system`, `axis`). The
  CAD generator falls back to a labelled box for unknown kinds.
  This is intended behaviour; the schema's open kind is what makes
  the system robust to unfamiliar patent vocabulary.

**Decision:** stop at iteration 0. No prompt or rule changes were
needed. Time and cost saved on the four iterations that the brief
budgeted for can be spent on later phases (or on a more-rigorous
*semantic* eval in V1-11 / V1-15 once those phases have reference
truths to compare against).

---

## What would have been iteration 1 — *not run*

If we had chosen to push beyond a structural eval, the experiment we
would run is:

> Pick the 5 patents with the **most idiosyncratic kind strings**
> (i.e., kinds that fall outside the structural / connection /
> functional closed enums). Hand-label what kind they should map to.
> Add an LLM-driven kind-normalisation step after parsing. Re-run.

We log this here as a future starting point rather than executing it,
because it requires hand-labels we haven't generated yet.
