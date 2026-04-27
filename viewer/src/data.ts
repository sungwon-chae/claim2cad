import type { ClaimIR, ClaimMap, Manifest, ManifestExample } from "./types";

const dataBase = "/data";

export async function loadManifest(): Promise<Manifest> {
  const res = await fetch(`${dataBase}/manifest.json`);
  if (!res.ok) {
    throw new Error(`manifest.json missing or unreadable (${res.status})`);
  }
  return (await res.json()) as Manifest;
}

export async function loadExample(example: ManifestExample): Promise<{
  claimText: string;
  ir: ClaimIR;
  claimMap: ClaimMap;
  glbUrl: string;
}> {
  const [claimText, ir, claimMap] = await Promise.all([
    fetchText(`${dataBase}/${example.base}/${example.claim_text_path}`),
    fetchJson<ClaimIR>(`${dataBase}/${example.base}/${example.ir_path}`),
    fetchJson<ClaimMap>(`${dataBase}/${example.base}/${example.claim_map_path}`),
  ]);
  return {
    claimText,
    ir,
    claimMap,
    glbUrl: `${dataBase}/${example.base}/${example.glb_path}`,
  };
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
