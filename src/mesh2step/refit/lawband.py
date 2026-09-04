"""Stage L — tessellation-law band recognition. Port of refs/stl2step/src/refit_lawband.cpp.

The idea this stage rests on: an exporter that tessellates a cylinder does it by a
*law*, not by chance. It picks a chordal deviation `d` (or an angular cap) and emits
generators at a constant angular step, so every strip of the band spans the same
angle `theta` and every circumferential chord obeys

    w = 2 R sin(theta / 2)

Read backwards, a run of facets whose generator angles are equal to within a
coefficient of variation of 1e-3 *is* an arc, and its radius follows from the chord
without any fitting. That is why this stage is called "Tier 1 — parameter-free" in
the reference: no tolerance, no degree threshold, no radius prior. It only asks
whether the facets obey the law.

Order matters. The reference runs this BEFORE cylinder growing and before the plane
commit (refit_segment.cpp:47-51), because plane growing will happily swallow a
coarsely tessellated arc band as a fan of near-coplanar facets, and once it has, the
arc is gone.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .mesh_view import MeshView

K_PI = math.pi
K_TWO_PI = 2.0 * math.pi

# refit_lawband.cpp:27-30
K_CV_THETA_MAX = 1e-3
K_REL_R_MAX = 5e-4
K_CV_R_MAX = 1e-6
K_TAU_SURF_FLOOR = 5e-5


@dataclass
class LawBand:
    """A run of facets that obey the tessellation law (refit_internal.hpp LawBand)."""

    tris: list = field(default_factory=list)
    theta: list = field(default_factory=list)   # per-strip generator angle, rad
    w: list = field(default_factory=list)       # per-strip circumferential chord, mm
    radius: float = 0.0                         # median w_i / (2 sin(theta_i/2))
    axis_loc: np.ndarray = field(default_factory=lambda: np.zeros(3))
    axis_dir: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 1.0]))
    phi: float = 0.0                            # sum theta_i, or 2*pi when closed
    n: int = 0                                  # strips
    closed360: bool = False
    cv_theta: float = 0.0
    cv_r: float = 0.0
    max_vert_resid: float = 0.0
    low_confidence: bool = False                # N == 2


@dataclass
class TessLawInterval:
    """d and alpha are PER-EXPORT unknowns: intervals, never points."""

    d_lo: float = 0.0
    d_hi: float = 0.0
    alpha_lo: float = 0.0
    alpha_hi: float = 0.0
    n_d_limited: int = 0
    n_alpha_limited: int = 0
    empty: bool = True


def wrap_pi(t: float) -> float:
    while t <= -K_PI:
        t += K_TWO_PI
    while t > K_PI:
        t -= K_TWO_PI
    return t


def wrap_two_pi(t: float) -> float:
    t = math.fmod(t, K_TWO_PI)
    if t < 0.0:
        t += K_TWO_PI
    return t


def tau_surf(mv: MeshView) -> float:
    return max(K_TAU_SURF_FLOOR, 4.0 * mv.weld_tol, 1e-6 * mv.diag)


def lin_tol(mv: MeshView, eps_mesh: float) -> float:
    return max(eps_mesh, 4.0 * mv.weld_tol, 1e-6 * mv.diag, K_TAU_SURF_FLOOR)


def pop_mean(v) -> float:
    return sum(v) / len(v) if v else 0.0


def pop_cv(v) -> float:
    """Population coefficient of variation — the equal-theta test's whole instrument."""
    if len(v) < 2:
        return 0.0
    m = pop_mean(v)
    if not abs(m) > 0.0:
        return 0.0
    ss = sum((x - m) ** 2 for x in v)
    return math.sqrt(ss / len(v)) / abs(m)


def median_of(v) -> float:
    if not v:
        return 0.0
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def sign_normalize(v: np.ndarray) -> np.ndarray:
    """Fix an axis's sign by its largest component, so ±axis compare equal."""
    i = int(np.argmax(np.abs(v)))
    return -v if v[i] < 0.0 else v


