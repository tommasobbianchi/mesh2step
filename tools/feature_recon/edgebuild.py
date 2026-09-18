"""Shape rebuild by exact surface intersection (Mesh2Brep's mechanism), not by mesh chains.

Every mesh region is ONE fitted analytic surface (plane, cylinder, cone, sphere, torus). Every edge between two
regions is the exact intersection of their two surfaces; every corner is the exact common point of the surfaces
meeting there. The mesh only decides WHICH surfaces meet and in which order around a face; no coordinate of the
result comes from a mesh vertex. A groove crossing a hole, a fillet meeting a sphere corner, a side hole in a
tube are the same code path: the intersection of two surfaces.

1. clean + segment (regions.py), absorb unlabelled triangles into the neighbour surface they lie on;
2. fit each region, snap axes to face normals, enforce tangency / coaxiality found between neighbours exactly;
3. boundary loops per region from the oriented mesh; corners = vertices where >= 3 surfaces meet;
4. corners solved on all their surfaces; each chain between corners becomes a line, circle or interpolated
   curve through points projected exactly onto both surfaces;
5. faces = surface + wires of shared edges, sewn, solid, STEP.
usage: edgebuild.py <mesh.stl> <out.step>    prints RESULT {...} radii [...]; exit 3 = not buildable here
"""
import collections, math, os, sys, time
from pathlib import Path

if len(sys.argv) > 2 and sys.argv[1] == "--combine":
    # edgebuild.py --combine OUT.step BODY0.step BODY1.step ...: the solids of separately rebuilt bodies of one mesh (a
    # print-in-place assembly, broom holder: bar + two clip arms 0.34 mm apart) written as one STEP
    from OCP.BRep import BRep_Builder
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Reader, STEPControl_Writer
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS_Compound
    bb_c = BRep_Builder(); comp_c = TopoDS_Compound(); bb_c.MakeCompound(comp_c); n_c = 0
    for p_c in sys.argv[3:]:
        r_c = STEPControl_Reader()
        if r_c.ReadFile(p_c) != 1:
            print(f"FAIL cannot read {p_c}"); sys.exit(1)
        r_c.TransferRoots(); ex_c = TopExp_Explorer(r_c.OneShape(), TopAbs_SOLID)
        while ex_c.More():
            bb_c.Add(comp_c, ex_c.Current()); n_c += 1; ex_c.Next()
    w_c = STEPControl_Writer(); w_c.Transfer(comp_c, STEPControl_AsIs); w_c.Write(sys.argv[2])
    print(f"COMBINED {n_c}"); sys.exit(0)

import numpy as np
import trimesh

REPO = Path.home() / "projects/mesh2step"
sys.path[:0] = [str(REPO / "src"), str(REPO / "tools/feature_recon")]
os.environ.setdefault("REGION_TOL", "3e-4")
from regions import regions, fit_smooth, fit_revolution  # noqa: E402
from slice import fit_circle  # noqa: E402
from mesh2step.feature import _mesh, measure  # noqa: E402

T0 = time.time()
log = lambda *a: print(*a, flush=True)  # noqa: E731
if os.environ.get("EB_TIMING"):
    # elapsed seconds on every log line, to see where a large part spends its time (never set by the service, which
    # parses lines starting with RESULT)
    log = lambda *a: print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)  # noqa: E731


def fail(msg):
    print("FAIL " + msg, flush=True)
    print("FAIL " + msg, file=sys.stderr, flush=True)
    sys.exit(3)


src, out = Path(sys.argv[1]), Path(sys.argv[2])

# ---------------------------------------------------------------- 1. clean + segment
m = trimesh.load(src, process=False)
V0 = m.vertices[m.faces.reshape(-1)]
diag = float(np.linalg.norm(V0.max(0) - V0.min(0)))
key = np.round(V0 / (float(os.environ.get("EB_WELD", "1.5e-4")) * diag)).astype(np.int64)   # EB_WELD: probe rung
_, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
F0 = inv.reshape(-1, 3)
# (an automatic finer weld whenever the 1.5e-4 weld left an edge used more than twice was tried 2026-09-15 and removed:
# it fired on meshes that built fine at 1.5e-4 and broke the tube50 lid body 0 (8 free edges, dV -160 %) and the broom
# holder body 2 (2 corners). A mesh that really is open at 1.5e-4 gets EB_WELD=1e-5 from the probe's "open" rung.)
keep = np.logical_and.reduce([F0[:, 0] != F0[:, 1], F0[:, 1] != F0[:, 2], F0[:, 0] != F0[:, 2]])
bodies_ = sorted(trimesh.Trimesh(V0[first], F0[keep], process=True).split(only_watertight=False), key=lambda p: -abs(p.volume))
if os.environ.get("EB_COUNT_BODIES"):
    # the service asks first: a mesh of several closed bodies (a print-in-place assembly) is rebuilt body by body
    print(f"BODIES {len(bodies_)}", flush=True); sys.exit(0)
body = bodies_[int(os.environ.get("EB_BODY", "0"))]
if not body.is_watertight:
    # a T-junction (mechparts/35: a vertex at z 2.5 in the middle of the other side's edge from z 0 to 5, 3 boundary edges
    # in 31,013 triangles) is closed exactly by splitting the triangle that owns the long edge at that vertex
    Fb = body.faces.copy(); Vb = body.vertices
    eb_ = np.sort(np.concatenate([Fb[:, [0, 1]], Fb[:, [1, 2]], Fb[:, [2, 0]]]), axis=1)
    ue_, ce_ = np.unique(eb_, axis=0, return_counts=True); bnd_ = ue_[ce_ == 1]
    bverts_ = np.unique(bnd_); n_tj = 0; new_faces = []; drop_ = set()
    for a_, b_ in bnd_:
        seg_ = Vb[b_] - Vb[a_]; len_ = float(np.linalg.norm(seg_))
        if len_ == 0:
            continue
        for c_ in bverts_:
            if c_ in (a_, b_):
                continue
            t_ = float((Vb[c_] - Vb[a_]) @ seg_) / len_ ** 2
            if 1e-6 < t_ < 1 - 1e-6 and float(np.linalg.norm(Vb[a_] + t_ * seg_ - Vb[c_])) < 1e-9 * max(1.0, len_):
                for fi_, f_ in enumerate(Fb):
                    if fi_ in drop_:
                        continue
                    for k_ in range(3):
                        if {f_[k_], f_[(k_ + 1) % 3]} == {a_, b_}:
                            p_, q_, r_ = f_[k_], f_[(k_ + 1) % 3], f_[(k_ + 2) % 3]
                            new_faces += [[p_, c_, r_], [c_, q_, r_]]; drop_.add(fi_); n_tj += 1
                            break
                break
    if n_tj:
        body = trimesh.Trimesh(Vb, np.vstack([np.delete(Fb, sorted(drop_), axis=0), np.array(new_faces)]), process=False)
        log(f"{n_tj} T-junctions closed by splitting the triangle at the vertex on its edge; watertight {body.is_watertight}")
r = regions(body.triangles)
V, F = r["topology"][0], r["topology"][1]
label = np.array(r["label"]).copy()
kinds = list(r["kinds"])
tri = V[F]
nt = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); area = np.linalg.norm(nt, axis=1) / 2
nt = nt / np.maximum(2 * area[:, None], 1e-30)
log(f"mesh {len(F)} tris, regions {collections.Counter(kinds)}, unlabelled {int((label < 0).sum())}")

E = collections.defaultdict(list)
for t, (a, b, c) in enumerate(F):
    for x, y in ((a, b), (b, c), (c, a)):
        E[(min(x, y), max(x, y))].append(t)
if any(len(ts) != 2 for ts in E.values()):
    fail("mesh is open or non-manifold")


def other(t, x, y):
    ts = E[(min(x, y), max(x, y))]
    return ts[0] if ts[1] == t else ts[1]


# ---------------------------------------------------------------- 2. surfaces
def frame(a):
    u = np.cross(a, [1.0, 0, 0] if abs(a[0]) < 0.9 else [0, 1.0, 0]); u /= np.linalg.norm(u)
    return u, np.cross(a, u)


def sdist(s, P):
    """Signed distance, positive on the side the surface normal points to."""
    if not isinstance(P, np.ndarray) or P.ndim != 2:
        P = np.atleast_2d(P)
    k = s["kind"]
    if k == "plane":
        return P @ s["n"] - s["d"]
    if k == "sphere":
        return np.linalg.norm(P - s["c"], axis=1) - s["R"]
    # h[:, None] * a is np.outer(h, a) without its ravel/copy overhead (38 s of mechparts/20), bit for bit the same product
    q = P - s["o"]; h = q @ s["a"]; rho = np.linalg.norm(q - h[:, None] * s["a"], axis=1)
    if k == "cylinder":
        return rho - s["R"]
    if k == "cone":
        return (rho - (s["k0"] * h + s["k1"])) / math.sqrt(1 + s["k0"] ** 2)
    return np.hypot(h - s["hc"], rho - s["major"]) - s["minor"]


EPS = 1e-6 * diag


def sgrad(s, P):
    P = np.atleast_2d(P); g = np.zeros_like(P)
    for i in range(3):
        e = np.zeros(3); e[i] = EPS
        g[:, i] = (sdist(s, P + e) - sdist(s, P - e)) / (2 * EPS)
    return g


def set_axis(s, a):
    s["a"] = a / np.linalg.norm(a); s["u"], s["w"] = frame(s["a"])


def to_vec(s):
    if s["kind"] == "sphere":
        return np.r_[s["c"], s["R"]]
    cu, cw = s["o"] @ s["u"], s["o"] @ s["w"]
    return np.array({"cylinder": [cu, cw, s.get("R")], "cone": [cu, cw, s.get("k0"), s.get("k1")],
                     "torus": [cu, cw, s.get("hc"), s.get("major"), s.get("minor")]}[s["kind"]], float)


def from_vec(s, x):
    t = dict(s)
    if s["kind"] == "sphere":
        t["c"], t["R"] = np.array(x[:3]), float(x[3]); return t
    t["o"] = x[0] * s["u"] + x[1] * s["w"]
    names = {"cylinder": ["R"], "cone": ["k0", "k1"], "torus": ["hc", "major", "minor"]}[s["kind"]]
    for nm, v in zip(names, x[2:]):
        t[nm] = float(v)
    return t


def jac(fun, x, m_):
    # central differences. (Tried 2026-09-15: forward differences halved the evaluations but shifted fits enough that
    # the known-axis refit ran on 357 regions instead of 93 on mechparts/1: no net speed-up, so reverted.)
    J = np.zeros((m_, len(x)))
    for j in range(len(x)):
        dx = np.zeros(len(x)); dx[j] = 1e-7 * max(1.0, abs(x[j]))
        J[:, j] = (fun(x + dx) - fun(x - dx)) / (2 * dx[j])
    return J


def refine(s, P, cons=(), fit=True):
    """Least squares on the region's vertices (they lie ON the true surface), then the smallest parameter change
    that satisfies the tangency / coaxiality constraints exactly. fit=False: the projection alone."""
    if s["kind"] == "plane":
        return s
    x = to_vec(s)
    P_all = P
    for _trim in range(4 if fit else 0):
        res = lambda x_: sdist(from_vec(s, x_), P)  # noqa: E731
        for _ in range(12):
            rr = res(x)
            if float(np.abs(rr).max()) < 1e-9 * diag:
                break        # already on the vertices: the numeric Jacobian was 119 of 150 s on mechparts/7
            step = np.linalg.lstsq(jac(res, x, len(rr)), -rr, rcond=None)[0]; x = x + step
            if np.linalg.norm(step) < 1e-13 * diag:
                break
        # tessellation vertices lie ON the true surface: a few far off it are a neighbour's triangles (gearbox:
        # 8 of 32 round vertices sat on the tangent top face, R 3.006-3.008 for 3.000). A median-based cut fails
        # when the median itself is dragged, so trim by quantile: refit on the best 70 %, then take back every
        # vertex that lies on that surface.
        r_all = np.abs(sdist(from_vec(s, x), P_all))
        if float(r_all.max()) < 1e-6 * diag or len(P_all) < 8:
            break
        if _trim == 0:
            keep = r_all <= np.quantile(r_all, 0.7)
        else:
            keep = r_all <= 1e-5 * diag
            if keep.sum() < max(4, 0.6 * len(P_all)) or keep.sum() == len(P):
                break
        P = P_all[keep]
    if cons:
        g = lambda x_: np.array([c(from_vec(s, x_)) for c in cons])  # noqa: E731
        for _ in range(30):
            rr = g(x)
            if np.abs(rr).max() < 1e-13 * diag:
                break
            # truncated like project(): two tangencies to ONE axis (slot end R 2.5 between coaxial walls R 33.8 and
            # R 28.8, mechparts/30) are two parallel rows whose targets differ by 7e-5; the untruncated solve divided
            # that by the noise singular value and slid the cylinder 8 mm around the axis
            x = x + np.linalg.lstsq(jac(g, x, len(rr)), -rr, rcond=1e-6)[0]
        if s["kind"] == "cone" and fit and P is not None and len(P) >= 4 and not os.environ.get("EB_NO_CONE_REFIT"):
            # the free fit slides a narrow cone's origin across its band (a 2 mm 45-degree chamfer: 7.1e-4) and the
            # coaxial projection above moves only the origin back, so k1 stays 7.2e-4 short of the cylinder rim it
            # meets (mechparts/31: 6 corners at 2.6e-4; DeepSeek review, verified). Refit on the vertices inside the
            # constraints' null space, re-projecting after each step.
            res_c = lambda x_: sdist(from_vec(s, x_), P)  # noqa: E731
            for _ in range(8):
                G_ = jac(g, x, len(cons)); _, sv_, Vt_ = np.linalg.svd(G_)
                rank_ = int((sv_ > 1e-9 * max(float(sv_.max()), 1e-300)).sum())
                N_ = Vt_[rank_:].T
                if N_.shape[1] == 0:
                    break
                rr_c = res_c(x); step_ = N_ @ np.linalg.lstsq(jac(res_c, x, len(rr_c)) @ N_, -rr_c, rcond=None)[0]
                x = x + step_
                for _p in range(10):
                    rr = g(x)
                    if np.abs(rr).max() < 1e-13 * diag:
                        break
                    x = x + np.linalg.lstsq(jac(g, x, len(rr)), -rr, rcond=1e-6)[0]
                if np.linalg.norm(step_) < 1e-13 * diag:
                    break
    return from_vec(s, x)


def region_tris(L):
    return np.where(label == L)[0]


def region_verts(L):
    return V[np.unique(F[label == L])]


def refit_keep(s, P):
    """refine() but, with EB_REFIT_GUARD, never leave a surface fitting its vertices worse than before (mechparts/20:
    a 10-triangle cone the merge/mixed passes grew blew up to k0 3e17, 2.4 off its own vertices, 2 corners unsolvable)."""
    new = refine(s, P)
    if os.environ.get("EB_REFIT_GUARD") and float(np.abs(sdist(new, P)).max()) > float(np.abs(sdist(s, P)).max()) + 1e-9 * diag:
        return s
    return new


def fit(L):
    ts = region_tris(L); P = region_verts(L); k = kinds[L]
    if k == "plane":
        c = P.mean(0); n = np.linalg.svd(P - c)[2][-1]
        if n @ (nt[ts] * area[ts, None]).sum(0) < 0:
            n = -n
        return {"kind": "plane", "n": n, "d": float(n @ c)}
    if k == "sphere":
        A_ = np.c_[2 * P, np.ones(len(P))]; sol = np.linalg.lstsq(A_, (P ** 2).sum(1), rcond=None)[0]
        return {"kind": "sphere", "c": sol[:3], "R": float(math.sqrt(max(sol[3] + sol[:3] @ sol[:3], 0.0)))}
    if k == "cylinder":
        N = nt[ts]; a = np.linalg.eigh((N * area[ts, None]).T @ N)[1][:, 0]
        s = {"kind": "cylinder"}; set_axis(s, a)
        c2, R, _ = fit_circle(np.c_[P @ s["u"], P @ s["w"]])
        s["o"] = c2[0] * s["u"] + c2[1] * s["w"]; s["R"] = float(R)
        return s
    big = 0.05 * diag
    mdl = (fit_smooth if k == "cone" else fit_revolution)(list(ts), V, F, nt, area, big)
    if mdl is None or mdl[0] != k:
        return None
    if k == "cone":
        a, c, kk = mdl[2]; k0, k1 = float(kk[0]), float(kk[1])
        if k0 < 0:
            a, k0 = -a, -k0
        s = {"kind": "cone"}; set_axis(s, a)
        off = float(c @ s["a"]); s["o"] = c - off * s["a"]; s["k0"] = k0; s["k1"] = k1 - k0 * off
        return s
    a, c, cc = mdl[2]
    s = {"kind": "torus"}; set_axis(s, a)
    off = float(c @ s["a"]); s["o"] = c - off * s["a"]; s["hc"] = float(cc[0]) + off
    s["major"] = float(cc[1]); s["minor"] = float(mdl[1][1])
    return s


def all_labels():
    return sorted(set(label[label >= 0].tolist()))


S = {}
n_unfit = 0
for L in all_labels():
    s = fit(L)
    if s is None:
        # the free-axis fit cannot name it (mechparts/29, /31: 14- and 26-triangle 45-degree cone bands read as a
        # cylinder R 124-147). Hand the triangles to the unlabelled pass, which fits about the known machining axes.
        label[label == L] = -1; n_unfit += 1
        continue
    S[L] = s if s["kind"] == "plane" else refine(s, region_verts(L))

# a triangle of a curved region lying entirely ON an adjacent plane belongs to that plane: where a plane is
# tangent to a round, regions.py hands it the plane's triangles (gearbox: 8 of 32 round vertices sat on the top
# face around the R2 holes and dragged the rounds to R 3.006-3.008)
n_moved = 0
# OFF by default: on L10_gearbox it also stripped the round's own tangent-line triangles and left 7 free edges
# (second opinion, DeepSeek, confirmed: off -> 0 free edges, 12 cylinders); it changed no cadbench count elsewhere.
for L in ([L for L, s in S.items() if s["kind"] != "plane"] if os.environ.get("EB_PLANE_RELABEL") else []):
    ts = region_tris(L); moved = []
    for t in ts:
        for i in range(3):
            u_ = other(t, F[t][i], F[t][(i + 1) % 3]); M = int(label[u_])
            if M >= 0 and M in S and S[M]["kind"] == "plane":
                if (np.abs(sdist(S[M], V[F[t]])).max() < 1e-5 * diag and float(nt[t] @ S[M]["n"]) > 0.99999):
                    label[t] = M; moved.append(t); break
    if moved:
        n_moved += len(moved)
        if (label == L).sum() >= 3:
            s_new = fit(L)
            if s_new is not None:
                S[L] = refine(s_new, region_verts(L))
        else:
            del S[L]
if n_moved:
    log(f"{n_moved} plane triangles moved out of curved regions")
    # moving them can cut a region in two (gearbox: a round split by a hole rim): each piece is its own face
    for L in [L for L, s in S.items() if s["kind"] != "plane"]:
        ts = set(region_tris(L).tolist()); pieces = []
        while ts:
            st = [ts.pop()]; comp = []
            while st:
                t = st.pop(); comp.append(t)
                for i in range(3):
                    u_ = other(t, F[t][i], F[t][(i + 1) % 3])
                    if u_ in ts:
                        ts.remove(u_); st.append(u_)
            pieces.append(comp)
        for comp in sorted(pieces, key=len)[:-1]:
            newL = len(kinds); kinds.append(S[L]["kind"]); label[comp] = newL; S[newL] = dict(S[L])
            if len(comp) >= 3:
                S[newL] = refine(S[newL], V[np.unique(F[comp])])

