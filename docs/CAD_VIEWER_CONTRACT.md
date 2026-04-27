# CAD ↔ Viewer Contract

The viewer can find a 3D part for a claim element only because the pipeline
agrees with the viewer about *what string to use as the GLB node name*.

## The contract

For every IR component:

1. The pipeline emits a build123d `Shape` with `Shape.label = component.id`.
2. After `bd.export_gltf(...)` writes the GLB,
   `claim2cad.glb_naming.rename_glb_root_children` rewrites the JSON chunk so
   the GLB scene's root node has one child per component, in the order the
   pipeline placed them, and that child's `name` field equals
   `component.id`.
3. The pipeline writes `claim_map.json` whose `components[].glb_node_name`
   field equals `component.id` for every row.
4. The viewer (`viewer/src/components/Scene.tsx`) walks the loaded glTF scene
   tree and indexes meshes by their nearest ancestor whose name appears in
   `claim_map.json`. That string is the *only* identifier shared between
   panel clicks and 3D mesh clicks.

## What can go wrong

- **build123d does not preserve `Shape.label` through `export_gltf`.** It
  emits OCAF refs like `=>[0:1:1:2]`. The post-processor in
  `claim2cad/glb_naming.py` exists *because* of this. If a future build123d
  release fixes label round-tripping, the post-processor becomes a no-op
  but stays harmless.
- **Sibling-uniqueness for component IDs.** Two siblings under the same
  parent must have distinct labels. The schema enforces uniqueness across
  the whole IR (`pattern=r"^[a-z][a-z0-9_]*$"` plus a duplicate check in
  `ClaimIR._check_referential_integrity`), so this is automatic.
- **Order matters.** `rename_glb_root_children(glb, ordered_ids)` matches
  by position, not by name. The `ordered_ids` list returned by
  `build_compound` must reflect the order children were added to the
  `Compound`. Don't reorder one without the other.
- **GLB nodes vs. GLB meshes.** We rename *nodes*, not meshes. The viewer's
  walk-up logic (`Scene.tsx:walkUpForComponentId`) looks at each mesh's
  ancestor chain for a name that's in the claim_map. A mesh's *own* `name`
  is typically `"SOLID"` (build123d's leaf label) — that's expected.

## Failure modes the viewer surfaces

- A component in `claim_map.json` with no matching node in the GLB → the
  span renders normally but clicking the span does nothing in 3D. We
  intentionally don't suppress the row because the panel is the
  authoritative source of "what the claim says".
- A node in the GLB with no entry in `claim_map.json` → the mesh is still
  rendered (no entries are filtered) but is unselectable. We also don't
  highlight it.
- A span in the IR whose component doesn't appear in `claim_map.json` →
  rendered with a dashed underline and a `?` badge (the "F6 — unmapped
  element indicator" feature from the revised Phase 5 brief).