def axis_frame(a_unit: np.ndarray):
    nx, ny, nz = abs(a_unit[0]), abs(a_unit[1]), abs(a_unit[2])
    if nx <= ny and nx <= nz:
        w = np.array([1.0, 0.0, 0.0])
    elif ny <= nz:
        w = np.array([0.0, 1.0, 0.0])
    else:
        w = np.array([0.0, 0.0, 1.0])
    u = np.cross(a_unit, w)
    um = float(np.linalg.norm(u))
    if um < 1e-15:
        return None
    u = u / um
    v = np.cross(a_unit, u)
    vm = float(np.linalg.norm(v))
    if vm < 1e-15:
        return None
    return u, v / vm


def _unit_tri_normal(mv: MeshView, lt: int):
    a, b, c = (mv.pts[mv.tris[lt, k]] for k in range(3))
    nu = np.cross(b - a, c - a)
    nm = float(np.linalg.norm(nu))
    area = 0.5 * nm
    if not area > 0.0 or nm < 1e-15:
        return None
    return nu / nm, area


def recover_axis_dir(mv: MeshView, ids: list):
    """The axis is the direction the facet normals rotate ABOUT.

    On a cylinder band every normal is perpendicular to the axis, so the
    area-weighted normal covariance is rank 2 and its smallest eigenvector is the
    axis. No fitting of the surface itself is involved.
    """
    nbar = np.zeros(3)
    area_sum = 0.0
    ns, areas = [], []
    for t in ids:
        r = _unit_tri_normal(mv, t)
        if r is None:
            continue
        n, area = r
        area_sum += area
        nbar = nbar + n * area
        ns.append(n)
        areas.append(area)
    if not area_sum > 0.0 or len(ns) < 2:
        return None
    nbar = nbar / area_sum
    cov = np.zeros((3, 3))
    for n, w in zip(ns, areas, strict=True):
        d = n - nbar
        cov += w * np.outer(d, d)
    _evals, evecs = np.linalg.eigh(cov)  # ascending; column k belongs to eigenvalue k
    axis = evecs[:, 0]
    am = float(np.linalg.norm(axis))
    if am < 1e-15:
        return None
    return sign_normalize(axis / am)


def collect_unique_verts(mv: MeshView, ids: list) -> np.ndarray:
    gids = sorted({int(mv.tris[t, k]) for t in ids for k in range(3)})
    return mv.pts[gids] if gids else np.zeros((0, 3))


def cluster_1d(vals, tol: float) -> list:
    if len(vals) == 0:
        return []
    s = sorted(vals)
    modes = []
    cur = [s[0]]
    for x in s[1:]:
        if abs(x - cur[-1]) <= tol:
            cur.append(x)
        else:
            modes.append(pop_mean(cur))
            cur = [x]
    modes.append(pop_mean(cur))
    return modes


def unique_positions(pts, merge: float) -> list:
    out = []
    for p in pts:
        hit = False
        for i, q in enumerate(out):
            if float(np.linalg.norm(p - q)) <= merge:
                out[i] = (q + p) * 0.5
                hit = True
                break
        if not hit:
            out.append(np.array(p, dtype=float))
    return out


def ls_bisector_center(x, y):
    """Least-squares intersection of every chord's perpendicular bisector.

    Every bisector of a chord passes through the centre, so stacking them is a
    centre estimate that never fits a radius and so cannot be biased by a short arc.
    """
    n = len(x)
    if n < 3:
        return None
    a00 = a01 = a11 = b0 = b1 = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            dx = x[j] - x[i]
            dy = y[j] - y[i]
            length = math.hypot(dx, dy)
            if length < 1e-12:
                continue
            nx = dx / length
            ny = dy / length
            mx = 0.5 * (x[i] + x[j])
            my = 0.5 * (y[i] + y[j])
            w = length * length
            proj = nx * mx + ny * my
            a00 += w * nx * nx
            a01 += w * nx * ny
            a11 += w * ny * ny
            b0 += w * nx * proj
            b1 += w * ny * proj
    det = a00 * a11 - a01 * a01
    if not abs(det) > 1e-18:
        return None
    cx = (a11 * b0 - a01 * b1) / det
    cy = (a00 * b1 - a01 * b0) / det
    if not (math.isfinite(cx) and math.isfinite(cy)):
        return None
    return cx, cy