# a curved region must hug and face its surface; flat facets that merely have their vertices on one sphere
# (chamfered cube: 20 chamfer faces on the circumscribed sphere) are split back into planes
_split_facets = set()             # plane labels born from a split, absorbable later
for L in list(S):
    s = S[L]
    if s["kind"] == "plane":
        continue
    ts = region_tris(L); cen_ = tri[ts].mean(1)
    g_ = sgrad(s, cen_); g_ /= np.maximum(np.linalg.norm(g_, axis=1, keepdims=True), 1e-300)
    sizes_ = [s.get(k_) for k_ in ("R", "major", "minor") if s.get(k_) is not None]
    # the simplest surface wins: a narrow flat strip also fits a curved surface within tolerance (broom holder logo: a
    # 7-triangle wall strip as a cylinder, refit later as an R 19.6 sphere, its corners 0.13 mm apart)
    Pv_f = V[np.unique(F[ts])]; c_f = Pv_f.mean(0); n_f = np.linalg.svd(Pv_f - c_f)[2][-1]
    flat_ = len(Pv_f) >= 3 and float(np.abs((Pv_f - c_f) @ n_f).max()) < 1e-6 * diag
    if (not flat_ and np.abs(sdist(s, cen_)).max() < 5e-3 * diag and all(0 < z_ < diag for z_ in sizes_)
            and np.abs(np.einsum("ij,ij->i", g_, nt[ts])).min() > math.cos(math.radians(20))):
        continue
    if os.environ.get("EB_DUMP_TRIS") and str(L) in os.environ["EB_DUMP_TRIS"].split(","):
        # what a rejected curved region is made of: facet normal directions and where its triangles sit
        ang_ = np.degrees(np.arctan2(nt[ts][:, 2], nt[ts][:, 0])); ny_ = nt[ts][:, 1] / np.maximum(np.linalg.norm(nt[ts], axis=1), 1e-300)
        log(f"  TRIS S{L}: axis {np.round(s.get('a', np.zeros(3)), 4).tolist()} o {np.round(s.get('o', np.zeros(3)), 4).tolist()} "
            f"R {s.get('R')}, normal y-component range {ny_.min():+.3f}..{ny_.max():+.3f}, centroid box "
            f"{np.round(cen_.min(0), 3).tolist()}..{np.round(cen_.max(0), 3).tolist()}")
        for a0 in range(-180, 180, 15):
            sel_ = np.where(np.logical_and(ang_ >= a0, ang_ < a0 + 15))[0]
            if len(sel_):
                log(f"    normal xz-angle {a0:+4d}..{a0 + 15:+4d}: {len(sel_):3d} tris, centroid box "
                    f"{np.round(cen_[sel_].min(0), 3).tolist()}..{np.round(cen_[sel_].max(0), 3).tolist()}, "
                    f"surface distance max {float(np.abs(sdist(s, cen_[sel_])).max()):.2e}")
    if os.environ.get("EB_DEBUG"):
        log(f"  flat-facet test S{L} ({s['kind']}, {len(ts)} tris, sizes {[round(float(z_), 4) for z_ in sizes_]}): centroid distance max "
            f"{float(np.abs(sdist(s, cen_)).max()):.2e} (limit {5e-3 * diag:.2e}), worst facing angle "
            f"{math.degrees(math.acos(min(1.0, float(np.abs(np.einsum('ij,ij->i', g_, nt[ts])).min())))):.1f} deg (limit 20)")
    del S[L]; tset = set(ts.tolist()); seen_t = set()
    fgroups = []                      # coplanar facet groups of the rejected region
    for t0 in ts:
        if t0 in seen_t:
            continue
        grp = []; stack = [t0]; seen_t.add(t0)
        while stack:
            t = stack.pop(); grp.append(t)
            for i in range(3):
                u = other(t, F[t][i], F[t][(i + 1) % 3])
                if u in tset and u not in seen_t and nt[t] @ nt[u] > 0.99999:
                    seen_t.add(u); stack.append(u)
        fgroups.append(grp)
    # opt-in probe rung: a finely tessellated curved region (under 3 triangles per coplanar group) whose one fit failed is
    # several merged curved surfaces, not flat facets (mechparts/20: 961-triangle "sphere" facing its facets at 57 deg;
    # splitting it gave 83 facet planes and 28 corners that cannot meet). Hand it to the known-axis unlabelled pass.
    if (os.environ.get("EB_CURVED_UNLABEL") and len(ts) < 3 * len(fgroups)
            and all(z_ < 0.5 * diag for z_ in sizes_)):
        label[ts] = -1
        log(f"region {L} ({s['kind']}) is a poorly fitted curved region, left to the known-axis pass")
        continue
    # a rejected region can be SEVERAL small rounds plus flat strips (broom holder logo: two R ~0.35 corner fillets and the
    # walls between them fitted as one R 5.4 cylinder). When every facet runs along the region's axis, grow runs of
    # adjacent facet groups that one circle about that axis fits; a run of three or more facets is a cylinder face.
    in_cyl = set(); n_rounds = 0
    # (tried 2026-09-15 and reverted: taking each run's axis from its own facet normals instead of the region axis
    # moved mechparts/1 from sound to a failed torus-cylinder edge and made no part sound)
    a_ax = s.get("a") if s["kind"] == "cylinder" else None
    if a_ax is not None and float(np.abs(nt[ts] @ a_ax).max()) < 0.02 and len(fgroups) >= 3:
        u_ax, w_ax = frame(a_ax)
        g_of = {t: gi for gi, g in enumerate(fgroups) for t in g}
        g_adj = collections.defaultdict(set)
        for t in ts:
            for i in range(3):
                u = other(t, F[t][i], F[t][(i + 1) % 3])
                if u in tset and g_of[u] != g_of[t]:
                    g_adj[g_of[t]].add(g_of[u])
        used_g = set()
        for gi in range(len(fgroups)):
            if gi in used_g:
                continue
            run = [gi]; frontier = [gi]
            while frontier:
                gj = frontier.pop()
                for gk in sorted(g_adj[gj]):
                    if gk in used_g or gk in run:
                        continue
                    # neighbouring facets of a round turn by a few degrees, not by a corner's 90
                    if float(nt[fgroups[gj][0]] @ nt[fgroups[gk][0]]) < math.cos(math.radians(30)):
                        continue
                    trial = run + [gk]
                    Pr = V[np.unique(F[[t for g in trial for t in fgroups[g]]])]
                    if len(trial) >= 3:
                        c2r, Rr, _ = fit_circle(np.c_[Pr @ u_ax, Pr @ w_ax])
                        if not (0 < Rr < diag) or float(np.abs(np.linalg.norm(np.c_[Pr @ u_ax, Pr @ w_ax] - c2r, axis=1) - Rr).max()) > 1e-5 * diag:
                            continue
                    run.append(gk); frontier.append(gk)
            # a round must actually turn: a near-straight run of facets fits any circle (broom holder logo: a leftover
            # run became an R 19.6 "sphere" strip; DeepSeek review, verified). Require a 15-degree normal sweep.
            nrm_r = np.array([nt[fgroups[g][0]] for g in run])
            if len(run) >= 3 and float((nrm_r @ nrm_r.T).min()) < math.cos(math.radians(15)):
                tris_r = [t for g in run for t in fgroups[g]]
                Pr = V[np.unique(F[tris_r])]; c2r, Rr, _ = fit_circle(np.c_[Pr @ u_ax, Pr @ w_ax])
                newL = len(kinds); kinds.append("cylinder"); label[tris_r] = newL
                sc = {"kind": "cylinder"}; set_axis(sc, a_ax); sc["o"] = c2r[0] * sc["u"] + c2r[1] * sc["w"]; sc["R"] = float(Rr)
                S[newL] = refine(sc, Pr); used_g.update(run); in_cyl.update(tris_r); n_rounds += 1
    for grp in fgroups:
        if grp[0] in in_cyl:
            continue
        newL = len(kinds); kinds.append("plane"); label[grp] = newL
        S[newL] = fit(newL)
        # these planes are ORPHANS -- facets of a curved surface whose identity was just
        # deleted, not flat faces of the part. Only they may be absorbed later
        # (EB_ABSORB_FACETS); absorbing every plane instead ate the part's genuine flat
        # faces and left 13 surfaces with dist_p95 6.86 mm.
        _split_facets.add(newL)
    log(f"region {L} ({s['kind']}) is flat facets, split into planes" + (f" and {n_rounds} small rounds" if n_rounds else ""))

# surfaces of revolution about a KNOWN machining axis: a face normal or the axis of a fitted cylinder/cone.
# A free-axis fit of a small or narrow patch is ill-posed (a 7-triangle chamfer strip around a fillet fits a
# tilted cylinder); with the axis direction given, the normal lines meeting it fix the rest.
KIND_RANK = {"cylinder": 0, "cone": 1, "sphere": 2, "torus": 3}


def axis_candidates():
    cands = []
    # one pass for every region's area: scanning all triangles once PER region was 9.8 s in a single call (mechparts/1)
    lab_ok = label >= 0
    area_by_label = np.bincount(label[lab_ok], weights=area[lab_ok], minlength=int(label.max()) + 1) if lab_ok.any() else np.zeros(1)
    # the pure-Python scan of every region against every candidate so far was 76 of 236 s of mechparts/19 (21k facet-plane
    # regions). A numpy product over all candidate directions only PRE-filters (looser threshold, so it can only admit
    # more); each survivor is then decided by the original scalar test in insertion order, so the list is identical.
    D_ = np.empty((max(16, len(S)), 3)); n_c = 0
    for L_, s_ in S.items():
        w_ = float(area_by_label[L_]) if 0 <= L_ < len(area_by_label) else 0.0
        d_, p_ = (s_["n"], None) if s_["kind"] == "plane" else (s_.get("a"), s_.get("o"))
        if d_ is None:
            continue
        for i_ in (np.nonzero(np.abs(D_[:n_c] @ d_) > 0.99998)[0] if n_c else ()):
            c_ = cands[i_]
            if abs(c_[0] @ d_) > 0.99999 and (p_ is None) == (c_[1] is None) and (
                    p_ is None or np.linalg.norm(np.cross(p_ - c_[1], d_)) < 1e-6 * diag):
                c_[2] += w_; break
        else:
            cands.append([d_ / np.linalg.norm(d_), p_, w_]); D_[n_c] = cands[-1][0]; n_c += 1
    return sorted(cands, key=lambda c_: -c_[2])[:24]


def fit_axis(ts, d, p=None):
    P = V[np.unique(F[ts])]; X = tri[ts].mean(1); N = nt[ts]
    u, w = frame(d)
    if p is None:
        m_ = np.cross(N, d); A_ = np.c_[m_ @ u, m_ @ w] * area[ts, None]; b_ = np.einsum("ij,ij->i", m_, X) * area[ts]
        if np.linalg.svd(A_, compute_uv=False)[-1] < 1e-9 * max(1.0, float(np.abs(A_).max())):
            return []
        cu, cw = np.linalg.lstsq(A_, b_, rcond=None)[0]
    else:
        cu, cw = float(p @ u), float(p @ w)
    o = cu * u + cw * w; q = P - o; h = q @ d; rho = np.linalg.norm(q - np.outer(h, d), axis=1)
    out = [{"kind": "cylinder", "a": d, "u": u, "w": w, "o": o, "R": float(np.median(rho))}]
    if np.ptp(h) > 1e-6 * diag:
        k0, k1 = np.polyfit(h, rho, 1)
        if abs(k0) > 1e-3:
            s_ = {"kind": "cone"}; set_axis(s_, d if k0 > 0 else -d)
            s_["o"] = o; s_["k0"] = abs(float(k0)); s_["k1"] = float(k1); out.append(s_)
    if len(P) >= 3:
        c2, r_, _ = fit_circle(np.c_[h, rho])
        if abs(c2[1]) < 1e-3 * diag:
            out.append({"kind": "sphere", "c": o + d * c2[0], "R": float(r_)})
        elif r_ < diag:
            out.append({"kind": "torus", "a": d, "u": u, "w": w, "o": o, "hc": float(c2[0]), "major": float(c2[1]), "minor": float(r_)})
    return out


def surface_ok(s_, ts):
    P = V[np.unique(F[ts])]; cen = tri[ts].mean(1)
    res = float(np.abs(sdist(s_, P)).max())
    g = sgrad(s_, cen); g /= np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-300)
    # a surface larger than the part is a flat patch in disguise (guide block: a plane fit as a cylinder R 1.1e6)
    sizes = [s_.get(k_) for k_ in ("R", "major", "minor") if s_.get(k_) is not None]
    if any(not (0 < z_ < diag) for z_ in sizes):
        return False, float("inf")
    if s_["kind"] == "cone" and os.environ.get("EB_REFIT_GUARD") and not (0 < abs(s_.get("k0", 0.0)) < 1e3):
        # a nearly flat patch fits a cone of half-angle ~90 deg or an apex at infinity (mechparts/20: k0 3.3e17). It is a
        # cylinder/plane in disguise; keeping it as a cone let a later refit diverge and left 2 corners unsolvable.
        return False, float("inf")
    ok = (res < 1e-5 * diag and float(np.abs(sdist(s_, cen)).max()) < 2e-3 * diag
          and float(np.abs(np.einsum("ij,ij->i", g, nt[ts])).min()) > math.cos(math.radians(20)))
    return ok, res


def best_axis_fit(ts, cands):
    best = None
    for d_, p_, _ in cands:
        for p_try in ([p_, None] if p_ is not None else [None]):
            for s0 in fit_axis(ts, d_, p_try):
                # the closed-form candidate on the RIGHT axis is already within a hair of the vertices; a wrong
                # axis or kind is off by a visible amount. Only near-fits pay for a refine.
                try:
                    if float(np.abs(sdist(s0, V[np.unique(F[ts])])).max()) > 1e-3 * diag:
                        continue
                except Exception:  # noqa: BLE001 - a candidate, not a result
                    continue
                try:
                    s1 = refine(s0, V[np.unique(F[ts])]) if s0["kind"] != "sphere" else refine(s0, V[np.unique(F[ts])])
                except Exception:  # noqa: BLE001 - a candidate, not a result
                    continue
                ok, res = surface_ok(s1, ts)
                if ok and (best is None or (KIND_RANK[s1["kind"]], res) < (KIND_RANK[best["kind"]], best["_res"])):
                    best = dict(s1, _res=res)
    if best is not None:
        best.pop("_res")
    return best


cands0 = axis_candidates()
n_axis_refit = 0
for L in [L for L, s in S.items() if s["kind"] != "plane"]:
    ts = region_tris(L); ok, _ = surface_ok(S[L], ts)
    aligned = S[L]["kind"] == "sphere" or any(abs(abs(S[L]["a"] @ c_[0]) - 1) < 1e-9 for c_ in cands0)
    if ok and aligned:
        continue
    b = best_axis_fit(ts, cands0)
    # OPT-IN (EB_STRIP_SPLIT=1, a probe rung): on by default it split genuine rounds on parts that were sound (broom holder
    # body 2: 37 -> 36 cylinders; mechparts/10: 46 -> 54 faces; the tube50 lid body 0 failed 6 corners). Bisected 2026-09-15.
    if b is None and not ok and S[L]["kind"] != "sphere" and len(ts) >= 6 and os.environ.get("EB_STRIP_SPLIT"):
        # no one surface fits: a chamfer strip running along a straight edge and round an arc end is flat facets plus
        # a cone about the arc's axis (mechparts/30: strip S26 misses its own tilted-cylinder fit and the best cone about
        # the vertical axis by 3.8e-2). Split it into coplanar facet groups, grow runs of adjacent groups that one cone
        # about a known axis fits, and keep the split only when every group is either in such a run or exactly flat.
        tl_ = list(ts); tset_ = set(tl_); gid_ = {}; groups_ = []
        for t0_ in tl_:
            if t0_ in gid_:
                continue
            g_ = [t0_]; gid_[t0_] = len(groups_); st_ = [t0_]
            while st_:
                t_ = st_.pop()
                for i_ in range(3):
                    u_ = other(t_, F[t_][i_], F[t_][(i_ + 1) % 3])
                    if u_ in tset_ and u_ not in gid_ and float(nt[t_] @ nt[u_]) > 1 - 1e-6:
                        gid_[u_] = len(groups_); g_.append(u_); st_.append(u_)
            groups_.append(g_)
        gadj_ = collections.defaultdict(set)
        for t_ in tl_:
            for i_ in range(3):
                u_ = other(t_, F[t_][i_], F[t_][(i_ + 1) % 3])
                if u_ in tset_ and gid_[u_] != gid_[t_]:
                    gadj_[gid_[t_]].add(gid_[u_])
        runs_ = []; used_ = set()
        if len(groups_) >= 3:
            for d_c, p_c, _ in cands0:
                for g0_ in range(len(groups_)):
                    if g0_ in used_:
                        continue
                    run_ = [g0_]; front_ = [g0_]; best_s = None
                    while front_:
                        gj_ = front_.pop()
                        for gk_ in sorted(gadj_[gj_]):
                            if gk_ in used_ or gk_ in run_:
                                continue
                            trial_ = run_ + [gk_]
                            tt_ = [t_ for g_ in trial_ for t_ in groups_[g_]]
                            if len(trial_) < 3:
                                run_.append(gk_); front_.append(gk_); continue
                            cone_ = next((c_ for c_ in fit_axis(tt_, d_c, p_c) if c_["kind"] == "cone"), None)
                            if cone_ is None:
                                continue
                            try:
                                cone_ = refine(cone_, V[np.unique(F[tt_])])
                            except Exception:  # noqa: BLE001 - a candidate, not a result
                                continue
                            ok_c, _ = surface_ok(cone_, tt_)
                            if ok_c:
                                run_.append(gk_); front_.append(gk_); best_s = cone_
                    nr_ = np.array([nt[groups_[g_][0]] for g_ in run_])
                    if best_s is not None and len(run_) >= 3 and float((nr_ @ nr_.T).min()) < math.cos(math.radians(15)):
                        runs_.append((run_, best_s)); used_.update(run_)
        rest_ = [g_ for g_ in range(len(groups_)) if g_ not in used_]
        # (a limit of 3 leftover groups of >= 2 triangles was tried and removed: it rejected every mechparts/30 strip and
        # the part fell back to 7 unsolvable corners. The small leftover planes re-merge in the later same-surface passes:
        # 30 came out 47 faces, 13 planes, 10 cones, valid, dV -0.0008 %.)
        flat_ok_ = all(len(V[np.unique(F[groups_[g_]])]) >= 3
                       and float(np.abs((V[np.unique(F[groups_[g_]])] - V[np.unique(F[groups_[g_]])].mean(0)) @ nt[groups_[g_][0]]).max()) < 1e-5 * diag
                       for g_ in rest_)
        if os.environ.get("EB_DEBUG"):
            log(f"  strip split S{L} ({S[L]['kind']}, {len(ts)} tris): {len(groups_)} facet groups, {len(runs_)} cone runs, "
                f"{len(rest_)} other groups flat {flat_ok_}")
        if runs_ and flat_ok_:
            first_ = True
            for run_, cone_ in runs_:
                tt_ = [t_ for g_ in run_ for t_ in groups_[g_]]
                newL = L if first_ else len(kinds)
                if not first_:
                    kinds.append("cone")
                kinds[newL] = "cone"; label[tt_] = newL; S[newL] = cone_; first_ = False
            for g_ in rest_:
                newL = len(kinds); kinds.append("plane"); label[groups_[g_]] = newL; S[newL] = fit(newL)
            n_axis_refit += 1
            log(f"  strip S{L} split into {len(runs_)} cone run(s) and {len(rest_)} plane(s) about known axes")
            continue
    if b is not None:
        if os.environ.get("EB_DEBUG"):
            Pv_d = V[np.unique(F[ts])]
            log(f"  axis refit S{L}: {S[L]['kind']} -> {b['kind']}, {len(ts)} tris, vertex distance max "
                f"{float(np.abs(sdist(S[L], Pv_d)).max()):.2e} -> {float(np.abs(sdist(b, Pv_d)).max()):.2e}")
        S[L] = b; kinds[L] = b["kind"]; n_axis_refit += 1
# unlabelled smooth components that are one surface about a known axis become regions (torus fillets, grooves)
free_t = set(np.where(label < 0)[0].tolist()); seen_c = set(); n_new = 0
for s0_ in sorted(free_t):
    if s0_ in seen_c:
        continue
    comp, st = [], [s0_]; seen_c.add(s0_)
    while st:
        t = st.pop(); comp.append(t)
        for i in range(3):
            u_ = other(t, F[t][i], F[t][(i + 1) % 3])
            if u_ in free_t and u_ not in seen_c and nt[t] @ nt[u_] > math.cos(math.radians(40)):
                seen_c.add(u_); st.append(u_)
    if len(comp) < 3:
        continue
    Pc = V[np.unique(F[comp])]; cc_ = Pc.mean(0); nc_ = np.linalg.svd(Pc - cc_)[2][-1]
    if np.abs((Pc - cc_) @ nc_).max() < 1e-5 * diag:
        # a flat unlabelled patch is a plane (regions.py held it back as a possible curved facet)
        newL = len(kinds); kinds.append("plane"); label[comp] = newL; S[newL] = fit(newL); n_new += 1
        continue
    b = best_axis_fit(np.array(comp), cands0)
    if b is not None:
        newL = len(kinds); kinds.append(b["kind"]); label[comp] = newL; S[newL] = b; n_new += 1
log(f"axis fits: {n_axis_refit} regions refit about a known axis, {n_new} unlabelled components became surfaces")

