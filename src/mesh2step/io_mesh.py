"""Mesh file loading. Delegates format parsing (STL/OBJ/3MF/PLY/...) to trimesh --
already a project dependency and battle-tested on all four required formats, so there
is no reason to hand-roll parsers the way stltostp/2STEP-Converter do.

Deliberately loads with process=False: trimesh's own vertex-merging/normal-fixing
pipeline must not run before our own explicit, tolerance-documented dedup step (dedup.py)
gets the raw data -- otherwise "how were vertices merged" would be split across two
undocumented policies instead of one.
"""
from pathlib import Path

import numpy as np
import trimesh

SUPPORTED_EXTENSIONS = {".stl", ".obj", ".3mf", ".ply"}


class MeshLoadError(ValueError):
    pass


def load_mesh(path) -> tuple[np.ndarray, np.ndarray]:
    """Load a mesh file and return (verts Nx3 float64, tris Mx3 int64), unprocessed."""
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise MeshLoadError(
            f"unsupported extension {path.suffix!r} (supported: {sorted(SUPPORTED_EXTENSIONS)})"
        )

    loaded = trimesh.load(path.as_posix(), force="mesh", process=False)

    if isinstance(loaded, trimesh.Scene):
        geoms = list(loaded.geometry.values())
        if not geoms:
            raise MeshLoadError(f"{path}: scene contains no geometry")
        loaded = trimesh.util.concatenate(geoms)

    if not isinstance(loaded, trimesh.Trimesh):
        raise MeshLoadError(f"{path}: loaded object is not a triangle mesh ({type(loaded)})")

    verts = np.asarray(loaded.vertices, dtype=np.float64)
    tris = np.asarray(loaded.faces, dtype=np.int64)

    if len(tris) == 0:
        raise MeshLoadError(f"{path}: no triangles found")
    if tris.shape[1] != 3:
        raise MeshLoadError(f"{path}: non-triangular faces present (shape {tris.shape})")

    return verts, tris
