import { useEffect, useMemo, useRef, useState } from "react";
import type { ClaimMapRow, FigureMap, VLMLabel } from "../types";

type Props = {
  imageUrl: string | null;
  figureMap: FigureMap | null;
  rows: ClaimMapRow[];
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
  /** V11-31: canonical figure_hotspots.json (raw image-pixel
   *  coordinates). When present, the viewer uses these instead of
   *  recomputing from figure_map.vlm_labels. */
  hotspotsCanonical: FigureHotspotSet | null;
};

export type FigureHotspot = {
  hotspot_id: string;
  figure_id: string;
  component_id: string | null;
  callout_number: string;
  label: string;
  coord_space: string;
  image_width_px: number;
  image_height_px: number;
  center_px: [number, number];
  bbox_px: [number, number, number, number];
  confidence: number;
  source: string;
};

export type FigureHotspotSet = {
  schema_version: string;
  figure_id: string;
  figure_path: string;
  image_width_px: number;
  image_height_px: number;
  hotspots: FigureHotspot[];
};

type Hotspot = {
  componentId: string;
  number: string;
  description: string;
  bbox: { x: number; y: number; w: number; h: number }; // normalised 0..1
  isDependent: boolean;
};

function bboxFromVLM(label: VLMLabel): { x: number; y: number; w: number; h: number } | null {
  if (label.bbox && label.bbox.length >= 4) {
    const [x, y, w, h] = label.bbox;
    return { x, y, w: Math.max(w, 0.02), h: Math.max(h, 0.02) };
  }
  if (label.approximate_position && label.approximate_position.length >= 2) {
    const [cx, cy] = label.approximate_position;
    return { x: cx - 0.025, y: cy - 0.025, w: 0.05, h: 0.05 };
  }
  return null;
}

function buildHotspots(figureMap: FigureMap | null, rows: ClaimMapRow[]): Hotspot[] {
  if (!figureMap) return [];
  const numberToComponent = new Map<string, ClaimMapRow>();
  for (const row of rows) {
    if (row.figure_number) {
      numberToComponent.set(row.figure_number, row);
    }
  }
  // If claim_map.json doesn't carry figure_number (old data), fall back to
  // figureMap.component_to_number.
  if (numberToComponent.size === 0) {
    const inverse: Record<string, string> = {};
    for (const [cid, num] of Object.entries(figureMap.component_to_number || {})) {
      inverse[num] = cid;
    }
    for (const label of figureMap.vlm_labels || []) {
      const cid = inverse[String(label.number)];
      if (!cid) continue;
      const row = rows.find((r) => r.component_id === cid);
      if (!row) continue;
      const bb = bboxFromVLM(label);
      if (!bb) continue;
      numberToComponent.set(String(label.number), row);
    }
  }

  const hotspots: Hotspot[] = [];
  for (const label of figureMap.vlm_labels || []) {
    const num = String(label.number || "").trim();
    if (!num) continue;
    const row = numberToComponent.get(num);
    if (!row) continue;
    const bb = bboxFromVLM(label);
    if (!bb) continue;
    hotspots.push({
      componentId: row.component_id,
      number: num,
      description: label.description || row.label,
      bbox: bb,
      isDependent: row.is_dependent,
    });
  }
  return hotspots;
}

export function FigurePanel(props: Props) {
  const {
    imageUrl, figureMap, rows, selectedId, hoveredId, onSelect, onHover,
    hotspotsCanonical,
  } = props;
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null);

  const hotspots = useMemo<Hotspot[]>(() => {
    // V11-31: prefer the canonical figure_hotspots.json with raw
    // image-pixel coordinates. Convert to normalised [0..1] for
    // CSS percentage rendering. Fall back to the v1.0 path
    // (figure_map.vlm_labels) when the canonical file is missing.
    if (hotspotsCanonical && hotspotsCanonical.hotspots.length > 0) {
      const W = Math.max(hotspotsCanonical.image_width_px, 1);
      const H = Math.max(hotspotsCanonical.image_height_px, 1);
      const rowsById = new Map<string, ClaimMapRow>();
      for (const r of rows) rowsById.set(r.component_id, r);
      const out: Hotspot[] = [];
      for (const h of hotspotsCanonical.hotspots) {
        if (!h.component_id) continue;
        const row = rowsById.get(h.component_id);
        if (!row) continue;
        const [x0, y0, x1, y1] = h.bbox_px;
        const x = x0 / W;
        const y = y0 / H;
        const w = Math.max((x1 - x0) / W, 0.02);
        const hs = Math.max((y1 - y0) / H, 0.02);
        out.push({
          componentId: h.component_id,
          number: h.callout_number,
          description: h.label || row.label,
          bbox: { x, y, w, h: hs },
          isDependent: row.is_dependent,
        });
      }
      return out;
    }
    return buildHotspots(figureMap, rows);
  }, [figureMap, rows, hotspotsCanonical]);

  useEffect(() => {
    setImgSize(null);
  }, [imageUrl]);

  if (!imageUrl) {
    return (
      <div className="figure-panel-empty">
        <div>
          <div className="figure-panel-empty-title">No figure available</div>
          <div className="figure-panel-empty-sub">
            This example does not have a `figure_map.json`. Pick another from the
            dropdown above to see the figure panel light up.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="figure-panel" onClick={(e) => {
      // Click on empty area = deselect.
      if (e.target === e.currentTarget) onSelect(null);
    }}>
      <div className="figure-panel-header">
        <span className="figure-panel-title">
          {figureMap?.primary_figure ?? "Figure"}
        </span>
        <span className="figure-panel-meta">
          {hotspots.length} hotspot{hotspots.length === 1 ? "" : "s"}
        </span>
      </div>
      <div className="figure-stage">
        <img
          ref={imgRef}
          className="figure-image"
          src={imageUrl}
          alt="Patent figure"
          onLoad={(e) => {
            const t = e.currentTarget;
            setImgSize({ w: t.naturalWidth, h: t.naturalHeight });
          }}
          draggable={false}
        />
        {imgSize && hotspots.map((h) => {
          const isSelected = selectedId === h.componentId;
          const isHovered = hoveredId === h.componentId && !isSelected;
          const cls = [
            "figure-hotspot",
            h.isDependent ? "dependent" : "independent",
            isSelected ? "selected" : "",
            isHovered ? "hovered" : "",
          ].filter(Boolean).join(" ");
          return (
            <div
              key={`${h.componentId}-${h.number}`}
              className={cls}
              style={{
                left: `${h.bbox.x * 100}%`,
                top: `${h.bbox.y * 100}%`,
                width: `${h.bbox.w * 100}%`,
                height: `${h.bbox.h * 100}%`,
              }}
              onClick={(e) => {
                e.stopPropagation();
                onSelect(isSelected ? null : h.componentId);
              }}
              onMouseEnter={() => onHover(h.componentId)}
              onMouseLeave={() => onHover(null)}
              title={`#${h.number} — ${h.description}`}
            >
              <span className="figure-hotspot-num">{h.number}</span>
            </div>
          );
        })}
      </div>
      {hotspots.length === 0 && (
        <div className="figure-panel-warn">
          The VLM extracted figure labels but none were matched to a claim
          component. The figure is shown without hotspots.
        </div>
      )}
    </div>
  );
}
