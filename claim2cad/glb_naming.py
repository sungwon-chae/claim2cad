"""GLB node-renaming helper.

build123d's ``export_gltf`` emits OpenCascade OCAF reference strings as node
names (e.g. ``"=>[0:1:1:2]"``) rather than the ``Shape.label``s we set. The
viewer's mesh-name → component-id lookup needs deterministic, human-readable
names, so we post-process the GLB JSON chunk: walk the root's children and
rename each in insertion order from a caller-supplied list.

This is the simplest fix that survives the build123d → STEP → GLB pipeline
without having to fork build123d's exporter or generate per-component GLBs.
"""
from __future__ import annotations

import json
import logging
import struct
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

_GLB_MAGIC = b"glTF"
_JSON_CHUNK_TYPE = b"JSON"


def rename_glb_root_children(glb_path: Path, ordered_names: Sequence[str]) -> None:
    """Rename the immediate children of the root scene's root node.

    The root scene is taken from ``scenes[scene]`` (default ``scene=0``). Its
    first node is the root; the renaming targets that root's ``children``
    list, in order. Surplus or missing names are tolerated: extras are
    ignored, missing ones leave the existing name in place.

    Raises:
        ValueError: if the file is not a binary glTF or the JSON chunk is
            missing.
    """
    glb_bytes = glb_path.read_bytes()
    if glb_bytes[:4] != _GLB_MAGIC:
        raise ValueError(f"{glb_path} is not a binary glTF file")

    json_chunk_len = struct.unpack("<I", glb_bytes[12:16])[0]
    if glb_bytes[16:20] != _JSON_CHUNK_TYPE:
        raise ValueError(f"{glb_path}: first chunk is not JSON")

    json_start = 20
    json_end = json_start + json_chunk_len
    json_blob = glb_bytes[json_start:json_end].decode("utf-8")
    parsed = json.loads(json_blob)

    scene_index = int(parsed.get("scene", 0))
    scenes = parsed.get("scenes") or [{"nodes": []}]
    scene_root_indices = scenes[scene_index].get("nodes", [])
    if not scene_root_indices:
        raise ValueError(f"{glb_path}: scene {scene_index} has no root nodes")

    nodes = parsed["nodes"]
    root_node = nodes[scene_root_indices[0]]
    child_indices = root_node.get("children", [])

    renamed = 0
    for slot, name in enumerate(ordered_names):
        if slot >= len(child_indices):
            logger.warning(
                "GLB %s has fewer root children (%d) than names supplied (%d)",
                glb_path.name,
                len(child_indices),
                len(ordered_names),
            )
            break
        target_node = nodes[child_indices[slot]]
        target_node["name"] = name
        renamed += 1

    new_json_blob = json.dumps(parsed, separators=(",", ":")).encode("utf-8")
    pad_len = (4 - (len(new_json_blob) % 4)) % 4
    new_json_blob += b" " * pad_len

    binary_chunk = glb_bytes[json_end:]  # everything after the JSON chunk

    new_json_chunk_header = struct.pack("<I", len(new_json_blob)) + _JSON_CHUNK_TYPE
    new_total = 12 + len(new_json_chunk_header) + len(new_json_blob) + len(binary_chunk)
    new_header = (
        _GLB_MAGIC
        + struct.pack("<I", 2)  # glTF version
        + struct.pack("<I", new_total)
    )

    glb_path.write_bytes(new_header + new_json_chunk_header + new_json_blob + binary_chunk)
    logger.info("GLB %s: renamed %d root children", glb_path.name, renamed)


__all__ = ["rename_glb_root_children"]
