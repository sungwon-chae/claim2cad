"""Library registry: fuzzy ``component_type → factory`` lookup.

The figure-to-CAD generator (V11-3) walks the claim IR plus VLM analysis of
the figure and asks the library for a part. We deliberately keep the lookup
heuristic shallow:

* exact name match wins,
* otherwise we score each registered name by a token-overlap heuristic
  against the requested type plus any "hints" (kind, category, label),
* if the best score is below a small threshold we return ``None`` so the
  generator falls back to VLM-generated build123d code.

This is intentionally not a vector-search retrieval system — patent claim
vocabulary maps to a few dozen mechanical primitives, and human-readable
aliases (``"hinge_leaf"`` → ``LeafHinge``) cover the gap.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from claim2cad.components.base import Component

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LibraryEntry:
    """A single registered factory. ``aliases`` are alternative names that
    figure analysis might use; they are also matched by lookup."""

    name: str
    factory: Callable[..., Component]
    aliases: tuple[str, ...] = ()
    description: str = ""


_REGISTRY: dict[str, LibraryEntry] = {}


def register(
    name: str,
    *,
    aliases: Iterable[str] = (),
    description: str = "",
) -> Callable[[Callable[..., Component]], Callable[..., Component]]:
    """Decorator: register a Component factory under ``name``."""

    def deco(factory: Callable[..., Component]) -> Callable[..., Component]:
        if name in _REGISTRY:
            raise ValueError(f"Library entry already registered: {name}")
        _REGISTRY[name] = LibraryEntry(
            name=name,
            factory=factory,
            aliases=tuple(aliases),
            description=description or (factory.__doc__ or "").strip().splitlines()[0]
            if (factory.__doc__ or "").strip()
            else "",
        )
        logger.debug("Registered library entry: %s", name)
        return factory

    return deco


def all_entries() -> list[LibraryEntry]:
    """Return every registered entry, sorted by name."""
    return sorted(_REGISTRY.values(), key=lambda e: e.name)


def get(name: str) -> LibraryEntry | None:
    """Exact-name lookup. Returns ``None`` if unknown."""
    return _REGISTRY.get(name)


# ---------------------------------------------------------------------------
# Fuzzy lookup
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(s: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(s or "")}


def _score(entry: LibraryEntry, query_tokens: set[str]) -> float:
    """Token-overlap score, normalised by name length. Aliases count too."""
    candidates = [_tokens(entry.name), *(_tokens(a) for a in entry.aliases)]
    best = 0.0
    for cand_tokens in candidates:
        if not cand_tokens:
            continue
        overlap = len(cand_tokens & query_tokens)
        if overlap == 0:
            continue
        # Reward heavy overlap with the candidate; mild reward for query
        # tokens covered.
        cand_cov = overlap / len(cand_tokens)
        query_cov = overlap / max(len(query_tokens), 1)
        score = 0.7 * cand_cov + 0.3 * query_cov
        if score > best:
            best = score
    return best


def lookup(
    component_type: str,
    *,
    hints: dict[str, Any] | None = None,
    threshold: float = 0.4,
) -> LibraryEntry | None:
    """Find the best library entry for ``component_type``.

    ``hints`` is a free-form dict; values stringify into the query token set
    so callers can pass an IR component dict, a VLM JSON blob, or both. The
    threshold is intentionally permissive — the figure-to-CAD generator
    treats a no-match as "fall back to VLM-generated build123d", which is
    fine but more expensive.
    """
    if not component_type:
        return None
    # Exact match wins immediately.
    direct = _REGISTRY.get(component_type)
    if direct is not None:
        return direct
    # Build the query token bag.
    query = _tokens(component_type)
    if hints:
        for v in hints.values():
            if v is None:
                continue
            if isinstance(v, (list, tuple, set)):
                for item in v:
                    query |= _tokens(str(item))
            else:
                query |= _tokens(str(v))
    if not query:
        return None
    scored: list[tuple[float, LibraryEntry]] = []
    for entry in _REGISTRY.values():
        sc = _score(entry, query)
        if sc > 0:
            scored.append((sc, entry))
    if not scored:
        return None
    scored.sort(key=lambda p: -p[0])
    best_score, best_entry = scored[0]
    if best_score < threshold:
        logger.debug(
            "lookup(%r) best=%s score=%.2f below threshold %.2f",
            component_type,
            best_entry.name,
            best_score,
            threshold,
        )
        return None
    return best_entry


def instantiate(
    component_type: str,
    *,
    params: dict[str, Any] | None = None,
    hints: dict[str, Any] | None = None,
) -> Component | None:
    """Lookup + instantiate. Drops unknown kwargs so VLM-supplied hints
    that don't match the dataclass fields don't break construction."""
    entry = lookup(component_type, hints=hints)
    if entry is None:
        return None
    safe_params = _safe_kwargs(entry.factory, params or {})
    try:
        return entry.factory(**safe_params)
    except TypeError as exc:
        logger.warning("Library factory %s rejected params: %s", entry.name, exc)
        return None


def _safe_kwargs(factory: Callable[..., Any], params: dict[str, Any]) -> dict[str, Any]:
    """Filter ``params`` to keys the underlying Component dataclass accepts.

    Most factories are tiny ``def f(**kw): return SomeClass(**kw)`` shims, so
    inspecting the factory's own signature only reveals ``**kwargs``. We try
    the factory once with no args to discover the produced class, then read
    its dataclass fields.
    """
    # Strategy 1: factory IS a class (preferred — when @register decorates a
    # Component subclass directly).
    fields = getattr(factory, "__dataclass_fields__", None)
    if fields is not None:
        return {k: v for k, v in params.items() if k in fields}
    # Strategy 2: factory is a wrapper that returns a Component instance.
    # Build with no args to discover the class.
    try:
        sample = factory()
        sample_fields = getattr(type(sample), "__dataclass_fields__", None)
        if sample_fields is not None:
            return {k: v for k, v in params.items() if k in sample_fields}
    except Exception:  # noqa: BLE001 — discovery is best-effort
        pass
    # Strategy 3: inspect the factory signature.
    try:
        import inspect
        sig = inspect.signature(factory)
        accepted = {
            name
            for name, p in sig.parameters.items()
            if p.kind not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
        }
        if accepted:
            return {k: v for k, v in params.items() if k in accepted}
    except (TypeError, ValueError):
        pass
    return dict(params)


__all__ = [
    "LibraryEntry",
    "register",
    "all_entries",
    "get",
    "lookup",
    "instantiate",
]
