// Mirrors claim2cad/ir_schema.py (subset used by the viewer).

export type ComponentCategory = "structural" | "connection" | "functional";

export type SourceSpan = {
  claim_id: string;
  char_start: number;
  char_end: number;
};

export type IRClaim = {
  id: string;
  text: string;
  is_independent: boolean;
  depends_on: string | null;
};

export type IRComponent = {
  id: string;
  label: string;
  category: ComponentCategory;
  kind: string;
  parent_id: string | null;
  source_span: SourceSpan;
  is_dependent: boolean;
  dependent_on: string | null;
  constraints: string[];
};

export type IRRelation = {
  id: string;
  kind: string;
  source: string;
  target: string;
  via: string | null;
  source_span: SourceSpan;
};

export type IRWherein = {
  id: string;
  text: string;
  targets: string[];
  source_span: SourceSpan;
};

export type ClaimIR = {
  schema_version: string;
  title: string;
  claims: IRClaim[];
  components: IRComponent[];
  relations: IRRelation[];
  wherein_clauses: IRWherein[];
};

export type ClaimMapRow = {
  component_id: string;
  glb_node_name: string;
  label: string;
  category: ComponentCategory;
  kind: string;
  is_dependent: boolean;
  source_span: SourceSpan;
};

export type ClaimMap = {
  schema_version: string;
  example: string;
  glb_path: string;
  components: ClaimMapRow[];
};

export type Manifest = {
  schema_version: string;
  examples: ManifestExample[];
};

export type ManifestExample = {
  id: string;
  title: string;
  base: string; // base path (under /data/<id>/) for the example
  claim_text_path: string;
  ir_path: string;
  claim_map_path: string;
  glb_path: string;
};
