"""Scan / remeshed-mesh cleaner: fit analytic surfaces within the mesh's OWN noise and move every vertex onto them, so
the exact-geometry pipeline (engine, edgebuild, feature builders) sees a CAD-like tessellation.

Why: every stage downstream finds surfaces by exact agreement (a plane to 1e-5 of the diagonal, circles exact). A CAD
export meets that (24 % of neighbouring triangles exactly coplanar on mechparts/7); a scan or a remeshed file meets it
nowhere (0 % on the owner's mechpart and Collarino), so all four of his real-world files came back as one planar face
per triangle (2026-09-29). Nothing downstream changes: this only moves vertices, never removes or adds any.

1. noise: the 25th percentile of the local PCA residual (16 nearest vertices): flat neighbourhoods dominate it.
2. regions: seeds in order of local flatness grow a compact patch over smooth neighbours; the simplest surface
   (plane, cylinder, cone, sphere, torus) that fits it within TOL_K x noise is grown over neighbours that lie on it
   and face like it, refitted as it doubles.
3. snap: a vertex of one region goes onto that surface, a vertex of two or more onto their common points
   (alternating projections). Vertices of unassigned triangles do not move.

usage: denoise.py <in.stl> <out.stl> [labels.npz]        (one JSON report line on stdout)"""
import json
import math
import sys

import numpy as np
import trimesh
from scipy.spatial import cKDTree

TOL_K = 3.0            # surface tolerance in units of the measured noise
MIN_AREA = 2e-4        # smallest region kept, share of the mesh area
# neighbouring triangles of a seed patch may turn this much: a 2 mm round at 1.4 mm triangles (mechpart pocket corners)
# turns ~30 degrees per triangle; sharp edges of machined and cast parts are 45+
PATCH_COS = math.cos(math.radians(18))   # 32 degrees was tried: coverage 98.7 -> 97.3 %, inexact vertices 303 -> 855
PATCH = 120            # faces in a seed patch: enough to show curvature above the noise
# a vertex may move this many tolerances onto the common point of its surfaces: a scanned edge is rounded (cast part,
# mechpart: 238 two-region vertices 1-2 mm from their faces' corner), and the corner is the edge the model has
MOVE_K = 5.0
GROW_ANGLE = math.cos(math.radians(25))   # a grown face must face like the surface there


# ---------- surfaces: fit, signed distance, normal, closest point ----------
def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-300)


def _circle2(x, y):
    """Algebraic circle fit -> (cx, cy, r)."""
    A = np.c_[2 * x, 2 * y, np.ones_like(x)]
    s, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    return s[0], s[1], math.sqrt(max(s[2] + s[0] ** 2 + s[1] ** 2, 0.0))


def _meridian(s, P):
    q = P - s["o"]; h = q @ s["a"]; rv = q - np.outer(h, s["a"])
    return h, np.linalg.norm(rv, axis=1), rv


