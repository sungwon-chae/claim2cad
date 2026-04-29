import { useEffect, useMemo, useState } from "react";
import { ClaimPanel } from "./components/ClaimPanel";
import { FigurePanel } from "./components/FigurePanel";
import { KinematicSliders } from "./components/KinematicSliders";
import { PriorArtOverlay } from "./components/PriorArtOverlay";
import { Scene, type CameraPreset } from "./components/Scene";
import type { FigureHotspotSet } from "./components/FigurePanel";
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

  // V11-15: camera preset for figure-aligned inspection. The "best"
  // preset comes from projection_report.json's best_view (when present).
  const [cameraPreset, setCameraPreset] = useState<CameraPreset | null>(null);
  const [bestView, setBestView] = useState<CameraPreset | null>(null);

  // V11-31: canonical figure hotspots (raw image-pixel coordinates).
  const [hotspots, setHotspots] = useState<FigureHotspotSet | null>(null);

  // V1.2-E: demo / debug mode (persisted via URL query).
  const initialMode = (() => {
    const q = new URLSearchParams(window.location.search).get("mode");
    return q === "debug" ? "debug" : "demo";
  })();
  const [viewerMode, setViewerMode] = useState<"demo" | "debug">(initialMode);

  // Initial manifest load.
  useEffect(() => {
    loadManifest()
      .then((m) => {
        setExamples(m.examples);
        const fromHash = window.location.hash.replace(/^#/, "");
        // V1.2-E: default to the v1.2 demo-quality example so a
        // first-time visitor sees the polished assembly, not
        // whichever synthetic happens to sort first.
        const demoFirst = m.examples.find((e) =>
          (e.tags ?? []).includes("demo_quality"),
        );
        const fallback =
          demoFirst?.id ?? m.examples[0]?.id ?? null;
        setCurrentId(
          fromHash && m.examples.some((e) => e.id === fromHash) ? fromHash : fallback
        );
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Reflect viewer mode in URL so reloads / shared links keep it.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (viewerMode === "debug") params.set("mode", "debug");
    else params.delete("mode");
    const newSearch = params.toString();
    const newUrl =
      window.location.pathname +
      (newSearch ? `?${newSearch}` : "") +
      window.location.hash;
    window.history.replaceState(null, "", newUrl);
  }, [viewerMode]);

  // V11-31: load figure_hotspots.json (when present).
  useEffect(() => {
    if (!loaded) {
      setHotspots(null);
      return;
    }
    const url = `data/${loaded.example.base}/figure_hotspots.json`;
    fetch(url)
      .then((r) => (r.ok ? r.json() : null))
      .then((j: FigureHotspotSet | null) => setHotspots(j))
      .catch(() => setHotspots(null));
  }, [loaded]);

  // V11-15 / V11-27: load projection_report.json + figure_projection.json
  // (when present). The V11-27 default for figure-grounded examples
  // is the "figure" preset — the camera matches the
  // figure_projection.view_type. Otherwise we fall back to V11-15's
  // best_view canonical match.
  useEffect(() => {
    if (!loaded) {
      setBestView(null);
      setCameraPreset(null);
      return;
    }
    const figProjUrl = `data/${loaded.example.base}/figure_projection.json`;
    const projReportUrl = `data/${loaded.example.base}/projection_report.json`;
    const cameraV12Url = `data/${loaded.example.base}/camera_v12.json`;
    Promise.all([
      fetch(figProjUrl).then((r) => (r.ok ? r.json() : null)).catch(() => null),
      fetch(projReportUrl).then((r) => (r.ok ? r.json() : null)).catch(() => null),
      fetch(cameraV12Url).then((r) => (r.ok ? r.json() : null)).catch(() => null),
    ]).then(([figProj, projReport, cameraV12]) => {
      const valid = ["top", "front", "right", "left", "iso", "iso2",
                     "figure", "patent_figure"];
      let best: CameraPreset | null = null;
      if (projReport && projReport.best_view) {
        const cand = projReport.best_view as CameraPreset;
        if (valid.includes(cand)) best = cand;
      }
      // V12-L: if the example has camera_v12.json AND the
      // demo_quality tag, default to the "patent_figure" preset.
      const isDemoQuality = (loaded.example.tags ?? []).includes(
        "demo_quality",
      );
      if (cameraV12 && isDemoQuality) {
        best = "patent_figure";
        setCameraPreset("patent_figure");
      } else if (figProj && figProj.projection) {
        best = "figure";
        setCameraPreset("figure");
      } else {
        setCameraPreset(null);
      }
      setBestView(best);
    });
  }, [loaded]);

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
                  {qualityBadge(e.quality_badge)}
                  {e.mismatch_severity && e.mismatch_severity !== "none" ? " ⚠" : ""}
                  {" "}{e.title}
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
        <button
          className={`mode-toggle ${viewerMode === "debug" ? "active" : ""}`}
          onClick={() =>
            setViewerMode((m) => (m === "demo" ? "debug" : "demo"))
          }
          title="Demo mode hides debug overlays. Debug mode shows hotspot anchors, label hotspots, and group bboxes."
        >
          {viewerMode === "demo" ? "Demo mode" : "Debug mode"}
        </button>
      </header>

      <div className={`split ${showRightPane ? "" : "two-pane"}`}>
        {/* Claim text pane */}
        <div className="pane">
          {error && <div className="error-overlay">Error: {error}</div>}
          {!error && !loaded && <div className="error-overlay">Loading…</div>}
          {!error && loaded && (
            <>
              {loaded.example.source === "real_patent"
                && loaded.example.mismatch_severity
                && loaded.example.mismatch_severity !== "none" && (
                <div className={`mismatch-banner mismatch-${loaded.example.mismatch_severity}`}>
                  {mismatchBadge(loaded.example.mismatch_severity)} —
                  {loaded.example.mismatch_reason
                    ? ` ${loaded.example.mismatch_reason}.`
                    : " classifier topology may not match the patent figure."}
                  {loaded.example.mismatch_expected
                    && loaded.example.mismatch_expected.length > 0
                    && ` Expected family: ${loaded.example.mismatch_expected.join(", ")}.`}
                </div>
              )}
              {loaded.example.source === "real_patent"
                && loaded.example.quality_badge
                && loaded.example.quality_badge !== "flagship" && (
                <div className={`quality-banner quality-${loaded.example.quality_badge}`}>
                  {qualityBadge(loaded.example.quality_badge)} —
                  {loaded.example.quality_badge === "fallback" || loaded.example.quality_badge === "failed"
                    ? " this example uses a fallback grid layout; the rendered geometry is a baseline, not a faithful figure reconstruction."
                    : loaded.example.quality_badge === "partial"
                    ? " this example uses a topology-matched scaffold but is not flagship-polished. Selection + claim/figure interaction work; geometry is approximate."
                    : " this example uses a topology-matched scaffold."}
                </div>
              )}
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
              cameraPreset={cameraPreset}
            />
          )}
          {/* V11-27 camera preset bar — figure-aligned default */}
          {loaded && (
            <div className="camera-presets">
              {(["patent_figure", "figure", "top", "front", "right", "iso"] as const).map(
                (preset) => {
                  const active = cameraPreset === preset;
                  const isBest = bestView === preset;
                  const cls = `camera-preset${active ? " active" : ""}${
                    isBest ? " best" : ""
                  }`;
                  return (
                    <button
                      key={preset}
                      className={cls}
                      onClick={() =>
                        setCameraPreset(active ? null : preset)
                      }
                      title={
                        preset === "patent_figure"
                          ? "Patent figure — V12-L oblique opened-door view"
                          : preset === "figure"
                          ? "figure-aligned — same projection as patent figure (front)"
                          : isBest
                          ? `${preset} — best aspect-match to figure`
                          : `${preset} view`
                      }
                    >
                      {preset === "patent_figure" ? "patent fig." : preset}
                      {isBest ? " ★" : ""}
                    </button>
                  );
                }
              )}
              <button
                className="camera-preset reset"
                onClick={() => setCameraPreset(null)}
                title="Free orbit"
              >
                free
              </button>
            </div>
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
                hotspotsCanonical={hotspots}
                viewerMode={viewerMode}
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

function qualityBadge(quality?: string): string {
  switch (quality) {
    case "flagship": return "★ flagship";
    case "good": return "● good";
    case "partial": return "◐ partial";
    case "fallback": return "○ fallback";
    case "failed": return "× failed";
    default: return "·";
  }
}

function mismatchBadge(severity?: string): string {
  switch (severity) {
    case "warning": return "⚠ semantic mismatch";
    case "advisory": return "⚠ semantic advisory";
    default: return "";
  }
}
