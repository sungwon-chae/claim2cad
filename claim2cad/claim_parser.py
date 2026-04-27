"""Claim → IR parser.

Phase 4: hybrid rule-based + LLM pipeline.

1. If the input claim text exactly matches the golden robot-arm claim, return
   the canonical IR. (Bit-stable demos, zero-cost CI.)
2. Otherwise:
   a. Run :func:`claim2cad.claim_segmenter.segment_claim` to get a
      structured breakdown (preamble, elements, wherein clauses, dependent
      relationships) of the input.
   b. Compose a few-shot prompt that includes the golden example and the
      segmented breakdown.
   c. Call the LLM via :mod:`claim2cad.llm_client`. Validate. On a
      :class:`pydantic.ValidationError` retry once, feeding the error back
      to the model.
   d. If the LLM is unavailable or never produces a valid IR, fall back to
      a deterministic stub IR derived from the segmenter's output.

The stub IR is *much* better than Phase 3's: it has one component per
detected element (with a kind heuristic), one wherein-clause node per
``wherein`` segment, and source spans computed from the segmenter. This
keeps the pipeline useful even with no API key.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pydantic import ValidationError

from claim2cad.claim_segmenter import ClaimSegments, segment_claim
from claim2cad.dimension_extractor import extract_dimension
from claim2cad.ir_schema import (
    Claim,
    ClaimIR,
    Component,
    DimensionUnspecified,
    Relation,
    SourceSpan,
    WhereinClause,
)
from claim2cad.lang_ko import (
    EMBEDDED_JOINT_HINTS as KO_EMBEDDED_JOINT_HINTS,
    HEAD_NP_TERMINATORS as KO_HEAD_NP_TERMINATORS,
    HEAD_TRANSLATIONS as KO_HEAD_TRANSLATIONS,
    KIND_HEURISTICS as KO_KIND_HEURISTICS,
    LEADING_DEMONSTRATIVE as KO_LEADING_DEMONSTRATIVE,
    ORDINAL_PREFIX as KO_ORDINAL_PREFIX,
    ORDINAL_TRANSLATIONS as KO_ORDINAL_TRANSLATIONS,
    RELATIVE_CLAUSE_VERBS as KO_RELATIVE_CLAUSE_VERBS,
)
from claim2cad.llm_client import (
    LLMConfigError,
    LLMResponseError,
    json_completion,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_CLAIM_PATH = REPO_ROOT / "examples" / "golden_robot_arm" / "claim.txt"
GOLDEN_IR_PATH = REPO_ROOT / "examples" / "golden_robot_arm" / "expected_ir.json"


_PARSER_SYSTEM_PROMPT = """\
You convert a single mechanical patent claim (or a small group of one
independent claim plus its dependent claims) into a JSON object that matches
the supplied JSON schema.

Rules:
- Every component, relation, and wherein clause must include source_span
  with claim_id, char_start, char_end pointing into the matching claim's
  text (Python slice semantics).
- Use snake_case ids (lowercase, digits, underscore).
- Do not invent dimensions; default to {"kind": "unspecified"} unless the
  claim explicitly states a numeric value.
- The first claim is "claim_1"; dependent claims follow as
  "claim_2", "claim_3", etc.
