"""Hand-crafted golden generator for the robot-arm example.

Each build123d shape has its ``label`` set to the matching IR component ID so
that the GLB node name matches the entries in ``claim_map.json``. This is the
gold standard the Phase-3 ``ir_to_cad.synthesize_generator`` aims to mimic.

Run::

    python examples/golden_robot_arm/generator.py

It writes ``model.step`` and ``model.glb`` next to this file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import build123d as bd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from claim2cad.glb_naming import rename_glb_root_children  # noqa: E402

# Order matters: matches the order children are added to the root Compound.
COMPONENT_ORDER = [
    "base",
    "fastener",
    "first_joint",
    "first_link",
    "second_joint",
    "second_link",
    "end_effector",
    "gripper",
    "position_sensor",
]


def _named(shape: bd.Shape, name: str) -> bd.Shape:
    shape.label = name
    return shape


def gen_step() -> dict:
    """Return a build123d envelope compatible with ``gen_step_part``."""
    base = _named(
        bd.Box(80, 80, 20).translate((0, 0, 10)),
        "base",
    )
    fastener = _named(
        bd.Cylinder(4, 12).translate((0, 0, -6)),
        "fastener",
    )
    first_joint = _named(
        bd.Cylinder(8, 16).translate((0, 0, 28)),
        "first_joint",
    )
    first_link = _named(
        bd.Box(60, 16, 16).translate((30, 0, 28)),
        "first_link",
    )
    second_joint = _named(
        bd.Cylinder(7, 14, rotation=(90, 0, 0)).translate((60, 0, 28)),
        "second_joint",
    )
    second_link = _named(
        bd.Box(60, 14, 14).translate((90, 0, 28)),
        "second_link",
    )
    end_effector = _named(
        bd.Box(20, 30, 14).translate((125, 0, 28)),
        "end_effector",
    )
    # Gripper sits at the very tip of the second link, "contained" by the
    # end_effector. We model it as two small finger-blocks.
    grip_left = bd.Box(12, 4, 14).translate((140, 12, 28))
    grip_right = bd.Box(12, 4, 14).translate((140, -12, 28))
    gripper = _named(grip_left + grip_right, "gripper")

    # Dependent claim: a position sensor on the second link.
    position_sensor = _named(
        bd.Sphere(5).translate((90, 12, 36)),
        "position_sensor",
    )

    children = [
        base,
        fastener,
        first_joint,
        first_link,
        second_joint,
        second_link,
        end_effector,
        gripper,
        position_sensor,
    ]
    root = bd.Compound(label="robot_arm", children=children)

    return {"shape": root, "step_output": "model.step"}


def main() -> None:
    envelope = gen_step()
    shape: bd.Compound = envelope["shape"]
    step_path = HERE / envelope["step_output"]
    glb_path = HERE / "model.glb"
    bd.export_step(shape, str(step_path))
    ok = bd.export_gltf(
        shape,
        str(glb_path),
        binary=True,
        linear_deflection=0.5,
        angular_deflection=0.5,
    )
    if not ok:
        raise RuntimeError(f"Failed to export GLB: {glb_path}")
    rename_glb_root_children(glb_path, COMPONENT_ORDER)
    print(f"Wrote {step_path.name} ({step_path.stat().st_size:,} B)")
    print(f"Wrote {glb_path.name} ({glb_path.stat().st_size:,} B)")


if __name__ == "__main__":
    main()
