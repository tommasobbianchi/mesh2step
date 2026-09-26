"""A CadQuery program -> our feature tree (tree.py), in the mesh's own mm frame.

The program is executed with Workplane.extrude/union/cut instrumented: each extrude records its sketch faces or pending
wires (global coordinates) and direction, union appends the other operand's features, cut appends them as pockets.
Each face is one pad/pocket (the tree takes one outline per feature, holes as extra loops).

Frame: `--frame box` (CADFit's output) undoes the normalization the program was fitted in: the mesh centred on its
bounding box and scaled by 2 / max extent, so mm = p / scale + centre. `--frame mm`: the program is already in mm.

Not mapped (noted in convert_notes): sketch planes off the principal axes, taper, intersect, revolve, fillet/chamfer
(the tree has no revolve and names finishes by cap, not by edge), a cut whose operand itself has cuts (its pockets
become pads, an approximation). The executed solid itself is measured too, so conversion loss shows.

usage: cadquery_ir.py <script.py> <mesh.stl> <out_prefix> [--frame box|mm] [--var result]
  writes <out_prefix>.tree.json, .step (executed solid, mm) and .json (analyse.measure of both)
"""
import json
import sys
from pathlib import Path

import cadquery as cq
import numpy as np

AXES = "XYZ"
_orig = {k: getattr(cq.Workplane, k) for k in ("extrude", "union", "cut", "add", "revolve", "fillet", "chamfer")}


def _feats(w):
    """Features recorded on w or the nearest ancestor that has them."""
    while w is not None:
        if hasattr(w, "_cq_feats"):
            return w._cq_feats
        w = w.parent
    return []


def _extrude(self, until, combine=True, clean=True, both=False, taper=None):
    from cadquery.occ_impl.shapes import wiresToFaces
    faces = [f for o in self.objects if isinstance(o, cq.Sketch) for f in o] + \
            [o for o in self.objects if isinstance(o, cq.Face)]
    faces = faces or wiresToFaces(list(self.ctx.pendingWires))   # CADFit: pending wires, read without popping
    d = self.plane.zDir.toTuple()
    rec = [{"face": f, "dir": d, "len": float(until), "both": both, "taper": taper} for f in faces]
    res = _orig["extrude"](self, until, combine, clean, both, taper)
    res._cq_feats = (_feats(self) if combine else []) + [("pad", r) for r in rec]
    return res


def _union(self, other=None, clean=True, glue=False, tol=None):
    res = _orig["union"](self, other, clean, glue, tol)
    res._cq_feats = _feats(self) + (_feats(other) if isinstance(other, cq.Workplane) else [])
    return res


def _add(self, obj):
    """CADFit stacks its solids with result.add(solid_k): the model is their union."""
    res = _orig["add"](self, obj)
    res._cq_feats = _feats(self) + (_feats(obj) if isinstance(obj, cq.Workplane) else [])
    return res


def _cut(self, other, clean=True, tol=None):
    res = _orig["cut"](self, other, clean, tol)
    flip = {"pad": "pocket", "pocket": "pad"}
    res._cq_feats = _feats(self) + ([(flip[op], r) for op, r in _feats(other)] if isinstance(other, cq.Workplane) else [])
    return res


def _unmapped(name):
    """revolve/fillet/chamfer: built as usual, recorded only so the conversion can say what it dropped."""
    def op(self, *a, **kw):
        res = _orig[name](self, *a, **kw)
        res._cq_feats = _feats(self) + [(name, {})]
        return res
    return op


def execute(code, var="r"):
    """Run a CadQuery program with the instrumented Workplane -> (solid in its own frame, [(op, record)])."""
    cq.Workplane.extrude, cq.Workplane.union, cq.Workplane.cut, cq.Workplane.add = _extrude, _union, _cut, _add
    for k in ("revolve", "fillet", "chamfer"):
        setattr(cq.Workplane, k, _unmapped(k))
    try:
        g = {"cq": cq, "__name__": "cq_program"}
        exec(code, g)                                  # noqa: S102 -- a local CadQuery program (CADFit's output)
        r = g["final_result"] if var == "result" and "final_result" in g else g[var]   # CADFit's refined scripts
        vals = [v for v in r.vals() if isinstance(v, cq.Shape)]   # a stack of solids (result.add) is their union,
        solid = vals[0]                                            # fused one at a time (a one-call multi-argument
        for v in vals[1:]:                                         # fuse gave part 12 a worse solid than its tree)
            solid = solid.fuse(v)
        return solid.clean(), _feats(r)
    finally:
        for k, f in _orig.items():
            setattr(cq.Workplane, k, f)


