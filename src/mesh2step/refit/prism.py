"""TrueForm prismaticity predicate + cap-level extraction — port of
refs/stl2step/src/refit_prism.cpp (Stage P, RULE 5.1).

This is a TRANSCRIPTION of ``detectPrismatic``, not a reimplementation. The order
of the six conditions is observable behaviour: ``failed_cond`` is emitted at the
FIRST failing condition and the function returns immediately (refit_prism.cpp:157).
Where the reference looks odd, it is still the specification.

The reference emits one ``DIAG_PRISM`` line per component via ``emitDiag``; this
port returns the equivalent ``PrismLevels`` and does not write to stderr — the
per-component loop is the caller's concern.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .mesh_view import tri_area
from .segment import SurfType


@dataclass
class PrismTols:
    """Port of ``refit::PrismTols`` (refit_prism.hpp:18). All tolerances are
    self-computed from the mesh (RULE 4.2a); zeros mean "derive me"."""

    tau_surf: float = 0.0
    tau_lvl: float = 0.0
    tau_fit: float = 0.0
    tau_ax: float = 0.0


@dataclass
class PrismLevels:
    """Port of ``refit::PrismLevels`` (refit_prism.hpp:25) plus the census the
    reference carries alongside it for the ``DIAG_PRISM`` line."""

    axis: np.ndarray = field(default_factory=lambda: np.zeros(3))
    y: list = field(default_factory=list)
    cap_region: list = field(default_factory=list)
    ok: bool = False
    failed_cond: int = 0
    n_cyl: int = 0
    n_plane: int = 0
    n_cap: int = 0
    n_lat: int = 0
    n_oblique: int = 0
    tau_ax: float = 0.0
    tau_lvl: float = 0.0


def _unit_or_zero(v: np.ndarray) -> np.ndarray:
    """Port of ``unitOrZero`` (refit_prism.cpp:147)."""
    v = np.asarray(v, dtype=float)
    m = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if not (m > 0.0) or not math.isfinite(m):
        return np.zeros(3)
    return v / m


def _dot3(a: np.ndarray, b: np.ndarray) -> float:
    """Scalar ``gp_XYZ::Dot`` (x*x + y*y + z*z), NOT numpy's OpenBLAS ``ddot`` FMA
    path. The reference is scalar throughout; a 1-ulp difference here moves the
    cap offsets and therefore the level heights, which the DXF prints in full."""
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm3(v: np.ndarray) -> float:
    """Scalar ``gp_XYZ::Modulus`` (sqrt(x^2 + y^2 + z^2)), NOT ``np.linalg.norm``
    (scaled two-pass dnrm2). See ``_unit_or_zero`` / the ``sm`` note below."""
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _cross3(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Scalar ``gp_XYZ::Crossed``."""
    return np.array(
        [
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        ],
        dtype=float,
    )


def _dir_xyz(d) -> np.ndarray:
    return np.array([d.X(), d.Y(), d.Z()], dtype=float)


def _pnt_xyz(p) -> np.ndarray:
    return np.array([p.X(), p.Y(), p.Z()], dtype=float)


def _derive_prism_tols(mv, rs, t: PrismTols) -> None:
    """Port of ``derivePrismTols`` (refit_prism.cpp:21)."""
    weld = mv.weld_tol if mv.weld_tol > 0.0 else 0.0
    diag = mv.diag if (math.isfinite(mv.diag) and mv.diag > 0.0) else 0.0
    tau_surf = max(5e-5, max(4.0 * weld, 1e-6 * diag))
    t.tau_surf = tau_surf
    t.tau_lvl = tau_surf
    t.tau_fit = tau_surf
    h_min = 0.0
    for r in rs.regions:
        if r.type != SurfType.CYLINDER:
            continue
        h = abs(r.v_max - r.v_min)
        if not (h > 0.0) or not math.isfinite(h):
            continue
        if h_min <= 0.0 or h < h_min:
            h_min = h
    t.tau_ax = 1e-6
    if h_min > 0.0:
        t.tau_ax = max(1e-6, 2.0 * tau_surf / h_min)


