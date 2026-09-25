"""One cheap LLM pass names the BASE BODIES; the deterministic engine fits every number.

For parts that are not one extrusion (bodies along different axes, over different ranges), propose.py slices the
whole part along one axis and gets thin layers. Here the planner sees 4 renders plus the measured flat faces (P#)
and cylinders (C#), and returns an ordered list of bodies that REFERENCE those ids -- no invented numbers:
  prism across an axis between two flat faces, optionally clipped between two more; a cylinder by its C id.
The engine then fits each body from the mesh:
  pad profile    = union of the mesh's sections inside the body's range, clipped to its region;
  pocket profile = (the model's section - the mesh's section) at mid range, clipped;
and the usual residual holes, modifier sizes and keep-only-if-it-helps checks follow (propose.py).
usage: plan.py <mesh> <out_tree.json>
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import propose as PR                                   # noqa: E402
import tree as T                                       # noqa: E402

CLAUDE = os.path.expanduser("~/.local/bin/claude")
RENDER = Path.home() / ".claude/skills/deepseek-vision/scripts/render.py"
MODEL = os.environ.get("PLAN_MODEL", "sonnet")
AXN = "XYZ"
HOPELESS = 0.9                                # bodies score below which polishing is skipped

PROMPT = """You plan how a designer would MODEL this part in CAD from basic bodies: prisms (a sketch extruded
between two flat faces) and cylinders/tubes, added (pad) or cut (pocket), biggest first, cuts after the bodies
they cut. Look at the renders (files below; read them) and use ONLY the measured ids for positions.

Measured (mesh units, probably mm). Axis u/v of a plane across an axis: X -> (Y, Z), Y -> (Z, X), Z -> (X, Y).
FLAT faces P#: axis = its normal's axis, side = which way it faces, at = its position on that axis, u/v = its extent.
CYLINDERS C#: axis, centre (u, v), r, hole (normals point inward) or boss; lo..hi is the span of its coaxial
PIECES, and the surface exists only on the pieces (a bore in two separate tubes is one C with two pieces).
{facts}

