"""Stage P2 — sliceProfiles + fitProfile (lines + arcs; R from the law inverse).

Port of ``refs/stl2step/src/refit_profile.cpp``. This is a TRANSCRIPTION, not a
reimplementation: every helper below carries the ``refit_profile.cpp`` line it was
copied from, and where the reference looks odd it is still the specification.

The reference emits ``DIAG_PROFILE`` lines to stderr via ``emitLoopDiag``; this port
returns the ``Profile`` objects directly and does not write to stderr (the same
decision ``prism.py`` made for ``DIAG_PRISM``). The advisory lookup path
(``lookupAdvisory``, gated on ``STL2STEP_PRISM_ASSIST``) is out of scope: the
harness never enables it, so a declined chain stays declined
(refit_profile.cpp:901-907).

2D points are plain ``numpy`` shape-(2,) float64 arrays (in place of ``gp_Pnt2d``);
3D points are shape-(3,) float64 (in place of ``gp_XYZ``). Dot products use the
scalar ``a*b + c*d + e*f`` path and angles use ``math.atan2``/``math.hypot`` to match
the OCCT / libm bit-exact behaviour of the reference (see ``lawband.py`` notes).
"""
from __future__ import annotations

import math
from copy import copy
from dataclasses import dataclass, field

import numpy as np

from .lawband import law_chain_accept
from .segment import SurfType

K_PI = math.pi  # refit_profile.cpp:27  kPi
K_TWO_PI = 2.0 * math.pi  # refit_profile.cpp:28  kTwoPi
K_ZERO_LEN = 1e-12  # refit_profile.cpp:443  kZeroLen


# --- bit-exact OCCT equivalents -------------------------------------------------

def _p2(x: float, y: float) -> np.ndarray:
    return np.array([x, y], dtype=float)


