"""Up-front, tolerance-quantized vertex dedup + degenerate-triangle rejection.

This runs BEFORE any B-Rep object is created (see SELECTION.md: this is the fix for
stltostp's exact-float-match edge map and OCC-CSG's per-triangle fresh vertices).

Tolerance semantics (the only tolerance in the default/faceted path -- see README):
  `tolerance` is a spatial quantization cell size. Two input vertices are merged into
  one shared vertex iff they round to the same integer cell at that resolution
  (`round(coord / tolerance)`). This is a *dedup* tolerance, not a *sew* tolerance --
  no BRepBuilderAPI_Sewing pass exists in this tool's default path, so there is no
  second, ambiguous consumer of this number to conflate it with (see SELECTION.md,
  FreeCAD issue #20455).

The merged vertex keeps the exact coordinates of one of its input occurrences (the
first one encountered) rather than a cell centroid or grid-snapped point -- faceted
mode's fidelity promise is "every kept vertex is a literal input vertex," not
"every vertex is within tolerance of the input."
"""
from dataclasses import dataclass

import numpy as np


@dataclass
class DedupResult:
    verts: np.ndarray          # (U, 3) float64 -- unique vertex positions
    tris: np.ndarray           # (K, 3) int64 -- surviving triangles, indices into verts
    n_input_verts: int
    n_input_tris: int
    n_unique_verts: int
    n_degenerate_collapsed: int   # triangle referenced <3 distinct verts after quantization
    n_degenerate_zero_area: int   # 3 distinct verts but near-zero area (colinear / sliver)
    n_kept_tris: int


def smart_tolerance(verts, divisor: float = 2000.0) -> float:
    """Scale-aware default dedup tolerance = bbox diagonal / divisor.
    Prevents the fixed 0.01 default from collapsing a small mesh's triangles."""
    v = np.asarray(verts, dtype=float)
    if len(v) == 0:
        return 0.01
    diag = float(np.linalg.norm(v.max(axis=0) - v.min(axis=0)))
    return max(diag / divisor, 1e-6)


def dedup_and_clean(verts: np.ndarray, tris: np.ndarray, tolerance: float) -> DedupResult:
    if tolerance <= 0:
        raise ValueError(f"tolerance must be > 0, got {tolerance}")

    n_input_verts = len(verts)
    n_input_tris = len(tris)

    keys = np.round(verts / tolerance).astype(np.int64)
    _, first_idx, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    unique_verts = verts[first_idx]
    inverse = inverse.reshape(-1)

    new_tris = inverse[tris]

    collapsed_mask = (
        (new_tris[:, 0] == new_tris[:, 1])
        | (new_tris[:, 1] == new_tris[:, 2])
        | (new_tris[:, 0] == new_tris[:, 2])
    )
    n_collapsed = int(collapsed_mask.sum())

    survivors = new_tris[~collapsed_mask]
    p0 = unique_verts[survivors[:, 0]]
    p1 = unique_verts[survivors[:, 1]]
    p2 = unique_verts[survivors[:, 2]]
    e0, e1, e2 = p1 - p0, p2 - p1, p0 - p2
    area = 0.5 * np.linalg.norm(np.cross(e0, -e2), axis=1)
    longest_edge_sq = np.maximum.reduce(
        [np.einsum("ij,ij->i", e0, e0), np.einsum("ij,ij->i", e1, e1), np.einsum("ij,ij->i", e2, e2)]
    )
    # Two independent, scale-appropriate degeneracy tests -- NOT a single
    # `area < tolerance**2` cutoff. That was tried first and rejected a real mesh's
    # legitimate thin CAD slivers (area smaller than tolerance^2 despite having 3
    # well-separated, non-collinear vertices) purely because the dedup tolerance
    # was coarse relative to those slivers -- see tests/test_real_scan.py history.
    #   (a) shape_ratio: area vs. longest_edge^2, a dimensionless collinearity test
    #       independent of absolute scale -- catches genuinely near-zero-area
    #       (collinear/sliver) triangles regardless of mesh size or tolerance choice.
    #   (b) sub-resolution: the whole triangle is smaller than the dedup cell, so
    #       treating it as real geometry would be noise below the tool's own stated
    #       resolution -- this is the only place `tolerance` still governs area.
    shape_ratio_eps = 1e-9
    collinear_mask = area < shape_ratio_eps * longest_edge_sq
    sub_resolution_mask = longest_edge_sq < (tolerance * tolerance)
    zero_area_mask = collinear_mask | sub_resolution_mask
    n_zero_area = int(zero_area_mask.sum())

    kept = survivors[~zero_area_mask]

    return DedupResult(
        verts=unique_verts,
        tris=kept,
        n_input_verts=n_input_verts,
        n_input_tris=n_input_tris,
        n_unique_verts=len(unique_verts),
        n_degenerate_collapsed=n_collapsed,
        n_degenerate_zero_area=n_zero_area,
        n_kept_tris=len(kept),
    )
