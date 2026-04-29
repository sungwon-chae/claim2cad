"""V13-B — base scaffold contract.

Every scaffold template is a class that takes a claim_map +
figure data and produces a build123d Compound whose top-level
children are labelled with the claim component_ids. The viewer
loads the resulting GLB and the GLB-naming contract preserves
claim ↔ figure ↔ CAD interactivity.

Scaffolds must be:
  * deterministic (no LLM calls inside the build path),
  * tolerant of partial inputs (claim_map without figure_map,
    or figure_map without callouts),
  * spatially coherent (no central pile — components must
    spread out by GROUP).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import build123d as bd


@dataclass
class ScaffoldInput:
    """Everything a scaffold needs to build a model."""

    example_dir: Path
    example_id: str
    claim_map: dict[str, Any] | None = None
    figure_map: dict[str, Any] | None = None
    figure_classification: dict[str, Any] | None = None
    figure_image_path: Path | None = None

    def component_ids(self) -> list[str]:
        if not self.claim_map:
            return []
        return [r["component_id"] for r in self.claim_map.get("components", [])]

    def component_label(self, cid: str) -> str:
        if not self.claim_map:
            return cid
        for r in self.claim_map.get("components", []):
            if r.get("component_id") == cid:
                return r.get("label", cid)
        return cid


@dataclass
class ScaffoldResult:
    """What a scaffold produces."""

    compound: bd.Compound
    ordered_ids: list[str]
    scaffold_id: str
    diagnostics: dict[str, Any] = field(default_factory=dict)
    quality_tier: str = "fallback"  # "flagship" | "good" | "partial" | "fallback"


class Scaffold(ABC):
    """Abstract base. Subclasses register a unique ``scaffold_id`` and
    implement :meth:`build`."""

    scaffold_id: str = "abstract"

    @abstractmethod
    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        ...

    def description(self) -> str:
        return self.__doc__ or self.scaffold_id


# Registry — populated by claim2cad.scaffolds.__init__
_REGISTRY: dict[str, type[Scaffold]] = {}


def register_scaffold(cls: type[Scaffold]) -> type[Scaffold]:
    if not getattr(cls, "scaffold_id", None) or cls.scaffold_id == "abstract":
        raise ValueError(f"{cls.__name__} missing scaffold_id")
    _REGISTRY[cls.scaffold_id] = cls
    return cls


def get_scaffold(scaffold_id: str) -> type[Scaffold] | None:
    return _REGISTRY.get(scaffold_id)


def list_scaffolds() -> list[str]:
    return sorted(_REGISTRY.keys())
