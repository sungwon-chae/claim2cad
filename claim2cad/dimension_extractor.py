"""Deterministic dimension extractor (V1-9).

Patent claims occasionally include explicit dimensions (``"a shaft of
length 30 mm"``, ``"두께 5 mm 이상"``) or comparative phrases (``"longer
than the first link"``, ``"제1 링크보다 긴"``). This module extracts both
into the IR's :class:`Dimension` union *deterministically*, so the stub
path can populate dimensions without an LLM and the LLM path can be
double-checked offline.

Design rules (V1-9 brief):

* Never hallucinate precision. If the claim says ``"approximately 30
  mm"`` we keep the number 30 *and* the relative descriptor "approximate"
  in the constraints field. We do *not* synthesise a tolerance.
* Heuristic defaults belong in :mod:`claim2cad.ir_to_cad` (where shapes
  are placed), not here. This module returns ``DimensionUnspecified``
  when the text gives no explicit hint.
* Korean and English share a single API (``language`` argument).

Public API: :func:`extract_dimension(text, *, language="en")` returning
a :class:`Dimension`.
"""
from __future__ import annotations

import re
from typing import Optional

from claim2cad.ir_schema import (
    Dimension,
    DimensionRelative,
    DimensionUnspecified,
    DimensionValue,
)

# ---------------------------------------------------------------------------
# Unit normalisation
# ---------------------------------------------------------------------------

# Map textual unit tokens (English & Korean) to canonical IR units.
_UNIT_NORMALISERS = {
    "mm": "mm",
    "millimeter": "mm",
    "millimeters": "mm",
    "millimetre": "mm",
    "millimetres": "mm",
    "밀리미터": "mm",
    "cm": "cm",
    "centimeter": "cm",
    "centimeters": "cm",
    "centimetre": "cm",
    "centimetres": "cm",
    "센티미터": "cm",
    "m": "m",
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
    "미터": "m",
    "in": "in",
    "inch": "in",
    "inches": "in",
    "ft": "ft",
    "foot": "ft",
    "feet": "ft",
    "deg": "deg",
    "degree": "deg",
    "degrees": "deg",
    "도": "deg",
}


_UNIT_ALTERNATION = "|".join(
    re.escape(u) for u in sorted(_UNIT_NORMALISERS, key=len, reverse=True)
)


# ---------------------------------------------------------------------------
# English patterns
# ---------------------------------------------------------------------------

# "30 mm", "30.5 cm", "0.5 in", "10mm" (no space)
_EN_VALUE_RE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*(" + _UNIT_ALTERNATION + r")(?![\w])",
    re.IGNORECASE,
)

# "approximately 30 mm", "about 30 mm", "around 30 mm", "~30 mm"
_EN_APPROX_RE = re.compile(
    r"(?:approximately|approx\.?|about|around|~)\s*(\d+(?:\.\d+)?)\s*("
    + _UNIT_ALTERNATION
    + r")",
    re.IGNORECASE,
)

# "between 10 and 20 mm" — "and" separator, only allowed after "between".
_EN_RANGE_BETWEEN_RE = re.compile(
    r"between\s+(\d+(?:\.\d+)?)\s+and\s+(\d+(?:\.\d+)?)\s*("
    + _UNIT_ALTERNATION
    + r")",
    re.IGNORECASE,
)
# "10 to 20 mm", "10-20 mm", "from 10 to 20 mm"
_EN_RANGE_RE = re.compile(
    r"(?:from\s+)?(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*("
    + _UNIT_ALTERNATION
    + r")",
    re.IGNORECASE,
)

# "at least 10 mm", "no less than 10 mm", "minimum of 10 mm"
_EN_MIN_RE = re.compile(
    r"(?:at\s+least|no\s+less\s+than|minimum\s+of|≥)\s*(\d+(?:\.\d+)?)\s*("
    + _UNIT_ALTERNATION
    + r")",
    re.IGNORECASE,
)

# "no more than 10 mm", "at most 10 mm", "up to 10 mm"
_EN_MAX_RE = re.compile(
    r"(?:at\s+most|no\s+more\s+than|maximum\s+of|up\s+to|≤)\s*(\d+(?:\.\d+)?)\s*("
    + _UNIT_ALTERNATION
    + r")",
    re.IGNORECASE,
)

# Comparative: "longer than the first link", "twice the length of the base",
# "shorter than the second arm", "equal in length to the first link"
_EN_COMPARATIVE_RE = re.compile(
    r"(?:"
    r"(?:longer|shorter|larger|smaller|wider|narrower|thicker|thinner|"
    r"taller|deeper)\s+than\s+(?:the\s+)?[\w\s]+?|"
    r"twice\s+(?:the\s+)?(?:length|width|diameter|radius)\s+of\s+(?:the\s+)?[\w\s]+?|"
    r"half\s+(?:the\s+)?(?:length|width|diameter|radius)\s+of\s+(?:the\s+)?[\w\s]+?|"
    r"(?:equal|comparable)\s+(?:in\s+\w+\s+)?to\s+(?:the\s+)?[\w\s]+?|"
    r"(?:as\s+long\s+as|as\s+wide\s+as|as\s+tall\s+as)\s+(?:the\s+)?[\w\s]+?"
    r")(?:\s+(?:link|arm|base|frame|shaft|component|element)|[\.;,])",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Korean patterns
# ---------------------------------------------------------------------------

# "30 mm", "30.5 cm", "5 미터" — same as English number+unit, but allow Korean
# unit words.
_KO_VALUE_RE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*(" + _UNIT_ALTERNATION + r")(?![\w])",
    re.IGNORECASE,
)