def fit(kind, P, N, diag, X):
    """Least-squares surface of `kind` through points P, from the (smoothed) normals N at the face centres X."""
    c = P.mean(0)
    if kind == "plane":
        n = np.linalg.eigh(np.cov((P - c).T))[1][:, 0]
        return {"kind": kind, "n": n, "d": float(n @ c)}
    if kind == "sphere":
        A = np.c_[2 * P, np.ones(len(P))]
        s, *_ = np.linalg.lstsq(A, (P * P).sum(1), rcond=None)
        R = math.sqrt(max(s[3] + s[:3] @ s[:3], 0.0))
        return {"kind": kind, "o": s[:3], "R": R} if 0 < R < diag else None
    if kind == "cylinder":
        a = np.linalg.eigh(N.T @ N)[1][:, 0]              # normals are perpendicular to the axis
        u = _unit(np.cross(a, [1.0, 0, 0] if abs(a[0]) < 0.9 else [0, 1.0, 0])); v = np.cross(a, u)
        cx, cy, R = _circle2(P @ u, P @ v)
        return {"kind": kind, "a": a, "o": cx * u + cy * v, "R": R} if 0 < R < diag else None
    if kind == "cone":
        a = np.linalg.eigh(np.cov(N.T))[1][:, 0]           # n.a is constant on a cone
        if abs(np.mean(N @ a)) < 0.05 or abs(np.mean(N @ a)) > 0.995:
            return None                                     # that is a cylinder or a plane
        C = N.T @ N; apex = np.linalg.lstsq(C, N.T @ np.einsum("ij,ij->i", N, X), rcond=None)[0]
        s = {"kind": kind, "a": a, "o": apex}
        h, rho, _ = _meridian(s, P); k = np.polyfit(h, rho, 1)
        s["k"] = k
        return s if np.linalg.norm(apex - c) < diag else None
    if kind == "torus":                                    # normal lines meet the axis (Pottmann and Randrup)
        L = np.c_[np.cross(X, N), N]
        ev, evec = np.linalg.eigh(L.T @ L)
        a, abar = evec[:3, 0], evec[3:, 0]                # (x cross d).a + d.abar = 0: a direction, abar moment
        na = np.linalg.norm(a)
        if na < 1e-6:
            return None
        a, abar = a / na, abar / na
        s = {"kind": kind, "a": a, "o": np.cross(a, abar)}
        h, rho, _ = _meridian(s, P)
        hc, Rc, r = _circle2(h, rho)
        s.update(hc=hc, Rc=Rc, r=r)
        return s if (r < Rc < diag and r > 0) or (0 < r < diag and Rc > 0) else None
    raise ValueError(kind)


def sdist(s, P):
    k = s["kind"]
    if k == "plane":
        return P @ s["n"] - s["d"]
    if k == "sphere":
        return np.linalg.norm(P - s["o"], axis=1) - s["R"]
    h, rho, _ = _meridian(s, P)
    if k == "cylinder":
        return rho - s["R"]
    if k == "cone":
        k1, k0 = s["k"]
        return (rho - (k1 * h + k0)) / math.hypot(1.0, k1)
    return np.hypot(h - s["hc"], rho - s["Rc"]) - s["r"]


def normal(s, P):
    k = s["kind"]
    if k == "plane":
        return np.broadcast_to(s["n"], P.shape)
    if k == "sphere":
        return _unit(P - s["o"])
    h, rho, rv = _meridian(s, P)
    ur = rv / np.maximum(rho, 1e-300)[:, None]
    if k == "cylinder":
        return ur
    if k == "cone":
        k1 = s["k"][0]
        return _unit(ur - k1 * s["a"])
    dh, dr = h - s["hc"], rho - s["Rc"]
    return _unit(dr[:, None] * ur + dh[:, None] * s["a"])


def project(s, P):
    return P - sdist(s, P)[:, None] * normal(s, P)


def common_point(surfs, x0, eps):
    """The point on every surface nearest x0 (Newton, minimum-norm steps: 1 surface = its foot, 2 = the curve they
    share, 3 = their corner); None if they share no point near x0 or more than 3 are over-determined."""
    if len(surfs) == 1:
        return project(surfs[0], x0)
    if len(surfs) > 3:
        return None
    x = x0.copy()
    for _ in range(100):                               # tangent surfaces converge linearly, not quadratically
        f = np.array([sdist(s_, x)[0] for s_ in surfs])
        if np.abs(f).max() < eps:
            return x
        J = np.array([normal(s_, x)[0] for s_ in surfs])
        x = x - (np.linalg.pinv(J, rcond=1e-6) @ f)[None, :]
    f = np.array([sdist(s_, x)[0] for s_ in surfs])
    return x if np.abs(f).max() < eps else None


# ---------- tangent-constrained refit ----------
def pack(s):
    k = s["kind"]
    if k == "sphere":
        return np.r_[s["o"], s["R"]]
    if k == "cylinder":
        return np.r_[s["a"], s["o"], s["R"]]
    if k == "cone":
        return np.r_[s["a"], s["o"], s["k"]]
    if k == "torus":
        return np.r_[s["a"], s["o"], s["hc"], s["Rc"], s["r"]]
    return None                                            # planes are references, never refitted here


