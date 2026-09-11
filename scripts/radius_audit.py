#!/usr/bin/env python3
"""Classify every built cylinder face as MATCHED or UNMATCHED against truth.json.

`ab_corpus.py` counts cylindrical faces in the written STEP. That number cannot tell a
recovered CAD cylinder from an invented one, and on coarse models both arms invent. This
splits the count by whether the face's radius exists in the source B-Rep at all.

Radius equality is NECESSARY, not sufficient: a right radius in the wrong place still
counts as matched, so `matched` here is an UPPER BOUND on real recall.

usage: radius_audit.py --a RUN --b RUN [--b-env k=v] [--variant normal] [--jobs 4]
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, json, os, subprocess, sys
from pathlib import Path

REL, ABS = 0.005, 1e-4


def shape_of(p: Path):
    """Radii of cylindrical faces, plus the B-Rep health of the written solid.

    Shape reconstruction is the goal, so the output must be a solid, not a bag of faces:
    a closed shell, topologically valid, with no free edges.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import (TopTools_IndexedDataMapOfShapeListOfShape,
                              TopTools_IndexedMapOfShape)
    r = STEPControl_Reader()
    if r.ReadFile(str(p)) != 1:
        return [], {}
    r.TransferRoots()
    sh = r.OneShape()
    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(sh, TopAbs_FACE, fm)
    radii = []
    for i in range(1, fm.Extent() + 1):
        s = BRepAdaptor_Surface(TopoDS.Face_s(fm.FindKey(i)))
        if s.GetType() == GeomAbs_Cylinder:
            radii.append(s.Cylinder().Radius())
    sm = TopTools_IndexedMapOfShape(); TopExp.MapShapes_s(sh, TopAbs_SOLID, sm)
    hm = TopTools_IndexedMapOfShape(); TopExp.MapShapes_s(sh, TopAbs_SHELL, hm)
    ef = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(sh, TopAbs_EDGE, TopAbs_FACE, ef)
    free = 0
    for i in range(1, ef.Extent() + 1):
        e = TopoDS.Edge_s(ef.FindKey(i))
        if BRep_Tool.Degenerated_s(e):
            continue
        if ef.FindFromIndex(i).Extent() < 2:
            free += 1
    try:
        valid = bool(BRepCheck_Analyzer(sh).IsValid())
    except Exception:  # noqa: BLE001
        valid = False
    health = {"faces": fm.Extent(), "solids": sm.Extent(), "shells": hm.Extent(),
              "free_edges": free, "valid": valid,
              "closed_solid": bool(sm.Extent() >= 1 and free == 0 and valid)}
    return radii, health


def radii_of(p: Path) -> list[float]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape
    r = STEPControl_Reader()
    if r.ReadFile(str(p)) != 1:
        return []
    r.TransferRoots()
    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(r.OneShape(), TopAbs_FACE, fm)
    out = []
    for i in range(1, fm.Extent() + 1):
        s = BRepAdaptor_Surface(TopoDS.Face_s(fm.FindKey(i)))
        if s.GetType() == GeomAbs_Cylinder:
            out.append(s.Cylinder().Radius())
    return out