# "약 30 mm" (approximately), "대략 30 mm", "거의 30 mm"
_KO_APPROX_RE = re.compile(
    r"(?:약|대략|거의|~)\s*(\d+(?:\.\d+)?)\s*(" + _UNIT_ALTERNATION + r")",
    re.IGNORECASE,
)

# "10 내지 20 mm", "10~20 mm", "10에서 20 mm"
_KO_RANGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:내지|~|-|에서)\s*(\d+(?:\.\d+)?)\s*("
    + _UNIT_ALTERNATION
    + r")",
    re.IGNORECASE,
)

# "10 mm 이상" (at least), "10 mm 초과" (greater than)
_KO_MIN_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(" + _UNIT_ALTERNATION + r")\s*(?:이상|초과)",
    re.IGNORECASE,
)

# "10 mm 이하" (at most), "10 mm 미만" (less than)
_KO_MAX_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(" + _UNIT_ALTERNATION + r")\s*(?:이하|미만)",
    re.IGNORECASE,
)

# Comparative: "제1 링크보다 긴" (longer than the first link), "X보다 짧은",
# "X와 동일한"
_KO_COMPARATIVE_RE = re.compile(
    r"[^\s]+보다\s+(?:더\s+)?(?:긴|짧은|넓은|좁은|두꺼운|얇은|큰|작은)|"
    r"[^\s]+와\s+동일한|"
    r"[^\s]+와\s+같은",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _normalise_unit(token: str) -> str:
    return _UNIT_NORMALISERS.get(token.lower(), token.lower())


def _build_value(value_str: str, unit_token: str) -> DimensionValue:
    return DimensionValue(value=float(value_str), unit=_normalise_unit(unit_token))


def extract_dimension(
    text: str, *, language: str = "en"
) -> tuple[Dimension, Optional[str]]:
    """Return ``(dimension, qualifier)`` for the given element text.

    The ``qualifier`` field is a short descriptor (e.g. ``"approximate"``,
    ``"minimum"``, ``"maximum"``, ``"range"``) that the parser can stash
    into ``Component.constraints`` so the round-trip is loss-less. When
    no qualifier applies, returns ``None``.

    Resolution order (most specific first):

    1. Range (``"10 to 20 mm"``)
    2. Approximate (``"approximately 30 mm"``)
    3. At-least / at-most (``"at least 10 mm"``)
    4. Plain numeric value (``"30 mm"``)
    5. Comparative (``"longer than the base"``)
    6. ``DimensionUnspecified``
    """
    if not text or not text.strip():
        return DimensionUnspecified(), None

    if language == "ko":
        # Range first.
        m = _KO_RANGE_RE.search(text)
        if m:
            lo, hi, unit = float(m.group(1)), float(m.group(2)), m.group(3)
            return _build_value(str((lo + hi) / 2.0), unit), f"range:{lo}-{hi}"
        m = _KO_APPROX_RE.search(text)
        if m:
            return _build_value(m.group(1), m.group(2)), "approximate"
        m = _KO_MIN_RE.search(text)
        if m:
            return _build_value(m.group(1), m.group(2)), "minimum"
        m = _KO_MAX_RE.search(text)
        if m:
            return _build_value(m.group(1), m.group(2)), "maximum"
        m = _KO_VALUE_RE.search(text)
        if m:
            return _build_value(m.group(1), m.group(2)), None
        m = _KO_COMPARATIVE_RE.search(text)
        if m:
            phrase = m.group(0).strip(" .,;。")
            return DimensionRelative(description=phrase), "comparative"
        return DimensionUnspecified(), None

    # English (default).
    m = _EN_RANGE_BETWEEN_RE.search(text)
    if m:
        lo, hi, unit = float(m.group(1)), float(m.group(2)), m.group(3)
        return _build_value(str((lo + hi) / 2.0), unit), f"range:{lo}-{hi}"
    m = _EN_RANGE_RE.search(text)
    if m:
        lo, hi, unit = float(m.group(1)), float(m.group(2)), m.group(3)
        return _build_value(str((lo + hi) / 2.0), unit), f"range:{lo}-{hi}"
    m = _EN_APPROX_RE.search(text)
    if m:
        return _build_value(m.group(1), m.group(2)), "approximate"
    m = _EN_MIN_RE.search(text)
    if m:
        return _build_value(m.group(1), m.group(2)), "minimum"
    m = _EN_MAX_RE.search(text)
    if m:
        return _build_value(m.group(1), m.group(2)), "maximum"
    m = _EN_VALUE_RE.search(text)
    if m:
        return _build_value(m.group(1), m.group(2)), None
    m = _EN_COMPARATIVE_RE.search(text)
    if m:
        phrase = m.group(0).strip(" .,;")
        return DimensionRelative(description=phrase), "comparative"
    return DimensionUnspecified(), None


__all__ = ["extract_dimension"]
