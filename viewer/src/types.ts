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

export type FigureReference = {
  figure_id: string;
  bbox?: number[] | null;
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
  figure_number?: string | null;
  figure_references?: FigureReference[];
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
  figure_number?: string;
};

export type ClaimMap = {
  schema_version: string;
  example: string;
  glb_path: string;
  components: ClaimMapRow[];
};

// V1-3 figure_map.json
export type VLMLabel = {
  number: string;
  description?: string;
  approximate_position?: number[];
  bbox?: number[];
};

export type FigureMap = {
  schema_version: string;
  patent_id: string;
  primary_figure: string | null;
  numbered_phrases: { phrase: string; number: string; char_start: number; char_end: number }[];
  vlm_labels: VLMLabel[];
  component_to_number: Record<string, string>;
  notes: string[];
};

export type Manifest = {
  schema_version: string;
  examples: ManifestExample[];
};

export type ManifestExample = {
  id: string;
  title: string;
  base: string; // base path (under /data/) for the example
  claim_text_path: string;
  ir_path: string;
  claim_map_path: string;
  glb_path: string;
  figure_map_path?: string | null;
  figure_image_path?: string | null;
  figure_coverage?: number;
  source?: "synthetic" | "real_patent" | "korean";
  tags?: string[];
};
