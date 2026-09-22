"""Measured facts for an LLM-authored reconstruction. Everything here is measured, nothing guessed.

For each chosen axis-normal slice: every loop, fitted as exact lines and arcs (auto2d's fitter,
0.02 mm), with coordinates. For each loop tracked across heights: its draft, from the Steiner
recess d(z) = (P(z0) - P(z)) / 2pi. The model decides the construction; these are its numbers.
usage: facts.py <stl> <out.json> [axis=2]
"""
import json
import math
import sys
import numpy as np
import trimesh
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "feature_recon"))
from slice import loops, dedupe                                    # noqa: E402
from auto2d import section2d, segment_loop, loop_area               # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reverse import segment as _segment                             # noqa: E402

stl, out = sys.argv[1], sys.argv[2]
m = trimesh.load(stl, force="mesh")
tri = np.asarray(m.triangles, float)
lo, hi = m.bounds
_arg = sys.argv[3] if len(sys.argv) > 3 else "auto"
if _arg == "auto":
    # the axis along which sections change least (auto2d's measure): perimeter at 30/50/70 %
    def _var(ax):
        ps = [sum(float(np.linalg.norm(b - a)) for a, b in section2d(tri, ax, lo[ax] + f * (hi[ax] - lo[ax])))
              for f in (0.3, 0.5, 0.7)]
        return (max(ps) - min(ps)) / max(np.mean(ps), 1e-9)
    AX = int(np.argmin([_var(a) for a in range(3)]))
else:
    AX = int(_arg)


def slice_loops(h):
    Ls = [dedupe(l) for l in loops(section2d(tri, AX, h)) if len(l) > 3]
    return [l for l in Ls if abs(loop_area(np.r_[l, l[:1]])) > 1e-3]


def describe(L):
    # reverse.segment, not auto2d.segment_loop: the latter turned coarse arcs into 1-segment lines (the facts for
    # part 16 were 210 lines and 2 arcs; its outline is 5 arcs)
    L2, prims = _segment(np.asarray(L, float))
    segs = []
    for p in prims:
        a, b = L2[p[1]], L2[p[2] if p[2] < len(L2) else 0]
        if p[0] == "line":
            segs.append({"line": [[round(a[0], 3), round(a[1], 3)], [round(b[0], 3), round(b[1], 3)]]})
        else:
            segs.append({"arc": {"from": [round(a[0], 3), round(a[1], 3)], "to": [round(b[0], 3), round(b[1], 3)],
                                 "centre": [round(float(p[3][0]), 3), round(float(p[3][1]), 3)],
                                 "r": round(float(p[4]), 3)}})
    area = loop_area(np.r_[L, L[:1]])
    per = float(np.sum(np.linalg.norm(np.diff(np.r_[L, L[:1]], axis=0), axis=1)))
    return {"area": round(abs(float(area)), 2), "perimeter": round(per, 3),
            "bbox": [[round(float(L[:, 0].min()), 3), round(float(L[:, 1].min()), 3)],
                     [round(float(L[:, 0].max()), 3), round(float(L[:, 1].max()), 3)]],
            "segments": segs}


# 1. structure by height: how many loops, and their perimeters, at fine pitch
zs = np.linspace(lo[AX] + 0.05, hi[AX] - 0.05, 120)
profile = []
for z in zs:
    Ls = slice_loops(z)
    profile.append((float(z), sorted([round(float(np.sum(np.linalg.norm(np.diff(np.r_[l, l[:1]], axis=0), axis=1))), 3)
                                       for l in Ls], reverse=True)))
# 2. levels = runs of constant loop count
levels, cur = [], None
for z, ps in profile:
    if cur is None or len(ps) != len(cur["perims"][-1]):
        if cur: levels.append(cur)
        cur = {"z_from": z, "z_to": z, "perims": [ps]}
    else:
        cur["z_to"] = z; cur["perims"].append(ps)
levels.append(cur)
facts = {"axis": "XYZ"[AX], "bbox_min": [round(float(x), 3) for x in lo],
         "bbox_max": [round(float(x), 3) for x in hi], "levels": []}
for lv in levels:
    zm = (lv["z_from"] + lv["z_to"]) / 2
    Ls = slice_loops(zm)
    Ls.sort(key=lambda l: -abs(loop_area(np.r_[l, l[:1]])))
    # draft per loop index: perimeter slope across the level -> recess rate -> angle
    P = np.array([p for p in lv["perims"] if len(p) == len(lv["perims"][0])])
    Z = np.linspace(lv["z_from"], lv["z_to"], len(P))
    drafts = []
    if len(P) >= 5 and lv["z_to"] - lv["z_from"] > 1.0:
        for k in range(P.shape[1]):
            slope = np.polyfit(Z, P[:, k], 1)[0]                     # dP/dz
            drafts.append(round(math.degrees(math.atan(-slope / (2 * math.pi))), 3))
    facts["levels"].append({
        "z_from": round(lv["z_from"], 3), "z_to": round(lv["z_to"], 3), "slice_at": round(zm, 3),
        "loops_sorted_by_perimeter_desc": lv["perims"][0] and len(lv["perims"][0]),
        "draft_deg_per_loop_by_perimeter_desc": drafts,
        "note": "draft > 0: the loop SHRINKS going up the axis (outer walls taper in; for a hole it widens)",
        "loops": [describe(L) for L in Ls]})
json.dump(facts, open(out, "w"), indent=1)
for lv in facts["levels"]:
    print(f"z {lv['z_from']:7.3f}-{lv['z_to']:7.3f}  loops {len(lv['loops'])}  drafts {lv['draft_deg_per_loop_by_perimeter_desc']}  "
          f"segs {[len(l['segments']) for l in lv['loops']]}")
