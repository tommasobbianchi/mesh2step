"""Mesh -> best feature tree: the free single-extrusion proposal first; the cheap planner only when that does not
explain the part (< 97 %). The better tree by volume IoU + surface match wins. Run it in its own process with a
memory cap (the server does): OCCT on a bad sketch can take tens of GB.
usage: analyse.py <mesh> <out_dir>      writes out_dir/tree.json and out_dir/analysis.json
"""
import os

# one thread per process, set before numpy loads: the analysis forks workers (OCCT shapes
# cannot be pickled), and a fork taken while BLAS/OpenMP threads exist deadlocked the gate's
# residual pool (19 threads, workers stuck on a futex)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import json  # noqa: E402
import multiprocessing as mp  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import plan as PL                                      # noqa: E402
import propose as PR                                   # noqa: E402
import tree as T                                       # noqa: E402

GOOD = 0.97
# from the start: past it the planner is dropped and the proposal stands, so an upload is
# answered in time whatever the part (SV08 shroud: planner 6 min, and hopeless)
PLANNER_DEADLINE_S = 240
THREE_PLANES_GRACE_S = 3                              # the three-plane candidate's wait past the other paths
THREE_PLANES_EARLY_S = 260                            # ... or until this, from the body's start, when they end sooner
THREE_PLANES_EARLY_SMALL_S = 30                       # ... for a small body (proposal only)
STEP_COST = 0.001                                      # score a step must earn: the owner graded 20-50-step trees 1-3
                                                       # where 2-5 steps (extrude + round) matched within 0.02


def merit(r):
    """A candidate's score less STEP_COST per step: fewest steps wins among near-equal matches."""
    return r.get("score", -1) - STEP_COST * r.get("steps", 0)


def measure(tree, m, tol, occ):
    s, notes = T.compile_tree(tree, tol)
    if s is None:
        return {"score": -1.0}
    d = T.deviation(m, s, tol)
    iou = T.volume_iou(m, s, tol, occ)
    return {"score": round(iou + 0.5 * (d["explained"] - d["extra"]), 4), "steps": len(tree["features"]), "iou": round(iou, 4),
            "explained": round(d["explained"], 4), "extra": round(d["extra"], 4), "notes": notes}


def _three_planes_child(emit, m, tol):
    """The three-plane reconstruction, emitted raw then finished (no ct_scan: it has every view already). Its first
    view from slab projections and from mid-slab sections, the better kept: a slope another view trims vs a round
    along a curved edge none can (parts 3 and 4 want opposite ones)."""
    os.nice(10)                                        # spare CPU only: it slowed the gate's planner path 50 s
    np.random.seed(2)
    occ = T.occupancy(m, m.bounds, n=60)
    best, raw = None, []
    for mid in (False, True):
        t = PR.three_planes(m, tol, mid=mid)
        r = measure(t, m, tol, occ)
        raw.append((merit(r), mid, t))
        if best is None or merit(r) > merit(best[1]):
            best = (t, dict(r, mid=mid, finished=False))
            emit(best)
    # both finished, projections first: finishing decides, not the raw match (part 10: the mid-section outline won
    # raw, and its holes take no chamfer; the projection one finished to 3 steps). Edge finishes and pruning first:
    # they take a three-plane tree from ~25 steps to ~3, which makes every later pass cheap, and are emitted at
    # once (parts 7 and 10 ran out of the 260 s window finishing in the other order)
    for _, mid, t in sorted(raw, key=lambda x: x[1]):
        for stage in (lambda: (PR.edge_mods(t, m, tol), PR.prune(t, m, tol)), lambda: PR.finish(t, m, tol, scan=False)):
            stage()
            r = measure(t, m, tol, occ)
            if merit(r) > merit(best[1]):
                best = (json.loads(json.dumps(t)), dict(r, mid=mid, finished=True))
                emit(best)


def _search_child(emit, m, tol):
    """The fewest-steps design search (search.py, docs/DESIGN-SEARCH.md): raw design emitted, then finished."""
    import search as SE
    os.nice(10)
    np.random.seed(3)
    occ = T.occupancy(m, m.bounds, n=60)
    t, si = SE.run(m, tol, finish=False)
    best = (t, dict(measure(t, m, tol, occ), finished=False, search=si))
    emit(best)
    t = json.loads(json.dumps(t))
    PR.edge_mods(t, m, tol)
    PR.prune(t, m, tol)
    r = measure(t, m, tol, occ)
    if merit(r) > merit(best[1]):
        emit((t, dict(r, finished=True, search=si)))