def _dot3(a: np.ndarray, b: np.ndarray) -> float:
    """Scalar gp_XYZ::Dot (x*x + y*y + z*z), NOT numpy's OpenBLAS ``ddot`` FMA path."""
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm3(v: np.ndarray) -> float:
    """Scalar gp_XYZ::Modulus (sqrt(x^2 + y^2 + z^2))."""
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _cross3(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Scalar gp_XYZ::Crossed."""
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


# --- public dataclasses (refit_prism.hpp:34-43, snake_case) ---------------------

@dataclass
class ProfSeg:
    is_arc: bool = False
    a: np.ndarray = field(default_factory=lambda: np.zeros(2))
    b: np.ndarray = field(default_factory=lambda: np.zeros(2))
    center: np.ndarray = field(default_factory=lambda: np.zeros(2))
    r: float = 0.0
    phi: float = 0.0
    ccw: bool = False
    declined_ambiguous: bool = False


@dataclass
class ProfLoop:
    segs: list = field(default_factory=list)
    outer: bool = False
    area: float = 0.0


@dataclass
class Profile:
    slab: int = -1
    loops: list = field(default_factory=list)


# --- internal state -------------------------------------------------------------

@dataclass
class _SketchFrame:  # refit_profile.cpp:30-41
    origin: np.ndarray = field(default_factory=lambda: np.zeros(3))
    axis: np.ndarray = field(default_factory=lambda: np.zeros(3))
    u: np.ndarray = field(default_factory=lambda: np.zeros(3))
    v: np.ndarray = field(default_factory=lambda: np.zeros(3))

    def xy(self, p: np.ndarray) -> np.ndarray:
        d = p - self.origin
        return _p2(_dot3(d, self.u), _dot3(d, self.v))

    def axial(self, p: np.ndarray) -> float:
        return _dot3(p - self.origin, self.axis)


@dataclass
class _SliceCache:  # refit_profile.cpp:43-49
    rs: object = None
    fr: object = None
    ok: bool = False
    rids: list = field(default_factory=list)


@dataclass
class _SliceEdge:  # refit_profile.cpp:212-216
    a: np.ndarray = field(default_factory=lambda: np.zeros(2))
    b: np.ndarray = field(default_factory=lambda: np.zeros(2))
    local_tri: int = -1
    rid: int = -1


@dataclass
class _RawLoop:  # refit_profile.cpp:218-221
    pts: list = field(default_factory=list)
    rids: list = field(default_factory=list)


_cache = _SliceCache()  # refit_profile.cpp:51-58  cache()


# --- math helpers (refit_profile.cpp:81-100) ------------------------------------

def _dist2(a: np.ndarray, b: np.ndarray) -> float:  # refit_profile.cpp:81
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _near2(a: np.ndarray, b: np.ndarray, tol: float) -> bool:  # refit_profile.cpp:85
    return _dist2(a, b) <= tol


def _signed_area(poly: list) -> float:  # refit_profile.cpp:89
    n = len(poly)
    if n < 3:
        return 0.0
    a = 0.0
    for i in range(n):
        p = poly[i]
        q = poly[(i + 1) % n]
        a += p[0] * q[1] - q[0] * p[1]
    return 0.5 * a


# --- frame / cylinder helpers (refit_profile.cpp:101-203) -----------------------

def _local_corners(mv, local_t: int):  # refit_profile.cpp:101
    if local_t < 0 or local_t >= mv.n_tri:
        return None
    t = mv.tris[local_t]
    return mv.pts[t[0]], mv.pts[t[1]], mv.pts[t[2]]


def _build_frame(rs, lv, fr: _SketchFrame) -> bool:  # refit_profile.cpp:111
    fr.axis = np.asarray(lv.axis, dtype=float).copy()
    am = _norm3(fr.axis)
    if not (am > 0.0):
        return False
    fr.axis = fr.axis / am
    hint = np.array([1.0, 0.0, 0.0])
    if abs(_dot3(fr.axis, hint)) > 0.9:
        hint = np.array([0.0, 1.0, 0.0])
    fr.u = _cross3(fr.axis, hint)
    um = _norm3(fr.u)
    if um < 1e-18:
        return False
    fr.u = fr.u / um
    fr.v = _cross3(fr.axis, fr.u)
    vm = _norm3(fr.v)
    if vm < 1e-18:
        return False
    fr.v = fr.v / vm
    fr.origin = np.zeros(3)
    if lv.cap_region:
        for r in rs.regions:
            if r.id == lv.cap_region[0]:
                fr.origin = _pnt_xyz(r.ax.Location())
                return True
    for r in rs.regions:
        if r.type == SurfType.CYLINDER:
            fr.origin = _pnt_xyz(r.ax.Location())
            return True
    return True


def _cyl_ends(r, axis: np.ndarray):  # refit_profile.cpp:144
    a = _dir_xyz(r.ax.Direction())
    loc = _pnt_xyz(r.ax.Location())
    p0 = loc + a * r.v_min
    p1 = loc + a * r.v_max
    y0 = _dot3(axis, p0)
    y1 = _dot3(axis, p1)
    return (min(y0, y1), max(y0, y1))


def _snap_level(y: list, v: float, tol: float) -> int:  # refit_profile.cpp:155
    best = -1
    best_d = 0.0
    for i in range(len(y)):
        d = abs(y[i] - v)
        if d <= tol and (best < 0 or d < best_d):
            best = i
            best_d = d
    return best


def _is_through(r, lv, tau: float) -> bool:  # refit_profile.cpp:169
    if r.type != SurfType.CYLINDER or len(lv.y) < 3:
        return False
    lo, hi = _cyl_ends(r, np.asarray(lv.axis, dtype=float))
    i0 = _snap_level(lv.y, lo, tau)
    i1 = _snap_level(lv.y, hi, tau)
    return i0 >= 0 and i1 >= 0 and (i1 - i0) >= 2


def _cyl_covers_slab(r, lv, slab: int, tau: float) -> bool:  # refit_profile.cpp:178
    if r.type != SurfType.CYLINDER or len(lv.y) < 2:
        return False
    if slab < 0 or slab + 1 >= len(lv.y):
        return False
    lo, hi = _cyl_ends(r, np.asarray(lv.axis, dtype=float))
    y0 = lv.y[slab]
    y1 = lv.y[slab + 1]
    return lo <= y0 + tau and hi >= y1 - tau


def _cyl_center(r, fr: _SketchFrame) -> np.ndarray:  # refit_profile.cpp:188
    return fr.xy(_pnt_xyz(r.ax.Location()))


def _cyl_assoc_tol(r, tau_fit: float) -> float:  # refit_profile.cpp:192
    sag = r.chord_sagitta
    if not (sag > 0.0):
        sag = r.max_vertex_dev
    return max(tau_fit, 4.0 * sag, 4.0 * r.max_vertex_dev)


def _on_cyl(p, r, fr, tau_fit: float) -> bool:  # refit_profile.cpp:199
    if r.type != SurfType.CYLINDER or not (r.radius > 0.0):
        return False
    c = _cyl_center(r, fr)
    return abs(_dist2(p, c) - r.radius) <= _cyl_assoc_tol(r, tau_fit)


def _make_derived(mv) -> float:  # refit_profile.cpp:205  epsMesh only (lawChainAccept)
    return max(mv.weld_tol, 1e-4 * mv.diag, 1e-3)


# --- slicing (refit_profile.cpp:223-295) ----------------------------------------

def _slice_tri(mv, local_t: int, rid: int, fr, y_slice: float, tol: float, edges):  # :223
    c = _local_corners(mv, local_t)
    if c is None:
        return
    p0, p1, p2 = c
    p = [p0, p1, p2]
    s = [_dot3(fr.axis, p[i]) for i in range(3)]
    smin = min(s)
    smax = max(s)
    if y_slice < smin - tol or y_slice > smax + tol:
        return
    if smax - smin <= tol:
        return
    ip = []
    n_ip = 0
    for e in range(3):
        i0 = e
        i1 = (e + 1) % 3
        d0 = s[i0] - y_slice
        d1 = s[i1] - y_slice
        if d0 < -tol and d1 < -tol:
            continue
        if d0 > tol and d1 > tol:
            continue
        if abs(d0) <= tol and abs(d1) <= tol:
            continue
        den = d0 - d1
        tp = (d0 / den) if (abs(den) > 0.0) else 0.0
        tp = max(0.0, min(1.0, tp))
        q = p[i0] + (p[i1] - p[i0]) * tp
        if n_ip < 2:
            ip.append(fr.xy(q))
            n_ip += 1
    if n_ip == 2 and _dist2(ip[0], ip[1]) > tol:
        edges.append(_SliceEdge(ip[0], ip[1], local_t, rid))


def _chain_edges(edges: list, tol: float, loops: list):  # refit_profile.cpp:261
    n = len(edges)
    used = [False] * n
    for start in range(n):
        if used[start]:
            continue
        pts = [edges[start].a, edges[start].b]
        rids = [edges[start].rid]
        used[start] = True
        tail = edges[start].b
        grew = True
        while grew:
            grew = False
            for i in range(n):
                if used[i]:
                    continue
                if _near2(tail, edges[i].a, tol):
                    pts.append(edges[i].b)
                    rids.append(edges[i].rid)
                    tail = edges[i].b
                    used[i] = True
                    grew = True
                elif _near2(tail, edges[i].b, tol):
                    pts.append(edges[i].a)
                    rids.append(edges[i].rid)
                    tail = edges[i].a
                    used[i] = True
                    grew = True
        if len(pts) >= 2 and _near2(pts[0], pts[-1], tol):
            pts.pop()
        if len(pts) >= 3:
            loops.append(_RawLoop(pts, rids))


def _emit_circle(r, fr, lp: _RawLoop, n_samp: int):  # refit_profile.cpp:297
    lp.pts = []
    lp.rids = []
    if not (r.radius > 0.0) or n_samp < 3:
        return
    c = _cyl_center(r, fr)
    R = r.radius
    for i in range(n_samp):
        ang = K_TWO_PI * float(i) / float(n_samp)
        lp.pts.append(_p2(c[0] + R * math.cos(ang), c[1] + R * math.sin(ang)))
        lp.rids.append(r.id)


# --- line / arc fitting helpers (refit_profile.cpp:310-775) ---------------------

def _line_resid(a, b, pts, i0: int, i1: int) -> float:  # refit_profile.cpp:310
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-18:
        return 0.0
    m = 0.0
    for i in range(i0, i1 + 1):
        if i >= len(pts):
            break
        px = pts[i][0] - a[0]
        py = pts[i][1] - a[1]
        m = max(m, abs((dx * py - dy * px) / length))
    return m


def _rule53a(lb, tau_fit: float) -> bool:  # refit_profile.cpp:325
    if lb.n <= 2:
        return True
    if not (lb.radius > 0.0):
        return True
    sag = lb.radius * (1.0 - math.cos(0.5 * lb.phi))
    return sag < tau_fit


def _region_by_id(rs, rid: int):  # refit_profile.cpp:415
    for r in rs.regions:
        if r.id == rid:
            return r
    return None


def _cyl_at_point(rs, fr, p, tau_fit: float):  # refit_profile.cpp:421
    best = None
    best_d = 0.0
    for r in rs.regions:
        if r.type != SurfType.CYLINDER or not (r.radius > 0.0):
            continue
        d = abs(_dist2(p, _cyl_center(r, fr)) - r.radius)
        if d <= _cyl_assoc_tol(r, tau_fit) and (best is None or d < best_d):
            best = r
            best_d = d
    return best


def _cyl_by_rid(rs, rid: int):  # refit_profile.cpp:436
    r = _region_by_id(rs, rid)
    if r is not None and r.type == SurfType.CYLINDER and r.radius > 0.0:
        return r
    return None


def _on_circ(c, R, p):  # refit_profile.cpp:445
    ang = math.atan2(p[1] - c[1], p[0] - c[0])
    return _p2(c[0] + R * math.cos(ang), c[1] + R * math.sin(ang))


def _ang_of(c, p) -> float:  # refit_profile.cpp:450
    return math.atan2(p[1] - c[1], p[0] - c[0])


def _unwrap_span(c, verts, i0: int, i_last: int) -> float:  # refit_profile.cpp:455
    if i0 >= len(verts) or i_last >= len(verts) or i_last < i0:
        return 0.0
    prev = _ang_of(c, verts[i0])
    total = 0.0
    for i in range(i0 + 1, i_last + 1):
        a = _ang_of(c, verts[i])
        d = a - prev
        while d > K_PI:
            d -= K_TWO_PI
        while d < -K_PI:
            d += K_TWO_PI
        total += d
        prev = a
    return total


def _circ_intersect(c1, R1, c2, R2, hint, slop):  # refit_profile.cpp:471
    dx = c2[0] - c1[0]
    dy = c2[1] - c1[1]
    d = math.hypot(dx, dy)
    if not (d > K_ZERO_LEN):
        return False, None
    ssum = R1 + R2
    dif = abs(R1 - R2)
    ux = dx / d
    uy = dy / d
    if d > ssum:
        if d - ssum > slop:
            return False, None
        return True, _p2(c1[0] + ux * R1, c1[1] + uy * R1)
    if d < dif:
        if dif - d > slop:
            return False, None
        s = 1.0 if R1 >= R2 else -1.0
        return True, _p2(c1[0] + s * ux * R1, c1[1] + s * uy * R1)
    aa = (R1 * R1 - R2 * R2 + d * d) / (2.0 * d)
    h2 = R1 * R1 - aa * aa
    if h2 < 0.0:
        h2 = 0.0
    h = math.sqrt(h2)
    p0 = _p2(c1[0] + aa * ux, c1[1] + aa * uy)
    pa = _p2(p0[0] - uy * h, p0[1] + ux * h)
    pb = _p2(p0[0] + uy * h, p0[1] - ux * h)
    out = pa if _dist2(pa, hint) <= _dist2(pb, hint) else pb
    return True, out


def _is_full_circ(s: ProfSeg) -> bool:  # refit_profile.cpp:503
    if not s.is_arc or not (s.r > 0.0):
        return False
    if s.phi >= K_TWO_PI - 1e-12:
        return True
    return s.phi > 0.5 * K_TWO_PI and _near2(s.a, s.b, K_ZERO_LEN)


def _analytic_area(segs: list) -> float:  # refit_profile.cpp:509
    if len(segs) == 1 and _is_full_circ(segs[0]):
        return (1.0 if segs[0].ccw else -1.0) * K_PI * segs[0].r * segs[0].r
    a = 0.0
    for s in segs:
        a += 0.5 * (s.a[0] * s.b[1] - s.b[0] * s.a[1])
        if s.is_arc and s.r > 0.0 and s.phi > 0.0 and not _is_full_circ(s):
            seg = 0.5 * s.r * s.r * (s.phi - math.sin(s.phi))
            a += (1.0 if s.ccw else -1.0) * seg
    return a


def _recompute_phi(s: ProfSeg):  # refit_profile.cpp:523
    if not s.is_arc or not (s.r > 0.0):
        return
    if _is_full_circ(s) or (_near2(s.a, s.b, K_ZERO_LEN) and s.phi > 0.5 * K_TWO_PI):
        s.phi = K_TWO_PI
        s.a = _p2(s.center[0] + s.r, s.center[1])
        s.b = s.a
        return
    u0 = _ang_of(s.center, s.a)
    u1 = _ang_of(s.center, s.b)
    d = u1 - u0
    if s.ccw:
        while d <= 0.0:
            d += K_TWO_PI
    else:
        while d >= 0.0:
            d -= K_TWO_PI
        d = -d
    if d > 0.0 and d < K_TWO_PI:
        s.phi = d


def _merge_same_circle(segs: list, tol: float):  # refit_profile.cpp:543
    if len(segs) < 2:
        return
    out = []
    acc = copy(segs[0])

    def same(a, b):
        if not a.is_arc or not b.is_arc or not (a.r > 0.0) or not (b.r > 0.0):
            return False
        if abs(a.r - b.r) > max(tol, 1e-9 * a.r):
            return False
        return _dist2(a.center, b.center) <= max(tol, 1e-9 * a.r)

    for i in range(1, len(segs)):
        s = segs[i]
        if same(acc, s) and acc.ccw == s.ccw:
            acc.b = s.b
            acc.phi += s.phi
            continue
        out.append(acc)
        acc = copy(s)
    if out and same(acc, out[0]) and acc.ccw == out[0].ccw:
        out[0].a = acc.a
        out[0].phi += acc.phi
        if out[0].phi > K_TWO_PI:
            out[0].phi = K_TWO_PI
    else:
        out.append(acc)
    for s in out:
        _recompute_phi(s)
    segs[:] = out


def _seat(s: ProfSeg, p, start: bool):  # refit_profile.cpp:605-618
    d = _dist2(p, s.center)
    if d <= K_ZERO_LEN:
        return
    ux = (p[0] - s.center[0]) / d
    uy = (p[1] - s.center[1]) / d
    s.center = _p2(p[0] - ux * s.r, p[1] - uy * s.r)
    if start:
        s.a = p
        s.b = _on_circ(s.center, s.r, s.b)
    else:
        s.b = p
        s.a = _on_circ(s.center, s.r, s.a)


def _stitch_loop(segs: list, tol: float):  # refit_profile.cpp:577
    if not segs:
        return
    for s in segs:
        if not s.is_arc or not (s.r > 0.0):
            continue
        if _is_full_circ(s):
            s.phi = K_TWO_PI
            s.a = _p2(s.center[0] + s.r, s.center[1])
            s.b = s.a
            continue
        s.a = _on_circ(s.center, s.r, s.a)
        s.b = _on_circ(s.center, s.r, s.b)
    n0 = len(segs)
    for i in range(n0):
        cur = segs[i]
        nxt = segs[(i + 1) % n0]
        if _is_full_circ(cur) or _is_full_circ(nxt):
            continue
        if cur.is_arc and nxt.is_arc and cur.r > 0.0 and nxt.r > 0.0:
            if _dist2(cur.center, nxt.center) <= tol and abs(cur.r - nxt.r) <= max(
                tol, 1e-9 * cur.r
            ):
                nxt.a = cur.b
                continue
            hint = _p2(
                0.5 * (cur.b[0] + nxt.a[0]), 0.5 * (cur.b[1] + nxt.a[1])
            )
            ok, hit = _circ_intersect(cur.center, cur.r, nxt.center, nxt.r, hint, tol)
            if ok:
                _seat(cur, hit, False)
                _seat(nxt, hit, True)
                continue
            continue
        if cur.is_arc and not nxt.is_arc:
            nxt.a = cur.b
        elif not cur.is_arc and nxt.is_arc:
            cur.b = nxt.a
        else:
            nxt.a = cur.b
    out = []
    for i in range(len(segs)):
        out.append(segs[i])
        cur = segs[i]
        nxt = segs[(i + 1) % len(segs)]
        if _is_full_circ(cur) or _is_full_circ(nxt):
            continue
        if not _near2(cur.b, nxt.a, K_ZERO_LEN):
            br = ProfSeg(is_arc=False, a=cur.b, b=nxt.a)
            out.append(br)
    segs[:] = out
    keep = []
    for s in segs:
        if not s.is_arc and _dist2(s.a, s.b) <= K_ZERO_LEN:
            continue
        keep.append(s)
    if len(keep) >= 1:
        segs[:] = keep
    for s in segs:
        _recompute_phi(s)
    if len(segs) >= 2:
        for i in range(len(segs)):
            cur = segs[i]
            nxt = segs[(i + 1) % len(segs)]
            if cur.is_arc and not nxt.is_arc:
                nxt.a = cur.b
            elif not cur.is_arc and nxt.is_arc:
                cur.b = nxt.a
            elif not cur.is_arc and not nxt.is_arc:
                nxt.a = cur.b


def _snap_closed(segs: list, tol: float):  # refit_profile.cpp:668
    if not segs:
        return
    for i in range(len(segs)):
        cur = segs[i]
        nxt = segs[(i + 1) % len(segs)]
        if not _near2(cur.b, nxt.a, tol):
            mid = _p2(0.5 * (cur.b[0] + nxt.a[0]), 0.5 * (cur.b[1] + nxt.a[1]))
            cur.b = mid
            nxt.a = mid
        else:
            nxt.a = cur.b


def _merge_colinear(segs: list, verts, tol: float):  # refit_profile.cpp:683
    if len(segs) < 2:
        return
    out = []
    acc = copy(segs[0])
    for i in range(1, len(segs)):
        s = segs[i]
        if (
            not acc.is_arc
            and not s.is_arc
            and not acc.declined_ambiguous
            and not s.declined_ambiguous
        ):
            dx = s.b[0] - acc.a[0]
            dy = s.b[1] - acc.a[1]
            length = math.hypot(dx, dy)
            mx = acc.b[0] - acc.a[0]
            my = acc.b[1] - acc.a[1]
            resid = (abs(dx * my - dy * mx) / length) if (length > 1e-18) else 0.0
            if resid <= tol:
                acc.b = s.b
                continue
        out.append(acc)
        acc = copy(s)
    out.append(acc)
    segs[:] = out


def _loop_has_radius(lp: ProfLoop, R: float, tol: float) -> bool:  # refit_profile.cpp:711
    if not (R > 0.0):
        return False
    for s in lp.segs:
        if s.is_arc and s.r > 0.0 and abs(s.r - R) <= max(tol, 0.003 * R):
            return True
    return False


def _add_circle_seg(lp: ProfLoop, c, R, ccw):  # refit_profile.cpp:720
    s = ProfSeg()
    s.is_arc = True
    s.center = c
    s.r = R
    s.phi = K_TWO_PI
    s.ccw = ccw
    s.a = _p2(c[0] + R, c[1])
    s.b = s.a
    lp.segs.append(s)


def _classify_outer(loops: list, rids):  # refit_profile.cpp:732
    if not loops:
        return
    oi = 0
    best = -1.0
    for i in range(len(loops)):
        if loops[i].area > best:
            best = loops[i].area
            oi = i
    for i in range(len(loops)):
        loops[i].outer = i == oi
    if oi != 0:
        loops[0], loops[oi] = loops[oi], loops[0]
        if rids is not None and len(rids) == len(loops):
            rids[0], rids[oi] = rids[oi], rids[0]
    loops[0].outer = True
    for i in range(1, len(loops)):
        loops[i].outer = False


def _centroid_of(pts: list) -> np.ndarray:  # refit_profile.cpp:751
    if not pts:
        return _p2(0.0, 0.0)
    sx = 0.0
    sy = 0.0
    for p in pts:
        sx += p[0]
        sy += p[1]
    n = len(pts)
    return _p2(sx / n, sy / n)


def _raw_matches_cyl(lp: _RawLoop, r, fr, tau: float) -> bool:  # refit_profile.cpp:764
    if len(lp.pts) < 3 or not (r.radius > 0.0):
        return False
    c = _cyl_center(r, fr)
    assoc = _cyl_assoc_tol(r, tau)
    mean = 0.0
    rmin = 1e300
    rmax = 0.0
    for p in lp.pts:
        d = _dist2(p, c)
        mean += d
        rmin = min(rmin, d)
        rmax = max(rmax, d)
    mean /= len(lp.pts)
    if abs(mean - r.radius) > assoc:
        return False
    if rmax - rmin > 4.0 * assoc:
        return False
    hit = 0
    for rid in lp.rids:
        if rid == r.id:
            hit += 1
    if lp.rids and hit * 2 >= len(lp.rids):
        return True
    return _dist2(_centroid_of(lp.pts), c) <= assoc


# --- slice one slab (refit_profile.cpp:787-867) ---------------------------------

def _slice_one_slab(mv, rs, lv, t, fr: _SketchFrame, slab: int, prof: Profile) -> bool:
    prof.slab = slab
    if len(lv.y) < 2:
        return False
    y0 = lv.y[slab]
    y1 = lv.y[slab + 1]
    y_slice = 0.5 * (y0 + y1)
    tol = t.tau_fit

    edges = []
    tri_region = rs.tri_region
    for ti in range(mv.n_tri):
        rid = -1
        if tri_region and ti < len(tri_region):
            rid = tri_region[ti]
        rg = _region_by_id(rs, rid) if rid >= 0 else None
        if rg is not None and rg.type == SurfType.PLANE:
            nd = abs(_dot3(_dir_xyz(rg.ax.Direction()), fr.axis))
            if nd > 1.0 - t.tau_ax:
                continue
        _slice_tri(mv, ti, rid, fr, y_slice, tol, edges)

    raw = []
    _chain_edges(edges, max(tol, 4.0 * mv.weld_tol), raw)

    # Closed-360 / through-features: one circular inner loop each.
    for r in rs.regions:
        if r.type != SurfType.CYLINDER:
            continue
        if not _cyl_covers_slab(r, lv, slab, t.tau_lvl):
            continue
        through = _is_through(r, lv, t.tau_lvl)
        hole360 = r.closed360 and not r.outward_normal
        if not through and not hole360:
            continue
        have = False
        for lp in raw:
            if not _raw_matches_cyl(lp, r, fr, tol):
                continue
            _emit_circle(r, fr, lp, max(8, r.n_sides if r.n_sides > 0 else 12))
            have = True
            break
        if not have:
            hole = _RawLoop()
            _emit_circle(r, fr, hole, max(8, r.n_sides if r.n_sides > 0 else 12))
            if len(hole.pts) >= 3:
                raw.append(hole)

    loops = []
    rid_per_loop = []
    for rl in raw:
        lp = ProfLoop()
        ids = []
        lp.area = abs(_signed_area(rl.pts))
        npts = len(rl.pts)
        for i in range(npts):
            s = ProfSeg()
            s.is_arc = False
            s.a = rl.pts[i]
            s.b = rl.pts[(i + 1) % npts]
            if _dist2(s.a, s.b) > K_ZERO_LEN:
                lp.segs.append(s)
                ids.append(rl.rids[i] if i < len(rl.rids) else -1)
        if len(lp.segs) >= 3:
            loops.append(lp)
            rid_per_loop.append(ids)
    _classify_outer(loops, rid_per_loop)
    _cache.rids.append(rid_per_loop)
    prof.loops = loops
    return bool(loops)


# --- line emission (refit_profile.cpp:869-892) ----------------------------------

def _emit_lines(verts, i0: int, i1: int, declined: bool, tol: float, out: list) -> int:
    n_decl = 0
    n = len(verts)
    if n < 2 or i0 >= n:
        return 0
    a = i0
    while a < i1 and a + 1 < n:
        b = a + 1
        while b < i1 and b < n:
            if _line_resid(verts[a], verts[b], verts, a, b) > tol:
                break
            b += 1
        if b <= a:
            b = a + 1
        s = ProfSeg()
        s.is_arc = False
        s.declined_ambiguous = declined
        s.a = verts[a]
        s.b = verts[b % n]
        if _dist2(s.a, s.b) > K_ZERO_LEN:
            out.append(s)
            if declined:
                n_decl += 1
        a = b
    return n_decl


# --- tryArc (refit_profile.cpp:894-995) -----------------------------------------

def _try_arc(mv, r, fr, verts, i0: int, i1: int, t, eps_mesh: float, exact: bool):
    lb = law_chain_accept(mv, r.tris, eps_mesh)
    if lb is None or not (lb.radius > 0.0):
        return False, None, False

    declined = _rule53a(lb, t.tau_fit)
    if declined:
        # Advisory override (refit_profile.cpp:901-907) is gated on
        # STL2STEP_PRISM_ASSIST, which the harness never sets, so the chain stays
        # declined and is emitted as lines.
        return True, None, True

    arc = ProfSeg()
    arc.is_arc = True
    arc.declined_ambiguous = False
    arc.r = lb.radius
    arc.center = _cyl_center(r, fr)
    if not exact:
        # r2 inner: mesh endpoints, law-band phi — no unwrap-to-2π.
        arc.phi = K_TWO_PI if lb.closed360 else lb.phi
        run = verts[i0:i1]
        arc.ccw = _signed_area(run) > 0.0
        n = len(verts)
        arc.a = verts[i0]
        arc.b = verts[i1 % n]
        if lb.closed360:
            arc.a = _p2(arc.center[0] + arc.r, arc.center[1])
            arc.b = arc.a
            arc.phi = K_TWO_PI
        elif _near2(arc.a, arc.b, K_ZERO_LEN):
            arc.a = _on_circ(arc.center, arc.r, arc.a)
            arc.b = arc.a
            arc.phi = 0.5 * K_TWO_PI
        return True, arc, False
    n = len(verts)
    i_last = i1 if i1 < n else (n - 1)
    if lb.closed360 and i0 == 0 and i_last + 1 >= n:
        arc.a = _p2(arc.center[0] + arc.r, arc.center[1])
        arc.b = arc.a
        arc.phi = K_TWO_PI
        arc.ccw = _signed_area(verts) > 0.0
        return True, arc, False
    span = _unwrap_span(arc.center, verts, i0, i_last)
    if not (abs(span) > 0.0):
        return False, None, False
    loc = _pnt_xyz(r.ax.Location())
    xd = _dir_xyz(r.ax.XDirection())
    yd = _dir_xyz(r.ax.YDirection())

    def at_u(u):
        q = loc + xd * (r.radius * math.cos(u)) + yd * (r.radius * math.sin(u))
        return _on_circ(arc.center, arc.r, fr.xy(q))

    p_lo = at_u(r.u_min)
    p_hi = at_u(r.u_max)
    v_a = verts[i0]
    v_b = verts[i_last]
    lo_first = _dist2(p_lo, v_a) + _dist2(p_hi, v_b) <= _dist2(p_hi, v_a) + _dist2(
        p_lo, v_b
    )
    e_a = p_lo if lo_first else p_hi
    e_b = p_hi if lo_first else p_lo
    u_a = _ang_of(arc.center, e_a)
    u_b = _ang_of(arc.center, e_b)
    gen = u_b - u_a
    if span > 0.0:
        while gen <= 0.0:
            gen += K_TWO_PI
    else:
        while gen >= 0.0:
            gen -= K_TWO_PI
    gen_ok = abs(abs(gen) - abs(span)) <= max(0.25, 0.35 * abs(span))
    if gen_ok and abs(gen) > 0.0 and abs(gen) < K_TWO_PI:
        arc.a = e_a
        arc.b = e_b
        arc.phi = abs(gen)
        arc.ccw = gen > 0.0
    else:
        a0 = _ang_of(arc.center, verts[i0])
        arc.a = _p2(arc.center[0] + arc.r * math.cos(a0), arc.center[1] + arc.r * math.sin(a0))
        a1 = a0 + span
        arc.b = _p2(arc.center[0] + arc.r * math.cos(a1), arc.center[1] + arc.r * math.sin(a1))
        arc.phi = abs(span)
        arc.ccw = span > 0.0
    return True, arc, False


# --- public entry points ---------------------------------------------------------

def slice_profiles(mv, rs, lv, tols) -> list:
    """Port of ``sliceProfiles`` (refit_profile.cpp:999)."""
    out = []
    try:
        if not lv.ok or len(lv.y) < 2:
            return out
        fr = _SketchFrame()
        if not _build_frame(rs, lv, fr):
            return out
        _cache.rs = rs
        _cache.fr = fr
        _cache.ok = True
        _cache.rids = []
        n_slab = len(lv.y) - 1
        for k in range(n_slab):
            prof = Profile(slab=k)
            if not _slice_one_slab(mv, rs, lv, tols, fr, k, prof):
                return []
            out.append(prof)

        # RULE 5.2a — through-features must appear as inner loops in every slab.
        for k in range(n_slab):
            for r in rs.regions:
                if not _is_through(r, lv, tols.tau_lvl):
                    continue
                if not _cyl_covers_slab(r, lv, k, tols.tau_lvl):
                    continue
                p = out[k]
                found = False
                for lp in p.loops:
                    if lp.outer:
                        continue
                    if _loop_has_radius(lp, r.radius, tols.tau_fit):
                        found = True
                        break
                    if len(lp.segs) >= 3:
                        c = _cyl_center(r, fr)
                        rmin = 1e300
                        rmax = 0.0
                        for s in lp.segs:
                            d = _dist2(s.a, c)
                            rmin = min(rmin, d)
                            rmax = max(rmax, d)
                        if (
                            r.radius > 0.0
                            and rmax - rmin <= 8.0 * tols.tau_fit
                            and abs(0.5 * (rmin + rmax) - r.radius)
                            <= max(tols.tau_fit, 0.003 * r.radius)
                        ):
                            found = True
                            break
                if not found:
                    hole = ProfLoop()
                    hole.outer = False
                    hole.area = K_PI * r.radius * r.radius
                    _add_circle_seg(hole, _cyl_center(r, fr), r.radius, True)
                    p.loops.append(hole)
                    _classify_outer(p.loops, None)
                    found = True
                if not found:
                    return []
        return out  # noqa: TRY300 - port of the reference's try/catch guard
    except Exception:  # noqa: BLE001 - port of the reference's catch-all guard
        return []


def fit_profile(mv, tols, profile: Profile) -> int:
    """Port of ``fitProfile`` (refit_profile.cpp:1093). Mutates ``profile.loops``
    in place and returns ``n_declined``."""
    n_declined = 0
    try:
        rs = _cache.rs if _cache.ok else None
        fr = _cache.fr if _cache.ok else None
        eps_mesh = _make_derived(mv)

        for li in range(len(profile.loops)):
            loop = profile.loops[li]
            if not loop.segs:
                continue
            verts = [loop.segs[0].a]
            for s in loop.segs:
                verts.append(s.b)
            if len(verts) >= 2 and _near2(verts[0], verts[-1], tols.tau_fit):
                verts.pop()
            if len(verts) < 2:
                if loop.segs:
                    loop.area = abs(_analytic_area(loop.segs))
                continue

            vrids = []
            if _cache.ok and profile.slab < len(_cache.rids) and li < len(
                _cache.rids[profile.slab]
            ):
                vrids = list(_cache.rids[profile.slab][li])
            while len(vrids) < len(verts):
                vrids.append(-1)

            # Closed-360 only (B10): f12-class rings.
            if rs is not None and fr is not None and len(verts) >= 3:
                only = None
                if vrids[0] >= 0:
                    only = _cyl_by_rid(rs, vrids[0])
                if only is None:
                    only = _cyl_at_point(rs, fr, verts[0], tols.tau_fit)
                all_ = only is not None and only.closed360
                if all_:
                    for k in range(len(verts)):
                        rid_hit = vrids[k] == only.id
                        if not rid_hit and not _on_cyl(verts[k], only, fr, tols.tau_fit):
                            all_ = False
                            break
                if all_:
                    lb = law_chain_accept(mv, only.tris, eps_mesh)
                    if lb is not None and lb.closed360 and not _rule53a(lb, tols.tau_fit):
                        arc = ProfSeg()
                        arc.is_arc = True
                        arc.r = lb.radius
                        arc.phi = K_TWO_PI
                        arc.center = _cyl_center(only, fr)
                        arc.a = _p2(arc.center[0] + arc.r, arc.center[1])
                        arc.b = arc.a
                        arc.ccw = _signed_area(verts) > 0.0
                        loop.segs = [arc]
                        loop.area = abs(_analytic_area(loop.segs))
                        continue

            outer_fit = loop.outer

            # Start at a non-cylinder edge so a wrap-around fillet stays one arc.
            if rs is not None and fr is not None and len(verts) >= 3:
                rot = 0
                for k in range(len(verts)):
                    if _cyl_by_rid(rs, vrids[k]) is None:
                        rot = k
                        break
                if rot > 0:
                    verts = verts[rot:] + verts[:rot]
                    vrids = vrids[rot:] + vrids[:rot]

            fitted = []
            n = len(verts)

            def edge_is_cyl(k, cr, _n=n, _vrids=vrids, _verts=verts):
                if cr is None or k >= _n:
                    return False
                if _vrids[k] == cr.id:
                    return True
                if _vrids[k] >= 0:
                    return False
                tight = max(tols.tau_fit, 1.25 * max(cr.chord_sagitta, cr.max_vertex_dev))
                return (
                    abs(_dist2(_verts[k], _cyl_center(cr, fr)) - cr.radius) <= tight
                    and abs(_dist2(_verts[(k + 1) % _n], _cyl_center(cr, fr)) - cr.radius)
                    <= tight
                )

            i = 0
            while i < n:
                took = False
                if rs is not None and fr is not None:
                    cr = _cyl_by_rid(rs, vrids[i]) if vrids[i] >= 0 else None
                    if not outer_fit and cr is None:
                        cr = _cyl_at_point(rs, fr, verts[i], tols.tau_fit)
                    if cr is not None:
                        if outer_fit:
                            j = i
                            while j + 1 < n and edge_is_cyl(j, cr):
                                j += 1
                            if j > i:
                                ok, arc, declined = _try_arc(
                                    mv, cr, fr, verts, i, j, tols, eps_mesh, True
                                )
                                if ok:
                                    if declined:
                                        n_declined += _emit_lines(
                                            verts, i, j + 1, True, tols.tau_fit, fitted
                                        )
                                    else:
                                        fitted.append(arc)
                                    i = j
                                    took = True
                        else:
                            j = i + 1
                            while j < n:
                                rid_hit = vrids[j] == cr.id
                                if not rid_hit and not _on_cyl(verts[j], cr, fr, tols.tau_fit):
                                    break
                                j += 1
                            if j > i + 1 or cr.closed360:
                                ok, arc, declined = _try_arc(
                                    mv, cr, fr, verts, i, j, tols, eps_mesh, False
                                )
                                if ok:
                                    if declined:
                                        n_declined += _emit_lines(
                                            verts, i, j, True, tols.tau_fit, fitted
                                        )
                                    else:
                                        fitted.append(arc)
                                    i = n if j >= n else j
                                    took = True
                if took:
                    continue

                j = i + 1
                while j < n:
                    if _line_resid(verts[i], verts[j], verts, i, j) > tols.tau_fit:
                        break
                    j += 1
                if j <= i + 1:
                    j = min(i + 2, n)
                if j > n:
                    j = n
                if j <= i:
                    break
                jb = j if j < n else 0
                line = ProfSeg()
                line.is_arc = False
                line.a = verts[i]
                line.b = verts[jb]
                if outer_fit:
                    keep = _dist2(line.a, line.b) > K_ZERO_LEN
                else:
                    keep = _dist2(line.a, line.b) > tols.tau_fit
                if keep:
                    fitted.append(line)
                i = j if j < n else n

            if outer_fit:
                _merge_same_circle(fitted, tols.tau_fit)
                _merge_colinear(fitted, verts, tols.tau_fit)
                _stitch_loop(fitted, tols.tau_fit)
                _merge_colinear(fitted, verts, tols.tau_fit)
                loop.segs = fitted
                loop.area = abs(_analytic_area(loop.segs))
            else:
                _snap_closed(fitted, tols.tau_fit)
                _merge_colinear(fitted, verts, tols.tau_fit)
                loop.segs = fitted
                loop.area = abs(_signed_area(verts))
        return n_declined  # noqa: TRY300 - port of the reference's try/catch guard
    except Exception:  # noqa: BLE001 - port of the reference's catch-all guard
        return n_declined
