"""Pydantic v2 schema for the Claim2CAD intermediate representation (IR).

The IR is the contract between the parser and every downstream stage: CAD
generator, mapping writer, and viewer. It captures **what the claim says**
(components, relations, wherein clauses), **where in the claim it said it**
(source spans for highlighting), and **how confident we are about geometry**
(dimensions are mostly unspecified by design).

Design notes:

- Component types are split into three open categories — ``structural``,
  ``connection``, ``functional`` — with sub-kinds inside each. The string
  taxonomy is open by design: a parser may emit ``structural:plate`` even if
  the matching shape isn't yet implemented in ``ir_to_cad`` and the pipeline
  will fall back to a labelled box. New kinds don't need a schema change.
- Relations are a small closed enum. Adding a new relation requires updating
  the layout engine, so it should be a deliberate change.
- Every node has a ``source_span``. Even synthetic nodes (e.g. a stub
  generated when LLM parsing fails) carry a span pointing to the whole
  claim.
- ``ClaimIR.model_dump_json(indent=2)`` produces a deterministic, diff-friendly
  on-disk format.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Provenance / dimensions
# ---------------------------------------------------------------------------


class SourceSpan(BaseModel):
    """A character range inside a specific claim.

    ``claim_id`` is the canonical claim identifier (e.g. ``"claim_1"``,
    ``"claim_2"``). ``char_start`` is inclusive, ``char_end`` is exclusive,
    matching Python slice semantics.
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(..., min_length=1)
    char_start: int = Field(..., ge=0)
    char_end: int = Field(..., ge=0)

    @model_validator(mode="after")
    def _check_range(self) -> "SourceSpan":
        if self.char_end < self.char_start:
            raise ValueError(
                f"char_end ({self.char_end}) must be >= char_start ({self.char_start})"
            )
        return self


class DimensionValue(BaseModel):
    """A numeric dimension with an explicit unit, e.g. ``{value: 30, unit: 'mm'}``."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["value"] = "value"
    value: float
    unit: str = Field(..., min_length=1, max_length=16)


class DimensionRelative(BaseModel):
    """A dimension expressed only relative to other components.

    e.g. "longer than the first link", "approximately twice the diameter of
    the bore". The parser captures the textual hint without committing to a
    number.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["relative"] = "relative"
    description: str = Field(..., min_length=1)


class DimensionUnspecified(BaseModel):
    """No dimensional information given by the claim."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["unspecified"] = "unspecified"


Dimension = Annotated[
    Union[DimensionValue, DimensionRelative, DimensionUnspecified],
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


# Open-ended sub-kind strings. The CAD generator looks them up in a dispatch
# table and falls back to a labelled box for unknown values.
StructuralKind = Literal["block", "rod", "plate", "shell", "frame", "housing"]
ConnectionKind = Literal[
    "revolute_joint",
    "prismatic_joint",
    "fixed_joint",
    "spherical_joint",
    "fastener",
]
FunctionalKind = Literal["sensor", "actuator", "end_effector", "controller"]
ComponentKind = Union[StructuralKind, ConnectionKind, FunctionalKind, str]
ComponentCategory = Literal["structural", "connection", "functional"]


class FigureReference(BaseModel):
    """A pointer back to a numbered label in a patent figure."""

    model_config = ConfigDict(extra="forbid")

    figure_id: str = Field(..., min_length=1, max_length=32)  # e.g. "figure_1"
    bbox: Optional[list[float]] = None  # [x, y, w, h] in *normalised* image coords (0..1)


class Component(BaseModel):
    """A named physical part referenced by the claim."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    label: str = Field(..., min_length=1, max_length=120)
    category: ComponentCategory
    kind: str = Field(..., min_length=1, max_length=64)
    parent_id: Optional[str] = None
    dimension: Dimension = Field(default_factory=DimensionUnspecified)
    constraints: list[str] = Field(default_factory=list)
    source_span: SourceSpan
    is_dependent: bool = False
    dependent_on: Optional[str] = None  # ID of the parent claim if dependent.

    # V1-3: figure-parsing additions. Both default to absent so old IRs stay
    # valid and the LLM doesn't need to know about these fields.
    figure_number: Optional[str] = None
    figure_references: list[FigureReference] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------


RelationKind = Literal[
    "attached_to",
    "connects",
    "contains",
    "rotates_about",
    "translates_along",
    "transmits_force_to",
]


class Relation(BaseModel):
    """A directed edge between components."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    kind: RelationKind
    source: str  # component id
    target: str  # component id
    via: Optional[str] = None  # third component, used by `connects`
    constraints: list[str] = Field(default_factory=list)
    source_span: SourceSpan
    is_dependent: bool = False
    dependent_on: Optional[str] = None


# ---------------------------------------------------------------------------
# Wherein clauses
# ---------------------------------------------------------------------------


class WhereinClause(BaseModel):
    """A `wherein …` modifier attached to one or more components/relations."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    text: str = Field(..., min_length=1)
    targets: list[str] = Field(
        default_factory=list,
        description="Component or Relation IDs the clause modifies.",
    )
    source_span: SourceSpan
    is_dependent: bool = False
    dependent_on: Optional[str] = None


# ---------------------------------------------------------------------------
# Claim and root IR
# ---------------------------------------------------------------------------


class Claim(BaseModel):
    """One claim within a patent. The parser may emit several of these."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^claim_[0-9]+$")
    text: str = Field(..., min_length=1)
    is_independent: bool = True
    depends_on: Optional[str] = None  # claim_id of the parent claim


class ClaimIR(BaseModel):
    """Top-level intermediate representation produced by the parser."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1.0"] = "0.1.0"
    title: str = Field(..., min_length=1)
    claims: list[Claim] = Field(..., min_length=1)
    components: list[Component] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    wherein_clauses: list[WhereinClause] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_referential_integrity(self) -> "ClaimIR":
        component_ids = {c.id for c in self.components}
        if len(component_ids) != len(self.components):
            raise ValueError("Duplicate component IDs in IR")

        claim_ids = {c.id for c in self.claims}
        if len(claim_ids) != len(self.claims):
            raise ValueError("Duplicate claim IDs in IR")

        for component in self.components:
            if component.parent_id and component.parent_id not in component_ids:
                raise ValueError(
                    f"Component {component.id!r} has unknown parent_id "
                    f"{component.parent_id!r}"
                )
            if component.source_span.claim_id not in claim_ids:
                raise ValueError(
                    f"Component {component.id!r} cites unknown claim "
                    f"{component.source_span.claim_id!r}"
                )

        for relation in self.relations:
            for ref_field in ("source", "target", "via"):
                ref = getattr(relation, ref_field)
                if ref is not None and ref not in component_ids:
                    raise ValueError(
                        f"Relation {relation.id!r}.{ref_field} refers to unknown "
                        f"component {ref!r}"
                    )
            if relation.source_span.claim_id not in claim_ids:
                raise ValueError(
                    f"Relation {relation.id!r} cites unknown claim "
                    f"{relation.source_span.claim_id!r}"
                )

        all_ref_ids = component_ids | {r.id for r in self.relations}
        for clause in self.wherein_clauses:
            for target in clause.targets:
                if target not in all_ref_ids:
                    raise ValueError(
                        f"WhereinClause {clause.id!r} targets unknown id "
                        f"{target!r}"
                    )

        return self


__all__ = [
    "Claim",
    "ClaimIR",
    "Component",
    "ComponentCategory",
    "Dimension",
    "DimensionRelative",
    "DimensionUnspecified",
    "DimensionValue",
    "FigureReference",
    "Relation",
    "RelationKind",
    "SourceSpan",
    "WhereinClause",
]
