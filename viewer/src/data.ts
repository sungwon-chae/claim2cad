import type {
  ClaimIR,
  ClaimMap,
  FigureMap,
  Manifest,
  ManifestExample,
  PriorArtDiff,
} from "./types";

const dataBase = "/data";

export async function loadManifest(): Promise<Manifest> {
  const res = await fetch(`${dataBase}/manifest.json`);
  if (!res.ok) {
    throw new Error(`manifest.json missing or unreadable (${res.status})`);
  }
  return (await res.json()) as Manifest;
}

export type LoadedExample = {
  claimText: string;
  ir: ClaimIR;
  claimMap: ClaimMap;
  glbUrl: string;
  figureMap: FigureMap | null;
  figureImageUrl: string | null;
};

export async function loadExample(example: ManifestExample): Promise<LoadedExample> {
  const baseUrl = `${dataBase}/${example.base}`;
  const [claimText, ir, claimMap] = await Promise.all([
    fetchText(`${baseUrl}/${example.claim_text_path}`),
    fetchJson<ClaimIR>(`${baseUrl}/${example.ir_path}`),
    fetchJson<ClaimMap>(`${baseUrl}/${example.claim_map_path}`),
  ]);

  let figureMap: FigureMap | null = null;
  if (example.figure_map_path) {
    try {
      figureMap = await fetchJson<FigureMap>(`${baseUrl}/${example.figure_map_path}`);
    } catch (err) {
      console.warn(`figure_map.json missing for ${example.id}:`, err);
    }
  }
  const figureImageUrl = example.figure_image_path
    ? `${baseUrl}/${example.figure_image_path}`
    : null;

  return {
    claimText,
    ir,
    claimMap,
    glbUrl: `${baseUrl}/${example.glb_path}`,
    figureMap,
    figureImageUrl,
  };
}

export async function loadDiff(
  example: ManifestExample,
  diffPath: string
): Promise<PriorArtDiff> {
  return fetchJson<PriorArtDiff>(`${dataBase}/${example.base}/${diffPath}`);
}

async function fetchText(url: string): Promise<string> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Could not fetch ${url} (${res.status})`);
  return res.text();
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Could not fetch ${url} (${res.status})`);
  return (await res.json()) as T;
}