def unpack(kind, x):
    if kind == "sphere":
        return {"kind": kind, "o": x[:3], "R": x[3]}
    a = _unit(x[:3])
    if kind == "cylinder":
        return {"kind": kind, "a": a, "o": x[3:6], "R": x[6]}
    if kind == "cone":
        return {"kind": kind, "a": a, "o": x[3:6], "k": x[6:8]}
    return {"kind": kind, "a": a, "o": x[3:6], "hc": x[6], "Rc": x[7], "r": x[8]}


def tangent_refit(S, V, vreg, label, area):
    """A curved region meeting a neighbour tangentially (a fillet into a face) is refitted to its own vertices AND to
    touch that neighbour, normal to normal, along their shared border. Fitted separately at scan noise the two miss
    each other by a hair and share no curve at all (mechpart: 195 of 356 inexact vertices were such borders), so
    nothing downstream can build the edge. The neighbour is the reference: a plane always, else the larger region."""
    from scipy.optimize import least_squares
    share = {L_: float(area[label == L_].sum()) for L_ in S}
    pairs = {}
    for v, regs in enumerate(vreg):
        if len(regs) == 2:
            pairs.setdefault(tuple(sorted(regs)), []).append(v)
    done = 0
    for L_ in sorted((L_ for L_ in S if S[L_]["kind"] != "plane"), key=lambda q: share[q]):
        refs = []
        for (p_, q_), vs in pairs.items():
            if L_ not in (p_, q_) or len(vs) < 3:
                continue
            R_ = q_ if p_ == L_ else p_
            if S[R_]["kind"] != "plane" and share[R_] < share[L_]:
                continue                                   # the smaller curved one is refitted, the larger is fixed
            B = project(S[R_], V[vs])                      # the border, on the reference
            nr = normal(S[R_], B)
            if np.median(np.abs(np.einsum("ij,ij->i", normal(S[L_], B), nr))) > 0.97:
                refs.append((B, nr))
        if not refs:
            continue
        own = V[[v for v, regs in enumerate(vreg) if regs == {L_}]]
        if len(own) < 6:
            continue
        kind = S[L_]["kind"]; x0 = pack(S[L_])
        Bs = np.vstack([b for b, _ in refs]); Ns = np.vstack([nn for _, nn in refs])
        scale = float(np.linalg.norm(own.max(0) - own.min(0))) or 1.0

        def resid(x):
            s = unpack(kind, x)
            ns = normal(s, Bs)
            tang = np.linalg.norm(np.cross(ns, Ns), axis=1) * scale      # sine of the normals' angle, as a length
            return np.r_[sdist(s, own), 10 * sdist(s, Bs), 10 * tang]
        try:
            r = least_squares(resid, x0, method="lm", max_nfev=400)
        except Exception:                                  # noqa: BLE001 - a degenerate border: keep the free fit
            continue
        s = unpack(kind, r.x)
        if np.percentile(np.abs(sdist(s, own)), 90) < 2 * np.percentile(np.abs(sdist(S[L_], own)), 90) + 1e-9:
            S[L_] = s; done += 1
    return done


# ---------- the cleaner ----------
def noise(V):
    _, idx = cKDTree(V).query(V, k=16)
    Q = V[idx] - V[idx].mean(1, keepdims=True)
    lam = np.linalg.eigvalsh(np.einsum("nki,nkj->nij", Q, Q) / 16)
    return float(np.percentile(np.sqrt(np.maximum(lam[:, 0], 0)), 25))


