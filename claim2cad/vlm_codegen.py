"""VLM-driven build123d code generation for components without library cover.

For each IR component that the figure-to-CAD generator could not map to a
library entry, we ask the VLM to write a small build123d snippet whose
side effect is to bind a single ``result`` variable to a build123d
``Solid`` / ``Part`` / ``Compound``. The snippet is evaluated in a
restricted exec namespace (``build123d`` and ``math`` only), the produced
solid is exported as STEP and labelled with the component id.

This is a careful path:

* The VLM is given the component's IR fields, the figure crop around its
  numbered callout, and the surrounding claim language. It is told to
  prefer a small parametric construction with named primitive calls.
* The exec namespace is curated — no ``__builtins__`` access beyond
  ``len``, ``range``, ``min``, ``max``, ``abs``, ``round``, and the
  ``math`` module. No file IO, no socket, no dynamic import.
* If the snippet errors, raises, or produces an empty/degenerate solid
  the caller falls back to a primitive box. Failures are captured for
  debugging, never bubbled.

This is the single most expensive path in the pipeline (each call writes
both prompt + figure crop), so the figure_to_cad generator only invokes
it for components where ``library_part is None``.
"""
from __future__ import annotations

import ast
import json
import logging
import math
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import build123d as bd

from claim2cad.figure_crops import FigureCrop
from claim2cad.llm_vision import vision_completion

logger = logging.getLogger(__name__)


@dataclass
class CodegenResult:
    """Outcome of one codegen call."""

    component_id: str
    success: bool
    solid: bd.Part | bd.Compound | None = None
    code: str = ""
    error: str = ""
    notes: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)


_SAFE_BUILTINS: dict[str, Any] = {
    "len": len,
    "range": range,
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "int": int,
    "float": float,
    "tuple": tuple,
    "list": list,
    "dict": dict,
    "enumerate": enumerate,
    "zip": zip,
}


# AST node types that are forbidden in VLM-supplied code.
_FORBIDDEN_NODES: tuple[type, ...] = (
    ast.Import,
    ast.ImportFrom,
    ast.Try,
    ast.With,
    ast.AsyncFunctionDef,
    ast.AsyncFor,
    ast.AsyncWith,
    ast.Global,
    ast.Nonlocal,
    ast.Lambda,
    ast.Yield,
    ast.YieldFrom,
)

# Attribute names the VLM should never reach for. Catches the common
# escape paths (__builtins__, __import__, __class__.__bases__ chain).
_FORBIDDEN_ATTRS: tuple[str, ...] = (
    "__builtins__",
    "__import__",
    "__getattribute__",
    "__bases__",
    "__subclasses__",
    "__globals__",
    "__class__",
    "__mro__",
    "__reduce__",
    "__code__",
    "__dict__",
    "open",
    "eval",
    "exec",
    "compile",
)


