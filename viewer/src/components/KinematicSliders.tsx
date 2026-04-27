import type { URDFJoint } from "../types";

type Props = {
  joints: URDFJoint[];
  values: Record<string, number>;
  onChange: (jointName: string, value: number) => void;
  onReset: () => void;
};

export function KinematicSliders(props: Props) {
  const movable = props.joints.filter(
    (j) => j.type === "revolute" || j.type === "prismatic" || j.type === "continuous"
  );

  if (movable.length === 0) {
    return (
      <div className="kinematic-empty">
        No movable joints in this URDF — every joint is <code>fixed</code>.
      </div>
    );
  }

  return (
    <div className="kinematic-panel">
      <div className="kinematic-header">
        <span className="kinematic-title">Joints ({movable.length})</span>
        <button className="kinematic-reset" onClick={props.onReset}>
          Reset
        </button>
      </div>
      {movable.map((j) => {
        const value = props.values[j.name] ?? 0;
        const lower = j.limit?.lower ?? -Math.PI;
        const upper = j.limit?.upper ?? Math.PI;
        const step = j.type === "prismatic" ? 0.001 : 0.02;
        const display = j.type === "prismatic"
          ? `${(value * 1000).toFixed(0)} mm`
          : `${((value / Math.PI) * 180).toFixed(0)}°`;
        return (
          <div key={j.name} className="kinematic-row">
            <div className="kinematic-row-head">
              <span className="kinematic-joint-name">{j.name}</span>
              <span className="kinematic-joint-value">{display}</span>
            </div>
            <input
              type="range"
              min={lower}
              max={upper}
              step={step}
              value={value}
              onChange={(e) => props.onChange(j.name, Number(e.target.value))}
            />
            <div className="kinematic-row-meta">
              <span>{j.type}</span>
              <span>parent {j.parent} → child {j.child}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
