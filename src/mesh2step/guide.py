import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/feature_recon"))
import numpy as np
import regions as R

KINDS = ("cylinder", "cone", "sphere", "torus", "fillet", "chamfer")


def _normals(tri):
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(n, axis=1) / 2
    n = n / np.maximum(2 * area[:, None], 1e-30)
    return n, area


def _params(model, surface):
    _kind, par, geo = model
    if surface == "cylinder":
        ax = np.asarray(geo[0], float)
        ax = ax / np.linalg.norm(ax)
        return {"axis": ax.tolist(), "point": np.asarray(geo[1], float).tolist(),
                "radius": float(par)}
    if surface == "cone":
        ax = np.asarray(geo[0], float)
        ax = ax / np.linalg.norm(ax)
        return {"axis": ax.tolist(), "apex": np.asarray(geo[1], float).tolist(),
                "half_angle": float(par)}
    if surface == "sphere":
        return {"center": np.asarray(geo[1], float).tolist(), "radius": float(par)}
    if surface == "torus":
        ax = np.asarray(geo[0], float)
        ax = ax / np.linalg.norm(ax)
        return {"axis": ax.tolist(), "center": np.asarray(geo[1], float).tolist(),
                "major": float(par[0]), "minor": float(par[1]), "radius": float(par[1])}
    if surface == "plane":
        return {"normal": np.asarray(geo[0], float).tolist(),
                "point": np.asarray(geo[1], float).tolist()}
    raise ValueError(surface)


def _fit_plane(P, tol):
    c = P.mean(axis=0)
    Q = P - c
    _, _, Vt = np.linalg.svd(Q, full_matrices=False)
    normal = Vt[2]
    if np.abs(Q @ normal).max() > 5 * tol:
        return None
    return normal, c


def _try_fit(prefix, V, F, n, area, tol, kind):
    if kind in ("cylinder", "cone", "sphere"):
        m = R.fit_smooth(prefix, V, F, n, area, tol)
        if m is None or m[0] != kind:
            return None
        return m, kind, _params(m, kind)
    if kind == "torus":
        m = R.fit_revolution(prefix, V, F, n, area, tol)
        if m is None or m[0] != "torus":
            return None
        return m, "torus", _params(m, "torus")
    if kind == "fillet":
        m = R.fit_smooth(prefix, V, F, n, area, tol)
        if m is not None and m[0] == "cylinder":
            return m, "cylinder", _params(m, "cylinder")
        m = R.fit_revolution(prefix, V, F, n, area, tol)
        if m is not None and m[0] == "torus":
            return m, "torus", _params(m, "torus")
        return None
    if kind == "chamfer":
        P = V[np.unique(F[prefix])]
        r = _fit_plane(P, tol)
        if r is None:
            return None
        normal, point = r
        m = ("plane", None, (normal, point))
        return m, "plane", {"normal": normal.tolist(), "point": point.tolist()}
    return None


def _make_ok(model, V, F, n, tol, surface):
    if surface == "plane":
        normal = np.asarray(model[2][0], float)
        point = np.asarray(model[2][1], float)

        def ok(t):
            if np.abs((V[F[t]] - point) @ normal).max() > 5 * tol:
                return False
            if abs(n[t] @ normal) < np.cos(np.radians(10)):
                return False
            return True
        return ok
    _kind, par, geo = model
    ax = np.asarray(geo[0], float)
    c = np.asarray(geo[1], float)
    lim = 5 * tol
    if surface == "cylinder":
        def ok(t):
            q = V[F[t]] - c
            rad = q - np.outer(q @ ax, ax)
            if np.abs(np.linalg.norm(rad, axis=1) - par).max() > lim:
                return False
            if abs(n[t] @ ax) > 0.05:
                return False
            m = rad.mean(0)
            nm = np.linalg.norm(m)
            if nm < 1e-12:
                return False
            if abs(abs(n[t] @ m) / nm - 1) > 0.05:
                return False
            return True
        return ok
    if surface == "cone":
        k = geo[2]

        def ok(t):
            q = V[F[t]] - c
            h = q @ ax
            rho = np.linalg.norm(q - np.outer(h, ax), axis=1)
            return np.abs(np.polyval(k, h) - rho).max() <= lim
        return ok
    if surface == "sphere":
        def ok(t):
            return np.abs(np.linalg.norm(V[F[t]] - c, axis=1) - par).max() <= lim
        return ok
    if surface == "torus":
        cc = geo[2]

        def ok(t):
            q = V[F[t]] - c
            h = q @ ax
            rho = np.linalg.norm(q - np.outer(h, ax), axis=1)
            return np.abs(np.hypot(h - cc[0], rho - cc[1]) - par[1]).max() <= lim
        return ok
    return R.surface_test(model, V, F, n, tol)


