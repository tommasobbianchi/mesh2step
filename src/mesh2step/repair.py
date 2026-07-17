"""Opt-in mesh repair path.

The default triangule-mesh -> faceted-B-Rep pipeline deliberately keeps trimesh
cleanup out of the load path (io_mesh.py returns raw vertices/faces) so that
dedup.py owns the ONE vertex-merge policy -- round(v / tol) cell grouping.

This module is a separate, explicit stage that runs *before* dedup.  It uses
trimesh's own surgery (merge_vertices, fix_normals, fill_holes) which applies a
different merge policy.  That is acceptable here BECAUSE the user opted in
and dedup's canonical round(v / tol) merge still runs afterward.

Level "solidify" uses pymeshfix to reconstruct a watertight manifold when
weld/fill cannot -- this may alter geometry and requires pymeshfix.
"""
from dataclasses import dataclass

import numpy as np
import trimesh

REPAIR_LEVELS = ("weld", "fill", "solidify")


@dataclass
class RepairResult:
    verts: np.ndarray  # Nx3 float64
    tris: np.ndarray   # Mx3 int64
    n_verts_before: int
    n_verts_after: int
    n_faces_before: int
    n_faces_after: int
    n_duplicate_faces_removed: int
    holes_filled: bool
    watertight_after: bool


def repair_mesh(verts, tris, level="weld") -> RepairResult:
    if level not in REPAIR_LEVELS:
        raise ValueError(f"repair level must be one of {REPAIR_LEVELS}, got {level!r}")

    m = trimesh.Trimesh(vertices=verts, faces=tris, process=False)
    n_verts_before = len(m.vertices)
    n_faces_before = len(m.faces)

    m.merge_vertices()  # weld coincident / split vertices

    if level == "solidify":
        try:
            import pymeshfix
        except ImportError as e:
            raise ImportError(
                "repair level 'solidify' requires pymeshfix (pip install pymeshfix)"
            ) from e
        vclean, fclean = pymeshfix.clean_from_arrays(
            np.asarray(m.vertices, dtype=float),
            np.asarray(m.faces, dtype=np.int32))
        m = trimesh.Trimesh(vertices=vclean, faces=fclean, process=False)
        return RepairResult(
            verts=np.asarray(m.vertices, dtype=np.float64),
            tris=np.asarray(m.faces, dtype=np.int64),
            n_verts_before=n_verts_before, n_verts_after=len(m.vertices),
            n_faces_before=n_faces_before, n_faces_after=len(m.faces),
            n_duplicate_faces_removed=0,
            holes_filled=bool(m.is_watertight),
            watertight_after=bool(m.is_watertight))

    mask = m.unique_faces()
    n_dupes = int((~mask).sum())
    m.update_faces(mask)

    m.fix_normals()  # consistent outward winding

    holes_filled = False
    if level == "fill":
        holes_filled = bool(m.fill_holes())
        m.fix_normals()

    return RepairResult(
        verts=np.asarray(m.vertices, dtype=np.float64),
        tris=np.asarray(m.faces, dtype=np.int64),
        n_verts_before=n_verts_before,
        n_verts_after=len(m.vertices),
        n_faces_before=n_faces_before,
        n_faces_after=len(m.faces),
        n_duplicate_faces_removed=n_dupes,
        holes_filled=holes_filled,
        watertight_after=bool(m.is_watertight),
    )
