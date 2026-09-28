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
import numpy as np

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
def edges_at(feat, path, tol):
    """Edge names of feat lying on the edges in BREP file path (the ones the OCP compile filleted): midpoint within
    tol/2. Evidence finishes are selected by the scan's faces, which FreeCAD cannot see; geometry is the handle."""
    ref = Part.read(path); out = []
    for j, e in enumerate(feat.Shape.Edges):
        q = Part.Vertex(e.valueAt((e.FirstParameter + e.LastParameter) / 2))
        if q.distToShape(ref)[0] < tol / 2:
            out.append("Edge%d" % (j + 1))
    return out
def revolve(kind, name, label, sk):
    f = body.newObject("PartDesign::" + kind, name); f.Label = label; f.Profile = sk
    f.ReferenceAxis = (sk, ["V_Axis"]); f.Angle = 360.0; f.Refine = True
    return f
def edges_on(feat, axis, caps, which, tol, near=None):
    """Edge names of the rims of feat's flat faces in the cap planes (outer wire / holes), as tree.modifier_edges;
    near: (u, v) points along the named holes (a modifier's `holes`), only edges on them."""
    k = "XYZ".index(axis); out = []
    mu, mv = ((1, 2), (2, 0), (0, 1))[k]
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
                    if near:
                        q = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
                        if min((((q.x, q.y, q.z)[mu] - u) ** 2 + ((q.x, q.y, q.z)[mv] - v) ** 2) for u, v in near) > (2 * tol) ** 2:
                            continue
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
    for b in BODIES:                                   # as the GUI shows a body: it and its tip, nothing else (saved
        b.Visibility = True                            # headless every feature but the sketches was hidden and the
        for o in b.Group:                              # file opened blank for the owner, 2026-09-27)
            o.Visibility = o == b.Tip
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
    App.closeDocument(doc.Name)
    res.update(edit_check(OUT, aliases) if EDIT else {"edit_pending": True})
except Exception:
    res["error"] = traceback.format_exc()[-1500:]
open(REPORT, "w").write(json.dumps(res))
'''

EDIT_FN = r'''
def edit_check(OUT, aliases):
    """Each Params size +3 % on a fresh copy of the saved document: which features break."""
    import time
    breaks = []
    t_gate = time.time()
    res = {"edit_checked": 0}
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
    return res
'''

EDIT_ONLY = r'''
import json, traceback
import FreeCAD as App
OUT, REPORT = {out!r}, {report!r}
try:
    d = App.openDocument(OUT); P = d.getObject("Params")
    aliases = [P.getAlias(c) for c in P.getUsedCells() if P.getAlias(c)]
    App.closeDocument(d.Name)
    res = edit_check(OUT, aliases)
except Exception:
    res = {{"error": traceback.format_exc()[-1500:]}}
