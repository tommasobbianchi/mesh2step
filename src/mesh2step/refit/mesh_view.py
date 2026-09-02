"""Per-component mesh adjacency — port of the reference `refit::MeshView` contract
(refs/stl2step/src/refit.hpp, filled by stl2step.cpp's component loop).

Holds the triangle/edge topology the segmentation and build stages consume:
local edge list `(vLo, vHi)` with per-triangle edge ids and direction bits, plus
normals/areas derived from the component's shared vertices.

Local-indexing note: the reference numbers component vertices in first-encounter
order while walking the component's triangles in ascending global-triangle order
(edge/vertex creation loop in stl2step.cpp). split.py numbers component vertices
differently (sorted-unique), so this view re-derives the reference's local ids
from the component's triangle rows, which follow the same ascending order.
"""
from dataclasses import dataclass

import numpy as np

K_TINY = 1e-30  # refit_grow.cpp kTiny


@dataclass
class MeshView:
    pts: np.ndarray            # local welded points, Nx3 float64 (mm)
    tris: np.ndarray           # local triangles (a,b,c), Mx3 int64
    comp_tris: np.ndarray      # local tri -> global tri id (identity here)
    comp_vtx: np.ndarray       # local vtx -> global point id (identity here)
    comp_edges: list           # local edge -> (vLo, vHi), vLo < vHi
    tri_edges: np.ndarray      # local tri -> 3 local edge ids, Mx3 int64
    tri_dirs: np.ndarray      # local tri -> direction bits (bit s: side s is vLo->vHi), Mx3
    n_tri: int
    n_vtx: int
    n_edge: int
    diag: float                # whole-mesh bbox diagonal (tolerance input)
    weld_tol: float            # engine weld tolerance (0 = exact weld)
    sew_tol: float             # engine sew tolerance (auto-derived from bbox)


def build_mesh_view(comp, diag: float, weld_tol: float, sew_tol: float) -> MeshView:
    """Build the view from a split.Component, replicating the reference's local
    vertex numbering (first-encounter order over triangle sides 0..2)."""
    tris_orig = np.asarray(comp.tris, dtype=np.int64)
    n_tri = len(tris_orig)
    comp_tris = np.arange(n_tri, dtype=np.int64)

    # First-encounter local numbering over triangle corners (reference order).
    vtx_remap: dict[int, int] = {}
    for t in range(n_tri):
        for s in range(3):
            g = int(tris_orig[t, s])
            if g not in vtx_remap:
                vtx_remap[g] = len(vtx_remap)
    tris = np.empty_like(tris_orig)
    for t in range(n_tri):
        for s in range(3):
            tris[t, s] = vtx_remap[int(tris_orig[t, s])]
    n_vtx = len(vtx_remap)
    comp_vtx = np.arange(n_vtx, dtype=np.int64)

    comp_edges: list[tuple[int, int]] = []
    edge_ids: dict[tuple[int, int], int] = {}
    tri_edges = np.zeros((n_tri, 3), dtype=np.int64)
    tri_dirs = np.zeros((n_tri, 3), dtype=np.uint8)

    for t in range(n_tri):
        for s in range(3):
            lu, lv = int(tris[t, s]), int(tris[t, (s + 1) % 3])
            key = (lu, lv) if lu < lv else (lv, lu)
            eid = edge_ids.get(key)
            if eid is None:
                eid = len(comp_edges)
                edge_ids[key] = eid
                comp_edges.append(key)
            tri_edges[t, s] = eid
            if lu < lv:
                tri_dirs[t, s] = 1

    pts = np.asarray(comp.verts, dtype=np.float64)[
        np.array(sorted(vtx_remap, key=vtx_remap.__getitem__), dtype=np.int64)
    ]
    return MeshView(
        pts=pts,
        tris=tris,
        comp_tris=comp_tris,
        comp_vtx=comp_vtx,
        comp_edges=comp_edges,
        tri_edges=tri_edges,
        tri_dirs=tri_dirs,
        n_tri=n_tri,
        n_vtx=n_vtx,
        n_edge=len(comp_edges),
        diag=diag,
        weld_tol=weld_tol,
        sew_tol=sew_tol,
    )


def tri_corner(mv: MeshView, lt: int, corner: int) -> np.ndarray:
    return mv.pts[int(mv.tris[lt, corner])]


def tri_area(mv: MeshView, lt: int) -> float:
    a, b, c = (tri_corner(mv, lt, k) for k in range(3))
    return 0.5 * float(np.linalg.norm(np.cross(b - a, c - a)))


def tri_centroid(mv: MeshView, lt: int) -> np.ndarray:
    a, b, c = (tri_corner(mv, lt, k) for k in range(3))
    return (a + b + c) / 3.0


def tri_normal(mv: MeshView, lt: int) -> np.ndarray:
    a, b, c = (tri_corner(mv, lt, k) for k in range(3))
    n = np.cross(b - a, c - a)
    m = float(np.linalg.norm(n))
    if m < K_TINY:
        return np.array([0.0, 0.0, 1.0])
    return n / m


def build_edge_adj(mv: MeshView) -> list[tuple[int, int]]:
    """local edge -> [t0, t1] incident local tris (-1 if boundary)."""
    adj = [(-1, -1)] * mv.n_edge
    for lt in range(mv.n_tri):
        for s in range(3):
            e = int(mv.tri_edges[lt, s])
            if adj[e][0] < 0:
                adj[e] = (lt, adj[e][1])
            else:
                adj[e] = (adj[e][0], lt)
    return adj


def edge_dihedral_abs(mv: MeshView, edge_id: int, adj: list) -> float:
    """Dihedral in [0, pi]: acos(n0.n1), not acos(|n0.n1|) — refit_grow.cpp."""
    t0, t1 = adj[edge_id]
    if t0 < 0 or t1 < 0:
        return 0.0
    n0, n1 = tri_normal(mv, t0), tri_normal(mv, t1)
    d = min(1.0, max(-1.0, float(np.dot(n0, n1))))
    return float(np.arccos(d))


def local_verts_of_tri(mv: MeshView, t: int) -> tuple[int, int, int]:
    """Corner vertices of local tri t from its edge directions — refit_chains.cpp."""
    lv = []
    for s in range(3):
        e = mv.comp_edges[int(mv.tri_edges[t, s])]
        lv.append(e[0] if mv.tri_dirs[t, s] else e[1])
    return lv[0], lv[1], lv[2]