# ---- post-axis-refit facet absorb (EB_ABSORB_FACETS=1, default OFF) -------------------
# The flat-facet split (:372-402) dissolves a curved region into one plane per coplanar facet
# group. Those facets are orphans: they carry no surface identity, so the corner solve later
# sees N planes where ONE curved face belongs -- part 16's failing corner is torus S136 plus
# 3 facet planes of S63, i.e. 4 surface equations in 3 unknowns (project(), :1527-1541).
#
# A better per-region fit cannot fix this, and that is the measured part: S63 is 53 triangles
# spanning 2.188 mm of a 10 mm-radius meridian, and an arc that short cannot determine its own
# major radius -- best_axis_fit returns major 146.19 against a true 43.97, residual 2.86e-2 vs
# the 2.59e-3 surface_ok allows. The information is CROSS-region, so the absorb must be too.
#
# By here the identity exists: the axis-refit rung above recovers the torus from the large
# surviving patches (measured on 16: major 43.977, minor 9.999), and 2994 of 3041 facet planes
# lie on it within 1e-5*diag -- exactly the residual surface_ok accepts.
#
# The existing absorb (:851+) cannot reach these: it requires ADJACENCY, and it runs inside the
# merge loop, which has already welded the small facets into larger planar patches by then.
if os.environ.get("EB_ABSORB_FACETS") == "1":
    _curved = [L for L in all_labels() if S[L]["kind"] in ("cylinder", "cone", "sphere", "torus")]
    # ONLY the split's orphans. Absorbing every plane instead absorbed 7033 of 7069 on part 16,
    # including the part's genuine flat faces: the corner solve was fixed (28/28 at 4.2e-05,
    # against a baseline of 1 corner failing at 2.50e-03) but the model collapsed to 13 surfaces
    # and dist_p95 6.86 mm against an allowed 1.30.
    _planes = [L for L in all_labels() if S[L]["kind"] == "plane" and L in _split_facets]
    _absorbed = 0
    for _P in _planes:
        _tp = region_tris(_P)
        _Pv = region_verts(_P)
        _cen = tri[_tp].mean(1)
        _best = None
        for _C in _curved:
            # cheap gate first: the facet's MIDDLE must sit within the tessellation deflection of
            # the surface. Without it this pass is 7069 planes x 252 surfaces of full vertex work.
            if float(np.abs(sdist(S[_C], _cen)).max()) > 2e-3 * diag:
                continue
            _r = float(np.abs(sdist(S[_C], _Pv)).max())
            if _r >= 1e-5 * diag:
                continue
            # vertices alone are not enough -- a cylinder's end disk has every vertex on the rim
            # circle. The facet must also FACE the surface, the same test surface_ok applies.
            _g = sgrad(S[_C], _cen)
            _g /= np.maximum(np.linalg.norm(_g, axis=1, keepdims=True), 1e-300)
            if float(np.abs(np.einsum("ij,ij->i", _g, nt[_tp])).min()) <= math.cos(math.radians(20)):
                continue
            if _best is None or _r < _best[1]:
                _best = (_C, _r)
        if _best is not None:
            label[label == _P] = _best[0]
            del S[_P]
            _absorbed += 1
    log(f"facet absorb: {_absorbed} of {len(_planes)} planes absorbed into {len(_curved)} curved surfaces")

# unlabelled triangles join the neighbouring surface they lie on
for _ in range(50):
    changed = False
    for t in np.where(label < 0)[0]:
        cand = {int(label[u]) for u in (other(t, F[t][i], F[t][(i + 1) % 3]) for i in range(3)) if label[u] >= 0}
        if cand:
            best = min(cand, key=lambda L: float(np.abs(sdist(S[L], V[F[t]])).max()))
            if float(np.abs(sdist(S[best], V[F[t]])).max()) < 1e-3 * diag:
                label[t] = best; changed = True
    if not changed:
        break
# a connected group of unlabelled triangles that one plane fits is a flat face segmentation left out (mechparts/9:
# 8 large triangles, 2.45 % of the area, on no neighbour's surface): it becomes its own plane region
seen_u = set(); n_flat_u = 0
for t0 in np.where(label < 0)[0]:
    if t0 in seen_u:
        continue
    grp_u = []; st_u = [int(t0)]; seen_u.add(int(t0))
    while st_u:
        t = st_u.pop(); grp_u.append(t)
        for i in range(3):
            u = other(t, F[t][i], F[t][(i + 1) % 3])
            if label[u] < 0 and u not in seen_u:
                seen_u.add(u); st_u.append(u)
    Pu_ = V[np.unique(F[grp_u])]
    if len(Pu_) >= 3:
        cu_ = Pu_.mean(0); nu_ = np.linalg.svd(Pu_ - cu_)[2][-1]
        if float(np.abs((Pu_ - cu_) @ nu_).max()) < 1e-5 * diag:
            newL = len(kinds); kinds.append("plane"); label[grp_u] = newL; S[newL] = fit(newL); n_flat_u += 1
        elif os.environ.get("EB_SPLIT_UNLABELLED"):
            # EB_SPLIT_UNLABELLED probe rung: a group spanning two flat faces (mechparts/31: 45-degree chamfers along two
            # straight edges meeting at 30 degrees, 2 triangles each) fits no single plane. Split it by facet normal and
            # keep each part that is exactly flat as its own plane.
            rest_ = list(grp_u)
            while rest_:
                n0_ = nt[rest_[0]]; part_ = [t for t in rest_ if float(nt[t] @ n0_) > 1 - 1e-6]
                rest_ = [t for t in rest_ if t not in part_]
                Pp_ = V[np.unique(F[part_])]
                if len(Pp_) >= 3 and float(np.abs((Pp_ - Pp_.mean(0)) @ n0_).max()) < 1e-5 * diag:
                    newL = len(kinds); kinds.append("plane"); label[part_] = newL; S[newL] = fit(newL); n_flat_u += 1
if n_flat_u:
    log(f"{n_flat_u} flat groups of unlabelled triangles became plane regions")
if os.environ.get("EB_LEFTOVER_AXIS"):
    # EB_LEFTOVER_AXIS probe rung: the known-axis pass above fits a whole smooth component, which still holds the
    # triangles a neighbour later takes back (mechparts/17: a R 200.66 bore in 5 fragments, 374 triangles, 1.05 % of the
    # area, inside rejected mixed regions). Once the neighbours have taken theirs, each leftover group is that surface alone
    cands_u = axis_candidates(); seen_u = set(); n_curved_u = 0
    for t0 in np.where(label < 0)[0]:
        if t0 in seen_u:
            continue
        grp_u = []; st_u = [int(t0)]; seen_u.add(int(t0))
        while st_u:
            t = st_u.pop(); grp_u.append(t)
            for i in range(3):
                u = other(t, F[t][i], F[t][(i + 1) % 3])
                if label[u] < 0 and u not in seen_u:
                    seen_u.add(u); st_u.append(u)
        if len(grp_u) >= 3:
            b = best_axis_fit(np.array(grp_u), cands_u)
            if os.environ.get("EB_DEBUG"):
                Pg_ = V[np.unique(F[grp_u])]
                log(f"  leftover group {len(grp_u)} tris, box {np.round(Pg_.min(0), 2).tolist()}..{np.round(Pg_.max(0), 2).tolist()}: "
                    + (f"{b['kind']} R {b.get('R', b.get('minor'))}" if b is not None else "no known-axis fit")
                    + f"; candidate axes {[np.round(c_[0], 3).tolist() for c_ in cands_u[:8]]}")
            if b is not None:
                newL = len(kinds); kinds.append(b["kind"]); label[grp_u] = newL; S[newL] = b; n_curved_u += 1
    log(f"{n_curved_u} curved groups of unlabelled triangles became regions about a known axis")
# what is still unlabelled is a corner-fan sliver spanning several surfaces (Schlauchschelle: 2 of 1560): it
# only has to belong to a face topologically, since no coordinate of the result comes from its vertices
tot_area = float(area.sum())
for _ in range(10):
    left = np.where(label < 0)[0]
    # EB_ABSORB_AREA: loosening probe rung (mechparts/31: 16 triangles, 1.78 % of the area, in strips along two rims)
    if not len(left) or float(area[left].sum()) > float(os.environ.get("EB_ABSORB_AREA", "1e-2")) * tot_area:
        break
    for t in left:
        share = collections.Counter()
        for i in range(3):
            x, y = F[t][i], F[t][(i + 1) % 3]; u = other(t, x, y)
            if label[u] >= 0:
                share[int(label[u])] += float(np.linalg.norm(V[x] - V[y]))
        if share:
            label[t] = share.most_common(1)[0][0]
if (label < 0).any():
    if os.environ.get("EB_DUMP_UNLABELLED"):
        # the leftover triangles' corner coordinates (n x 3 x 3) and normals, to fit candidate surfaces offline
        np.savez(os.environ["EB_DUMP_UNLABELLED"], tri=tri[label < 0], normal=nt[label < 0])
    if os.environ.get("EB_DEBUG"):
        left_d = np.where(label < 0)[0]
        log(f"  UNLABELLED {len(left_d)} triangles, area {float(area[left_d].sum()):.3f} of {tot_area:.1f} "
            f"({100 * float(area[left_d].sum()) / tot_area:.2f} %), labelled neighbours per triangle "
            + str([sum(1 for i in range(3) if label[other(t, F[t][i], F[t][(i + 1) % 3])] >= 0) for t in left_d[:16]])
            + f", centroids {np.round(tri[left_d].mean(1)[:4], 2).tolist()}")
    fail(f"{int((label < 0).sum())} triangles lie on no fitted surface (freeform or unrecognised)")


def adjacency():
    adj = collections.defaultdict(set)
    for (x, y), (t1, t2) in E.items():
        if label[t1] != label[t2]:
            adj[int(label[t1])].add(int(label[t2])); adj[int(label[t2])].add(int(label[t1]))
    return adj


# axes: a machined axis is a face normal, or the line where two faces meet
plane_normals = [s["n"] for s in S.values() if s["kind"] == "plane"]
COS1, SIN1 = math.cos(math.radians(1)), math.sin(math.radians(1))
for L, s in S.items():
    if s["kind"] not in ("cylinder", "cone", "torus"):
        continue
    a = s["a"]; new = None
    for n_ in plane_normals:
        if abs(a @ n_) > COS1:
            new = n_ * np.sign(a @ n_); break
    if new is None:
        perp = [n_ for n_ in plane_normals if abs(a @ n_) < SIN1]
        crs = [np.cross(perp[i], perp[j]) for i in range(len(perp)) for j in range(i + 1, len(perp))]
        crs = [c_ / np.linalg.norm(c_) for c_ in crs if np.linalg.norm(c_) > 0.1]
        if crs:
            c_ = max(crs, key=lambda c_: abs(a @ c_)); new = c_ * np.sign(a @ c_)
    if new is not None and np.linalg.norm(new - a) > 0:
        o_pt = s["o"]; x = to_vec(s); t = dict(s); set_axis(t, new)
        t["o"] = o_pt - (o_pt @ t["a"]) * t["a"]
        Pv_a = region_verts(L)
        t = refine(t, Pv_a)
        # a snapped axis can send a near-degenerate cone's refit to infinity (mechparts/20: k0 0.021 -> 3.3e17, 2.4 off
        # its vertices). EB_REFIT_GUARD keeps the unsnapped surface when the snap fits worse.
        if (os.environ.get("EB_REFIT_GUARD")
                and float(np.abs(sdist(t, Pv_a)).max()) > float(np.abs(sdist(s, Pv_a)).max()) + 1e-9 * diag):
            t = s
        S[L] = t

# adjacent regions on one surface are one face
TOLM = 1e-4 * diag
merged = True
tried_union = set()
tried_absorb = set()
tried_same = set()
union_stats = collections.Counter()   # EB_UNION_STATS=1: which union attempts ever succeed, by the pair's kinds
fragment_cache = {}
# the adjacency map is built ONCE and patched after each merge: rebuilding it from every mesh edge on every restart of
# this loop was 1879 calls and 57 of 300 s on mechparts/1 (24k triangles). A merged-away region's neighbours pass to the
# region that absorbed it, found through one remembered triangle of the vanished region.
adj = adjacency()
rep_t = {L_: int(np.argmax(label == L_)) for L_ in S}
prev_S = set(S)
while merged:
    merged = False
    # region sizes for this scan, read by the pair keys below: (label == q).sum() per pair was 8.5M array sums, 102 s of
    # mechparts/20's default build. Exact: label changes only at a merge, and every merge ends this scan
    n_lab = np.bincount(label + 1)
    _sz = lambda q: int(n_lab[q + 1]) if 0 <= q + 1 < len(n_lab) else 0  # noqa: E731
    for g_ in prev_S - set(S):
        k_ = int(label[rep_t[g_]])
        for n_ in adj.pop(g_, set()):
            adj[n_].discard(g_)
            if n_ != k_ and k_ >= 0:
                adj[n_].add(k_); adj[k_].add(n_)
        if k_ >= 0:
            adj[k_].discard(g_); adj[k_].discard(k_)
    prev_S = set(S)
    for L in all_labels():
        for M in sorted(adj[L]):
            if S[L]["kind"] != S[M]["kind"]:
                if "plane" in (S[L]["kind"], S[M]["kind"]):
                    # a "plane" whose vertices all sit on the curved neighbour is one of its facets (coarse
                    # tessellation); left as a plane it fakes a tangency and drags the curved fit off
                    P_, C_ = (L, M) if S[L]["kind"] == "plane" else (M, L)
                else:
                    # two curved fits of ONE surface: a narrow 45-degree chamfer band reads locally as tilted
                    # cylinders (Schlauchschelle: one cone + 18 oblique "cylinders" that never meet at corners)
                    P_, C_ = sorted((L, M), key=_sz)
                # this check refit EVERY plane/curved neighbour pair on EVERY restart of the loop: 5266 refines,
                # 79 of 150 s on mechparts/7 (166 cylinders). A failed pair is not retried until a region changes,
                # and only a smaller region already lying near the larger surface pays for the refit.
                absorb_key = (P_, C_, _sz(P_), _sz(C_))
                if absorb_key in tried_absorb:
                    s2 = None
                else:
                    tried_absorb.add(absorb_key)
                    s2 = (None if float(np.abs(sdist(S[C_], region_verts(P_))).max()) > 1e-3 * diag
                          else refine(S[C_], V[np.unique(F[np.isin(label, [P_, C_])])]))
            if S[L]["kind"] != S[M]["kind"] and s2 is not None:
                # judged on a refit over both vertex sets: the curved fit alone may be poor exactly because the
                # facets took its triangles (cross block: quarter rounds at R 2.4937 instead of 2.5)
                Pu = V[np.unique(F[np.isin(label, [P_, C_])])]
                # vertices alone are not enough: a cylinder's end disk has every vertex on the rim circle.
                # A facet also FACES like the surface there.
                tp = region_tris(P_); gn = sgrad(s2, tri[tp].mean(1))
                gn /= np.maximum(np.linalg.norm(gn, axis=1, keepdims=True), 1e-300)
                facing = np.abs(np.einsum("ij,ij->i", gn, nt[tp])).min() > math.cos(math.radians(20))
                # and it hugs it: a facet's middle sits within the tessellation deflection; a cube face on its
                # circumscribed sphere (chamfered cube: all 26 faces "on" one sphere) does not
                hugs = np.abs(sdist(s2, tri[tp].mean(1))).max() < 2e-3 * diag
                if facing and hugs and np.abs(sdist(s2, Pu)).max() < 1e-5 * diag:
                    label[label == P_] = C_; del S[P_]
                    S[C_] = s2; merged = True; break
            # a pair that failed stays failed until one of its regions grows: the loop restarts after every
            # merge, and retrying every failed pair made best_axis_fit 1894 calls, 150 of 180 s on the puck
            pair_key = (L, M, _sz(L), _sz(M))
            # two HEALTHY surfaces are never one: every union that mattered joined a fragment (chamfer strips,
            # sphere-like patches of a torus). Refitting every pair of mechparts/7's 166 cylinders cost
            # best_axis_fit 1035 calls and fit_smooth 918 calls, 141 of 200 s.
            def _fragment(q):
                # cached per (region, size, surface identity): uncached it was 63612 calls, 127 of 293 s on mechparts/7
                tq = region_tris(q); ck = (q, len(tq), id(S[q]))
                if ck not in fragment_cache:
                    fragment_cache[ck] = len(tq) < 25 or not surface_ok(S[q], tq)[0]
                return fragment_cache[ck]
            # no union refit for a pair with a sphere: a sphere has no axis of its own, and best_axis_fit returned
            # None for every one of the puck's 15 sphere patches (second opinion, DeepSeek: 99 s -> 8.7 s, same result)
            if (S[L]["kind"] != "plane" and S[M]["kind"] != "plane" and pair_key not in tried_union
                    and "sphere" not in (S[L]["kind"], S[M]["kind"])
                    and not os.environ.get("EB_NO_UNION_REFIT") and (_fragment(L) or _fragment(M))):
                tried_union.add(pair_key)
                # neither fragment holds the other, but their union may be ONE surface of another kind
                # (outer 45-degree chamfer of the Schlauchschelle ring: 20 tilted "cylinder" strips of one cone)
                ts_u = np.where(np.isin(label, [L, M]))[0]; Pu = V[np.unique(F[ts_u])]
                # first about a known machining axis (puck: 15 sphere-like patches of two torus fillets).
                # Only axes the pair itself implies: its own revolution axes, or known axes through a sphere
                # centre. Trying every axis on every pair ran the puck past 12 minutes.
                own = []
                for q_ in (S[L], S[M]):
                    if q_["kind"] in ("cylinder", "cone", "torus"):
                        own.append([q_["a"], q_["o"], 0.0])
                    elif q_["kind"] == "sphere":
                        for c_ in cands0:
                            p0 = c_[1] if c_[1] is not None else q_["c"]
                            dq = q_["c"] - p0
                            if np.linalg.norm(dq - (dq @ c_[0]) * c_[0]) < 1e-3 * diag:
                                own.append([c_[0], q_["c"], 0.0])
                if not os.environ.get("EB_UNION_MIXED") and S[L]["kind"] != S[M]["kind"]:
                    # same-kind only (EB_UNION_MIXED=1 restores mixed pairs): mixed-kind axis unions merged 0 times on
                    # Schlauchschelle, puck, cross block and mechparts/7; every merge was cone+cone or torus+torus
                    own = []
                b_ax = best_axis_fit(ts_u, own[:6]) if own else None
                if os.environ.get("EB_UNION_STATS"):
                    union_stats[("axis", S[L]["kind"], S[M]["kind"], b_ax is not None)] += 1
                if b_ax is not None:
                    label[label == M] = L; kinds[L] = b_ax["kind"]; del S[M]; S[L] = b_ax
                    merged = True; break
                best_u = None
                # OFF by default (EB_KINDS4=1 restores): the free-axis four-kind union merged 0 of 138 attempts measured
                # (Schlauchschelle 62, puck 54, cross block 4, mechparts/7 42) and kept mechparts/1 (24k tris) in this
                # loop past 600 s; without it mechparts/1 leaves the loop in 172 s. Results identical on 25 models.
                for kind_u in (("cylinder", "cone", "sphere", "torus") if os.environ.get("EB_KINDS4") else ()):
                    kinds_save = kinds[L]; kinds[L] = kind_u; label_save = label.copy()
                    label[label == M] = L
                    try:
                        s_u = fit(L)
                        s_u = refine(s_u, Pu) if s_u is not None else None
                    except Exception:  # noqa: BLE001 - a candidate model, not a result
                        s_u = None
                    label[:] = label_save; kinds[L] = kinds_save
                    if s_u is None:
                        continue
                    res_u = float(np.abs(sdist(s_u, Pu)).max())
                    g_u = sgrad(s_u, tri[ts_u].mean(1)); g_u /= np.maximum(np.linalg.norm(g_u, axis=1, keepdims=True), 1e-300)
                    if (res_u < 1e-5 * diag and np.abs(sdist(s_u, tri[ts_u].mean(1))).max() < 2e-3 * diag
                            and np.abs(np.einsum("ij,ij->i", g_u, nt[ts_u])).min() > math.cos(math.radians(20))
                            and best_u is None):
                        # the SIMPLEST kind that fits wins: a narrow band has vertices only on its two rim
                        # circles, so cone, sphere and torus all fit it exactly (the chamfer came out a sphere)
                        best_u = (res_u, kind_u, s_u)
                if os.environ.get("EB_UNION_STATS"):
                    union_stats[("kinds4", S[L]["kind"], S[M]["kind"],
                                 best_u is not None and best_u[1] not in (S[L]["kind"], S[M]["kind"]))] += 1
                if best_u is not None and best_u[1] not in (S[L]["kind"], S[M]["kind"]):
                    label[label == M] = L; kinds[L] = best_u[1]; del S[M]; S[L] = best_u[2]
                    merged = True; break
            if M > L and S[L]["kind"] == S[M]["kind"]:
                if (np.abs(sdist(S[L], region_verts(M))).max() < TOLM
                        and np.abs(sdist(S[M], region_verts(L))).max() < TOLM):
                    label[label == M] = L; del S[M]
                    S[L] = S[L] if S[L]["kind"] == "plane" else refit_keep(S[L], region_verts(L))
                    merged = True; break
                if S[L]["kind"] != "plane":
                    # fragments of ONE revolution surface fit separately differ more than TOLM (mechparts/7: a R6
                    # fillet around the R44.1 boss in 12 torus pieces, major 44.07-44.14, 11 free edges between them).
                    # Judge them on a JOINT refit of the union, like the cross-kind absorb (DeepSeek review, verified).
                    same_key = (L, M, _sz(L), _sz(M))
                    if same_key not in tried_same:
                        tried_same.add(same_key)
                        C_, P_ = (L, M) if _sz(L) >= _sz(M) else (M, L)
                        if float(np.abs(sdist(S[C_], region_verts(P_))).max()) < 1e-2 * diag:
                            ts_u = np.where(np.isin(label, [L, M]))[0]
                            s_u = refine(S[C_], V[np.unique(F[ts_u])])
                            if surface_ok(s_u, ts_u)[0]:
                                label[label == P_] = C_; del S[P_]; S[C_] = s_u
                                merged = True; break
        if merged:
            break