def _validate_code(code: str) -> str | None:
    """Return an error string if ``code`` should not be executed; ``None`` if ok."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        return f"SyntaxError: {exc}"
    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_NODES):
            return f"Forbidden AST node: {type(node).__name__}"
        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_ATTRS:
            return f"Forbidden attribute access: {node.attr!r}"
        if isinstance(node, ast.Name) and node.id.startswith("__") and node.id.endswith("__"):
            return f"Dunder name not allowed: {node.id!r}"
    return None


def _exec_snippet(code: str) -> tuple[Any, str]:
    """Run ``code`` in a restricted namespace. Returns (result, error_str)."""
    err = _validate_code(code)
    if err is not None:
        return None, err
    namespace: dict[str, Any] = {
        "__builtins__": _SAFE_BUILTINS,
        "bd": bd,
        "build123d": bd,
        "math": math,
    }
    try:
        exec(code, namespace, namespace)  # noqa: S102 — sandboxed via builtins shim
    except Exception as exc:  # noqa: BLE001 — capture every runtime fault
        return None, f"{type(exc).__name__}: {exc}"
    if "result" not in namespace:
        return None, "snippet did not bind a `result` variable"
    return namespace["result"], ""


def _solid_is_valid(solid: Any) -> bool:
    if not isinstance(solid, (bd.Part, bd.Compound, bd.Solid)):
        return False
    try:
        bb = solid.bounding_box()
    except Exception:  # noqa: BLE001
        return False
    sx = bb.max.X - bb.min.X
    sy = bb.max.Y - bb.min.Y
    sz = bb.max.Z - bb.min.Z
    if sx <= 0.001 or sy <= 0.001 or sz <= 0.001:
        return False
    # Reject absurdly large outputs (e.g. millions of mm).
    if max(sx, sy, sz) > 5000.0:
        return False
    return True


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "You are writing a tiny build123d Python snippet to construct ONE "
    "mechanical component for a parametric CAD assembly. You will see a "
    "crop of the patent figure showing the component, plus the claim "
    "constraints describing it. Return strict JSON. The code must:\n"
    "  - bind a single variable named `result` to a build123d Part / Solid / Compound\n"
    "  - use ONLY `bd` (alias for build123d) and `math`\n"
    "  - have NO imports, NO try/except, NO file IO, NO __dunder__ access\n"
    "  - keep the dimensions reasonable (overall extent <= 250 mm)\n"
    "  - end with `result = <expression>` so the caller can pick it up\n"
    "Work in millimetres. Keep it short — under 25 lines."
)


_USER_TEMPLATE = """Component to build:

  id: {component_id}
  label: {label}
  kind: {kind}
  category: {category}
  figure_number: {figure_number}
  parent_id: {parent_id}

Claim constraints (verbatim from the patent claim text):
{constraints}

Hints from the prior figure-to-spec pass:
  features: {features}
  notes: {notes}
  desired_position_mm: {position_mm}
  desired_rotation_deg: {rotation_deg}

The image is the patent figure cropped around this component's
callout (number {figure_number}).

Return JSON with this EXACT shape:
{{
  "code": "<build123d snippet, ends with result = <expr>>",
  "explanation": "<1 sentence on what shape and why>"
}}
"""


def generate_component_code(
    *,
    component_id: str,
    label: str,
    kind: str,
    category: str,
    figure_number: str,
    parent_id: str | None,
    constraints: list[str],
    features: list[str],
    notes: str,
    position_mm: tuple[float, float, float],
    rotation_deg: tuple[float, float, float],
    figure_crop: FigureCrop | Path,
    task_type: str = "v11_codegen_component",
) -> CodegenResult:
    """Ask the VLM for a build123d snippet, validate, exec, return the solid."""
    crop_path = (
        figure_crop.crop_path if isinstance(figure_crop, FigureCrop) else Path(figure_crop)
    )
    user_prompt = _USER_TEMPLATE.format(
        component_id=component_id,
        label=label,
        kind=kind or "(unknown)",
        category=category or "(unknown)",
        figure_number=figure_number or "(none)",
        parent_id=parent_id or "(none)",
        constraints="\n".join(f"  - {c}" for c in constraints) if constraints else "  (none)",
        features=features or [],
        notes=notes or "",
        position_mm=list(position_mm),
        rotation_deg=list(rotation_deg),
    )
    raw = vision_completion(
        image_path=crop_path,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        task_type=task_type,
    )
    code = str(raw.get("code", "")).strip()
    explanation = str(raw.get("explanation", ""))
    if not code:
        return CodegenResult(
            component_id=component_id,
            success=False,
            error="empty code in VLM response",
            notes=explanation,
            raw_response=raw,
        )
    code = textwrap.dedent(code)
    solid, err = _exec_snippet(code)
    if err:
        return CodegenResult(
            component_id=component_id,
            success=False,
            code=code,
            error=err,
            notes=explanation,
            raw_response=raw,
        )
    if not _solid_is_valid(solid):
        return CodegenResult(
            component_id=component_id,
            success=False,
            code=code,
            error="produced solid is empty / degenerate / oversized",
            notes=explanation,
            raw_response=raw,
        )
    return CodegenResult(
        component_id=component_id,
        success=True,
        solid=solid,
        code=code,
        notes=explanation,
        raw_response=raw,
    )


__all__ = ["CodegenResult", "generate_component_code"]
