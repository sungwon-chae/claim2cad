import { useEffect, useState } from "react";
import { ClaimPanel } from "./components/ClaimPanel";
import { Scene } from "./components/Scene";
import { loadExample, loadManifest } from "./data";
import type { ClaimIR, ClaimMap, ManifestExample } from "./types";

type LoadedExample = {
  example: ManifestExample;
  claimText: string;
  ir: ClaimIR;
  claimMap: ClaimMap;
  glbUrl: string;
};

export function App() {
  const [examples, setExamples] = useState<ManifestExample[] | null>(null);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<LoadedExample | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [limitationFocus, setLimitationFocus] = useState<boolean>(false);

  // Initial manifest load.
  useEffect(() => {
    loadManifest()
      .then((m) => {
        setExamples(m.examples);
        const fromHash = window.location.hash.replace(/^#/, "");
        const fallback = m.examples[0]?.id ?? null;
        setCurrentId(fromHash && m.examples.some((e) => e.id === fromHash) ? fromHash : fallback);
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Whenever currentId changes, fetch the example bundle.
  useEffect(() => {
    if (!examples || !currentId) return;
    const ex = examples.find((e) => e.id === currentId);
    if (!ex) return;
    setLoaded(null);
    setSelectedId(null);
    setHoveredId(null);
    setError(null);
    window.location.hash = ex.id;
    loadExample(ex)
      .then(({ claimText, ir, claimMap, glbUrl }) =>
        setLoaded({ example: ex, claimText, ir, claimMap, glbUrl })
      )
      .catch((e) => setError(String(e)));
  }, [currentId, examples]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>CLAIM2CAD</h1>
        {examples && examples.length > 0 && currentId && (
          <select
            value={currentId}
            onChange={(e) => setCurrentId(e.target.value)}
            aria-label="Example selector"
          >
            {examples.map((e) => (
              <option key={e.id} value={e.id}>
                {e.title}
              </option>
            ))}
          </select>
        )}
        <span className="grow" />
        <button
          className={limitationFocus ? "active" : ""}
          onClick={() => setLimitationFocus((v) => !v)}
          title="Show only the independent claim's components"
        >
          {limitationFocus ? "Limitation focus: ON" : "Limitation focus: off"}
        </button>
      </header>

      <div className="split">
        {/* Claim text pane */}
        <div className="pane">
          {error && <div className="error-overlay">Error: {error}</div>}
          {!error && !loaded && <div className="error-overlay">Loading…</div>}
          {!error && loaded && (
            <>
              <ClaimPanel
                ir={loaded.ir}
                claimMapRows={loaded.claimMap.components}
                selectedId={selectedId}
                hoveredId={hoveredId}
                onSelect={setSelectedId}
                onHover={setHoveredId}
                limitationFocus={limitationFocus}
              />
              <div className="legend">
                <span>
                  <span className="swatch independent" /> independent
                </span>
                <span>
                  <span className="swatch dependent" /> dependent
                </span>
                <span>
                  <span className="swatch selected" /> selected
                </span>
              </div>
            </>
          )}
        </div>

        {/* 3D scene pane */}
        <div className="pane scene" style={{ position: "relative" }}>
          {!error && loaded && (
            <Scene
              key={loaded.glbUrl}
              glbUrl={loaded.glbUrl}
              rows={loaded.claimMap.components}
              selectedId={selectedId}
              hoveredId={hoveredId}
              onSelect={setSelectedId}
              onHover={setHoveredId}
              limitationFocus={limitationFocus}
            />
          )}
          {loaded && (
            <div className="scene-status">
              {selectedId
                ? `Selected: ${labelOf(loaded, selectedId)}`
                : hoveredId
                  ? `Hover: ${labelOf(loaded, hoveredId)}`
                  : "Click a span or a part to select."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function labelOf(loaded: LoadedExample, id: string): string {
  const row = loaded.claimMap.components.find((c) => c.component_id === id);
  return row ? row.label : id;
}