if os.environ.get("EB_UNION_STATS"):
    for k_s, v_s in sorted(union_stats.items(), key=lambda kv: -kv[1]):
        log(f"  union {k_s[0]:6s} {k_s[1]:>8s}+{k_s[2]:<8s} merged={k_s[3]}: {v_s}")

# a curved region whose own fit misses some of its vertices is a MIX of surfaces (L04_puck: 15 "sphere" patches, each with
# its median vertex on one torus fillet to 1e-6 but its worst vertices 2.95 mm off, on the side cylinder or the other fillet).
# Move each triangle that is not on its region's surface to the neighbouring surface all three of its vertices lie on; a
# region emptied this way disappears. Regions whose vertices are all on their surface are never touched.
n_mixed = 0
# ON by default (EB_NO_MIXED=1 disables). Measured: the 4 Schlauchschelle cylinder faces it removed were the tilted R 8.04
# junction strips (1.74 mm2, 45-degree axes), every real cylinder kept, still valid; puck 5 -> 2 bad corners,
# mechparts/7 4 -> 2; mechparts/29 4 -> 10 but it fails either way. Awaiting the full corpus run.
for _pass in ([] if os.environ.get("EB_NO_MIXED") else range(6)):
    moved_any = False; adj_m = adjacency()
    for L in [L for L, s in S.items() if s["kind"] != "plane"]:
        ts = region_tris(L)
        if len(ts) == 0 or float(np.abs(sdist(S[L], region_verts(L))).max()) < 1e-5 * diag:
            continue
        cands_m = [M for M in adj_m[L] if M in S and M != L]
        for t in ts:
            Pt = V[F[t]]
            if float(np.abs(sdist(S[L], Pt)).max()) < 1e-5 * diag:
                continue
            best_m = min(cands_m, key=lambda M: float(np.abs(sdist(S[M], Pt)).max()), default=None)
            if best_m is not None and float(np.abs(sdist(S[best_m], Pt)).max()) < 1e-5 * diag:
                label[t] = best_m; moved_any = True; n_mixed += 1
    for L in [L for L in list(S) if not (label == L).any()]:
        del S[L]
    if not moved_any:
        break
# (tried and removed 2026-09-15: moving curved-region triangles that lie exactly on a neighbouring plane fixed one of
# mechparts/34's two corners but moved 8 real fillet triangles on L09_bearing_block, which then built invalid)
if n_mixed:
    for L in [L for L, s in S.items() if s["kind"] != "plane"]:
        if (label == L).sum() >= 3:
            S[L] = refit_keep(S[L], region_verts(L))
    log(f"{n_mixed} triangles of mixed curved regions moved to the surface they lie on; surfaces now {collections.Counter(s['kind'] for s in S.values())}")

if os.environ.get("EB_SPLIT_MIXED"):
    # A region whose own fit does not hug and face its triangles (surface_ok false) can still fit its VERTICES within
    # 1e-5*diag, so the mixed pass above never touches it, yet its triangles really lie on KNOWN primitives: mechparts/20's
    # S21 is the big-ring bottom R2 round (267 tris) + the R22.5 outer cylinder (90), S17 the R22.5 cylinder (54) + the
    # round (10), all fitted as a distorted torus / a cone. Vote every triangle of such a region onto the healthiest
    # region surface (the ring cylinders and the R2 rounds already exist as regions) and keep only if the vote is a
    # majority: that leaves a genuine round with a slightly loose fit (the arm's R2 cylinders get 16/88 votes) untouched.
    n_sm = 0
    for _pass in range(6):
        moved_sm = False
        health = {M: (S[M]["kind"] == "plane" or surface_ok(S[M], region_tris(M))[0]) for M in S}
        adj_sm = adjacency()
        for L in list(S):
            s = S[L]; ts = region_tris(L)
            if len(ts) == 0:
                continue
            is_pl = s["kind"] == "plane"
            # a torus whose tube centre is farther than the whole part is a cylinder/plane in disguise (mechparts/20 S2:
            # major 13, minor 10, hc 5484, sitting on the small ring's R10 outer). It must be split whatever the vote says.
            is_bad = (not is_pl) and s["kind"] == "torus" and abs(s.get("hc", 0.0)) > diag
            if not is_pl and not is_bad and surface_ok(s, ts)[0]:
                continue
            if is_pl:
                # only a small facet of a ROUND (a torus neighbour): mechparts/20's 2-triangle S118 on the ring widest
                # point keeps a {round, plane, plane} corner whose two near-parallel planes cannot meet. Real flat faces
                # (mechparts/26, washer) have no torus neighbour and are left alone.
                nbrs = adj_sm.get(L, set())
                if len(ts) > 12 or not any(S[M]["kind"] == "torus" for M in nbrs if M in S):
                    continue
            cands_sm = [M for M in S if M != L and health.get(M) and (not is_pl or S[M]["kind"] != "plane")]
            if not cands_sm:
                continue
            newlab = {}; strict_sm = 0
            for t in ts:
                Pt = V[F[t]]
                own_d = float(np.abs(sdist(S[L], Pt)).max())
                best_sm = min(cands_sm, key=lambda M: float(np.abs(sdist(S[M], Pt)).max()))
                bd = float(np.abs(sdist(S[best_sm], Pt)).max())
                if (bd < 5e-3 * diag) if is_pl else (bd < own_d):
                    strict_sm += 1
                if (bd < own_d or bd < 5e-3 * diag):
                    newlab[t] = best_sm
            # majority on the STRICT votes only: a genuine round with a loose fit (the arm's R2 cylinders) gets few strict
            # votes and is left alone; the loose clause above then only cleans up the leftovers of a region already split.
            if strict_sm >= 0.5 * len(ts) or is_bad:
                for t, M in newlab.items():
                    label[t] = M
                moved_sm = True; n_sm += 1
                left_sm = [t for t in ts if t not in newlab]
                log(f"  split-mixed S{L} ({S[L]['kind']}, {len(ts)} tris): {len(newlab)} moved, "
                    f"{len(left_sm)} left, to "
                    + str(collections.Counter(S[M]["kind"] + f" S{M}" for M in newlab.values())))
                if left_sm:
                    zl = V[np.unique(F[left_sm])][:, 2]
                    log(f"    split-mixed leftover {len(left_sm)} tris near {np.round(V[np.unique(F[left_sm])].mean(0), 1).tolist()} "
                        f"z {zl.min():.2f}..{zl.max():.2f}")
        for L in [L for L in list(S) if not (label == L).any()]:
            del S[L]
        if not moved_sm:
            break
    for L in [L for L, s in S.items() if s["kind"] != "plane"]:
        if (label == L).sum() >= 3:
            S[L] = refit_keep(S[L], region_verts(L))
    for L in [L for L, s in S.items() if s["kind"] == "plane"]:
        if (label == L).sum() >= 3:
            S[L] = fit(L)
    log(f"split-mixed: {n_sm} mixed regions split; surfaces now {collections.Counter(s['kind'] for s in S.values())}")

# a curved region with no more vertices than its surface has parameters fits ANY such surface exactly: a 2-triangle
# junction sliver became a 45-degree R 122 cylinder (mechparts/29) or a sphere 0.35 mm off-centre (L04_puck). It takes
# the neighbouring surface its vertices lie on, else the simplest surface through them: a plane.
DOF = {"sphere": 4, "cylinder": 5, "cone": 6, "torus": 7}
adj_u = adjacency(); n_under = 0
for L in [L for L, s in S.items() if s["kind"] != "plane"]:
    Pv = region_verts(L)
    if len(Pv) > DOF[S[L]["kind"]] + 1:
        continue
    best_m = min((M for M in adj_u[L] if M in S and M != L), key=lambda M: float(np.abs(sdist(S[M], Pv)).max()), default=None)
    if best_m is not None and float(np.abs(sdist(S[best_m], Pv)).max()) < 1e-5 * diag:
        label[label == L] = best_m; del S[L]; n_under += 1
        for M in adj_u.pop(L, set()):
            adj_u[M].discard(L)
            if M != best_m:
                adj_u[M].add(best_m); adj_u[best_m].add(M)
        continue
    kinds[L] = "plane"; pl_ = fit(L)
    if float(np.abs(sdist(pl_, Pv)).max()) < 1e-5 * diag:
        S[L] = pl_; n_under += 1
    else:
        kinds[L] = S[L]["kind"]
if n_under:
    log(f"{n_under} curved regions with too few vertices to fix their own surface took a neighbour's surface or a plane")

# a curved region its own fit misses, lying whole on a neighbour's surface, is part of that neighbour (mechparts/30: two
# chamfer strips fitted as 45-degree R 48 cylinders, own miss 1.5e-2, on the chamfer cone within 4.9e-4). The per-triangle
# mixed pass ran before that cone had its final fit.
adj_w = adjacency(); n_whole = 0
for L in sorted(L_ for L_, s_ in S.items() if s_["kind"] != "plane"):
    if L not in S:
        continue
    Pv_w = region_verts(L)
    if float(np.abs(sdist(S[L], Pv_w)).max()) < 1e-5 * diag:
        continue
    best_w = min((M for M in adj_w[L] if M in S and M != L), key=lambda M: float(np.abs(sdist(S[M], Pv_w)).max()), default=None)
    if best_w is not None and float(np.abs(sdist(S[best_w], Pv_w)).max()) < 1e-5 * diag:
        label[label == L] = best_w; del S[L]; n_whole += 1
        for M in adj_w.pop(L, set()):
            adj_w[M].discard(L)
            if M != best_w:
                adj_w[M].add(best_w); adj_w[best_w].add(M)
if n_whole:
    log(f"{n_whole} curved regions their own fit misses lay whole on a neighbour's surface and joined it")
if os.environ.get("EB_DEBUG"):
    # curved regions with no interior vertex: every vertex is on a boundary, so their own fit is unconstrained
    adj_i = adjacency()
    for L in [L for L, s in S.items() if s["kind"] != "plane"]:
        ts_i = region_tris(L); vs_i = np.unique(F[ts_i]); interior_i = [v for v in vs_i if vlabels_all[v] == {L}] if "vlabels_all" in dir() else None
        nbr_labels = {int(label[other(t, F[t][i], F[t][(i + 1) % 3])]) for t in ts_i for i in range(3)} - {L}
        bnd_v = {v for t in ts_i for i in range(3) if int(label[other(t, F[t][i], F[t][(i + 1) % 3])]) != L for v in (F[t][i], F[t][(i + 1) % 3])}
        if len(ts_i) <= 30 and len(bnd_v) == len(vs_i):
            Pv_i = V[vs_i]
            log(f"  NO-INTERIOR S{L} ({S[L]['kind']}, {len(ts_i)} tris, {len(vs_i)} verts): own max {float(np.abs(sdist(S[L], Pv_i)).max()):.2e}; "
                + ", ".join(f"S{M}:{S[M]['kind']} max {float(np.abs(sdist(S[M], Pv_i)).max()):.2e} "
                            f"per-vertex-min-over-neighbours max {float(np.min(np.stack([np.abs(sdist(S[M2], Pv_i)) for M2 in nbr_labels if M2 in S]), axis=0).max()):.2e}"
                            for M in sorted(nbr_labels) if M in S))

# triangles of a PLANE region off its plane are another face swallowed by it (mechparts/29: a 2-triangle 45-degree
# chamfer strip inside the top plane; its corners solved 0.8 mm off). Each connected group of them takes the
# neighbouring surface its vertices lie on, else becomes its own plane when one fits.
n_split = 0; adj_s = adjacency()
for L in [L for L, s in S.items() if s["kind"] == "plane"]:
    ts = region_tris(L)
    off_t = ts[np.abs(sdist(S[L], tri[ts].reshape(-1, 3))).reshape(-1, 3).max(1) > 1e-5 * diag]
    if len(off_t) == 0:
        continue
    # more than a fifth off its plane: the "plane" is doubtful, so its off triangles may still move to a neighbour whose
    # surface they lie ON (broom holder arm: a 6-triangle tangent lead-in with 4 triangles on the R 20.4 arc), but no
    # new plane is invented from them
    many_off = len(off_t) > 0.2 * len(ts)
    oset = set(off_t.tolist()); seen_o = set()
    for t0 in off_t:
        if t0 in seen_o:
            continue
        grp = []; stack = [t0]; seen_o.add(t0)
        while stack:
            t = stack.pop(); grp.append(t)
            for i in range(3):
                u = other(t, F[t][i], F[t][(i + 1) % 3])
                if u in oset and u not in seen_o:
                    seen_o.add(u); stack.append(u)
        Pg = V[np.unique(F[grp])]
        best_m = min((M for M in adj_s[L] if M in S and M != L), key=lambda M: float(np.abs(sdist(S[M], Pg)).max()), default=None)
        if best_m is not None and float(np.abs(sdist(S[best_m], Pg)).max()) < 1e-5 * diag:
            label[grp] = best_m; n_split += 1
            continue
        if many_off:
            continue
        newL = len(kinds); kinds.append("plane"); label[grp] = newL; pl_ = fit(newL)
        if float(np.abs(sdist(pl_, Pg)).max()) < 1e-5 * diag:
            S[newL] = pl_; n_split += 1
        else:
            label[grp] = L
    if (label == L).sum() >= 3:
        S[L] = fit(L)
if n_split:
    log(f"{n_split} groups of triangles off their plane became their own face")

# two neighbouring curved regions on ONE surface (broom holder arm: an R 0.68 fillet as S15 and S37, axes 1.4e-4 apart,
# each region's loops threading through the other) have no intersection curve: their "edges" were noise and left 15
# free edges. Each surface lying on the other's vertices makes them one region.
n_same = 0; merged_same = True
while merged_same:
    merged_same = False; adj_c = adjacency()
    for L in sorted(L_ for L_, s_ in S.items() if s_["kind"] != "plane"):
        for M in sorted(adj_c[L]):
            if M not in S or M == L or S[M]["kind"] != S[L]["kind"]:
                continue
            PL, PM = region_verts(L), region_verts(M)
            same_ = (float(np.abs(sdist(S[M], PL)).max()) < 1e-5 * diag and float(np.abs(sdist(S[L], PM)).max()) < 1e-5 * diag)
            if not same_ and S[L]["kind"] in ("cylinder", "cone", "sphere"):
                # two fits of one arc can differ by more than the tolerance (mechparts/34: R 50.8058 and R 50.8016,
                # axes 4e-3 apart, one each side of a slot): ONE surface fitted to both vertex sets decides
                PU = np.vstack([PL, PM]); near_ = min((S[L], S[M]), key=lambda q_: float(np.abs(sdist(q_, PU)).max()))
                if float(np.abs(sdist(near_, PU)).max()) < 5e-4 * diag:
                    try:
                        joint_ = refine(near_, PU)
                        same_ = float(np.abs(sdist(joint_, PU)).max()) < 1e-5 * diag
                    except Exception:  # noqa: BLE001 - a candidate merge, not a result
                        same_ = False
            if same_:
                # vertices alone are not enough: a side hole through a tube wall has every vertex on its two rims, which
                # lie ON the tube (L02_cyl_side_hole: hole and tube merged into one R 17 cylinder). The merged surface must
                # also hug and face the triangles of both regions.
                ts_lm = np.concatenate([region_tris(L), region_tris(M)])
                same_ = surface_ok(S[L], ts_lm)[0] or surface_ok(S[M], ts_lm)[0]
            if same_:
                label[label == M] = L; del S[M]
                S[L] = refit_keep(S[L], region_verts(L)); n_same += 1; merged_same = True
                break
        if merged_same:
            break
if n_same:
    log(f"{n_same} pairs of neighbouring regions on one surface merged")

if os.environ.get("EB_DUMP_SPHERE_TORUS"):
    # L04_puck: 15 sphere patches (centres on the axis, R 11-18.5) beside 2 exact tori. Are their VERTICES on a torus,
    # and do they border a torus at all (a sphere-only chain never meets the absorb check)?
    adj_d = adjacency(); tori_d = [L_ for L_, s_ in S.items() if s_["kind"] == "torus"]
    for L_ in [L_ for L_, s_ in S.items() if s_["kind"] == "sphere"]:
        Pv = region_verts(L_)
        on = ", ".join(f"S{Lt}: max {float(np.abs(sdist(S[Lt], Pv)).max()):.2e} median {float(np.median(np.abs(sdist(S[Lt], Pv)))):.2e}" for Lt in tori_d)
        nbk = collections.Counter(S[M_]["kind"] for M_ in adj_d[L_] if M_ in S)
        log(f"  sphere S{L_} ({len(region_tris(L_))} tris): on tori [{on}] | neighbours {dict(nbk)} {sorted(M_ for M_ in adj_d[L_] if M_ in S and S[M_]['kind'] == 'torus')}")

# tangency and coaxiality between neighbours, enforced exactly (a fillet that misses its flank by 1e-3 has no edge)
adj = adjacency()
REL = 0.02
# a curved surface larger than the whole part is a flat patch in disguise that a later refit produced (mechparts/16:
# a 23-triangle strip ended as a cylinder of R 1.1e8, its corner solved 470 mm away). A plane through its vertices
# takes over when one fits them.
n_giant = 0
for L in [L for L, s in S.items() if s["kind"] != "plane"]:
    sizes_g = [S[L].get(k_) for k_ in ("R", "major", "minor") if S[L].get(k_) is not None]
    if all(0 < z_ < diag for z_ in sizes_g):
        continue
    kinds[L] = "plane"; pl_g = fit(L); Pv_g = region_verts(L)
    if float(np.abs(sdist(pl_g, Pv_g)).max()) < 1e-5 * diag:
        S[L] = pl_g; n_giant += 1
    else:
        kinds[L] = S[L]["kind"]
        # (splitting such a surface by facet normal into planes was tried 2026-09-15 and removed: on mechparts/20 the four
        # R 2.8e8-4.7e8 strips are real rounds a plane misses by 0.38 mm, they split into 52-53 one-facet planes each and
        # the part went from 28 to 65 failed corners. A single facet is always "flat"; these need a round refit.)
if n_giant:
    log(f"{n_giant} curved surfaces larger than the part became planes")
adj = adjacency()
# a plane that runs along a neighbour's axis but was fitted a hair off parallel (broom holder arm: n.a = 2e-6 on a
# small wall tangent to an R 0.68 fillet) failed the exact-parallel test below, so its tangency was never enforced and
# the fillet missed it by 3e-4. Make it exactly parallel when its own vertices still lie on the result.
for L in [L for L, s in S.items() if s["kind"] == "plane"]:
    n_ = S[L]["n"]; Pv_ = region_verts(L)
    for M in sorted(adj[L]):
        if M not in S or S[M]["kind"] not in ("cylinder", "cone", "torus"):
            continue
        a_ = S[M]["a"]; c_ = float(n_ @ a_)
        n2 = None
        if 1e-9 <= abs(c_) < 1e-4:
            n2 = n_ - c_ * a_; n2 /= np.linalg.norm(n2)
        elif 1e-12 <= 1 - abs(c_) < 5e-9:
            # the same for a plane ACROSS the axis (mechparts/28: top plane n = (-6e-6, 3e-6, 1) on a fillet torus of
            # major R 64 whose axis leans by 4.5e-6: the tangent circle's height wandered 4e-4 and projection failed)
            n2 = math.copysign(1.0, c_) * a_
        if n2 is not None:
            d2 = float((Pv_ @ n2).mean())
            if float(np.abs(Pv_ @ n2 - d2).max()) < 1e-5 * diag:
                S[L] = dict(S[L], n=n2, d=d2)
            break
