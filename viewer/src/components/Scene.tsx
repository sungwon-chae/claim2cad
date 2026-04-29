import { Suspense, useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Bounds, OrbitControls, useGLTF } from "@react-three/drei";
import * as THREE from "three";
import type { ClaimMapRow, PriorArtDiff, URDFJoint } from "../types";

type Props = {
  glbUrl: string;
  rows: ClaimMapRow[];
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
  limitationFocus: boolean;
  /** When non-null, mesh tints follow the diff status:
   *  - matched: keep original (white)
   *  - novel_in_base: green
   *  - else: dimmed neutral
   */
  diff?: PriorArtDiff | null;
  /** V1-6: when non-empty, apply joint transforms to the corresponding
   *  child link's GLB node (rotation for revolute/continuous, translation
   *  for prismatic). */
  joints?: URDFJoint[];
  jointValues?: Record<string, number>;
  /** V11-15: camera preset key. When set, the OrbitControls target+camera
   *  snap to that view. */
  cameraPreset?: CameraPreset | null;
};

export type CameraPreset = "top" | "front" | "right" | "left" | "iso" | "iso2";

/** World-space camera positions (relative to scene bounds, normalised
 *  to roughly fit the model). The OrbitControls' target stays at the
 *  scene origin. */
export const CAMERA_PRESETS: Record<CameraPreset, [number, number, number]> = {
  top: [0.001, 1.0, 0.001],
  front: [0.0, 0.0, 1.0],
  right: [1.0, 0.0, 0.0],
  left: [-1.0, 0.0, 0.0],
  iso: [0.7, 0.5, 0.7],
  iso2: [-0.7, 0.5, -0.7],
};

const COLOR_INDEPENDENT = new THREE.Color("#4f8cff");
const COLOR_DEPENDENT = new THREE.Color("#ffb04a");
const COLOR_SELECTED = new THREE.Color("#ffd76a");
const COLOR_HOVER = new THREE.Color("#cfcfd8");
const COLOR_DEFAULT = new THREE.Color("#9396a3");
const COLOR_MATCHED = new THREE.Color("#e6e6ee");        // white-ish
const COLOR_NOVEL = new THREE.Color("#56d97a");           // green
const COLOR_NEUTRAL_DIM = new THREE.Color("#5a5a66");

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
      {props.cameraPreset ? <CameraSnap preset={props.cameraPreset} /> : null}
    </Canvas>
  );
}

function CameraSnap({ preset }: { preset: CameraPreset }) {
  const dir = CAMERA_PRESETS[preset];
  // Use useFrame to snap once after first render (after Bounds fits).
  const snappedRef = useRef(false);
  const previousPresetRef = useRef<CameraPreset | null>(null);
  useFrame((state) => {
    if (previousPresetRef.current !== preset) {
      snappedRef.current = false;
      previousPresetRef.current = preset;
    }
    if (snappedRef.current) return;
    // Place the camera along `dir` at a distance proportional to the
    // current scene bounds. Look at origin.
    const cam = state.camera;
    // Target distance: 1.4 × world bounds radius.
    const radius = cam.position.length() || 1.0;
    const r = Math.max(radius, 0.4) * 1.4;
    cam.position.set(dir[0] * r, dir[1] * r, dir[2] * r);
    cam.lookAt(0, 0, 0);
    cam.updateProjectionMatrix();
    snappedRef.current = true;
  });
  return null;
}