open(REPORT, "w").write(json.dumps(res))
'''




def connected_order(feats):
    """Each run of consecutive pads reordered so every pad touches one placed before it (a union does not depend
    on order): a PartDesign Body refuses a pad that starts a second, separate solid (part 5: F1 along X and F2 along
    Y only meet through later pads; FreeCAD invalidated the whole body from F2 on)."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    out, i = [], 0
    while i < len(feats):
        j = i
        while j < len(feats) and feats[j]["op"] == "pad" and not feats[j].get("body"):
            j += 1
        if j - i < 2:
            out.append(feats[i]); i += 1; continue
        run = feats[i:j]
        try:
            B = [T.body(f) for f in run]
        except Exception:                              # noqa: BLE001 -- an unbuildable body: keep the order
            out += run; i = j; continue
        touch = lambda a, b: BRepExtrema_DistShapeShape(B[a], B[b]).Value() < 1e-4
        placed, rest = [0], list(range(1, len(run)))
        while rest:                                    # ponytail: O(n^2) distance calls, fine at tens of pads
            k = next((r for r in rest if any(touch(r, q) for q in placed)), rest[0])
            placed.append(k); rest.remove(k)
        out += [run[k] for k in placed]; i = j
    return out


def script(tree, out, report, tol, brep=None, skip=(), edit=True):
    brep = brep or {}
    tree = dict(tree, features=connected_order(tree["features"]))
    L = [HEAD.format(out=str(out), report=str(report), rot=ROT) + EDIT_FN + f"\nEDIT = {edit!r}\n"]
    feats = {f["id"]: f for f in tree["features"]}
    taper = {}
    for f in tree["features"]:                        # rim chamfers become tapered pads, as in tree.compile_tree
        if f["op"] == "chamfer" and f.get("loops", "outer") == "outer" and feats.get(f.get("on"), {}).get("op") == "pad" \
                and feats[f["on"]]["length"] != "through" and sum(g["op"] == "pad" for g in tree["features"]) == 1:
            for cap in (("top", "bottom") if f.get("cap", "both") == "both" else (f["cap"],)):
                taper.setdefault(f["on"], {})[cap] = (float(f["size"]), f["id"])
    last, cur = None, None
    for f in tree["features"]:
        if f["id"] in skip:
            continue
        i, lab = f["id"], json.dumps(f.get("label", f["id"]))
        tag = f.get("body", "")
        if cur is not None and tag != cur:             # the next body of a multi-body part: its own Body
            L.append(f"body = doc.addObject('PartDesign::Body', 'Body_{tag}')\nlast = None")
        cur = tag
        if f["op"] in ("pad", "pocket") and "revolve" in f:   # profile in (r, h): sketch x = r, y = h along the axis
            rv = f["revolve"]; k, ru = T.AX[rv["axis"]], T.UV[rv["axis"]][0]
            u = [0.0] * 3; u[ru] = 1.0; v = [0.0] * 3; v[k] = 1.0; n = np.cross(u, v).tolist()
            o = [float(x) for x in rv["point"]]; o[k] = 0.0
            L.append(f"sk = sketch('S{i}', {json.dumps(f.get('label', i) + ' profile')}, 'Z', 0.0, {json.dumps(f['loops'])})")
            L.append(f"sk.Placement = App.Placement(V(*{o!r}), App.Rotation(App.Matrix({u[0]}, {v[0]}, {n[0]}, 0, "
                     f"{u[1]}, {v[1]}, {n[1]}, 0, {u[2]}, {v[2]}, {n[2]}, 0, 0, 0, 0, 1)))")
            L.append(f"last = revolve({'Revolution' if f['op'] == 'pad' else 'Groove'!r}, '{i}', {lab}, sk)")
        elif f["op"] in ("pad", "pocket"):
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
            kind = "Fillet" if f["op"] == "round" else "Chamfer"
            if brep.get(i):                            # evidence finish: the edges the compile built it on
                L.append(f"es = edges_at(last, {brep[i]!r}, {tol!r})")
                L.append(f"if es:\n    last = modifier('{kind}', '{i}', {lab}, last, es, {float(f['size'])!r}, "
                         f"param('size_{i}', {float(f['size'])!r}))")
                L.append("doc.recompute()")
                continue
            on = feats[f["on"]]
            Lf = float(on["length"]); lo, hi = sorted((on["at"], on["at"] + Lf))
            caps = {"top": [hi], "bottom": [lo], "both": [lo, hi]}[f.get("cap", "both")]
            near = None
            if f.get("holes"):                         # the named holes only: points along them, <= tol apart
                near = []
                for j in f["holes"]:
                    P = np.array(T.loop_polygon(on["loops"][j]) + T.loop_polygon(on["loops"][j])[:1], float)
                    for a, b in zip(P[:-1], P[1:]):
                        n = max(1, int(np.ceil(np.linalg.norm(b - a) / tol)))
                        near += [[round(float(x), 4) for x in a + (b - a) * t] for t in np.arange(n) / n]
            L.append(f"es = edges_on(last, {on['axis']!r}, {caps!r}, {f.get('loops', 'outer')!r}, {tol!r}, {near!r})")
            L.append(f"if es:\n    last = modifier('{kind}', '{i}', {lab}, last, es, {float(f['size'])!r}, "
                     f"param('size_{i}', {float(f['size'])!r}))")
        L.append("doc.recompute()")
    return "\n".join(L) + TAIL


GUI_SAVE = r'''
import FreeCAD as App, FreeCADGui as Gui
doc = App.openDocument({path!r}); Gui.updateGui()
for b in [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]:
    for o in [b] + list(b.Group):
        o.ViewObject.Visibility = o is b or o == b.Tip