ncons = collections.Counter()
cc_pairs, cc_lam, saved_cons = {}, set(), {}
for kind in ("sphere", "cylinder", "cone", "torus"):
    for L in [L for L, s in S.items() if s["kind"] == kind]:
        s = S[L]; cons = []; k0_fix = None
        for M in sorted(adj[L]):
            q = S[M]
            if q["kind"] == "plane":
                n_, d_ = q["n"], q["d"]
                if kind == "sphere":
                    dist = float(n_ @ s["c"] - d_)
                    if abs(abs(dist) - s["R"]) < REL * s["R"]:
                        sg = math.copysign(1, dist)
                        cons.append(lambda t, n_=n_, d_=d_, sg=sg: sg * (t["c"] @ n_ - d_) - t["R"]); ncons["sphere-plane"] += 1
                elif kind == "cylinder" and abs(s["a"] @ n_) < 1e-9:
                    dist = float(n_ @ s["o"] - d_)
                    if abs(abs(dist) - s["R"]) < REL * s["R"]:
                        sg = math.copysign(1, dist)
                        cons.append(lambda t, n_=n_, d_=d_, sg=sg: sg * (t["o"] @ n_ - d_) - t["R"]); ncons["cyl-plane"] += 1
                elif kind == "cone" and 1e-3 < abs(float(s["a"] @ n_)) < 1 - 1e-3:
                    # a plane tangent to a cone fixes its half-angle: |n.a| = sin(alpha), k0 = tan(alpha). A 45-degree
                    # chamfer cone fitted at k0 1.000012 missed its 45-degree chamfer plane by 2e-4..4e-4 (mechparts/29)
                    ca_ = abs(float(s["a"] @ n_)); k_plane = ca_ / math.sqrt(1.0 - ca_ * ca_)
                    # OPT-IN (EB_CONE_PLANE=1): two attempts made mechparts/29 worse (4 -> 9 bad corners; snap alone, then
                    # snap + refit of axis position and offset with the angle held). Needs a joint solve, not a snap.
                    if abs(s["k0"] - k_plane) < 1e-3 * k_plane and os.environ.get("EB_CONE_PLANE"):
                        k0_fix = k_plane; ncons["cone-plane angle"] += 1
                elif kind == "torus" and abs(abs(s["a"] @ n_) - 1) < 1e-9:
                    dist = float(n_ @ (s["o"] + s["a"] * s["hc"]) - d_)
                    if os.environ.get("EB_DEBUG"):
                        log(f"  torus-plane candidate S{L} vs S{M}: |a.n|-1 {abs(float(s['a'] @ n_)) - 1:+.1e}, tube-plane distance "
                            f"{dist:+.6f}, minor {s['minor']:.6f}, |dist|-minor {abs(dist) - s['minor']:+.2e} -> "
                            f"{'CONSTRAINT' if abs(abs(dist) - s['minor']) < REL * s['minor'] else 'no'}")
                    if abs(abs(dist) - s["minor"]) < REL * s["minor"]:
                        sg = math.copysign(1, dist)
                        cons.append(lambda t, n_=n_, d_=d_, sg=sg: sg * (n_ @ (t["o"] + t["a"] * t["hc"]) - d_) - t["minor"])
                        ncons["torus-plane"] += 1
            elif (q["kind"] == "cylinder" and kind == "cylinder" and q["R"] >= s["R"] and os.environ.get("EB_CYL_CYL", "1") not in ("", "0")
                    and abs(abs(float(s["a"] @ q["a"])) - 1) < 1e-9):
                # OPT-IN (EB_CYL_CYL=1) until reviewed: fixed mechparts/13 at 2 % but made 7 a +47 % wrong solid,
                # 14 a -16 % wrong solid and 10 time out; at 2e-4 of R 13 failed again (bd projects-2i0)
                # parallel cylinders tangent to each other: a blend radius between two arcs (mechparts/7: R 9.652
                # between R 16 and R 50.8 missed its neighbours by 6.6e-4, 4 corners never met). The smaller one moves.
                dq = q["o"] - s["o"]; dist_ax = float(np.linalg.norm(dq - (dq @ s["a"]) * s["a"]))
                for sg_ in (1.0, -1.0):
                    if abs(dist_ax - (q["R"] + sg_ * s["R"])) < REL * s["R"] and os.environ.get("EB_DEBUG"):
                        log(f"  cyl-cyl candidate S{L} R {s['R']:.4f} vs S{M} R {q['R']:.4f}: axis distance {dist_ax:.4f}, "
                            f"R{'+' if sg_ > 0 else '-'}R {q['R'] + sg_ * s['R']:.4f}, mismatch {abs(dist_ax - (q['R'] + sg_ * s['R'])):.2e} "
                            f"({abs(dist_ax - (q['R'] + sg_ * s['R'])) / s['R']:.1e} of R), shared mesh edges {sum(1 for t_ in region_tris(L) for i_ in range(3) if label[other(t_, F[t_][i_], F[t_][(i_ + 1) % 3])] == M)}, "
                            f"normal dot across them {[round(float(nt[t_] @ nt[other(t_, F[t_][i_], F[t_][(i_ + 1) % 3])]), 3) for t_ in region_tris(L) for i_ in range(3) if label[other(t_, F[t_][i_], F[t_][(i_ + 1) % 3])] == M][:6]}")
                    # 2e-4 of R, not the 2 % used against planes: on mechparts/7 the 12 real tangencies missed by
                    # 2e-7..1.6e-5 of R, four false ones (R 9.652 vs R 10.935) by 8.6e-4..9.1e-4 and wrecked the solid
                    # 5e-4 of R separates mechparts/13's real tangency (2.2e-4) from mechparts/7's false ones (8.6e-4).
                    # The target distance uses the smaller cylinder's FITTED radius as a constant: with t["R"] inside the
                    # constraint the projection also changed R (9.652 -> 9.6498 on model 7, DeepSeek review, verified).
                    if abs(dist_ax - (q["R"] + sg_ * s["R"])) < 5e-4 * s["R"]:
                        oq, target = q["o"], q["R"] + sg_ * s["R"]
                        cons.append(lambda t, oq=oq, target=target: float(np.linalg.norm(
                            (oq - t["o"]) - ((oq - t["o"]) @ t["a"]) * t["a"])) - target)
                        ncons["cyl-cyl"] += 1; cc_pairs.setdefault(L, []).append((M, sg_)); cc_lam.add(id(cons[-1]))
                        break
            elif q["kind"] == "sphere" and kind == "cylinder" and q is not s:
                qq = q["c"] - s["o"]; off = np.linalg.norm(qq - (qq @ s["a"]) * s["a"])
                if off < REL * s["R"] and abs(q["R"] - s["R"]) < REL * s["R"]:
                    cs, Rs = q["c"], q["R"]
                    cons += [lambda t, cs=cs: (cs - t["o"]) @ t["u"], lambda t, cs=cs: (cs - t["o"]) @ t["w"],
                             lambda t, Rs=Rs: t["R"] - Rs]
                    ncons["cyl-sphere"] += 1
            elif q["kind"] == "cylinder" and kind in ("cone", "torus") and abs(abs(s["a"] @ q["a"]) - 1) < 1e-9:
                qq = q["o"] - s["o"]; off = np.linalg.norm(qq - (qq @ s["a"]) * s["a"])
                if off < REL * q["R"]:
                    oc = q["o"]
                    cons += [lambda t, oc=oc: (oc - t["o"]) @ t["u"], lambda t, oc=oc: (oc - t["o"]) @ t["w"]]
                    ncons[f"{kind}-cyl coaxial"] += 1
                    if kind == "torus" and abs(abs(s["major"] - q["R"]) - s["minor"]) < REL * s["minor"]:
                        sg = math.copysign(1, s["major"] - q["R"]); Rq = q["R"]
                        cons.append(lambda t, sg=sg, Rq=Rq: sg * (t["major"] - Rq) - t["minor"]); ncons["torus-cyl"] += 1
        if k0_fix is not None:
            # hold the tangent plane's half-angle and refit the axis position and radius offset to the data: snapping
            # k0 alone kept k1 from the free fit and broke 9 corners instead of 4 on mechparts/29
            Pk = region_verts(L); x = to_vec(s); x[2] = k0_fix
            for _ in range(12):
                res_k = lambda y, x=x: sdist(from_vec(s, np.array([y[0], y[1], k0_fix, y[2]])), Pk)  # noqa: E731
                y = np.array([x[0], x[1], x[3]]); rr = res_k(y)
                if float(np.abs(rr).max()) < 1e-9 * diag:
                    break
                y = y + np.linalg.lstsq(jac(res_k, y, len(rr)), -rr, rcond=None)[0]
                x = np.array([y[0], y[1], k0_fix, y[2]])
            s = from_vec(s, x); S[L] = s
            cons.append(lambda t, k0_fix=k0_fix: t["k0"] - k0_fix)     # keep it through any further projection
        if cons:
            saved_cons[L] = cons
            S[L] = refine(s, region_verts(L), cons)
            if os.environ.get("EB_DEBUG") and L in cc_pairs:
                free_ = refine(s, region_verts(L))
                log(f"  CC-TRACE S{L}: before {np.round(s['o'], 4).tolist()} R {s['R']:.6f} | free fit {np.round(free_['o'], 4).tolist()} "
                    f"R {free_['R']:.6f} | constrained {np.round(S[L]['o'], 4).tolist()} R {S[L]['R']:.6f} | residuals "
                    + ", ".join(f"{float(c(S[L])):+.1e}" for c in cons) + f" | vertex fit max {float(np.abs(sdist(S[L], region_verts(L))).max()):.2e}")
            if L not in cc_pairs:
                # every kind of constraint gets the same guard: a sphere-plane tangency (window 2 % of R) moved a
                # 7-triangle R 19.6 sphere 0.13 mm off its own vertices (broom holder logo)
                Pv_g = region_verts(L); free_g = refine(s, Pv_g)
                if (float(np.abs(sdist(S[L], Pv_g)).max())
                        > float(np.abs(sdist(free_g, Pv_g)).max()) + 1e-5 * diag):
                    S[L] = free_g; saved_cons[L] = []
                    log(f"  constraints of S{L} ({kind}) dropped: they pull it off its own vertices")
            if L in cc_pairs:
                # a tangency may move a surface off its vertices by its own tolerance, no more. Two tangencies to walls
                # that should share one axis but were fitted 1.1e-4 apart are two near-identical circles whose exact
                # crossing lies 8 mm around the slot (mechparts/30: R 2.5 slot end, vertex fit 2e-13 -> 8.2 mm)
                Pv_ = region_verts(L); free_ = refine(s, Pv_)
                if (float(np.abs(sdist(S[L], Pv_)).max())
                        > float(np.abs(sdist(free_, Pv_)).max()) + 5e-4 * s["R"] + 1e-5 * diag):
                    cons = [c for c in cons if id(c) not in cc_lam]; del cc_pairs[L]; saved_cons[L] = cons
                    S[L] = refine(s, Pv_, cons) if cons else free_
                    log(f"  cyl-cyl tangencies of S{L} dropped: they pull it off its own vertices")
            if os.environ.get("EB_DEBUG"):
                # a constraint left unsatisfied means the set is inconsistent (mechparts/1: fillet torus S28 still 5e-5 off
                # its tangent plane after projection, so torus and plane never touch and the chain between them fails)
                res_c = [float(c(S[L])) for c in cons]
                if res_c and max(abs(x) for x in res_c) > 1e-9 * diag:
                    log(f"  UNSATISFIED constraints on S{L} ({kind}, {len(cons)} constraints): residuals "
                        + ", ".join(f"{x:+.2e}" for x in res_c) + f" | neighbours {sorted(M_ for M_ in adj[L] if M_ in S)}")
# the cyl-cyl target was frozen from the radii BEFORE refine(), whose free fit then moved R, and the constraint has no
# pull on R (mechparts/14: S48 R -2.5e-4, the axes 3e-4 apart, never touching; DeepSeek review, verified). Re-project
# each smaller cylinder onto the FINAL radii with its R held, largest first so every partner is already final.
for L in sorted(cc_pairs, key=lambda L_: -S[L_]["R"]):
    Rl = S[L]["R"]; cons = [c for c in saved_cons[L] if id(c) not in cc_lam]
    for M, sg_ in cc_pairs[L]:
        cons.append(lambda t, oq=S[M]["o"], target=S[M]["R"] + sg_ * Rl: float(np.linalg.norm(
            (oq - t["o"]) - ((oq - t["o"]) @ t["a"]) * t["a"])) - target)
    cons.append(lambda t, Rl=Rl: t["R"] - Rl)
    new_ = refine(S[L], None, cons, fit=False); Pv_ = region_verts(L)
    if float(np.abs(sdist(new_, Pv_)).max()) <= float(np.abs(sdist(S[L], Pv_)).max()) + 5e-4 * Rl + 1e-5 * diag:
        S[L] = new_
log(f"surfaces {collections.Counter(s['kind'] for s in S.values())}, constraints {dict(ncons)}")
if os.environ.get("EB_DEBUG"):
    for L, s in S.items():
        ts_ = region_tris(L); off_ = np.abs(sdist(s, tri[ts_].reshape(-1, 3))).reshape(-1, 3).max(1) > 1e-5 * diag
        if off_.any():
            log(f"  OFF-SURFACE S{L} ({s['kind']}): {int(off_.sum())}/{len(ts_)} triangles, centroids "
                + str(np.round(tri[ts_[off_]].mean(1)[:4], 3).tolist()))
            # which neighbour its vertices actually lie on, and how closely
            adj_o = adjacency(); Pv_o = region_verts(L)
            near_o = sorted(((float(np.abs(sdist(S[M], Pv_o)).max()), M) for M in adj_o[L] if M in S and M != L))[:3]
            log("    nearest neighbour surfaces: " + ", ".join(f"S{M}:{S[M]['kind']} max {d:.2e}" for d, M in near_o)
                + f" | own max {float(np.abs(sdist(s, Pv_o)).max()):.2e}")
    for L, s in S.items():
        log(f"  S{L} " + " ".join(f"{k}={np.round(v, 6).tolist() if isinstance(v, np.ndarray) else (round(v, 6) if isinstance(v, float) else v)}"
                                  for k, v in s.items() if k not in ("u", "w")))

# ---------------------------------------------------------------- 3. boundary loops
bnd = {}
for t, (a, b, c) in enumerate(F):
    for x, y in ((a, b), (b, c), (c, a)):
        if label[other(t, x, y)] != label[t]:
            if (x, y) in bnd:
                fail("mesh orientation is inconsistent")
            bnd[(x, y)] = t


def third(t, x, y):
    return next(v for v in F[t] if v != x and v != y)


def succ(x, y):
    t = bnd[(x, y)]; z = third(t, x, y)
    while not ((y, z) in bnd and bnd[(y, z)] == t):
        t2 = other(t, y, z); z = third(t2, z, y); t = t2
    return (y, z)


vlabels = collections.defaultdict(set)
for t, (a, b, c) in enumerate(F):
    for v in (a, b, c):
        vlabels[v].add(int(label[t]))
starts = collections.Counter((int(label[t]), x) for (x, _), t in bnd.items())
corner = {v for v, ls in vlabels.items() if len(ls) >= 3} | {v for (L, v), k in starts.items() if k > 1}

loops = []            # (region, [vertex, ...])
seen = set()
for h in bnd:
    if h in seen:
        continue
    seq = []; cur = h
    while cur not in seen:
        seen.add(cur); seq.append(cur[0]); cur = succ(*cur)
    loops.append((int(label[bnd[h]]), seq))

chains, edge2chain = [], {}
region_loops = collections.defaultdict(list)
for L, lp in loops:
    mlen = len(lp); cidx = [i for i in range(mlen) if lp[i] in corner]
    if not cidx:
        i0 = lp.index(min(lp)); runs = [lp[i0:] + lp[:i0] + [lp[i0]]]
    else:
        runs = []
        for j, i in enumerate(cidx):
            k = cidx[(j + 1) % len(cidx)]
            k = k + mlen if k <= i else k
            runs.append([lp[q % mlen] for q in range(i, k + 1)])
    wl = []
    for run in runs:
        e0 = (min(run[0], run[1]), max(run[0], run[1]))
        if e0 in edge2chain:
            cid = edge2chain[e0]; fwd = chains[cid]["verts"][1] == run[1] and chains[cid]["verts"][0] == run[0]
        else:
            cid = len(chains)
            M = int(label[other(bnd[(run[0], run[1])], run[0], run[1])])
            chains.append({"verts": run, "labs": (L, M), "corner_ends": bool(cidx)})
            for x, y in zip(run, run[1:]):
                edge2chain[(min(x, y), max(x, y))] = cid
            fwd = True
        wl.append((cid, fwd))
    region_loops[L].append(wl)
log(f"loops {len(loops)}, chains {len(chains)}, corners {len(corner)}")
if os.environ.get("EB_DUMP_REGION"):
    for L_d in (int(x) for x in os.environ["EB_DUMP_REGION"].split(",")):
        log(f"  region S{L_d} ({S[L_d]['kind'] if L_d in S else 'gone'}): {len(region_loops[L_d])} loops")
        for i_l, wl in enumerate(region_loops[L_d]):
            parts = []
            for cid, fwd in wl:
                ch_ = chains[cid]; nb_ = ch_["labs"][1] if ch_["labs"][0] == L_d else ch_["labs"][0]
                parts.append(f"S{nb_}{'' if ch_['corner_ends'] else '(closed)'}:{len(ch_['verts'])}v")
            log(f"    loop {i_l}: " + ", ".join(parts))
            if L_d in S and S[L_d]["kind"] == "plane":
                # signed area in the plane (loops run with the region on the left seen along the outward normal): positive =
                # an outer boundary, negative = a hole. Two positive loops = two lobes of one region touching at a point.
                n_p = S[L_d]["n"]; u_p, w_p = frame(n_p)
                pts_l = []
                for cid, fwd in wl:
                    vs_l = chains[cid]["verts"] if fwd else chains[cid]["verts"][::-1]
                    pts_l.extend(V[vs_l[:-1]])
                P2 = np.array([[float(p @ u_p), float(p @ w_p)] for p in pts_l])
                area_l = 0.5 * float(np.sum(P2[:, 0] * np.roll(P2[:, 1], -1) - np.roll(P2[:, 0], -1) * P2[:, 1])) if len(P2) >= 3 else 0.0
                shared_v = set()
                for j_l, wl2 in enumerate(region_loops[L_d]):
                    if j_l != i_l:
                        other_v = {v_ for c2, f2 in wl2 for v_ in chains[c2]["verts"]}
                        shared_v |= {v_ for c1, f1 in wl for v_ in chains[c1]["verts"]} & other_v
                log(f"      loop {i_l} signed area {area_l:+.3f}, vertices shared with other loops of S{L_d}: {len(shared_v)}")
    # every region adjacent to the dumped ones, with its loop count, to spot a hole loop that went to the wrong face
    for L_d in (int(x) for x in os.environ["EB_DUMP_REGION"].split(",")):
        nbs = sorted({(ch_["labs"][1] if ch_["labs"][0] == L_d else ch_["labs"][0]) for ch_ in chains if L_d in ch_["labs"]})
        log(f"  neighbours of S{L_d}: " + ", ".join(f"S{n_}({S[n_]['kind'] if n_ in S else '?'}, {len(region_loops[n_])} loops)" for n_ in nbs))


# ---------------------------------------------------------------- 4. exact corners and edges
RCOND = float(os.environ.get("EB_RCOND", "1e-6"))          # EB_RCOND: probe rung
CORNER_TOL = float(os.environ.get("EB_CORNER_TOL", "1e-6")) * diag   # EB_CORNER_TOL: loosening probe rung


def project(P0, surfs, iters=300, rcond=None):
    rcond = RCOND if rcond is None else rcond
    P = np.array(P0, float).reshape(-1, 3).copy()
    for _ in range(iters):
        rr = np.stack([sdist(s, P) for s in surfs], 1)
        G = np.stack([sgrad(s, P) for s in surfs], 1)
        # tangent surfaces (fillet flank, fillet/sphere) have nearly parallel gradients: a 3e-8 singular value
        # threw the soap bar's points 0.2 mm away. Truncate it, and cap the step to a trust region.
        step = -np.einsum("nij,nj->ni", np.linalg.pinv(G, rcond=rcond), rr)
        ln = np.linalg.norm(step, axis=1, keepdims=True)
        step *= np.minimum(1.0, 1e-3 * diag / np.maximum(ln, 1e-300))
        P += step
        if np.abs(step).max() < 1e-14 * diag:
            break
    return P, np.abs(np.stack([sdist(s, P) for s in surfs], 1)).max(1)


from OCP.BRep import BRep_Builder  # noqa: E402
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeSolid,  # noqa: E402
                                BRepBuilderAPI_MakeVertex, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Sewing)
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.Geom import (Geom_Circle, Geom_ConicalSurface, Geom_CylindricalSurface, Geom_Plane,  # noqa: E402
                      Geom_SphericalSurface, Geom_ToroidalSurface)
