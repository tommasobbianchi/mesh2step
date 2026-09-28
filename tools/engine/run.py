"""The engine, end to end (docs/ENGINE.md), the same for every part:

  evidence solid (production STEP) -> exact undo of the local features the base planes cannot explain
  -> minimal pad/pocket program by cells + ILP, on the solid as served and on the undone base
  -> each with and without the finishing pass (rounds/chamfers)
  -> the program with the best exact J on the mesh.

usage: run.py <part.stl> <part.step> [out_tree.json]
"""
import copy
import json
import os
import sys
import time
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):   # before numpy: forked workers deadlock
    os.environ.setdefault(_v, "1")                                          # on a threaded BLAS

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cells as C                                      # noqa: E402
import evidence as E                                   # noqa: E402
import finish as FN                                    # noqa: E402
import revolve as RV                                   # noqa: E402
import snap as SN                                      # noqa: E402
import mirror as MR                                    # noqa: E402
import solve as S                                      # noqa: E402
import undo as U                                       # noqa: E402

PR = C.PR
FINISH_TOP = 2         # raw programs that get the finishing passes
BUDGET = 2100.0        # seconds for the whole part (the fleet kills at 2400)
BROKEN = 0.03          # exact vs voxel volume of a program: beyond this a boolean failed silently
BIG_PAIRS = 1000       # cap-level pairs (sum over axes) past which hypotheses run serially (corpus max 310, part 14)
FIN_S = 60.0           # wall seconds for all the finishing chains together (the owner's budget)
FIN_SCORE_S = 30.0     # the final score of a finished program (one exact compile)
HYP_SHARE = 0.5        # share of the budget the program hypotheses may take (the rest is finishing's)


def j_exact(tree, m, tol, timeout=90.0):
    sc = PR._forked(PR.pick_score, tree, m, tol, default=-1.0, timeout=timeout)
    return sc - C.STEP_COST * C.steps(tree), sc


