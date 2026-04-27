"""Language detection for patent claims.

V1-7: Korean (KIPRIS-style) claims need different segmentation rules and a
language hint passed to the LLM. Detection is deliberately tiny — we only
distinguish "ko" vs "en" and bail to "en" by default. A Hangul Unicode
block check (AC00–D7A3) is enough to classify the corpus we care about
without pulling in langdetect / fasttext.
"""
from __future__ import annotations

from typing import Literal

Language = Literal["en", "ko"]

# Hangul syllables block (most common Korean characters).
_HANGUL_RANGE = (0xAC00, 0xD7A3)
# Hangul jamo block (Korean letters in isolation).
_JAMO_RANGE = (0x1100, 0x11FF)


def _is_hangul(ch: str) -> bool:
    cp = ord(ch)
    return _HANGUL_RANGE[0] <= cp <= _HANGUL_RANGE[1] or _JAMO_RANGE[0] <= cp <= _JAMO_RANGE[1]


def detect_language(text: str) -> Language:
    """Return ``"ko"`` if the text is meaningfully Korean, else ``"en"``.

    Heuristic: ≥10 % Hangul characters out of all letters. Patent claims
    can mention English part numbers or Latin abbreviations even in Korean,
    so we don't require purity.
    """
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return "en"
    hangul = sum(1 for ch in letters if _is_hangul(ch))
    return "ko" if hangul / len(letters) >= 0.10 else "en"


__all__ = ["Language", "detect_language"]
