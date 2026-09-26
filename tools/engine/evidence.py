"""Evidence E for the design-history engine (docs/ENGINE.md section 3): the exact surfaces the production
converter fitted to the mesh, read from its STEP, turned into the candidate sets the solver may draw from.
Facts only: no rule here decides a design, the objective does.

usage: evidence.py <part.step> [out.json]
"""
import json
import math
import sys

import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus
from OCP.GProp import GProp_GProps
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

KIND = {GeomAbs_Plane: "plane", GeomAbs_Cylinder: "cylinder", GeomAbs_Cone: "cone", GeomAbs_Torus: "torus",
        GeomAbs_Sphere: "sphere"}


def _v(d):
    return np.array([d.X(), d.Y(), d.Z()], float)


def read(path):
    r = STEPControl_Reader()
    if r.ReadFile(str(path)) != 1:
        raise ValueError(f"cannot read {path}")
    r.TransferRoots()
    return r.OneShape()


def surfaces(shape):
    """Every face as a record: kind, area and its analytic parameters (other kinds only kind + area)."""
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        ex.Next()
        g = GProp_GProps()
        BRepGProp.SurfaceProperties_s(f, g)
        s = BRepAdaptor_Surface(f)
        k = KIND.get(s.GetType(), "other")
        rec = {"kind": k, "area": g.Mass()}
        u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
        if k == "plane":
            p = s.Plane()
            n = _v(p.Axis().Direction())
            if f.Orientation() == TopAbs_REVERSED:
                n = -n
            rec.update(normal=n.tolist(), offset=float(n @ _v(p.Location())))
        elif k in ("cylinder", "cone", "torus"):
            q = {"cylinder": s.Cylinder, "cone": s.Cone, "torus": s.Torus}[k]()
            ax = q.Axis() if k == "torus" else q.Axis()
            a, o = _v(ax.Direction()), _v(ax.Location())
            rec.update(axis=a.tolist(), origin=o.tolist(), span=float(u1 - u0))
            if k == "cylinder":
                rec.update(radius=q.Radius(), extent=[float(v0), float(v1)])
            elif k == "cone":
                rec.update(radius=q.RefRadius(), half_angle=q.SemiAngle(), extent=[float(v0), float(v1)])
            else:
                rec.update(major=q.MajorRadius(), minor=q.MinorRadius())
        out.append(rec)
    return out


def _cluster_dirs(recs, key, ang):
    """Directions (sign-agnostic) clustered within `ang` radians, weighted by area -> [(unit, area, members)]."""
    cl = []
    for i, r in enumerate(recs):
        d = np.array(r[key])
        for c in cl:
            if abs(float(c[0] @ d)) > math.cos(ang):
                c[1] += r["area"]
                c[2].append(i)
                break
        else:
            cl.append([d / np.linalg.norm(d), r["area"], [i]])
    return sorted(cl, key=lambda c: -c[1])


def candidates(recs, tol):
    """The candidate sets of docs/ENGINE.md section 3, per sketch-plane normal."""
    total = sum(r["area"] for r in recs) or 1.0
    planes = [r for r in recs if r["kind"] == "plane"]
    curved = [r for r in recs if r["kind"] in ("cylinder", "cone", "torus")]
    normals = []
    for d, area, idx in _cluster_dirs(planes, "normal", math.radians(1.0)):
        if abs(d).max() > 0.999:                        # report axis-aligned normals with a positive sign
            d = np.round(np.abs(d)) if abs(d).max() > 0.999 else d
        levels = []
        for i in idx:
            z = float(np.array(planes[i]["normal"]) @ d) * planes[i]["offset"]
            for L in levels:
                if abs(L["z"] - z) <= tol:
                    L["area"] += planes[i]["area"]
                    break
            else:
                levels.append({"z": z, "area": planes[i]["area"]})
        circles, finishes = [], []
        for r in curved:
            if abs(float(np.array(r["axis"]) @ d)) < math.cos(math.radians(1.0)):
                continue
            o = np.array(r["origin"])
            c = o - (o @ d) * d                        # centre, in 3D on the plane through the origin
            rad = r.get("radius", r.get("major"))
            item = {"kind": r["kind"], "centre": c.round(4).tolist(), "radius": round(float(rad), 4),
                    "span_deg": round(math.degrees(r["span"]), 1), "area": r["area"]}
            if r["kind"] == "torus":
                item["minor"] = round(r["minor"], 4)
            (circles if r["span"] > math.radians(150) and r["kind"] == "cylinder" else finishes).append(item)
        normals.append({"normal": d.round(6).tolist(), "area_share": round(area / total, 4),
                        "axis_aligned": bool(abs(d).max() > 0.999), "levels": sorted(levels, key=lambda L: L["z"]),
                        "circles": circles, "partial_curved": finishes})
    axes = []                                          # revolve evidence: curved surfaces sharing one axis line
    for d, area, idx in _cluster_dirs(curved, "axis", math.radians(1.0)):
        lines = []
        for i in idx:
            o = np.array(curved[i]["origin"])
            p = o - (o @ d) * d
            for ln in lines:
                if np.linalg.norm(ln["p"] - p) <= tol:
                    ln["n"] += 1
                    ln["kinds"].add(curved[i]["kind"])
                    ln["area"] += curved[i]["area"]
                    break
            else:
                lines.append({"p": p, "n": 1, "kinds": {curved[i]["kind"]}, "area": curved[i]["area"]})
        for ln in lines:
            if ln["n"] >= 2:
                axes.append({"axis": d.round(6).tolist(), "point": ln["p"].round(4).tolist(), "surfaces": ln["n"],
                             "kinds": sorted(ln["kinds"]), "area_share": round(ln["area"] / total, 4)})
    kinds = {}
    for r in recs:
        kinds[r["kind"]] = kinds.get(r["kind"], 0.0) + r["area"] / total
    return {"faces": len(recs), "area_share_by_kind": {k: round(v, 4) for k, v in kinds.items()},
            "normals": normals, "coaxial": sorted(axes, key=lambda a: -a["area_share"])}


def evidence(step_path, tol):
    return candidates(surfaces(read(step_path)), tol)


if __name__ == "__main__":
    shape = read(sys.argv[1])
    recs = surfaces(shape)
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    b = Bnd_Box()
    BRepBndLib.Add_s(shape, b)
    x0, y0, z0, x1, y1, z1 = b.Get()
    tol = max(3e-3 * math.dist((x0, y0, z0), (x1, y1, z1)), 0.05)
    ev = candidates(recs, tol)
    ev["tol"] = round(tol, 4)
    if len(sys.argv) > 2:
        json.dump(ev, open(sys.argv[2], "w"), indent=1)
    print(json.dumps({k: ev[k] for k in ("faces", "area_share_by_kind", "tol")}))
    for n in ev["normals"][:6]:
        print(n["normal"], n["area_share"], "levels", [round(L["z"], 2) for L in n["levels"]],
              "circles", [(c["radius"], c["span_deg"]) for c in n["circles"]][:6],
              "partial", [(c["kind"], c["radius"], c["span_deg"]) for c in n["partial_curved"]][:6])
    for a in ev["coaxial"][:4]:
        print("coaxial", a)