from OCP.GeomAPI import GeomAPI_Interpolate  # noqa: E402
from OCP.gp import gp_Ax2, gp_Ax3, gp_Dir, gp_Pnt  # noqa: E402
from OCP.ShapeFix import ShapeFix_Face, ShapeFix_Solid  # noqa: E402
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer  # noqa: E402
from OCP.TColgp import TColgp_HArray1OfPnt  # noqa: E402
from OCP.TopAbs import TopAbs_SHELL  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402
from OCP.TopLoc import TopLoc_Location  # noqa: E402
from OCP.TopoDS import TopoDS, TopoDS_Face  # noqa: E402

pnt = lambda p: gp_Pnt(*map(float, p))  # noqa: E731
gdir = lambda p: gp_Dir(*map(float, p))  # noqa: E731

# corners: solved on every surface meeting there; corners landing on one point are one vertex
cpos, cres, cres_v = {}, 0.0, {}
for v in corner:
    p, res = project(V[v], [S[L] for L in sorted(vlabels[v])])
    cpos[v] = p[0]; cres_v[v] = float(res[0]); cres = max(cres, cres_v[v])
if cres > CORNER_TOL:
    # a cylinder on its exactly tangent plane leaves a 2e-5 singular value that rcond 1e-6 keeps: corners walk off
    # (mechparts/29, 10; DeepSeek review, verified). 1e-3 on every part broke mechparts/1, and 1e-3 on the failed corners
    # alone left them off the edge points still projected at 1e-6 (29: invalid, dV -1235 %). So a part whose corners fail
    # does ALL its projections, corners and edges, again with that direction dropped.
    RCOND = 1e-3; cres = 0.0
    for v in corner:
        p, res = project(V[v], [S[L] for L in sorted(vlabels[v])])
        cpos[v] = p[0]; cres_v[v] = float(res[0]); cres = max(cres, cres_v[v])
    log(f"corners failed at rcond 1e-6, solved again at 1e-3: worst residual {cres:.1e}")
if cres > CORNER_TOL:
    bad = [v for v in corner if np.abs(np.array([sdist(S[L], cpos[v])[0] for L in vlabels[v]])).max() > CORNER_TOL]
    if os.environ.get("EB_DEBUG"):
        for v in bad[:12]:
            log(f"  bad corner at {np.round(V[v], 4).tolist()} -> {np.round(cpos[v], 4).tolist()}: "
                + ", ".join(f"S{L}:{S[L]['kind']}={float(sdist(S[L], cpos[v])[0]):.1e}" for L in sorted(vlabels[v])))
    fail(f"{len(bad)} corners where the fitted surfaces do not meet (worst residual {cres:.2e})")
rep = {}
cl = sorted(corner, key=lambda v: tuple(np.round(cpos[v] / (1e-6 * diag))))
for v in cl:
    for w in list(rep.values())[-50:]:
        if np.linalg.norm(cpos[v] - cpos[w]) < 1e-6 * diag:
            rep[v] = w; break
    else:
        rep[v] = v
vert = {w: BRepBuilderAPI_MakeVertex(pnt(cpos[w])).Vertex() for w in set(rep.values())}
# a corner where tangent surfaces meet converges to ~1e-7 only: its vertex tolerance must admit that
vtol = collections.defaultdict(lambda: 1e-7)
for v in corner:
    vtol[rep[v]] = max(vtol[rep[v]], 10 * cres_v[v], 2 * float(np.linalg.norm(cpos[v] - cpos[rep[v]])))
for w_, vx_ in vert.items():
    BRep_Builder().UpdateVertex(vx_, vtol[w_])
log(f"corners solved: {len(corner)} -> {len(vert)} vertices, worst residual {cres:.1e}")
if os.environ.get("EB_DEBUG"):
    for v in corner:
        if rep[v] != v:
            log(f"  MERGED corner {np.round(V[v], 4).tolist()} {sorted(vlabels[v])} into {np.round(V[rep[v]], 4).tolist()} "
                f"{sorted(vlabels[rep[v]])}: mesh vertices {float(np.linalg.norm(V[v] - V[rep[v]])):.3e} apart, solved "
                f"{float(np.linalg.norm(cpos[v] - cpos[rep[v]])):.1e} apart, moved {float(np.linalg.norm(cpos[v] - V[v])):.2e}")


def densify(P, surfs):
    if os.environ.get("EB_OLD_DENSIFY"):
        mids, _ = project(0.5 * (P[1:] + P[:-1]), surfs)
    else:
        # each new point also lies on the plane through its midpoint across the segment: two nearly tangent surfaces
        # (a 45-degree chamfer cone meeting a 45-degree facet) let a midpoint projected onto them alone slide along
        # their common tangent, and a 2.83 mm edge between two corners came out a 55 mm and a 158 mm B-spline
        # (mechparts/31 chains 66 and 102). Three equations pin the point; it still lies on both surfaces.
        mids = np.empty((len(P) - 1, 3))
        for i_ in range(len(P) - 1):
            m_ = 0.5 * (P[i_] + P[i_ + 1]); d_ = P[i_ + 1] - P[i_]; ld_ = float(np.linalg.norm(d_))
            if ld_ < 1e-12 * diag:
                mids[i_] = m_; continue
            d_ = d_ / ld_
            mids[i_] = project(m_, list(surfs) + [{"kind": "plane", "n": d_, "d": float(d_ @ m_)}])[0][0]
    o_ = np.empty((2 * len(P) - 1, 3)); o_[0::2] = P; o_[1::2] = mids
    return o_


def mk_edge(crv, VA, VB, u0, u1):
    """Edge on the exact curve between the SHARED corner vertices. A corner on tangent surfaces is only good to
    ~1e-7, so a vertex that misses the curve end gets its tolerance raised to the gap instead of a new vertex
    (a private vertex breaks the wire: soap bar, pillow)."""
    from OCP.BRep import BRep_Tool
    me = BRepBuilderAPI_MakeEdge(crv, VA, VB, u0, u1)
    if not me.IsDone():
        for vx, u in ((VA, u0), (VB, u1)):
            gap = crv.Value(u).Distance(BRep_Tool.Pnt_s(vx))
            if gap > 1e-4 * diag:
                log(f"  vertex misses its curve end by {gap:.2e}")
            if gap >= BRep_Tool.Tolerance_s(vx):
                BRep_Builder().UpdateVertex(vx, 2 * gap)
        me = BRepBuilderAPI_MakeEdge(crv, VA, VB, u0, u1)
    if me.IsDone():
        return me.Edge()
    fail(f"edge construction failed ({me.Error()})")


def common_axis(s1, s2):
    """(point, direction) of an axis both surfaces are symmetric about, or None. Their intersection is then
    a set of circles about it; tangent pairs (fillet/sphere) need this, their projected points are too soft."""
    def rev(s):
        if s["kind"] in ("cylinder", "cone", "torus"):
            return ("line", s["o"], s["a"])
        return ("point", s["c"], None) if s["kind"] == "sphere" else ("dir", None, s["n"])
    k1, k2 = rev(s1), rev(s2); tl = 1e-7 * diag
    if "line" in (k1[0], k2[0]):
        (_, o, a), q = (k1, k2) if k1[0] == "line" else (k2, k1)
        if q[0] == "dir":
            # 1e-9 (the tangency constraints' limit): a fillet torus whose plane normal is (2e-6, 0, 1) has |a.n|-1 of
            # -1.9e-12 and needs its closed-form circle (mechparts/1); alone this change did nothing, the rescue below uses it
            return (o, a) if abs(abs(a @ q[2]) - 1) < 1e-9 else None
        d = q[1] - o; off = np.linalg.norm(d - (d @ a) * a)
        if q[0] == "point":
            return (o, a) if off < tl else None
        return (o, a) if abs(abs(a @ q[2]) - 1) < 1e-12 and off < tl else None
    if {k1[0], k2[0]} == {"point", "dir"}:
        return (k1[1] if k1[0] == "point" else k2[1], k1[2] if k1[0] == "dir" else k2[2])
    if k1[0] == k2[0] == "point" and np.linalg.norm(k2[1] - k1[1]) > tl:
        return (k1[1], (k2[1] - k1[1]) / np.linalg.norm(k2[1] - k1[1]))
    return None


def meridian_meet(surfs, o_, a_, h_guess, r_guess):
    """(h, rho) where the two surfaces' meridians cross about their common axis, in closed form. The square
    root is clamped at 0, so a tangent pair (fillet/sphere, fillet/flank) meets exactly instead of softly."""
    def mer(s):
        k = s["kind"]
        if k == "plane":
            return ("h", float((s["d"] - s["n"] @ o_) / (s["n"] @ a_)))
        if k == "cylinder":
            return ("rho", s["R"])
        if k == "sphere":
            return ("circ", float((s["c"] - o_) @ a_), 0.0, s["R"])
        if k == "torus":
            return ("circ", float((s["o"] + s["a"] * s["hc"] - o_) @ a_), s["major"], s["minor"])
        sg = float(s["a"] @ a_); off = float((o_ - s["o"]) @ s["a"])   # cone: rho = k0 (sg h + off) + k1
        return ("line", s["k0"] * sg, s["k0"] * off + s["k1"])
    m1, m2 = sorted((mer(surfs[0]), mer(surfs[1])), key=lambda m_: ["h", "rho", "line", "circ"].index(m_[0]))
    sq = lambda x: math.sqrt(max(x, 0.0))  # noqa: E731
    near = lambda c1, c2, g: c1 if abs(c1 - g) <= abs(c2 - g) else c2  # noqa: E731
    if m1[0] == "h":
        h = m1[1]
        if m2[0] == "rho":
            return (h, m2[1])
        if m2[0] == "line":
            return (h, m2[1] * h + m2[2])
        if m2[0] == "circ":
            dr = sq(m2[3] ** 2 - (h - m2[1]) ** 2)
            return (h, near(m2[2] + dr, m2[2] - dr, r_guess) if m2[2] > 0 else dr)
    if m1[0] == "rho":
        rho = m1[1]
        if m2[0] == "line" and abs(m2[1]) > 1e-12:
            return ((rho - m2[2]) / m2[1], rho)
        if m2[0] == "circ":
            dh = sq(m2[3] ** 2 - (rho - m2[2]) ** 2)
            return (near(m2[1] + dh, m2[1] - dh, h_guess), rho)
    return None


def arc_edge(cen, nrm, Rc, A, B, pts, closed, VA, VB):
    xd = A - cen; xd = xd - (xd @ nrm) * nrm; xd /= np.linalg.norm(xd)
    def ang(p, nr):
        return math.atan2(float((p - cen) @ np.cross(nr, xd)), float((p - cen) @ xd)) % (2 * math.pi)
    if closed:
        # a "closed" chain that leaves a corner and comes back to it without going round (4 vertices along a sliver,
        # broom holder arm) is no circle: built as one it put two phantom full rims on an R 17 face
        a_ = [ang(p, nrm) for p in pts]
        if abs(sum(((a_[i + 1] - a_[i] + math.pi) % (2 * math.pi)) - math.pi for i in range(len(a_) - 1))) < math.pi:
            return None
        if ang(pts[1], nrm) > math.pi:
            nrm = -nrm
        th1 = 2 * math.pi
    else:
        # direction from the chain itself: the summed turn between consecutive points. The midpoint test alone built a
        # 12-degree rim arc as 348 degrees, and an arc whose two ends merged into one corner as a full circle
        # (broom holder arm: an R 17 face of 3430 mm2 for ~600)
        a_ = [ang(p, nrm) for p in pts]
        turn = sum(((a_[i + 1] - a_[i] + math.pi) % (2 * math.pi)) - math.pi for i in range(len(a_) - 1))
        if abs(turn) * Rc < 1e-6 * diag:
            return None          # both ends on one corner: a zero-length edge, dropped like a collapsed chain
        if turn < 0:
            nrm = -nrm
        th1 = ang(B, nrm)
        if th1 < 1e-12:
            th1 = 2 * math.pi
    return mk_edge(Geom_Circle(gp_Ax2(pnt(cen), gdir(nrm), gdir(xd)), Rc), VA, VB, 0.0, th1)


def iso_torus_snap(surfs, A, B, pts, VA, VB):
    """A chain that runs along one iso-parametric line of a torus IS that exact circle. Near a tangent corner the
    interpolated B-spline, and the p-curve projected from it, hook back on themselves; the hooked p-curve makes
    BRepClass_FaceClassifier call interior UV points OUT, so BRepExtrema_DistShapeShape rejects the surface hit and
    falls back to the boundary (mechparts/20 F9: dist_p95 1.286 vs 0.831, gate 0.005*diag). Projected from the exact
    iso circle the p-curve is a clean line. Opt-in: EB_ISO_SNAP=1."""
    du_tol = math.radians(float(os.environ.get("EB_ISO_SNAP_DEG", "5")))
    for s_ in surfs:
        if s_["kind"] != "torus" or "u" not in s_:
            continue
        C_ = s_["o"] + s_["a"] * s_["hc"]; e1_, e2_ = s_["u"], s_["w"]
        q_ = pts - C_; h_ = q_ @ s_["a"]; rad_ = q_ - np.outer(h_, s_["a"])
        rho_ = np.linalg.norm(rad_, axis=1)
        uu_ = np.unwrap(np.arctan2(rad_ @ e2_, rad_ @ e1_))
        vv_ = np.unwrap(np.arctan2(h_, rho_ - s_["major"]))
        if uu_.max() - uu_.min() > du_tol or s_["minor"] <= 1e-6 * diag:
            continue
        u0_ = float(uu_.mean())
        rad0_ = math.cos(u0_) * e1_ + math.sin(u0_) * e2_
        cen_ = C_ + s_["major"] * rad0_
        nrm_ = np.cross(s_["a"], rad0_)
        # keep A -> B order (vv_[0] is A, vv_[-1] is B): arc_edge picks the short way from the turn sign, and a
        # min->max ordering would make a chain that runs B->A come out as the long (270 deg) arc.
        iso_pts = np.array([cen_ + s_["minor"] * (math.cos(t) * rad0_ + math.sin(t) * s_["a"])
                            for t in np.linspace(float(vv_[0]), float(vv_[-1]), max(5, len(pts)))])
        # the other surface must follow the circle too (same 1e-4*diag limit as the tangent-circle rescue): a short
        # chain on a torus that is a real torus/cylinder curve, not an iso line, keeps its interpolated edge
        if any(float(np.abs(sdist(o_, iso_pts)).max()) > 1e-4 * diag for o_ in surfs if o_ is not s_):
            continue
        return (arc_edge(cen_, nrm_, s_["minor"], A, B, iso_pts, False, VA, VB), "iso-circle")
    return None


