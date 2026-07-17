"""Selection & cut operations applied to a triangle mesh BEFORE repair.

All cuts are centroid-mask based: for each triangle we compute its centroid
(the mean of its three vertices) and decide whether to keep or discard the
whole triangle based on that single point. No new vertices are created and
no vertex positions are altered -- this preserves exact faceted fidelity.
Cuts are applied in order; off by default (empty ops list = no-op).
"""
import json
import math
from dataclasses import dataclass

import numpy as np
import trimesh

CUT_TYPES = ("box", "plane", "lasso", "largest")


@dataclass
class CutResult:
    verts: np.ndarray
    tris: np.ndarray
    n_tris_before: int
    n_tris_after: int
    ops_applied: int


def _centroids(verts: np.ndarray, tris: np.ndarray) -> np.ndarray:
    return verts[tris].mean(axis=1)  # (M, 3)


def _point_in_polygon(px: float, py: float, polygon) -> bool:
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _apply_box(c, tris, op):
    lo = np.array(op["min"], dtype=float)
    hi = np.array(op["max"], dtype=float)
    inside = np.all((c >= lo) & (c <= hi), axis=1)
    keep_mask = inside if op.get("keep", "inside") == "inside" else ~inside
    return tris[keep_mask]


def _apply_plane(c, tris, op):
    axis_map = {"x": 0, "y": 1, "z": 2}
    a = axis_map[op["axis"]]
    offset = float(op["offset"])
    side = op.get("side", "min")
    if side == "min":
        keep_mask = c[:, a] <= offset
    else:
        keep_mask = c[:, a] >= offset
    return tris[keep_mask]


def _apply_lasso(c, tris, op):
    polygon = op["polygon"]  # list of [ndcx, ndcy]
    e = op["matrix"]  # 16 floats col-major
    keep_val = op.get("keep", "inside")

    # Transform centroids to clip space
    x, y, z = c[:, 0], c[:, 1], c[:, 2]
    clipx = e[0] * x + e[4] * y + e[8] * z + e[12]
    clipy = e[1] * x + e[5] * y + e[9] * z + e[13]
    clipw = e[3] * x + e[7] * y + e[11] * z + e[15]

    # Guard w == 0
    valid = np.abs(clipw) > 1e-12
    ndcx = np.where(valid, clipx / clipw, 999.0)
    ndcy = np.where(valid, clipy / clipw, 999.0)

    # Point-in-polygon test for each centroid
    inside = np.zeros(len(c), dtype=bool)
    for i in range(len(c)):
        if valid[i]:
            inside[i] = _point_in_polygon(float(ndcx[i]), float(ndcy[i]), polygon)

    # lasso selects what to delete: keep='inside' REMOVES selected -> ~inside
    if keep_val == "inside":
        keep_mask = ~inside
    else:
        keep_mask = inside
    return tris[keep_mask]


def _apply_largest(verts, tris, op):
    m = trimesh.Trimesh(vertices=verts, faces=tris, process=False)
    # STL-loaded meshes have split (unwelded) vertices, so face adjacency does
    # not exist and every triangle would be its own component. Weld first so
    # split() sees real connectivity and "largest" means the largest body.
    m.merge_vertices()
    parts = m.split(only_watertight=False)
    if not parts:
        return verts, tris
    largest = max(parts, key=lambda p: len(p.faces))
    m2 = trimesh.Trimesh(vertices=largest.vertices, faces=largest.faces, process=False)
    m2.remove_unreferenced_vertices()
    return np.asarray(m2.vertices, dtype=np.float64), np.asarray(m2.faces, dtype=np.int64)


def apply_cuts(verts: np.ndarray, tris: np.ndarray, ops) -> CutResult:
    """Apply a sequence of centroid-mask cut operations.

    Args:
        verts: (N, 3) float64 vertex array.
        tris: (M, 3) int64 triangle array.
        ops: list of dicts, each with a 'type' field in CUT_TYPES.

    Returns:
        CutResult with updated verts/tris and stats.
    """
    n_before = len(tris)

    if not ops:
        return CutResult(
            verts=verts.copy(),
            tris=tris.copy(),
            n_tris_before=n_before,
            n_tris_after=n_before,
            ops_applied=0,
        )

    for op in ops:
        op_type = op.get("type")
        if op_type not in CUT_TYPES:
            raise ValueError(f"unknown cut type {op_type!r}; must be one of {CUT_TYPES}")

    applied = 0
    for op in ops:
        op_type = op["type"]
        if op_type == "largest":
            verts, tris = _apply_largest(verts, tris, op)
            applied += 1
            continue

        if len(tris) == 0:
            break

        c = _centroids(verts, tris)
        if op_type == "box":
            tris = _apply_box(c, tris, op)
        elif op_type == "plane":
            tris = _apply_plane(c, tris, op)
        elif op_type == "lasso":
            tris = _apply_lasso(c, tris, op)
        applied += 1

    # Rebuild to remove unreferenced vertices
    if len(tris) > 0:
        m = trimesh.Trimesh(vertices=verts, faces=tris, process=False)
        m.remove_unreferenced_vertices()
        verts = np.asarray(m.vertices, dtype=np.float64)
        tris = np.asarray(m.faces, dtype=np.int64)
    else:
        verts = verts[:0].copy()
        tris = tris[:0].copy()

    return CutResult(
        verts=verts,
        tris=tris,
        n_tris_before=n_before,
        n_tris_after=len(tris),
        ops_applied=applied,
    )


def load_cut_ops(path) -> list:
    """Load a JSON list of cut operations from a file path."""
    with open(path) as fh:
        ops = json.load(fh)
    if not isinstance(ops, list):
        raise ValueError(f"cut JSON must be a list, got {type(ops)}")
    return ops
