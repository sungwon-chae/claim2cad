import { useEffect, useMemo, useState } from "react";
import { ClaimPanel } from "./components/ClaimPanel";
import { FigurePanel } from "./components/FigurePanel";
import { KinematicSliders } from "./components/KinematicSliders";
import { PriorArtOverlay } from "./components/PriorArtOverlay";
import { Scene } from "./components/Scene";
import { loadDiff, loadExample, loadManifest, type LoadedExample } from "./data";
import type { ManifestExample, PriorArtDiff, URDFJoint } from "./types";
import { loadUrdf } from "./urdf";

type LoadedExamplePlus = LoadedExample & { example: ManifestExample };

export function App() {
  const [examples, setExamples] = useState<ManifestExample[] | null>(null);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<LoadedExamplePlus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [limitationFocus, setLimitationFocus] = useState<boolean>(false);
  const [filterFullMappingOnly, setFilterFullMappingOnly] = useState<boolean>(false);

  // V1-5 prior-art state.
  const [activeDiffId, setActiveDiffId] = useState<string | null>(null);
  const [activeDiff, setActiveDiff] = useState<PriorArtDiff | null>(null);

  // V1-6 kinematic state.
  const [joints, setJoints] = useState<URDFJoint[]>([]);
  const [jointValues, setJointValues] = useState<Record<string, number>>({});
  const [showKinematics, setShowKinematics] = useState<boolean>(false);

  // Initial manifest load.
  useEffect(() => {
    loadManifest()
      .then((m) => {
        setExamples(m.examples);
        const fromHash = window.location.hash.replace(/^#/, "");
        const fallback = m.examples[0]?.id ?? null;
        setCurrentId(
          fromHash && m.examples.some((e) => e.id === fromHash) ? fromHash : fallback
        );
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
    setActiveDiffId(null);
    setActiveDiff(null);
    setJoints([]);
    setJointValues({});
    setShowKinematics(false);
    window.location.hash = ex.id;
    loadExample(ex)
      .then((bundle) => setLoaded({ example: ex, ...bundle }))
      .catch((e) => setError(String(e)));
  }, [currentId, examples]);

  // V1-6 — load URDF whenever a new example is loaded that has one.
  useEffect(() => {
    if (!loaded?.example.urdf_path) {
      setJoints([]);
      return;
    }
    const url = `/data/${loaded.example.base}/${loaded.example.urdf_path}`;
    loadUrdf(url)
      .then((js) => {
        setJoints(js);
        const initial: Record<string, number> = {};
        for (const j of js) {
          if (j.type === "revolute" || j.type === "continuous" || j.type === "prismatic") {
            initial[j.name] = 0;
          }
        }
        setJointValues(initial);
      })
      .catch((err) => {
        console.warn("URDF load failed:", err);
        setJoints([]);
      });
  }, [loaded]);

  // Load the chosen diff JSON whenever activeDiffId changes.
  useEffect(() => {
    if (!loaded || !activeDiffId) {
      setActiveDiff(null);
      return;
    }
    const summary = (loaded.example.diffs_available || []).find(
      (d) => d.comparison_id === activeDiffId
    );
    if (!summary) return;
    loadDiff(loaded.example, summary.diff_path)
      .then(setActiveDiff)
      .catch((e) => {
        console.warn("Failed to load diff:", e);
        setActiveDiff(null);
      });
  }, [loaded, activeDiffId]);

  const availableDiffs = loaded?.example.diffs_available ?? [];

  const visibleExamples = useMemo(() => {
    if (!examples) return [];
    if (filterFullMappingOnly) {
      return examples.filter(
        (e) => (e.figure_coverage ?? 0) >= 0.999 || (e.tags ?? []).includes("full_figure_mapping")
      );
    }
    return examples;
  }, [examples, filterFullMappingOnly]);

  const hasFigure = !!(loaded?.figureImageUrl && loaded?.figureMap);
  const hasDiff = !!activeDiff;
  const movableJoints = useMemo(
    () => joints.filter((j) => j.type === "revolute" || j.type === "continuous" || j.type === "prismatic"),
    [joints]
  );
  const hasKinematics = movableJoints.length > 0;
  const kinematicsActive = showKinematics && hasKinematics;
  // When a diff is active OR kinematic sliders requested, the right
  // pane shows that instead of the figure panel.
  const showRightPane = hasFigure || hasDiff || kinematicsActive;

  return (
    <div className="app">
      <header className="app-header">
        <h1>CLAIM2CAD</h1>
        {visibleExamples.length > 0 && currentId && (
          <select
            value={currentId}
            onChange={(e) => setCurrentId(e.target.value)}
            aria-label="Example selector"
          >
            <optgroup label="Synthetic">
              {visibleExamples.filter((e) => e.source !== "real_patent").map((e) => (
                <option key={e.id} value={e.id}>{e.title}</option>
              ))}
            </optgroup>
            <optgroup label="Real patents">
              {visibleExamples.filter((e) => e.source === "real_patent").map((e) => (
                <option key={e.id} value={e.id}>
                  {coverageBadge(e.figure_coverage ?? 0)} {e.title}
                </option>
              ))}
            </optgroup>
          </select>
        )}
        <button
          className={filterFullMappingOnly ? "active" : ""}
          onClick={() => setFilterFullMappingOnly((v) => !v)}
          title="Show only patents whose IR components were 100% mapped to figure numbers"
        >
          {filterFullMappingOnly ? "★ full-mapping only" : "all examples"}
        </button>
        {availableDiffs.length > 0 && (
          <select
            value={activeDiffId ?? ""}
            onChange={(e) => setActiveDiffId(e.target.value || null)}
            aria-label="Compare against prior art"
            title="Compare this claim's IR against another patent"
            className={hasDiff ? "active-select" : ""}
          >
            <option value="">Compare to prior art…</option>
            {availableDiffs.map((d) => (
              <option key={d.comparison_id} value={d.comparison_id}>
                vs. {d.comparison_title} ({d.matched}/{d.matched + d.novel_in_base + d.only_in_comparison})
              </option>
            ))}
          </select>
        )}
        <span className="grow" />
        {hasKinematics && (
          <button
            className={kinematicsActive ? "active" : ""}
            onClick={() => setShowKinematics((v) => !v)}
            title={`This example has ${movableJoints.length} movable joints`}
          >
            {kinematicsActive ? "Joints: ON" : `Joints (${movableJoints.length})`}
          </button>
        )}
        <button
          className={limitationFocus ? "active" : ""}
          onClick={() => setLimitationFocus((v) => !v)}
          title="Show only the independent claim's components"
        >
          {limitationFocus ? "Limitation focus: ON" : "Limitation focus: off"}
        </button>
      </header>

      <div className={`split ${showRightPane ? "" : "two-pane"}`}>
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
                <span><span className="swatch independent" /> independent</span>
                <span><span className="swatch dependent" /> dependent</span>
                <span><span className="swatch selected" /> selected</span>
                {loaded.example.figure_coverage !== undefined && (
                  <span style={{ marginLeft: "auto" }}>
                    figure coverage:{" "}
                    {Math.round((loaded.example.figure_coverage ?? 0) * 100)}%
                  </span>
                )}
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
              diff={activeDiff}
              joints={kinematicsActive ? joints : undefined}
              jointValues={kinematicsActive ? jointValues : undefined}
            />
          )}
          {loaded && (
            <div className="scene-status">
              {hasDiff && (
                <span style={{ color: "var(--accent-novel, #56d97a)" }}>
                  diff active —
                </span>
              )}{" "}
              {selectedId
                ? `Selected: ${labelOf(loaded, selectedId)}`
                : hoveredId
                  ? `Hover: ${labelOf(loaded, hoveredId)}`
                  : "Click a span / hotspot / part to select."}
            </div>
          )}
        </div>

        {/* Right pane: kinematic sliders if requested, else prior-art
            overlay if active, else figure panel. */}
        {showRightPane && loaded && (
          <div className="pane figure">
            {kinematicsActive ? (
              <KinematicSliders
                joints={joints}
                values={jointValues}
                onChange={(name, v) =>
                  setJointValues((prev) => ({ ...prev, [name]: v }))
                }
                onReset={() =>
                  setJointValues(
                    Object.fromEntries(movableJoints.map((j) => [j.name, 0]))
                  )
                }
              />
            ) : hasDiff ? (
              <PriorArtOverlay
                diff={activeDiff}
                comparisonTitle={
                  availableDiffs.find((d) => d.comparison_id === activeDiffId)
                    ?.comparison_title ?? activeDiffId ?? ""
                }
                selectedId={selectedId}
                hoveredId={hoveredId}
                onSelect={setSelectedId}
                onHover={setHoveredId}
                onClose={() => setActiveDiffId(null)}
              />
            ) : (
              <FigurePanel
                imageUrl={loaded.figureImageUrl}
                figureMap={loaded.figureMap}
                rows={loaded.claimMap.components}
                selectedId={selectedId}
                hoveredId={hoveredId}
                onSelect={setSelectedId}
                onHover={setHoveredId}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function labelOf(loaded: LoadedExamplePlus, id: string): string {
  const row = loaded.claimMap.components.find((c) => c.component_id === id);
  return row ? row.label : id;
}

function coverageBadge(coverage: number): string {
  if (coverage >= 0.999) return "★";
  if (coverage >= 0.5) return "◐";
  if (coverage > 0) return "◷";
  return "○";
}
