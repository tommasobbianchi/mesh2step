"""TrueForm planar segmentation — port of refs/stl2step/src/refit_segment.cpp,
refit_grow.cpp (stages A1/A2/A3) and refit_chains.cpp (stage D).

Only the planar path is implemented (M2): charts (A1), running-PCA provisional
plane growth (A2), plane commit with facet-island demotion (A3) and boundary
chain / loop topology with the RefitStats census (D). Cylinder, law-band and
fillet claiming (B1/L/C1) are M3-M5 stubs that claim nothing; the prismatic
rebuild is likewise out of scope.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field, replace
from enum import IntEnum

import numpy as np
from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt

from .lawband import (
    law_bands_mergeable,
    law_calibrate,
    law_chain_accept,
    sign_normalize,
)
from .mesh_view import (
    MeshView,
    build_edge_adj,
    edge_dihedral_abs,
    local_verts_of_tri,
    tri_area,
    tri_centroid,
    tri_corner,
    tri_normal,
)
from .stats import RefitStats

K_PI = math.pi
K_DEG3 = 3.0 * K_PI / 180.0
INT_MAX = 2**31 - 1

# refit_internal.hpp DerivedTols static constants (D5.2, verbatim)
K_GAUSS_PLANARITY = 0.05
K_G3_LO = 0.35
K_G3_HI = 2.00
K_G5_SPAN_CLOSED_DEG = 300.0
K_G5_SPAN_PARTIAL_DEG = 40.0
K_G5_NSIDES_MIN = 6
K_G5_NBANDS_MIN = 4
# refit_grow.cpp kRingResidualFrac (D1.3-A3, file-local B1 residual)
K_RING_RESIDUAL_FRAC = 0.25
K_TINY = 1e-30
# refit_math.cpp kPrattNewtonCap -- Chernov reports 4-6 iterations typical.
K_PRATT_NEWTON_CAP = 20
# refit_grow.cpp:1153-1155. Normal-parallelism gates for law strips: cos(2deg) for
# the chart pass, cos(1deg) for the tighter leftover pass.
K_LAW_STRIP_NORMAL_COS = 0.9993908270190957
K_LAW_STRIP_NORMAL_COS_TIGHT = 0.9998476951563913
K_LAW_R_REL_GROW = 5e-4


class SurfType(IntEnum):
    PLANE = 0
    CYLINDER = 1
    CONE = 2
    SPHERE = 3
    TORUS = 4


class Origin(IntEnum):
    PLANE_GROW = 0
    CYL_GROW = 1
    FILLET_STRIP = 2


class BuiltAs(IntEnum):
    NOT_BUILT = 0
    SINGLE = 1
    SEAMED360 = 2
    TWO_HALVES = 3
    EXPLODED_TO_FACETS = 4


class Reject(IntEnum):
    NONE = 0
    GAUSS_PLANARITY = 1
    VERTEX_RESIDUAL = 2
    CHORD_CONSISTENCY = 3
    RADIUS_SANITY = 4
    SPAN = 5
    FILLET_CONSENSUS = 6
    NEIGHBOR_NOT_ANALYTIC = 7
    STRIP_WIDTH = 8
    TORUS_NYI = 9
    CONE_NYI = 10
    SPHERE_NYI = 11
    DIRTY_COMPONENT = 12
    FACE_BUILD_FAILED = 13
    CHAIN_UNSTABLE = 14


class LoopRole(IntEnum):
    OUTER = 0
    INNER = 1
    CAP_LOW = 2
    CAP_HIGH = 3


class ProvClaim(IntEnum):
    UNCLAIMED = 0
    IN_CYLINDER_CLAIM = 1
    CONSUMED_CYLINDER = 2
    IN_FILLET_CLAIM = 3
    CONSUMED_FILLET = 4
    COMMITTED_PLANE = 5


class Gate(IntEnum):
    G1 = 0
    G2 = 1
    G3 = 2
    G4 = 3
    G5 = 4
    PASS = 5


@dataclass
class SegmentParams:
    """Port of refit::SegmentParams at the golden defaults.

    eps_mesh / eps_plane are in mm, 0 => auto-derive from the MeshView
    (refit_segment.cpp deriveTols). Angles in degrees.
    """
    eps_mesh: float = 0.0
    eps_plane: float = 0.0          # Options::smoothTolMM (0 = auto)
    theta_plane_deg: float = 2.0    # Options::smoothAngleDeg
    theta_sharp_deg: float = 30.0
    theta_cyl_lo_deg: float = 5.0   # Phase B seed band, INCLUSIVE
    theta_cyl_hi_deg: float = 60.0  # Phase B seed band, INCLUSIVE (D5.4)
    theta_bin_deg: float = 0.25     # nSides band-clustering floor (D2.2)
    do_fillets: bool = True         # Options::smoothFillets


@dataclass
class DerivedTols:
    eps_mesh: float = 0.0
    eps_plane: float = 0.0
    theta_plane: float = 0.0      # radians
    theta_sharp: float = 0.0
    theta_cyl_lo: float = 0.0
    theta_cyl_hi: float = 0.0
    theta_bin: float = 0.0

    def gauss_axis_tilt_sin(self) -> float:
        return math.sin(K_DEG3)

    def eps_cyl_accept(self, r: float) -> float:
        return max(self.eps_mesh, 0.01 * r)


@dataclass
class Provisional:
    chart_id: int = -1
    tris: list = field(default_factory=list)  # LOCAL triangle ids, ascending
    plane: gp_Ax3 | None = None
    area: float = 0.0
    max_vertex_dev: float = 0.0
    rms_vertex_dev: float = 0.0
    claim: int = ProvClaim.UNCLAIMED
    seed_tried: bool = False


@dataclass
class Loop:
    chain_idx: list = field(default_factory=list)  # indices into RegionSet.chains
    reversed: list = field(default_factory=list)   # 1 = traverse that chain backwards
    role: int = LoopRole.OUTER


@dataclass
class Region:
    id: int = -1
    type: int = SurfType.PLANE
    origin: int = Origin.PLANE_GROW
    ax: gp_Ax3 | None = None       # Plane: point + normal (same frame as pts)
    radius: float = 0.0
    closed360: bool = False
    outward_normal: bool = True
    tris: list = field(default_factory=list)   # LOCAL triangle indices
    loops: list = field(default_factory=list)  # Loop objects
    max_vertex_dev: float = 0.0
    rms_vertex_dev: float = 0.0
    chord_sagitta: float = 0.0
    n_sides: int = 0
    dvol_predicted: float = 0.0
    reject: int = Reject.NONE
    built_as: int = BuiltAs.NOT_BUILT
    fillet_nbr_a: int = -1
    fillet_nbr_b: int = -1
    law_band: bool = False   # claimed by stage L rather than grown by B1
    u_min: float = 0.0       # cylinder parametric extent (D2)
    u_max: float = 0.0
    v_min: float = 0.0
    v_max: float = 0.0


@dataclass
class BoundaryChain:
    reg_a: int = -1        # region ids; -1 => faceted island
    reg_b: int = -1
    island_a: int = -1
    island_b: int = -1
    tangent: bool = False
    closed_loop: bool = False
    mesh_edges: list = field(default_factory=list)  # ordered LOCAL edge ids
    mesh_verts: list = field(default_factory=list)  # ordered LOCAL vertex ids


@dataclass
class RegionSet:
    comp_root: int = -1
    regions: list = field(default_factory=list)    # accepted only (reject == NONE)
    rejected: list = field(default_factory=list)   # diagnostics; never built
    chains: list = field(default_factory=list)
    tri_region: list = field(default_factory=list)  # local tri -> region id, else -1
    tri_island: list = field(default_factory=list)  # local tri -> island id, else -1
    n_islands: int = 0
    stats: RefitStats = field(default_factory=RefitStats)


@dataclass
class _SegmentWork:
    tri_chart: list = field(default_factory=list)
    n_charts: int = 0
    provisionals: list = field(default_factory=list)
    accepted: list = field(default_factory=list)
    rejected: list = field(default_factory=list)


@dataclass
class _GaussResult:
    ok: bool = False
    degenerate: bool = False
    axis: np.ndarray = field(default_factory=lambda: np.zeros(3))
    mu1: float = 0.0
    mu2: float = 0.0
    mu3: float = 0.0
    flat: float = 0.0
    patch: float = 0.0
    c: float = 0.0
    dev: float = 0.0


@dataclass
class _D2Metrics:
    n_bands: int = 0
    span: float = 0.0
    n_sides: int = 0
    u_min: float = 0.0
    u_max: float = 0.0
    v_min: float = 0.0
    v_max: float = 0.0
    closed360: bool = False
    ax: gp_Ax3 | None = None
    center: np.ndarray = field(default_factory=lambda: np.zeros(3))
    radius: float = 0.0
    span_reject: bool = False


@dataclass
class _CommitEval:
    fail_gate: int = Gate.G1
    eberly_ok: bool = False
    center: np.ndarray = field(default_factory=lambda: np.zeros(3))
    radius: float = 0.0
    d2: _D2Metrics = field(default_factory=_D2Metrics)
    g: _GaussResult = field(default_factory=_GaussResult)
    arch_chain: bool = False


@dataclass
class _ProvAdj:
    other: int = -1
    phi: float = 0.0
    length: int = 0


@dataclass
class _Seed:
    p: int = -1
    q: int = -1
    neg_area_sum: float = 0.0
    min_tri: int = -1
    max_tri: int = -1
    adj_lo: int = -1
    adj_hi: int = -1


@dataclass
class _GrowCand:
    x: int = -1
    neg_len: int = 0
    min_tri: int = -1


# --- tolerance derivation (refit_segment.cpp deriveTols, verbatim) -------------

def coarse_fusion_band(mv: MeshView) -> bool:
    return 500 <= mv.n_tri <= 1200


def law_band_applicable(mv: MeshView) -> bool:
    """refit_internal.hpp archChainBand. Overlaps the coarse band on [500, 1200];
    the 8000 ceiling excludes Body11 (15300 triangles) and its 12060-triangle body."""
    return 500 <= mv.n_tri <= 8000


def derive_tols(mv: MeshView, p: SegmentParams) -> DerivedTols:
    tol = DerivedTols()
    tol.eps_mesh = p.eps_mesh if p.eps_mesh > 0.0 else max(mv.weld_tol, 1e-4 * mv.diag, 1e-3)
    tol.eps_plane = p.eps_plane if p.eps_plane > 0.0 else max(tol.eps_mesh, mv.sew_tol, 0.02)
    tol.theta_plane = math.radians(p.theta_plane_deg)
    tol.theta_sharp = math.radians(p.theta_sharp_deg)
    tol.theta_cyl_lo = math.radians(p.theta_cyl_lo_deg)
    tol.theta_cyl_hi = math.radians(p.theta_cyl_hi_deg)
    tol.theta_bin = math.radians(p.theta_bin_deg)
    return tol


def adapt_coarse_segment_params(mv: MeshView, p: SegmentParams) -> SegmentParams:
    """refit_segment.cpp adaptCoarseSegmentParams, applied BEFORE derive_tols.

    In the coarse band the tessellation no longer resolves the difference between a
    gently curved band and a plane at a 2-degree gate, so the gates widen to where
    the signal actually is: plane growth to 15 degrees, the cylinder seed band's
    upper edge to 70. This is not tuning -- it is the regime the mesh is in. Without
    it every coarse-band measurement is taken under the wrong parameters.
    """
    if not coarse_fusion_band(mv):
        return p
    return replace(
        p,
        theta_plane_deg=max(p.theta_plane_deg, 15.0),
        theta_cyl_hi_deg=max(p.theta_cyl_hi_deg, 70.0),
    )


def derived_eps_plane(mv: MeshView) -> float:
    """Same derivation as DerivedTols::epsPlane (frozen TU, refit_build.cpp)."""
    diag = mv.diag if mv.diag > 0.0 else 1.0
    eps_mesh = max(mv.weld_tol, 1e-4 * diag, 1e-3)
    return max(eps_mesh, mv.sew_tol, 0.02)


# --- math (refit_math.cpp pcaPlane, verbatim formula) --------------------------

def pca_plane(mv: MeshView, tris: list) -> gp_Ax3 | None:
    """Area-weighted centroid + smallest-eigenvector normal, oriented toward the
    mean of unnormalized facet normals (refit_math.cpp pcaPlane)."""
    ids = sorted(set(tris))
    if not ids:
        return None
    area_sum = 0.0
    c = np.zeros(3)
    n_mean = np.zeros(3)
    geoms = []
    for t in ids:
        a, b, p = (tri_corner(mv, t, k) for k in range(3))
        n_un = np.cross(b - a, p - a)
        area = 0.5 * float(np.linalg.norm(n_un))
        if not np.isfinite(area) or area <= 0.0:
            continue
        g = (a + b + p) / 3.0
        area_sum += area
        c += g * area
        n_mean += n_un
        geoms.append((a, b, p, area))
    if not (area_sum > 0.0) or not np.all(np.isfinite(c)):
        return None
    c /= area_sum

    cov = np.zeros((3, 3))
    for a, b, p, area in geoms:
        w = area / 3.0
        for d in (a - c, b - c, p - c):
            cov += w * np.outer(d, d)

    try:
        _evals, evecs = np.linalg.eigh(cov)
    except np.linalg.LinAlgError:
        return None
    n = evecs[:, 0]
    nm = float(np.linalg.norm(n))
    if not np.isfinite(nm) or nm < 1e-15:
        return None
    n = n / nm
    if float(np.dot(n, n_mean)) < 0.0:
        n = -n
    if float(np.linalg.norm(n)) < 1e-15:
        return None
    loc = gp_Pnt(float(c[0]), float(c[1]), float(c[2]))
    d = gp_Dir(float(n[0]), float(n[1]), float(n[2]))
    return gp_Ax3(loc, d)


def compute_prov_deviations(mv: MeshView, p: Provisional) -> None:
    n = p.plane.Direction()
    n = np.array([n.X(), n.Y(), n.Z()])
    loc = p.plane.Location()
    loc = np.array([loc.X(), loc.Y(), loc.Z()])
    sum_sq = 0.0
    max_d = 0.0
    n_pts = 0
    for lt in p.tris:
        for k in range(3):
            v = tri_corner(mv, lt, k)
            d = abs(float(np.dot(v - loc, n)))
            max_d = max(max_d, d)
            sum_sq += d * d
            n_pts += 1
    p.max_vertex_dev = max_d
    p.rms_vertex_dev = math.sqrt(sum_sq / n_pts) if n_pts > 0 else 0.0


def compute_outward_plane(mv: MeshView, tris: list, plane: gp_Ax3) -> bool:
    n = np.array([plane.Direction().X(), plane.Direction().Y(), plane.Direction().Z()])
    sigma = 0.0
    for lt in tris:
        sigma += tri_area(mv, lt) * float(np.dot(tri_normal(mv, lt), n))
    return sigma > 0.0


def dvol_plane_region(mv: MeshView, tris: list, ax: gp_Ax3) -> float:
    """Signed mm^3 the analytic surface adds vs the chords (D4.3 leading minus)."""
    ids = sorted(set(tris))
    n = np.array([ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()])
    o = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()])
    total = 0.0
    for t in ids:
        a, b, p = (tri_corner(mv, t, k) for k in range(3))
        area = tri_area(mv, t)
        if area <= 0.0:
            continue
        total += area * (
            float(np.dot(a - o, n)) + float(np.dot(b - o, n)) + float(np.dot(p - o, n))
        ) / 3.0
    dvol = -total
    return dvol if math.isfinite(dvol) else 0.0


class _UnionFind:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, a: int) -> int:
        p = self.p
        while p[a] != a:
            p[a] = p[p[a]]
            a = p[a]
        return a

    def unite(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


# --- A1: charts (refit_grow.cpp chartsA1) --------------------------------------

def _charts_a1(mv: MeshView, tol: DerivedTols, work: _SegmentWork) -> bool:
    work.tri_chart = [-1] * mv.n_tri
    work.n_charts = 0
    if mv.n_tri == 0:
        return True

    adj = build_edge_adj(mv)
    uf = _UnionFind(mv.n_tri)
    for e in range(mv.n_edge):
        t0, t1 = adj[e]
        if t0 < 0 or t1 < 0:
            continue
        phi = edge_dihedral_abs(mv, e, adj)
        if phi <= tol.theta_sharp:
            uf.unite(t0, t1)

    components: dict[int, list[int]] = {}
    for t in range(mv.n_tri):
        components.setdefault(uf.find(t), []).append(t)

    chart_order = sorted(
        (min(tris), idx) for idx, tris in enumerate(components.values())
    )
    work.n_charts = len(chart_order)
    remap = {old: new for new, (_, old) in enumerate(chart_order)}
    for old, tris in enumerate(components.values()):
        chart_id = remap[old]
        for t in tris:
            work.tri_chart[t] = chart_id
    return True


# --- A2: provisional plane growth (refit_grow.cpp growProvisionalA2) -----------

def _grow_provisional_a2(mv: MeshView, tol: DerivedTols, work: _SegmentWork) -> bool:
    work.provisionals = []
    if mv.n_tri == 0:
        return True

    adj = build_edge_adj(mv)
    tri_label = [-1] * mv.n_tri

    tri_neighbors: list[list[tuple[int, int]]] = [[] for _ in range(mv.n_tri)]
    for e in range(mv.n_edge):
        t0, t1 = adj[e]
        if t0 < 0 or t1 < 0:
            continue
        tri_neighbors[t0].append((e, t1))
        tri_neighbors[t1].append((e, t0))
    for nb in tri_neighbors:
        nb.sort(key=lambda x: x[0])

    cos_plane = math.cos(tol.theta_plane)
    n_charts = work.n_charts if work.n_charts > 0 else 1
    for chart in range(n_charts):
        while True:
            seed = -1
            best_area = -1.0
            for t in range(mv.n_tri):
                if tri_label[t] >= 0:
                    continue
                if work.tri_chart[t] != chart:
                    continue
                a = tri_area(mv, t)
                if a > best_area or (a == best_area and t < seed):
                    best_area = a
                    seed = t
            if seed < 0:
                break

            prov = Provisional(chart_id=chart)
            queue = [seed]
            tri_label[seed] = len(work.provisionals)

            seed_c = tri_centroid(mv, seed)
            seed_n = tri_normal(mv, seed)
            plane = gp_Ax3(
                gp_Pnt(float(seed_c[0]), float(seed_c[1]), float(seed_c[2])),
                gp_Dir(float(seed_n[0]), float(seed_n[1]), float(seed_n[2])),
            )
            grow_tris: list[int] = []

            while queue:
                t = queue.pop(0)
                grow_tris.append(t)

                if len(grow_tris) > 2:
                    refreshed = pca_plane(mv, grow_tris)
                    if refreshed is not None:
                        pca_n = refreshed.Direction()
                        d = abs(
                            float(seed_n[0]) * pca_n.X()
                            + float(seed_n[1]) * pca_n.Y()
                            + float(seed_n[2]) * pca_n.Z()
                        )
                        if d >= cos_plane:
                            plane = refreshed
                        else:
                            plane = gp_Ax3(
                                refreshed.Location(),
                                gp_Dir(float(seed_n[0]), float(seed_n[1]), float(seed_n[2])),
                            )

                n_p = plane.Direction()
                n_p = np.array([n_p.X(), n_p.Y(), n_p.Z()])
                loc = plane.Location()
                loc = np.array([loc.X(), loc.Y(), loc.Z()])
                for e, u in tri_neighbors[t]:
                    if tri_label[u] >= 0:
                        continue
                    if work.tri_chart[u] != chart:
                        continue
                    phi = edge_dihedral_abs(mv, e, adj)
                    if phi > tol.theta_sharp:
                        continue
                    n_u = tri_normal(mv, u)
                    if abs(float(np.dot(n_u, n_p))) < cos_plane:
                        continue
                    max_d = 0.0
                    for k in range(3):
                        v = tri_corner(mv, u, k)
                        max_d = max(max_d, abs(float(np.dot(v - loc, n_p))))
                    if max_d > tol.eps_plane:
                        continue

                    trial = [*grow_tris, u]
                    trial_plane = pca_plane(mv, trial)
                    if trial_plane is None:
                        trial_plane = plane
                    else:
                        pca_n = trial_plane.Direction()
                        d = abs(
                            float(seed_n[0]) * pca_n.X()
                            + float(seed_n[1]) * pca_n.Y()
                            + float(seed_n[2]) * pca_n.Z()
                        )
                        if d < cos_plane:
                            trial_plane = gp_Ax3(
                                trial_plane.Location(),
                                gp_Dir(float(seed_n[0]), float(seed_n[1]), float(seed_n[2])),
                            )

                    tri_label[u] = len(work.provisionals)
                    queue.append(u)
                    plane = trial_plane

            grow_tris.sort()
            prov.tris = grow_tris
            prov.plane = plane
            prov.area = 0.0
            for lt in prov.tris:
                prov.area += tri_area(mv, lt)
            compute_prov_deviations(mv, prov)
            work.provisionals.append(prov)

    work.provisionals.sort(key=lambda p: p.tris[0] if p.tris else INT_MAX)
    return True


# --- B1: cylinder claim (refit_grow.cpp claimCylindersB1 + gate chain) ---------
# Port of the whole provisional-merge cylinder recognition path: seed pairs,
# grow members, evaluateCommit (G1..G5), and the reject census. The coarse-band
# radius refinement / arch-chain helpers below are band-guarded no-ops for
# n_tri < 500 (ponytail: coarse band 500..1200 is not exercised by any in-scope
# fixture — fill in _refine_cylinder_radius when a coarse fixture lands).


def _llround(x: float) -> int:
    return math.floor(x + 0.5)


def _median_of(v: list) -> float:
    if not v:
        return 0.0
    s = sorted(v)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return 0.5 * (s[n // 2 - 1] + s[n // 2])


def _percentile75(v: list) -> float:
    if not v:
        return 0.0
    s = sorted(v)
    idx = math.floor(0.75 * (len(s) - 1))
    return s[idx]


def _wrap_to_pi(t: float) -> float:
    while t <= -K_PI:
        t += 2.0 * K_PI
    while t > K_PI:
        t -= 2.0 * K_PI
    return t


def _angle_band_eps(theta_rad: float) -> float:
    k_abs = 1e-12
    ulp = sys.float_info.epsilon * max(1.0, abs(theta_rad))
    return max(k_abs, 8.0 * ulp)


def _eigen_axis_sign(w: np.ndarray) -> float:
    for k in range(3):
        if abs(w[k]) > 1e-9:
            return 1.0 if w[k] > 0.0 else -1.0
    return 1.0


def _canonical_axis(w: np.ndarray) -> np.ndarray:
    m = float(np.linalg.norm(w))
    if m < K_TINY:
        return np.array([1.0, 0.0, 0.0])
    return (w * _eigen_axis_sign(w)) / m


def _gp_dir(v: np.ndarray) -> gp_Dir:
    return gp_Dir(float(v[0]), float(v[1]), float(v[2]))


def _gp_pnt(v: np.ndarray) -> gp_Pnt:
    return gp_Pnt(float(v[0]), float(v[1]), float(v[2]))


def _np_dir(d: gp_Dir) -> np.ndarray:
    return np.array([d.X(), d.Y(), d.Z()])


def _np_pnt(p: gp_Pnt) -> np.ndarray:
    return np.array([p.X(), p.Y(), p.Z()])


def _axis_frame(a_unit: np.ndarray):
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
    v = v / vm
    return u, v


def _solve2x2(a00, a01, a11, b0, b1):
    det = a00 * a11 - a01 * a01
    scale = abs(a00) + abs(a11) + 2.0 * abs(a01)
    if not (math.isfinite(det) and math.isfinite(scale)):
        return None
    if scale <= 0.0 or abs(det) <= 1e-14 * scale * scale:
        return None
    x0 = (a11 * b0 - a01 * b1) / det
    x1 = (-a01 * b0 + a00 * b1) / det
    if not (math.isfinite(x0) and math.isfinite(x1)):
        return None
    return x0, x1


def _kasa_fit2(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sxy = syy = sxrr = syrr = 0.0
    for x, y in zip(xs, ys, strict=True):
        x -= mx
        y -= my
        rr = x * x + y * y
        sxx += x * x
        sxy += x * y
        syy += y * y
        sxrr += x * rr
        syrr += y * rr
    sol = _solve2x2(sxx, sxy, syy, 0.5 * sxrr, 0.5 * syrr)
    if sol is None:
        return None
    dcx, dcy = sol
    cx = mx + dcx
    cy = my + dcy
    acc = 0.0
    for x, y in zip(xs, ys, strict=True):
        acc += (x - cx) ** 2 + (y - cy) ** 2
    radius = math.sqrt(acc / n)
    if not (math.isfinite(cx) and math.isfinite(cy) and math.isfinite(radius)):
        return None
    if not (radius > 0.0):
        return None
    return cx, cy, radius


def _eberly_center_radius(mv: MeshView, tris: list, axis: np.ndarray):
    ids = sorted(set(tris))
    if not ids:
        return False, np.zeros(3), 0.0
    a = np.asarray(axis, dtype=float)
    am = float(np.linalg.norm(a))
    if am < 1e-15:
        return False, np.zeros(3), 0.0
    a = a / am
    frame = _axis_frame(a)
    if frame is None:
        return False, np.zeros(3), 0.0
    u, v = frame
    gids = sorted({mv.tris[t, k] for t in ids for k in range(3)})
    if len(gids) < 3:
        return False, np.zeros(3), 0.0
    xs, ys = [], []
    mean = np.zeros(3)
    for gi in gids:
        p = mv.pts[gi]
        mean = mean + p
        xs.append(float(np.dot(p, u)))
        ys.append(float(np.dot(p, v)))
    mean = mean / len(gids)
    fit = _kasa_fit2(xs, ys)
    if fit is None:
        return False, np.zeros(3), 0.0
    cx, cy, radius = fit
    c = cx * u + cy * v + (float(np.dot(mean, a)) * a)
    if not (math.isfinite(c[0]) and math.isfinite(c[1]) and math.isfinite(c[2])):
        return False, np.zeros(3), 0.0
    if not (radius > 0.0) or not math.isfinite(radius):
        return False, np.zeros(3), 0.0
    return True, c, radius


def _area_weighted_nbar(mv: MeshView, tris: list) -> np.ndarray:
    A = 0.0
    nbar = np.zeros(3)
    for lt in tris:
        n = tri_normal(mv, lt)
        a = tri_area(mv, lt)
        A += a
        nbar += n * a
    if A < K_TINY:
        return np.zeros(3)
    return nbar / A


def _centered_gauss(
    mv: MeshView, tris: list, seed_axis: np.ndarray, tol: DerivedTols
) -> _GaussResult:
    r = _GaussResult()
    if not tris:
        return r
    A = 0.0
    nbar = np.zeros(3)
    for lt in tris:
        n = tri_normal(mv, lt)
        a = tri_area(mv, lt)
        A += a
        nbar += n * a
    if A < K_TINY:
        return r
    nbar = nbar / A

    C = np.zeros((3, 3))
    for lt in tris:
        n = tri_normal(mv, lt)
        a = tri_area(mv, lt)
        d = n - nbar
        C += a * np.outer(d, d)
    try:
        evals, evecs = np.linalg.eigh(C)
    except np.linalg.LinAlgError:
        return r
    r.mu1 = float(evals[0])
    r.mu2 = float(evals[1])
    r.mu3 = float(evals[2])
    r.flat = r.mu1 / max(r.mu2, 1e-300)
    r.patch = r.mu2 / max(r.mu3, 1e-300)

    L = max(mv.diag, tol.eps_mesh)
    theta = (tol.eps_mesh / L) if L > 0.0 else 0.0
    mu2_floor = A * theta * theta
    few_normals = r.mu2 <= 1e-12 * r.mu3
    mu2_below_noise = r.mu2 <= mu2_floor
    if few_normals or mu2_below_noise:
        r.degenerate = True
        r.axis = _canonical_axis(np.asarray(seed_axis, dtype=float))
        r.c = 0.0
        r.dev = 0.0
        r.flat = 0.0
        r.patch = 0.0
        r.ok = True
        return r

    w1 = evecs[:, 0]
    r.axis = _canonical_axis(w1)
    r.c = float(np.dot(nbar, r.axis))
    r.dev = 0.0
    for lt in tris:
        d = float(np.dot(tri_normal(mv, lt), r.axis))
        r.dev = max(r.dev, abs(d - r.c))
    r.ok = True
    return r


def _axis_tilt_stats(mv: MeshView, tris: list, axis: np.ndarray):
    nbar = _area_weighted_nbar(mv, tris)
    if float(np.dot(nbar, nbar)) <= 0.0 and not tris:
        return 0.0, 0.0
    c_out = float(np.dot(nbar, axis))
    dev_out = 0.0
    for lt in tris:
        d = float(np.dot(tri_normal(mv, lt), axis))
        dev_out = max(dev_out, abs(d - c_out))
    return c_out, dev_out


def _test_t1_running(g: _GaussResult) -> bool:
    return g.ok and g.flat < K_GAUSS_PLANARITY


def _test_g1_commit_seed_axis(
    g: _GaussResult, tol: DerivedTols, c_tilt: float, dev_tilt: float
) -> bool:
    sin3 = tol.gauss_axis_tilt_sin()
    return g.ok and g.flat < K_GAUSS_PLANARITY and dev_tilt < sin3 and abs(c_tilt) < sin3


def _eps_cyl_ring(tol: DerivedTols, R: float) -> float:
    return max(tol.eps_mesh, K_RING_RESIDUAL_FRAC * R)


def _max_vertex_residual(
    mv: MeshView, tris: list, axis: np.ndarray, center: np.ndarray, radius: float
) -> float:
    a = np.asarray(axis, dtype=float)
    c = np.asarray(center, dtype=float)
    max_r = 0.0
    for lt in tris:
        for k in range(3):
            p = tri_corner(mv, lt, k)
            d = p - c
            radial = float(np.linalg.norm(np.cross(a, d)))
            max_r = max(max_r, abs(radial - radius))
    return max_r


def _median_centroid_residual(
    mv: MeshView, tris: list, axis: np.ndarray, center: np.ndarray, radius: float
) -> float:
    a = np.asarray(axis, dtype=float)
    c = np.asarray(center, dtype=float)
    vals = []
    for lt in tris:
        cent = tri_centroid(mv, lt)
        d = cent - c
        vals.append(abs(float(np.linalg.norm(np.cross(a, d))) - radius))
    return _median_of(vals)


def _classify_g1_reject(g: _GaussResult, tol: DerivedTols) -> int:
    sin3 = tol.gauss_axis_tilt_sin()
    c1 = g.flat < K_GAUSS_PLANARITY
    c2 = g.dev < sin3
    if c1 and c2 and abs(g.c) >= sin3:
        return Reject.CONE_NYI
    if not c1 and g.patch >= 0.25:
        return Reject.SPHERE_NYI
    return Reject.GAUSS_PLANARITY


def _chord_sagitta(radius: float, n_sides: int) -> float:
    if n_sides < 1 or not math.isfinite(radius):
        return 0.0
    return radius * (1.0 - math.cos(K_PI / n_sides))


def _compute_d2(
    mv: MeshView,
    tris: list,
    axis_in: np.ndarray,
    center_in: np.ndarray,
    radius_in: float,
    tol: DerivedTols,
) -> _D2Metrics:
    m = _D2Metrics()
    m.center = center_in
    m.radius = radius_in
    aw = np.asarray(axis_in, dtype=float)

    centroid = np.zeros(3)
    total_area = 0.0
    for lt in tris:
        ar = tri_area(mv, lt)
        centroid = centroid + tri_centroid(mv, lt) * ar
        total_area += ar
    if total_area > K_TINY:
        centroid = centroid / total_area

    cxyz = np.asarray(center_in, dtype=float)
    t_loc = float(np.dot(centroid - cxyz, aw))
    loc = cxyz + aw * t_loc

    uniq = []
    for lt in tris:
        for k in range(3):
            lv = mv.tris[lt, k]
            uniq.append((lv, tri_corner(mv, lt, k)))
    uniq.sort(key=lambda x: x[0])
    dedup = []
    last = -1
    for lv, pos in uniq:
        if lv != last:
            dedup.append((lv, pos))
            last = lv

    min_lv = INT_MAX
    ps = np.zeros(3)
    for lv, pos in dedup:
        if lv < min_lv:
            min_lv = lv
            ps = pos
    dps = ps - loc
    ads = float(np.dot(dps, aw))
    x_dir = dps - aw * ads
    if float(np.linalg.norm(x_dir)) < 1e-12:
        tmp = np.array([1.0, 0.0, 0.0]) if abs(aw[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        x_dir = np.cross(aw, tmp)
    xD = _canonical_axis(x_dir)

    m.ax = gp_Ax3(_gp_pnt(loc), _gp_dir(aw), _gp_dir(xD))
    x_ax = _np_dir(m.ax.XDirection())
    y_ax = _np_dir(m.ax.YDirection())

    psi = []
    for lt in tris:
        n = tri_normal(mv, lt)
        pu = float(np.dot(n, x_ax))
        pv = float(np.dot(n, y_ax))
        psi.append(_wrap_to_pi(math.atan2(pv, pu)))
    psi.sort()

    n_bands = 1
    if len(psi) >= 2:
        gaps = [psi[i + 1] - psi[i] for i in range(len(psi) - 1)]
        gaps.append(2.0 * K_PI - psi[-1] + psi[0])
        gap_input = list(gaps)
        if gap_input:
            gap_input.pop(max(range(len(gap_input)), key=lambda i: gap_input[i]))
        theta_bin = max(tol.theta_bin, 0.5 * _percentile75(gap_input))
        n_bands = 1
        for i in range(1, len(psi)):
            if psi[i] - psi[i - 1] > theta_bin:
                n_bands += 1
    m.n_bands = n_bands

    chi = []
    for _, pos in dedup:
        d = pos - loc
        chi.append(_wrap_to_pi(math.atan2(float(np.dot(d, y_ax)), float(np.dot(d, x_ax)))))
    chi.sort()

    if len(chi) < 2:
        m.span_reject = True
        return m

    jmax = 0
    max_gap_v = chi[1] - chi[0]
    for j in range(1, len(chi) - 1):
        g = chi[j + 1] - chi[j]
        if g > max_gap_v:
            max_gap_v = g
            jmax = j
    wrap_gap = 2.0 * K_PI - chi[-1] + chi[0]
    if wrap_gap > max_gap_v:
        max_gap_v = wrap_gap
        jmax = len(chi) - 1

    band_arc = (2.0 * K_PI / n_bands) if n_bands > 0 else 2.0 * K_PI
    m.closed360 = n_bands >= 3 and max_gap_v <= 1.5 * band_arc
    m.span = 2.0 * K_PI if m.closed360 else (2.0 * K_PI - max_gap_v)

    if m.span <= 0 or n_bands < 1:
        m.span_reject = True
    else:
        m.n_sides = _llround(2.0 * K_PI * n_bands / m.span)

    if m.closed360:
        m.u_min = 0.0
        m.u_max = 2.0 * K_PI
    else:
        u_idx = (jmax + 1) % len(chi)
        m.u_min = _wrap_to_pi(chi[u_idx])
        m.u_max = m.u_min + m.span

    m.v_min = math.inf
    m.v_max = -math.inf
    for _, pos in dedup:
        v = float(np.dot(pos - loc, aw))
        m.v_min = min(m.v_min, v)
        m.v_max = max(m.v_max, v)
    return m


def _compute_outward_cylinder(mv: MeshView, tris: list, axis: np.ndarray, loc: np.ndarray) -> bool:
    aw = np.asarray(axis, dtype=float)
    lxyz = np.asarray(loc, dtype=float)
    sigma = 0.0
    for lt in tris:
        a = tri_area(mv, lt)
        cent = tri_centroid(mv, lt)
        d = cent - lxyz
        ad = float(np.dot(d, aw))
        radial = d - aw * ad
        rm = float(np.linalg.norm(radial))
        if rm < K_TINY:
            continue
        radial = radial / rm
        sigma += a * float(np.dot(tri_normal(mv, lt), radial))
    return sigma > 0.0


def _dvol_cylinder_sector(area: float, radius: float, n_sides: int, outward: bool) -> float:
    if n_sides < 3 or not (radius > 0.0) or not math.isfinite(area) or not math.isfinite(radius):
        return 0.0
    gamma = 2.0 * K_PI / n_sides
    if not (gamma < K_PI):
        return 0.0
    s = math.sin(0.5 * gamma)
    if abs(s) < 1e-15:
        return 0.0
    sigma = 1.0 if outward else -1.0
    dvol = sigma * area * radius * (gamma - math.sin(gamma)) / (4.0 * s)
    return dvol if math.isfinite(dvol) else 0.0


def _fill_cylinder_region(mv: MeshView, ev: _CommitEval, axis: np.ndarray, tris: list) -> Region:
    area = 0.0
    for lt in tris:
        area += tri_area(mv, lt)
    reg = Region()
    reg.type = SurfType.CYLINDER
    reg.origin = Origin.CYL_GROW
    reg.tris = list(tris)
    reg.ax = ev.d2.ax
    reg.radius = ev.radius
    reg.closed360 = ev.d2.closed360
    reg.u_min = ev.d2.u_min
    reg.u_max = ev.d2.u_max
    reg.v_min = ev.d2.v_min
    reg.v_max = ev.d2.v_max
    reg.n_sides = ev.d2.n_sides
    reg.chord_sagitta = _chord_sagitta(ev.radius, ev.d2.n_sides)
    reg.outward_normal = _compute_outward_cylinder(mv, tris, axis, _np_pnt(ev.d2.ax.Location()))
    reg.dvol_predicted = _dvol_cylinder_sector(area, ev.radius, ev.d2.n_sides, reg.outward_normal)
    reg.max_vertex_dev = _max_vertex_residual(mv, tris, axis, ev.center, ev.radius)
    a = np.asarray(axis, dtype=float)
    c = np.asarray(ev.center, dtype=float)
    sum_sq = 0.0
    n_v = 0
    for lt in tris:
        for k in range(3):
            p = tri_corner(mv, lt, k)
            rr = float(np.linalg.norm(np.cross(a, p - c)))
            d = rr - ev.radius
            sum_sq += d * d
            n_v += 1
    reg.rms_vertex_dev = math.sqrt(sum_sq / n_v) if n_v > 0 else 0.0
    return reg


def _merge_member_tris(provs: list, members: list) -> list:
    tris = set()
    for m in members:
        tris.update(provs[m].tris)
    return sorted(tris)


def _min_tri_id(p: Provisional) -> int:
    return p.tris[0] if p.tris else INT_MAX


def _seed_pair_axis(P: Provisional, Q: Provisional) -> np.ndarray:
    n_p = _np_dir(P.plane.Direction())
    n_q = _np_dir(Q.plane.Direction())
    cross = np.cross(n_p, n_q)
    if float(np.dot(cross, cross)) <= 1e-18:
        return np.array([0.0, 0.0, 1.0])
    return _canonical_axis(cross)


def _axis_of(mv: MeshView, provs: list, members: list, seed_axis: np.ndarray, tol: DerivedTols):
    tris = _merge_member_tris(provs, members)
    g = _centered_gauss(mv, tris, seed_axis, tol)
    _, sc_seed = _axis_tilt_stats(mv, tris, seed_axis)
    sc_w1 = g.dev if (g.ok and not g.degenerate) else 0.0
    if len(members) <= 3 or g.degenerate or not g.ok:
        return seed_axis, g, False, sc_w1, sc_seed
    if sc_w1 <= sc_seed:
        return g.axis, g, True, sc_w1, sc_seed
    return seed_axis, g, False, sc_w1, sc_seed


def _build_prov_adjacency(mv: MeshView, tri_to_prov: list, n_prov: int) -> list:
    adj = build_edge_adj(mv)
    raw = []
    for e in range(mv.n_edge):
        t0, t1 = adj[e]
        if t0 < 0 or t1 < 0:
            continue
        p0, p1 = tri_to_prov[t0], tri_to_prov[t1]
        if p0 < 0 or p1 < 0 or p0 == p1:
            continue
        lo, hi = (p0, p1) if p0 < p1 else (p1, p0)
        raw.append((lo, hi, edge_dihedral_abs(mv, e, adj)))
    raw.sort(key=lambda x: (x[0], x[1], x[2]))

    prov_adj = [[] for _ in range(n_prov)]
    i = 0
    while i < len(raw):
        lo, hi, _ = raw[i]
        phis = []
        while i < len(raw) and raw[i][0] == lo and raw[i][1] == hi:
            phis.append(raw[i][2])
            i += 1
        phi = _median_of(phis)
        prov_adj[lo].append(_ProvAdj(other=hi, phi=phi, length=len(phis)))
        prov_adj[hi].append(_ProvAdj(other=lo, phi=phi, length=len(phis)))
    for p in range(n_prov):
        prov_adj[p].sort(key=lambda a: a.other)
    return prov_adj


def _phi_to_set(adj: list, x: int, members: list) -> float:
    phis = []
    for m in members:
        for a in adj[x]:
            if a.other == m:
                phis.append(a.phi)
    return _median_of(phis)


def _shared_len(adj: list, x: int, members: list) -> int:
    total = 0
    for m in members:
        for a in adj[x]:
            if a.other == m:
                total += a.length
    return total


def _adjacent_to_set(adj: list, x: int, members: list) -> bool:
    for m in members:
        for a in adj[x]:
            if a.other == m:
                return True
    return False


def _seed_in_band(phi: float, tol: DerivedTols) -> bool:
    lo_eps = _angle_band_eps(tol.theta_cyl_lo)
    hi_eps = _angle_band_eps(tol.theta_cyl_hi)
    return phi >= tol.theta_cyl_lo - lo_eps and phi <= tol.theta_cyl_hi + hi_eps


def _members_edge_connected(adj: list, members: list) -> bool:
    if len(members) <= 1:
        return True
    n = len(adj)
    in_s = [False] * n
    for m in members:
        if 0 <= m < n:
            in_s[m] = True
    seen = [False] * n
    q = [members[0]]
    seen[members[0]] = True
    n_seen = 1
    i = 0
    while i < len(q):
        for a in adj[q[i]]:
            if 0 <= a.other < n and in_s[a.other] and not seen[a.other]:
                seen[a.other] = True
                q.append(a.other)
                n_seen += 1
        i += 1
    return n_seen == len(members)


def _pratt_fit2(xs, ys):
    """Pratt algebraic circle fit (refit_math.cpp prattFit2).

    Kasa biases the radius low on a short arc, which is exactly the case here: a
    tessellated band covering a fraction of a turn. Pratt's constraint removes that
    bias, so the reference uses it for the ring re-fit while keeping Kasa for the
    bulk Eberly solve.
    """
    n = len(xs)
    if n < 3:
        return None
    inv = 1.0 / n
    mx = sum(xs) * inv
    my = sum(ys) * inv
    mxx = myy = mxy = mxz = myz = mzz = 0.0
    for x, y in zip(xs, ys, strict=True):
        xi = x - mx
        yi = y - my
        zi = xi * xi + yi * yi
        mxx += xi * xi
        myy += yi * yi
        mxy += xi * yi
        mxz += xi * zi
        myz += yi * zi
        mzz += zi * zi
    mxx *= inv
    myy *= inv
    mxy *= inv
    mxz *= inv
    myz *= inv
    mzz *= inv

    mz = mxx + myy
    cov_xy = mxx * myy - mxy * mxy
    mxz2 = mxz * mxz
    myz2 = myz * myz
    a2 = 4.0 * cov_xy - 3.0 * mz * mz - mzz
    a1 = mzz * mz + 4.0 * cov_xy * mz - mxz2 - myz2 - mz * mz * mz
    a0 = mxz2 * myy + myz2 * mxx - mzz * cov_xy - 2.0 * mxz * myz * mxy + mz * mz * cov_xy
    a22 = a2 + a2

    xnew = 0.0
    ynew = 1.0e20
    for _ in range(K_PRATT_NEWTON_CAP):
        yold = ynew
        ynew = a0 + xnew * (a1 + xnew * (a2 + 4.0 * xnew * xnew))
        if not math.isfinite(ynew) or abs(ynew) > abs(yold):
            xnew = 0.0
            break
        dy = a1 + xnew * (a22 + 16.0 * xnew * xnew)
        if dy == 0.0 or not math.isfinite(dy):
            xnew = 0.0
            break
        xold = xnew
        xnew = xold - ynew / dy
        if not math.isfinite(xnew) or xnew < 0.0:
            xnew = 0.0
            break
        if abs(xnew) > 1e-15 and abs((xnew - xold) / xnew) < 1e-12:
            break
        if abs(xnew - xold) < 1e-15:
            break

    det = xnew * xnew - xnew * mz + cov_xy
    if not math.isfinite(det) or abs(det) <= 1e-16 * (1.0 + abs(mz) + abs(cov_xy)):
        return None
    xc = (mxz * (myy - xnew) - myz * mxy) / det / 2.0
    yc = (myz * (mxx - xnew) - mxz * mxy) / det / 2.0
    r2 = xc * xc + yc * yc + mz + 2.0 * xnew
    if not (math.isfinite(xc) and math.isfinite(yc) and math.isfinite(r2)) or r2 <= 0.0:
        return None
    cx = mx + xc
    cy = my + yc
    radius = math.sqrt(r2)
    if not (math.isfinite(cx) and math.isfinite(cy) and math.isfinite(radius)):
        return None
    if not (radius > 0.0):
        return None
    return cx, cy, radius


def _radius_from_chord_length(chord_len: float, n_sides: int) -> float:
    if n_sides < 3 or not (chord_len > 0.0) or not math.isfinite(chord_len):
        return 0.0
    s = math.sin(K_PI / n_sides)
    if s <= 1e-15:
        return 0.0
    r = chord_len / (2.0 * s)
    return r if (math.isfinite(r) and r > 0.0) else 0.0


def _circumradius_from_inscribed(r_inscribed: float, n_sides: int) -> float:
    if n_sides < 3 or not (r_inscribed > 0.0) or not math.isfinite(r_inscribed):
        return 0.0
    c = math.cos(K_PI / n_sides)
    if c <= 1e-15:
        return 0.0
    r = r_inscribed / c
    return r if (math.isfinite(r) and r > 0.0) else 0.0


def _shared_edge_pairs(mv: MeshView, ids: list):
    """Yield (t, u, edge_id) for every pair of triangles in `ids` sharing an edge.

    The reference compares corner pairs in an O(n^2 * 9) scan; sharing an undirected
    edge is the same predicate as sharing an entry in `tri_edges`, since comp_edges
    is keyed on (vLo, vHi). Same answer, without the quadratic corner comparison.
    """
    owner: dict[int, list] = {}
    for t in ids:
        for k in range(3):
            owner.setdefault(int(mv.tri_edges[t, k]), []).append(t)
    for e, ts in owner.items():
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                yield ts[i], ts[j], e


def _estimate_full_circle_sides(mv: MeshView, tris: list) -> int:
    """Turns per full circle implied by the median dihedral angle across the patch
    (refit_math.cpp estimateFullCircleSides). A tessellated cylinder bends by a
    constant angle per facet, so 2*pi over that angle recovers the generating
    polygon even when only a few degrees of arc are present."""
    ids = sorted(set(tris))
    if not ids:
        return 0
    phis = []
    for t, u, _e in _shared_edge_pairs(mv, ids):
        n0 = tri_normal(mv, t)
        n1 = tri_normal(mv, u)
        m0 = float(np.linalg.norm(n0))
        m1 = float(np.linalg.norm(n1))
        if m0 < 1e-15 or m1 < 1e-15:
            continue
        dot = float(np.dot(n0 / m0, n1 / m1))
        phi = math.acos(max(-1.0, min(1.0, dot)))
        if 0.05 < phi < K_PI - 0.05:
            phis.append(phi)
    if not phis:
        return 0
    med = _median_of(phis)
    if med < 1e-6:
        return 0
    return max(3, _llround(2.0 * K_PI / med))


def _ring_chord_radii(mv, ids, c0, aw, u, v, r_lo, r_hi, only_boundary=False):
    """Radii implied by facet chords: R = chord / (2 sin(dtheta/2)).

    This is the tessellation law read backwards. `only_boundary` selects the
    partial-arc pass, where the circumferential edges are patch boundaries rather
    than interior ones.
    """
    out = []
    idset = set(ids)
    interior = set()
    for t, uT, e in _shared_edge_pairs(mv, ids):
        if t in idset and uT in idset:
            interior.add(e)
    for t in ids:
        for k in range(3):
            e = int(mv.tri_edges[t, k])
            if only_boundary and e in interior:
                continue
            if not only_boundary and e not in interior:
                continue
            gv0, gv1 = mv.comp_edges[e]
            p0 = mv.pts[gv0]
            p1 = mv.pts[gv1]
            chord = float(np.linalg.norm(p1 - p0))
            if not (chord > 0.0):
                continue
            d0 = p0 - c0
            d1 = p1 - c0
            r0 = d0 - aw * float(np.dot(d0, aw))
            r1 = d1 - aw * float(np.dot(d1, aw))
            rad0 = float(np.linalg.norm(r0))
            rad1 = float(np.linalg.norm(r1))
            if not (rad0 > 0.0) or not (rad1 > 0.0):
                continue
            ang0 = math.atan2(float(np.dot(r0, v)), float(np.dot(r0, u)))
            ang1 = math.atan2(float(np.dot(r1, v)), float(np.dot(r1, u)))
            d_ang = abs(ang1 - ang0)
            if d_ang > K_PI:
                d_ang = 2.0 * K_PI - d_ang
            # Skip axial seams (dtheta ~ 0) and near-diameter spans.
            if d_ang < 0.09 or d_ang >= K_PI - 0.09:
                continue
            if not only_boundary and abs(rad0 - rad1) > 0.05 * max(rad0, rad1):
                continue
            s = math.sin(0.5 * d_ang)
            if s <= 1e-9:
                continue
            r_chord = chord / (2.0 * s)
            if r_lo < r_chord < r_hi:
                out.append(r_chord)
    return out


def _refine_cylinder_radius(
    mv: MeshView, tris: list, axis, center, radius, n_sides, span, r_hint
):
    """Coarse-band radius refinement (refit_math.cpp refineCylinderRadius).

    Returns ``(ok, center, radius)`` — Python cannot mutate the caller's floats the
    way the C++ reference mutates its reference parameters.

    Why it exists: on a coarsely tessellated bore the bulk Eberly fit is dragged
    below the true radius by the axial extent of the patch, while the facet chords
    around the circumference still carry the right answer through the tessellation
    law. This re-reads the radius from those chords and lifts the fit, under a cap.
    """
    c0 = np.asarray(center, dtype=float)
    if not (radius > 0.0) or not math.isfinite(radius) or n_sides < 3:
        return False, c0, radius
    if mv.n_tri < 500 or mv.n_tri > 1200:
        return False, c0, radius

    ids = sorted(set(tris))
    if len(ids) < 2:
        return False, c0, radius

    aw = np.asarray(axis, dtype=float)
    am = float(np.linalg.norm(aw))
    if am < 1e-15:
        return False, c0, radius
    aw = aw / am
    frame = _axis_frame(aw)
    if frame is None:
        return False, c0, radius
    u, v = frame
    r_eberly = radius

    gids = sorted({int(mv.tris[t, k]) for t in ids for k in range(3)})
    ring = []
    for gi in gids:
        p = mv.pts[gi]
        d = p - c0
        radial = d - aw * float(np.dot(d, aw))
        rr = float(np.linalg.norm(radial))
        if not (rr > 0.0):
            continue
        ang = math.atan2(float(np.dot(radial, v)), float(np.dot(radial, u)))
        ring.append((ang, rr, p))
    if len(ring) < 3:
        return False, c0, radius
    ring.sort(key=lambda e: e[0])

    n_dihedral = _estimate_full_circle_sides(mv, ids)
    n_eff = n_dihedral if n_dihedral > 0 else n_sides
    n_eff = max(4, min(48, n_eff))

    # Growth R_ref from an early circumferential band can exceed the axial-dragged
    # Eberly fit; widen chord acceptance toward r_hint when present.
    r_anchor = r_hint if r_hint > radius * 1.02 else radius
    r_chord_lo = min(radius * 0.90, r_anchor * 0.88)
    r_chord_hi = max(radius * 1.42, r_anchor * 1.08)

    n_v = len(ring)
    skip_edge = n_v
    max_gap = -1.0
    for i in range(n_v):
        j = (i + 1) % n_v
        gap = (ring[0][0] + 2.0 * K_PI) - ring[n_v - 1][0] if j == 0 else ring[j][0] - ring[i][0]
        if gap > max_gap:
            max_gap = gap
            skip_edge = i

    chord_radii = _ring_chord_radii(mv, ids, c0, aw, u, v, r_chord_lo, r_chord_hi)

    # Fallback: angularly consecutive vertices when no internal mesh chords found.
    if not chord_radii:
        for i in range(n_v):
            if i == skip_edge:
                continue
            j = (i + 1) % n_v
            d_ang = (
                (ring[0][0] + 2.0 * K_PI) - ring[n_v - 1][0] if j == 0
                else ring[j][0] - ring[i][0]
            )
            if d_ang < 1e-6 or d_ang >= K_PI:
                continue
            chord = float(np.linalg.norm(ring[j][2] - ring[i][2]))
            if not (chord > 0.0):
                continue
            s = math.sin(0.5 * d_ang)
            if s <= 1e-9:
                continue
            r_chord = chord / (2.0 * s)
            if r_chord_lo < r_chord < r_chord_hi:
                chord_radii.append(r_chord)

    # Partial arcs: circumferential edges are often patch boundaries (thin axial bands).
    if not chord_radii and 0.05 < span < 2.8:
        chord_radii = _ring_chord_radii(
            mv, ids, c0, aw, u, v, r_chord_lo, r_chord_hi, only_boundary=True
        )

    r_inscribed = _circumradius_from_inscribed(radius, n_eff)
    r_pick = radius
    if chord_radii:
        r_chord_med = _median_of(chord_radii)
        if r_chord_med > radius:
            r_pick = r_chord_med
    if r_inscribed > r_pick * 1.003 and r_inscribed <= radius * 1.20 and n_eff <= 12:
        r_pick = max(r_pick, r_inscribed)
    # Axially-grown large-bore patch: bulk Eberly drags below the circumferential band.
    if r_hint > radius * 1.08 and r_hint <= radius * 1.38 and radius >= 11.0:
        chords_low = (not chord_radii) or _median_of(chord_radii) < radius * 1.05
        if chords_low:
            r_pick = max(r_pick, r_hint)

    if r_pick <= radius * 1.01:
        return True, c0, radius

    cap = radius * 1.25
    if r_hint > radius * 1.02:
        cap = max(cap, r_hint * 1.03)
    if chord_radii:
        r_chord_med = _median_of(chord_radii)
        cap = max(cap, max(r_pick * 1.02, r_chord_med * 1.02))
    radius = min(r_pick, cap)

    # After an r_hint lift, snap back to tight circumferential chords on the patch.
    if r_hint > r_eberly * 1.08 and radius > r_eberly * 1.05:
        snap = _all_chord_radii(mv, ids, c0, aw, u, v, radius * 0.92, radius * 1.06)
        if snap:
            med = _median_of(snap)
            if med > r_eberly * 1.02 and med < radius:
                radius = med
        elif n_eff >= 4:
            max_chord = _max_circumferential_chord(mv, ids, c0, aw, u, v)
            r_nom = _radius_from_chord_length(max_chord, n_eff)
            if r_nom > r_eberly * 1.02 and r_nom < radius:
                radius = r_nom

    xs = [float(np.dot(p - c0, u)) for _a, _r, p in ring]
    ys = [float(np.dot(p - c0, v)) for _a, _r, p in ring]
    fit = _pratt_fit2(xs, ys)
    if fit is not None:
        cx, cy, r2 = fit
        c_new = c0 + cx * u + cy * v
        if all(math.isfinite(x) for x in c_new) and r2 > 0.0:
            c0 = c_new
            if radius * 0.97 < r2 < radius * 1.06:
                radius = 0.5 * (radius + r2)
            elif r_hint > r_eberly * 1.08 and r2 > r_eberly * 1.02:
                radius = r2
    return (math.isfinite(radius) and radius > 0.0), c0, radius


def _all_chord_radii(mv, ids, c0, aw, u, v, r_lo, r_hi):
    """Every facet chord on the patch, interior or boundary, inside [r_lo, r_hi]."""
    out = []
    for t in ids:
        for k in range(3):
            gv0 = int(mv.tris[t, k])
            gv1 = int(mv.tris[t, (k + 1) % 3])
            p0 = mv.pts[gv0]
            p1 = mv.pts[gv1]
            chord = float(np.linalg.norm(p1 - p0))
            if not (chord > 0.0):
                continue
            d0 = p0 - c0
            d1 = p1 - c0
            r0 = d0 - aw * float(np.dot(d0, aw))
            r1 = d1 - aw * float(np.dot(d1, aw))
            if not (float(np.linalg.norm(r0)) > 0.0) or not (float(np.linalg.norm(r1)) > 0.0):
                continue
            ang0 = math.atan2(float(np.dot(r0, v)), float(np.dot(r0, u)))
            ang1 = math.atan2(float(np.dot(r1, v)), float(np.dot(r1, u)))
            d_ang = abs(ang1 - ang0)
            if d_ang > K_PI:
                d_ang = 2.0 * K_PI - d_ang
            if d_ang < 0.09 or d_ang >= K_PI - 0.09:
                continue
            s = math.sin(0.5 * d_ang)
            if s <= 1e-9:
                continue
            r_chord = chord / (2.0 * s)
            if r_lo < r_chord < r_hi:
                out.append(r_chord)
    return out


def _max_circumferential_chord(mv, ids, c0, aw, u, v) -> float:
    best = 0.0
    for t in ids:
        for k in range(3):
            gv0 = int(mv.tris[t, k])
            gv1 = int(mv.tris[t, (k + 1) % 3])
            p0 = mv.pts[gv0]
            p1 = mv.pts[gv1]
            chord = float(np.linalg.norm(p1 - p0))
            if not (chord > 0.0):
                continue
            d0 = p0 - c0
            d1 = p1 - c0
            r0 = d0 - aw * float(np.dot(d0, aw))
            r1 = d1 - aw * float(np.dot(d1, aw))
            if not (float(np.linalg.norm(r0)) > 0.0) or not (float(np.linalg.norm(r1)) > 0.0):
                continue
            ang0 = math.atan2(float(np.dot(r0, v)), float(np.dot(r0, u)))
            ang1 = math.atan2(float(np.dot(r1, v)), float(np.dot(r1, u)))
            d_ang = abs(ang1 - ang0)
            if d_ang > K_PI:
                d_ang = 2.0 * K_PI - d_ang
            if d_ang < 0.09 or d_ang >= K_PI - 0.09:
                continue
            best = max(best, chord)
    return best


def _arch_chain_radius_from_patch(
    mv: MeshView, tris: list, axis, radius, chain_score, r_hint
) -> bool:
    # ponytail: arch-chain band only (n_tri >= 500); no in-scope fixture lands here.
    return False


def _evaluate_commit(
    mv: MeshView,
    tol: DerivedTols,
    tris: list,
    axis: np.ndarray,
    r_hint: float = 0.0,
    law_band: bool = False,
) -> _CommitEval:
    ev = _CommitEval()
    ev.g = _centered_gauss(mv, tris, axis, tol)
    c_tilt, dev_tilt = _axis_tilt_stats(mv, tris, axis)
    if not law_band:
        ok, center, radius = _eberly_center_radius(mv, tris, axis)
        ev.eberly_ok = ok
        if ok:
            ev.center = center
            ev.radius = radius
    ev.fail_gate = Gate.PASS
    if not _test_g1_commit_seed_axis(ev.g, tol, c_tilt, dev_tilt):
        ev.fail_gate = Gate.G1
        return ev
    if not law_band and not ev.eberly_ok:
        ev.fail_gate = Gate.G4
        return ev
    ev.d2 = _compute_d2(mv, tris, axis, ev.center, ev.radius, tol)
    r_before_refine = ev.radius
    arch_chain_applied = False
    coarse = coarse_fusion_band(mv)
    if not law_band and coarse and ev.d2.n_sides >= 3 and not ev.d2.span_reject:
        # refit_grow.cpp:834 ignores the return value and recomputes d2 either way:
        # the centre may have moved even when the radius did not.
        _ok, ev.center, ev.radius = _refine_cylinder_radius(
            mv, tris, axis, ev.center, ev.radius, ev.d2.n_sides, ev.d2.span, r_hint
        )
        ev.d2 = _compute_d2(mv, tris, axis, ev.center, ev.radius, tol)
    if ev.d2.span_reject:
        ev.fail_gate = Gate.G1
        return ev
    lift = max(0.0, ev.radius - r_before_refine)
    if coarse:
        g2_tol = tol.eps_cyl_accept(ev.radius)
        n_est_sides = max(ev.d2.n_sides, max(6, len(tris)))
        g2_tol = max(g2_tol, _chord_sagitta(ev.radius, n_est_sides))
        if lift > 0.0:
            g2_tol = max(g2_tol, lift * 1.15 + _chord_sagitta(ev.radius, n_est_sides))
        if len(tris) <= 8:
            g2_tol = max(g2_tol, _eps_cyl_ring(tol, ev.radius))
        if not arch_chain_applied and _max_vertex_residual(
            mv, tris, axis, ev.center, ev.radius
        ) > g2_tol:
            ev.fail_gate = Gate.G2
            return ev
    elif _max_vertex_residual(mv, tris, axis, ev.center, ev.radius) > tol.eps_cyl_accept(ev.radius):
        ev.fail_gate = Gate.G2
        return ev
    delta = _chord_sagitta(ev.radius, ev.d2.n_sides)
    if delta > tol.eps_mesh and (
        not coarse or (ev.d2.span >= 0.35 and lift <= 0.0 and not arch_chain_applied)
    ):
        s = _median_centroid_residual(mv, tris, axis, ev.center, ev.radius)
        if s < K_G3_LO * delta or s > K_G3_HI * delta:
            ev.fail_gate = Gate.G3
    if ev.fail_gate == Gate.PASS and not (2.0 * tol.eps_plane < ev.radius < 2.0 * mv.diag):
        ev.fail_gate = Gate.G4
    if ev.fail_gate == Gate.PASS:
        span_deg = ev.d2.span * 180.0 / K_PI
        n_bands_use = ev.d2.n_bands
        g5_closed = span_deg >= K_G5_SPAN_CLOSED_DEG and ev.d2.n_sides >= K_G5_NSIDES_MIN
        g5_partial_deg = 30.0 if coarse else K_G5_SPAN_PARTIAL_DEG
        g5_partial = span_deg >= g5_partial_deg and n_bands_use >= K_G5_NBANDS_MIN
        g5_micro = (
            coarse
            and ev.radius >= 5.0
            and len(tris) <= 8
            and span_deg >= 12.0
            and n_bands_use >= 2
        )
        if not (g5_closed or g5_partial or g5_micro) and not arch_chain_applied:
            ev.fail_gate = Gate.G5
    return ev


@dataclass
class _LawStrip:
    tris: list = field(default_factory=list)
    min_tri: int = 0
    chart_id: int = -1


def _cluster_law_strips(mv, ids, chart_id, out, n_cos=K_LAW_STRIP_NORMAL_COS, seed_only=False):
    """Flood adjacent triangles whose normals stay parallel: one strip per generator
    band (refit_grow.cpp:1166). `seed_only` gates against the seed normal instead of
    the running mean, which keeps the leftover pass from drifting around a curve."""
    if not ids:
        return
    in_patch = [False] * mv.n_tri
    for t in ids:
        if 0 <= t < mv.n_tri:
            in_patch[t] = True
    used = [False] * mv.n_tri
    adj = build_edge_adj(mv)
    for seed in ids:
        if seed < 0 or seed >= mv.n_tri or used[seed]:
            continue
        n_seed = tri_normal(mv, seed)
        n_ref = np.array(n_seed, dtype=float)
        used[seed] = True
        comp = [seed]
        stack = [seed]
        while stack:
            t = stack.pop()
            for s in range(3):
                e = int(mv.tri_edges[t, s])
                t0, t1 = adj[e]
                u = t1 if t0 == t else t0
                if u < 0 or not in_patch[u] or used[u]:
                    continue
                n_u = tri_normal(mv, u)
                n_gate = n_seed if seed_only else n_ref
                if abs(float(np.dot(n_gate, n_u))) < n_cos:
                    continue
                used[u] = True
                comp.append(u)
                stack.append(u)
                if not seed_only:
                    n_ref = n_ref + n_u
                    nm = float(np.linalg.norm(n_ref))
                    if nm > 1e-15:
                        n_ref = n_ref / nm
        comp.sort()
        out.append(_LawStrip(tris=comp, min_tri=comp[0], chart_id=chart_id))


def _bands_share_any_edge(mv: MeshView, a, b, adj) -> bool:
    in_b = [False] * mv.n_tri
    for t in b.tris:
        if 0 <= t < mv.n_tri:
            in_b[t] = True
    for t in a.tris:
        if t < 0 or t >= mv.n_tri:
            continue
        for s in range(3):
            e = int(mv.tri_edges[t, s])
            t0, t1 = adj[e]
            u = t1 if t0 == t else t0
            if u >= 0 and in_b[u]:
                return True
    return False


def _peel_law_band_from_provisionals(mv: MeshView, claimed: list, work: _SegmentWork) -> None:
    """Remove claimed triangles from the A2 provisionals and re-fit what is left.

    This is what stops a claimed arc from also being committed as a plane: the
    provisional that used to own those facets shrinks, and if nothing is left it is
    marked consumed.
    """
    taken = [False] * mv.n_tri
    for t in claimed:
        if 0 <= t < mv.n_tri:
            taken[t] = True
    for p in work.provisionals:
        if not p.tris:
            continue
        keep = [t for t in p.tris if not (0 <= t < mv.n_tri and taken[t])]
        if len(keep) == len(p.tris):
            continue
        p.tris = keep
        if not p.tris:
            p.area = 0.0
            p.claim = ProvClaim.CONSUMED_CYLINDER
            continue
        fit = pca_plane(mv, p.tris)
        if fit is not None:
            p.plane = fit
        p.area = sum(tri_area(mv, t) for t in p.tris)
        compute_prov_deviations(mv, p)


def _fill_law_band_region(mv: MeshView, tol: DerivedTols, band) -> Region:
    axis = band.axis_dir
    center = band.axis_loc
    ev = _CommitEval()
    ev.fail_gate = Gate.PASS
    ev.eberly_ok = True
    ev.center = center
    ev.radius = band.radius
    ev.d2 = _compute_d2(mv, band.tris, axis, center, band.radius, tol)
    if band.closed360:
        ev.d2.closed360 = True
        ev.d2.u_min = 0.0
        ev.d2.u_max = 2.0 * K_PI
        ev.d2.span = 2.0 * K_PI
    reg = _fill_cylinder_region(mv, ev, axis, band.tris)
    reg.law_band = True
    reg.radius = band.radius
    reg.closed360 = band.closed360 or reg.closed360
    return reg


def _claim_law_bands_l(mv: MeshView, tol: DerivedTols, work: _SegmentWork) -> bool:
    """Stage L (refit_grow.cpp:2057). Runs BEFORE B1 and A3.

    Arc bands must be claimed before plane growing gets to commit them, because a
    coarsely tessellated arc looks exactly like a fan of near-coplanar facets and
    plane growth will take it.
    """
    if not law_band_applicable(mv) or mv.n_tri == 0:
        return True

    n_charts = work.n_charts if work.n_charts > 0 else 1
    per_chart = [[] for _ in range(n_charts)]
    for t in range(mv.n_tri):
        c = work.tri_chart[t] if t < len(work.tri_chart) else 0
        if c < 0 or c >= n_charts:
            c = 0
        per_chart[c].append(t)

    strips: list = []
    for c in range(n_charts):
        if per_chart[c]:
            _cluster_law_strips(mv, per_chart[c], c, strips)

    adj_e = build_edge_adj(mv)
    n_s = len(strips)
    adj = [set() for _ in range(n_s)]
    tri_strip = [-1] * mv.n_tri
    for i, st in enumerate(strips):
        for t in st.tris:
            if 0 <= t < mv.n_tri:
                tri_strip[t] = i
    for e in range(mv.n_edge):
        t0, t1 = adj_e[e]
        if t0 < 0 or t1 < 0:
            continue
        a, b = tri_strip[t0], tri_strip[t1]
        if a < 0 or b < 0 or a == b:
            continue
        if strips[a].chart_id != strips[b].chart_id:
            continue
        adj[a].add(b)
        adj[b].add(a)
    adj = [sorted(s) for s in adj]

    def union_strip_tris(members):
        ts = set()
        for m in members:
            ts.update(strips[m].tris)
        return sorted(ts)

    # A single facet cannot recover an axis (its shared edge is the diagonal), so
    # seeds are connected TRIPLES, which carry enough generators.
    triples = set()
    for a in range(n_s):
        for b in adj[a]:
            for c in adj[b]:
                if c == a:
                    continue
                t = tuple(sorted((a, b, c)))
                if t[0] != t[1] and t[1] != t[2]:
                    triples.add(t)
        for j in adj[a]:
            if j <= a:
                continue
            for k in adj[a]:
                if k > j:
                    triples.add((a, j, k))

    grown = []
    for trip in sorted(triples):
        members = list(trip)
        seed_b = law_chain_accept(mv, union_strip_tris(members), tol.eps_mesh)
        if seed_b is None:
            continue
        in_set = set(members)
        changed = True
        while changed:
            changed = False
            cand = sorted(
                {nb for m in members for nb in adj[m] if nb not in in_set},
                key=lambda x: strips[x].min_tri,
            )
            for nb in cand:
                tb = law_chain_accept(mv, union_strip_tris([*members, nb]), tol.eps_mesh)
                if tb is None:
                    continue
                members.append(nb)
                in_set.add(nb)
                seed_b = tb
                changed = True
                break
        grown.append(seed_b)

    # A2 provisionals that already isolate a band on their own.
    for p in work.provisionals:
        if p.claim != ProvClaim.UNCLAIMED or len(p.tris) < 3:
            continue
        pb = law_chain_accept(mv, p.tris, tol.eps_mesh)
        if pb is not None:
            grown.append(pb)

    order = sorted(
        range(len(grown)),
        key=lambda i: (-grown[i].n, -len(grown[i].tris), grown[i].tris[0] if grown[i].tris else 0),
    )
    taken = [False] * mv.n_tri
    accepted = []
    for oi in order:
        b = grown[oi]
        if any(0 <= t < mv.n_tri and taken[t] for t in b.tris):
            continue
        accepted.append(b)
        for t in b.tris:
            if 0 <= t < mv.n_tri:
                taken[t] = True

    # Merge neighbouring bands that are coaxial, same-radius and still equal-theta.
    merged = True
    while merged:
        merged = False
        for i in range(len(accepted)):
            for j in range(i + 1, len(accepted)):
                if not _bands_share_any_edge(mv, accepted[i], accepted[j], adj_e):
                    continue
                if not law_bands_mergeable(accepted[i], accepted[j], mv, tol.eps_mesh):
                    continue
                mt = sorted(set(accepted[i].tris) | set(accepted[j].tris))
                nb = law_chain_accept(mv, mt, tol.eps_mesh)
                if nb is None:
                    continue
                accepted[i] = nb
                accepted.pop(j)
                merged = True
                break
            if merged:
                break

    li = law_calibrate(accepted)
    if li.empty:
        return True
    # A single-preset lock needs several d-limited chains; fewer than five means a
    # foreign or partial component, and a d-window wider than 5% means the component
    # mixes exports. Either way the stage declines wholesale rather than guessing.
    if li.n_d_limited < 5:
        return True
    if li.d_hi > li.d_lo:
        mid = 0.5 * (li.d_lo + li.d_hi)
        if mid > 0.0 and (li.d_hi - li.d_lo) / mid >= 0.05:
            return True

    for b in accepted:
        if len(b.tris) < 3 or not b.radius > 0.0 or b.n < 2:
            continue
        work.accepted.append(_fill_law_band_region(mv, tol, b))
        _peel_law_band_from_provisionals(mv, b.tris, work)
    work.accepted.sort(key=lambda r: r.tris[0] if r.tris else INT_MAX)
    return True


def _claim_cylinders_b1(mv: MeshView, tol: DerivedTols, work: _SegmentWork) -> bool:
    for p in work.provisionals:
        if not p.tris:
            p.claim = ProvClaim.CONSUMED_CYLINDER
    if not work.provisionals:
        return True

    tri_to_prov = [-1] * mv.n_tri
    for pi, prov in enumerate(work.provisionals):
        for t in prov.tris:
            tri_to_prov[t] = pi

    prov_adj = _build_prov_adjacency(mv, tri_to_prov, len(work.provisionals))
    lateral_sin = math.sin(tol.theta_sharp)

    seeds = []
    for i in range(len(work.provisionals)):
        for a in prov_adj[i]:
            j = a.other
            if j <= i:
                continue
            if not _seed_in_band(a.phi, tol):
                continue
            P, Q = work.provisionals[i], work.provisionals[j]
            if P.seed_tried or Q.seed_tried:
                continue
            if P.claim != ProvClaim.UNCLAIMED or Q.claim != ProvClaim.UNCLAIMED:
                continue
            mt_p, mt_q = _min_tri_id(P), _min_tri_id(Q)
            seeds.append(
                _Seed(
                    i,
                    j,
                    -(P.area + Q.area),
                    min(mt_p, mt_q),
                    max(mt_p, mt_q),
                    min(i, j),
                    max(i, j),
                )
            )
    seeds.sort(
        key=lambda s: (s.neg_area_sum, s.min_tri, s.max_tri, s.adj_lo, s.adj_hi)
    )

    for seed in seeds:
        P = work.provisionals[seed.p]
        Q = work.provisionals[seed.q]
        if P.claim != ProvClaim.UNCLAIMED or Q.claim != ProvClaim.UNCLAIMED:
            continue
        if P.seed_tried or Q.seed_tried:
            continue

        seed_axis = _seed_pair_axis(P, Q)
        members = [seed.p, seed.q]
        in_claim = [False] * len(work.provisionals)
        dead = [False] * len(work.provisionals)
        in_claim[seed.p] = True
        in_claim[seed.q] = True
        P.claim = ProvClaim.IN_CYLINDER_CLAIM
        Q.claim = ProvClaim.IN_CYLINDER_CLAIM

        r_ref = 0.0
        have_rref = False
        dead_cleared = False

        while True:
            aS, _, used_w1, _, _ = _axis_of(
                mv, work.provisionals, members, seed_axis, tol
            )
            if not dead_cleared and used_w1:
                dead = [False] * len(work.provisionals)
                dead_cleared = True
            s_tris_now = _merge_member_tris(work.provisionals, members)
            cS, _ = _axis_tilt_stats(mv, s_tris_now, aS)
            sin3 = tol.gauss_axis_tilt_sin()
            mem_areas = [work.provisionals[m].area for m in members]
            med_area = _median_of(mem_areas)

            cands = []
            for xi in range(len(work.provisionals)):
                if in_claim[xi] or dead[xi]:
                    continue
                X = work.provisionals[xi]
                if X.claim != ProvClaim.UNCLAIMED:
                    continue
                if not _adjacent_to_set(prov_adj, xi, members):
                    continue
                phi = _phi_to_set(prov_adj, xi, members)
                if phi < tol.theta_cyl_lo - _angle_band_eps(tol.theta_cyl_lo):
                    continue
                nX = _np_dir(X.plane.Direction())
                if abs(float(np.dot(nX, aS))) > lateral_sin:
                    continue
                if med_area > 0.0 and X.area * K_GAUSS_PLANARITY > med_area:
                    continue
                nXbar = _area_weighted_nbar(mv, X.tris)
                g5_bound = sin3 + _angle_band_eps(sin3)
                g5v = abs(float(np.dot(nXbar, aS)) - cS)
                if g5v > g5_bound:
                    dead[xi] = True
                    continue
                cands.append(_GrowCand(xi, -_shared_len(prov_adj, xi, members), _min_tri_id(X)))
            if not cands:
                break
            cands.sort(key=lambda g: (g.neg_len, g.min_tri))

            progressed = False
            for gc in cands:
                xi = gc.x
                trial_members = [*members, xi]
                U = _merge_member_tris(work.provisionals, trial_members)
                aU, gU, _, _, _ = _axis_of(mv, work.provisionals, trial_members, seed_axis, tol)
                if not _test_t1_running(gU):
                    dead[xi] = True
                    continue
                ok, center, radius = _eberly_center_radius(mv, U, aU)
                if not ok or not (radius > 0.0 and radius < 2.0 * mv.diag):
                    dead[xi] = True
                    continue
                t3R = r_ref if have_rref else radius
                res_u = _max_vertex_residual(mv, U, aU, center, radius)
                if res_u > _eps_cyl_ring(tol, t3R):
                    dead[xi] = True
                    continue
                if have_rref and abs(radius - r_ref) > K_RING_RESIDUAL_FRAC * r_ref:
                    dead[xi] = True
                    continue
                members.append(xi)
                in_claim[xi] = True
                work.provisionals[xi].claim = ProvClaim.IN_CYLINDER_CLAIM
                if not have_rref and len(members) == 3:
                    r_ref = radius
                    have_rref = True
                elif have_rref and radius > r_ref:
                    r_ref = radius
                progressed = True
                break
            if not progressed:
                break

        pre_peel_tris = _merge_member_tris(work.provisionals, members)
        axis_final, _, _, _, _ = _axis_of(
            mv, work.provisionals, members, seed_axis, tol
        )
        grow_hint = r_ref if (have_rref and r_ref > 0.0) else 0.0
        ev = _evaluate_commit(mv, tol, pre_peel_tris, axis_final, grow_hint)

        if ev.fail_gate == Gate.PASS:
            reg = _fill_cylinder_region(mv, ev, axis_final, pre_peel_tris)
            work.accepted.append(reg)
            for m in members:
                work.provisionals[m].claim = ProvClaim.CONSUMED_CYLINDER
            continue

        if ev.fail_gate == Gate.G2 and len(members) >= 3:
            peel_x = members[0]
            best_res = -1.0
            best_min_tri = INT_MAX
            for m in members:
                res = _max_vertex_residual(
                    mv, work.provisionals[m].tris, axis_final, ev.center, ev.radius
                )
                mt = _min_tri_id(work.provisionals[m])
                if res > best_res or (res == best_res and mt < best_min_tri):
                    best_res = res
                    best_min_tri = mt
                    peel_x = m
            peeled = [m for m in members if m != peel_x]
            if _members_edge_connected(prov_adj, peeled):
                peel_tris = _merge_member_tris(work.provisionals, peeled)
                axis_peel, _, _, _, _ = _axis_of(
                    mv, work.provisionals, peeled, seed_axis, tol
                )
                ev_p = _evaluate_commit(mv, tol, peel_tris, axis_peel)
                if ev_p.fail_gate == Gate.PASS:
                    reg = _fill_cylinder_region(mv, ev_p, axis_peel, peel_tris)
                    work.accepted.append(reg)
                    for m in peeled:
                        work.provisionals[m].claim = ProvClaim.CONSUMED_CYLINDER
                    work.provisionals[peel_x].claim = ProvClaim.UNCLAIMED
                    work.provisionals[peel_x].seed_tried = True
                    continue

        for m in members:
            work.provisionals[m].claim = ProvClaim.UNCLAIMED
            work.provisionals[m].seed_tried = True

        if ev.fail_gate != Gate.G5:
            rej = Region()
            rej.id = len(work.rejected)
            rej.type = SurfType.CYLINDER
            rej.origin = Origin.CYL_GROW
            rej.tris = pre_peel_tris
            if ev.fail_gate == Gate.G1:
                rej.reject = Reject.SPAN if ev.d2.span_reject else _classify_g1_reject(ev.g, tol)
            elif ev.fail_gate == Gate.G2:
                rej.reject = Reject.VERTEX_RESIDUAL
            elif ev.fail_gate == Gate.G3:
                rej.reject = Reject.CHORD_CONSISTENCY
            elif ev.fail_gate == Gate.G4:
                rej.reject = Reject.RADIUS_SANITY
            else:
                rej.reject = Reject.GAUSS_PLANARITY
            work.rejected.append(rej)

    work.accepted.sort(key=lambda r: r.tris[0] if r.tris else INT_MAX)
    work.rejected.sort(key=lambda r: r.tris[0] if r.tris else INT_MAX)
    return True


# --- A3: plane commit (refit_grow.cpp commitPlanesA3) ---------------------------

@dataclass
class _ArcStripDetect:
    """refit_internal.hpp ArcStripDetect."""

    ok: bool = False
    axis: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 1.0]))
    center: np.ndarray = field(default_factory=lambda: np.zeros(3))
    radius: float = 0.0
    span_rad: float = 0.0
    static_normals: bool = False
    chain_score: float = 0.0
    from_arch_chain: bool = False
    area_cv: float = 0.0
    ang_cv: float = 0.0
    chain_n: int = 0


def _unit_tri_normal(mv: MeshView, lt: int):
    n = tri_normal(mv, lt)
    area = tri_area(mv, lt)
    if not area > 0.0:
        return None
    return n, area


def _edge_dihedral_tri_pair(mv: MeshView, t0: int, t1: int) -> float:
    a = _unit_tri_normal(mv, t0)
    b = _unit_tri_normal(mv, t1)
    if a is None or b is None:
        return 0.0
    return math.acos(max(-1.0, min(1.0, float(np.dot(a[0], b[0])))))


def _normal_covariance(mv: MeshView, tris: list):
    """Area-weighted covariance of the facet normals (refit_math.cpp)."""
    nbar = np.zeros(3)
    area_sum = 0.0
    for lt in tris:
        r = _unit_tri_normal(mv, lt)
        if r is None:
            continue
        n, area = r
        area_sum += area
        nbar = nbar + n * area
    if not area_sum > 0.0:
        return None
    nbar = nbar / area_sum
    cov = np.zeros((3, 3))
    for lt in tris:
        r = _unit_tri_normal(mv, lt)
        if r is None:
            continue
        n, area = r
        d = n - nbar
        cov += area * np.outer(d, d)
    return nbar, cov, area_sum


def _max_cyl_residual(mv, tris, axis, center, radius) -> float:
    a = np.asarray(axis, dtype=float)
    c = np.asarray(center, dtype=float)
    worst = 0.0
    for lt in tris:
        for k in range(3):
            v = tri_corner(mv, lt, k)
            rr = float(np.linalg.norm(np.cross(a, v - c)))
            worst = max(worst, abs(rr - radius))
    return worst


def _monotonic_normal_span(mv: MeshView, order: list, axis: np.ndarray):
    """Do the facet normals rotate monotonically about the axis, and by how much?"""
    if len(order) < 3:
        return False, 0.0, 0.0
    frame = _axis_frame(axis)
    if frame is None:
        return False, 0.0, 0.0
    u, v = frame
    ang = []
    for lt in order:
        r = _unit_tri_normal(mv, lt)
        if r is None:
            continue
        n = r[0]
        pp = n - axis * float(np.dot(n, axis))
        pm = float(np.linalg.norm(pp))
        if pm < 1e-12:
            continue
        pp = pp / pm
        ang.append(_wrap_to_pi(math.atan2(float(np.dot(pp, v)), float(np.dot(pp, u)))))
    if len(ang) < 3:
        return False, 0.0, 0.0
    s = sorted(ang)
    pos = neg = tot = 0
    for i in range(1, len(s)):
        d = s[i] - s[i - 1]
        if abs(d) < 1e-4:
            continue
        tot += 1
        if d > 0.0:
            pos += 1
        else:
            neg += 1
    mono_frac = max(pos, neg) / tot if tot > 0 else 1.0
    span = s[-1] - s[0]
    wrap_gap = 2.0 * K_PI - s[-1] + s[0]
    if wrap_gap > span:
        span = wrap_gap
    return (span >= 0.14 and mono_frac >= 0.70), span, mono_frac


def _tris_share_edge_verts(mv: MeshView, t0: int, t1: int):
    T0 = mv.tris[t0]
    T1 = mv.tris[t1]
    for k in range(3):
        a, b = int(T0[k]), int(T0[(k + 1) % 3])
        for j in range(3):
            c, d = int(T1[j]), int(T1[(j + 1) % 3])
            if (a == c and b == d) or (a == d and b == c):
                return a, b
    return None


def _strip_width_along_axis(mv: MeshView, t0: int, t1: int, axis: np.ndarray) -> float:
    """Circumferential width of a strip: area divided by axial extent.

    Deriving the width from area rather than from the shared edge is what makes
    R = w / (2 sin(theta/2)) read the arc rather than the seam: on a Fusion export the
    shared edge is often an axial generator, whose length says nothing about the arc.
    """
    ax = np.asarray(axis, dtype=float)
    am = float(np.linalg.norm(ax))
    if am < 1e-15:
        return 0.0
    ax = ax / am

    def axial_extent(t):
        pts = [tri_corner(mv, t, k) for k in range(3)]
        d = [float(np.dot(ax, p)) for p in pts]
        return max(d) - min(d)

    def width_from_area(t):
        r = _unit_tri_normal(mv, t)
        if r is None:
            return 0.0
        h = axial_extent(t)
        if h <= 1e-6:
            return 0.0
        return 2.0 * r[1] / h

    w0 = width_from_area(t0)
    w1 = width_from_area(t1)
    if w0 > 0.0 and w1 > 0.0:
        return 0.5 * (w0 + w1)
    sh = _tris_share_edge_verts(mv, t0, t1)
    if sh is None:
        return 0.0
    e = mv.pts[sh[1]] - mv.pts[sh[0]]
    length = float(np.linalg.norm(e))
    if not length > 0.0:
        return 0.0
    if abs(float(np.dot(e, ax))) / length > 0.82:
        return 0.0
    return length


def _tri_in_patch_neighbors(mv: MeshView, t: int, in_patch: list) -> list:
    nb = set()
    for s in range(3):
        e = int(mv.tri_edges[t, s])
        for u in range(mv.n_tri):
            if not in_patch[u] or u == t:
                continue
            if e in (int(mv.tri_edges[u, 0]), int(mv.tri_edges[u, 1]), int(mv.tri_edges[u, 2])):
                nb.add(u)
    return sorted(nb)


def _build_tri_path_chain(mv: MeshView, tris: list) -> list:
    """Longest walk through the patch that always steps across a real bend.

    A tessellated arc is a *path* of strips, not a blob; recovering that order is what
    lets the equal-step law be tested at all.
    """
    if len(tris) < 3:
        return []
    in_patch = [False] * mv.n_tri
    for t in tris:
        if 0 <= t < mv.n_tri:
            in_patch[t] = True

    def walk_from(start: int, arc_only: bool) -> list:
        out = []
        seen = [False] * mv.n_tri
        cur, prev = start, -1
        while cur >= 0 and not seen[cur]:
            out.append(cur)
            seen[cur] = True
            nxt, best_phi = -1, 0.0
            for u in _tri_in_patch_neighbors(mv, cur, in_patch):
                if u == prev or seen[u]:
                    continue
                phi = _edge_dihedral_tri_pair(mv, cur, u)
                if arc_only and (phi < 0.012 or phi > K_PI - 0.012):
                    continue
                if nxt < 0 or phi > best_phi:
                    nxt, best_phi = u, phi
            prev, cur = cur, nxt
        return out

    best: list = []
    for t in tris:
        if 0 <= t < mv.n_tri:
            c = walk_from(t, True)
            if len(c) > len(best):
                best = c
    if len(best) < 3:
        for t in tris:
            if 0 <= t < mv.n_tri:
                c = walk_from(t, False)
                if len(c) > len(best):
                    best = c
    return best if len(best) >= 3 else []


def _cv_ok(vals: list, skip_ends: int, max_cv: float) -> bool:
    cv = _cv_of(vals, skip_ends)
    return cv is not None and cv <= max_cv


def _cv_of(vals: list, skip_ends: int):
    """Population CV over the interior of the list, or None if it cannot be formed."""
    if len(vals) < 2:
        return None
    lo = max(0, skip_ends)
    hi = len(vals) - max(0, skip_ends)
    if hi <= lo + 1:
        return None
    seg = vals[lo:hi]
    if any(not v > 0.0 for v in seg):
        return None
    if len(seg) < 2:
        return None
    mean = sum(seg) / len(seg)
    if not mean > 0.0:
        return None
    var = sum(v * v for v in seg) / len(seg) - mean * mean
    if var <= 0.0:
        return 0.0
    return math.sqrt(var) / mean


def _chain_area_ang_cv(mv: MeshView, chain: list):
    if len(chain) < 3:
        return None
    areas = []
    for t in chain:
        r = _unit_tri_normal(mv, t)
        if r is None:
            return None
        areas.append(r[1])
    arc_thetas = []
    for i in range(1, len(chain)):
        th = _edge_dihedral_tri_pair(mv, chain[i - 1], chain[i])
        if 0.012 <= th <= K_PI - 0.04:
            arc_thetas.append(th)
    area_cv = _cv_of(areas, 2 if len(chain) >= 10 else 1)
    if area_cv is None:
        return None
    ang_cv = _cv_of(arc_thetas, 0) if len(arc_thetas) >= 2 else 0.0
    return area_cv, (ang_cv if ang_cv is not None else 0.0)


def _radius_from_arch_chain(mv, chain, axis, r_hint=0.0):
    """R = w / (2 sin(theta/2)) along an ordered strip chain, with equal-step gates."""
    if len(chain) < 3:
        return None
    k_min_theta, k_max_theta = 0.012, K_PI - 0.04
    areas = []
    for t in chain:
        r = _unit_tri_normal(mv, t)
        if r is None:
            return None
        areas.append(r[1])
    thetas = [_edge_dihedral_tri_pair(mv, chain[i - 1], chain[i]) for i in range(1, len(chain))]
    if not _cv_ok(areas, 2 if len(chain) >= 10 else 1, 0.42):
        return None
    arc_thetas = [t for t in thetas if k_min_theta <= t <= k_max_theta]
    if len(arc_thetas) < 2 or not _cv_ok(arc_thetas, 0, 0.45):
        return None
    radii = []
    good = 0
    for i in range(1, len(chain)):
        theta = thetas[i - 1]
        if theta < k_min_theta or theta > k_max_theta:
            continue
        w = _strip_width_along_axis(mv, chain[i - 1], chain[i], axis)
        if not w > 0.0:
            continue
        s = math.sin(0.5 * theta)
        if s <= 1e-9:
            continue
        r_chord = w / (2.0 * s)
        if not (r_chord > 0.0) or not math.isfinite(r_chord):
            continue
        if r_hint > 0.0 and not (0.48 < r_chord / r_hint < 1.52):
            continue
        radii.append(r_chord)
        good += 1
    if len(radii) < 2:
        return None
    r_med = _median_of(radii)
    if not r_med > 0.0:
        return None
    n_links = len(chain) - 1
    link_frac = good / n_links if n_links > 0 else 0.0
    score = link_frac * min(1.0, len(chain) / 5.0)
    if score < 0.28:
        return None
    return r_med, score


def _radius_from_arch_chain_pairs(mv, tris, axis, r_hint=0.0):
    ids = sorted(set(tris))
    if len(ids) < 3:
        return None
    ws, ths = [], []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if _tris_share_edge_verts(mv, ids[i], ids[j]) is None:
                continue
            theta = _edge_dihedral_tri_pair(mv, ids[i], ids[j])
            if theta < 0.012 or theta > K_PI - 0.012:
                continue
            w = _strip_width_along_axis(mv, ids[i], ids[j], axis)
            if not w > 0.0:
                continue
            s = math.sin(0.5 * theta)
            if s <= 1e-9:
                continue
            r_chord = w / (2.0 * s)
            if not (r_chord > 0.0) or not math.isfinite(r_chord):
                continue
            if r_hint > 0.0 and not (0.48 < r_chord / r_hint < 1.52):
                continue
            ws.append(w)
            ths.append(theta)
    if len(ws) < 2 or not _cv_ok(ws, 0, 0.45) or not _cv_ok(ths, 0, 0.45):
        return None
    s = math.sin(0.5 * _median_of(ths))
    if s <= 1e-9:
        return None
    radius = _median_of(ws) / (2.0 * s)
    if not radius > 0.0 or not math.isfinite(radius):
        return None
    return radius, min(1.0, len(ws) / 6.0)


def _detect_arch_chain(mv: MeshView, tris: list, tol: DerivedTols) -> _ArcStripDetect:
    """Point-to-point arch chain: equal-area strips joined at uniform dihedral steps."""
    out = _ArcStripDetect()
    if not law_band_applicable(mv):
        return out
    ids = sorted(set(tris))
    if len(ids) < 3:
        return out
    nc = _normal_covariance(mv, ids)
    if nc is None:
        return out
    _evals, evecs = np.linalg.eigh(nc[1])
    w1 = evecs[:, 0]
    wm = float(np.linalg.norm(w1))
    if wm < 1e-15:
        return out
    axis = sign_normalize(w1 / wm)

    chain = _build_tri_path_chain(mv, ids)
    if not chain:
        return out
    rc = _radius_from_arch_chain(mv, chain, axis, 0.0)
    if rc is None:
        return out
    chain_r, chain_score = rc

    cv = _chain_area_ang_cv(mv, chain)
    if cv is not None:
        out.area_cv, out.ang_cv = cv
    out.chain_n = len(chain)
    out.chain_score = chain_score

    _mono, span, _frac = _monotonic_normal_span(mv, chain, axis)

    ok, center, radius = _eberly_center_radius(mv, ids, axis)
    if not ok:
        return out
    if chain_score >= 0.45:
        radius = chain_r

    # Coarse band keeps the shipped R >= 8 floor; outside it a high-confidence chain
    # may go down to R >= 2.
    r_floor = 2.0 if (not coarse_fusion_band(mv) and chain_score >= 0.85) else 8.0
    if not (radius >= r_floor) or radius > 55.0:
        return out

    accept = tol.eps_cyl_accept(radius)
    accept = max(accept, _chord_sagitta(radius, max(6, len(ids))))
    if coarse_fusion_band(mv):
        accept = max(accept, 0.05 * radius)
    if _max_cyl_residual(mv, ids, axis, center, radius) > accept:
        return out

    out.ok = True
    out.axis = axis
    out.center = center
    out.radius = radius
    out.span_rad = span
    out.from_arch_chain = True
    return out


def _order_tris_bfs(mv: MeshView, tris: list, max_phi: float) -> list:
    in_patch = [False] * mv.n_tri
    for t in tris:
        if 0 <= t < mv.n_tri:
            in_patch[t] = True
    seed = min(tris)
    seen = [False] * mv.n_tri
    seen[seed] = True
    q = [seed]
    order = []
    while q:
        t = q.pop(0)
        order.append(t)
        for u in _tri_in_patch_neighbors(mv, t, in_patch):
            if seen[u] or _edge_dihedral_tri_pair(mv, t, u) > max_phi:
                continue
            seen[u] = True
            q.append(u)
    return order if len(order) >= 3 else []


def _detect_large_arc_strip(mv: MeshView, tris: list, tol: DerivedTols) -> _ArcStripDetect:
    """Gauss-map strip detector: normals rotating about one axis, or a static-normal
    ring on tessellation too coarse for the rotation to show (refit_math.cpp)."""
    out = _ArcStripDetect()
    ids = sorted(set(tris))
    if len(ids) < 3:
        return out
    nc = _normal_covariance(mv, ids)
    if nc is None:
        return out
    _nbar, cov, area_sum = nc
    evals, evecs = np.linalg.eigh(cov)

    length = max(mv.diag, tol.eps_mesh)
    theta = (tol.eps_mesh / length) if length > 0.0 else 0.0
    mu2_floor = area_sum * theta * theta
    if evals[1] <= mu2_floor and evals[1] <= 1e-12 * max(evals[2], 1e-300):
        return out

    pca = pca_plane(mv, ids)
    pdev = _max_vertex_plane_dev(mv, ids, pca) if pca is not None else 0.0

    w1 = evecs[:, 0]
    wm = float(np.linalg.norm(w1))
    if wm < 1e-15:
        return out
    axis = sign_normalize(w1 / wm)

    order = _order_tris_bfs(mv, ids, tol.theta_plane)
    if not order:
        return out
    mono, span, _frac = _monotonic_normal_span(mv, order, axis)
    static_normals = (not mono) and pdev > tol.eps_plane * 2.0
    if not mono and not static_normals:
        return out
    if mono and span < 0.21:  # ~12 degrees
        return out

    ok, center, radius = _eberly_center_radius(mv, ids, axis)
    if not ok or not (radius >= 15.0) or radius > 55.0:
        return out

    accept = tol.eps_cyl_accept(radius)
    accept = max(accept, _chord_sagitta(radius, max(6, len(ids))))
    if coarse_fusion_band(mv):
        # Chordal rings on large-R partial arcs need slack beyond the sagitta floor.
        accept = max(accept, 0.05 * radius)
    if _max_cyl_residual(mv, ids, axis, center, radius) > accept:
        return out

    out.ok = True
    out.axis = axis
    out.center = center
    out.radius = radius
    out.span_rad = span
    out.static_normals = static_normals
    return out


def _max_vertex_plane_dev(mv: MeshView, tris: list, ax: gp_Ax3) -> float:
    n = _np_dir(ax.Direction())
    loc = _np_pnt(ax.Location())
    worst = 0.0
    for lt in tris:
        for k in range(3):
            worst = max(worst, abs(float(np.dot(tri_corner(mv, lt, k) - loc, n))))
    return worst


def _peel_large_arc_strips_a2b(mv: MeshView, tol: DerivedTols, work: _SegmentWork) -> bool:
    """Stage A2b (refit_grow.cpp:1838), called from INSIDE commitPlanesA3.

    Absorption is the named failure mode of arm C: a large-radius arc spread over a few
    coarse facets differs so little from a plane that A2 swallows it, and once the plane
    is committed the arc is gone. This peels those strips back out of the unclaimed
    provisionals before the commit, and only there -- it never touches a provisional a
    later stage already claimed.
    """
    if not coarse_fusion_band(mv):
        # Outside the coarse band, peel only high-confidence arch chains.
        if not (law_band_applicable(mv) and not coarse_fusion_band(mv) and mv.n_tri <= 2500):
            return True
        for prov in work.provisionals:
            if prov.claim != ProvClaim.UNCLAIMED or len(prov.tris) < 3:
                continue
            det = _detect_arch_chain(mv, prov.tris, tol)
            if not det.ok or det.chain_score < 0.85:
                continue
            ev = _evaluate_commit(mv, tol, prov.tris, det.axis)
            if ev.fail_gate != Gate.PASS:
                continue
            work.accepted.append(_fill_cylinder_region(mv, ev, det.axis, prov.tris))
            prov.claim = ProvClaim.CONSUMED_CYLINDER
            prov.tris = []
            prov.area = 0.0
        work.accepted.sort(key=lambda r: r.tris[0] if r.tris else INT_MAX)
        return True

    for prov in work.provisionals:
        if prov.claim != ProvClaim.UNCLAIMED or len(prov.tris) < 3:
            continue
        arch = _detect_arch_chain(mv, prov.tris, tol)
        gauss = _detect_large_arc_strip(mv, prov.tris, tol)
        if not arch.ok and not gauss.ok:
            continue
        if arch.ok and arch.chain_score >= 0.45 and (
            not gauss.ok or arch.chain_score >= gauss.chain_score + 0.05
            or gauss.chain_score < 0.35
        ):
            det = arch
        elif gauss.ok:
            det = gauss
        else:
            det = arch

        ev = _evaluate_commit(mv, tol, prov.tris, det.axis)
        if ev.fail_gate != Gate.PASS:
            # A coarse large-R partial arc can pass the detector and still miss B1's
            # G3/G5 on a few-band span. The detector already gated it; accept on the
            # Eberly solve rather than lose the arc to a plane.
            if not coarse_fusion_band(mv) or det.radius < 15.0:
                continue
            ok, c, r = _eberly_center_radius(mv, prov.tris, det.axis)
            if not ok:
                continue
            ev = _CommitEval()
            ev.fail_gate = Gate.PASS
            ev.radius = r
            ev.center = c
            ev.eberly_ok = True
            ev.d2 = _compute_d2(mv, prov.tris, det.axis, c, r, tol)
            if ev.d2.span_reject:
                continue

        work.accepted.append(_fill_cylinder_region(mv, ev, det.axis, prov.tris))
        prov.claim = ProvClaim.CONSUMED_CYLINDER
        prov.tris = []
        prov.area = 0.0

    work.accepted.sort(key=lambda r: r.tris[0] if r.tris else INT_MAX)
    return True


def _commit_planes_a3(mv: MeshView, tol: DerivedTols, work: _SegmentWork) -> bool:
    # Shatter-class unclaimed provisionals stay Unclaimed so stage D emits
    # islands (I1). Area floor is D5.2: epsPlane * diag.
    area_min = tol.eps_plane * mv.diag
    n_prov = len(work.provisionals)

    # Coarse meshes (handle-lock): merge coplanar provisional neighbours before
    # commit so plane|cyl chain count stays buildable.
    if coarse_fusion_band(mv):
        adj = build_edge_adj(mv)
        tri_to_prov = [-1] * mv.n_tri
        for pi, prov in enumerate(work.provisionals):
            for t in prov.tris:
                tri_to_prov[t] = pi
        uf = _UnionFind(n_prov)
        merge_ang = tol.theta_plane
        uncl = [p for p in work.provisionals if p.claim == ProvClaim.UNCLAIMED]
        if uncl and sum(len(p.tris) for p in uncl) // len(uncl) <= 4:
            merge_ang = max(merge_ang, 10.0 * K_PI / 180.0)
        cos_merge = math.cos(merge_ang)

        def coplanar(i: int, j: int) -> bool:
            P, Q = work.provisionals[i], work.provisionals[j]
            if P.claim != ProvClaim.UNCLAIMED or Q.claim != ProvClaim.UNCLAIMED:
                return False
            n_p, n_q = P.plane.Direction(), Q.plane.Direction()
            if (
                n_p.X() * n_q.X() + n_p.Y() * n_q.Y() + n_p.Z() * n_q.Z()
            ) < cos_merge:
                return False
            lp, lq = P.plane.Location(), Q.plane.Location()
            d = abs(
                (lp.X() - lq.X()) * n_p.X()
                + (lp.Y() - lq.Y()) * n_p.Y()
                + (lp.Z() - lq.Z()) * n_p.Z()
            )
            return d <= tol.eps_plane * 10.0

        for e in range(mv.n_edge):
            t0, t1 = adj[e]
            if t0 < 0 or t1 < 0:
                continue
            p0, p1 = tri_to_prov[t0], tri_to_prov[t1]
            if p0 < 0 or p1 < 0 or p0 == p1:
                continue
            if coplanar(p0, p1):
                uf.unite(p0, p1)
        groups: dict[int, list[int]] = {}
        for i in range(n_prov):
            groups.setdefault(uf.find(i), []).append(i)
        for r in range(n_prov):
            g = groups.get(uf.find(r), [])
            if len(g) <= 1:
                continue
            g = sorted(set(g))
            if g[0] != r:
                continue
            merged = Provisional(
                chart_id=work.provisionals[r].chart_id, claim=ProvClaim.UNCLAIMED
            )
            tris = set()
            for pi in g:
                tris.update(work.provisionals[pi].tris)
            merged.tris = sorted(tris)
            fit = pca_plane(mv, merged.tris)
            merged.plane = fit if fit is not None else work.provisionals[r].plane
            merged.area = 0.0
            for lt in merged.tris:
                merged.area += tri_area(mv, lt)
            compute_prov_deviations(mv, merged)
            work.provisionals[r] = merged
            for k in g[1:]:
                dead = work.provisionals[k]
                dead.tris = []
                dead.area = 0.0

    # A2b: peel absorbed large-R arc strips back out BEFORE the plane commit
    # (refit_grow.cpp:2017 — inside A3, after the coplanar merge, so merged shards
    # are visible to the detector).
    if not _peel_large_arc_strips_a2b(mv, tol, work):
        return False

    for prov in work.provisionals:
        if prov.claim != ProvClaim.UNCLAIMED:
            continue
        n = len(prov.tris)
        if n <= 2 and prov.area <= area_min:
            continue  # stays Unclaimed; stage D emits it as a facet island

        reg = Region()
        reg.type = SurfType.PLANE
        reg.origin = Origin.PLANE_GROW
        reg.tris = list(prov.tris)
        reg.ax = prov.plane
        reg.max_vertex_dev = prov.max_vertex_dev
        reg.rms_vertex_dev = prov.rms_vertex_dev
        reg.n_sides = 0
        reg.chord_sagitta = 0.0
        reg.outward_normal = compute_outward_plane(mv, prov.tris, prov.plane)
        reg.dvol_predicted = dvol_plane_region(mv, prov.tris, prov.plane)
        reg.closed360 = False
        work.accepted.append(reg)
        prov.claim = ProvClaim.COMMITTED_PLANE

    work.accepted.sort(key=lambda r: r.tris[0] if r.tris else INT_MAX)
    return True


# --- D: topology (refit_chains.cpp buildTopologyD) ------------------------------

class _Part:
    __slots__ = ("isl", "reg")

    def __init__(self, reg: int = -1, isl: int = -1):
        self.reg = reg
        self.isl = isl


def _part_eq(a: _Part, b: _Part) -> bool:
    return a.reg == b.reg and a.isl == b.isl


def _label_of_tri(t: int, tri_region: list, tri_island: list) -> _Part:
    if t < 0:
        return _Part()
    return _Part(tri_region[t], tri_island[t])


def _local_pnt(mv: MeshView, lv: int) -> np.ndarray:
    return mv.pts[int(mv.comp_vtx[lv])]


def _left_triangle(mv, e, v_from, v_to, edge_tris) -> int:
    for t in edge_tris[e]:
        lv = local_verts_of_tri(mv, t)
        for s in range(3):
            if lv[s] == v_from and lv[(s + 1) % 3] == v_to:
                return t
    return -1


def _reverse_open(w) -> None:
    w.verts.reverse()
    w.edges.reverse()


def _reverse_closed_keep_start(w) -> None:
    """Reverse a closed chain, preserving verts[i] --edges[i]--> verts[(i+1)%n]
    (including the wrap edge) and keeping the start vertex in slot 0."""
    n = len(w.verts)
    if n < 2 or len(w.edges) != n:
        return
    verts, edges = w.verts, w.edges
    w.verts = [verts[0]] + [verts[n - i] for i in range(1, n)]
    w.edges = [edges[n - 1]] + [edges[n - 1 - i] for i in range(1, n)]


def _rotate_closed_to_min_vert(w) -> None:
    verts = w.verts
    best = 0
    for i in range(1, len(verts)):
        if verts[i] < verts[best]:
            best = i
    w.verts = verts[best:] + verts[:best]
    w.edges = w.edges[best:] + w.edges[:best]


def _chain_start_vert(chain: BoundaryChain, rev: bool) -> int:
    return chain.mesh_verts[-1] if rev else chain.mesh_verts[0]


def _chain_end_vert(chain: BoundaryChain, rev: bool) -> int:
    return chain.mesh_verts[0] if rev else chain.mesh_verts[-1]


def _project_plane(ax: gp_Ax3, p: np.ndarray) -> tuple[float, float]:
    loc = ax.Location()
    xd = ax.XDirection()
    yd = ax.YDirection()
    dx, dy, dz = p[0] - loc.X(), p[1] - loc.Y(), p[2] - loc.Z()
    return (
        dx * xd.X() + dy * xd.Y() + dz * xd.Z(),
        dx * yd.X() + dy * yd.Y() + dz * yd.Z(),
    )


def _shoelace(uv: list) -> float:
    s = 0.0
    n = len(uv)
    for i in range(n):
        x0, y0 = uv[i]
        x1, y1 = uv[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return 0.5 * s


def _g1_tangent_plane(a: Region, b: Region) -> bool:
    na, nb = a.ax.Direction(), b.ax.Direction()
    return (
        na.X() * nb.X() + na.Y() * nb.Y() + na.Z() * nb.Z()
    ) >= math.cos(K_DEG3) - 1e-15


def _dist_point_plane(ax: gp_Ax3, p: np.ndarray) -> float:
    n = ax.Direction()
    loc = ax.Location()
    return abs(
        n.X() * (p[0] - loc.X()) + n.Y() * (p[1] - loc.Y()) + n.Z() * (p[2] - loc.Z())
    )


def _chord_dev_to_region(r: Region, p: np.ndarray, q: np.ndarray) -> float:
    m = (p + q) * 0.5
    if r.type == SurfType.PLANE:
        return _dist_point_plane(r.ax, m)
    return 0.0


class _ChainWalk:
    __slots__ = ("closed", "edges", "verts")

    def __init__(self):
        self.edges: list[int] = []
        self.verts: list[int] = []
        self.closed = False


def _build_topology_d(mv: MeshView, tol: DerivedTols, work: _SegmentWork, out: RegionSet) -> bool:
    n_tri, n_vtx, n_edge = mv.n_tri, mv.n_vtx, mv.n_edge

    out.regions = []
    out.rejected = []
    out.chains = []
    out.tri_region = [-1] * n_tri
    out.tri_island = [-1] * n_tri
    out.n_islands = 0

    if n_tri == 0:
        out.rejected = list(work.rejected)
        out.stats.rejected = len(work.rejected)
        return True

    # --- accepted regions: sort (-area, minLocalTriId), dense ids ----------
    acc = []
    for i, r in enumerate(work.accepted):
        r.tris = sorted(r.tris)
        for t in r.tris:
            if t < 0 or t >= n_tri:
                return False
        area = 0.0
        for t in r.tris:  # ascending: I5 accumulation order
            area += tri_area(mv, t)
        min_tri = r.tris[0] if r.tris else INT_MAX
        r.loops = []
        acc.append((area, min_tri, i, r))
    acc.sort(key=lambda x: (-x[0], x[1], x[2]))

    acc_remap = [-1] * len(work.accepted)
    for new_id, (_, _, in_idx, r) in enumerate(acc):
        r.id = new_id
        acc_remap[in_idx] = new_id
        out.regions.append(r)
        for t in r.tris:
            if out.tri_region[t] >= 0:
                return False
            out.tri_region[t] = new_id

    # --- islands: maximal connected unclaimed, sort (-area, minLocalTriId)
    uf = list(range(n_tri))

    def find(x: int) -> int:
        while uf[x] != x:
            uf[x] = uf[uf[x]]
            x = uf[x]
        return x

    def unite(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if ra > rb:
            ra, rb = rb, ra
        uf[rb] = ra

    edge_tris: list[list[int]] = [[] for _ in range(n_edge)]
    for t in range(n_tri):
        for s in range(3):
            e = int(mv.tri_edges[t, s])
            if e < 0 or e >= n_edge:
                return False
            edge_tris[e].append(t)
    for e in range(n_edge):
        v = sorted(set(edge_tris[e]))
        edge_tris[e] = v

    for e in range(n_edge):
        if len(edge_tris[e]) != 2:
            continue
        t0, t1 = edge_tris[e]
        if out.tri_region[t0] < 0 and out.tri_region[t1] < 0:
            unite(t0, t1)

    root_index: list[int] = []
    islands: list[tuple[list, float, int]] = []
    for t in range(n_tri):
        if out.tri_region[t] >= 0:
            continue
        r = find(t)
        try:
            slot = root_index.index(r)
        except ValueError:
            slot = len(islands)
            root_index.append(r)
            islands.append(([], 0.0, 0))
        islands[slot][0].append(t)
    isl_sorted = []
    for tris, _, _ in islands:
        tris.sort()
        area = 0.0
        for t in tris:
            area += tri_area(mv, t)
        min_tri = tris[0] if tris else INT_MAX
        isl_sorted.append((tris, area, min_tri))
    isl_sorted.sort(key=lambda x: (-x[1], x[2]))
    out.n_islands = len(isl_sorted)
    for isl_id, (tris, _, _) in enumerate(isl_sorted):
        for t in tris:
            out.tri_island[t] = isl_id

    # I1: total, non-overlapping partition
    for t in range(n_tri):
        if (out.tri_region[t] >= 0) == (out.tri_island[t] >= 0):
            return False

    # --- I8 split vertices --------------------------------------------------
    is_split = [0] * n_vtx
    vtx_tris: list[list[int]] = [[] for _ in range(n_vtx)]
    vtx_edges: list[list[int]] = [[] for _ in range(n_vtx)]
    for e in range(n_edge):
        a, b = mv.comp_edges[e]
        if a < 0 or a >= n_vtx or b < 0 or b >= n_vtx:
            return False
        vtx_edges[a].append(e)
        vtx_edges[b].append(e)
        cnt = len(edge_tris[e])
        if cnt == 1 or cnt >= 3:
            is_split[a] = 1
            is_split[b] = 1
    for t in range(n_tri):
        lv = local_verts_of_tri(mv, t)
        for k in range(3):
            if lv[k] < 0 or lv[k] >= n_vtx:
                return False
            vtx_tris[lv[k]].append(t)
    for v in range(n_vtx):
        ts = sorted(set(vtx_tris[v]))
        vtx_tris[v] = ts
        parts: list[_Part] = []
        for t in ts:
            lab = _label_of_tri(t, out.tri_region, out.tri_island)
            if not any(_part_eq(q, lab) for q in parts):
                parts.append(lab)
        if len(parts) >= 3:
            is_split[v] = 1

    def is_boundary_edge(e: int) -> bool:
        cnt = len(edge_tris[e])
        if cnt == 1:
            return True
        if cnt != 2:
            return False
        a = _label_of_tri(edge_tris[e][0], out.tri_region, out.tri_island)
        b = _label_of_tri(edge_tris[e][1], out.tri_region, out.tri_island)
        return not _part_eq(a, b)

    boundary = [0] * n_edge
    bound_at_v = [0] * n_vtx
    for e in range(n_edge):
        if not is_boundary_edge(e):
            continue
        boundary[e] = 1
        bound_at_v[mv.comp_edges[e][0]] += 1
        bound_at_v[mv.comp_edges[e][1]] += 1
    for v in range(n_vtx):
        if bound_at_v[v] != 2:
            is_split[v] = 1

    used = [0] * n_edge

    def next_bound_edge(v: int, incoming: int) -> int:
        found = -1
        for e in vtx_edges[v]:
            if not boundary[e] or used[e] or e == incoming:
                continue
            if found < 0 or e < found:
                found = e
        return found

    def walk_from(start_e: int, start_v: int) -> _ChainWalk:
        w = _ChainWalk()
        e, v = start_e, start_v
        w.verts.append(v)
        while e >= 0 and not used[e]:
            used[e] = 1
            w.edges.append(e)
            a, b = mv.comp_edges[e]
            nv = b if a == v else a
            w.verts.append(nv)
            v = nv
            if is_split[v]:
                break
            ne = next_bound_edge(v, e)
            if ne < 0:
                break
            e = ne
        return w

    walks: list[_ChainWalk] = []

    # Open chains: start at every unused boundary edge leaving a split vertex.
    split_verts = [v for v in range(n_vtx) if is_split[v]]
    for v in split_verts:
        leaves = sorted(e for e in vtx_edges[v] if boundary[e] and not used[e])
        for e in leaves:
            if used[e]:
                continue
            w = walk_from(e, v)
            w.closed = False
            if w.edges:
                walks.append(w)

    # Remaining unused boundary edges are closed cycles with no split vertex.
    for e0 in range(n_edge):
        if not boundary[e0] or used[e0]:
            continue
        a, b = mv.comp_edges[e0]
        start_v = a if a < b else b
        w = _ChainWalk()
        e, v = e0, start_v
        if v != a and v != b:
            v = a
        v = a
        w.verts.append(v)
        guard = n_edge + 2
        steps = 0
        while e >= 0 and not used[e] and steps < guard:
            steps += 1
            used[e] = 1
            w.edges.append(e)
            ea, eb = mv.comp_edges[e]
            nv = eb if ea == v else ea
            v = nv
            if v == w.verts[0] and len(w.edges) > 1:
                break
            w.verts.append(nv)
            ne = next_bound_edge(v, e)
            e = ne
            if ne < 0:
                break
            if ne == e0 and v == w.verts[0]:
                break
        if w.verts and len(w.verts) == len(w.edges) + 1 and w.verts[-1] == w.verts[0]:
            w.verts.pop()
        if len(w.verts) == len(w.edges) and w.edges:
            w.closed = True
            walks.append(w)
        elif w.edges:
            w.closed = False
            walks.append(w)

    # --- materialise BoundaryChain: I3 orientation, D5.6 start vertex -------
    for w in walks:
        if not w.edges or len(w.verts) < 2:
            continue
        if not w.closed:
            if w.verts[0] > w.verts[-1]:
                w.verts.reverse()
                w.edges.reverse()
        else:
            if len(w.verts) != len(w.edges):
                if len(w.verts) == len(w.edges) + 1 and w.verts[-1] == w.verts[0]:
                    w.verts.pop()
            if len(w.verts) != len(w.edges):
                return False
            _rotate_closed_to_min_vert(w)
            if len(w.edges) >= 2 and w.edges[-1] < w.edges[0]:
                _reverse_closed_keep_start(w)

        v_from, v_to = w.verts[0], w.verts[1]
        e0 = w.edges[0]
        t_left = _left_triangle(mv, e0, v_from, v_to, edge_tris)
        t_right = _left_triangle(mv, e0, v_to, v_from, edge_tris)
        if len(edge_tris[e0]) == 2:
            t0, t1 = edge_tris[e0]
            if t_left < 0 and t_right >= 0:
                t_left = t1 if t_right == t0 else t0
            elif t_right < 0 and t_left >= 0:
                t_right = t1 if t_left == t0 else t0
            elif t_left < 0 and t_right < 0:
                t_left, t_right = t0, t1
            elif t_right == t_left:
                t_right = t1 if t_left == t0 else t0
        part_l = _label_of_tri(t_left, out.tri_region, out.tri_island)
        part_r = _label_of_tri(t_right, out.tri_region, out.tri_island)

        ch = BoundaryChain()
        ch.reg_a, ch.reg_b = part_l.reg, part_r.reg
        ch.island_a, ch.island_b = part_l.isl, part_r.isl
        ch.closed_loop = w.closed
        ch.mesh_edges = list(w.edges)
        ch.mesh_verts = list(w.verts)
        if w.closed:
            if len(ch.mesh_verts) != len(ch.mesh_edges):
                return False
        else:
            if len(ch.mesh_verts) != len(ch.mesh_edges) + 1:
                return False
        if ch.reg_a >= 0 and ch.reg_b >= 0:
            ch.tangent = _g1_tangent_plane(out.regions[ch.reg_a], out.regions[ch.reg_b])
        out.chains.append(ch)

    out.chains.sort(key=lambda c: min(c.mesh_edges) if c.mesh_edges else INT_MAX)

    # --- loop assembly per region -------------------------------------------
    area_tie = 1e-12 * (mv.diag * mv.diag if mv.diag > 0 else 1.0)

    def classify_and_push(reg: Region, loops: list) -> bool:
        if not loops:
            return False
        scored = []
        for lp in loops:
            min_ch = min(lp.chain_idx) if lp.chain_idx else INT_MAX
            vs = []
            for k, ci in enumerate(lp.chain_idx):
                c = out.chains[ci]
                rev = lp.reversed[k]
                if c.closed_loop:
                    if rev:
                        vs.append(c.mesh_verts[0])
                        vs.extend(c.mesh_verts[i] for i in range(len(c.mesh_verts) - 1, 0, -1))
                    else:
                        vs.extend(c.mesh_verts)
                else:
                    if not rev:
                        begin = 0 if not vs else 1
                        vs.extend(c.mesh_verts[i] for i in range(begin, len(c.mesh_verts)))
                        if not vs:
                            vs.append(c.mesh_verts[0])
                    else:
                        last = len(c.mesh_verts) - 1
                        begin = last if not vs else last - 1
                        vs.extend(c.mesh_verts[i] for i in range(begin, -1, -1))
                        if not vs:
                            vs.append(c.mesh_verts[-1])
            if len(vs) >= 2 and vs[0] == vs[-1]:
                vs.pop()
            uv = [_project_plane(reg.ax, _local_pnt(mv, lv)) for lv in vs]
            scored.append((abs(_shoelace(uv)), min_ch, lp))

        # outer = max |area|, tie -> smaller minChainIdx
        i_outer, best_abs = 0, -1.0
        for i in range(len(scored)):
            aa, min_ch, _ = scored[i]
            if (
                aa > best_abs + area_tie
                or (abs(aa - best_abs) <= area_tie and min_ch < scored[i_outer][1])
                or best_abs < 0
            ):
                best_abs = aa
                i_outer = i
        for i in range(len(scored)):
            scored[i][2].role = LoopRole.OUTER if i == i_outer else LoopRole.INNER
        scored.sort(key=lambda s: (int(s[2].role), s[1]))
        reg.loops = [lp for _, _, lp in scored]
        return True

    for reg in out.regions:
        used_ch = [0] * len(out.chains)
        loops: list[Loop] = []

        def rev_for(c: BoundaryChain, _reg: "Region" = reg) -> int:
            if c.reg_a == _reg.id:
                return 0
            if c.reg_b == _reg.id:
                return 1
            return -1

        # Closed single-chain loops first.
        for ci, c in enumerate(out.chains):
            rv = rev_for(c)
            if rv < 0 or not c.closed_loop:
                continue
            lp = Loop(chain_idx=[ci], reversed=[rv], role=LoopRole.INNER)
            loops.append(lp)
            used_ch[ci] = 1

        # Stitch open chains into cycles.
        while True:
            seed = -1
            for ci, c in enumerate(out.chains):
                if used_ch[ci] or rev_for(c) < 0:
                    continue
                seed = ci
                break
            if seed < 0:
                break
            lp = Loop()
            ci = seed
            rv = rev_for(out.chains[ci])
            start_v = _chain_start_vert(out.chains[ci], rv != 0)
            guard = len(out.chains) + 2
            steps = 0
            closed_ok = False
            while ci >= 0 and not used_ch[ci] and steps < guard:
                steps += 1
                used_ch[ci] = 1
                lp.chain_idx.append(ci)
                lp.reversed.append(rv)
                end_v = _chain_end_vert(out.chains[ci], rv != 0)
                if end_v == start_v:
                    if len(lp.chain_idx) >= 2 or out.chains[ci].closed_loop:
                        closed_ok = True
                        break
                    if start_v == end_v:
                        closed_ok = True
                        break
                nxt, nxt_rev = -1, -1
                for k, c in enumerate(out.chains):
                    if used_ch[k] or rev_for(c) < 0:
                        continue
                    if _chain_start_vert(c, rev_for(c) != 0) == end_v:
                        if nxt < 0 or k < nxt:
                            nxt, nxt_rev = k, rev_for(c)
                if nxt < 0:
                    break
                ci = nxt
                rv = nxt_rev
                if _chain_end_vert(out.chains[ci], rv != 0) == start_v:
                    used_ch[ci] = 1
                    lp.chain_idx.append(ci)
                    lp.reversed.append(rv)
                    closed_ok = True
                    break
            if not closed_ok or not lp.chain_idx:
                return False
            loops.append(lp)

        # Every chain touching this region must appear in exactly one loop.
        for ci, c in enumerate(out.chains):
            if rev_for(c) < 0:
                continue
            hits = sum(1 for lp in loops if ci in lp.chain_idx)
            if hits != 1:
                return False

        if not classify_and_push(reg, loops):
            return False

        n_outer = sum(1 for lp in reg.loops if lp.role == LoopRole.OUTER)
        n_cap = sum(
            1
            for lp in reg.loops
            if lp.role in (LoopRole.CAP_LOW, LoopRole.CAP_HIGH)
        )
        if n_outer != 1 or n_cap != 0:
            return False

    # --- rejected[] (empty in the planar path; kept for contract parity) ------
    out.rejected = list(work.rejected)

    # --- RefitStats -----------------------------------------------------------
    st = RefitStats()
    st.rejected = len(out.rejected)
    st.facet_islands = out.n_islands
    st.facet_triangles = sum(1 for t in range(n_tri) if out.tri_island[t] >= 0)

    max_dev = 0.0
    dvol = 0.0
    radii = []
    for r in out.regions:
        if r.origin == Origin.FILLET_STRIP:
            st.fillets += 1
        elif r.type == SurfType.PLANE:
            st.planes += 1
        elif r.type == SurfType.CYLINDER:
            st.cylinders += 1
        max_dev = max(max_dev, r.max_vertex_dev)
        dvol += r.dvol_predicted
        if (r.type == SurfType.CYLINDER or r.origin == Origin.FILLET_STRIP) and r.radius > 0:
            radii.append(r.radius)
    st.max_vertex_dev = max_dev
    st.dvol_predicted = dvol

    # Distinct radii (refit_chains.cpp:1008-1015): sorted radii, counting a new one
    # whenever the step exceeds the mesh epsilon. Two bores that agree to within the
    # mesh's own resolution are one radius, not two.
    radii.sort()
    if radii:
        eps = max(tol.eps_mesh, 1e-9)
        st.distinct_radii = 1
        for i in range(1, len(radii)):
            if abs(radii[i] - radii[i - 1]) > eps:
                st.distinct_radii += 1

    max_edge = 0.0
    for c in out.chains:
        for i in range(len(c.mesh_edges)):
            if c.closed_loop:
                a = c.mesh_verts[i]
                b = c.mesh_verts[(i + 1) % len(c.mesh_verts)]
            else:
                a, b = c.mesh_verts[i], c.mesh_verts[i + 1]
            pa = _local_pnt(mv, a)
            pb = _local_pnt(mv, b)
            if c.reg_a >= 0:
                max_edge = max(max_edge, _chord_dev_to_region(out.regions[c.reg_a], pa, pb))
            if c.reg_b >= 0:
                max_edge = max(max_edge, _chord_dev_to_region(out.regions[c.reg_b], pa, pb))
    st.max_edge_tol = max_edge
    out.stats = st
    return True


# --- entry (refit_segment.cpp segment) -------------------------------------------

def segment(mv: MeshView, params: SegmentParams | None = None) -> RegionSet | None:
    """P1 entry point. Returns None on any stage failure (reference R3)."""
    if params is None:
        params = SegmentParams()
    out = RegionSet()
    try:
        params = adapt_coarse_segment_params(mv, params)
        tol = derive_tols(mv, params)
        work = _SegmentWork()
        # A1 charts
        if not _charts_a1(mv, tol, work):
            return None
        # A2 provisional plane growth (running PCA per chart; TOTAL partition)
        if not _grow_provisional_a2(mv, tol, work):
            return None
        # L law-band claim (M3b). refit_segment.cpp:47 runs this BEFORE B1 and A3:
        # a coarsely tessellated arc reads as a fan of near-coplanar facets, so
        # plane growing will commit it unless the law claims it first.
        if not _claim_law_bands_l(mv, tol, work):
            return None
        # B1 cylinder claim (M3a): seeds provisional pairs, grows members, runs the
        # G1-G5 gate chain and fills the reject census.
        if not _claim_cylinders_b1(mv, tol, work):
            return None
        # A3 plane commit
        if not _commit_planes_a3(mv, tol, work):
            return None
        # D topology
        if not _build_topology_d(mv, tol, work, out):
            return None
    except Exception:  # noqa: BLE001 - port of the reference's catch-all guard
        return None
    return out
