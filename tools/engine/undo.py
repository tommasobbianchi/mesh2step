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
    d.SetRunParallel(False)                            # a parallel run leaves OCCT's thread pool in this process and
                                                       # every later fork deadlocks (the hypothesis forks of run.py)
    d.Build()
    if not d.IsDone():
        return None
    s = d.Shape()
    return s if BRepCheck_Analyzer(s).IsValid() else None


def unexplained_sets(shape, explained):
    """The faces the base cannot explain, split into edge-connected sets: each set is one undo candidate. Faces are
    looked up in OCCT's hashed index map (a nested IsSame search was quadratic: part 16's 1946 faces took most of
    the part's 40-minute budget)."""
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_IndexedMapOfShape
    fl = faces(shape)
    fmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fmap)
    pos = {fmap.FindIndex(f): i for i, f in enumerate(fl)}          # map index -> position in fl
    bad = {i for i in range(len(fl)) if not explained[i]}
    parent = {i: i for i in bad}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    emap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, emap)
    for e in range(1, emap.Extent() + 1):
        adj = [k for k in (pos.get(fmap.FindIndex(f)) for f in emap.FindFromIndex(e)) if k in bad]
        for k in adj[1:]:
            parent[find(k)] = find(adj[0])
    groups = {}
    for i in sorted(bad):
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


UNDO_MEM_GB = 8.0      # budget of the exact undo: a scan-faceted solid (part 19: 39450 faces) needs 40+ GB and
UNDO_S = 300.0         # takes a whole host down; within budget it is seconds on an analytic one


def _trial(shape, rm, mem_bytes):
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    return defeature(shape, rm) is not None


def defeature_budgeted(shape, rm):
    """defeature() only if a forked trial under the memory and time budget succeeds (OCCT has no budget of its own
    and segfaults or eats the host past it). -> shape or None."""
    import time
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tree"))
    import propose as PR
    ok = PR._fork_collect(PR._fork_start(_trial, shape, rm, int(UNDO_MEM_GB * 2 ** 30)), time.time() + UNDO_S, False)
    return defeature(shape, rm) if ok else None


def undo_chains(shape, planes=None, budget_s=240.0):
    """Undo what the base planes cannot explain ONE chain at a time (Analysis Situs' SuppressBlendsInc loop around
    OCCT defeaturing): the biggest remaining chain first, the evidence re-derived from the new solid after every
    success (faces change identity), a chain that fails skipped for good. One big face set at once is what made
    BRepAlgoAPI_Defeaturing return the solid unchanged or run out of memory. -> (solid or None, chains undone)"""
    import time
    t0 = time.time()
    cur, done, failed = shape, 0, set()
    while time.time() - t0 < budget_s:
        b = base_kind(cur) if planes is None else (None, planes, None, _explained(cur, planes))
        sets = [x for x in unexplained_sets(cur, b[3]) if _sig(x) not in failed]
        if not sets:
            break
        sets.sort(key=lambda x: -sum(describe(f)[3] for f in x))
        nxt = defeature_budgeted(cur, sets[0])
        if nxt is None or len(faces(nxt)) >= len(faces(cur)):
            failed.add(_sig(sets[0]))                 # refused or unchanged: never tried again
            continue
        cur, done = nxt, done + 1
        if planes is None:
            planes = base_kind(shape)[1]              # keep the planes of the served solid while undoing
    return (cur if done else None), done


def _sig(fs):
    """A chain's identity across iterations: its face count and total area (faces themselves change objects)."""
    return (len(fs), round(sum(describe(f)[3] for f in fs), 3))


def _explained(shape, planes):
    import math
    ang = math.radians(0.5)
    out = []
    for f in faces(shape):
        k, d, _, _ = describe(f)
        ok = False
        if d is not None:
            for a in planes:
                c = abs(float(d @ AXES[a]))
                ok |= (k == "plane" and (c > math.cos(ang) or c < math.sin(ang))) or (k == "cylinder" and c > math.cos(ang))
        out.append(ok)
    return np.array(out, bool)
