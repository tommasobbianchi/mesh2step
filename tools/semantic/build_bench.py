#!/usr/bin/env python3
"""M2 measurement: compile plans, score against reference trees."""
import json
import multiprocessing
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/semantic"))
sys.path.insert(0, str(ROOT / "tools/tree"))

import numpy as np
import trimesh

import compile_plan
import analyse
import tree as T
import truth
import plan_bench


def _score(tree, mesh):
    tol = max(3e-3 * float(np.linalg.norm(mesh.extents)), 0.05)
    occ = T.occupancy(mesh, mesh.bounds, n=60)
    return analyse.measure(tree, mesh, tol, occ)


def _run_part(part):
    t0 = time.time()
    mesh = trimesh.load(str(Path.home() / "corpora/mechparts" / f"{part}.stl"), force="mesh")

    plan_path = ROOT / "runs/semantic/m2/qwen27b_facts" / f"{part}.json"
    plan = None
    if plan_path.exists():
        with open(plan_path) as f:
            plan = json.load(f).get("plan")
    if plan is None:
        plan = {"base": {}}

    ours_tree = compile_plan.compile_plan(plan, mesh)
    ours_score = _score(ours_tree, mesh)

    ref_score = None
    for g_path in truth.GRADES.glob("*.json"):
        with open(g_path) as f:
            g = json.load(f)
        if g.get("part") == part and g.get("reviewer") == "tommaso" and g.get("overall") == 5:
            with open(g["tree_file"]) as f:
                ref_tree = json.load(f)
            ref_score = _score(ref_tree, mesh)
            break

    return {
        "part": part,
        "ours": ours_score,
        "ref": ref_score,
        "ours_tree": ours_tree,
        "seconds": time.time() - t0,
    }


def _worker(part, q):
    try:
        q.put(_run_part(part))
    except Exception:
        tb_lines = traceback.format_exc().strip().split("\n")
        q.put({"part": part, "error": tb_lines[-1]})


def _default(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="M2 measurement")
    ap.add_argument("out_dir")
    ap.add_argument("parts", nargs="*")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.parts:
        parts = sorted(args.parts, key=int)
    else:
        parts = sorted(plan_bench.truth(), key=int)

    ctx = multiprocessing.get_context("fork")
    results = []

    for part in parts:
        out_file = out_dir / f"{part}.json"
        if out_file.exists():
            print(json.dumps({"part": part, "skipped": True}), flush=True)
            continue

        q = ctx.Queue()
        p = ctx.Process(target=_worker, args=(part, q))
        p.start()
        p.join(timeout=300)
        if p.is_alive():
            p.terminate()
            p.join()
            result = {"part": part, "error": "timeout (300s)"}
        else:
            try:
                result = q.get_nowait()
            except Exception:
                result = {"part": part, "error": "no result from worker"}

        out_file.write_text(json.dumps(result, indent=2, default=_default))
        results.append(result)
        print(json.dumps(result, default=_default), flush=True)

    ok = [r for r in results if "error" not in r]
    errs = [r for r in results if "error" in r]

    def _mean(key, side):
        vals = [r[side][key] for r in ok if r.get(side) and key in r[side]]
        return sum(vals) / len(vals) if vals else None

    summary = {
        "parts": len(parts),
        "errors": len(errs),
        "mean_iou_ours": _mean("iou", "ours"),
        "mean_iou_ref": _mean("iou", "ref"),
        "mean_explained_ours": _mean("explained", "ours"),
        "mean_explained_ref": _mean("explained", "ref"),
        "mean_extra_ours": _mean("extra", "ours"),
        "mean_extra_ref": _mean("extra", "ref"),
        "ours_iou_ge_095": sum(1 for r in ok if r.get("ours") and r["ours"].get("iou", 0) >= 0.95),
        "ours_score_ge_ref_minus_001": sum(
            1 for r in ok
            if r.get("ours") and r.get("ref")
            and r["ours"].get("iou", 0) >= r["ref"].get("iou", 0) - 0.01
        ),
    }
    print("SUMMARY " + json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