function ModelTree(props: Props) {
  const { glbUrl, rows, selectedId, hoveredId, onSelect, onHover, limitationFocus, diff,
          joints, jointValues } = props;
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

  // Pre-index diff statuses by component_id when a diff is loaded.
  const diffStatus = useMemo(() => {
    if (!diff) return null;
    const map = new Map<string, "matched" | "novel">();
    for (const m of diff.matched) map.set(m.base_id, "matched");
    for (const n of diff.novel_in_base) map.set(n.id, "novel");
    return map;
  }, [diff]);

  // V1-6 — Apply joint transforms to child link nodes.
  // Each child node gets its position reset to its rest position, plus a
  // rotation about the joint axis (revolute/continuous) or a translation
  // along the axis (prismatic).
  const restPositions = useRef<Map<string, [number, number, number, [number, number, number, number]]>>(new Map());
  useEffect(() => {
    // Re-cache rest positions when scene changes.
    restPositions.current.clear();
    nodeIndex.forEach((_, nodeName) => {
      const obj = scene.getObjectByName(nodeName);
      if (!obj) return;
      restPositions.current.set(nodeName, [
        obj.position.x, obj.position.y, obj.position.z,
        [obj.quaternion.x, obj.quaternion.y, obj.quaternion.z, obj.quaternion.w],
      ]);
    });
  }, [scene, nodeIndex]);

  useEffect(() => {
    if (!joints || joints.length === 0) return;
    for (const joint of joints) {
      if (joint.type !== "revolute" && joint.type !== "continuous" && joint.type !== "prismatic") continue;
      const obj = scene.getObjectByName(joint.child);
      if (!obj) continue;
      const rest = restPositions.current.get(joint.child);
      if (!rest) continue;
      const [rx, ry, rz, [qx, qy, qz, qw]] = rest;

      // Reset to rest first.
      obj.position.set(rx, ry, rz);
      obj.quaternion.set(qx, qy, qz, qw);

      const value = (jointValues || {})[joint.name] ?? 0;
      if (Math.abs(value) < 1e-6) continue;

      const axis = new THREE.Vector3(...joint.axis).normalize();
      if (joint.type === "prismatic") {
        const offset = axis.clone().multiplyScalar(value);
        obj.position.set(rx + offset.x, ry + offset.y, rz + offset.z);
      } else {
        // Rotate child about the joint origin (which is in the parent's frame).
        // We pivot the child's mesh around the joint origin: translate so origin
        // is at the world origin, rotate, translate back.
        const pivotWorld = new THREE.Vector3(...joint.origin);
        // Joint origin is given relative to the parent in URDF; in our scene,
        // both parent and child are siblings of the GLB root, so the joint
        // origin is approximately at (parent_world_pos + joint.origin).
        const parentObj = scene.getObjectByName(joint.parent);
        const parentWorld = new THREE.Vector3();
        if (parentObj) parentObj.getWorldPosition(parentWorld);
        pivotWorld.add(parentWorld);

        // We're operating in local space of the GLB scene root, so use parent's
        // local position as pivot reference.
        const pivot = parentObj
          ? new THREE.Vector3(parentObj.position.x, parentObj.position.y, parentObj.position.z)
              .add(new THREE.Vector3(...joint.origin))
          : new THREE.Vector3(...joint.origin);

        const rotQ = new THREE.Quaternion().setFromAxisAngle(axis, value);
        // child_pos' = pivot + rotQ · (child_pos - pivot)
        const offset = new THREE.Vector3(rx, ry, rz).sub(pivot).applyQuaternion(rotQ);
        obj.position.copy(pivot.clone().add(offset));
        // Apply rotation to child's quaternion.
        const restQ = new THREE.Quaternion(qx, qy, qz, qw);
        obj.quaternion.copy(rotQ.clone().multiply(restQ));
      }
    }
  }, [scene, joints, jointValues, nodeIndex]);

  // Apply highlight materials whenever selection / hover / focus / diff change.
  useEffect(() => {
    nodeIndex.forEach((meshes, nodeName) => {
      const row = rowsById.get(nodeName);
      const isSelected = selectedId === nodeName;
      const isHovered = hoveredId === nodeName && !isSelected;
      const isDimmedByFocus = limitationFocus && row?.is_dependent;

      let baseColor: THREE.Color;
      if (diffStatus) {
        const status = diffStatus.get(nodeName);
        if (status === "novel") baseColor = COLOR_NOVEL.clone();
        else if (status === "matched") baseColor = COLOR_MATCHED.clone();
        else baseColor = COLOR_NEUTRAL_DIM.clone();
      } else {
        baseColor = row
          ? row.is_dependent
            ? COLOR_DEPENDENT
            : COLOR_INDEPENDENT
          : COLOR_DEFAULT;
      }

      for (const mesh of meshes) {
        const tinted = createTintedMaterial({
          baseColor,
          isSelected,
          isHovered,
          isDimmed: !!isDimmedByFocus,
          dimSelectedElsewhere: !!selectedId && !isSelected && !isHovered,
        });
        mesh.material = tinted;
      }
    });
  }, [nodeIndex, rowsById, selectedId, hoveredId, limitationFocus, diffStatus]);

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
