#!/usr/bin/env python3
"""CADScore: one 0-100 number for "did we rebuild the SHAPE as a B-Rep?".

Shape reconstruction, not metrology. Two rules follow from that, and both were learned the
hard way on this corpus:

1. MATCH AT THE MESH DEFLECTION. A cylinder counts as rebuilt when its radius is within the
   model's tessellation deflection of a truth radius. Below that the mesh carries no
   information distinguishing the two. (SpeedTest builds 0.2034 against truth 0.199996 --
   1 % of its 0.3545 mm deflection. NEG_SOT-1334-1's n5h cylinder is 2.5x its deflection
   off: a real shape error.)

2. SCORE ONLY RESOLVABLE GEOMETRY. A truth cylinder whose radius is SMALLER than the mesh
   deflection is not in the mesh; no engine can recover it and counting it only hides real
   performance. 278 of SpeedTestStructure's 285 truth cylinder faces are R=0.2 against a
   0.3545 mm deflection -- 36 % of the main set's denominator, all unrecoverable.
   Needs `cyl_radii_hist` in truth.json (scripts/truth_face_radii.py); the deduplicated
   `cyl_radii` list hides distributions like that one. Pass --all to score everything.

    matched_m = min(#built cyl faces within deflection of a RESOLVABLE truth radius, truth_m)
    recall    = sum matched_m / sum truth_m        did we rebuild the analytic faces
    precision = sum matched_m / sum built_m        or did we invent surfaces
    CADScore  = 100 * 2PR/(P+R)

UPPER BOUND: radius agreement is necessary, not sufficient -- right size, wrong place still
counts. B-Rep validity is reported by radius_audit.py and is a guard, not folded in here.

usage: cadscore.py [--all] <rad_*.json> [...]      (output of radius_audit.py)
"""
import json, sys
from pathlib import Path

TRUTH = json.loads((Path.home() / "corpora/cadbench/truth.json").read_text())


def score(rows, variant, resolvable_only=True):
    M = T = B = 0.0
    excluded = 0
    for r in rows:
        if r.get("status") != "OK":
            continue
        key = r["model"][: -len(f"_{variant}")]
        tr = TRUTH.get(key, {})
        tol = max(tr.get("stl", {}).get(variant, {}).get("deflection", 0.0), 1e-6)
        hist = {float(k): v for k, v in (tr.get("cyl_radii_hist") or {}).items()}
        bm = r.get("n", 0)
        if hist:
            keep = {rad: n for rad, n in hist.items()
                    if not resolvable_only or rad >= tol}
            excluded += sum(hist.values()) - sum(keep.values())
        else:
            keep = {}
        tm = sum(keep.values())
        mm = r.get("matched", 0)
        rads = r.get("unmatched_radii") or []
        if rads and keep:
            per_r = r.get("unmatched", 0) / len(rads)
            for x in rads:
                if any(abs(x - rad) <= tol for rad in keep):
                    mm += per_r
        # Built faces that match an EXCLUDED (sub-resolution) truth radius are neither
        # credit nor blame: we declared those features unrecoverable, so penalising their
        # reconstruction as "invention" would be incoherent. Drop them from `built` too.
        if resolvable_only and hist and rads:
            drop = {rad for rad in hist if rad < tol}
            per_r = r.get("unmatched", 0) / len(rads)
            for x in rads:
                if any(abs(x - rad) <= tol for rad in drop) and \
                   not any(abs(x - rad) <= tol for rad in keep):
                    bm -= per_r
        bm = max(bm, 0)
        if tm == 0 and bm == 0:
            tm = bm = mm = 1
        M += min(mm, tm); T += tm; B += bm
    rec = M / T if T else 0.0
    pre = M / B if B else 0.0
    f1 = 2 * pre * rec / (pre + rec) if (pre + rec) else 0.0
    return 100 * f1, 100 * rec, 100 * pre, M, T, B, excluded


def main():
    args = [a for a in sys.argv[1:] if a != "--all"]
    ro = "--all" not in sys.argv
    for p in args:
        rows = json.loads(Path(p).read_text())
        variant = Path(p).stem.split("_", 1)[1]
        print(f"\n== {p}  ({variant}, "
              f"{'resolvable only' if ro else 'all truth faces'}, tol = deflection)")
        for arm in sorted({r["arm"] for r in rows}):
            s, rec, pre, M, T, B, ex = score(
                [r for r in rows if r["arm"] == arm], variant, ro)
            print(f"   arm {arm}   CADScore {s:6.2f}   recall {rec:6.2f}%  "
                  f"precision {pre:6.2f}%   matched {M:.0f}  truth {T:.0f}  built {B:.0f}"
                  + (f"   (excluded {ex} sub-resolution)" if ro else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
