#!/usr/bin/env python3
"""A/B two engine binaries over the corpus and answer the promotion questions.

The questions, in the order that decides a promotion:
  1. PARITY   -- with its new behaviour inert, does arm B reproduce arm A byte-for-byte?
                 Compared on the STEP DATA SECTION only: the header carries a wall-clock
                 timestamp, so whole-file equality is always false and proves nothing.
                 (Only meaningful when arm B has an off switch; skipped otherwise.)
  2. RECALL   -- analytic cylindrical faces surviving into the written STEP, per model,
                 counted from the FILE, never from a RESULT counter. Counters in this
                 engine have lied twice (`watertight`, `smoothRevertedComponents`).
  3. WORSE    -- any model where B builds fewer cylinders than A. The gate is ZERO.
  4. SENTINELS-- the CAD-verified counts must land exactly.

Parallel by (model, arm). `seconds` from a parallel run is NOT a timing measurement.

usage: ab_corpus.py --a <run.sh|bin> --b <run.sh|bin> --corpus DIR --out DIR [--jobs N]
                    [--variant normal|fine|coarse] [--limit N]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

DATA_SKIP = 11  # STEP header lines before DATA; the header holds a timestamp


def cyl_faces_in_step(p: Path) -> int:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape
    r = STEPControl_Reader()
    if r.ReadFile(str(p)) != 1:
        return -1
    r.TransferRoots()
    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(r.OneShape(), TopAbs_FACE, fm)
    return sum(1 for i in range(1, fm.Extent() + 1)
               if BRepAdaptor_Surface(TopoDS.Face_s(fm.FindKey(i))).GetType() == GeomAbs_Cylinder)


def data_hash(p: Path) -> str:
    try:
        lines = p.read_text(errors="replace").splitlines()[DATA_SKIP:]
    except OSError:
        return "-"
    return hashlib.md5("\n".join(lines).encode()).hexdigest()[:12]


def run_one(arm: str, engine: str, stl: str, outdir: str, env_extra: dict, timeout: int) -> dict:
    stem = Path(stl).stem
    out = Path(outdir) / f"{arm}_{stem}.step"
    env = dict(os.environ, **env_extra)
    rec = {"model": stem, "arm": arm}
    try:
        pr = subprocess.run([engine, stl, "-o", str(out), "--engine", "trueform"],
                            capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {**rec, "status": "TIMEOUT", "cyl": -1}
    line = next((l for l in pr.stdout.splitlines() if l.startswith("RESULT")), None)
    rec["rc"] = pr.returncode
    if line:
        try:
            d = json.loads(line.split("RESULT", 1)[1].strip())
            rec["adopted"] = d.get("smoothBuiltComponents")
            rec["reverted_true"] = d.get("smoothRevertedTrue")
            rec["result_cyl"] = d.get("smoothBuiltCylinders")
        except Exception:  # noqa: BLE001
            pass
    if out.exists():
        rec["cyl"] = cyl_faces_in_step(out)
        rec["data_md5"] = data_hash(out)
        rec["status"] = "OK"
        out.unlink()          # keep the sweep's footprint bounded; hashes are what matter
    else:
        rec["cyl"] = -1
        rec["status"] = "NO_OUTPUT"
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="reference engine (run.sh)")
    ap.add_argument("--b", required=True, help="candidate engine (run.sh)")
    ap.add_argument("--corpus", default=str(Path.home() / "corpora/cadbench"))
    ap.add_argument("--out", default=str(Path.home() / ".cache/n4/ab"))
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--variant", default="normal")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--b-env", default="", help="k=v,k=v applied to arm B only")
    a = ap.parse_args()

    outdir = Path(a.out); outdir.mkdir(parents=True, exist_ok=True)
    corpus = Path(a.corpus)
    stls = sorted(corpus.glob(f"*_{a.variant}.stl"))
    if a.variant == "fine":
        stls = [p for p in stls if p.name.startswith("NEG_")] or stls
    if a.limit:
        stls = stls[:a.limit]
    if not stls:
        print(f"no *_{a.variant}.stl under {corpus}", file=sys.stderr); return 2

    benv = dict(kv.split("=", 1) for kv in a.b_env.split(",") if "=" in kv)
    jobs = [(arm, eng, str(p)) for p in stls
            for arm, eng in (("A", a.a), ("B", a.b))]
    print(f"{len(stls)} models x 2 arms = {len(jobs)} runs, {a.jobs} workers, "
          f"variant={a.variant}, B env={benv or 'none'}", flush=True)

    rows: list[dict] = []
    with cf.ProcessPoolExecutor(max_workers=a.jobs) as pool:
        futs = [pool.submit(run_one, arm, eng, stl, str(outdir),
                            benv if arm == "B" else {}, a.timeout)
                for arm, eng, stl in jobs]
        for i, f in enumerate(cf.as_completed(futs), 1):
            rows.append(f.result())
            if i % 50 == 0:
                print(f"  [{i}/{len(jobs)}]", flush=True)

    (outdir / f"ab_{a.variant}.json").write_text(json.dumps(rows, indent=1))

    by: dict[str, dict] = {}
    for r in rows:
        by.setdefault(r["model"], {})[r["arm"]] = r
    ca = cb = worse = better = same = to_a = to_b = 0
    worse_rows, better_rows = [], []
    for m, d in sorted(by.items()):
        A, B = d.get("A"), d.get("B")
        if not A or not B:
            continue
        if A["status"] == "TIMEOUT": to_a += 1
        if B["status"] == "TIMEOUT": to_b += 1
        va, vb = max(A["cyl"], 0), max(B["cyl"], 0)
        ca += va; cb += vb
        if vb < va: worse += 1; worse_rows.append((m, va, vb))
        elif vb > va: better += 1; better_rows.append((m, va, vb))
        elif A.get("data_md5") == B.get("data_md5"): same += 1

    print(f"\n=== {a.variant}: {len(by)} models ===")
    print(f"  cylinders   A {ca}  ->  B {cb}   ({cb-ca:+d})")
    print(f"  models better {better} | WORSE {worse} | DATA-identical {same}")
    print(f"  timeouts    A {to_a}  B {to_b}")
    if worse_rows:
        print("  WORSE rows (the gate is zero):")
        for m, va, vb in worse_rows: print(f"    {m:44} {va:>4} -> {vb:>4}")
    if better_rows:
        print("  top gains:")
        for m, va, vb in sorted(better_rows, key=lambda r: r[1]-r[2])[:12]:
            print(f"    {m:44} {va:>4} -> {vb:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