def _rms(model, V, F, region, surface):
    P = V[np.unique(F[region])]
    if surface == "plane":
        normal = np.asarray(model[2][0], float)
        point = np.asarray(model[2][1], float)
        d = np.abs((P - point) @ normal)
    else:
        _kind, par, geo = model
        ax = np.asarray(geo[0], float)
        c = np.asarray(geo[1], float)
        if surface == "sphere":
            d = np.abs(np.linalg.norm(P - c, axis=1) - par)
        elif surface == "cylinder":
            q = P - c
            rad = q - np.outer(q @ ax, ax)
            d = np.abs(np.linalg.norm(rad, axis=1) - par)
        elif surface == "cone":
            k = geo[2]
            q = P - c
            h = q @ ax
            rho = np.linalg.norm(q - np.outer(h, ax), axis=1)
            d = np.abs(np.polyval(k, h) - rho)
        elif surface == "torus":
            cc = geo[2]
            q = P - c
            h = q @ ax
            rho = np.linalg.norm(q - np.outer(h, ax), axis=1)
            d = np.abs(np.hypot(h - cc[0], rho - cc[1]) - par[1])
    return float(np.sqrt(np.mean(d ** 2)))


def _is_full(model, V, F, region, surface):
    if surface in ("sphere", "plane"):
        return False
    ax = np.asarray(model[2][0], float)
    c = np.asarray(model[2][1], float)
    P = V[np.unique(F[region])]
    q = P - c
    u = np.cross(ax, [1, 0, 0] if abs(ax[0]) < 0.9 else [0, 1, 0])
    u = u / np.linalg.norm(u)
    v = np.cross(ax, u)
    angles = np.sort(np.arctan2(q @ v, q @ u))
    gaps = np.diff(np.concatenate([angles, [angles[0] + 2 * np.pi]]))
    return bool((2 * np.pi - gaps.max()) > np.radians(350))


def _coplanar(seed, nb, n, cap):
    """Triangles reachable from seed through neighbours within 1 deg of the seed's normal, at most cap."""
    out, frontier = {seed}, [seed]
    while frontier and len(out) < cap:
        frontier = [u for t in frontier for u in nb[t]
                    if u not in out and abs(n[u] @ n[seed]) > np.cos(np.radians(1))]
        out.update(frontier)
    return out


def grow(tri, seed, kind):
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    V, F, nb, diag = R.mesh_topology(tri)
    n, area = _normals(tri)
    tol = 3e-4 * diag

    # a curved surface is coplanar within 1 deg only across a quad's two triangles; a plane is a large
    # coplanar cluster. Planar triangles never enter a curved seed patch: a fillet tangent to a wall would
    # otherwise fit a looser cylinder through both (measured: r 5.06 for an r 4 fillet).
    # CAD tessellations cover a flat face with a few LARGE triangles, so a coplanar cluster also counts as a
    # plane when its area dwarfs the seed's (a fillet strip is thin; the wall it is tangent to is not)
    def planar(t):
        c = _coplanar(t, nb, n, 8)
        return len(c) >= 8 or (t != seed and area[list(c)].sum() >= 20 * area[seed])

    if kind != "chamfer" and planar(seed):
        raise ValueError("seed is planar")

    # BFS seed patch: smooth dihedral between current triangle and neighbour
    SMOOTH = np.cos(np.radians(40))
    patch = [seed]
    patch_set = {seed}
    frontier = [seed]
    while frontier and len(patch) < 200:
        nxt = []
        for t in frontier:
            for u in nb[t]:
                if u not in patch_set and n[u] @ n[t] > SMOOTH and (kind == "chamfer" or not planar(u)):
                    patch.append(u)
                    patch_set.add(u)
                    nxt.append(u)
        frontier = nxt

    # Try fits on doubling prefixes, keep the longest that matches
    lengths = sorted(set(min(k, len(patch)) for k in (4, 8, 16, 32, 64, 128, 200)))
    best = None
    for length in lengths:
        result = _try_fit(patch[:length], V, F, n, area, tol, kind)
        if result is not None:
            best = result

    if best is None:
        raise ValueError(f"no {kind} fits here")

    model, surface, params = best
    ok = _make_ok(model, V, F, n, tol, surface)
    region = R.dry_grow([seed], nb, ok)
    if seed not in region:
        region.append(seed)

    # Refit on whole region and grow once more
    refit = _try_fit(region, V, F, n, area, tol, kind)
    if refit is not None:
        model, surface, params = refit
        ok = _make_ok(model, V, F, n, tol, surface)
        region = R.dry_grow([seed], nb, ok)
        if seed not in region:
            region.append(seed)

    region = sorted(region)
    return {
        "triangles": [int(t) for t in region],
        "surface": surface,
        "params": params,
        "rms": _rms(model, V, F, region, surface),
        "full": _is_full(model, V, F, region, surface),
    }


