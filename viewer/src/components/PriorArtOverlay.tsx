import { useMemo } from "react";
import type { PriorArtDiff } from "../types";

type Props = {
  diff: PriorArtDiff | null;
  comparisonTitle: string;
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
  onClose: () => void;
};

export function PriorArtOverlay(props: Props) {
  const { diff, comparisonTitle, selectedId, hoveredId, onSelect, onHover, onClose } = props;

  const counts = useMemo(() => {
    if (!diff) return { matched: 0, novel: 0, prior: 0 };
    return {
      matched: diff.matched.length,
      novel: diff.novel_in_base.length,
      prior: diff.only_in_comparison.length,
    };
  }, [diff]);

  if (!diff) return null;

  return (
    <div className="prior-art-overlay">
      <div className="prior-art-header">
        <span className="prior-art-title">vs. {comparisonTitle}</span>
        <button className="prior-art-close" onClick={onClose} title="Close prior-art view">×</button>
      </div>
      <div className="prior-art-counts">
        <span className="diff-chip diff-matched">{counts.matched} matched</span>
        <span className="diff-chip diff-novel">{counts.novel} novel</span>
        <span className="diff-chip diff-prior">{counts.prior} prior-only</span>
      </div>

      <Section title={`Matched (${counts.matched})`} kind="matched">
        {diff.matched.map((m) => (
          <Row
            key={m.base_id}
            id={m.base_id}
            primary={m.base_label}
            secondary={`↔ ${m.comparison_label} · ${(m.score * 100).toFixed(0)}%`}
            kind="matched"
            selected={selectedId === m.base_id}
            hovered={hoveredId === m.base_id}
            onSelect={onSelect}
            onHover={onHover}
          />
        ))}
      </Section>

      <Section title={`Novel in this claim (${counts.novel})`} kind="novel">
        {diff.novel_in_base.map((c) => (
          <Row
            key={c.id}
            id={c.id}
            primary={c.label}
            secondary={`${c.category} · ${c.kind}`}
            kind="novel"
            selected={selectedId === c.id}
            hovered={hoveredId === c.id}
            onSelect={onSelect}
            onHover={onHover}
          />
        ))}
      </Section>

      <Section title={`Only in prior art (${counts.prior})`} kind="prior">
        {diff.only_in_comparison.map((c) => (
          <Row
            key={c.id}
            id={c.id}
            primary={c.label}
            secondary={`${c.category} · ${c.kind}`}
            kind="prior"
            selected={false}
            hovered={false}
            onSelect={() => {}}
            onHover={() => {}}
            unclickable
          />
        ))}
      </Section>

      {diff.notes && diff.notes.length > 0 && (
        <div className="prior-art-notes">
          {diff.notes.map((n, i) => <div key={i}>· {n}</div>)}
        </div>
      )}
    </div>
  );
}

function Section(props: {
  title: string;
  kind: "matched" | "novel" | "prior";
  children: React.ReactNode;
}) {
  return (
    <div className={`prior-art-section section-${props.kind}`}>
      <div className="prior-art-section-title">{props.title}</div>
      <div className="prior-art-section-body">{props.children}</div>
    </div>
  );
}

function Row(props: {
  id: string;
  primary: string;
  secondary?: string;
  kind: "matched" | "novel" | "prior";
  selected: boolean;
  hovered: boolean;
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
  unclickable?: boolean;
}) {
  const cls = [
    "prior-art-row",
    `row-${props.kind}`,
    props.selected ? "selected" : "",
    props.hovered ? "hovered" : "",
    props.unclickable ? "unclickable" : "",
  ].filter(Boolean).join(" ");
  return (
    <div
      className={cls}
      onClick={() => !props.unclickable && props.onSelect(props.selected ? null : props.id)}
      onMouseEnter={() => !props.unclickable && props.onHover(props.id)}
      onMouseLeave={() => !props.unclickable && props.onHover(null)}
    >
      <div className="prior-art-primary">{props.primary}</div>
      {props.secondary && <div className="prior-art-secondary">{props.secondary}</div>}
    </div>
  );
}
