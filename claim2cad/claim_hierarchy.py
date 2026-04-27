"""Multi-claim hierarchy helpers (V1-8).

The IR already represents independent + dependent claims via
``Claim.depends_on`` and ``Component.is_dependent`` /
``Component.dependent_on``. This module adds:

* :func:`claim_chain` — walk dependency pointers to produce the chain
  ``[claim_id, parent, …, root]``.
* :func:`components_for_claim` — return components contributed by a
  given claim (optionally including ancestors).
* :func:`filter_ir_to_claim` — produce a new :class:`ClaimIR` containing
  only the requested claim, its ancestors, and the components / relations
  / wherein clauses they introduce. Useful for answering "what does
  claim N look like by itself?".
* :func:`hierarchy_summary` — a JSON-serialisable summary of the claim
  tree and per-claim contribution counts.

Backwards-compatible: callers that don't care about hierarchy never see
these helpers, and existing IRs validate unchanged.
"""
from __future__ import annotations

from typing import Iterable

from claim2cad.ir_schema import Claim, ClaimIR, Component, Relation, WhereinClause


def claim_chain(ir: ClaimIR, claim_id: str) -> list[str]:
    """Return ``[claim_id, parent_claim_id, …, root_claim_id]``.

    Detects cycles defensively (no claim should appear twice). Raises
    :class:`KeyError` if ``claim_id`` is not in ``ir``.
    """
    by_id = {c.id: c for c in ir.claims}
    if claim_id not in by_id:
        raise KeyError(f"claim_id {claim_id!r} not in IR")
    chain: list[str] = []
    seen: set[str] = set()
    cursor: str | None = claim_id
    while cursor is not None:
        if cursor in seen:
            break
        seen.add(cursor)
        chain.append(cursor)
        cursor = by_id[cursor].depends_on if cursor in by_id else None
    return chain


def _component_belongs_to(comp: Component, claim_ids: set[str]) -> bool:
    return comp.source_span.claim_id in claim_ids


def _relation_belongs_to(rel: Relation, claim_ids: set[str]) -> bool:
    return rel.source_span.claim_id in claim_ids


def _wherein_belongs_to(clause: WhereinClause, claim_ids: set[str]) -> bool:
    return clause.source_span.claim_id in claim_ids


def components_for_claim(
    ir: ClaimIR,
    claim_id: str,
    *,
    include_ancestors: bool = True,
) -> list[Component]:
    """Return components introduced by ``claim_id``.

    If ``include_ancestors`` is True (default), also include components
    from claims this one depends on. This is the practical "show me
    everything that's part of claim N" view — a dependent claim
    inherits its parent's components.
    """
    if include_ancestors:
        keep = set(claim_chain(ir, claim_id))
    else:
        keep = {claim_id}
    return [c for c in ir.components if _component_belongs_to(c, keep)]


def filter_ir_to_claim(
    ir: ClaimIR,
    claim_id: str,
    *,
    include_ancestors: bool = True,
) -> ClaimIR:
    """Return a new IR containing only ``claim_id`` (+ optional ancestors).

    The filtered IR keeps:

    * The claim node(s) in the dependency chain.
    * Components whose ``source_span.claim_id`` is in that chain.
    * Relations whose endpoints (source / target / via) are all kept.
    * Wherein clauses targeting kept components / relations.

    The :class:`ClaimIR` referential-integrity validator runs on the
    returned object, so the result is guaranteed valid.
    """
    if include_ancestors:
        chain = set(claim_chain(ir, claim_id))
    else:
        chain = {claim_id}

    kept_claims: list[Claim] = [c for c in ir.claims if c.id in chain]
    kept_components: list[Component] = [
        c for c in ir.components if _component_belongs_to(c, chain)
    ]
    kept_component_ids = {c.id for c in kept_components}

    kept_relations: list[Relation] = []
    for rel in ir.relations:
        if not _relation_belongs_to(rel, chain):
            continue
        if rel.source not in kept_component_ids:
            continue
        if rel.target not in kept_component_ids:
            continue
        if rel.via is not None and rel.via not in kept_component_ids:
            continue
        kept_relations.append(rel)
    kept_relation_ids = {r.id for r in kept_relations}

    kept_wherein: list[WhereinClause] = []
    for wc in ir.wherein_clauses:
        if not _wherein_belongs_to(wc, chain):
            continue
        targets_ok = all(
            t in kept_component_ids or t in kept_relation_ids for t in wc.targets
        )
        if not targets_ok:
            # Drop targets that have been filtered out, but keep the clause
            # if any targets remain (or there were none to begin with).
            new_targets = [
                t for t in wc.targets if t in kept_component_ids or t in kept_relation_ids
            ]
            wc = wc.model_copy(update={"targets": new_targets})
        kept_wherein.append(wc)

    return ClaimIR(
        title=ir.title,
        claims=kept_claims or [ir.claims[0]],
        components=kept_components,
        relations=kept_relations,
        wherein_clauses=kept_wherein,
    )


def hierarchy_summary(ir: ClaimIR) -> dict:
    """Return a JSON-serialisable summary of the claim tree.

    Shape::

        {
          "claims": [
            {
              "id": "claim_1",
              "is_independent": true,
              "depends_on": null,
              "chain": ["claim_1"],
              "n_components": 9,
              "n_components_introduced": 9,
              "n_relations_introduced": 8,
              "n_wherein_introduced": 2,
              "introduces": ["base", "first_link", ...]
            },
            ...
          ],
          "max_depth": 2,
          "n_independent": 1,
          "n_dependent": 1
        }
    """
    by_id = {c.id: c for c in ir.claims}
    summary_claims = []
    max_depth = 1
    n_independent = 0
    n_dependent = 0

    for cl in ir.claims:
        chain = claim_chain(ir, cl.id)
        max_depth = max(max_depth, len(chain))
        if cl.is_independent:
            n_independent += 1
        else:
            n_dependent += 1

        introduced = [
            c.id for c in ir.components if c.source_span.claim_id == cl.id
        ]
        rels_introduced = [
            r.id for r in ir.relations if r.source_span.claim_id == cl.id
        ]
        wcs_introduced = [
            wc.id for wc in ir.wherein_clauses if wc.source_span.claim_id == cl.id
        ]

        summary_claims.append(
            {
                "id": cl.id,
                "is_independent": cl.is_independent,
                "depends_on": cl.depends_on,
                "chain": chain,
                "n_components_introduced": len(introduced),
                "n_relations_introduced": len(rels_introduced),
                "n_wherein_introduced": len(wcs_introduced),
                "introduces": introduced,
            }
        )

    return {
        "claims": summary_claims,
        "max_depth": max_depth,
        "n_independent": n_independent,
        "n_dependent": n_dependent,
    }


__all__ = [
    "claim_chain",
    "components_for_claim",
    "filter_ir_to_claim",
    "hierarchy_summary",
]