def suggest(tri, kind):
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    if kind == "chamfer":
        return []
    V, F, _nb, diag = R.mesh_topology(tri)
    n, area = _normals(tri)
    tol = 3e-4 * diag
    reg = R.regions(tri)
    label = reg["label"]
    kinds = reg["kinds"]
    results = []
    for lid in range(len(kinds)):
        lk = kinds[lid]
        if kind == "cylinder" and lk != "cylinder":
            continue
        if kind == "cone" and lk != "cone":
            continue
        if kind == "sphere" and lk != "sphere":
            continue
        if kind == "torus" and lk != "torus":
            continue
        if kind == "fillet" and lk not in ("cylinder", "torus"):
            continue
        tris = sorted(np.where(label == lid)[0].tolist())
        if not tris:
            continue
        result = _try_fit(tris, V, F, n, area, tol, lk)
        if result is None:
            continue
        model, surface, params = result
        full = _is_full(model, V, F, tris, surface)
        if kind == "cylinder" and not full:
            continue
        if kind == "fillet" and full:
            continue
        results.append({
            "kind": kind,
            "triangles": [int(t) for t in tris],
            "params": params,
            "rms": _rms(model, V, F, tris, surface),
        })
    return results


def _expand_gauges(selections):
    """A gauge selection (kind "gauge", bd projects-vgj7.4: two perpendicular planes the user snapped to a scan edge)
    becomes its two plane selections, with exact params the builder uses as given. The gauge wins its triangles over
    the user's other plane selections; those lose them (a curved selection overlapping it is still an error)."""
    if not any(s.get("kind") == "gauge" for s in selections):
        return selections
    out, claimed = [], set()
    for s in selections:
        if s.get("kind") == "gauge":
            for p in s["planes"]:
                t = [x for x in p["triangles"] if x not in claimed]
                claimed.update(t)
                nrm = [float(v) for v in p["normal"]]
                out.append({"kind": "plane", "surface": "plane", "triangles": t,
                            "params": {"normal": nrm, "point": [float(p["d"]) * v for v in nrm], "exact": True}})
    for s in selections:
        if s.get("kind") == "gauge":
            continue
        if s.get("surface", s.get("kind")) in ("plane", "chamfer"):
            s = dict(s, triangles=[x for x in s["triangles"] if x not in claimed])
            if not s["triangles"]:
                continue
        out.append(s)
    return out


def labels(n, selections):
    selections = _expand_gauges(selections)
    label = [-1] * n
    kinds, params, fill = {}, {}, []
    seen = set()
    for i, sel in enumerate(selections):
        surface = sel.get("surface")
        if surface is None:
            k = sel["kind"]
            if k in ("cylinder", "cone", "sphere", "torus"):
                surface = k
            elif k == "fillet":
                surface = "cylinder"
            elif k == "chamfer":
                surface = "plane"
            else:
                surface = k
        for t in sel["triangles"]:
            if t in seen:
                raise ValueError(f"triangle {t} selected twice")
            seen.add(t)
            label[t] = i
        kinds[str(i)] = surface
        if sel.get("params"):   # the surface the user accepted; cellbuild builds it as is
            params[str(i)] = sel["params"]
        if sel.get("fill"):     # not the user's: labelled for them from detection, to be checked by the builder
            fill.append(str(i))
    return ({"label": label, "kinds": kinds} | ({"params": params} if params else {})
            | ({"fill": fill} if fill else {}))