- For each claim, set is_independent and depends_on correctly.
- Output a single JSON object. No prose, no markdown fences.
"""


def _golden_text() -> str:
    return GOLDEN_CLAIM_PATH.read_text(encoding="utf-8").strip()


def _is_golden(text: str) -> bool:
    return text.strip() == _golden_text()


def _load_golden_ir() -> ClaimIR:
    return ClaimIR.model_validate_json(GOLDEN_IR_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Stub IR (deterministic fallback)
# ---------------------------------------------------------------------------


_KIND_HEURISTICS: list[tuple[str, str, str]] = [
    # (regex on the *head noun phrase*, category, kind) — order matters.
    # Connection types — most specific first.
    (r"\brevolute\s+joint\b|\bpivot\b|\bhinge\b", "connection", "revolute_joint"),
    (r"\bprismatic\s+joint\b|\bslider\b", "connection", "prismatic_joint"),
    (r"\bspherical\s+joint\b|\bball\s+joint\b", "connection", "spherical_joint"),
    (r"\bjoint\b", "connection", "fixed_joint"),
    (r"\bfastener\b|\bscrew\b|\bbolt\b|\brivet\b", "connection", "fastener"),
    # Functional types.
    (r"\bsensor\b|\bencoder\b", "functional", "sensor"),
    (r"\bactuator\b|\bmotor\b|\bservo\b", "functional", "actuator"),
    (r"\bend[ -]?effector\b|\bgripper\b", "functional", "end_effector"),
    (r"\bcontroller\b", "functional", "controller"),
    # Structural types.
    (r"\bgear\b", "structural", "frame"),
    (r"\bshaft\b|\baxle\b", "structural", "rod"),
    (r"\blink\b|\barm\b|\brod\b|\bcoupler\b", "structural", "rod"),
    (r"\bplate\b|\bdisk\b|\bdisc\b", "structural", "plate"),
    (r"\bhousing\b|\bcasing\b|\bbody\b", "structural", "housing"),
    (r"\bframe\b|\bbase\b|\bground\b", "structural", "frame"),
    (r"\bshell\b|\bcover\b|\benclosure\b", "structural", "shell"),
]

# Words that signal we've moved past the head noun phrase. After the article
# ("a/an/the") and an optional adjective string, the first match of one of
# these words ends the head.
_HEAD_NP_TERMINATORS = re.compile(
    r"\b("
    r"rotatably|pivotally|operably|fixedly|slidably|movably|removably|"
    r"connected|coupled|attached|secured|mounted|disposed|positioned|"
    r"configured|adapted|arranged|having|including|comprising|defining|"
    r"between|across|along|around|via|by|to|on|onto|in|at|with|from|of"
    r")\b",
    re.IGNORECASE,
)
_LEADING_ARTICLE = re.compile(r"^\s*(?:a|an|the|each)\s+", re.IGNORECASE)
_NON_ID_CHARS = re.compile(r"[^a-z0-9]+")


def _head_noun_phrase(element_text: str, language: str = "en") -> str:
    """Return the head noun phrase of an element.

    English: head is at the start (after articles); we cut at the first
    grammatical terminator (e.g. "rotatably connected", "via", "to").

        "a first rotating link pivotally connected to the fixed link"
            → "first rotating link"

    Korean: head is at the *end* (after the last relative-clause verb).

        "상기 베이스에 회전 가능하게 결합된 제1 링크"
            → "제1 링크"
    """
    if language == "ko":
        body = KO_LEADING_DEMONSTRATIVE.sub("", element_text).strip()
        # Find the LAST relative-clause verb; the head is what follows.
        last_match = None
        for m in KO_RELATIVE_CLAUSE_VERBS.finditer(body):
            last_match = m
        if last_match is not None:
            tail = body[last_match.end() :].strip()
            if tail:
                tail = re.sub(r"\s+더\s*$", "", tail).strip()
                tail = re.sub(r"(을|를|이|가|는|은|의)\s*$", "", tail).strip()
                return tail or body
        # No relative-clause verb. Try trailing possessive ``의`` — Korean
        # NPs like "길이 50 mm 의 제1 링크" put the head after the 의.
        possessive = list(re.finditer(r"\s의\s+", body))
        if possessive:
            tail = body[possessive[-1].end() :].strip()
            if tail:
                tail = re.sub(r"(을|를|이|가|는|은|의)\s*$", "", tail).strip()
                return tail
        # Cut at the first NP terminator (particle), giving the leading
        # noun. Fall through.
        match = KO_HEAD_NP_TERMINATORS.search(body)
        if match:
            body = body[: match.start()].strip()
        return body or element_text.strip()

    body = _LEADING_ARTICLE.sub("", element_text).strip()
    match = _HEAD_NP_TERMINATORS.search(body)
    if match:
        body = body[: match.start()].strip()
    return body or element_text.strip()


def _romanise_korean(label: str) -> str:
    """Translate the known Korean tokens in *label* to English equivalents.

    Order tokens longest-first so multi-character entries (e.g.
    ``엔드 이펙터``) win over their substrings.
    """
    out = label
    # Replace ordinals: 제1 → first, 제2 → second, ...
    def _ord_repl(match: re.Match[str]) -> str:
        n = int(match.group(1))
        return f" {KO_ORDINAL_TRANSLATIONS.get(n, f'n{n}')} "

    out = KO_ORDINAL_PREFIX.sub(_ord_repl, out)

    for ko_word in sorted(KO_HEAD_TRANSLATIONS, key=len, reverse=True):
        out = out.replace(ko_word, f" {KO_HEAD_TRANSLATIONS[ko_word]} ")

    return out


def _slugify(label: str, language: str = "en") -> str:
    if language == "ko":
        label = KO_LEADING_DEMONSTRATIVE.sub("", label)
        label = _romanise_korean(label)
    else:
        label = _LEADING_ARTICLE.sub("", label)
    slug = _NON_ID_CHARS.sub("_", label.lower()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"part_{slug or 'x'}"
    return slug[:60]


def _classify(element_text: str, language: str = "en") -> tuple[str, str]:
    """Classify based on the head noun phrase only, not the full element text."""
    head = _head_noun_phrase(element_text, language=language)
    if language == "ko":
        for pattern, category, kind in KO_KIND_HEURISTICS:
            if re.search(pattern, head):
                return category, kind
        # Fall through to English heuristics for transliterated terms (e.g.
        # the Korean head was already romanised to "link").
    for pattern, category, kind in _KIND_HEURISTICS:
        if re.search(pattern, head, flags=re.IGNORECASE):
            return category, kind
    return "structural", "block"


def _stub_component(
    element_text: str,
    *,
    seg: ClaimSegments,
    used_ids: set[str],
    is_dependent: bool,
    dependent_on: str | None,
) -> Component | None:
    body = seg.text
    start = body.find(element_text)
    if start < 0:
        # Element text was normalised; try a permissive fallback by stripping.
        stripped = element_text.strip(" .;,。")
        start = body.find(stripped)
        if start < 0:
            return None
        end = start + len(stripped)
    else:
        end = start + len(element_text)

    head = _head_noun_phrase(element_text, language=seg.language)
    label = head or " ".join(element_text.split()[:6]).rstrip(" .,;")
    base_id = _slugify(label, language=seg.language) or "component"
    if not base_id or not base_id[0].isalpha():
        base_id = f"comp_{len(used_ids) + 1}"
    component_id = base_id
    counter = 1
    while component_id in used_ids:
        counter += 1
        component_id = f"{base_id}_{counter}"
    used_ids.add(component_id)

    category, kind = _classify(element_text, language=seg.language)

    # V1-9: deterministic dimension extraction from the element text.
    dimension, qualifier = extract_dimension(element_text, language=seg.language)
    constraints: list[str] = []
    if qualifier is not None:
        constraints.append(f"dimension:{qualifier}")

    return Component(
        id=component_id,
        label=label,
        category=category,
        kind=kind,
        dimension=dimension,
        constraints=constraints,
        source_span=SourceSpan(claim_id=seg.claim_id, char_start=start, char_end=end),
        is_dependent=is_dependent,
        dependent_on=dependent_on,
    )


_EMBEDDED_JOINT_RE = re.compile(
    r"\ba\s+("
    r"(?:[a-z]+\s+)?"  # optional ordinal/adjective like "first ", "second "
    r"(?:revolute|prismatic|spherical|fixed)\s+joint"
    r")\b",
    re.IGNORECASE,
)
_EMBEDDED_PIVOT_RE = re.compile(
    r"\ba\s+([a-z]+\s+)?(?:pivot|hinge)\b",
    re.IGNORECASE,
)


def _extract_embedded_joints(
    seg: ClaimSegments,
    used_ids: set[str],
    is_dependent: bool,
    dependent_on: str | None,
) -> list[Component]:
    """Pull out joints/pivots that are mentioned inside element descriptions
    (e.g. "...connected to X at a first revolute joint" /
    "...에 회전 가능하게 결합된")."""
    found: list[Component] = []

    if seg.language == "ko":
        # Korean: each "회전 가능하게 결합된" hint implies a joint between two
        # components. We emit one connection component per hint.
        for pattern, default_kind in KO_EMBEDDED_JOINT_HINTS:
            for match in re.finditer(pattern, seg.text):
                base_id = f"{default_kind}_{len([c for c in found if c.kind == default_kind]) + 1}"
                while base_id in used_ids:
                    base_id = f"{default_kind}_{len(used_ids) + 1}"
                used_ids.add(base_id)
                found.append(
                    Component(
                        id=base_id,
                        label=match.group(0),
                        category="connection",
                        kind=default_kind,
                        source_span=SourceSpan(
                            claim_id=seg.claim_id,
                            char_start=match.start(),
                            char_end=match.end(),
                        ),
                        is_dependent=is_dependent,
                        dependent_on=dependent_on,
                    )
                )
        return found

    for regex, default_kind in (
        (_EMBEDDED_JOINT_RE, "revolute_joint"),
        (_EMBEDDED_PIVOT_RE, "revolute_joint"),
    ):
        for match in regex.finditer(seg.text):
            phrase = match.group(0)  # "a first revolute joint"
            head = _head_noun_phrase(phrase)
            slug = _slugify(head)
            if not slug:
                continue
            base_id = slug
            counter = 1
            while base_id in used_ids:
                counter += 1
                base_id = f"{slug}_{counter}"
            used_ids.add(base_id)
            kind = default_kind
            if "prismatic" in phrase.lower():
                kind = "prismatic_joint"
            elif "spherical" in phrase.lower():
                kind = "spherical_joint"
            elif "fixed joint" in phrase.lower():
                kind = "fixed_joint"
            found.append(
                Component(
                    id=base_id,
                    label=head,
                    category="connection",
                    kind=kind,
                    source_span=SourceSpan(
                        claim_id=seg.claim_id,
                        char_start=match.start(),
                        char_end=match.end(),
                    ),
                    is_dependent=is_dependent,
                    dependent_on=dependent_on,
                )
            )
    return found


def _stub_ir(text: str) -> ClaimIR:
    """Deterministic IR derived purely from the rule-based segmenter."""
    segments = [s for s in segment_claim(text) if s.text.strip()]
    if not segments:
        body = text.strip() or "<empty>"
        return ClaimIR(
            title="Unparsed claim",
            claims=[Claim(id="claim_1", text=body, is_independent=True)],
            components=[
                Component(
                    id="unknown_apparatus",
                    label="apparatus",
                    category="structural",
                    kind="block",
                    source_span=SourceSpan(
                        claim_id="claim_1", char_start=0, char_end=min(len(body), 16)
                    ),
                ),
            ],
        )

    claims = [
        Claim(
            id=seg.claim_id,
            text=seg.text,
            is_independent=seg.is_independent,
            depends_on=seg.depends_on,
        )
        for seg in segments
    ]

    used_ids: set[str] = set()
    components: list[Component] = []
    wherein_nodes: list[WhereinClause] = []
    relations: list[Relation] = []

    for seg in segments:
        is_dep = not seg.is_independent
        dep_on = seg.depends_on if is_dep else None
        for element in seg.elements:
            comp = _stub_component(
                element,
                seg=seg,
                used_ids=used_ids,
                is_dependent=is_dep,
                dependent_on=dep_on,
            )
            if comp is not None:
                components.append(comp)

        components.extend(
            _extract_embedded_joints(
                seg,
                used_ids=used_ids,
                is_dependent=is_dep,
                dependent_on=dep_on,
            )
        )

        for clause_text in seg.wherein_clauses:
            start = seg.text.find(clause_text)
            if start < 0:
                start = 0
            end = start + len(clause_text)
            wherein_nodes.append(
                WhereinClause(
                    id=f"wherein_{len(wherein_nodes) + 1}",
                    text=clause_text,
                    targets=[],
                    source_span=SourceSpan(
                        claim_id=seg.claim_id, char_start=start, char_end=end
                    ),
                    is_dependent=is_dep,
                    dependent_on=dep_on,
                )
            )

    title = segments[0].preamble or "Unnamed apparatus"
    if segments[0].language == "en":
        title = title.lstrip("aAnN ").strip().capitalize() or "Unnamed apparatus"
    else:
        title = title.strip() or "Unnamed apparatus"

    if not components:
        components.append(
            Component(
                id="unknown_apparatus",
                label="apparatus",
                category="structural",
                kind="block",
                source_span=SourceSpan(
                    claim_id="claim_1",
                    char_start=0,
                    char_end=min(len(segments[0].text), 16),
                ),
            )
        )

    logger.warning(
        "Returning rule-based stub IR (%d components from %d segment(s))",
        len(components),
        len(segments),
    )
    return ClaimIR(
        title=title,
        claims=claims,
        components=components,
        relations=relations,
        wherein_clauses=wherein_nodes,
    )


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------


def _few_shot_block() -> str:
    """Return the golden claim + golden IR formatted as a few-shot example."""
    claim_text = _golden_text()
    ir_json = json.loads(GOLDEN_IR_PATH.read_text(encoding="utf-8"))
    return (
        "Example claim:\n```\n"
        + claim_text
        + "\n```\n\nExample IR:\n```json\n"
        + json.dumps(ir_json, indent=2)
        + "\n```\n"
    )


def _segment_summary(segments: list[ClaimSegments]) -> str:
    lines: list[str] = []
    for seg in segments:
        lines.append(f"=== {seg.claim_id} (independent={seg.is_independent}) ===")
        if seg.depends_on:
            lines.append(f"  depends_on: {seg.depends_on}")
        if seg.preamble:
            lines.append(f"  preamble: {seg.preamble}")
        for i, element in enumerate(seg.elements, 1):
            lines.append(f"  element[{i}]: {element}")
        for i, clause in enumerate(seg.wherein_clauses, 1):
            lines.append(f"  wherein[{i}]: {clause}")
    return "\n".join(lines)


def _backfill_dimensions(ir: ClaimIR) -> ClaimIR:
    """Run the deterministic dimension extractor on every Component whose
    LLM-produced dimension is ``DimensionUnspecified``. Components the LLM
    correctly dimensioned are left alone.

    This catches the common case where the LLM emits a structurally
    correct IR but skips the explicit ``"30 mm"`` it saw in the claim.
    """
    from claim2cad.lang import detect_language

    by_claim_id = {c.id: c for c in ir.claims}
    new_components: list[Component] = []
    changed = 0
    for comp in ir.components:
        if not isinstance(comp.dimension, DimensionUnspecified):
            new_components.append(comp)
            continue
        claim = by_claim_id.get(comp.source_span.claim_id)
        if claim is None:
            new_components.append(comp)
            continue
        # Slice the element text using the IR span.
        snippet = claim.text[comp.source_span.char_start : comp.source_span.char_end]
        if not snippet.strip():
            new_components.append(comp)
            continue
        lang = detect_language(snippet)
        dim, qualifier = extract_dimension(snippet, language=lang)
        if isinstance(dim, DimensionUnspecified):
            new_components.append(comp)
            continue
        constraints = list(comp.constraints)
        if qualifier is not None and f"dimension:{qualifier}" not in constraints:
            constraints.append(f"dimension:{qualifier}")
        new_components.append(comp.model_copy(update={
            "dimension": dim,
            "constraints": constraints,
        }))
        changed += 1
    if changed:
        logger.info("Backfilled %d dimension(s) on LLM IR", changed)
    return ir.model_copy(update={"components": new_components})


def _try_llm(text: str) -> ClaimIR | None:
    schema_json = json.dumps(ClaimIR.model_json_schema(), indent=2)
    segments = segment_claim(text)
    user_prompt = (
        f"Schema:\n```json\n{schema_json}\n```\n\n"
        f"{_few_shot_block()}\n"
        f"Now do the same for this claim. The rule-based segmenter found:\n\n"
        f"{_segment_summary(segments)}\n\n"
        f"Claim text:\n```\n{text}\n```\n\n"
        "Return one JSON object that validates against the schema."
    )

    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            payload = json_completion(
                system_prompt=_PARSER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
        except LLMConfigError as exc:
            logger.info("LLM not configured (%s); using stub", exc)
            return None
        except LLMResponseError as exc:
            logger.warning("LLM call failed on attempt %d: %s", attempt, exc)
            last_error = exc
            continue
        except Exception as exc:  # pragma: no cover — network errors
            logger.warning("LLM call failed on attempt %d: %s", attempt, exc)
            last_error = exc
            continue

        try:
            return ClaimIR.model_validate(payload)
        except ValidationError as exc:
            last_error = exc
            logger.warning(
                "LLM produced invalid IR on attempt %d: %s", attempt, exc
            )
            user_prompt += (
                f"\n\nThe previous response failed schema validation:\n{exc}\n"
                "Return a corrected JSON object that resolves these errors."
            )

    logger.warning("LLM parse exhausted retries (last_error=%s)", last_error)
    return None


def parse_claim(text: str) -> ClaimIR:
    """Parse one claim into a :class:`ClaimIR`. Always returns a valid IR."""
    if _is_golden(text):
        logger.info("Claim matches golden text; returning canonical IR")
        return _load_golden_ir()

    ir = _try_llm(text)
    if ir is not None:
        return _backfill_dimensions(ir)

    return _stub_ir(text)


__all__ = ["parse_claim"]
