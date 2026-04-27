import { Suspense, useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Bounds, OrbitControls, useGLTF } from "@react-three/drei";
import * as THREE from "three";
import type { ClaimMapRow } from "../types";

type Props = {
  glbUrl: string;
  rows: ClaimMapRow[];
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
  limitationFocus: boolean;
};

const COLOR_INDEPENDENT = new THREE.Color("#4f8cff");
const COLOR_DEPENDENT = new THREE.Color("#ffb04a");
const COLOR_SELECTED = new THREE.Color("#ffd76a");
const COLOR_HOVER = new THREE.Color("#cfcfd8");
const COLOR_DEFAULT = new THREE.Color("#9396a3");

export function Scene(props: Props) {
  return (
    <Canvas
      camera={{ position: [0.4, 0.25, 0.6], fov: 35, near: 0.001, far: 100 }}
      gl={{ antialias: true }}
      onPointerMissed={() => props.onSelect(null)}
    >
      <color attach="background" args={["#0b0b10"]} />
      <ambientLight intensity={0.55} />
      <directionalLight position={[5, 8, 6]} intensity={1.0} />
      <directionalLight position={[-4, 3, -5]} intensity={0.4} />
      <Suspense fallback={null}>
        <Bounds fit clip observe margin={1.4}>
          <ModelTree {...props} />
        </Bounds>
      </Suspense>
      <OrbitControls makeDefault enableDamping dampingFactor={0.12} />
    </Canvas>
  );
}

function ModelTree(props: Props) {
  const { glbUrl, rows, selectedId, hoveredId, onSelect, onHover, limitationFocus } = props;
  const { scene } = useGLTF(glbUrl);

  const rowsById = useMemo(() => {
    const m = new Map<string, ClaimMapRow>();
    for (const r of rows) m.set(r.glb_node_name, r);
    return m;
  }, [rows]);

  // Map: glb_node_name → array of meshes inside that node's subtree.
  const nodeIndex = useMemo(() => {
    const idx = new Map<string, THREE.Mesh[]>();
    scene.traverse((obj) => {
      if (!(obj instanceof THREE.Object3D)) return;
      const isComponentRoot = rowsById.has(obj.name);
      if (!isComponentRoot) return;
      const meshes: THREE.Mesh[] = [];
      obj.traverse((child) => {
        if (child instanceof THREE.Mesh) {
          meshes.push(child);
          if (!child.userData.componentId) {
            child.userData.componentId = obj.name;
          }
        }
      });
      idx.set(obj.name, meshes);
    });
    return idx;
  }, [scene, rowsById]);

  // Original-material cache so we can restore on deselect.
  const originalRef = useRef<Map<THREE.Mesh, THREE.Material | THREE.Material[]>>(new Map());
  useEffect(() => {
    const cache = originalRef.current;
    cache.clear();
    nodeIndex.forEach((meshes) => {
      for (const m of meshes) cache.set(m, m.material);
    });
  }, [nodeIndex]);

  // Apply highlight materials whenever selection / hover / focus changes.
  useEffect(() => {
    nodeIndex.forEach((meshes, nodeName) => {
      const row = rowsById.get(nodeName);
      const isSelected = selectedId === nodeName;
      const isHovered = hoveredId === nodeName && !isSelected;
      const isDimmedByFocus = limitationFocus && row?.is_dependent;

      for (const mesh of meshes) {
        const tinted = createTintedMaterial({
          baseColor: row
            ? row.is_dependent
              ? COLOR_DEPENDENT
              : COLOR_INDEPENDENT
            : COLOR_DEFAULT,
          isSelected,
          isHovered,
          isDimmed: !!isDimmedByFocus,
          dimSelectedElsewhere: !!selectedId && !isSelected && !isHovered,
        });
        mesh.material = tinted;
      }
    });
  }, [nodeIndex, rowsById, selectedId, hoveredId, limitationFocus]);

  return (
    <primitive
      object={scene}
      onClick={(e: any) => {
        e.stopPropagation();
        const id = walkUpForComponentId(e.object, rowsById);
        if (id) onSelect(id === selectedId ? null : id);
      }}
      onPointerMove={(e: any) => {
        e.stopPropagation();
        const id = walkUpForComponentId(e.object, rowsById);
        if (id !== hoveredId) onHover(id);
      }}
      onPointerOut={() => onHover(null)}
    />
  );
}

function walkUpForComponentId(
  obj: THREE.Object3D | null,
  rowsById: Map<string, unknown>
): string | null {
  let cur: THREE.Object3D | null = obj;
  while (cur) {
    if (cur.name && rowsById.has(cur.name)) return cur.name;
    cur = cur.parent;
  }
  return null;
}

function createTintedMaterial(opts: {
  baseColor: THREE.Color;
  isSelected: boolean;
  isHovered: boolean;
  isDimmed: boolean;
  dimSelectedElsewhere: boolean;
}): THREE.MeshStandardMaterial {
  const color = opts.isSelected
    ? COLOR_SELECTED.clone()
    : opts.isHovered
      ? COLOR_HOVER.clone()
      : opts.baseColor.clone();
  const opacity = opts.isDimmed ? 0.15 : opts.dimSelectedElsewhere ? 0.32 : 1.0;
  const emissive = opts.isSelected
    ? COLOR_SELECTED.clone().multiplyScalar(0.35)
    : opts.isHovered
      ? COLOR_HOVER.clone().multiplyScalar(0.18)
      : new THREE.Color("#000000");
  const mat = new THREE.MeshStandardMaterial({
    color,
    metalness: 0.05,
    roughness: 0.55,
    emissive,
    transparent: opacity < 1,
    opacity,
  });
  return mat;
}

// Helper used by App to bust drei's GLTF cache when switching examples.
export function preloadGlb(url: string) {
  useGLTF.preload(url);
}

// Tiny per-frame rotator we don't actually mount — exported only to silence
// the "useFrame imported but unused" lint when stripped down. Importing is
// harmless and lets future stretch features add it without churn.
export function _UnusedFrameProbe() {
  useFrame(() => {});
  return null;
}
