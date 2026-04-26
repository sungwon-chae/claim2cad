# Claim2CAD IR Schema

The IR (`claim2cad.ir_schema.ClaimIR`) is the contract between the parser and
every downstream stage. Parsers produce it, the CAD generator consumes it, the
mapping writer flattens it, and the viewer overlays it.

This document is the human-readable companion to
[`claim2cad/ir_schema.py`](../claim2cad/ir_schema.py). When the two diverge
the Python file wins.

## Top-level: `ClaimIR`

```jsonc
{
  "schema_version": "0.1.0",
  "title": "Articulated robotic manipulator",
  "claims": [ /* one Claim per claim */ ],
  "components": [ /* every named part */ ],
  "relations": [ /* directed edges between components */ ],
  "wherein_clauses": [ /* "wherein..." modifiers */ ]
}
```

- `schema_version` is pinned to `"0.1.0"` for v0.1. Bumping it is a deliberate
  breaking change; all examples and tests need updating in lockstep.
- `title` is a short, human-readable summary used in the viewer header. It is
  not authoritative — the claim text is.

## `Claim`

```jsonc
{
  "id": "claim_1",                 // must match /^claim_[0-9]+$/
  "text": "An articulated ...",   // verbatim from the patent
  "is_independent": true,
  "depends_on": null               // or "claim_1" if this is dependent
}
```

The parser may emit several claims (an independent + one or more dependent).
All `source_span.claim_id`s must reference one of these.

## `Component`

```jsonc
{
  "id": "first_link",                // /^[a-z][a-z0-9_]*$/, used as build123d Shape.label
  "label": "first link",             // surface form for the UI
  "category": "structural",          // structural | connection | functional
  "kind": "rod",                     // open string; see ir_to_cad dispatch
  "parent_id": null,                 // for hierarchical containment
  "dimension": { "kind": "unspecified" },
  "constraints": [],
  "source_span": {
    "claim_id": "claim_1",
    "char_start": 42,
    "char_end": 53
  },
  "is_dependent": false,
  "dependent_on": null
}
```

### Categories vs. kinds

The 3-way split (`structural | connection | functional`) is closed; sub-kinds
are open. The ir_to_cad dispatch table uses the *kind* to pick a primitive
shape and falls back to a labelled box for unknowns.

| category    | example kinds                                                       |
|-------------|---------------------------------------------------------------------|
| structural  | `block`, `rod`, `plate`, `shell`, `frame`, `housing`               |
| connection  | `revolute_joint`, `prismatic_joint`, `fixed_joint`, `spherical_joint`, `fastener` |
| functional  | `sensor`, `actuator`, `end_effector`, `controller`                  |

### Hierarchical containment

`parent_id` lets a parser emit a "joint assembly" containing "pin" and
"bushing":

```jsonc
{ "id": "joint_assembly", "kind": "fixed_joint", ... },
{ "id": "pin", "kind": "fastener", "parent_id": "joint_assembly", ... },
{ "id": "bushing", "kind": "shell", "parent_id": "joint_assembly", ... }
```

The viewer uses `parent_id` to group meshes when "limitation focus mode" is on.

### Dimensions

Three forms, discriminated by `kind`:

```jsonc
{ "kind": "unspecified" }
{ "kind": "relative", "description": "longer than the first link" }
{ "kind": "value", "value": 30, "unit": "mm" }
```

The CAD generator reads `dimension.value` when present; otherwise it picks
defaults from the kind (e.g. a rod is 50 mm long by default).

### Provenance

Every component has a `source_span` pointing into one of the claims. Spans
are character ranges using Python slice semantics (`text[start:end]`). The
viewer uses these to render the claim text with `<span>` wrappers.

### Independent vs. dependent

`is_dependent: true` marks a component or relation introduced by a *dependent*
claim (and `dependent_on` says which one). The viewer colours these with the
amber accent vs. blue for independent.

## `Relation`

```jsonc
{
  "id": "rel_first_link_to_base",
  "kind": "attached_to",
  "source": "first_link",
  "target": "base",
  "via": null,                       // used by `connects` to name a third component
  "constraints": [],
  "source_span": { ... },
  "is_dependent": false,
  "dependent_on": null
}
```

### Relation kinds

| kind                  | meaning                                                            |
|-----------------------|--------------------------------------------------------------------|
| `attached_to`         | rigid attachment (e.g., "the first link is attached to the base") |
| `connects`            | A connects B via C (`source=A target=B via=C`)                     |
| `contains`            | A contains B (subassembly)                                         |
| `rotates_about`       | A rotates about axis defined by B                                  |
| `translates_along`    | A translates along axis defined by B                               |
| `transmits_force_to`  | mechanical force transmission (e.g. gear coupling)                |

The layout engine uses `attached_to` and `contains` to do BFS placement; the
others are decorative for v0.1 (passed through to the viewer for tooltips).

## `WhereinClause`

```jsonc
{
  "id": "wherein_revolute",
  "text": "wherein each joint is a revolute joint having one degree of freedom",
  "targets": ["shoulder_joint", "elbow_joint", "wrist_joint"],
  "source_span": { ... },
  "is_dependent": false,
  "dependent_on": null
}
```

Wherein clauses can target either component IDs or relation IDs. The viewer
renders them in italics with a side margin marker.

## Referential integrity

The root `ClaimIR` validator enforces:

- All `Component.id` and `Claim.id` values are unique.
- Every `Component.parent_id`, `Relation.{source,target,via}`, and
  `WhereinClause.targets[*]` resolves to a known component or relation ID.
- Every `source_span.claim_id` resolves to a known `Claim.id`.

Validation failures raise `pydantic.ValidationError` and the parser retries
once with the error message fed back to the LLM (see Phase 4).
