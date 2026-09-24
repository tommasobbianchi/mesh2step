"""Feature tree -> native FreeCAD PartDesign document (.FCStd), deterministically: no model, no tokens.

Every length, diameter, hole position and modifier size is a Params alias driving the feature by expression.
Rim chamfers are tapered pads (edge chamfers name edges, and edge names die on the next edit). The result is
checked like to_freecad.py: one valid solid, equal to the STEP compile, and every Params size survives +3 %.
usage: fcstd.py <tree.json> <out.FCStd>      (prints one JSON line)
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tree as T                                       # noqa: E402

FREECAD = "/snap/bin/freecad.cmd"
ROT = {"Z": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),        # columns u, v, n of each sketch plane
       "X": ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
       "Y": ((0, 0, 1), (1, 0, 0), (0, 1, 0))}

HEAD = r'''
import json, math, traceback
import FreeCAD as App, Part, Sketcher
OUT, REPORT = {out!r}, {report!r}
V = App.Vector
doc = App.newDocument("Part")
body = doc.addObject("PartDesign::Body", "Body")
P = doc.addObject("Spreadsheet::Sheet", "Params")
_row = [0]
def param(alias, value):
    _row[0] += 1
    P.set("A%d" % _row[0], alias); P.set("B%d" % _row[0], repr(float(value))); P.setAlias("B%d" % _row[0], alias)
    return "Params." + alias
def placement(axis, at):
    u, v, n = {rot}[axis]
    o = [0.0, 0.0, 0.0]; o["XYZ".index(axis)] = at
    m = App.Matrix(u[0], v[0], n[0], 0, u[1], v[1], n[1], 0, u[2], v[2], n[2], 0, 0, 0, 0, 1)
    return App.Placement(V(*o), App.Rotation(m))
def sketch(name, label, axis, at, loops, drive=None):
    sk = body.newObject("Sketcher::SketchObject", name)
    sk.Label = label; sk.MapMode = "Deactivated"; sk.Placement = placement(axis, at)
    for loop in loops:
        for s in loop:
            if s["t"] == "circle":
                i = sk.addGeometry(Part.Circle(V(s["c"][0], s["c"][1], 0), V(0, 0, 1), s["r"]))
                if drive:
                    sk.addConstraint(Sketcher.Constraint("Diameter", i, 2 * s["r"]))
                    sk.setExpression("Constraints[%d]" % (sk.ConstraintCount - 1), drive["d"])
                    for k, key in ((0, "x"), (1, "y")):
                        sk.addConstraint(Sketcher.Constraint("DistanceX" if k == 0 else "DistanceY", i, 3, s["c"][k]))
                        sk.setExpression("Constraints[%d]" % (sk.ConstraintCount - 1), drive[key])
                continue
            a, b = V(*s["p"][0], 0), V(*s["p"][-1], 0)
            g = Part.LineSegment(a, b) if s["t"] == "line" else Part.ArcOfCircle(a, V(*s["p"][1], 0), b)
            # ponytail: outline geometry is left unconstrained. Its endpoints are shared exactly, so the wire closes;
            # Coincident constraints on counter-clockwise-normalised arcs paired wrong ends and the solver dragged
            # the outline (C part: area 26 -> 92). Constrain outlines when outline sizes need to be Params.
            sk.addGeometry(g)
    return sk
def pad(name, label, sk, length, expr, reversed_=False, taper=0.0):
    f = body.newObject("PartDesign::Pad", name); f.Label = label; f.Profile = sk
    f.Refine = True                                    # unify coplanar faces: bodies meeting face to face
    f.Length = abs(length); f.Reversed = reversed_
    if taper:
        f.TaperAngle = taper
    if expr:
        f.setExpression("Length", expr)
    return f
def pocket(name, label, sk, length, expr, through=False):
    f = body.newObject("PartDesign::Pocket", name); f.Label = label; f.Profile = sk
    f.Refine = True
    if through:
        f.Type = "ThroughAll"; f.Midplane = True
    else:
        f.Length = abs(length)
        if expr:
            f.setExpression("Length", expr)
    return f
def modifier(kind, name, label, base, es, size, expr):
    """Fillet/Chamfer on base's edges es; if OCCT refuses the set, keep the edges that build together (as tree.py)."""
    key = "Radius" if kind == "Fillet" else "Size"
    m = body.newObject("PartDesign::" + kind, name); m.Label = label; m.Base = (base, es); setattr(m, key, size)
    ok = lambda: "Invalid" not in m.State and not m.Shape.isNull() and m.Shape.isValid()
    for k in (1.0, 0.995, 0.98, 0.95):               # a full round (r = half the thickness) is refused exactly
        m.setExpression(key, expr if k == 1.0 else "%s * %g" % (expr, k)); doc.recompute()
        if ok():
            return m
    keep = []
    for e in es:                                       # ponytail: greedy, one recompute per edge
        m.Base = (base, keep + [e]); doc.recompute()
        if "Invalid" not in m.State and not m.Shape.isNull() and m.Shape.isValid():
            keep.append(e)
    if not keep:
        body.removeObject(m); doc.removeObject(m.Name); return base
    m.Base = (base, keep); doc.recompute()
    return m
