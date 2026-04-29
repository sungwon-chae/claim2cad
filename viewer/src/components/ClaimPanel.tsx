import { useEffect, useMemo, useRef } from "react";
import type { ClaimIR, ClaimMapRow, IRWherein } from "../types";

type Props = {
  ir: ClaimIR;
  claimMapRows: ClaimMapRow[];
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
  limitationFocus: boolean;
};

// Build the span set for one claim's text:
// - one entry per Component whose source_span.claim_id matches
// - plus one "wherein" anchor per matching WhereinClause (italic styling)
function buildSpansForClaim(
  claimId: string,
  components: { id: string; isDependent: boolean; start: number; end: number; mapped: boolean }[],
  whereinClauses: IRWherein[]
): { id: "wherein" | string; isDependent: boolean; start: number; end: number; mapped: boolean }[] {
  const spans: ReturnType<typeof buildSpansForClaim> = [];
  for (const c of components) {
    spans.push({ id: c.id, isDependent: c.isDependent, start: c.start, end: c.end, mapped: c.mapped });
  }
  for (const w of whereinClauses) {
    if (w.source_span.claim_id !== claimId) continue;
    spans.push({
      id: "wherein",
      isDependent: false,
      start: w.source_span.char_start,
      end: w.source_span.char_end,
      mapped: false,
    });
  }
  // V11-13: drop sentinel zero-length spans and ill-formed ranges
  // before sorting. The pipeline writes (0, 0) for components whose
  // label could not be relocated in the claim text — we don't want
  // those rendered as a wrong-substring underline.
  const filtered = spans.filter((s) => s.end > s.start);
  filtered.sort((a, b) => a.start - b.start || a.end - b.end);
  const cleaned: typeof filtered = [];
  let cursor = 0;
  for (const span of filtered) {
    if (span.start < cursor) continue;
    cleaned.push(span);
    cursor = span.end;
  }
  return cleaned;
}

export function ClaimPanel(props: Props) {
  const { ir, claimMapRows, selectedId, hoveredId, onSelect, onHover, limitationFocus } = props;

  const mapById = useMemo(() => {
    const m = new Map<string, ClaimMapRow>();
    for (const row of claimMapRows) m.set(row.component_id, row);
    return m;
  }, [claimMapRows]);

  const selectedRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    if (selectedId && selectedRef.current) {
      selectedRef.current.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [selectedId]);

  const onPanelClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) {
      onSelect(null);
    }
  };

  return (
    <div className="claim-panel" onClick={onPanelClick}>
      <h2>{ir.title}</h2>
      {ir.claims.map((claim) => {
        const componentsHere = ir.components
          .filter((c) => c.source_span.claim_id === claim.id)
          .map((c) => ({
            id: c.id,
            isDependent: c.is_dependent,
            start: c.source_span.char_start,
            end: c.source_span.char_end,
            mapped: mapById.has(c.id),
          }));
        const spans = buildSpansForClaim(claim.id, componentsHere, ir.wherein_clauses);
        const blockClass = `claim-block ${claim.is_independent ? "independent" : "dependent"}`;
        const dimmed = limitationFocus && !claim.is_independent;
        return (
          <div
            key={claim.id}
            className={blockClass}
            style={dimmed ? { opacity: 0.4 } : undefined}
          >
            <div style={{ fontSize: 11, color: "var(--fg-1)", marginBottom: 4 }}>
              {claim.id} ({claim.is_independent ? "independent" : `dependent on ${claim.depends_on}`})
            </div>
            <div>
              {renderText(claim.text, spans, {
                selectedId,
                hoveredId,
                onSelect,
                onHover,
                selectedRef,
              })}
            </div>
          </div>
        );
      })}

      <div style={{ fontSize: 11, color: "var(--fg-1)", marginTop: 16 }}>
        {claimMapRows.length} components mapped to GLB nodes.
      </div>
    </div>
  );
}

type RenderCtx = {
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
  selectedRef: React.MutableRefObject<HTMLSpanElement | null>;
};

function renderText(
  text: string,
  spans: ReturnType<typeof buildSpansForClaim>,
  ctx: RenderCtx
): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let cursor = 0;
  spans.forEach((span, idx) => {
    if (span.start > cursor) {
      out.push(text.slice(cursor, span.start));
    }
    const slice = text.slice(span.start, span.end);
    if (span.id === "wherein") {
      out.push(
        <span key={`w-${idx}`} className="claim-wherein">
          {slice}
        </span>
      );
    } else {
      const id = span.id;
      const isSelected = ctx.selectedId === id;
      const isHovered = ctx.hoveredId === id && !isSelected;
      const cls = [
        "claim-span",
        span.isDependent ? "dependent" : "independent",
        !span.mapped ? "unmapped" : "",
        isSelected ? "selected" : "",
        isHovered ? "hovered" : "",
      ]
        .filter(Boolean)
        .join(" ");
      out.push(
        <span
          key={`c-${idx}-${id}`}
          ref={isSelected ? ctx.selectedRef : undefined}
          className={cls}
          data-component-id={id}
          onClick={(e) => {
            e.stopPropagation();
            ctx.onSelect(isSelected ? null : id);
          }}
          onMouseEnter={() => ctx.onHover(id)}
          onMouseLeave={() => ctx.onHover(null)}
        >
          {slice}
          {!span.mapped && <span className="badge-unmapped" title="Not yet visualized">?</span>}
        </span>
      );
    }
    cursor = span.end;
  });
  if (cursor < text.length) out.push(text.slice(cursor));
  return out;
}
