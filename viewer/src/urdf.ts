import type { URDFJoint } from "./types";

function parseTriplet(s: string | null, fallback: [number, number, number]): [number, number, number] {
  if (!s) return fallback;
  const parts = s.trim().split(/\s+/).map((v) => Number(v));
  if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) return fallback;
  return parts as [number, number, number];
}

export function parseUrdf(xml: string): URDFJoint[] {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  const out: URDFJoint[] = [];
  doc.querySelectorAll("robot > joint").forEach((j) => {
    const name = j.getAttribute("name") ?? "";
    const type = (j.getAttribute("type") ?? "fixed") as URDFJoint["type"];
    const parent = j.querySelector("parent")?.getAttribute("link") ?? "";
    const child = j.querySelector("child")?.getAttribute("link") ?? "";
    const origin = parseTriplet(
      j.querySelector("origin")?.getAttribute("xyz") ?? null,
      [0, 0, 0]
    );
    const axis = parseTriplet(
      j.querySelector("axis")?.getAttribute("xyz") ?? null,
      [0, 0, 1]
    );
    const limitEl = j.querySelector("limit");
    const lower = limitEl ? Number(limitEl.getAttribute("lower")) : NaN;
    const upper = limitEl ? Number(limitEl.getAttribute("upper")) : NaN;
    const limit =
      Number.isFinite(lower) && Number.isFinite(upper)
        ? { lower, upper }
        : undefined;
    out.push({ name, type, parent, child, origin, axis, limit });
  });
  return out;
}

export async function loadUrdf(url: string): Promise<URDFJoint[]> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Could not fetch ${url} (${res.status})`);
  return parseUrdf(await res.text());
}