def _planner_child(stl, out, q):
    import resource
    os.setpgrp()                                       # its own group: a deadline kill reaches its workers too
    # its own memory ceiling (workers inherit it): an OCCT blowup here (7.8 GB seen) raises
    # inside the child and drops the planner, instead of taking the capped analysis down
    resource.setrlimit(resource.RLIMIT_AS, (5 << 30, 5 << 30))
    np.random.seed(1)
    try:
        t2, _, _, pi = PL.plan_tree(stl, out)
        info = {"cost": pi["cost"], "skipped": pi["skipped"], "hopeless": pi.get("hopeless")}
        q.put((t2, info, None))
    except Exception as e:                             # noqa: BLE001
        q.put((None, None, f"{type(e).__name__}: {e}"[:300]))


def _start_planner(stl, out):
    """The planner in a forked child: it inherits the loaded modules; results come back by queue."""
    ctx = mp.get_context("fork")
    q = ctx.Queue()
    child = ctx.Process(target=_planner_child, args=(stl, str(out), q))
    child.start()
    return q, child


def analyse_one(stl, out, t0, planner=True):
    """One closed body's mesh -> (tree, info): the free proposal, the planner when useful
    (forked early for a layer stack), the better tree kept. ANALYSE_NO_PLANNER=1: free path only."""
    full = planner                                     # a body worth the full analysis (bodies(): >= 1 % of volume)
    planner = planner and not os.environ.get("ANALYSE_NO_PLANNER")
    tb = time.time()                                   # this body's start: t0 is the whole mesh's
    m = trimesh.load(stl, force="mesh")
    tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)
    tree = {"units": "mm", "features": PR.main_extrusion(m, stl)}
    PR._ids(tree)
    # a stack of thin layers traces the shape but is no designer's history: the planner runs too.
    # Known right after the extrusion pass, so it starts now, forked, while the proposal finishes
    layered = sum(f["op"] == "pad" and f.get("label", "").startswith("Level") for f in tree["features"]) > 3
    q, child = None, None
    if layered and planner:
        q, child = _start_planner(stl, out)
    # the part sketched on three planes and intersected (PR.three_planes), built and finished in a forked child
    # while the proposal finishes here: an OCCT crash or runaway there only drops the candidate
    # raw and finished side by side: the finishing passes on a 90-feature tree took 730 s (part 6) where the raw
    # build already matched 98.8 %; the finished one is taken only if it lands in time
    h3 = PR._fork_stream(_three_planes_child, m, tol)
    # opt-in until it pays its way: forked beside the others it cost the gate 77 s of wall (317 s vs 240)
    hs = PR._fork_stream(_search_child, m, tol) if full and os.environ.get("ANALYSE_SEARCH") else None
    PR.finish(tree, m, tol)
    occ = T.occupancy(m, m.bounds, n=60)
    info = {"tol": tol, "proposal": measure(tree, m, tol, occ), "planner": None, "chosen": "proposal",
            "cost_usd": 0.0, "layered": layered}
    if child is None and planner and info["proposal"].get("explained", 0) < GOOD:
        q, child = _start_planner(stl, out)
    if child is not None:
        import queue
        import signal
        try:                                           # before join: a full pipe blocks the child
            left = max(5.0, PLANNER_DEADLINE_S - (time.time() - t0))
            t2, pi, err = q.get(timeout=left)
        except queue.Empty:
            os.killpg(child.pid, signal.SIGKILL)
            t2, pi, err = None, None, f"no answer within {PLANNER_DEADLINE_S} s: dropped"
        child.join()
        if err:
            info["planner"] = {"error": err}
        else:
            info["cost_usd"] = pi["cost"]
            if pi.get("hopeless") is not None:         # its bodies cannot win: not measured
                info["planner"] = {"hopeless": pi["hopeless"], "skipped": pi["skipped"]}
            elif t2:
                info["planner"] = dict(measure(t2, m, tol, occ), skipped=pi["skipped"])
                # the history matters more than the last points of match: a planner tree that holds the volume
                # (IoU >= 0.9) replaces a layer stack even when the stack traces the surface closer
                better = merit(info["planner"]) > merit(info["proposal"])
                if better or (layered and info["planner"].get("iou", 0) >= 0.9):
                    tree, info["chosen"] = t2, "planner"
    # waited for only a short grace past the proposal and planner paths: it must not extend the wall (the gate
    # waited 300 s for it, 307 s against a 220 s budget); a part done early gives it until THREE_PLANES_EARLY_S
    early = THREE_PLANES_EARLY_S if full else THREE_PLANES_EARLY_SMALL_S   # per body: the gate's small bodies
    grace = max(THREE_PLANES_GRACE_S, early - (time.time() - tb))           # each waited to 200 s from t0
    r3 = PR._fork_latest(h3, time.time() + grace)
    print(f"[analyse] three-plane at {time.time() - tb:.0f} s: "
          f"{'finished' if r3 and r3[1].get('finished') else 'raw' if r3 else 'not ready'}", file=sys.stderr, flush=True)
    info["three_planes"] = r3[1] if r3 else {"error": "crashed or not ready in time"}
    held = info["planner"] if info["chosen"] == "planner" else info["proposal"]
    if r3 and merit(r3[1]) > merit(held):
        tree, info["chosen"] = r3[0], "three_planes"
        held = r3[1]
    if hs is not None:                                 # same window as the three-plane candidate
        rs = PR._fork_latest(hs, time.time() + max(THREE_PLANES_GRACE_S, early - (time.time() - tb)))
        info["search"] = rs[1] if rs else {"error": "crashed or not ready in time"}
        if rs and merit(rs[1]) > merit(held):
            tree, info["chosen"], held = rs[0], "search", rs[1]
    if full and os.environ.get("ANALYSE_COMBINE"):
        # the combiner (docs/DESIGN-SEARCH.md): every approach's steps pooled with the search's own, the fewest-steps
        # design that holds kept. Opt-in: 200-700 s per part today, past the gate's budget until finishing is fast
        import search as SE
        seeds = [tree] + ([r3[0]] if r3 else [])
        tc, ci = SE.portfolio(m, tol, seeds=seeds, budget=float(os.environ.get("ANALYSE_COMBINE_S", "240")))
        rc = measure(tc, m, tol, occ)
        info["combined"] = dict(rc, strategies=ci["strategies"], seconds=ci["seconds"])
        if merit(rc) > merit(held):
            tree, info["chosen"] = tc, "combined"
    return tree, info