def _region_area(mv, r) -> float:
    """Port of ``regionArea`` (refit_prism.cpp:105). The parallel branch and the
    n<8 short-circuit are the same summation; order is ascending by construction."""
    s = 0.0
    for t in r.tris:
        s += tri_area(mv, t)
    return s


def _chain_length(mv, ch) -> float:
    """Port of ``chainLength`` (refit_prism.cpp:120)."""
    if len(ch.mesh_verts) < 2:
        return 0.0
    pts = mv.pts
    n_vtx = mv.n_vtx

    def pt(loc: int) -> np.ndarray:
        if loc < 0 or loc >= n_vtx:
            return np.zeros(3)
        return pts[int(mv.comp_vtx[loc])]

    length = 0.0
    for i in range(1, len(ch.mesh_verts)):
        length += float(np.linalg.norm(pt(ch.mesh_verts[i]) - pt(ch.mesh_verts[i - 1])))
    if ch.closed_loop and len(ch.mesh_verts) > 2:
        length += float(np.linalg.norm(pt(ch.mesh_verts[0]) - pt(ch.mesh_verts[-1])))
    return length


def _cap_perimeter(mv, rs, r) -> float:
    """Port of ``capPerimeter`` (refit_prism.cpp:134)."""
    peri = 0.0
    for lp in r.loops:
        for ci in lp.chain_idx:
            if ci < 0 or ci >= len(rs.chains):
                continue
            peri += _chain_length(mv, rs.chains[ci])
    if peri > 0.0:
        return peri
    a = _region_area(mv, r)
    return 4.0 * math.sqrt(a) if a > 0.0 else 0.0