def run_one(arm, engine, stl, outdir, env_extra, timeout, truth_radii):
    stem = Path(stl).stem
    out = Path(outdir) / f"{arm}_{stem}.step"
    try:
        subprocess.run([engine, stl, "-o", str(out), "--engine", "trueform"],
                       capture_output=True, text=True, timeout=timeout,
                       env=dict(os.environ, **env_extra))
    except subprocess.TimeoutExpired:
        return {"model": stem, "arm": arm, "status": "TIMEOUT"}
    if not out.exists():
        return {"model": stem, "arm": arm, "status": "NO_OUTPUT"}
    rs, health = shape_of(out)
    out.unlink()
    m = u = 0
    for r in rs:
        if any(abs(r - t) <= max(REL * t, ABS) for t in truth_radii):
            m += 1
        else:
            u += 1
    return {"model": stem, "arm": arm, "status": "OK", "n": len(rs), **health,
            "matched": m, "unmatched": u,
            "unmatched_radii": sorted({round(r, 4) for r in rs
                                       if not any(abs(r - t) <= max(REL * t, ABS)
                                                  for t in truth_radii)})}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True); ap.add_argument("--b", required=True)
    ap.add_argument("--corpus", default=str(Path.home() / "corpora/cadbench"))
    ap.add_argument("--out", default=str(Path.home() / ".cache/n4/radaudit"))
    ap.add_argument("--variant", default="normal"); ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=1200); ap.add_argument("--b-env", default="")
    a = ap.parse_args()

    truth = json.loads((Path(a.corpus) / "truth.json").read_text())
    outdir = Path(a.out); outdir.mkdir(parents=True, exist_ok=True)
    stls = sorted(Path(a.corpus).glob(f"*_{a.variant}.stl"))
    if a.variant == "fine":
        stls = [p for p in stls if p.name.startswith("NEG_")] or stls
    benv = dict(kv.split("=", 1) for kv in a.b_env.split(",") if "=" in kv)

    jobs = []
    for p in stls:
        key = p.stem[: -len(f"_{a.variant}")]
        tr = truth.get(key, {}).get("cyl_radii", [])
        for arm, eng in (("A", a.a), ("B", a.b)):
            jobs.append((arm, eng, str(p), benv if arm == "B" else {}, tr))
    print(f"{len(stls)} models x 2 arms, variant={a.variant}, B env={benv or 'none'}", flush=True)

    rows = []
    with cf.ProcessPoolExecutor(max_workers=a.jobs) as pool:
        futs = [pool.submit(run_one, arm, eng, stl, str(outdir), env, a.timeout, tr)
                for arm, eng, stl, env, tr in jobs]
        for i, f in enumerate(cf.as_completed(futs), 1):
            rows.append(f.result())
            if i % 100 == 0:
                print(f"  [{i}/{len(jobs)}]", flush=True)
    (outdir / f"rad_{a.variant}.json").write_text(json.dumps(rows, indent=1))

    by = {}
    for r in rows:
        by.setdefault(r["model"], {})[r["arm"]] = r
    tot = {"A": [0, 0], "B": [0, 0]}
    worse_m, better_m = [], []
    for mdl, d in sorted(by.items()):
        A, B = d.get("A"), d.get("B")
        if not A or not B or A["status"] != "OK" or B["status"] != "OK":
            continue
        for k in ("A", "B"):
            tot[k][0] += d[k]["matched"]; tot[k][1] += d[k]["unmatched"]
        if B["matched"] < A["matched"]: worse_m.append((mdl, A["matched"], B["matched"]))
        elif B["matched"] > A["matched"]: better_m.append((mdl, A["matched"], B["matched"]))
    print(f"\n=== {a.variant}: MATCHED (upper bound on real recall) ===")
    print(f"  A matched {tot['A'][0]}  unmatched {tot['A'][1]}")
    print(f"  B matched {tot['B'][0]}  unmatched {tot['B'][1]}")
    print(f"  matched delta {tot['B'][0]-tot['A'][0]:+d}   "
          f"unmatched delta {tot['B'][1]-tot['A'][1]:+d}")
    print(f"  models worse-on-matched {len(worse_m)} | better-on-matched {len(better_m)}")
    for arm in ("A", "B"):
        ok = [d[arm] for d in by.values() if arm in d and d[arm].get("status") == "OK"]
        if not ok:
            continue
        print(f"  arm {arm} B-Rep health: closed valid solids "
              f"{sum(1 for r in ok if r.get('closed_solid'))}/{len(ok)}   "
              f"valid {sum(1 for r in ok if r.get('valid'))}   "
              f"with a solid {sum(1 for r in ok if r.get('solids', 0) >= 1)}   "
              f"free-edge-free {sum(1 for r in ok if r.get('free_edges') == 0)}")
    for mdl, x, y in worse_m: print(f"    WORSE  {mdl:42} {x:>4} -> {y:>4}")
    for mdl, x, y in better_m[:12]: print(f"    better {mdl:42} {x:>4} -> {y:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