def bodies(m):
    """The mesh's closed bodies worth a tree: (mesh, full analysis?). A print-in-place part is
    several closed bodies (broom holder: 3, 0.34 mm apart); zero-volume shards are debris (the
    gate has 298)."""
    parts = [p for p in m.split(only_watertight=False) if p.is_watertight and abs(p.volume) > 0]
    total = sum(abs(p.volume) for p in parts) or 1.0
    keep = [p for p in parts if abs(p.volume) >= 1e-4 * total]
    keep.sort(key=lambda p: -abs(p.volume))
    return [(p, bool(abs(p.volume) >= 0.01 * total)) for p in keep]   # small: free proposal only


def main(stl, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    np.random.seed(0)                                  # surface sampling is random: same mesh, same decisions
    t0 = time.time()
    m = trimesh.load(stl, force="mesh")
    bs = bodies(m)
    if len(bs) <= 1:
        tree, info = analyse_one(stl, out, t0)
    else:                                              # one tree per body, tagged, ids renumbered
        feats, infos, n = [], [], 0
        for i, (b, full) in enumerate(bs):
            bstl = out / f"body{i + 1}.stl"
            b.export(bstl)
            t, inf = analyse_one(str(bstl), out / f"body{i + 1}", t0, planner=full)
            ren = {}
            for f in t["features"]:
                n += 1
                ren[f["id"]] = f"F{n}"
            for f in t["features"]:
                g = dict(f, id=ren[f["id"]], body=f"B{i + 1}")
                if "on" in g:
                    g["on"] = ren.get(g["on"], g["on"])
                feats.append(g)
            infos.append(dict(inf, body=f"B{i + 1}", volume=round(abs(b.volume), 2), full=full))
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
            print(f"[analyse] body {i + 1}/{len(bs)} done at {time.time() - t0:.0f} s, "
                  f"peak rss {rss} MB", file=sys.stderr, flush=True)
        tree = {"units": "mm", "features": feats}
        tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)
        occ = T.occupancy(m, m.bounds, n=60)
        whole = measure(tree, m, tol, occ)             # the merged tree against the whole mesh
        info = {"tol": tol, "bodies": infos, "proposal": whole, "planner": None,
                "chosen": "+".join(x["chosen"] for x in infos),
                "cost_usd": round(sum(x["cost_usd"] for x in infos), 4)}
    info["seconds"] = round(time.time() - t0, 1)
    (out / "tree.json").write_text(json.dumps(tree, indent=1))
    (out / "analysis.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