def detect_prismatic(mv, rs, tols: PrismTols | None = None) -> PrismLevels:
    """Port of ``detectPrismatic`` (refit_prism.cpp:157). Never throws."""
    out = PrismLevels()
    out.ok = False
    out.failed_cond = 1
    t = (
        PrismTols(
            tau_surf=tols.tau_surf,
            tau_lvl=tols.tau_lvl,
            tau_fit=tols.tau_fit,
            tau_ax=tols.tau_ax,
        )
        if tols is not None
        else PrismTols()
    )
    try:
        cyls = []
        planes = []
        for r in rs.regions:
            if r.type == SurfType.CYLINDER:
                cyls.append(r)
            elif r.type == SurfType.PLANE:
                planes.append(r)
        out.n_cyl = len(cyls)
        out.n_plane = len(planes)

        if t.tau_surf <= 0.0 or t.tau_ax <= 0.0:
            _derive_prism_tols(mv, rs, t)
        out.tau_ax = t.tau_ax
        out.tau_lvl = t.tau_lvl

        # --- 1: at least two recognized cylinders (refit_prism.cpp:179) ---
        if out.n_cyl < 2:
            out.failed_cond = 1
            return out

        # --- 2: common axis (refit_prism.cpp:185) ---
        axes = [_unit_or_zero(_dir_xyz(cyls[i].ax.Direction())) for i in range(out.n_cyl)]
        max_sin = 0.0
        for i in range(out.n_cyl):
            for j in range(out.n_cyl):
                if j <= i:
                    continue
                s = _norm3(_cross3(axes[i], axes[j]))
                if s > max_sin:
                    max_sin = s
        if not (max_sin < t.tau_ax):
            out.failed_cond = 2
            return out

        ref = axes[0]
        if _norm3(ref) <= 0.0:
            out.failed_cond = 2
            return out
        total = np.zeros(3)
        for a in axes:
            u = a.copy()
            if _dot3(u, ref) < 0.0:
                u = -u
            total = total + u
        # gp_XYZ::Modulus (refit_prism.cpp:230) is a plain sqrt(x^2+y^2+z^2),
        # NOT numpy's scaled two-pass dnrm2 -- the two differ by ulps and the
        # DXF header prints the axis at full precision, so the scalar path is
        # part of the byte contract.
        sm = _norm3(total)
        if not (sm > 0.0):
            out.failed_cond = 2
            return out
        total = total / sm
        # The reference keeps ahat = sum/sm for cap clustering and re-normalises
        # the reported axis through gp_Dir(sum) (a second Modulus,
        # refit_prism.cpp:236-237) -- two normalisations, both reproduced.
        ahat = total
        out.axis = total / _norm3(total)

        # --- 3: no oblique planes (refit_prism.cpp:231) ---
        kind = [2] * out.n_plane
        for i in range(out.n_plane):
            n = _unit_or_zero(_dir_xyz(planes[i].ax.Direction()))
            nd = abs(_dot3(n, ahat))
            if nd > 1.0 - t.tau_ax:
                kind[i] = 0
            elif nd < t.tau_ax:
                kind[i] = 1
            else:
                kind[i] = 2
        caps = []
        for i in range(out.n_plane):
            if kind[i] == 0:
                out.n_cap += 1
                caps.append(planes[i])
            elif kind[i] == 1:
                out.n_lat += 1
            else:
                out.n_oblique += 1
        if out.n_oblique > 0:
            out.failed_cond = 3
            return out

        # --- 4: >=2 distinct cap levels (cluster n.p along ahat) (refit_prism.cpp:257) ---
        offs = [
            (_dot3(ahat, _pnt_xyz(r.ax.Location())), r.id, r) for r in caps
        ]
        offs.sort(key=lambda o: (o[0], o[1]))
        clusters = []
        for o in offs:
            if not clusters or (o[0] - clusters[-1][-1][0]) > t.tau_lvl:
                clusters.append([])
            clusters[-1].append(o)
        out.y = []
        out.cap_region = []
        for cl in clusters:
            mean = 0.0
            best_id = cl[0][1]
            best_a = -1.0
            for o in cl:
                mean += o[0]
                ar = _region_area(mv, o[2])
                if ar > best_a or (ar == best_a and o[1] < best_id):
                    best_a = ar
                    best_id = o[1]
            mean /= len(cl)
            out.y.append(mean)
            out.cap_region.append(best_id)
        if len(out.y) < 2:
            out.failed_cond = 4
            return out

        # --- 5: every cylinder spans a contiguous run of levels (refit_prism.cpp:307) ---
        n_lvl = len(out.y)

        def nearest(yv: float) -> int:
            best = -1
            best_d = t.tau_lvl
            for k in range(n_lvl):
                d = abs(yv - out.y[k])
                if d <= t.tau_lvl and (best < 0 or d < best_d):
                    best = k
                    best_d = d
            return best

        span_ok = [0] * out.n_cyl
        for i in range(out.n_cyl):
            r = cyls[i]
            c = _pnt_xyz(r.ax.Location())
            ad = _unit_or_zero(_dir_xyz(r.ax.Direction()))
            y0 = _dot3(ahat, c + ad * r.v_min)
            y1 = _dot3(ahat, c + ad * r.v_max)
            ia = nearest(y0)
            ib = nearest(y1)
            if ia < 0 or ib < 0:
                continue
            if ia > ib:
                ia, ib = ib, ia
            if ib > ia:
                span_ok[i] = 1
        for v in span_ok:
            if not v:
                out.failed_cond = 5
                return out

        # --- 6: signed cap-area closure (per-level flux sums to ~0) (refit_prism.cpp:342) ---
        signed_a = [0.0] * len(caps)
        peri = [0.0] * len(caps)
        for i in range(len(caps)):
            r = caps[i]
            n = _unit_or_zero(_dir_xyz(r.ax.Direction()))
            signed_a[i] = _region_area(mv, r) * _dot3(n, ahat)
            peri[i] = _cap_perimeter(mv, rs, r)
        flux = 0.0
        peri_scale = 0.0
        for i in range(len(caps)):
            flux += signed_a[i]
            peri_scale += peri[i]
        if peri_scale <= 0.0:
            peri_scale = 1.0
        if not (abs(flux) < t.tau_fit * peri_scale):
            out.failed_cond = 6
            return out

        out.ok = True
        out.failed_cond = 0
        return out  # noqa: TRY300 - port of the reference's try/catch guard
    except Exception:  # noqa: BLE001 - port of the reference's catch-all guard
        out.ok = False
        if out.failed_cond <= 0:
            out.failed_cond = 1
        return out
