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
  const { imageUrl, figureMap, rows, selectedId, hoveredId, onSelect, onHover } = props;
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null);

  const hotspots = useMemo(
    () => buildHotspots(figureMap, rows),
    [figureMap, rows]
  );

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