def circumcenter2(ax, ay, bx, by, cx, cy):
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if not abs(d) > 1e-18:
        return None
    a2 = ax * ax + ay * ay
    b2 = bx * bx + by * by
    c2 = cx * cx + cy * cy
    ox = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    oy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    if not (math.isfinite(ox) and math.isfinite(oy)):
        return None
    return ox, oy


def circum_median_center(x, y):
    """Fallback centre: median circumcentre of the best-conditioned triples."""
    n = len(x)
    if n < 3:
        return None
    xs, ys, areas = [], [], []
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                area = 0.5 * abs(
                    (x[j] - x[i]) * (y[k] - y[i]) - (y[j] - y[i]) * (x[k] - x[i])
                )
                if area < 1e-10:
                    continue
                c = circumcenter2(x[i], y[i], x[j], y[j], x[k], y[k])
                if c is None:
                    continue
                xs.append(c[0])
                ys.append(c[1])
                areas.append(area)
    if not xs:
        return None
    order = sorted(range(len(xs)), key=lambda i: -areas[i])
    take = max(1, len(order) // 4)
    return (
        median_of([xs[i] for i in order[:take]]),
        median_of([ys[i] for i in order[:take]]),
    )


def azimuth(p, origin, axis, u, v) -> float:
    d = p - origin
    rad = d - axis * float(np.dot(d, axis))
    return math.atan2(float(np.dot(rad, v)), float(np.dot(rad, u)))


def rho_of(p, origin, axis) -> float:
    d = p - origin
    return float(np.linalg.norm(d - axis * float(np.dot(d, axis))))


def cluster_angles(angs, tol: float) -> list:
    """Group azimuths into generator directions, wrapping across the seam."""
    if len(angs) == 0:
        return []
    a = sorted(wrap_two_pi(x) for x in angs)
    cl = [[a[0]]]
    for x in a[1:]:
        if abs(wrap_pi(x - cl[-1][-1])) <= tol:
            cl[-1].append(x)
        else:
            cl.append([x])
    if len(cl) > 1 and abs(wrap_pi(cl[0][0] - cl[-1][-1])) <= tol:
        cl[0] = cl[-1] + cl[0]
        cl.pop()
    gens = []
    for c in cl:
        sx = sum(math.cos(t) for t in c)
        sy = sum(math.sin(t) for t in c)
        gens.append(wrap_two_pi(math.atan2(sy, sx)))
    return sorted(gens)


@dataclass
class StripPair:
    span: float = 0.0
    a0: float = 0.0
    a1: float = 0.0


def make_intervals(gens: list):
    """Consecutive generator pairs become strips; decide whether the band closes.

    An open band has one sector that is not part of the surface — the gap between
    its two ends. It shows up as a span much larger than the others, so it is
    dropped rather than measured.
    """
    pairs = []
    n_g = len(gens)
    if n_g < 2:
        return [], False
    for i in range(n_g):
        a0 = gens[i]
        a1 = gens[(i + 1) % n_g]
        span = wrap_two_pi(a1 - a0)
        if span > 1e-12:
            pairs.append(StripPair(span, a0, a1))
    if not pairs:
        return [], False
    mx = max(p.span for p in pairs)
    others = [p.span for p in pairs if p.span < mx - 1e-12] or [mx]
    med = median_of(others)
    closed = n_g >= 3 and mx < 1.8 * med
    if not closed and len(pairs) >= 2:
        pairs.sort(key=lambda p: -p.span)
        pairs.pop(0)  # drop the unused circular sector
        pairs.sort(key=lambda p: p.a0)
    return pairs, closed


_ATAN2 = np.frompyfunc(math.atan2, 2, 1)


def _row_dots(m, w):
    """Per-row `np.dot(m[i], w)`, bit-identical to the scalar call.

    A 3-vector `np.dot` is OpenBLAS `ddot`, whose tail loop is compiled to an
    FMA chain -- NOT plain `a*b + c*d + e*f`, and not `m @ w` either (that is
    `dgemv`, which accumulates in a different order). Batched matmul on
    (n,1,3)@(3,) takes numpy's vector-vector path, i.e. the same `ddot` per
    row, so the rounding matches to the bit.
    """
    return np.matmul(m[:, None, :], w)[:, 0]


def azimuths_of(pts, origin, axis, u, v):
    """Azimuths of many points about one axis frame, in a single pass.

    Bit-identical to mapping the scalar `azimuth` over `pts`: the projections
    go through `_row_dots`, and the final atan2 is libm's via `math.atan2`
    (numpy's `arctan2` is its own implementation and differs by 1 ulp on ~2%
    of inputs, enough to flip an argmin near-tie in `nearest_at_angle`).
    """
    d = np.asarray(pts, dtype=float).reshape(-1, 3) - origin
    rad = d - np.outer(_row_dots(d, axis), axis)
    return _ATAN2(_row_dots(rad, v), _row_dots(rad, u)).astype(float)


def nearest_at_angle(pts, ang, origin, axis, u, v, az=None):
    """Point whose azimuth is nearest `ang`.

    `az` is the precomputed azimuth array for `pts`. The frame is constant for a
    whole chain while the queried angle varies, so recomputing it per query cost
    25.3M scalar `azimuth` calls on a 908-triangle fixture -- 36% of total runtime.
    Only |angle difference| is compared, so vectorised wrapping to [-pi, pi) is
    interchangeable with wrap_pi's (-pi, pi]; and argmin, like the strict `<` it
    replaces, keeps the FIRST minimum.
    """
    if az is None:
        az = azimuths_of(pts, origin, axis, u, v)
    dif = az - ang
    dif -= K_TWO_PI * np.floor((dif + K_PI) / K_TWO_PI)
    return pts[int(np.argmin(np.abs(dif)))]


def axis_line_sep(a_loc, a_dir, b_loc, b_dir) -> float:
    d = b_loc - a_loc
    cr = np.cross(a_dir, b_dir)
    cm = float(np.linalg.norm(cr))
    if cm < 1e-12:
        return float(np.linalg.norm(np.cross(a_dir, d)))
    return abs(float(np.dot(d, cr))) / cm


def extract_chain(mv: MeshView, ids: list, eps_mesh: float) -> LawBand | None:
    """Recover (axis, origin, per-strip theta and chord) from the facets themselves."""
    out = LawBand()
    out.tris = list(ids)

    axis = recover_axis_dir(mv, ids)
    if axis is None:
        return None

    verts = collect_unique_verts(mv, ids)
    if len(verts) < 3:
        return None
    centroid = verts.mean(axis=0)

    axial = [float(np.dot(p - centroid, axis)) for p in verts]
    span = max(axial) - min(axial)
    mode_tol = max(1e-4, 1e-3 * max(span, 1e-9))
    modes = cluster_1d(axial, mode_tol)
    lo, hi = modes[0], modes[-1]
    ring_tol = max(5e-4, lin_tol(mv, eps_mesh))

    end_pts = [verts[i] for i in range(len(verts))
               if abs(axial[i] - lo) <= ring_tol or abs(axial[i] - hi) <= ring_tol]
    if len(end_pts) < 3:
        end_pts = list(verts)

    merge = max(4.0 * mv.weld_tol, 1e-4, 1e-6 * mv.diag)
    gens3 = unique_positions(end_pts, merge)
    if len(gens3) < 3:
        return None

    frame = axis_frame(axis)
    if frame is None:
        return None
    u, v = frame

    xs = [float(np.dot(p - centroid, u)) for p in gens3]
    ys = [float(np.dot(p - centroid, v)) for p in gens3]
    c = ls_bisector_center(xs, ys) or circum_median_center(xs, ys)
    if c is None:
        return None
    cx, cy = c
    origin = centroid + u * cx + v * cy

    # Refine the axis from generator pairs at the same azimuth on the two end rings:
    # those pairs ARE the surface's own generators, so they beat the normal-covariance
    # estimate wherever both rings are present.
    acc = np.zeros(3)
    n_p = 0
    az_all = [azimuth(p, origin, axis, u, v) for p in gens3]
    ax_all = [float(np.dot(p - centroid, axis)) for p in gens3]
    for i, p in enumerate(gens3):
        for j, q in enumerate(gens3):
            if i == j:
                continue
            if abs(wrap_pi(az_all[j] - az_all[i])) > 5e-3:
                continue
            if abs(ax_all[j] - ax_all[i]) < 1e-3:
                continue
            d = q - p
            # gp_XYZ::Modulus is scalar sqrt(x*x+y*y+z*z); np.linalg.norm is a scaled
            # two-pass dnrm2 and differs by ulps. This is the one site in this loop
            # where that reaches a VALUE -- az_all/ax_all only feed 5e-3/1e-3 gates and
            # np.dot(d, axis) is a sign test -- and 96 d/m terms accumulate here.
            m = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
            if m < 1e-9:
                continue
            d = d / m
            if float(np.dot(d, axis)) < 0.0:
                d = -d
            acc = acc + d
            n_p += 1
    acc_m = math.sqrt(acc[0] * acc[0] + acc[1] * acc[1] + acc[2] * acc[2])
    if n_p >= 2 and acc_m > 1e-15:
        axis = sign_normalize(acc / acc_m)
        frame = axis_frame(axis)
        if frame is not None:
            u, v = frame
            xs = [float(np.dot(p - centroid, u)) for p in gens3]
            ys = [float(np.dot(p - centroid, v)) for p in gens3]
            c = ls_bisector_center(xs, ys) or circum_median_center(xs, ys)
            if c is not None:
                origin = centroid + u * c[0] + v * c[1]

    gens = cluster_angles([azimuth(p, origin, axis, u, v) for p in gens3], 5e-4)
    if len(gens) < 2:
        return None

    pairs, closed = make_intervals(gens)
    if not pairs:
        return None

    radii = []
    gaz = azimuths_of(gens3, origin, axis, u, v)  # frame is fixed for the chain
    for p in pairs:
        p0 = nearest_at_angle(gens3, p.a0, origin, axis, u, v, gaz)
        p1 = nearest_at_angle(gens3, p.a1, origin, axis, u, v, gaz)
        d = p1 - p0
        w3 = float(np.linalg.norm(d - axis * float(np.dot(d, axis))))
        rho = 0.5 * (rho_of(p0, origin, axis) + rho_of(p1, origin, axis))
        s = math.sin(0.5 * p.span)
        if not s > 1e-15:
            continue
        # Circumferential chord of the two generators about the recovered axis; the
        # polar form is the same chord on the inscribed circle.
        w = 2.0 * rho * s if rho > 0.0 else w3
        if not w > 0.0:
            continue
        out.theta.append(p.span)
        out.w.append(w)
        radii.append(w / (2.0 * s))

    out.axis_loc = origin
    out.axis_dir = axis
    if len(out.theta) < 2:
        out.n = len(out.theta)
        if radii:
            out.radius = median_of(radii)
        return None

    # Equal-theta inverse: R_i straight from the measured (w_i, theta_i).
    out.radius = median_of(radii)
    out.n = len(out.theta)
    out.closed360 = closed
    out.phi = K_TWO_PI if closed else sum(out.theta)
    out.cv_theta = pop_cv(out.theta)
    out.cv_r = pop_cv(radii)
    out.max_vert_resid = max(
        (abs(rho_of(p, origin, axis) - out.radius) for p in verts), default=0.0
    )
    return out


def _test_equal_theta(b: LawBand) -> bool:
    return b.cv_theta < K_CV_THETA_MAX


def _test_r_cons(b: LawBand) -> bool:
    if not (b.radius > 0.0) or len(b.theta) != len(b.w) or not b.theta:
        return False
    mx = 0.0
    radii = []
    for th, w in zip(b.theta, b.w, strict=True):
        s = math.sin(0.5 * th)
        if not s > 1e-15:
            return False
        r = w / (2.0 * s)
        radii.append(r)
        mx = max(mx, abs(r - b.radius) / b.radius)
    return mx < K_REL_R_MAX and (pop_cv(radii) < K_CV_R_MAX or b.cv_theta < K_CV_THETA_MAX)


def _test_common_axis(mv: MeshView, ids: list, b: LawBand, eps_mesh: float) -> bool:
    """Generator edges (those parallel to the axis) must sit at the same radius."""
    lim = lin_tol(mv, eps_mesh)
    n_gen = n_ok = 0
    for t in ids:
        for s in range(3):
            e = int(mv.tri_edges[t, s])
            v0, v1 = mv.comp_edges[e]
            p0 = mv.pts[v0]
            p1 = mv.pts[v1]
            d = p1 - p0
            length = float(np.linalg.norm(d))
            if not length > 1e-12:
                continue
            ehat = d / length
            tilt = float(np.linalg.norm(np.cross(ehat, b.axis_dir)))
            if tilt * length > lim * 8.0:
                continue
            if abs(float(np.dot(ehat, b.axis_dir))) < 0.98:
                continue
            n_gen += 1
            mid_rho = rho_of((p0 + p1) * 0.5, b.axis_loc, b.axis_dir)
            if abs(mid_rho - b.radius) < max(lim, 5e-3 * max(b.radius, 1.0)):
                n_ok += 1
    if n_gen < 2:
        return True  # no generator edges resolved; the covariance axis stands
    return n_ok * 2 >= n_gen


def _test_on_surface(b: LawBand, mv: MeshView) -> bool:
    return b.max_vert_resid < tau_surf(mv)


def _cap_circle_ok(mv: MeshView, ids: list, b: LawBand) -> bool:
    verts = collect_unique_verts(mv, ids)
    if len(verts) < 3 or not b.radius > 0.0:
        return False
    rhos = [rho_of(p, b.axis_loc, b.axis_dir) for p in verts]
    if not median_of(rhos) > 0.0:
        return False
    mx = max(abs(r - b.radius) / b.radius for r in rhos)
    return mx < K_REL_R_MAX and pop_cv(rhos) < 1e-3


def law_chain_accept(mv: MeshView, tris: list, eps_mesh: float):
    """Tier 1 — parameter-free. Returns the LawBand when the facets obey the law."""
    ids = sorted(set(tris))
    if len(ids) < 2:
        return None
    band = extract_chain(mv, ids, eps_mesh)
    if band is None:
        return None

    t1 = _test_equal_theta(band)
    t2 = _test_r_cons(band)
    t3 = _test_common_axis(mv, ids, band, eps_mesh)
    t4 = _test_on_surface(band, mv)

    band.low_confidence = False
    if band.n <= 1:
        return None
    if band.n == 2:
        # N == 2 needs the cap-circle too: a 4-triangle plane/cylinder chimera can
        # look like two strips, so demand a real chain before believing it.
        accept = t1 and t2 and t3 and t4 and _cap_circle_ok(mv, ids, band) and len(ids) >= 6
        band.low_confidence = accept
    else:
        accept = t1 and t2 and t3 and t4
    return band if accept else None


def _d_feasible(b: LawBand):
    """The chordal deviations `d` consistent with this band, as an interval."""
    if b.n < 2 or not b.radius > 0.0 or not b.phi > 0.0:
        return None
    th_lo = b.phi / b.n
    th_hi = b.phi / (b.n - 1)
    if not th_lo > 0.0 or th_lo >= K_PI:
        return None

    def d_from(th):
        return b.radius * (1.0 - math.cos(0.5 * th))

    lo = d_from(th_lo)
    hi = 2.0 * b.radius if th_hi >= K_PI else d_from(th_hi)
    if not (hi > lo and math.isfinite(lo) and math.isfinite(hi)):
        return None
    return lo, hi


def theta_surf(radius: float, d: float) -> float:
    """Generator angle a chordal-deviation budget `d` implies at radius `radius`."""
    if not (radius > 0.0) or not (d > 0.0) or d >= 2.0 * radius:
        return 0.0
    x = 1.0 - d / radius
    if x <= -1.0:
        return K_PI
    if x >= 1.0:
        return 0.0
    return 2.0 * math.acos(x)


def law_calibrate(bands: list) -> TessLawInterval:
    """Tier 2 — recover the export's own settings from the accepted bands.

    A single export used one chordal-deviation budget `d` and one angular cap, so the
    per-band feasible `d` intervals should share a common point. Rather than
    intersecting all of them and failing on the first outlier, the reference takes the
    LARGEST subset with a non-empty intersection (a maximum interval stabbing) and
    calls those "d-limited". A band left out is only forgiven if it is explicable as
    *angle*-limited instead: its equal-theta step is smaller than the angle `d` alone
    would have allowed, meaning the angular cap bound first. Any band that is neither
    means the component mixes exports, and then the stage declines wholesale rather
    than pick which half to believe.
    """
    li = TessLawInterval()
    iv = [_d_feasible(b) for b in bands]
    idx = [i for i, x in enumerate(iv) if x is not None]
    if not idx:
        return li

    # Maximum interval stabbing: sweep endpoints, opening before closing at ties.
    events = []
    for i in idx:
        events.append((iv[i][0], 1, i))
        events.append((iv[i][1], -1, i))
    events.sort(key=lambda e: (e[0], -e[1]))
    cov = best = 0
    best_x = events[0][0]
    for x, s, _i in events:
        cov += s
        if cov > best:
            best = cov
            best_x = x

    dset = [i for i in idx if iv[i][0] <= best_x < iv[i][1]]
    leftover = [i for i in idx if not (iv[i][0] <= best_x < iv[i][1])]
    if not dset:
        return li

    d_lo = max(iv[i][0] for i in dset)
    d_hi = min(iv[i][1] for i in dset)
    d_mid = 0.5 * (d_lo + d_hi)

    aset = []
    mixed = False
    for i in leftover:
        b = bands[i]
        th_eq = (b.phi / b.n) if b.n > 0 else 0.0
        if theta_surf(b.radius, d_mid) > th_eq and b.n >= 2:
            aset.append(i)
        else:
            mixed = True
    if mixed:
        li.n_d_limited = len(dset)
        li.n_alpha_limited = len(aset)
        return li

    li.d_lo = d_lo
    li.d_hi = d_hi
    li.n_d_limited = len(dset)
    li.n_alpha_limited = len(aset)
    li.empty = not (d_hi > d_lo)

    if aset:
        a_lo, a_hi = 0.0, 1e300
        first = True
        for i in aset:
            b = bands[i]
            if b.n < 2:
                continue
            lo = b.phi / b.n
            hi = b.phi / (b.n - 1)
            if first:
                a_lo, a_hi, first = lo, hi, False
            else:
                a_lo = max(a_lo, lo)
                a_hi = min(a_hi, hi)
        if not first and a_hi > a_lo:
            li.alpha_lo = a_lo
            li.alpha_hi = a_hi
    return li


def law_bands_mergeable(a: LawBand, b: LawBand, mv: MeshView, eps_mesh: float) -> bool:
    """Merge iff coaxial, radius-consistent, and still equal-theta once concatenated."""
    if not (a.radius > 0.0 and b.radius > 0.0):
        return False
    r_avg = 0.5 * (a.radius + b.radius)
    if abs(a.radius - b.radius) / max(r_avg, 1e-12) >= K_REL_R_MAX:
        return False
    if abs(float(np.dot(a.axis_dir, b.axis_dir))) < 0.999:
        return False
    lim = lin_tol(mv, eps_mesh)
    sep = axis_line_sep(a.axis_loc, a.axis_dir, b.axis_loc, b.axis_dir)
    if sep > max(lim, K_REL_R_MAX * max(r_avg, 1.0)):
        return False
    return pop_cv(list(a.theta) + list(b.theta)) < K_CV_THETA_MAX