TOLC = 1e-7 * diag
ctypes = collections.Counter()
edges = {}
for cid, ch in enumerate(chains):
    vs = ch["verts"]; surfs = [S[ch["labs"][0]], S[ch["labs"][1]]]
    if ch["corner_ends"] and rep[vs[0]] == rep[vs[-1]] and vs[0] != vs[-1]:
        edges[cid] = None; ctypes["collapsed"] += 1; continue
    closed = vs[0] == vs[-1]
    inner, res = project(V[vs[1:-1]], surfs) if len(vs) > 2 else (np.zeros((0, 3)), np.zeros(0))
    circ_r = None     # (centre, axis, radius) when the rescue below put the chain on its closed-form circle
    if len(res) and res.max() > CORNER_TOL:
        # an EXACTLY tangent pair about a common axis (fillet torus on its plane, fillet on a sphere) has parallel
        # gradients along the whole curve, so point projection cannot converge; the curve is still known in closed
        # form. Put the inner points on that circle instead of failing (mechparts/1: fillet torus S28 on plane S45,
        # tangency constraint satisfied, projection stuck at 9.2e-3).
        ca_r = common_axis(*surfs)
        if os.environ.get("EB_DEBUG"):
            log(f"  RESCUE chain {cid} {surfs[0]['kind']}-{surfs[1]['kind']}: common axis {'none' if ca_r is None else np.round(ca_r[1], 8).tolist()}"
                + "".join(f", S{l_} axis/normal {np.round(S[l_].get('a', S[l_].get('n')), 8).tolist()}" for l_ in ch["labs"]))
        if ca_r is not None:
            o_r, a_r = ca_r; q_r = V[vs[1:-1]] - o_r; h_r = q_r @ a_r
            rad_r = q_r - np.outer(h_r, a_r); rr_r = np.linalg.norm(rad_r, axis=1)
            hr_r = meridian_meet(surfs, o_r, a_r, float(h_r.mean()), float(rr_r.mean()))
            if os.environ.get("EB_DEBUG"):
                log(f"    meridian meet {None if hr_r is None else np.round(hr_r, 6).tolist()}, chain height {h_r.min():.6f}..{h_r.max():.6f}, "
                    f"radius {rr_r.min():.6f}..{rr_r.max():.6f}, limit {1e-4 * diag:.2e}")
            # on an exactly tangent contact the region labels wander across the band where both surfaces coincide: a
            # chain vertex 0.175 mm off the circle still lies within 4.8e-3 of both (mechparts/28, R 64 fillet ring on
            # its top plane). The edge is still that circle.
            on_both_r = max(float(np.abs(sdist(s_, V[vs[1:-1]])).max()) for s_ in surfs) < 1e-5 * diag
            if os.environ.get("EB_DEBUG"):
                log(f"    on both surfaces: {[round(float(np.abs(sdist(s_, V[vs[1:-1]])).max()), 6) for s_ in surfs]} "
                    f"(limit {1e-5 * diag:.2e}) -> {on_both_r}")
            # a torus whose tube touches its plane exactly (the tangency constraint held) meets it on the circle
            # rho = major in closed form, however far the labels wander across the flat band (mechparts/28: chain
            # vertices up to 0.175 mm out and 3.4e-3 off a plane contaminated by 65 rim triangles)
            tan_r = False
            if hr_r is not None and {s_["kind"] for s_ in surfs} == {"plane", "torus"}:
                t_r = next(s_ for s_ in surfs if s_["kind"] == "torus")
                gap_r = abs(abs(hr_r[0] - float((t_r["o"] + t_r["a"] * t_r["hc"] - o_r) @ a_r)) - t_r["minor"])
                tan_r = gap_r < 1e-7 * diag
                if os.environ.get("EB_DEBUG"):
                    log(f"    torus-plane tangency gap {gap_r:.2e} (limit {1e-7 * diag:.2e}) -> {tan_r}")
            if (hr_r is not None and hr_r[1] > 1e-6 * diag and np.abs(h_r - hr_r[0]).max() < 1e-4 * diag
                    and (np.abs(rr_r - hr_r[1]).max() < 1e-4 * diag or on_both_r or tan_r)):
                inner = o_r + np.outer(np.full(len(h_r), hr_r[0]), a_r) + rad_r / np.maximum(rr_r[:, None], 1e-300) * hr_r[1]
                res = np.zeros(len(inner)); circ_r = (o_r + a_r * hr_r[0], a_r, hr_r[1])
    if len(res) and res.max() > CORNER_TOL:
        if os.environ.get("EB_DEBUG"):
            worst = V[vs[1:-1]][int(np.argmax(res))]
            log(f"  chain {cid} labels {ch['labs']} worst vertex {np.round(worst, 5).tolist()}")
            p_ = worst.reshape(1, 3).copy()
            for it_ in range(12):
                rr_ = [float(sdist(s_, p_)[0]) for s_ in surfs]
                G_ = np.stack([sgrad(s_, p_) for s_ in surfs], 1)
                sv_ = np.linalg.svd(G_[0], compute_uv=False)
                log(f"    it {it_} p {np.round(p_[0], 6).tolist()} f {rr_} sing {sv_.tolist()}")
                p_ = p_ - np.einsum("nij,nj->ni", np.linalg.pinv(G_, rcond=1e-10), np.array([rr_]))
        fail(f"chain {cid} between {surfs[0]['kind']} and {surfs[1]['kind']}: the surfaces do not meet there "
             f"(residual {res.max():.2e})")
    if ch["corner_ends"]:
        A = cpos[rep[vs[0]]]; B = cpos[rep[vs[-1]]]; VA = vert[rep[vs[0]]]; VB = vert[rep[vs[-1]]]
    elif circ_r is not None:
        # a rescued closed chain starts on its circle too: projecting its first vertex stalls on the tangent pair
        # like the inner points did, and one point 0.175 mm off turned the circle into a B-spline (mechparts/28)
        q0 = V[vs[0]] - circ_r[0]; q0 = q0 - (q0 @ circ_r[1]) * circ_r[1]
        A = B = circ_r[0] + q0 / np.linalg.norm(q0) * circ_r[2]; VA = VB = BRepBuilderAPI_MakeVertex(pnt(A)).Vertex()
    else:
        A = B = project(V[vs[0]], surfs)[0][0]; VA = VB = BRepBuilderAPI_MakeVertex(pnt(A)).Vertex()
    pts = np.vstack([A, inner, B])
    while len(pts) < 9:
        pts = densify(pts, surfs)
    made = None
    if not closed and os.environ.get("EB_ISO_SNAP"):
        made = iso_torus_snap(surfs, A, B, pts, VA, VB)
    kk_ = {s_["kind"]: s_ for s_ in surfs}
    if made is None and not closed and set(kk_) == {"plane", "cylinder"} and abs(float(kk_["cylinder"]["a"] @ kk_["plane"]["n"])) < 1e-9:
        # plane parallel to a cylinder axis: the intersection is one or two exact lines (one when tangent).
        # Projected points on a tangent pair are too soft for the 1e-7 line test (gearbox: a fillet's tangent
        # edge came out a B-spline and stayed unsewn)
        cy_, pl_ = kk_["cylinder"], kk_["plane"]
        dist_ = float(pl_["n"] @ cy_["o"] - pl_["d"]); foot = cy_["o"] - dist_ * pl_["n"]
        lat = np.cross(cy_["a"], pl_["n"]); off_ = math.sqrt(max(cy_["R"] ** 2 - dist_ ** 2, 0.0))
        c_mid = pts.mean(0)
        base_ = min((foot + off_ * lat, foot - off_ * lat), key=lambda b_: np.linalg.norm(np.cross(c_mid - b_, cy_["a"])))
        if np.linalg.norm(np.cross(pts - base_, cy_["a"]), axis=1).max() < 1e-5 * diag:
            made = (BRepBuilderAPI_MakeEdge(VA, VB).Edge(), "line")
    if (made is None and not closed and surfs[0]["kind"] == "cylinder" and surfs[1]["kind"] == "cylinder"
            and abs(abs(float(surfs[0]["a"] @ surfs[1]["a"])) - 1) < 1e-9):
        # parallel cylinders meet along lines parallel to the axis, through the points where their cross-section
        # circles cross; tangent ones along ONE line (sqrt clamped at 0). Built from projected points instead, an
        # exactly tangent fillet/ring pair gave a self-intersecting wire (Schlauchschelle with EB_CYL_CYL=1).
        c1_, c2_ = surfs
        a_ = c1_["a"]; u_, w_ = frame(a_)
        p1 = np.array([float(c1_["o"] @ u_), float(c1_["o"] @ w_)]); p2 = np.array([float(c2_["o"] @ u_), float(c2_["o"] @ w_)])
        dd = float(np.linalg.norm(p2 - p1))
        if dd > 1e-12:
            ex_ = (p2 - p1) / dd; ey_ = np.array([-ex_[1], ex_[0]])
            xx = (dd * dd + c1_["R"] ** 2 - c2_["R"] ** 2) / (2 * dd)
            yy = math.sqrt(max(c1_["R"] ** 2 - xx * xx, 0.0))
            c_mid = pts.mean(0); h_mid = float(c_mid @ a_)
            best_line = None
            for sgn_ in (1.0, -1.0):
                q2 = p1 + xx * ex_ + sgn_ * yy * ey_
                base_ = q2[0] * u_ + q2[1] * w_ + h_mid * a_
                dev_ = float(np.linalg.norm(np.cross(pts - base_, a_), axis=1).max())
                if best_line is None or dev_ < best_line:
                    best_line = dev_
            if best_line is not None and best_line < 1e-5 * diag:
                made = (BRepBuilderAPI_MakeEdge(VA, VB).Edge(), "line")
    ca = common_axis(*surfs) if made is None else None
    if ca is not None:
        o_, a_ = ca; q_ = pts - o_; hh = q_ @ a_; rr_ = np.linalg.norm(q_ - np.outer(hh, a_), axis=1)
        hr = meridian_meet(surfs, o_, a_, float(hh.mean()), float(rr_.mean()))
        if (hr is not None and hr[1] > 1e-6 * diag and np.abs(hh - hr[0]).max() < 1e-4 * diag
                and np.abs(rr_ - hr[1]).max() < 1e-4 * diag):
            made = (arc_edge(o_ + a_ * hr[0], a_, hr[1], A, B, pts, closed, VA, VB), "circle")
    if made is None and not closed:
        d = B - A; Ld = np.linalg.norm(d)
        if Ld > 0 and np.linalg.norm(np.cross(pts - A, d / Ld), axis=1).max() < TOLC:
            made = (BRepBuilderAPI_MakeEdge(VA, VB).Edge(), "line")
    if made is None:
        body_pts = pts[:-1] if closed else pts
        c = body_pts.mean(0); Q = pts - c; nrm = np.linalg.svd(body_pts - c)[2][-1]
        if np.abs(Q @ nrm).max() < TOLC:
            xa, ya = frame(nrm)
            X2, Y2 = Q @ xa, Q @ ya
            sol = np.linalg.lstsq(np.c_[2 * X2, 2 * Y2, np.ones(len(X2))], X2 ** 2 + Y2 ** 2, rcond=None)[0]
            Rc = math.sqrt(max(sol[2] + sol[0] ** 2 + sol[1] ** 2, 0.0)); cen = c + sol[0] * xa + sol[1] * ya
            if Rc > 0 and np.abs(np.linalg.norm(pts - cen, axis=1) - Rc).max() < TOLC:
                made = (arc_edge(cen, nrm, Rc, A, B, pts, closed, VA, VB), "circle")
    if made is None:
        for _ in range(6):
            use = pts[:-1] if closed else pts
            arr = TColgp_HArray1OfPnt(1, len(use))
            for i, p in enumerate(use):
                arr.SetValue(i + 1, pnt(p))
            ip = GeomAPI_Interpolate(arr, closed, 1e-12); ip.Perform()
            crv = ip.Curve(); u0, u1 = crv.FirstParameter(), crv.LastParameter()
            samp = np.array([[crv.Value(u).X(), crv.Value(u).Y(), crv.Value(u).Z()] for u in np.linspace(u0, u1, 6 * len(use))])
            dev = max(float(np.abs(sdist(s_, samp)).max()) for s_ in surfs)
            if dev < 1e-6 * diag:
                break
            pts = densify(pts, surfs)
        made = (mk_edge(crv, VA, VB, u0, u1), "bspline")
    edges[cid] = made[0]; ctypes[made[1]] += 1
    if os.environ.get("EB_DUMP_REGION") and any(str(l_) in os.environ["EB_DUMP_REGION"].split(",") for l_ in ch["labs"]):
        from OCP.BRepAdaptor import BRepAdaptor_Curve as _ACd
        _span = ""
        if made[0] is not None:
            _cd = _ACd(made[0]); _span = f", parameter span {math.degrees(_cd.LastParameter() - _cd.FirstParameter()):.2f} deg-or-units"
        log(f"  EDGE chain {cid} S{ch['labs'][0]}-S{ch['labs'][1]}: {len(vs)} mesh verts, closed {closed}, corner_ends {ch['corner_ends']}, "
            f"ends {np.round(V[vs[0]], 3).tolist()} -> {np.round(V[vs[-1]], 3).tolist()}, built {made[1]}{_span}")
log(f"edges {dict(ctypes)}")


def tangent_corner_tolerances(shape_):
    """Two arcs that meet TANGENTIALLY at a corner stay within their edge tolerances of each other for sqrt(2 Reff tol)
    either side of it, farther than the corner's 1e-7 tolerance, so BRepCheck calls the face's wire self-intersecting
    although the corner sits on the exact tangent point (mechparts/14: R 812.8 / R 177.8 and R 723.9 / R 304.8 on its
    plates, 0.3 um from the tangent points; valid once those corners admit 1e-3 mm). Give each tangent corner that
    contact zone. Runs on the finished solid: sewing rebuilds the vertices, so a tolerance set before it is lost."""
    from OCP.BRep import BRep_Tool as _BTt
    from OCP.BRepAdaptor import BRepAdaptor_Curve as _BACt
    from OCP.TopAbs import TopAbs_EDGE as _TEd
    from OCP.TopExp import TopExp as _TEt
    from OCP.gp import gp_Vec
    from OCP.TopAbs import TopAbs_VERTEX as _TVx
    from OCP.TopTools import TopTools_IndexedMapOfShape
    # group edge ends by the vertex itself: rounding positions to a grid split one corner's ends across two cells
    # (mechparts/14: 2 of the 3 tangent corners never paired)
    _vmap = TopTools_IndexedMapOfShape(); _TEt.MapShapes_s(shape_, _TVx, _vmap)
    _ends = collections.defaultdict(list); _vx = {}
    ex_ = TopExp_Explorer(shape_, _TEd)
    while ex_.More():
        e_ = TopoDS.Edge_s(ex_.Current()); ex_.Next()
        c_ = _BACt(e_); k_ = str(c_.GetType()).split("_")[-1]
        if k_ not in ("Circle", "Line") or _BTt.Degenerated_s(e_):
            continue
        ci_ = c_.Circle() if k_ == "Circle" else None
        for u_, vx_ in ((c_.FirstParameter(), _TEt.FirstVertex_s(e_)), (c_.LastParameter(), _TEt.LastVertex_s(e_))):
            p_ = gp_Pnt(); d_ = gp_Vec(); c_.D1(u_, p_, d_)
            t_ = np.array([d_.X(), d_.Y(), d_.Z()]); t_ = t_ / max(float(np.linalg.norm(t_)), 1e-300)
            k2_ = _vmap.FindIndex(vx_)
            _ends[k2_].append((t_, ci_, _BTt.Tolerance_s(e_))); _vx.setdefault(k2_, []).append(vx_)
    n_tan_ = 0
    for key_, ends_ in _ends.items():
        zone_ = 0.0
        for i_ in range(len(ends_)):
            for j_ in range(i_ + 1, len(ends_)):
                (t1, c1, e1), (t2, c2, e2) = ends_[i_], ends_[j_]
                if 1 - abs(float(t1 @ t2)) > 1e-8 or (c1 is None and c2 is None):
                    continue
                if c1 is not None and c2 is not None:
                    a1, a2 = c1.Axis().Direction(), c2.Axis().Direction()
                    if 1 - abs(a1.X() * a2.X() + a1.Y() * a2.Y() + a1.Z() * a2.Z()) > 1e-8:
                        continue          # not coplanar: not two arcs of one face
                    d_c = c1.Location().Distance(c2.Location()); R1, R2 = c1.Radius(), c2.Radius()
                    if abs(d_c - (R1 + R2)) <= abs(d_c - abs(R1 - R2)):
                        reff = R1 * R2 / (R1 + R2)
                    elif abs(R1 - R2) > 1e-9 * diag:
                        reff = R1 * R2 / abs(R1 - R2)
                    else:
                        continue          # the same circle continued: no contact zone
                else:
                    reff = (c1 or c2).Radius()
                zone_ = max(zone_, math.sqrt(2 * reff * (e1 + e2)))
        if zone_ > 0 and any(zone_ > _BTt.Tolerance_s(v_) for v_ in _vx[key_]):
            for v_ in _vx[key_]:
                BRep_Builder().UpdateVertex(v_, max(zone_, _BTt.Tolerance_s(v_)))
            n_tan_ += 1
    return n_tan_


# ---------------------------------------------------------------- 5. faces, shell, solid
def geom_surface(s, L):
    P = region_verts(L)
    if s["kind"] == "plane":
        c = P.mean(0); c = c - (c @ s["n"] - s["d"]) * s["n"]
        return Geom_Plane(gp_Ax3(pnt(c), gdir(s["n"]), gdir(frame(s["n"])[0])))
    if s["kind"] == "sphere":
        d = P.mean(0) - s["c"]; dn = np.linalg.norm(d)
        dirs = (P - s["c"]) / np.linalg.norm(P - s["c"], axis=1)[:, None]
        if dn > 1e-9 and float((dirs @ (d / dn)).min()) > math.cos(math.radians(80)):
            X = -d / dn; Z = frame(X)[0]            # seam and poles away from a region that spans < 80 deg
        else:
            Z = d / dn if dn > 1e-9 else np.array([0, 0, 1.0]); X = frame(Z)[0]
        return Geom_SphericalSurface(gp_Ax3(pnt(s["c"]), gdir(Z), gdir(X)), s["R"])
    q = P - s["o"]; h = q @ s["a"]; radial = (q - np.outer(h, s["a"])).mean(0)
    X = -radial / np.linalg.norm(radial) if np.linalg.norm(radial) > 1e-6 * diag else s["u"]
    if s["kind"] == "cylinder":
        return Geom_CylindricalSurface(gp_Ax3(pnt(s["o"] + s["a"] * h.mean()), gdir(s["a"]), gdir(X)), s["R"])
    if s["kind"] == "cone":
        href = float(h.mean()) if s["k0"] * h.mean() + s["k1"] > 0 else float(h.max())
        return Geom_ConicalSurface(gp_Ax3(pnt(s["o"] + s["a"] * href), gdir(s["a"]), gdir(X)),
                                   math.atan(s["k0"]), s["k0"] * href + s["k1"])
    return Geom_ToroidalSurface(gp_Ax3(pnt(s["o"] + s["a"] * s["hc"]), gdir(s["a"]), gdir(X)), s["major"], s["minor"])