Reply with ONLY a JSON object:
{{"bodies": [
  {{"op": "pad" | "pocket", "label": "<designer's name>", "kind": "prism", "axis": "X"|"Y"|"Z",
    "from": "P#", "to": "P#",                       # flat faces bounding it along the axis (or "through")
    "clip_u": ["P#", "P#"], "clip_v": ["P#", "P#"]}},   # optional: faces bounding its region in the plane
  {{"op": "pad" | "pocket", "label": "...", "kind": "cylinder", "cyl": "C#", "from": "P#", "to": "P#"}}
]}}
Rules: at most 8 bodies. The engine reads each prism's outline from the mesh inside that range and region, so a
prism is the right choice for any extruded outline (however complex); clip only to separate it from a neighbour
body in the same range. Small holes, fillets and chamfers are found later: do not list them."""


def facts(m, tol, max_flat=40, max_cyl=16):
    n, w, c = m.face_normals, m.area_faces, m.triangles_center
    flats = []
    for k in range(3):
        for sign in (1, -1):
            sel = n[:, k] * sign > 0.999
            if not sel.any():
                continue
            key = np.round(c[sel, k] / tol).astype(int)
            for q in np.unique(key):
                idx = np.where(sel)[0][key == q]
                a = float(w[idx].sum())
                if a < 2e-3 * m.area:
                    continue
                mu, mv = T.UV[AXN[k]]; V = m.vertices[m.faces[idx].ravel()]
                flats.append({"axis": AXN[k], "side": "+" if sign > 0 else "-", "at": round(float(c[idx, k].mean()), 3),
                              "area": round(a, 1), "u": [round(float(V[:, mu].min()), 2), round(float(V[:, mu].max()), 2)],
                              "v": [round(float(V[:, mv].min()), 2), round(float(V[:, mv].max()), 2)]})
    flats = sorted(flats, key=lambda f: -f["area"])[:max_flat]
    for i, f in enumerate(flats):
        f["id"] = f"P{i + 1}"
    cyls = []
    for name, cc, r, lo, hi, hole, a, pieces in PR.cylinders(m, np.arange(len(m.faces)), tol, smooth=25):
        cyls.append({"axis": name, "centre": [round(float(cc[0]), 3), round(float(cc[1]), 3)], "r": round(r, 3),
                     "lo": round(lo, 3), "hi": round(hi, 3), "hole": bool(hole), "area": round(a, 1),
                     "pieces": sorted(pieces)})      # coaxial pieces: the surface exists only there, not lo..hi
    span = float(max(m.extents))                       # a "cylinder" wider than the part is a flat patch misfit
    cyls = sorted((x for x in cyls if x["r"] < 0.5 * span), key=lambda x: -x["area"])[:max_cyl]
    for i, x in enumerate(cyls):
        x["id"] = f"C{i + 1}"
    return {"bbox_min": np.round(m.bounds[0], 3).tolist(), "bbox_max": np.round(m.bounds[1], 3).tolist(),
            "flat": flats, "cyl": cyls}


def ask_plan(stl, F, wd):
    vis = Path(wd) / "vis"
    subprocess.run([sys.executable, str(RENDER), str(stl), "--out", str(vis), "--views", "ISO,PX,PY,PZ",
                    "--crops", "0", "--px", "640"], capture_output=True, text=True, timeout=300)
    imgs = sorted(str(p) for p in vis.glob("*.png"))
    prompt = PROMPT.format(facts=json.dumps(F)) + "\nRenders: " + " ".join(imgs)
    cmd = [CLAUDE, "-p", "--model", MODEL, "--allowedTools", "Read",
           "--disallowedTools", "Bash,Task,Edit,Write,NotebookEdit,WebFetch,WebSearch",
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--output-format", "json", prompt]
    return _call(cmd, wd)


def _call(cmd, wd):
    d = json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd=str(wd)).stdout)
    raw = d.get("result") or ""
    import fix as FX
    plan = FX.first_json(raw, "bodies") or {"bodies": []}
    return plan, float(d.get("total_cost_usd") or 0), raw, d.get("session_id")


REVISE = """The engine built your plan. Steps it made: {steps}
Skipped bodies: {skipped}
Match: {explained:.1%} of the mesh within {tol:.3g}; the model has extra solid over {extra:.1%} of its surface.
Where it misses (missing = mesh surface the model lacks; extra = model surface where the mesh has none; boxes in
X, Y, Z): {clusters}
Revise the plan: return the COMPLETE bodies list again (same JSON format, ids only), fixing what the misses show."""


_section = T.section_region


def _majority(secs, tol=0.05):
    """The region inside at least half of the sections: a body's base outline. The union keeps the far side of every
    pocket (gate: 3179 mm2 of extra solid); a pocket through less than half the range is cut later instead, a boss
    over less than half is added later. Exact: overlay the section boundaries, count per cell."""
    from shapely.ops import polygonize
    secs = [g for g in secs if not g.is_empty]
    if not secs:
        return Polygon()
    cells = polygonize(unary_union([g.boundary for g in secs]))
    keep = [c for c in cells if sum(g.contains(c.representative_point()) for g in secs) * 2 >= len(secs)]
    if not keep:
        return Polygon()
    g = unary_union(keep).buffer(0)
    # sections that differ by noise along one boundary leave slivers that vote apart (99 pieces on the gate):
    # close then open by 2 tol, which merges them and drops hairlines, but keeps any real feature wider than that
    return g.buffer(2 * tol, join_style=2).buffer(-4 * tol, join_style=2).buffer(2 * tol, join_style=2)


def _pos(ref, F, axis=None):
    if isinstance(ref, (int, float)):
        return float(ref)
    f = next((x for x in F["flat"] if x["id"] == ref), None)
    if f is None:
        raise KeyError(f"unknown face {ref}")
    return f["at"]


def _polys(g, tol):
    geoms = [g] if g.geom_type == "Polygon" else list(getattr(g, "geoms", []))
    return [p for p in geoms if p.geom_type == "Polygon" and p.area > 25 * tol * tol]


def _ring(loop):
    """A tree loop back to a 2D polygon (arcs sampled): to check a fit against its source."""
    pts = []
    for x in loop:
        if x["t"] == "circle":
            t = np.linspace(0, 2 * np.pi, 90, endpoint=False)
            return Polygon(np.c_[x["c"][0] + x["r"] * np.cos(t), x["c"][1] + x["r"] * np.sin(t)])
        pts += list(T._arc_pts(*x["p"], n=24)[:-1]) if x["t"] == "arc" else [x["p"][0]]
    return Polygon(pts)


def _fit_ring(axis, coords, tol):
    """Lines/arcs for one ring; plain lines when the arc fit self-intersects or loses area (> 1 %)."""
    src = Polygon(coords)
    lp = PR.loop_prims(axis, coords, native=True)
    g = _ring(lp)
    if g.is_valid and abs(g.area - src.area) < 0.01 * src.area:
        return lp
    s2 = src.simplify(tol * 0.3, preserve_topology=True)
    c = np.asarray(s2.exterior.coords)[:-1]
    return [{"t": "line", "p": [[round(float(a[0]), 4), round(float(a[1]), 4)], [round(float(b[0]), 4), round(float(b[1]), 4)]]}
            for a, b in zip(c, np.roll(c, -1, 0))]


def _loops(axis, poly, tol):
    poly = poly.simplify(tol * 0.1, preserve_topology=True)
    out = [_fit_ring(axis, np.asarray(poly.exterior.coords)[:-1], tol)]
    for ring in poly.interiors:
        if Polygon(ring).area > 25 * tol * tol:
            out.append(_fit_ring(axis, np.asarray(ring.coords)[:-1], tol))
    return out


def _log(*a):
    import resource, time
    print(f"[plan {time.strftime('%X')} rss {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB]", *a,
          file=sys.stderr, flush=True)


def build(plan, m, F, tol):
    """Plan -> tree. Every number comes from the mesh or a measured id; a body that fails to fit is skipped."""
    feats, skipped = [], []
    lo_all, hi_all = m.bounds
    base = [None]

    occ = T.occupancy(m, m.bounds)

    def score(fs):
        """Volume IoU (is the material where the mesh has it?) + half the surface match. Surface alone let a bore
        cut through solid material pass (gate: 5600 mm3 removed, the score barely moved)."""
        t = {"units": "mm", "features": [dict(f, id=f"B{i}") for i, f in enumerate(fs)]}
        sh, _ = T.compile_tree(t, tol)
        if sh is None:
            return -1.0
        d = T.deviation(m, sh, tol)
        return T.volume_iou(m, sh, tol, occ) + 0.5 * (d["explained"] - d["extra"])

    for b in plan.get("bodies", [])[:8]:
        _log("body", json.dumps(b))
        n0 = len(feats)
        try:
            op, lab = b["op"], b.get("label", b["op"])
            if b.get("kind") == "cylinder":
                cy = next(x for x in F["cyl"] if x["id"] == b["cyl"])
                axis = cy["axis"]; k = AXN.index(axis)
                h0 = _pos(b["from"], F) if b.get("from") not in (None, "through") else cy["lo"]
                h1 = _pos(b["to"], F) if b.get("to") not in (None, "through") else cy["hi"]
                if b.get("from") == "through" or b.get("to") == "through":
                    h0, h1 = lo_all[k] - 2 * tol, hi_all[k] + 2 * tol
                h0, h1 = sorted((h0, h1))
                feats.append({"op": op, "label": lab, "axis": axis, "at": round(h0, 4), "length": round(h1 - h0, 4),
                              "loops": [[{"t": "circle", "c": cy["centre"], "r": cy["r"]}]]})
            else:
                _prism_body(b, op, lab, feats, m, F, tol, lo_all, hi_all)
        except Exception as e:                         # noqa: BLE001 -- a bad body is skipped, never fatal
            skipped.append(f"{b.get('label')}: {e}"[:160])
            continue
        # the planner is trusted for WHAT, never for whether it fits: a body that makes the match worse is dropped
        if n0 == 0:
            base[0] = score(feats)
            continue
        sc = score(feats)
        _log("score", round(base[0], 4), "->", round(sc, 4))
        if sc < base[0] + 0.002:
            skipped.append(f"{b.get('label')}: dropped, the mesh does not support it (score {base[0]:.3f} -> {sc:.3f})")
            del feats[n0:]
        else:
            base[0] = sc
    tree = {"units": "mm", "features": feats}
    PR._ids(tree)
    tree["_score"] = base[0]                  # volume IoU + half the surface match of the bodies
    return tree, skipped


def _prism_body(b, op, lab, feats, m, F, tol, lo_all, hi_all):
    """A prism body: its outline read from the mesh inside its range (pad) or cut from the model (pocket)."""
    axis = b["axis"]; k = AXN.index(axis)
    if b.get("from") == "through" or b.get("to") == "through":
        h0, h1 = float(lo_all[k]) - 2 * tol, float(hi_all[k]) + 2 * tol
    else:
        h0, h1 = sorted((_pos(b["from"], F), _pos(b["to"], F)))
    if h1 - h0 < tol:
        raise ValueError("empty range")
    clip = None
    if b.get("clip_u") or b.get("clip_v"):
        mu, mv = T.UV[axis]
        u = sorted(_pos(x, F) for x in b["clip_u"]) if b.get("clip_u") else [lo_all[mu] - 1, hi_all[mu] + 1]
        v = sorted(_pos(x, F) for x in b["clip_v"]) if b.get("clip_v") else [lo_all[mv] - 1, hi_all[mv] + 1]
        clip = box(u[0], v[0], u[1], v[1])
    inner = [h0 + f * (h1 - h0) for f in (0.1, 0.3, 0.5, 0.7, 0.9)]
    if op == "pad":                            # material present through most of its range
        region = _majority([_section(m, axis, h0 + f * (h1 - h0)) for f in np.linspace(0.06, 0.94, 9)], tol)
    else:                                      # what the model has there and the mesh does not
        cur = {"units": "mm", "features": [dict(f, id=f"B{i}") for i, f in enumerate(feats)]}
        shape, _ = T.compile_tree(cur, tol)
        if shape is None:
            raise ValueError("nothing to cut yet")
        region = unary_union([T.solid_region(shape, axis, h).difference(_section(m, axis, h)) for h in inner[1:4]])
        region = region.buffer(-tol / 2).buffer(tol / 2)   # drop the hairline between two meshes
    if clip is not None:
        region = region.intersection(clip)
    ps = _polys(region, tol)
    if not ps:
        raise ValueError("no material in that range/region")
    for j, poly in enumerate(ps):
        feats.append({"op": op, "label": lab + (f" {j + 1}" if len(ps) > 1 else ""), "axis": axis,
                      "at": round(h0, 4), "length": round(h1 - h0, 4), "loops": _loops(axis, poly, tol)})


def residual_prisms(tree, m, F, tol, max_blobs=6):
    """Deterministic: where model and mesh volumes disagree, fit a pocket (model has extra) or a pad (model lacks),
    trying each principal axis over the blob's own range (snapped to measured flat faces); keep a body only if the
    score improves. Catches the slots and pockets the planner did not name. Edits tree in place."""
    from scipy import ndimage
    import shapely
    occ_m = T.occupancy(m, m.bounds, n=60)
    lo, hi = m.bounds; k0 = int(np.argmax(hi - lo)); g = (hi[k0] - lo[k0]) / 60
    feats = tree["features"]

    def score(fs):
        t = {"units": "mm", "features": [dict(f, id=f"B{i}") for i, f in enumerate(fs)]}
        sh, notes = T.compile_tree(t, tol)
        if sh is None:
            return -1.0, None
        d = T.deviation(m, sh, tol)
        broken = sum(1 for n in notes.values() if any(w in n for w in ("refused", "failed", "invalid")))
        if broken > base_broken[0]:                    # it breaks a step that built before (mechparts/16: pockets
            return -1.0, sh                            # at the ends made the full-round rim refuse on 34 edges)
        return T.volume_iou(m, sh, tol, occ_m) + 0.5 * (d["explained"] - d["extra"]), sh

    base_broken = [10 ** 9]
    _, base_notes = T.compile_tree({"units": "mm", "features": list(feats)}, tol)
    base_broken[0] = sum(1 for n in base_notes.values() if any(w in n for w in ("refused", "failed", "invalid")))
    base, shape = score(feats)
    occ_s = T.occupancy(None, m.bounds, n=60, region=lambda ax, h: T.solid_region(shape, ax, h))
    flats = {a: sorted(x["at"] for x in F["flat"] if x["axis"] == a) for a in AXN}
    snap = lambda a, h: min(flats[a], key=lambda z: abs(z - h)) if flats[a] and min(abs(z - h) for z in flats[a]) < 1.5 * g else h
    # grid index -> world: slices along k0, then the two plane axes of k0 (T.occupancy's layout)
    mu, mv = T.UV[AXN[k0]]; order = [k0, mu, mv]
    blobs = []
    for op, mask in (("pocket", np.logical_and(occ_s, ~occ_m)), ("pad", np.logical_and(occ_m, ~occ_s))):
        lab, n = ndimage.label(mask)
        for i in range(1, n + 1):
            idx = np.argwhere(lab == i)
            if len(idx) < 4:
                continue
            bmin = np.zeros(3); bmax = np.zeros(3)
            for j, kk in enumerate(order):
                bmin[kk] = lo[kk] + idx[:, j].min() * g; bmax[kk] = lo[kk] + (idx[:, j].max() + 1) * g
            blobs.append((len(idx), op, bmin, bmax))
    global _CTX
    import multiprocessing as mp
    for _, op, bmin, bmax in sorted(blobs, key=lambda x: -x[0])[:max_blobs]:
        # the three axis trials are independent: forked workers inherit shape, mesh and caches
        # copy-on-write (OCCT shapes cannot be pickled; OCP holds the GIL: threads ran 0.34x)
        _CTX = dict(shape=shape, m=m, tol=tol, g=g, snap=snap, op=op, bmin=bmin, bmax=bmax,
                    feats=list(feats), score=score)
        with mp.get_context("fork").Pool(3) as pool:
            trials = [t for t in pool.map(_axis_trial, AXN) if t]
        best = max(trials, key=lambda t: t[0], default=None)
        if best and best[0] > base + 0.002:
            base = best[0]; feats.insert(best[2], best[1])
            _log("residual", best[1]["label"], "->", round(base, 4))
    PR._ids(tree, keep_refs=True)
    return tree


_CTX = {}


def _axis_trial(axis):
    """One residual candidate across `axis` for the current blob (a forked worker; reads _CTX)."""
    c = _CTX
    op, bmin, bmax, g, tol = c["op"], c["bmin"], c["bmax"], c["g"], c["tol"]
    m, shape, feats = c["m"], c["shape"], c["feats"]
    k = AXN.index(axis)
    a, b = c["snap"](axis, bmin[k]), c["snap"](axis, bmax[k])
    if b - a < 2 * tol:
        return None
    pu, pv = T.UV[axis]
    clip = box(bmin[pu] - g, bmin[pv] - g, bmax[pu] + g, bmax[pv] + g)
    hs = [a + f * (b - a) for f in (0.25, 0.5, 0.75)]
    diffs = [(T.solid_region(shape, axis, h).difference(_section(m, axis, h)) if op == "pocket" else
              _section(m, axis, h).difference(T.solid_region(shape, axis, h))).intersection(clip) for h in hs]
    for poly in _polys(_majority(diffs, tol), tol)[:1]:
        cand = {"op": op, "label": ("Pocket" if op == "pocket" else "Boss") + f" across {axis}", "axis": axis,
                "at": round(a, 4), "length": round(b - a, 4), "loops": _loops(axis, poly, tol)}
        k_ins = next((i for i, f in enumerate(feats) if f["op"] in ("round", "chamfer")), len(feats))
        sc, _ = c["score"](feats[:k_ins] + [cand] + feats[k_ins:])
        return (sc, cand, k_ins)
    return None


def plan_tree(stl, wd=None):
    """Planner + engine + the deterministic finishing passes. Returns (tree, mesh, tol, info)."""
    m = trimesh.load(stl, force="mesh")
    tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)
    F = facts(m, tol)
    wd = wd or tempfile.mkdtemp()
    _log("facts", len(F["flat"]), "flat,", len(F["cyl"]), "cyl")
    replay = json.loads(Path(os.environ["PLAN_REPLAY"]).read_text())["plans"] if os.environ.get("PLAN_REPLAY") else None
    if replay:                                         # bench: the recorded planner replies, no model call
        plan, cost, raw, sid = replay[0], 0.0, "", ("replay" if len(replay) > 1 else None)
    else:
        plan, cost, raw, sid = ask_plan(stl, F, wd)
    _log("plan", cost)
    best, tries, d = None, [], None
    for turn in range(2):                              # plan, then one revision that sees the misses
        tree, skipped = build(plan, m, F, tol)
        _log("built", len(tree["features"]), "features; skipped", skipped)
        d = None
        if tree["features"]:
            shape, _ = T.compile_tree(tree, tol)
            d = T.deviation(m, shape, tol) if shape is not None else None
            sc = (d["explained"] - d["extra"]) if d else -1
            tries.append({"plan": plan, "skipped": skipped, "score": round(sc, 4)})
            if best is None or sc > best[0]:
                best = (sc, tree, plan, skipped)
        if turn == 1 or sid is None:
            break
        import fix as FX
        ev = FX.clusters(m, d, tol, k=8) if tree["features"] and d else []
        msg = REVISE.format(steps=json.dumps([(f["id"], f["op"], f["label"], f["axis"], f["at"], f["length"])
                                              for f in tree["features"]]), skipped=json.dumps(skipped),
                            explained=d["explained"] if d else 0, extra=d["extra"] if d else 0, tol=tol,
                            clusters=json.dumps(ev))
        if replay:
            plan2, c2 = replay[1], 0.0
        else:
            plan2, c2, raw, sid = _call([CLAUDE, "-p", "--model", MODEL, "--resume", sid, "--allowedTools", "Read",
                                         "--disallowedTools", "Bash,Task,Edit,Write,NotebookEdit,WebFetch,WebSearch",
                                         "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                                         "--output-format", "json", msg], wd)
        cost = max(cost, c2)                           # a resumed session reports its running total
        _log("revised plan", cost)
        if not plan2.get("bodies"):
            break
        plan = plan2
    (Path(wd) / "plan.json").write_text(json.dumps({"facts": F, "tries": tries, "cost": cost}, indent=1))
    if best is None:
        return None, m, tol, {"cost": cost, "plan": plan, "skipped": [], "raw": raw[-500:]}
    _, tree, plan, skipped = best
    bodies_score = tree.pop("_score", None)
    if bodies_score is not None and bodies_score < HOPELESS:
        # bodies this far off cannot win (analyse needs a higher score than the proposal, or
        # IoU >= 0.9): skip the polishing. SV08 shroud: bodies 0.45, ~250 s of residual/finish
        # for a tree at IoU 0.49
        _log("bodies score", round(bodies_score, 3), "< HOPELESS: no residual/finish")
        return tree, m, tol, {"cost": cost, "plan": plan, "skipped": skipped, "tries": tries,
                              "hopeless": round(bodies_score, 4)}
    PR.finish(tree, m, tol)
    _log("finished")
    return tree, m, tol, {"cost": cost, "plan": plan, "skipped": skipped, "tries": tries}


if __name__ == "__main__":
    t, m, tol, info = plan_tree(sys.argv[1], str(Path(sys.argv[2]).resolve().parent))
    Path(sys.argv[2]).write_text(json.dumps(t, indent=1))
    out = {"cost": info["cost"], "bodies": info["plan"].get("bodies"), "skipped": info["skipped"]}
    if t:
        s, notes = T.compile_tree(t, tol); d = T.deviation(m, s, tol)
        out.update(features=[(f["id"], f["op"], f["label"]) for f in t["features"]], notes=notes,
                   explained=round(d["explained"], 4), extra=round(d["extra"], 4), volume=round(T.volume(s), 2),
                   mesh_volume=round(float(m.volume), 2))
    print(json.dumps(out))
