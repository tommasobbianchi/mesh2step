"""Exact undo on the B-rep (docs/ENGINE.md section 4, backward): remove a face set with OCCT's defeaturing (the
solid is healed as if the feature had never been made) and test whether what is left is a base: extrusions from
one sketch plane (every face either parallel to the extrusion axis or a flat cap across it), or two such planes.

usage: undo.py <part.step>      (prints the face census, the finish undo and the base test before/after)
"""
import math
import sys
from pathlib import Path

import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Torus
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_ListOfShape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence as E                                   # noqa: E402

AXES = np.eye(3)


def faces(shape):
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        out.append(TopoDS.Face_s(ex.Current()))
        ex.Next()
    return out


def describe(f):
    """(kind, direction, span, area): plane -> its normal; cylinder/cone/torus -> its axis; else no direction."""
    s = BRepAdaptor_Surface(f)
    t = s.GetType()
    g = GProp_GProps()
    BRepGProp.SurfaceProperties_s(f, g)
    u0, u1, _, _ = BRepTools.UVBounds_s(f)
    if t == GeomAbs_Plane:
        return "plane", E._v(s.Plane().Axis().Direction()), None, g.Mass()
    if t in (GeomAbs_Cylinder, GeomAbs_Cone, GeomAbs_Torus):
        q = {GeomAbs_Cylinder: s.Cylinder, GeomAbs_Cone: s.Cone, GeomAbs_Torus: s.Torus}[t]()
        k = {GeomAbs_Cylinder: "cylinder", GeomAbs_Cone: "cone", GeomAbs_Torus: "torus"}[t]
        return k, E._v(q.Axis().Direction()), u1 - u0, g.Mass()
    return "other", None, None, g.Mass()


def base_kind(shape, ang=math.radians(0.5)):
    """Which sketch planes the solid needs: for each axis a, the faces an extrusion along a explains (planes across
    a, planes and cylinders parallel to a). -> (planes needed, axes, share of area left unexplained)."""
    fs = [describe(f) for f in faces(shape)]
    total = sum(x[3] for x in fs) or 1.0

    def along(a):
        ok = np.zeros(len(fs), bool)
        for i, (k, d, _, _) in enumerate(fs):
            if d is None:
                continue
            c = abs(float(d @ AXES[a]))
            if k == "plane":
                ok[i] = c > math.cos(ang) or c < math.sin(ang)       # a cap across a, or a wall parallel to a
            elif k == "cylinder":
                ok[i] = c > math.cos(ang)                             # a wall parallel to a
        return ok

    ex = [along(a) for a in range(3)]
    area = np.array([x[3] for x in fs])
    best = None
    for a in range(3):
        left = float(area[~ex[a]].sum() / total)
        if best is None or left < best[2]:
            best = (1, (a,), left, ex[a])
    for a in range(3):
        for b in range(a + 1, 3):
            left = float(area[~(ex[a] | ex[b])].sum() / total)
            if left < best[2] - 1e-6:
                best = (2, (a, b), left, ex[a] | ex[b])
    return best


def defeature(shape, rm):
    """Shape with the faces `rm` removed and healed -> shape or None when OCCT refuses."""
    d = BRepAlgoAPI_Defeaturing()
    d.SetShape(shape)
    lst = TopTools_ListOfShape()
    for f in rm:
        lst.Append(f)
    d.AddFacesToRemove(lst)
    d.SetRunParallel(True)
    d.Build()
    if not d.IsDone():
        return None
    s = d.Shape()
    return s if BRepCheck_Analyzer(s).IsValid() else None


def unexplained_sets(shape, explained):
    """The faces the base cannot explain, split into edge-connected sets: each set is one undo candidate."""
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    fl = faces(shape)
    bad = [i for i in range(len(fl)) if not explained[i]]
    emap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, emap)
    idx = {}
    for i in bad:
        idx[i] = i
    parent = {i: i for i in bad}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for e in range(1, emap.Extent() + 1):
        adj = [k for k in bad for f in emap.FindFromIndex(e) if fl[k].IsSame(f)]
        for k in adj[1:]:
            parent[find(k)] = find(adj[0])
    groups = {}
    for i in bad:
        groups.setdefault(find(i), []).append(fl[i])
    return list(groups.values())


if __name__ == "__main__":
    shape = E.read(sys.argv[1])
    fs = [describe(f) for f in faces(shape)]
    kinds = {}
    for k, _, _, a in fs:
        kinds[k] = kinds.get(k, 0) + 1
    b = base_kind(shape)
    print("faces", len(fs), kinds, "| base:", b[0], "planes", b[1], "unexplained", round(b[2], 4))
    sets = unexplained_sets(shape, b[3])
    print("undo candidates:", len(sets), "sizes", sorted((len(x) for x in sets), reverse=True)[:12])
    t = defeature(shape, [f for x in sets for f in x]) if sets else shape
    if t is None:
        ok = sum(defeature(shape, x) is not None for x in sets)
        print(f"all at once refused; one set at a time: {ok}/{len(sets)} accepted")
    else:
        b2 = base_kind(t)
        print("after undoing all:", b2[0], "planes", b2[1], "unexplained", round(b2[2], 4), "faces", len(faces(t)))
