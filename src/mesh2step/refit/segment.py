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
from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np
from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt

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


@dataclass
class SegmentParams:
    """Port of refit::SegmentParams at the golden defaults.

    eps_mesh / eps_plane are in mm, 0 => auto-derive from the MeshView
    (refit_segment.cpp deriveTols). Angles in degrees.
    """
    eps_mesh: float = 0.0
    eps_plane: float = 0.0        # Options::smoothTolMM (0 = auto)
    theta_plane_deg: float = 2.0  # Options::smoothAngleDeg
    theta_sharp_deg: float = 30.0
    do_fillets: bool = True       # Options::smoothFillets


@dataclass
class DerivedTols:
    eps_mesh: float = 0.0
    eps_plane: float = 0.0
    theta_plane: float = 0.0      # radians
    theta_sharp: float = 0.0
    theta_cyl_lo: float = 0.0
    theta_cyl_hi: float = 0.0
    theta_bin: float = 0.0


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


# --- tolerance derivation (refit_segment.cpp deriveTols, verbatim) -------------

def coarse_fusion_band(mv: MeshView) -> bool:
    return 500 <= mv.n_tri <= 1200


def derive_tols(mv: MeshView, p: SegmentParams) -> DerivedTols:
    tol = DerivedTols()
    tol.eps_mesh = p.eps_mesh if p.eps_mesh > 0.0 else max(mv.weld_tol, 1e-4 * mv.diag, 1e-3)
    tol.eps_plane = p.eps_plane if p.eps_plane > 0.0 else max(tol.eps_mesh, mv.sew_tol, 0.02)
    tol.theta_plane = math.radians(p.theta_plane_deg)
    tol.theta_sharp = math.radians(p.theta_sharp_deg)
    tol.theta_cyl_lo = math.radians(5.0)
    tol.theta_cyl_hi = math.radians(60.0)
    tol.theta_bin = math.radians(0.25)
    return tol


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


# --- A3: plane commit (refit_grow.cpp commitPlanesA3) ---------------------------

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
    for r in out.regions:
        if r.origin == Origin.FILLET_STRIP:
            st.fillets += 1
        elif r.type == SurfType.PLANE:
            st.planes += 1
        elif r.type == SurfType.CYLINDER:
            st.cylinders += 1
        max_dev = max(max_dev, r.max_vertex_dev)
        dvol += r.dvol_predicted
    st.max_vertex_dev = max_dev
    st.dvol_predicted = dvol

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
        tol = derive_tols(mv, params)
        work = _SegmentWork()
        # A1 charts
        if not _charts_a1(mv, tol, work):
            return None
        # A2 provisional plane growth (running PCA per chart; TOTAL partition)
        if not _grow_provisional_a2(mv, tol, work):
            return None
        # B1 / L / C1: cylinder, law-band and fillet claiming — M3-M5 stubs that
        # claim nothing, so every provisional is still Unclaimed here.
        # A3 plane commit
        if not _commit_planes_a3(mv, tol, work):
            return None
        # D topology
        if not _build_topology_d(mv, tol, work, out):
            return None
    except Exception:  # noqa: BLE001 - port of the reference's catch-all guard
        return None
    return out