def clean(m):
    V, F = m.vertices.copy(), m.faces
    diag = float(np.linalg.norm(m.extents)); nf = len(F)
    sigma = noise(V); tol = max(TOL_K * sigma, 1e-5 * diag)
    area = m.area_faces; cen = m.triangles_center
    adj = m.face_adjacency
    nb = [[] for _ in range(nf)]
    for a_, b_ in adj:
        nb[a_].append(b_); nb[b_].append(a_)
    # normals smoothed over neighbours that face the same way (a sharp edge is never averaged across)
    n = m.face_normals.copy()
    for _ in range(4):
        acc = n * area[:, None]
        for a_, b_ in adj:
            if n[a_] @ n[b_] > 0.8:
                acc[a_] += n[b_] * area[b_]; acc[b_] += n[a_] * area[a_]
        n = _unit(acc)
    # seed order: flattest neighbourhoods first
    flat = np.array([min((n[t] @ n[u] for u in nb[t]), default=0.0) for t in range(nf)])
    label = -np.ones(nf, int); S = []
    for seed in np.argsort(-flat):
        if label[seed] >= 0:
            continue
        patch = [seed]; seen = {seed}; i = 0
        while i < len(patch) and len(patch) < PATCH:
            for u in nb[patch[i]]:
                if u not in seen and label[u] < 0 and n[u] @ n[patch[i]] > PATCH_COS:
                    seen.add(u); patch.append(u)
            i += 1
        if len(patch) < 6:
            continue
        P = V[np.unique(F[patch])]
        # by fit quality, not first-acceptable: at scan noise a gently curved patch also passes as a plane
        # (mechpart: 192 small planes on 47 % of the area, every curved kind under 1 %). A curved kind replaces the
        # simpler one only when it halves the residual: noise alone lets the richer model win by a little.
        s, best = None, None
        for kind in ("plane", "cylinder", "cone", "sphere", "torus"):
            c = fit(kind, P, n[patch], diag, cen[patch])
            if c is None:
                continue
            r = float(np.percentile(np.abs(sdist(c, P)), 90))
            if r < tol and np.mean(np.abs(np.einsum("ij,ij->i", normal(c, cen[patch]), n[patch]))) > GROW_ANGLE \
                    and (best is None or r < 0.5 * best):
                s, best = c, r
        if s is None:
            continue
        L = len(S); region = list(patch); label[patch] = L; front = list(patch); refit_at = 2 * len(region)
        while front:
            cand = {u for t in front for u in nb[t] if label[u] < 0}
            if not cand:
                break
            cu = np.fromiter(cand, int)
            d = np.abs(sdist(s, V[F[cu]].reshape(-1, 3))).reshape(-1, 3).max(1)
            f = np.abs(np.einsum("ij,ij->i", normal(s, cen[cu]), n[cu]))
            ok = cu[(d < 2 * tol) & (f > GROW_ANGLE)]
            label[ok] = L; region += ok.tolist(); front = ok.tolist()
            if len(region) >= refit_at:
                c = fit(s["kind"], V[np.unique(F[region])], n[region], diag, cen[region])
                if c is not None and np.percentile(np.abs(sdist(c, V[np.unique(F[region])])), 90) < tol:
                    s = c
                refit_at = 2 * len(region)
        if area[region].sum() < MIN_AREA * area.sum():
            label[region] = -2                             # too small to be a face: never a seed again
            continue
        S.append(s)
    label[label == -2] = -1
    # leftovers join the neighbouring region whose surface they lie on. ponytail: distance only, so a wall strip the seeds
    # missed is pulled into a parallel level (Kimi: 14 of 40 failing corners); a facing check plus strip regions was
    # tried 2026-09-30 and gave 41 failing corners (edgebuild's topological absorb re-pulls what stays unlabelled)
    for _ in range(3):
        for t in np.where(label < 0)[0]:
            best = min(({label[u] for u in nb[t] if label[u] >= 0}),
                       key=lambda L_: float(np.abs(sdist(S[L_], V[F[t]])).max()), default=None)
            if best is not None and np.abs(sdist(S[best], V[F[t]])).max() < 3 * tol:
                label[t] = best
    # one surface in several regions (a face split where the seed order met it twice): regions whose vertices lie
    # on each other's surface are merged (mechpart: 215 planes before)
    alias = list(range(len(S)))
    def root(L_):
        while alias[L_] != L_:
            L_ = alias[L_]
        return L_
    verts = [V[np.unique(F[label == L_])] for L_ in range(len(S))]
    for i in range(len(S)):
        for j in range(i + 1, len(S)):
            ri, rj = root(i), root(j)
            if ri == rj or S[ri]["kind"] != S[rj]["kind"]:
                continue
            if np.percentile(np.abs(sdist(S[ri], verts[j])), 90) < tol and \
                    np.percentile(np.abs(sdist(S[rj], verts[i])), 90) < tol:
                alias[rj] = ri
    label = np.where(label >= 0, [root(L_) if L_ >= 0 else -1 for L_ in label], -1)
    # neighbours of one kind that ONE surface fits (a joint fit, not each on the other's: a long face fitted in two
    # halves tilts each half; mechpart: 136 inexact vertices between near-parallel planes)
    while True:
        a_, b_ = m.face_adjacency.T
        la, lb = label[a_], label[b_]
        cand = {(min(p_, q_), max(p_, q_)) for p_, q_ in zip(la, lb) if p_ >= 0 and q_ >= 0 and p_ != q_
                and S[p_]["kind"] == S[q_]["kind"]}
        merged = False
        for p_, q_ in sorted(cand, key=lambda pq: -(area[label == pq[0]].sum() + area[label == pq[1]].sum())):
            if p_ not in set(label.tolist()) or q_ not in set(label.tolist()):
                continue
            both = (label == p_) | (label == q_)
            P = V[np.unique(F[both])]
            c = fit(S[p_]["kind"], P, n[both], diag, cen[both])
            if c is not None and np.percentile(np.abs(sdist(c, P)), 90) < tol:
                label[label == q_] = p_; S[p_] = c; merged = True
        if not merged:
            break
    for L_ in set(label[label >= 0].tolist()):
        c = fit(S[L_]["kind"], V[np.unique(F[label == L_])], n[label == L_], diag, cen[label == L_])
        if c is not None:
            S[L_] = c
    S = {L_: S[L_] for L_ in set(label[label >= 0].tolist())}
    vreg = [set() for _ in range(len(V))]
    for t in np.where(label >= 0)[0]:
        for v in F[t]:
            vreg[v].add(int(label[t]))
    n_tangent = tangent_refit(S, V, vreg, label, area)
    # every corner (a vertex of 3+ regions) must be a point all its surfaces share: where they do not, the smallest of
    # them is almost always spurious (an embossed logo read as a sphere, a noise patch) and joins the neighbour its
    # vertices lie closest to. mechpart: 56 of 177 corners did not meet in edgebuild before this.
    # Only a SMALL region (under 1 % of the area) that lies on the neighbour's surface anyway is absorbed: absorbing by
    # size alone took 69 of 95 regions on mechpart and flattened its pocket floors (moves p95 2 mm).
    n_absorbed = 0; skip = set()
    for _ in range(200):
        bad = None
        for v, regs in enumerate(vreg):
            if len(regs) >= 3 and frozenset(regs) not in skip:
                x = common_point([S[L_] for L_ in regs], V[v:v + 1], 1e-6 * diag)
                if x is None or np.linalg.norm(x - V[v]) > MOVE_K * tol:
                    bad = regs
                    break
        if bad is None:
            break
        small = min(bad, key=lambda L_: area[label == L_].sum())
        ts = np.where(label == small)[0]
        nbrs = {int(label[u]) for t in ts for u in nb[t]} - {small, -1}
        P = V[np.unique(F[ts])]
        into = min(nbrs, key=lambda L_: float(np.percentile(np.abs(sdist(S[L_], P)), 90)), default=None)
        if into is None or area[ts].sum() > 0.01 * area.sum() \
                or np.percentile(np.abs(sdist(S[into], P)), 90) > 2 * tol:
            skip.add(frozenset(bad)); continue
        label[ts] = into; del S[small]; n_absorbed += 1
        for v in np.unique(F[ts]):
            vreg[v].discard(small); vreg[v].add(into)
    # snap: every vertex onto its region's surface, or onto the common points of its regions
    V0 = V.copy(); inexact = 0; causes = {}; bad_v = []
    for v, regs in enumerate(vreg):
        if not regs:
            continue
        x0 = V[v:v + 1].copy()
        x = common_point([S[L_] for L_ in regs], x0, 1e-6 * diag)   # edgebuild checks 1e-5
        if x is None or np.linalg.norm(x - x0) > MOVE_K * tol:
            # the surfaces do not meet near this vertex (a region boundary that is not a real edge): the vertex stays
            # on its nearest surface and counts as inexact (its triangles in the other regions are not flat)
            x = min((project(S[L_], x0) for L_ in regs), key=lambda y: float(np.linalg.norm(y - x0)))
            inexact += 1
            why = "+".join(sorted(S[L_]["kind"] for L_ in regs)) if len(regs) <= 3 else "4+ regions"
            why += (", tangent" if len(regs) > 1 and max(
                abs(float(normal(S[p_], x0)[0] @ normal(S[q_], x0)[0])) for p_ in regs for q_ in regs if p_ < q_) > 0.97 else "")
            causes[why] = causes.get(why, 0) + 1
            bad_v.append(v)
            if np.linalg.norm(x - x0) > MOVE_K * tol:
                continue
        V[v] = x[0]
    # two vertices snapped onto one point (both ends of a thin strip onto its corner) would be welded downstream
    # (edgebuild welds at 1.5e-4 of the diagonal) and leave the mesh non-manifold: the one that moved more goes back
    n_collide = 0
    for _ in range(5):
        pairs_c = cKDTree(V).query_pairs(3e-4 * diag, output_type="ndarray")
        if not len(pairs_c):
            break
        for i_, j_ in pairs_c:
            k_ = i_ if np.linalg.norm(V[i_] - V0[i_]) >= np.linalg.norm(V[j_] - V0[j_]) else j_
            if np.linalg.norm(V[k_] - V0[k_]) > 0:
                V[k_] = V0[k_]; n_collide += 1
    move = np.linalg.norm(V - V0, axis=1)
    out = trimesh.Trimesh(V, F, process=False)
    flipped = int((np.einsum("ij,ij->i", out.face_normals, m.face_normals) < 0).sum())
    kinds = {}
    for s in S.values():
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    share = {}
    for L_, s_ in S.items():
        share.setdefault(s_["kind"], []).append(round(100 * float(area[label == L_].sum() / area.sum()), 2))
    report = {"noise_mm": round(sigma, 4), "tol_mm": round(tol, 4), "regions": kinds,
              "area_pct": {k: sorted(v, reverse=True)[:12] + ([f"+{len(v) - 12} more, {round(sum(sorted(v, reverse=True)[12:]), 1)} %"] if len(v) > 12 else []) for k, v in share.items()},
              "covered_pct": round(100 * float(area[label >= 0].sum() / area.sum()), 1),
              "move_max_mm": round(float(move.max()), 4), "move_p95_mm": round(float(np.percentile(move, 95)), 4),
              "flipped": flipped, "inexact_vertices": inexact, "inexact_why": causes, "tangent_refits": n_tangent, "absorbed_for_corners": n_absorbed, "collisions_undone": n_collide}
    # compact numbering (0..k-1) and each region's surface kind, for edgebuild's EB_LABELS
    ids = sorted(S)
    remap = {L_: i for i, L_ in enumerate(ids)}
    label = np.array([remap.get(L_, -1) for L_ in label])
    report["kinds"] = [S[L_]["kind"] for L_ in ids]
    # each region's surface for edgebuild (its own torus/cone fitters reject noisy regions): axis, axis point, profile
    geo = np.zeros((len(ids), 9))
    for i, L_ in enumerate(ids):
        g = S[L_]
        if g["kind"] == "torus":
            geo[i] = np.r_[g["a"], g["o"], g["hc"], g["Rc"], g["r"]]
        elif g["kind"] == "cone":
            geo[i] = np.r_[g["a"], g["o"], g["k"], 0.0]
    report["geo"] = geo
    report["inexact_at"] = bad_v
    return out, report, label


if __name__ == "__main__":
    m = trimesh.load(sys.argv[1], force="mesh")
    out, rep, label = clean(m)
    out.export(sys.argv[2])
    if len(sys.argv) > 3:
        # per-face region and each region's kind: edgebuild.py takes them as its segmentation (EB_LABELS=<file>)
        np.savez(sys.argv[3], label=label, kinds=np.array(rep["kinds"]), centres=out.triangles_center,
                 inexact=np.array(rep["inexact_at"], int), geo=rep["geo"])
    rep.pop("kinds"); rep.pop("inexact_at"); rep.pop("geo")
    print(json.dumps(rep))