sew = BRepBuilderAPI_Sewing(float(os.environ.get("EB_SEW_TOL", "1e-5")) * diag)   # EB_SEW_TOL: loosening probe rung
faces_presew = []
bb = BRep_Builder()
for L, s in S.items():
    ts = region_tris(L)
    cen = tri[ts].mean(1)
    sgn = float((sgrad(s, cen) * nt[ts] * area[ts, None]).sum())
    gs = geom_surface(s, L)
    apex_face = None
    if s["kind"] == "cone" and len(region_loops[L]) == 1 and len(region_loops[L][0]) == 1:
        # a cone that reaches its apex has one boundary circle and the apex inside: a face from that single wire
        # crashed OCCT (segfault, L01_cone). Build the exact lateral face from apex to base instead.
        hh_ = (region_verts(L) - s["o"]) @ s["a"]; h_apex = -s["k1"] / s["k0"]
        if min(abs(hh_.min() - h_apex), abs(hh_.max() - h_apex)) < 1e-3 * diag:
            from OCP.BRepPrimAPI import BRepPrimAPI_MakeCone
            h_base = float(hh_.max() if abs(hh_.max() - h_apex) > abs(hh_.min() - h_apex) else hh_.min())
            dir_ = s["a"] * math.copysign(1.0, h_base - h_apex); r_base = s["k0"] * h_base + s["k1"]
            prim = BRepPrimAPI_MakeCone(gp_Ax2(pnt(s["o"] + s["a"] * h_apex), gdir(dir_)), 0.0, float(r_base),
                                        float(abs(h_base - h_apex))).Shape()
            from OCP.GeomAbs import GeomAbs_Cone as _GCone
            from OCP.BRepAdaptor import BRepAdaptor_Surface as _BAS
            from OCP.TopAbs import TopAbs_FACE
            exa = TopExp_Explorer(prim, TopAbs_FACE)
            while exa.More():
                if _BAS(TopoDS.Face_s(exa.Current())).GetType() == _GCone:
                    apex_face = TopoDS.Face_s(exa.Current())
                exa.Next()
    torus_face = None
    edge_ov = {}          # chain id -> edge used on THIS face only (a rim restarted on the seam, see below)
    if (s["kind"] == "torus" and len(region_loops[L]) == 2
            and all(len(wl) == 1 and not chains[wl[0][0]]["corner_ends"] for wl in region_loops[L])):
        # a fillet ring bounded by two whole circles: healing a face built from those two wires kept one and left the
        # other circle free (mechparts/24: fillet tori at z -40 and -10, 1 free edge, p95 2.7 mm). Build the band
        # between the two tube angles directly; its circles sew to the neighbours' identical circles.
        C_t = s["o"] + s["a"] * s["hc"]

        def _tube_angle(p):
            q_t = p - C_t; h_t = float(q_t @ s["a"]); rho_t = float(np.linalg.norm(q_t - h_t * s["a"]))
            return math.atan2(h_t, rho_t - s["major"]) % (2 * math.pi)
        # bound the band by the built circles' own vertices: a tangent contact's mesh vertex wanders across the band
        # (mechparts/28: up to 0.175 mm), so its tube angle put the band rim 3e-4 off the neighbour's circle
        from OCP.BRep import BRep_Tool as _BT
        from OCP.TopExp import TopExp as _TE

        def _rim_point(cid_):
            if edges.get(cid_) is None:
                return V[chains[cid_]["verts"][0]]
            p_ = _BT.Pnt_s(_TE.FirstVertex_s(edges[cid_]))
            return np.array([p_.X(), p_.Y(), p_.Z()])
        v_lo, v_hi = sorted(_tube_angle(_rim_point(wl[0][0])) for wl in region_loops[L])
        v_mid = float(np.median([_tube_angle(c_) for c_ in cen]))
        if not v_lo <= v_mid <= v_hi:
            v_lo, v_hi = v_hi, v_lo + 2 * math.pi          # the band runs the other way round the tube
        mf_t = BRepBuilderAPI_MakeFace(gs, 0.0, 2 * math.pi, v_lo, v_hi, 1e-7)
        if mf_t.IsDone():
            torus_face = mf_t.Face()
    if (s["kind"] == "cylinder" and len(region_loops[L]) == 2 and not os.environ.get("EB_NO_CYL_BAND")
            and all(len(wl) == 1 and not chains[wl[0][0]]["corner_ends"] and edges.get(wl[0][0]) is not None
                    for wl in region_loops[L])):
        # a whole cylinder between two circles (a through hole, a bore): healing a face built from the two circle wires
        # splits one circle where its vertex misses the seam, into a full arc and a 4e-5 mm sliver, and sewing then
        # pairs the plane's circle with the sliver on one hole in four (mechparts/28 hole S4, 1 free edge). Build the band
        # between the two circles' heights instead, like the fillet ring band above; its circles sew to the neighbours'.
        from OCP.BRep import BRep_Tool as _BTc
        from OCP.BRepAdaptor import BRepAdaptor_Curve as _BACc
        from OCP.TopExp import TopExp as _TXc
        ax_c = gs.Position(); lo_c = ax_c.Location(); di_c = ax_c.Direction()

        def _coaxial_circle(e_):
            # the band's rims are isolines of the cylinder: only a circle on the cylinder's own axis is one. A hole ending
            # on a fillet torus is bounded by a torus-cylinder curve, and a band cut flat there was a wrong rim at every
            # hole (mechparts/27: 4 -> 20 free edges)
            c_ = _BACc(e_)
            if str(c_.GetType()).split("_")[-1] != "Circle":
                return False
            ci_ = c_.Circle(); a_ = ci_.Axis().Direction(); p_ = ci_.Location()
            q_ = np.array([p_.X() - lo_c.X(), p_.Y() - lo_c.Y(), p_.Z() - lo_c.Z()]); d_ = np.array([di_c.X(), di_c.Y(), di_c.Z()])
            return (abs(abs(a_.X() * d_[0] + a_.Y() * d_[1] + a_.Z() * d_[2]) - 1) < 1e-9
                    and float(np.linalg.norm(q_ - (q_ @ d_) * d_)) < 1e-6 * diag)

        def _v_c(cid_):
            p_ = _BTc.Pnt_s(_TXc.FirstVertex_s(edges[cid_]))
            return (p_.X() - lo_c.X()) * di_c.X() + (p_.Y() - lo_c.Y()) * di_c.Y() + (p_.Z() - lo_c.Z()) * di_c.Z()
        if all(_coaxial_circle(edges[wl[0][0]]) for wl in region_loops[L]):
            v_c = sorted(_v_c(wl[0][0]) for wl in region_loops[L])
            mf_c = BRepBuilderAPI_MakeFace(gs, 0.0, 2 * math.pi, v_c[0], v_c[1], 1e-7)
            if mf_c.IsDone() and v_c[1] - v_c[0] > 1e-6 * diag:
                torus_face = mf_c.Face()     # served by the same one-face path as the fillet ring band
        else:
            # one rim is not a circle (a hole ending on a fillet torus): healing adds the seam at u = 0 and splits any rim
            # whose vertex is not on it into its edge and a sliver of up to 2.5e-4 mm; sewing drops some slivers and keeps
            # others as free edges (mechparts/27: 4 holes of 10). Put the seam through the curved rim's vertex and
            # restart each circular rim at that same angle, so there is nothing to split.
            nonc_ = [wl[0][0] for wl in region_loops[L] if not _coaxial_circle(edges[wl[0][0]])]
            if len(nonc_) == 1:
                p_ = _BTc.Pnt_s(_TXc.FirstVertex_s(edges[nonc_[0]]))
                d_ = np.array([di_c.X(), di_c.Y(), di_c.Z()])
                q_ = np.array([p_.X() - lo_c.X(), p_.Y() - lo_c.Y(), p_.Z() - lo_c.Z()]); r_ = q_ - (q_ @ d_) * d_
                if float(np.linalg.norm(r_)) > 1e-6 * diag:
                    X_ = r_ / np.linalg.norm(r_)
                    gs = Geom_CylindricalSurface(gp_Ax3(lo_c, di_c, gdir(X_)), s["R"])
                    for wl in region_loops[L]:
                        cid_ = wl[0][0]
                        if cid_ == nonc_[0]:
                            continue
                        ci_ = _BACc(edges[cid_]).Circle()
                        ax2_ = gp_Ax2(ci_.Location(), ci_.Axis().Direction(), gdir(X_))
                        mk_ = BRepBuilderAPI_MakeEdge(Geom_Circle(ax2_, ci_.Radius()), 0.0, 2 * math.pi)
                        if mk_.IsDone():
                            edge_ov[cid_] = mk_.Edge()
    if apex_face is not None:
        faces_out = [apex_face]; sgn = 1.0          # the primitive's lateral face is already outward
    elif torus_face is not None:
        faces_out = [torus_face]
    elif not region_loops[L]:
        faces_out = [BRepBuilderAPI_MakeFace(gs, 1e-7).Face()]
    else:
        # a PLANE region can hold several OUTER loops: separate faces lying on one plane (mechparts/1: four side planes,
        # outer loops of 398.4 and 4.8 mm2, no shared vertex). A face takes one outer wire, so ShapeFix_Face kept the big
        # loop and dropped the small one, leaving its edges free. One face per outer loop, with the holes inside it.
        # (Periodic surfaces are left alone: their 2 -> 1 wire merge through the seam is normal and harmless.)
        groups = [list(range(len(region_loops[L])))]
        if s["kind"] in ("cylinder", "cone") and len(region_loops[L]) > 1:
            # a partial cylinder with SEPARATE boundary loops (broom holder arm: an R 0.68 fillet interrupted by a slot)
            # is separate faces. Only a band that goes all the way round has two loops bounding one face; a loop that
            # goes round turns 2 pi about the axis, a lobe's loop turns 0.
            # A hole in the face also turns 0, so loops are told apart like on a plane: signed area in the unrolled
            # (angle, height) coordinates, the largest loop is an outer boundary, loops of its sign are other outer
            # boundaries (other faces), loops of the opposite sign are holes and stay with the outer loop around them.
            u_c, w_c = frame(s["a"]); turns_c = []; uv_c = []
            for wl in region_loops[L]:
                pts_c = []
                for cid, fwd in wl:
                    vs_c = chains[cid]["verts"] if fwd else chains[cid]["verts"][::-1]
                    pts_c.extend(V[vs_c[:-1]])
                ang_c = [math.atan2(float((p - s["o"]) @ w_c), float((p - s["o"]) @ u_c)) for p in pts_c]
                steps_c = [((ang_c[(i + 1) % len(ang_c)] - ang_c[i] + math.pi) % (2 * math.pi)) - math.pi for i in range(len(ang_c))]
                turns_c.append(abs(sum(steps_c)) if len(ang_c) >= 2 else 0.0)
                th_c = np.concatenate([[ang_c[0]], ang_c[0] + np.cumsum(steps_c[:-1])]) if ang_c else np.zeros(0)
                uv_c.append(np.c_[th_c, [float((p - s["o"]) @ s["a"]) for p in pts_c]] if pts_c else np.zeros((0, 2)))
            if all(t_ < math.pi for t_ in turns_c):
                area_c = [0.5 * float(np.sum(q[:, 0] * np.roll(q[:, 1], -1) - np.roll(q[:, 0], -1) * q[:, 1])) if len(q) >= 3 else 0.0
                          for q in uv_c]
                big_c = int(np.argmax(np.abs(area_c))); sign_c = math.copysign(1.0, area_c[big_c])
                # ponytail: a same-sign loop under a tenth of the largest stays with it (broom holder arm 2: loops of 0.027
                # and 0.62 beside 4.7 and 25 built as zero-area faces with self-intersecting wires); real separate lobes
                # measured 0.97-1.0 of each other. Revisit if a part has genuinely small separate curved faces.
                outer_c = [i for i, a_ in enumerate(area_c) if a_ * sign_c > 0.1 * abs(area_c[big_c])]
                if len(outer_c) > 1:
                    def _inside_c(pt, poly):
                        x, y = pt; inside = False; n_ = len(poly)
                        for k in range(n_):
                            x1, y1 = poly[k]; x2, y2 = poly[(k + 1) % n_]
                            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-300) + x1:
                                inside = not inside
                        return inside
                    groups = [[i] for i in outer_c]
                    for j, a_ in enumerate(area_c):
                        if j in outer_c or len(uv_c[j]) == 0:
                            continue
                        host = [g for g in groups if _inside_c(uv_c[j][0], uv_c[g[0]])]
                        (host[0] if host else groups[0]).append(j)
                    log(f"  {s['kind']} S{L}: loop areas {[round(a_, 4) for a_ in area_c]} -> {len(groups)} faces")
        if s["kind"] == "plane" and len(region_loops[L]) > 1 and not os.environ.get("EB_NO_PLANE_SPLIT"):
            u_g, w_g = frame(s["n"]); polys = []
            for wl in region_loops[L]:
                pts_g = []
                for cid, fwd in wl:
                    vs_g = chains[cid]["verts"] if fwd else chains[cid]["verts"][::-1]
                    pts_g.extend(V[vs_g[:-1]])
                P2g = np.array([[float(p @ u_g), float(p @ w_g)] for p in pts_g]) if pts_g else np.zeros((0, 2))
                ar_g = (0.5 * float(np.sum(P2g[:, 0] * np.roll(P2g[:, 1], -1) - np.roll(P2g[:, 0], -1) * P2g[:, 1]))
                        if len(P2g) >= 3 else 0.0)
                polys.append((P2g, ar_g))
            outer_idx = [i for i, (_, a_) in enumerate(polys) if a_ > 0]
            if len(outer_idx) > 1:
                def _inside(pt, poly):
                    x, y = pt; inside = False; n_ = len(poly)
                    for k in range(n_):
                        x1, y1 = poly[k]; x2, y2 = poly[(k + 1) % n_]
                        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-300) + x1:
                            inside = not inside
                    return inside
                groups = [[i] for i in outer_idx]
                for j, (P2h, a_h) in enumerate(polys):
                    if a_h > 0 or len(P2h) == 0:
                        continue
                    host = [g for g in groups if _inside(P2h[0], polys[g[0]][0])]
                    (host[0] if host else groups[0]).append(j)
                log(f"  plane S{L}: {len(outer_idx)} outer loops -> {len(groups)} faces")
        def _nwires(f_):
            from OCP.TopAbs import TopAbs_WIRE as _TW
            e_ = TopExp_Explorer(f_, _TW); k_ = 0
            while e_.More():
                k_ += 1; e_.Next()
            return k_
        faces_out = []
        for grp in groups:
            face = TopoDS_Face(); bb.MakeFace(face, gs, TopLoc_Location(), 1e-7)
            n_loops_added = 0
            for li in grp:
                wl = region_loops[L][li]
                seq = [(cid, fwd) for cid, fwd in wl if edges[cid] is not None]
                if not seq:
                    continue     # every edge of this loop collapsed to a point: a zero-area sliver loop (broom holder arm)
                n_loops_added += 1
                if sgn < 0:
                    seq = [(cid, not fwd) for cid, fwd in reversed(seq)]
                mw = BRepBuilderAPI_MakeWire()
                for cid, fwd in seq:
                    e_use = edge_ov.get(cid, edges[cid])
                    mw.Add(e_use if fwd else TopoDS.Edge_s(e_use.Reversed()))
                if not mw.IsDone():
                    fail(f"face {L} ({s['kind']}): its boundary does not close (wire error {mw.Error()})")
                bb.Add(face, mw.Wire())
            if n_loops_added == 0:
                log(f"  face S{L} ({s['kind']}) dropped: all its boundary edges collapsed")
                continue
            n_before = _nwires(face)
            sf = ShapeFix_Face(face); sf.SetPrecision(1e-7 * diag); sf.SetMaxTolerance(1e-3 * diag); sf.Perform()
            face = sf.Face()
            if os.environ.get("EB_DEBUG") and _nwires(face) < n_before:
                # face healing removed a boundary: its edges are then left free on the neighbouring faces
                log(f"  WIRE DROPPED by ShapeFix_Face on S{L} ({s['kind']}): {n_before} -> {_nwires(face)} wires, {len(grp)} loops in this face")
            if os.environ.get("EB_DUMP_REGION") and str(L) in os.environ["EB_DUMP_REGION"].split(","):
                from OCP.GProp import GProp_GProps as _GPd
                from OCP.BRepGProp import BRepGProp as _BGd
                _g = _GPd(); _BGd.SurfaceProperties_s(face, _g)
                log(f"  face S{L} ({s['kind']}): {len(grp)} loops -> {n_before} wires built -> "
                    f"{_nwires(face)} wires after ShapeFix_Face, area {_g.Mass():.3f}")
            faces_out.append(face)
    for face in faces_out:
        if sgn < 0:
            face = TopoDS.Face_s(face.Reversed())
        sew.Add(face)
        faces_presew.append(face)
if os.environ.get("EB_DUMP_FACES"):
    # the oriented faces exactly as handed to sewing, to replay sewing offline in seconds instead of a full rebuild
    from OCP.BRepTools import BRepTools as _BRT
    from OCP.TopoDS import TopoDS_Compound as _TDC
    _cmp = _TDC(); BRep_Builder().MakeCompound(_cmp)
    for _f in faces_presew:
        BRep_Builder().Add(_cmp, _f)
    _BRT.Write_s(_cmp, os.environ["EB_DUMP_FACES"])
    log(f"dumped {len(faces_presew)} pre-sewing faces to {os.environ['EB_DUMP_FACES']}")
sew.Perform()
sewn = sew.SewedShape()
log(f"sewn {len(S)} faces, free edges {sew.NbFreeEdges()}, multiple edges {sew.NbMultipleEdges()}")
if os.environ.get("EB_DEBUG") and sew.NbFreeEdges():
    # the OWNING face of each free edge in the sewn shape: "nearest surfaces" misleads for short fillet arcs, which sit
    # within 1e-3 of two planes (mechparts/1: 7 of 12 free circles reported as plane/plane)
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape as _EFmap
    from OCP.TopExp import TopExp as _TE
    from OCP.TopAbs import TopAbs_EDGE as _TEd, TopAbs_FACE as _TFa
    from OCP.BRepAdaptor import BRepAdaptor_Surface as _ASf
    from OCP.GProp import GProp_GProps as _GPf
    from OCP.BRepGProp import BRepGProp as _BGf
    _ef = _EFmap(); _TE.MapShapesAndAncestors_s(sewn, _TEd, _TFa, _ef)
    _kinds_free = collections.Counter()
    for _i in range(1, _ef.Extent() + 1):
        _faces = _ef.FindFromIndex(_i)
        if _faces.Extent() != 1:
            continue
        _f = TopoDS.Face_s(_faces.First()); _ad = _ASf(_f); _t = str(_ad.GetType()).split("_")[-1]
        _g = _GPf(); _BGf.SurfaceProperties_s(_f, _g)
        _extra = f" R {_ad.Cylinder().Radius():.4f}" if _t == "Cylinder" else (f" minor {_ad.Torus().MinorRadius():.4f}" if _t == "Torus" else "")
        _kinds_free[f"{_t}{_extra}"] += 1
    log(f"  free edges by OWNING face: {dict(_kinds_free)}")
    # every free edge with owner, curve and midpoint, then pairs by midpoint: the SAME curve built twice with different
    # end vertices pairs up closely; a curve with no partner means a face lost or never got that boundary
    from OCP.BRepAdaptor import BRepAdaptor_Curve as _ACf
    _fe_rows = []
    for _i in range(1, _ef.Extent() + 1):
        _faces = _ef.FindFromIndex(_i)
        if _faces.Extent() != 1:
            continue
        _e = TopoDS.Edge_s(_ef.FindKey(_i)); _cu = _ACf(_e); _u0, _u1 = _cu.FirstParameter(), _cu.LastParameter()
        _pm = _cu.Value(0.5 * (_u0 + _u1)); _pa = _cu.Value(_u0); _pb = _cu.Value(_u1)
        _fo = TopoDS.Face_s(_faces.First()); _ad = _ASf(_fo); _t = str(_ad.GetType()).split("_")[-1]
        _own = f"{_t}{' R %.4f' % _ad.Cylinder().Radius() if _t == 'Cylinder' else ''}"
        _fe_rows.append((np.array([_pm.X(), _pm.Y(), _pm.Z()]), np.array([_pa.X(), _pa.Y(), _pa.Z()]), np.array([_pb.X(), _pb.Y(), _pb.Z()]),
                         str(_cu.GetType()).split("_")[-1], _own))
    _used = set()
    for _a in range(len(_fe_rows)):
        if _a in _used:
            continue
        _best = min((b for b in range(len(_fe_rows)) if b != _a and b not in _used),
                    key=lambda b: float(np.linalg.norm(_fe_rows[b][0] - _fe_rows[_a][0])), default=None)
        _ma, _ea0, _ea1, _ca, _oa = _fe_rows[_a]
        if _best is not None and float(np.linalg.norm(_fe_rows[_best][0] - _ma)) < 1e-2 * diag:
            _mb, _eb0, _eb1, _cb, _ob = _fe_rows[_best]; _used.update((_a, _best))
            _end_gap = min(float(np.linalg.norm(_ea0 - _eb0)) + float(np.linalg.norm(_ea1 - _eb1)),
                           float(np.linalg.norm(_ea0 - _eb1)) + float(np.linalg.norm(_ea1 - _eb0)))
            log(f"  FREE PAIR {_ca}/{_oa} <-> {_cb}/{_ob}: mid gap {float(np.linalg.norm(_mb - _ma)):.2e}, end-vertex gap {_end_gap:.2e}, "
                f"mid {np.round(_ma, 2).tolist()}")
        else:
            _used.add(_a)
            log(f"  FREE ALONE {_ca}/{_oa}: mid {np.round(_ma, 2).tolist()} length {float(np.linalg.norm(_ea1 - _ea0)):.3f}")
    # which regions sit at each free edge, and how well each fits its own vertices: a face boundary that lands 0.5 mm
    # from its neighbour's (mechparts/1) means some region there does not lie on its surface
    # plane regions that do NOT lie on their plane (the mixed-region pass only examines curved regions): mechparts/1's
    # S48 misses its own vertices by 1.4e-3 while every free edge lies on a neighbouring, exactly fitted plane
    for _Lp, _sp in S.items():
        if _sp["kind"] != "plane":
            continue
        _dv = sdist(_sp, region_verts(_Lp))
        if float(np.abs(_dv).max()) < 1e-5 * diag:
            continue
        _tp = region_tris(_Lp); _nt_p = nt[_tp]
        _hist = np.histogram(_dv, bins=6)
        _nbp = collections.Counter(S[M_]["kind"] for M_ in adj.get(_Lp, set()) if M_ in S) if isinstance(adj, dict) else {}
        log(f"  PLANE NOT ON ITS PLANE S{_Lp}: {len(_tp)} tris, n {np.round(_sp['n'], 5).tolist()} d {_sp['d']:.4f}, "
            f"vertex distance min {float(_dv.min()):+.2e} max {float(_dv.max()):+.2e}, histogram counts {_hist[0].tolist()} "
            f"edges {np.round(_hist[1], 4).tolist()}, facet-normal spread {math.degrees(math.acos(max(-1.0, min(1.0, float((_nt_p @ _sp['n']).min()))))):.2f} deg, "
            f"neighbour kinds {dict(_nbp)}")
    # distance from each free edge's midpoint and ends to the MESH SURFACE (closest point on the triangles; triangle
    # centres misled on a 250 mm part with large flat facets), and the region of the nearest triangle
    import trimesh as _tm
    _mesh_q = _tm.Trimesh(V, F, process=False)
    for _m_fe, _e0_fe, _e1_fe, _c_fe, _o_fe in _fe_rows[:12]:
        _pts_q = np.vstack([_m_fe, _e0_fe, _e1_fe])
        _cp, _dq, _tq = _tm.proximity.closest_point(_mesh_q, _pts_q)
        _Ln = int(label[int(_tq[0])])
        _own = f"S{_Ln}:{S[_Ln]['kind']} own-fit max {float(np.abs(sdist(S[_Ln], region_verts(_Ln))).max()):.1e}" if _Ln in S else f"label {_Ln} (no surface)"
        _surf_d = f", distance to S{_Ln} {float(abs(sdist(S[_Ln], _m_fe)[0])):.2e}" if _Ln in S else ""
        log(f"  AT FREE {_c_fe}/{_o_fe} mid {np.round(_m_fe, 2).tolist()}: to mesh mid {_dq[0]:.2e} ends {_dq[1]:.2e}/{_dq[2]:.2e}; "
            f"nearest triangle in {_own}{_surf_d}")
if os.environ.get("EB_DEBUG"):
    from OCP.BRepAdaptor import BRepAdaptor_Curve as _AC
    for _i in range(1, min(sew.NbFreeEdges(), 12) + 1):
        _c = _AC(sew.FreeEdge(_i)); _u = 0.5 * (_c.FirstParameter() + _c.LastParameter()); _p = _c.Value(_u)
        _pp = np.array([_p.X(), _p.Y(), _p.Z()])
        near = sorted(S, key=lambda L_: abs(float(sdist(S[L_], _pp)[0])))[:2]
        log(f"  FREE edge {_i}: {str(_c.GetType()).split('_')[-1]} mid {np.round(_pp, 3).tolist()} "
            f"length {_c.LastParameter() - _c.FirstParameter():.3f} nearest surfaces "
            + ", ".join(f"S{L_}:{S[L_]['kind']}" for L_ in near))
if os.environ.get("EB_FAST_FAIL") and sew.NbFreeEdges():
    # set by the probe: a shell with free edges can never pass the gate (free_edges must be 0), and healing, the
    # tangent pass and measuring an open solid cost 740 of 972 s on one mechparts/31 variant
    fail(f"{sew.NbFreeEdges()} free edges after sewing")
ms = BRepBuilderAPI_MakeSolid()
ex = TopExp_Explorer(sewn, TopAbs_SHELL)
n_shells = 0
while ex.More():
    ms.Add(TopoDS.Shell_s(ex.Current())); ex.Next(); n_shells += 1
if n_shells == 0:
    # sewing a single closed face (a whole sphere) returns the face, not a shell: the solid came out empty and
    # the STEP read back as a NULL shape (L01_sphere)
    from OCP.TopoDS import TopoDS_Shell
    from OCP.TopAbs import TopAbs_FACE as _TAF
    sh_ = TopoDS_Shell(); bb.MakeShell(sh_)
    exf = TopExp_Explorer(sewn, _TAF)
    while exf.More():
        bb.Add(sh_, exf.Current()); exf.Next()
    ms.Add(sh_)
try:
    fx = ShapeFix_Solid(ms.Solid()); fx.Perform()
    shape = fx.Solid()
except Exception as exc:  # noqa: BLE001 - L10_gearbox: Geom_TrimmedCurve range error inside the healer
    from OCP.BRepLib import BRepLib
    log(f"  ShapeFix_Solid failed ({str(exc)[:60]}); orienting the closed solid directly")
    shape = ms.Solid(); BRepLib.OrientClosedSolid_s(shape)
if not BRepCheck_Analyzer(shape).IsValid():
    n_tan = tangent_corner_tolerances(shape)
    if n_tan:
        log(f"{n_tan} corners where arcs meet tangentially: vertex tolerance raised to their contact zone")
log(f"solid valid {BRepCheck_Analyzer(shape).IsValid()}  ({time.time() - T0:.1f} s)")
# (building about the bounding-box centre, EB_RECENTER, was tried 2026-09-15 and removed: mechparts/30, sound at its
# 6.7 m offset, failed 7 corners once recentred, and 20 / 17 got no better)
w = STEPControl_Writer(); w.Transfer(shape, STEPControl_AsIs); w.Write(str(out))
# EB_BODY builds one body of a multi-body mesh: judge it against that body, not against the whole file
mm = measure(out, np.asarray(body.triangles) if os.environ.get("EB_BODY") else _mesh(src), samples=300)
if mm is None:
    fail("written STEP does not read back")
if not mm["valid"]:
    # a STEP file has no per-vertex tolerance: read back, every corner is 1e-7 again and tangent arcs "self-intersect"
    # (mechparts/14). Judge the read-back solid with the tangent corners' contact zone (user decision 2026-09-15).
    from mesh2step.feature import _read
    from OCP.BRepCheck import BRepCheck_Analyzer as _BCA
    rb_ = _read(out)
    if rb_ is not None and tangent_corner_tolerances(rb_) and _BCA(rb_).IsValid():
        mm["valid"] = True
        log("read-back solid valid once its tangent-arc corners carry their contact zone")
log("RESULT", {k: (round(v, 5) if isinstance(v, float) else v) for k, v in mm.items() if k != "radii"},
    "radii", sorted({round(x, 4) for x in mm["radii"]}))
