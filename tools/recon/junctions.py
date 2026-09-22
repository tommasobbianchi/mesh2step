"""Library part 1: take a B-rep (STEP) apart into junctions and blends (docs/JUNCTIONS.md).

    junctions.extract(step) -> {"junctions": [...], "blends": [...]}
    junctions.py catalog <out.json> <step> [<step> ...]

Every field and signature is defined in docs/JUNCTIONS.md; nothing is decided here.
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepGProp import BRepGProp
from OCP.Bnd import Bnd_Box
from OCP.GeomAbs import GeomAbs_CurveType, GeomAbs_SurfaceType
from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
from OCP.GProp import GProp_GProps
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import (TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_REVERSED)
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.gp import gp_Pnt, gp_Vec

_FACE_KIND = {
    GeomAbs_SurfaceType.GeomAbs_Plane: "plane",
    GeomAbs_SurfaceType.GeomAbs_Cylinder: "cylinder",
    GeomAbs_SurfaceType.GeomAbs_Cone: "cone",
    GeomAbs_SurfaceType.GeomAbs_Torus: "torus",
    GeomAbs_SurfaceType.GeomAbs_Sphere: "sphere",
}
_CURVE_KIND = {
    GeomAbs_CurveType.GeomAbs_Line: "line",
    GeomAbs_CurveType.GeomAbs_Circle: "circle",
    GeomAbs_CurveType.GeomAbs_Ellipse: "ellipse",
}
_BLEND_KINDS = ("cylinder", "cone", "torus", "sphere")


def _load(step_path):
    reader = STEPControl_Reader()
    if reader.ReadFile(str(step_path)) != 1:
        raise ValueError(f"cannot read STEP: {step_path}")
    reader.TransferRoots()
    return reader.OneShape()


def _face_kind(ad):
    return _FACE_KIND.get(ad.GetType(), "other")


def _curve_kind(ac):
    return _CURVE_KIND.get(ac.GetType(), "other")


def _diag(shape):
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    return max(float(box.CornerMax().Distance(box.CornerMin())), 1e-6)


def _outward_normal(ad, face, u, v):
    n = ad.DN(u, v, 1, 0).Crossed(ad.DN(u, v, 0, 1))
    if n.Magnitude() < 1e-12:
        return None
    n.Normalize()
    if face.Orientation() == TopAbs_REVERSED:
        n.Reverse()
    return n


def _uv_on(face, point):
    proj = GeomAPI_ProjectPointOnSurf(point, BRep_Tool.Surface_s(face))
    if proj.NbPoints() == 0:
        return None
    return proj.LowerDistanceParameters()


def _normal_at(face, ad, point):
    uv = _uv_on(face, point)
    if uv is None:
        return None, None
    return _outward_normal(ad, face, uv[0], uv[1]), uv


def _angle_deg(n1, n2):
    d = max(-1.0, min(1.0, n1.Dot(n2)))
    return math.degrees(math.acos(d))


def _edge_midpoint(ac):
    return ac.Value(0.5 * (ac.FirstParameter() + ac.LastParameter()))


def _edge_length(edge):
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, props)
    return props.Mass()


def _axis_matches(circ, axis):
    d = circ.Axis().Direction()
    if abs(d.Dot(axis.Direction())) < 1.0 - 1e-6:
        return False
    c = circ.Location()
    loc = axis.Location()
    v = gp_Vec(loc, c)
    d = axis.Direction()
    along = v.X() * d.X() + v.Y() * d.Y() + v.Z() * d.Z()
    perp = math.sqrt(max(0.0, v.SquareMagnitude() - along * along))
    return perp < 1e-5


def _coaxial(circ, kinds, surfs):
    for kind, ad in zip(kinds, surfs):
        if kind == "cylinder":
            axis = ad.Cylinder().Axis()
        elif kind == "cone":
            axis = ad.Cone().Axis()
        elif kind == "torus":
            axis = ad.Torus().Axis()
        else:
            continue
        if _axis_matches(circ, axis):
            return True
    return None


def _tangent_normals(faceA, adA, faceB, adB, ac):
    """True iff the two outward normals agree within 2 degrees at 5 samples along the edge.

    Returns (tangent, (nA, nB, midpoint)). Normals are always the midpoint values so the
    caller can measure angle/convexity on non-tangent junctions too.
    """
    t0, t1 = ac.FirstParameter(), ac.LastParameter()
    tangent = True
    for k in range(5):
        t = t0 + (t1 - t0) * k / 4.0
        p = ac.Value(t)
        nA, _ = _normal_at(faceA, adA, p)
        nB, _ = _normal_at(faceB, adB, p)
        if nA is None or nB is None or _angle_deg(nA, nB) > 2.0:
            tangent = False
    mid = ac.Value(0.5 * (t0 + t1))
    nA, _ = _normal_at(faceA, adA, mid)
    nB, _ = _normal_at(faceB, adB, mid)
    return tangent, (nA, nB, mid)


def _convex_at(shape, point, nA, nB, eps):
    """Material angle < 180 deg: step into face A's outside and face B's inside."""
    d = nA.Subtracted(nB)
    q = gp_Pnt(point.X() + d.X() * eps, point.Y() + d.Y() * eps, point.Z() + d.Z() * eps)
    sc = BRepClass3d_SolidClassifier(shape, q, 1e-6)
    return sc.State() != TopAbs_IN


def _blend_radius(ad):
    t = ad.GetType()
    if t == GeomAbs_SurfaceType.GeomAbs_Cylinder:
        return ad.Cylinder().Radius()
    if t == GeomAbs_SurfaceType.GeomAbs_Torus:
        return ad.Torus().MinorRadius()
    if t == GeomAbs_SurfaceType.GeomAbs_Sphere:
        return ad.Sphere().Radius()
    return None


def _blend_round(face, ad, uv):
    """Material on the concave side of the blend surface => a convex bulge (round)."""
    u, v = uv
    h = 1e-4
    use_v = ad.GetType() == GeomAbs_SurfaceType.GeomAbs_Torus
    n0 = _outward_normal(ad, face, u, v)
    if n0 is None:
        return False
    if use_v:
        n1 = _outward_normal(ad, face, u, v + h)
        dP = ad.DN(u, v, 0, 1)
    else:
        n1 = _outward_normal(ad, face, u + h, v)
        dP = ad.DN(u, v, 1, 0)
    if n1 is None:
        return False
    return n1.Subtracted(n0).Dot(dP) > 0.0


def _centroid(face):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    c = props.CentreOfMass()
    return [c.X(), c.Y(), c.Z()]


def _edge_records(shape, fmap, emap, edge_faces, eps):
    adj = defaultdict(list)
    records = []
    for ei in range(1, emap.Extent() + 1):
        edge = TopoDS.Edge_s(emap.FindKey(ei))
        fis = edge_faces.get(ei)
        if not fis or len(fis) != 2:
            continue
        if BRep_Tool.Degenerated_s(edge):
            continue
        length = _edge_length(edge)
        if length <= 1e-9:
            continue
        fi, fj = fis
        faceA, faceB = TopoDS.Face_s(fmap.FindKey(fi)), TopoDS.Face_s(fmap.FindKey(fj))
        adA, adB = BRepAdaptor_Surface(faceA), BRepAdaptor_Surface(faceB)
        ac = BRepAdaptor_Curve(edge)
        ka, kb = _face_kind(adA), _face_kind(adB)
        a, b = (ka, kb) if ka <= kb else (kb, ka)
        curve = _curve_kind(ac)

        tangent, (nA, nB, mid) = _tangent_normals(faceA, adA, faceB, adB, ac)
        if tangent:
            state, convex = "tangent", None
        else:
            convex = _convex_at(shape, mid, nA, nB, eps) if (nA and nB) else True
            state = "convex" if convex else "concave"
        angle = _angle_deg(nA, nB) if (nA and nB) else 0.0

        radius = None
        circ = None
        if curve == "circle":
            circ = ac.Circle()
            radius = circ.Radius()
        centre = _edge_midpoint(ac)
        record = {
            "a": a, "b": b, "curve": curve, "tangent": tangent, "convex": convex,
            "angle": angle, "radius": radius,
            "coaxial": _coaxial(circ, (ka, kb), (adA, adB)) if circ else None,
            "centre": [centre.X(), centre.Y(), centre.Z()],
            "length": length,
            "sig": f"{a}|{b}|{curve}|{state}",
            "_faces": (fi, fj, tangent),
        }
        records.append(record)
        adj[fi].append((fj, tangent, centre))
        adj[fj].append((fi, tangent, centre))
    return records, adj


def _blend_records(fmap, adj, face_recs, eps):
    blends = []
    for fi in range(1, fmap.Extent() + 1):
        face = TopoDS.Face_s(fmap.FindKey(fi))
        ad = BRepAdaptor_Surface(face)
        kind = _face_kind(ad)
        if kind not in _BLEND_KINDS:
            continue
        neighbours = []
        for fj, tangent, mid in adj.get(fi, ()):
            if tangent and fj not in [n[0] for n in neighbours]:
                neighbours.append((fj, mid))
        if len(neighbours) < 2:
            continue
        (f1, _), (f2, probe) = neighbours[0], neighbours[1]
        k1 = face_recs[f1]["kind"]
        k2 = face_recs[f2]["kind"]
        between = "+".join(sorted((k1, k2)))
        centre = _centroid(face)
        uv = _uv_on(face, probe)
        is_round = _blend_round(face, ad, uv) if uv else False
        blends.append({
            "blend": kind,
            "between": between,
            "round": is_round,
            "radius": _blend_radius(ad),
            "centre": centre,
            "sig": f"blend:{kind}|{between}|{'round' if is_round else 'fillet'}",
        })
    return blends


def extract(step_path):
    shape = _load(step_path)
    eps = _diag(shape) * 1e-3

    fmap = TopTools_IndexedMapOfShape()
    emap = TopTools_IndexedMapOfShape()
    edge_faces = defaultdict(set)
    fex = TopExp_Explorer(shape, TopAbs_FACE)
    while fex.More():
        face = TopoDS.Face_s(fex.Current())
        fi = fmap.Add(face)
        eex = TopExp_Explorer(face, TopAbs_EDGE)
        while eex.More():
            ei = emap.Add(eex.Current())
            edge_faces[ei].add(fi)
            eex.Next()
        fex.Next()

    face_recs = {fi: {"kind": _face_kind(BRepAdaptor_Surface(TopoDS.Face_s(fmap.FindKey(fi))))}
                 for fi in range(1, fmap.Extent() + 1)}
    records, adj = _edge_records(shape, fmap, emap, edge_faces, eps)
    for r in records:
        r.pop("_faces", None)
    blends = _blend_records(fmap, adj, face_recs, eps)
    return {"junctions": records, "blends": blends}


def catalog(out_path, step_paths):
    signatures = {}
    for step in step_paths:
        rec = extract(step)
        part = Path(step).stem
        for r in rec["junctions"] + rec["blends"]:
            entry = signatures.setdefault(r["sig"], {"count": 0, "examples": []})
            entry["count"] += 1
            if len(entry["examples"]) < 5:
                entry["examples"].append({
                    "part": part,
                    "centre": r["centre"],
                    "radius": r.get("radius"),
                })
    out = {"parts": len(step_paths), "signatures": signatures}
    Path(out_path).write_text(json.dumps(out, indent=2))
    return out


def main(argv):
    if len(argv) < 4 or argv[1] != "catalog":
        print("usage: junctions.py catalog <out.json> <step> [<step> ...]", file=sys.stderr)
        return 2
    catalog(argv[2], argv[3:])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