v = Gui.activeDocument().activeView(); v.viewIsometric(); v.fitAll(); Gui.updateGui()
doc.save(); open({path!r} + ".gui_ok", "w").write("ok")
import os; os._exit(0)                                 # closing the window leaves FreeCAD running (hung to the timeout)
'''


def gui_save(out):
    """Re-save the document once through the FreeCAD GUI on a virtual display: a file saved headless has no
    GuiDocument.xml, and FreeCAD then opens it with every object hidden (the owner saw a blank file, 2026-09-27).
    False when no display could be made; the file is then the headless one."""
    py, ok = Path(str(out) + ".gui.py"), Path(str(out) + ".gui_ok")
    py.write_text(GUI_SAVE.format(path=str(out))); ok.unlink(missing_ok=True)
    try:
        subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1280x1024x24", FREECAD.replace(".cmd", ""), str(py)],
                       capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return False
    for bak in Path(out).parent.glob(Path(out).stem + ".*.FCBak"):
        bak.unlink()                                   # FreeCAD's save backup
    import time
    for _ in range(30):                                # the snap's FreeCAD can finish after xvfb-run returns
        if ok.exists():
            return True
        time.sleep(1)
    return False


def write_gui(out, shape):
    """GuiDocument.xml written into the saved document: every object's visibility as the document stores it (body +
    tip, set in TAIL) and an isometric camera on the part. A file saved headless has none and FreeCAD opens it
    with every object hidden (the owner's blank file, 2026-09-28); this replaces a GUI re-save (7-32 s)."""
    import re
    import zipfile
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    with zipfile.ZipFile(out) as z:
        doc = z.read("Document.xml").decode()
        if "GuiDocument.xml" in z.namelist():
            return True
    vis = {}
    for m in re.finditer(r'<Object name="([^"]+)"[^>]*>(.*?)</Object>', doc, re.S):
        v = re.search(r'name="Visibility".*?value="(\w+)"', m.group(2), re.S)
        vis[m.group(1)] = bool(v) and v.group(1) == "true"
    vp = "".join(f'<ViewProvider name="{n}" expanded="0"><Properties Count="1" TransientCount="0">'
                 f'<Property name="Visibility" type="App::PropertyBool" status="1"><Bool value="{str(v).lower()}"/>'
                 f"</Property></Properties></ViewProvider>" for n, v in vis.items())
    bb = Bnd_Box(); BRepBndLib.Add_s(shape, bb)
    lo, hi = np.array(bb.CornerMin().Coord()), np.array(bb.CornerMax().Coord())
    c, diag = (lo + hi) / 2, float(np.linalg.norm(hi - lo)) or 1.0
    ax, ang = np.array([0.74290615, 0.30772212, 0.59447289]), 0.61583132   # FreeCAD's isometric orientation
    z = np.array([0.0, 0.0, 1.0])                      # the camera looks down its -Z: it sits along R z, focal away
    rz = z * np.cos(ang) + np.cross(ax, z) * np.sin(ang) + ax * np.dot(ax, z) * (1 - np.cos(ang))
    pos = c + rz * diag / 2
    nl = "&#10;"
    cam = (f"OrthographicCamera {{{nl}  viewportMapping ADJUST_CAMERA{nl}  position {pos[0]:.5f} {pos[1]:.5f} {pos[2]:.5f}{nl}"
           f"  orientation 0.74290615 0.30772212 0.59447289  0.61583132{nl}  nearDistance {-diag / 2:.5f}{nl}"
           f"  farDistance {1.5 * diag:.5f}{nl}  aspectRatio 1{nl}  focalDistance {diag / 2:.5f}{nl}  height {diag:.5f}{nl}{nl}}}{nl}")
    xml = (f"<?xml version='1.0' encoding='utf-8'?>\n<Document SchemaVersion=\"1\"><ViewProviderData Count=\"{len(vis)}\">"
           f'{vp}</ViewProviderData><Camera settings="{cam}"/></Document>\n')
    with zipfile.ZipFile(out, "a", zipfile.ZIP_DEFLATED) as z:
        z.writestr("GuiDocument.xml", xml)
    return True


def iter_solids(sh):
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    ex = TopExp_Explorer(sh, TopAbs_SOLID)
    while ex.More():
        yield ex.Current(); ex.Next()


def edit_check(out):
    """The editability check alone, on a saved document (the app runs it after the files are delivered)."""
    out = Path(out).resolve(); report = out.with_suffix(".edit.json"); py = out.with_suffix(".edit.py")
    py.write_text(EDIT_FN + EDIT_ONLY.format(out=str(out), report=str(report)))
    report.unlink(missing_ok=True)
    subprocess.run([FREECAD, str(py)], capture_output=True, text=True, timeout=900)
    return json.loads(report.read_text()) if report.exists() else {"error": "FreeCAD wrote no edit report"}


def build(tree, out, tol=0.05, edit_check=True):
    out = Path(out).resolve(); report = out.with_suffix(".report.json"); py = out.with_suffix(".build.py")
    T._PREFIX.clear(); T.APPLIED.clear()               # a fresh compile: every modifier records its edges
    ref, notes = T.compile_tree(tree, tol)
    # the features the compile skipped (self-intersecting sketch) or could not build are not in the STEP: leave them
    # out, or FreeCAD builds them anyway (a self-intersecting Level 2 became a sheet 39 mm past the part, symdiff 1.79)
    skip = {i for i, n in notes.items() if i != "result" and any(w in n for w in ("skipped", "failed", "refused on"))}
    brep = {}
    for f in tree["features"]:
        if f["op"] in ("round", "chamfer") and any(f.get(k) for k in ("near", "support", "coax", "round_axes")) \
                and T.APPLIED.get(f["id"]):
            from OCP.BRep import BRep_Builder
            from OCP.BRepTools import BRepTools
            from OCP.TopoDS import TopoDS_Compound
            c, b = TopoDS_Compound(), BRep_Builder(); b.MakeCompound(c)
            for e in T.APPLIED[f["id"]]:
                b.Add(c, e)
            brep[f["id"]] = str(out.with_suffix(f".{f['id']}.brep")); BRepTools.Write_s(c, brep[f["id"]])
    py.write_text(script(tree, out, report, tol, brep, skip, edit=edit_check))
    report.unlink(missing_ok=True)
    n = len(tree["features"])
    subprocess.run([FREECAD, str(py)], capture_output=True, text=True, timeout=600 + 20 * n)   # build + 180 s gate
    r = json.loads(report.read_text()) if report.exists() else {"ok": False, "error": "FreeCAD wrote no report"}
    if out.exists() and ref is not None:
        r["gui_saved"] = write_gui(out, ref)
    n_ref = r["ref_solids"] = len(list(iter_solids(ref)))
    if r.get("ok") and r.get("valid") and r.get("solids") == n_ref:   # as many solids as the STEP compile   # same solid as the STEP compile? (an invalid
        # shape makes the boolean volumes meaningless: the SV08 shroud read 0.0 while FreeCAD had lost 63 %)
        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps
        from OCP.STEPControl import STEPControl_Reader
        rd = STEPControl_Reader(); rd.ReadFile(str(out)[:-6] + ".fc.step"); rd.TransferRoots(); fc = rd.OneShape()
        v = T.volume(ref)
        # from the common part: a cut of two identical solids can return garbage (part 22: -303960 mm3, common = all)
        # booleans between two identical solids are unreliable (common = 0 on the user's 2912 mm3 solid, garbage
        # cuts on part 22), so "same solid" = matched solids with equal volume, area and centre of mass: the
        # largest relative difference (a FreeCAD build that drifted shows up in all three)
        def props(sh):
            out = []
            for x in iter_solids(sh):
                g, a = GProp_GProps(), GProp_GProps()
                BRepGProp.VolumeProperties_s(x, g); BRepGProp.SurfaceProperties_s(x, a); c = g.CentreOfMass()
                out.append((g.Mass(), a.Mass(), np.array([c.X(), c.Y(), c.Z()])))
            return sorted(out, key=lambda q: q[0])
        P, Q = props(ref), props(fc)
        size = abs(v) ** (1 / 3)
        r["symdiff"] = round(max(max(abs(p[0] - q[0]) / abs(p[0]), abs(p[1] - q[1]) / p[1],
                                     float(np.linalg.norm(p[2] - q[2])) / size) for p, q in zip(P, Q)), 5)
    return r


if __name__ == "__main__":
    print(json.dumps(build(json.load(open(sys.argv[1])), sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 0.05)))
