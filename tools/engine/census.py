"""Corpus census of the evidence (docs/ENGINE.md milestone 1): what the language L must cover, counted over the
whole corpus, never decided on one part.

usage: census.py <steps_dir> [out.json]
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence as E                                   # noqa: E402


def row(step):
    shape = E.read(step)
    recs = E.surfaces(shape)
    total = sum(r["area"] for r in recs) or 1.0
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    b = Bnd_Box()
    BRepBndLib.Add_s(shape, b)
    x0, y0, z0, x1, y1, z1 = b.Get()
    tol = max(3e-3 * math.dist((x0, y0, z0), (x1, y1, z1)), 0.05)
    ev = E.candidates(recs, tol)
    planes = [n for n in ev["normals"]]
    return {
        "faces": ev["faces"],
        "kinds": ev["area_share_by_kind"],
        "axis_aligned_planes": round(sum(n["area_share"] for n in planes if n["axis_aligned"]), 4),
        "general_planes": round(sum(n["area_share"] for n in planes if not n["axis_aligned"]), 4),
        "general_normals": sum(1 for n in planes if not n["axis_aligned"] and n["area_share"] > 0.01),
        "circles": sum(len(n["circles"]) for n in planes),
        "partial_curved": sum(len(n["partial_curved"]) for n in planes),
        "curved_off_axis": round(sum(r["area"] for r in recs if r["kind"] in ("cylinder", "cone", "torus")
                                     and max(abs(x) for x in r["axis"]) < 0.999) / total, 4),
        "revolve_axes": sum(1 for a in ev["coaxial"] if a["surfaces"] >= 3 and len(a["kinds"]) >= 2),
        "tol": round(tol, 4),
    }


if __name__ == "__main__":
    d = Path(sys.argv[1])
    out = {}
    for p in sorted(d.glob("*.step"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0):
        try:
            out[p.stem] = row(p)
        except Exception as e:                           # noqa: BLE001
            out[p.stem] = {"error": repr(e)[:200]}
        print(p.stem, json.dumps(out[p.stem]), flush=True)
    ok = [r for r in out.values() if "error" not in r]
    if ok:
        agg = {"parts": len(ok),
               "needs_general_plane (>2% area)": sum(r["general_planes"] > 0.02 for r in ok),
               "needs_revolve (coaxial >=3, >=2 kinds)": sum(r["revolve_axes"] > 0 for r in ok),
               "curved_off_axis (>2% area)": sum(r["curved_off_axis"] > 0.02 for r in ok),
               "has_torus_or_cone": sum(("torus" in r["kinds"]) or ("cone" in r["kinds"]) for r in ok),
               "other_surfaces (>2% area)": sum(r["kinds"].get("other", 0) > 0.02 for r in ok)}
        print(json.dumps(agg))
        out["_aggregate"] = agg
    if len(sys.argv) > 2:
        json.dump(out, open(sys.argv[2], "w"), indent=1)