def edges_on(feat, axis, caps, which, tol):
    """Edge names of the rims of feat's flat faces in the cap planes (outer wire / holes), as tree.modifier_edges."""
    k = "XYZ".index(axis); out = []
    edges = feat.Shape.Edges
    for f in feat.Shape.Faces:
        if f.Surface.TypeId != "Part::GeomPlane":
            continue
        n = f.normalAt(0, 0); c = f.CenterOfMass
        if abs((n.x, n.y, n.z)[k]) < 0.999 or not any(abs((c.x, c.y, c.z)[k] - z) < tol for z in caps):
            continue
        for w in f.Wires:
            is_outer = w.isSame(f.OuterWire)
            if which == "all" or (which == "outer") == is_outer:
                for e in w.Edges:
                    i = next(j for j, x in enumerate(edges) if x.isSame(e))
                    if "Edge%d" % (i + 1) not in out:
                        out.append("Edge%d" % (i + 1))
    return out
'''

TAIL = r'''
res = {"ok": False}
try:
    doc.recompute()
    BODIES = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]   # one per body of the part
    GROUP = [o for b in BODIES for o in b.Group]
    bad = [o.Label for o in GROUP if "Invalid" in o.State or "Error" in o.State]
    def info(o):
        d = {"state": list(o.State)}
        try:
            d["null"] = o.Shape.isNull(); d["valid"] = (not d["null"]) and o.Shape.isValid()
            if o.TypeId.startswith("Sketcher"):
                d["wires"] = len(o.Shape.Wires); d["closed"] = [w.isClosed() for w in o.Shape.Wires]
                d["solve"] = o.solve()
            elif d["valid"]:
                d["volume"] = round(o.Shape.Volume, 3)
        except Exception as e:
            d["err"] = str(e)[:120]
        return d
    diag = {o.Label: info(o) for o in GROUP if not o.TypeId.startswith("App::")}
    shapes = [b.Shape for b in BODIES if not b.Shape.isNull()]
    sh = shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes) if shapes else Part.Shape()
    doc.saveAs(OUT)
    res = {"ok": False, "invalid_features": bad, "diag": diag}
    if sh.isNull():
        raise RuntimeError("Body has no shape")
    sh.exportStep(OUT[:-6] + ".fc.step")
    res = {"ok": not sh.isNull(), "diag": diag, "valid": sh.isValid(), "volume": sh.Volume,
           "solids": len(sh.Solids), "bodies": len(BODIES),
           "features": [(o.TypeId.split("::")[-1], o.Label) for o in GROUP if not o.TypeId.startswith("App::")],
           "invalid_features": bad}
    aliases = [P.getAlias(c) for c in P.getUsedCells() if P.getAlias(c)]
    res["params"] = aliases
    breaks = []
    App.closeDocument(doc.Name)
    import time
    t_gate = time.time()
    res["edit_checked"] = 0
    for a in aliases:                                   # editable = survives an edit (fresh copy per size)
        if time.time() - t_gate > 180:                  # a 98-pad tree recomputes for minutes per size: budget it
            break
        res["edit_checked"] += 1
        d2 = App.openDocument(OUT); P2 = d2.getObject("Params")
        B2 = [o for o in d2.Objects if o.TypeId == "PartDesign::Body"]
        x = P2.get(a); P2.set(P2.getCellFromAlias(a), repr(x * 1.03)); d2.recompute()
        broke = [o.Label for b in B2 for o in b.Group
                 if "Invalid" in o.State or "Error" in o.State or "Touched" in o.State]
        if broke or not all(b.Shape.isValid() for b in B2):
            breaks.append({"param": a, "broken": broke})
        App.closeDocument(d2.Name)
    res["edit_breaks"] = breaks