def run(m, step, tol, ilp_s=60.0):
    t0 = time.time()
    s = E.read(step)
    b = U.base_kind(s)
    sets = U.unexplained_sets(s, b[3])
    # one call within the budget: one chain at a time (U.undo_chains, Analysis Situs' loop) gave the same bases on
    # 6 parts in twice the time (runs/engine/undo_cmp2.log), so it is kept only as a tool
    rc = RV.candidates(s, m, tol)                      # revolve or not is a hypothesis too (finishes may do it)
    solids = [("as served", s, False, ()), ("as served, sharp outlines", s, True, ())] + \
        ([("as served, revolves", s, False, rc), ("as served, sharp outlines, revolves", s, True, rc)] if rc else [])
    log, best = [], None
    end = t0 + BUDGET

    def gen(sh, sharp, extra, snap):
        """One hypothesis's program and its raw exact J (runs in a fork)."""
        t1 = time.time()
        if sh is s:
            tree, info = C.program(m, tol, ilp_s, sharp=sharp, extra=extra, snap=snap)
        else:
            tree, info = C.program(S.mesh_of(sh, tol / 10), tol, ilp_s, shape=sh, snap=snap)
        info["snapped"] = snap
        info["program_s"] = round(time.time() - t1, 1)
        if tree is None:
            return None, info, None, None
        j, sc = j_exact(tree, m, tol)
        info["broken"] = _broken(tree)               # the silent-empty-fuse symptom (see below)
        return tree, info, j, sc

    def _broken(tree):
        """Exact solid and voxel program disagree on volume by more than BROKEN: a boolean of near-coincident
        walls silently lost material (part 6: exact 177k vs voxels 280k). Only then is the snapped build tried."""
        import jfast as JF
        import tree as T
        try:
            sh, _ = T.compile_tree(tree, tol)
            ve = T.volume(sh) if sh is not None else 0.0
            V, c, h = JF.SE.voxels(m)
            vr = float(JF.rasterize(tree, c).sum()) * h ** 3
            return abs(ve - vr) > BROKEN * max(vr, 1e-9)
        except Exception:                            # noqa: BLE001
            return True

    # finishing (rounds, chamfers) gets FIN_S of wall time in all: the owner, 2026-09-28: "60 seconds is enough, a
    # human fixes a fillet in a few seconds in post-processing" (v15: part 14 spent 964 s here and kept nothing)
    fin = {"end": None}
    left = lambda: max(1.0, fin["end"] - time.time())

    def fin_measured(tree):
        """The measured finishing pass, then the evidence finishes on top (runs in a fork)."""
        ft = copy.deepcopy(tree)
        PR.DEADLINE = fin["end"]                       # every trial in this chain, edge_mods' and prune's included
        PR.edge_mods(ft, m, tol, budget=left())
        PR.prune(ft, m, tol, budget=left())
        bt, _, _ = FN.apply(ft, s, m, tol, lambda t: j_exact(t, m, tol, timeout=left()), until=fin["end"])
        PR.DEADLINE = None                             # the final scores get their own time
        return [("finished", ft, *j_exact(ft, m, tol, timeout=FIN_SCORE_S)),
                ("finished + evidence finishes", bt, *j_exact(bt, m, tol, timeout=FIN_SCORE_S))]

    def fin_evidence(tree):
        PR.DEADLINE = fin["end"]
        et, _, _ = FN.apply(tree, s, m, tol, lambda t: j_exact(t, m, tol, timeout=left()), until=fin["end"])
        PR.DEADLINE = None
        return [("evidence finishes", et, *j_exact(et, m, tol, timeout=FIN_SCORE_S))]

    def note(name, vn, t, info, j, sc):
        nonlocal best
        log.append({"solid": name, "variant": vn, "ops": len(t["features"]), "score": round(sc, 4),
                    "J": round(j, 4), "ilp": info, "t": round(time.time() - t0, 1)})
        # J ties (within 1e-4) go to the program with fewer revolves: a round is one radius on existing edges, a
        # revolve an axis and a whole profile (the longer description; the owner graded pad + round on part 7)
        nrev = sum("revolve" in f for f in t["features"])
        if best is None or j > best[0] + 1e-4 or (abs(j - best[0]) <= 1e-4 and nrev < best[4]):
            best = (j, t, sc, f"{name}, {vn}", nrev)

    # the hypotheses in parallel (independent: same decisions as one after another, a third of the wall time).
    # Sections of the served solid come from the scan itself (watertight; the solid's per-face tessellation cracks
    # and its exact sections can drop edges within its tolerance); the undone base has no scan: its exact sections.
    # "sharp": pads take each band's widest outline, for the finishes to trim (a full round leaves no wall for
    # defeaturing to extend, so the undone base cannot give that outline)
    # every hypothesis built plain and with snapped walls, each in its own process: a snapped build that crashes
    # or overruns loses only itself (v11: it took the plain 'sharp outlines' program of part 11 down with it)
    # plain builds first; a hypothesis whose plain build shows the silent-empty-fuse symptom is rebuilt with snapped
    # walls in its own process (a snapped build that crashes loses only itself)
    # a part far outside the corpus (many distinct cap heights: candidates grow with their square) runs its
    # hypotheses one at a time: a user part with 3055 level pairs (corpus max 310) peaked ~10 GB per hypothesis and
    # four in parallel were OOM-killed at 34 GB (Kimi, 2026-09-27). Below BIG_PAIRS nothing changes
    big = sum(len(lv) * (len(lv) + 1) // 2 for lv in (C.levels_of(m, a, tol) for a in range(3))) > BIG_PAIRS
    start = (lambda *a: ("lazy", a)) if big else (lambda *a: PR._fork_start(gen, *a))

    def collect(h, until, default):
        if isinstance(h, tuple) and h[0] == "lazy":
            h = PR._fork_start(gen, *h[1])
        return PR._fork_collect(h, until, default)

    hs = [(name, sh, sharp, extra, start(sh, sharp, extra, False)) for name, sh, sharp, extra in solids]
    # the undo (up to UNDO_S in its own fork) runs while the served-solid hypotheses compute, not before them
    # (parts 5 and 39 spent ~300 s and ~220 s here with every core but one idle); same bases, same decisions
    base = U.defeature_budgeted(s, [f for x in sets for f in x]) if sets else None
    if base is not None:
        solids.append(("undone base", base, False, ()))
        hs.append(("undone base", base, False, (), start(base, False, (), False)))
    got, redo = {}, []
    end_h = t0 + HYP_SHARE * BUDGET                    # hypotheses get at most this share: finishing always runs
    for name, sh, sharp, extra, h in hs:               # (v13/v14: part 6 spent 1366 s here and never got its fillets)
        tree, info, j, sc = collect(h, end_h, (None, {"error": "died or over budget", "snapped": False}, None, None))
        if tree is None:
            log.append({"solid": name, **info})
            redo.append((name, sh, sharp, extra))
            continue
        got[name] = (tree, info, j, sc)
        if info.get("broken"):
            redo.append((name, sh, sharp, extra))
    hs2 = [(name, start(sh, sharp, extra, True)) for name, sh, sharp, extra in redo]
    for name, h in hs2:
        tree, info, j, sc = collect(h, max(end_h, time.time() + 60), (None, {"error": "died or over budget",
                                                                                     "snapped": True}, None, None))
        if tree is None:
            log.append({"solid": name, **info})
            continue
        if name not in got or j > got[name][2] + 1e-4:      # ties go to the plain build
            got[name] = (tree, info, j, sc)
    raws = []
    for name, (tree, info, j, sc) in got.items():
        note(name, "raw", tree, info, j, sc)
        raws.append((j, name, tree, info))
    # finishing costs most of the time (every trial is an exact compile): the FINISH_TOP best raw programs, their
    # two finishing chains all in parallel
    jobs = []
    rev = lambda t: any("revolve" in f for f in t["features"])
    ranked = sorted(raws, key=lambda r: -r[0])
    pick = [r for r in ranked if not rev(r[2])][:FINISH_TOP] + [r for r in ranked if rev(r[2])][:1]
    fin["end"] = time.time() + FIN_S
    for _, name, tree, info in pick:                   # the best of each family: finishes vs revolves
        jobs += [(name, info, PR._fork_start(fin_measured, tree)), (name, info, PR._fork_start(fin_evidence, tree))]
    for name, info, h in jobs:
        for vn, t, j, sc in PR._fork_collect(h, min(end, fin["end"] + 2 * FIN_SCORE_S), []):
            note(name, vn, t, info, j, sc)
    if best is not None:                               # finishes grounded on the evidence faces, kept if J holds
        gt, nch, nkind = FN.ground(best[1], s, tol)
        if nch:
            j, sc = j_exact(gt, m, tol, timeout=FIN_SCORE_S)
            log.append({"variant": "finishes on evidence", "changed": nch, "kind_fixed": nkind, "J": round(j, 4)})
            # a finish of the wrong kind contradicts the evidence: correcting it is worth up to one step of J
            if j >= best[0] - (C.STEP_COST if nkind else 1e-4):
                best = (j, gt, sc, best[3] + ", finishes on evidence", best[4])
    if best is not None:                               # sketch arcs from the evidence, kept if J holds
        st, nch = SN.snap(best[1], s, tol)
        if nch:
            j, sc = j_exact(st, m, tol)
            log.append({"variant": "evidence arcs", "loops_changed": nch, "J": round(j, 4)})
            if j >= best[0] - 1e-4:
                best = (j, st, sc, best[3] + ", evidence arcs", best[4])
    while best is not None:                            # mirrors found in the program, greedily: J decides which
        top = None                                     # copy stays; a tie goes to the mirror (shorter description)
        for mt, desc in MR.candidates(best[1], tol, m.bounds):
            j, sc = j_exact(mt, m, tol)
            log.append({"variant": "mirror", "what": desc, "J": round(j, 4)})
            if j >= best[0] - 1e-4 and (top is None or j > top[0]):
                top = (j, mt, sc, desc)
        if top is None:
            break
        best = (top[0], top[1], top[2], best[3] + f", {top[3]}", best[4])
    out = {"undo_sets": len(sets), "base_planes": list(b[1]), "log": log, "seconds": round(time.time() - t0, 1)}
    if best is None:
        return None, out
    out.update(program=best[3], score=round(best[2], 4), steps=len(best[1]["features"]),
               weighted_steps=C.steps(best[1]), merit=round(best[0], 4))
    return best[1], out


if __name__ == "__main__":
    m = trimesh.load(sys.argv[1], force="mesh")
    tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)
    tree, info = run(m, sys.argv[2], tol)
    print(json.dumps(info))
    for f in (tree or {}).get("features", []):
        print(f["id"], f["op"], f.get("axis", ""), f.get("at", ""), f.get("length", f.get("size", "")), f["label"])
    if tree is not None and len(sys.argv) > 3:
        json.dump(tree, open(sys.argv[3], "w"), indent=1)
