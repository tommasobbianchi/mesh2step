"""Mesh -> proposed feature tree, deterministically ($0). The LLM and the owner only confirm or correct it.

1. main extrusion (reverse.py): axis, outline sketch, holes, stacked levels, cap rounds;
2. cap modifier: round or chamfer, told apart by the section inset at half its depth (round 0.13 d, chamfer 0.5 d);
3. residual: compile, find the mesh the solid does not explain, fit cylinders on any principal axis -> holes
   (normals toward the axis) or bosses, coaxial pieces merged (a screw hole through two jaws is one hole).
usage: propose.py <mesh> <out_tree.json>
"""
import json
import sys
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "recon"))
import reverse                                        # noqa: E402
import tree as T                                      # noqa: E402

AXN = "XYZ"


def _uv(axis, P2):
    """reverse.py's 2D coords (its plane axes, sorted) -> this tree's right-handed (u, v)."""
    a = AXN.index(axis); ru, rv = reverse.plane_axes(a); mu, mv = T.UV[axis]
    P2 = np.asarray(P2, float)
    p3 = np.zeros((len(P2), 3)); p3[:, ru] = P2[:, 0]; p3[:, rv] = P2[:, 1]
    return np.c_[p3[:, mu], p3[:, mv]]


def loop_prims(axis, L, native=False):
    """Closed polyline -> exact lines / arcs / one circle (reverse.segment's fit), in tree coordinates.
    native: L is already in tree (u, v) coordinates, not reverse.py's."""
    conv = (lambda a, P: np.asarray(P, float)) if native else _uv
    L2, prims = reverse.segment(np.asarray(L, float))
    Q = conv(axis, L2)
    r2 = lambda p: [round(float(p[0]), 4), round(float(p[1]), 4)]
    if len(prims) == 1 and prims[0][0] == "arc":
        c = conv(axis, [prims[0][3]])[0]
        return [{"t": "circle", "c": r2(c), "r": round(float(prims[0][4]), 4)}]
    out = []
    for p in prims:
        i0, i1 = p[1], min(p[2], len(Q) - 1)
        if p[0] == "line" or i1 - i0 < 2:
            out.append({"t": "line", "p": [r2(Q[i0]), r2(Q[i1])]})
        else:
            out.append({"t": "arc", "p": [r2(Q[i0]), r2(Q[(i0 + i1) // 2]), r2(Q[i1])]})
    return out


def _name(loop):
    return f"Hole ⌀{2 * loop[0]['r']:.3g}" if len(loop) == 1 and loop[0]["t"] == "circle" else "Cutout"


def cap_kind(m, ax, lo, hi, sil, d, cap):
    """Round or chamfer on a cap edge of inset d: compare the section inset at depth d/2 with both models."""
    A_sil, P_sil = sil.area, sil.length
    ins = []
    for h in (0.25 * d, 0.5 * d, 0.75 * d):
        z = hi[ax] - h if cap > 0 else lo[ax] + h
        A, P = reverse.section_area_perimeter(m, ax, z)
        ins.append(max(0.0, 2 * (A_sil - A) / max(P + P_sil, 1e-9)))
    i_half = ins[1]
    if abs(i_half - 0.5 * d) < abs(i_half - 0.134 * d):
        return "chamfer", float(np.mean([i + h for i, h in zip(ins, (0.25 * d, 0.5 * d, 0.75 * d))]))
    return "round", float(d)


def sketch_axis(m):
    """The main extrusion's axis: most area aligned with it (walls parallel, caps across) PLUS its cap area, weighted
    by half. Aligned area alone picks X on a rim-chamfered 40x20x6 plate: the chamfers along its long sides are
    parallel to X, so X out-scores the real extrusion axis Z, whose flat caps are 60 % of the part."""
    n, w = m.face_normals, m.area_faces
    def score(k):
        c = np.abs(n[:, k])
        return (w[(c < 0.02) | (c > 0.999)].sum() + 0.5 * w[c > 0.999].sum()) / w.sum()
    return int(np.argmax([score(k) for k in range(3)]))


def main_extrusion(m, stl):
    R = reverse.reverse(stl, axis=sketch_axis(m))
    axis, ax = R["axis"], AXN.index(R["axis"])
    lo, hi = m.bounds
    feats = []
    if R["levels"]:
        for k, lv in enumerate(R["levels"]):
            for j, sh in enumerate(lv["shapes"]):
                feats.append({"op": "pad", "label": f"Level {k + 1}" + (f".{j + 1}" if len(lv["shapes"]) > 1 else ""),
                              "axis": axis, "at": round(lv["z0"], 4), "length": round(lv["z1"] - lv["z0"], 4),
                              "loops": [loop_prims(axis, sh["outer"])] + [loop_prims(axis, h) for h in sh["holes"]]})
        return feats
    feats.append({"op": "pad", "label": "Base extrusion", "axis": axis, "at": round(R["z0"], 4),
                  "length": round(R["height"], 4), "loops": [loop_prims(axis, R["outer"])]})
    for h in R["holes"]:
        lp = loop_prims(axis, h)
        feats.append({"op": "pocket", "label": _name(lp), "axis": axis, "at": round(R["z0"], 4),
                      "length": "through", "loops": [lp]})
    sil = reverse.silhouette(np.asarray(m.triangles, float), ax)
    if sil.geom_type != "Polygon":
        sil = max(sil.geoms, key=lambda g: g.area)
    mods = {}
    for cap, rr, name in ((+1, R["r_top"], "top"), (-1, R["r_bottom"], "bottom")):
        for which in ("outer", "holes"):
            d = min(float(rr[which]), R["height"] / 2 - 1e-3)
            if d > 1e-3 * R["height"]:
                kind, size = cap_kind(m, ax, lo, hi, sil, d, cap) if which == "outer" else ("round", d)
                mods.setdefault((kind, round(size, 3), which), []).append(name)
    for (kind, size, which), caps in mods.items():
        feats.append({"op": kind, "label": f"{'Rounded' if kind == 'round' else 'Chamfered'} "
                      f"{'rim' if which == 'outer' else 'hole'} edges", "size": size, "on": "F1",
                      "cap": "both" if len(caps) == 2 else caps[0], "loops": "outer" if which == "outer" else "inner"})
    return feats


def cylinders(m, faces, tol, smooth=None):
    """Cylindrical pieces among the given mesh faces: [(axis_name, centre_uv, r, lo, hi, is_hole, area)].
    smooth (degrees): split pieces at sharper edges too (needed when `faces` is the whole mesh)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    sel = np.zeros(len(m.faces), bool); sel[faces] = True
    keep = sel[m.face_adjacency[:, 0]] & sel[m.face_adjacency[:, 1]]
    if smooth:
        keep &= m.face_adjacency_angles < np.radians(smooth)
    adj = m.face_adjacency[keep]
    n = len(m.faces)
    _, lab = connected_components(coo_matrix((np.ones(len(adj)), (adj[:, 0], adj[:, 1])), shape=(n, n)), directed=False)
    out = []
    for comp in np.unique(lab[sel]):
        idx = np.where((lab == comp) & sel)[0]
        w = m.area_faces[idx]
        if w.sum() < 2e-3 * m.area or len(idx) < 8:
            continue
        nrm0 = m.face_normals[idx]
        axis = np.linalg.svd(nrm0 * w[:, None], full_matrices=False)[2][-1]
        k = int(np.argmax(np.abs(axis)))
        if abs(axis[k]) < 0.995:                       # principal axes only
            continue
        cap = np.abs(nrm0[:, k]) > 0.9                 # a flat blind-hole bottom (or boss top): an exact end
        wall = np.abs(nrm0[:, k]) < 0.3
        if wall.sum() < 8 or w[wall].sum() < 0.7 * w.sum() * (1 - cap.mean()):
            continue
        ends = m.triangles_center[idx[cap]][:, k] if cap.any() else np.array([])
        idx, w = idx[wall], w[wall]
        nrm, pts = m.face_normals[idx], m.triangles_center[idx]
        name = AXN[k]; mu, mv = T.UV[name]
        p = np.c_[pts[:, mu], pts[:, mv]]
        sol = np.linalg.lstsq(np.c_[2 * p, np.ones(len(p))], (p ** 2).sum(1), rcond=None)[0]
        c = sol[:2]; r = float(np.sqrt(max(sol[2] + c @ c, 0)))
        if r <= 0 or np.abs(np.linalg.norm(p - c, axis=1) - r).max() > max(2 * tol, 0.05 * r):
            continue
        radial = np.c_[p - c]; radial /= np.linalg.norm(radial, axis=1)[:, None]
        hole = float(((np.c_[nrm[:, mu], nrm[:, mv]] * radial).sum(1) * w).sum()) < 0
        h = m.vertices[m.faces[idx].ravel()][:, k]
        lo, hi = float(h.min()), float(h.max())
        closed_lo = bool(len(ends)) and np.abs(ends - lo).min() < tol
        closed_hi = bool(len(ends)) and np.abs(ends - hi).min() < tol
        out.append((name, c, r, lo - (0 if closed_lo else 2 * tol), hi + (0 if closed_hi else 2 * tol), hole,
                    float(w.sum()), [[round(lo, 3), round(hi, 3)]]))
    merged = []                                        # coaxial, same radius, same kind: one feature
    for cy in sorted(out, key=lambda x: -x[6]):
        for mg in merged:
            if mg[0] == cy[0] and mg[5] == cy[5] and np.linalg.norm(mg[1] - cy[1]) < 2 * tol and abs(mg[2] - cy[2]) < 0.05 * mg[2]:
                mg[3], mg[4] = min(mg[3], cy[3]), max(mg[4], cy[4]); mg[6] += cy[6]; mg[7] += cy[7]; break
        else:
            merged.append(list(cy))
    return merged


def propose(stl):
    m = trimesh.load(stl, force="mesh")
    # 0.3 % of the diagonal, floored at 0.05: portal STLs are mm, and 0.05 mm is below what a printer resolves
    tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)
    tree = {"units": "mm", "features": main_extrusion(m, stl)}
    _ids(tree)
    finish(tree, m, tol)
    return tree, m, tol


def finish(tree, m, tol):
    """The deterministic passes after the base bodies: residual cylinders (holes/bosses on any principal axis, each
    kept only if the mesh match improves), then modifier sizes fitted to the mesh. Edits tree in place."""
    feats = tree["features"]
    shape, _ = T.compile_tree(tree, tol)
    dev = T.deviation(m, shape, tol)
    far = np.where(dev["face_dist"] > tol)[0]
    extra = []
    for name, c, r, lo, hi, hole, _, _ in cylinders(m, far, tol):
        extra.append({"op": "pocket" if hole else "pad", "label": f"{'Hole' if hole else 'Boss'} ⌀{2 * r:.3g}",
                      "axis": name, "at": round(lo, 4), "length": round(hi - lo, 4),   # open ends already extended
                      "loops": [[{"t": "circle", "c": [round(float(c[0]), 4), round(float(c[1]), 4)], "r": round(r, 4)}]]})
    base = (dev["explained"], dev["extra"])
    for cand in extra:                                 # keep a candidate only if the mesh says it helps
        k = next((i for i, f in enumerate(feats) if f["op"] in ("round", "chamfer")), len(feats))
        trial = {"units": "mm", "features": feats[:k] + [dict(cand, id=f"R{k}")] + feats[k:]}
        sh, _ = T.compile_tree(trial, tol)
        if sh is None:
            continue
        d = T.deviation(m, sh, tol)
        if d["explained"] > base[0] + 0.003 and d["extra"] < base[1] + 0.003:
            feats.insert(k, dict(cand, id=f"R{k}")); base = (d["explained"], d["extra"])   # renumbered below
    _ids(tree, keep_refs=True)
    refine(tree, m, tol)
    return tree


def score(tree, m, tol):
    """How badly the tree's solid misses the mesh: mean face distance, capped at 3 tol (area-weighted)."""
    shape, _ = T.compile_tree(tree, tol)
    if shape is None:
        return 1e9
    d = T.deviation(m, shape, tol)
    return float((np.minimum(d["face_dist"], 3 * tol) * m.area_faces).sum() / m.area)


def refine(tree, m, tol, evals=7):
    """Fit each round/chamfer size to the mesh (golden section over 0.4x..2.5x the first estimate). The structure is
    fixed; only numbers move, and only by measurement."""
    g = (5 ** 0.5 - 1) / 2
    for f in tree["features"]:
        if f["op"] not in ("round", "chamfer"):
            continue
        s0 = float(f["size"]); a, b = 0.4 * s0, 2.5 * s0
        def at(x):
            f["size"] = round(x, 4); return score(tree, m, tol)
        c, d = b - g * (b - a), a + g * (b - a); fc, fd = at(c), at(d)
        for _ in range(evals - 2):
            if fc < fd:
                b, d, fd = d, c, fc; c = b - g * (b - a); fc = at(c)
            else:
                a, c, fc = c, d, fd; d = a + g * (b - a); fd = at(d)
        f["size"] = round(c if fc < fd else d, 4)
    return tree


def _ids(tree, keep_refs=False):
    old = {f.get("id"): f for f in tree["features"]}
    for i, f in enumerate(tree["features"]):
        f["id"] = f"F{i + 1}"
    if keep_refs:                                      # modifiers keep pointing at the same feature
        for f in tree["features"]:
            if "on" in f and f["on"] in old:
                f["on"] = old[f["on"]]["id"]


if __name__ == "__main__":
    t, m, tol = propose(sys.argv[1])
    Path(sys.argv[2]).write_text(json.dumps(t, indent=1))
    s, notes = T.compile_tree(t, tol)
    d = T.deviation(m, s, tol)
    print(json.dumps({"features": [(f["id"], f["op"], f["label"]) for f in t["features"]], "notes": notes,
                      "explained": round(d["explained"], 4), "extra": round(d["extra"], 4), "tol": round(tol, 4),
                      "volume": round(T.volume(s), 3), "mesh_volume": round(float(m.volume), 3)}))