except Exception:
    res["error"] = traceback.format_exc()[-1500:]
open(REPORT, "w").write(json.dumps(res))
'''




def script(tree, out, report, tol):
    L = [HEAD.format(out=str(out), report=str(report), rot=ROT)]
    feats = {f["id"]: f for f in tree["features"]}
    taper = {}
    for f in tree["features"]:                        # rim chamfers become tapered pads, as in tree.compile_tree
        if f["op"] == "chamfer" and f.get("loops", "outer") == "outer" and feats.get(f.get("on"), {}).get("op") == "pad" \
                and feats[f["on"]]["length"] != "through" and sum(g["op"] == "pad" for g in tree["features"]) == 1:
            for cap in (("top", "bottom") if f.get("cap", "both") == "both" else (f["cap"],)):
                taper.setdefault(f["on"], {})[cap] = (float(f["size"]), f["id"])
    last, cur = None, None
    for f in tree["features"]:
        i, lab = f["id"], json.dumps(f.get("label", f["id"]))
        tag = f.get("body", "")
        if cur is not None and tag != cur:             # the next body of a multi-body part: its own Body
            L.append(f"body = doc.addObject('PartDesign::Body', 'Body_{tag}')\nlast = None")
        cur = tag
        if f["op"] in ("pad", "pocket"):
            circ = len(f["loops"]) == 1 and len(f["loops"][0]) == 1 and f["loops"][0][0]["t"] == "circle"
            drive = "None"
            if circ:
                c = f["loops"][0][0]
                L.append(f"drv_{i} = {{'d': param('d_{i}', {2 * c['r']!r}), 'x': param('x_{i}', {c['c'][0]!r}), "
                         f"'y': param('y_{i}', {c['c'][1]!r})}}")
                drive = f"drv_{i}"
            through = f["length"] == "through"
            if f["op"] == "pocket":
                Lf = 0.0 if through else float(f["length"])
                at = f["at"] + max(Lf, 0.0)            # a pocket cuts against the sketch normal: sketch at its top
                L.append(f"sk = sketch('S{i}', {json.dumps(f.get('label', i) + ' sketch')}, {f['axis']!r}, {at!r}, "
                         f"{json.dumps(f['loops'])}, {drive})")
                expr = "None" if through else f"param('len_{i}', {abs(Lf)!r})"
                L.append(f"last = pocket('{i}', {lab}, sk, {abs(Lf)!r}, {expr}, through={through})")
            else:
                Lf = float(f["length"]); lo = f["at"] + min(Lf, 0.0); H = abs(Lf)
                ch = taper.get(i, {})
                cb, cbid = ch.get("bottom", (0.0, None)); ct, ctid = ch.get("top", (0.0, None))
                L.append(f"eH = param('len_{i}', {H!r})")
                sz = {}
                for cid, cv in {cbid: cb, ctid: ct}.items():
                    if cid:
                        L.append(f"e_{cid} = param('size_{cid}', {cv!r})"); sz[cid] = f"e_{cid}"
                mid_expr = "eH" + (f" + ' - ' + {sz[cbid]}" if cbid else "") + (f" + ' - ' + {sz[ctid]}" if ctid else "")
                L.append(f"sk = sketch('S{i}', {json.dumps(f.get('label', i) + ' sketch')}, {f['axis']!r}, {lo + cb!r}, "
                         f"{json.dumps(f['loops'])}, {drive})")
                if cbid:
                    L.append(f"sk.setExpression('.Placement.Base.{'xyz'['XYZ'.index(f['axis'])]}', '{lo!r} + ' + {sz[cbid]})")
                L.append(f"last = pad('{i}', {lab}, sk, {H - cb - ct!r}, {mid_expr})")
                for cap, (cv, cid) in (("top", (ct, ctid)), ("bottom", (cb, cbid))):
                    if not cid:
                        continue
                    h = lo + H - ct if cap == "top" else lo + cb
                    L.append(f"skc = sketch('S{cid}{cap}', {json.dumps(cap + ' rim profile')}, {f['axis']!r}, {h!r}, "
                             f"{json.dumps(f['loops'][:1])})")
                    base = f"'{lo!r} + ' + eH + ' - ' + {sz[ctid]}" if cap == "top" else f"'{lo!r} + ' + {sz[cbid]}"
                    L.append(f"skc.setExpression('.Placement.Base.{'xyz'['XYZ'.index(f['axis'])]}', {base})")
                    L.append(f"last = pad('{cid}{cap}', {json.dumps(cap.capitalize() + ' rim chamfer')}, skc, {cv!r}, "
                             f"{sz[cid]}, reversed_={cap == 'bottom'}, taper=-45.0)")
        elif f["op"] in ("round", "chamfer"):
            if f["id"] in {v[1] for d in taper.values() for v in d.values()}:
                continue                               # built into its pad
            on = feats[f["on"]]
            Lf = float(on["length"]); lo, hi = sorted((on["at"], on["at"] + Lf))
            caps = {"top": [hi], "bottom": [lo], "both": [lo, hi]}[f.get("cap", "both")]
            kind = "Fillet" if f["op"] == "round" else "Chamfer"
            L.append(f"es = edges_on(last, {on['axis']!r}, {caps!r}, {f.get('loops', 'outer')!r}, {tol!r})")
            L.append(f"if es:\n    last = modifier('{kind}', '{i}', {lab}, last, es, {float(f['size'])!r}, "
                     f"param('size_{i}', {float(f['size'])!r}))")
        L.append("doc.recompute()")
    return "\n".join(L) + TAIL


def build(tree, out, tol=0.05):
    out = Path(out).resolve(); report = out.with_suffix(".report.json"); py = out.with_suffix(".build.py")
    py.write_text(script(tree, out, report, tol))
    report.unlink(missing_ok=True)
    n = len(tree["features"])
    subprocess.run([FREECAD, str(py)], capture_output=True, text=True, timeout=600 + 20 * n)   # build + 180 s gate
    r = json.loads(report.read_text()) if report.exists() else {"ok": False, "error": "FreeCAD wrote no report"}
    if r.get("ok") and r.get("valid") and r.get("solids") == r.get("bodies", 1):   # same solid as the STEP compile? (an invalid
        # shape makes the boolean volumes meaningless: the SV08 shroud read 0.0 while FreeCAD had lost 63 %)
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        from OCP.STEPControl import STEPControl_Reader
        rd = STEPControl_Reader(); rd.ReadFile(str(out)[:-6] + ".fc.step"); rd.TransferRoots(); fc = rd.OneShape()
        ref, _ = T.compile_tree(tree, tol)
        v = T.volume(ref)
        r["symdiff"] = round((T.volume(BRepAlgoAPI_Cut(ref, fc).Shape()) + T.volume(BRepAlgoAPI_Cut(fc, ref).Shape())) / v, 5)
    return r


if __name__ == "__main__":
    print(json.dumps(build(json.load(open(sys.argv[1])), sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 0.05)))