def _loop(face, wire, axis, to_mm):
    """One wire of a face -> a tree loop in the axis' (u, v) sketch coordinates, edges in wire order."""
    from OCP.BRepTools import BRepTools_WireExplorer
    import tree as T
    a, b = T.UV[axis]
    uv = lambda p: [round(float(to_mm(p)[a]), 6), round(float(to_mm(p)[b]), 6)]
    ex = BRepTools_WireExplorer(wire.wrapped, face.wrapped)
    edges = []
    while ex.More():
        edges.append((cq.Edge(ex.Current()), cq.Vector(cq.Vertex(ex.CurrentVertex()).toTuple())))
        ex.Next()
    if len(edges) == 1 and edges[0][0].geomType() == "CIRCLE":
        e = edges[0][0]
        c = to_mm(e.arcCenter())
        return [{"t": "circle", "c": [round(float(c[a]), 6), round(float(c[b]), 6)],
                 "r": round(float(np.linalg.norm(to_mm(e.startPoint()) - c)), 6)}]
    loop = []
    for i, (e, s) in enumerate(edges):
        t = edges[(i + 1) % len(edges)][1]
        kind = e.geomType()
        if kind == "LINE":
            loop.append({"t": "line", "p": [uv(s), uv(t)]})
        elif kind == "CIRCLE":
            loop.append({"t": "arc", "p": [uv(s), uv(e.positionAt(0.5)), uv(t)]})
        else:                                          # spline/ellipse: a polyline, in the wire's direction
            P = [e.positionAt(x) for x in np.linspace(0, 1, 13)]
            if (P[0] - s).Length > (P[-1] - s).Length:
                P = P[::-1]
            P = [s] + P[1:-1] + [t]
            loop += [{"t": "line", "p": [uv(p), uv(q)]} for p, q in zip(P, P[1:])]
    return loop


def to_tree(recs, k=1.0, centre=(0.0, 0.0, 0.0)):
    """Recorded extrudes -> (tree, notes); program coordinates map to mm as p * k + centre."""
    to_mm = lambda p: np.array(p.toTuple() if hasattr(p, "toTuple") else p, float) * k + np.asarray(centre)
    feats, notes = [], []
    for op, r in recs:
        if op not in ("pad", "pocket"):
            notes.append(f"{op} dropped: not in the tree IR")
            continue
        d = np.array(r["dir"])
        i = int(np.argmax(np.abs(d)))
        if abs(abs(d[i]) - 1) > 1e-6:
            notes.append(f"{op} skipped: sketch plane normal {d.round(3).tolist()} is off the principal axes")
            continue
        if r["taper"]:
            notes.append(f"{op}: taper {r['taper']} ignored")
        axis, face = AXES[i], r["face"]
        h = to_mm(face.Center())[i]
        L = r["len"] * k * np.sign(d[i])               # signed length along +axis
        at, L = (h - abs(L), 2 * abs(L)) if r["both"] else (h, L)
        loops = [_loop(face, face.outerWire(), axis, to_mm)] + [_loop(face, w, axis, to_mm) for w in face.innerWires()]
        feats.append({"id": f"F{len(feats) + 1}", "op": op, "label": f"{op} on {axis} (converted)",
                      "axis": axis, "at": round(float(at), 6), "length": round(float(L), 6), "loops": loops})
    return {"units": "mm", "features": feats}, notes


def measure_shape(shape, m, tol, occ):
    """analyse.measure's numbers for an arbitrary OCCT solid (the program's own solid, before conversion)."""
    import tree as T
    d = T.deviation(m, shape, tol)
    iou = T.volume_iou(m, shape, tol, occ)
    return {"score": round(iou + 0.5 * (d["explained"] - d["extra"]), 4), "iou": round(iou, 4),
            "explained": round(d["explained"], 4), "extra": round(d["extra"], 4)}


def main(script, mesh, prefix, frame="box", var="result"):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import analyse as A
    import tree as T
    import trimesh
    m = trimesh.load(mesh, force="mesh")
    k, centre = 1.0, [0.0, 0.0, 0.0]
    if frame == "box":
        k, centre = float(max(m.extents)) / 2.0, ((m.bounds[0] + m.bounds[1]) / 2).tolist()
    tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)   # analyse.analyse_one's tolerance
    occ = T.occupancy(m, m.bounds, n=60)
    code = "\n".join(ln for ln in Path(script).read_text().splitlines() if "export" not in ln)   # no side files
    solid, recs = execute(code, var=var)
    solid_mm = solid.scale(k).translate(cq.Vector(*centre))
    np.random.seed(0)
    info = {"script": str(script), "tol": tol, "solid": measure_shape(solid_mm.wrapped, m, tol, occ),
            "ops": [op for op, _ in recs]}
    tree, info["convert_notes"] = to_tree(recs, k, centre)
    np.random.seed(0)
    info["tree"] = A.measure(tree, m, tol, occ) if tree["features"] else {"score": -1.0}
    info["tree"]["merit"] = round(A.merit(info["tree"]), 4)
    Path(f"{prefix}.tree.json").write_text(json.dumps(tree, indent=1))
    cq.exporters.export(solid_mm, f"{prefix}.step")
    Path(f"{prefix}.json").write_text(json.dumps(info, indent=1, default=str))
    print(json.dumps({x: info[x] for x in ("solid", "tree", "convert_notes")}, default=str))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("script"); ap.add_argument("mesh"); ap.add_argument("prefix")
    ap.add_argument("--frame", choices=("box", "mm"), default="box"); ap.add_argument("--var", default="result")
    a = ap.parse_args()
    main(a.script, a.mesh, a.prefix, a.frame, a.var)
