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

export type DiffSummary = {
  comparison_id: string;
  comparison_title: string;
  diff_path: string; // filename relative to the example's staged directory
  matched: number;
  novel_in_base: number;
  only_in_comparison: number;
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
  diffs_available?: DiffSummary[];
  urdf_path?: string | null;
  movable_joints?: string[];
  /** V13-H: per-example quality verdict from eval_v13.
   *  flagship | good | partial | fallback | failed | unknown */
  quality_badge?: string;
  quality_score?: number;
  scaffold_id?: string;
  /** V13-O: semantic mismatch surfaced from
   *  claim2cad.semantic_mismatch. */
  mismatch_severity?: "none" | "advisory" | "warning";
  mismatch_reason?: string;
  mismatch_expected?: string[];
  /** V14-H: figure view classification + view-matched render. */
  figure_view_type?: string;
  figure_required_camera?: string;
  figure_matched_render?: string;
  plan_view_render?: string;
  section_view_render?: string;
};

// V1-6 — URDF parsed payload (subset).
export type URDFJoint = {
  name: string;
  type: "revolute" | "prismatic" | "continuous" | "fixed";
  parent: string;
  child: string;
  origin: [number, number, number];
  axis: [number, number, number];
  limit?: { lower: number; upper: number };
};

// V1-5 prior-art diff payload (mirrors claim2cad/prior_art.py PriorArtDiff).
export type PriorArtDiff = {
  base_patent: string;
  comparison_patent: string;
  matched: {
    base_id: string;
    base_label: string;
    comparison_id: string;
    comparison_label: string;
    score: number;
    category: string;
    kind_base: string;
    kind_comparison: string;
  }[];
  novel_in_base: { id: string; label: string; category: string; kind: string }[];
  only_in_comparison: { id: string; label: string; category: string; kind: string }[];
  notes?: string[];
};
