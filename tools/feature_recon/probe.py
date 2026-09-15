"""Adaptive probing around edgebuild.py: same command line, same RESULT / FAIL output, so the webapp calls it in place.

The default build runs first. If it misses the webapp's acceptance check (one valid closed solid, no free edges, volume
within 1 %, p95 surface distance within 0.005 of the diagonal), variants picked by the failure class run in parallel
and the first that passes is served. Tightening / construction variants go first; loosening rungs (corner residual,
sewing tolerance) only after them (user decision 2026-09-15). The acceptance check itself never changes. Every probe
appends one JSON line to EB_PROBE_LOG so the variants that keep winning can become the defaults.
"""
import ast
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

EB = Path(__file__).with_name("edgebuild.py")
MAX_DV_PCT, MAX_P95_REL = 1.0, 0.005          # the webapp gate (server.py EDGE_MAX_DV_PCT / EDGE_MAX_P95_REL)
JOBS = int(os.environ.get("EB_PROBE_JOBS", "4"))
BUDGET = float(os.environ.get("EB_PROBE_BUDGET", "840"))
LOG = Path(os.environ.get("EB_PROBE_LOG", str(Path.home() / ".local/share/mesh2step/probe_log.jsonl")))
LOOSENING_KEYS = {"EB_CORNER_TOL", "EB_SEW_TOL", "EB_ABSORB_AREA"}

# per failure class: (tightening / construction variants, loosening variants)
LADDERS = {
    "open": ([{"EB_WELD": "1e-5"}, {"EB_WELD": "1e-6"}], []),
    # mechparts/20: a cylinder merged with its tangent round is split back (SPLIT_MIXED), refits may not get worse
    # (REFIT_GUARD), and a round's side edge along one torus iso line is that exact circle (ISO_SNAP)
    "corners": ([{"EB_RIM_CYL": "1"},
                 {"EB_REFIT_GUARD": "1", "EB_CURVED_UNLABEL": "1", "EB_SPLIT_MIXED": "1", "EB_ISO_SNAP": "1"},
                 {"EB_STRIP_SPLIT": "1"}, {"EB_CURVED_UNLABEL": "1"}, {"EB_RCOND": "1e-3"}, {"EB_CYL_CYL": "0"},
                 {"EB_CONE_PLANE": "1"}, {"EB_CYL_CYL": "0", "EB_RCOND": "1e-3"}],
                [{"EB_CORNER_TOL": "1e-5"}, {"EB_CORNER_TOL": "1e-4"}]),
    "chain": ([{"EB_CYL_CYL": "0"}, {"EB_RCOND": "1e-3"}, {"EB_NO_PLANE_SPLIT": "1"}], [{"EB_CORNER_TOL": "1e-5"}]),
    "unlabelled": ([{"EB_SPLIT_UNLABELLED": "1"}, {"EB_PLANE_RELABEL": "1"}, {"EB_NO_MIXED": "1"}, {"EB_UNION_MIXED": "1"},
                    {"EB_KINDS4": "1"}],
                   [{"EB_ABSORB_AREA": "0.05"}, {"EB_ABSORB_AREA": "0.05", "EB_CORNER_TOL": "1e-5"}]),
    "unsound": ([{"EB_NO_CYL_BAND": "1"}, {"EB_CYL_CYL": "0"}, {"EB_NO_PLANE_SPLIT": "1"}, {"EB_WELD": "1e-5"}],
                [{"EB_SEW_TOL": "5e-5"}, {"EB_SEW_TOL": "2e-4"}]),
}


def classify(rc, stdout):
    """(class, metrics or None) of one build's output."""
    res = next((ln for ln in reversed(stdout.splitlines()) if ln.startswith("RESULT ")), None)
    if res is not None:
        m = ast.literal_eval(res[7:].split(" radii ")[0])
        ok = (m["valid"] and m["solids"] == 1 and m["free_edges"] == 0 and abs(m["dv_pct"]) <= MAX_DV_PCT
              and m["dist_p95"] <= MAX_P95_REL * m["diag"])
        return ("pass" if ok else "unsound"), m
    fail = next((ln for ln in reversed(stdout.splitlines()) if ln.startswith("FAIL ")), "")
    if rc is None:
        return "timeout", None
    for key, cls in (("open or non-manifold", "open"), ("corners where", "corners"), ("do not meet there", "chain"),
                     ("lie on no fitted surface", "unlabelled"), ("free edges after sewing", "unsound")):
        if key in fail:
            return cls, None
    return "unsound", None


def build(src, out, env_extra, deadline):
    """(rc or None on timeout, stdout, seconds) of one edgebuild run that must end by `deadline` (epoch seconds)."""
    t0 = time.time()
    timeout = deadline - t0
    if timeout < 1.0:
        return None, "", 0.0           # queued past the deadline: never started
    try:
        p = subprocess.run([sys.executable, str(EB), str(src), str(out)], env=dict(os.environ, EB_FAST_FAIL="1", **env_extra),
                           capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, time.time() - t0
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), time.time() - t0


def main():
    if "--combine" in sys.argv or os.environ.get("EB_COUNT_BODIES"):
        os.execv(sys.executable, [sys.executable, str(EB), *sys.argv[1:]])      # nothing to probe
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    deadline = time.time() + BUDGET
    rc, stdout, sec = build(src, out, {}, deadline)
    cls, m = classify(rc, stdout)
    record = {"mesh": str(src), "body": os.environ.get("EB_BODY"), "default": cls, "tried": [], "winner": None}
    if cls == "pass" or cls not in LADDERS:
        record["winner"] = {} if cls == "pass" else None
        _log(record)
        sys.stdout.write(stdout)
        sys.exit(rc if rc is not None else 3)
    winner = None
    tried_envs = set()
    # (class to fix, settings kept from an earlier rung): a rung that turns one failure into ANOTHER class has fixed
    # its own problem (mechparts/31: absorbing leftovers turns "unlabelled" into "corners"), so its settings stay on
    # and the new class's ladder runs on top of them, up to EB_PROBE_DEPTH levels
    frontier = [(cls, {})]
    for _depth in range(int(os.environ.get("EB_PROBE_DEPTH", "2"))):
        nxt = []
        for cls_f, base in frontier:
            tight, loose = LADDERS.get(cls_f, ([], []))
            for stage in (tight, loose):
                stage = [dict(base, **v) for v in stage]
                stage = [v for v in stage if json.dumps(v, sort_keys=True) not in tried_envs]
                if winner or not stage or time.time() >= deadline:
                    continue
                tried_envs.update(json.dumps(v, sort_keys=True) for v in stage)
                with ThreadPoolExecutor(max_workers=JOBS) as pool:
                    futs = {pool.submit(build, src, out.with_name(f"{out.stem}.probe{i}{out.suffix}"), v, deadline): (i, v)
                            for i, v in enumerate(stage, start=len(record["tried"]))}
                    for fut in as_completed(futs):
                        if fut.cancelled():
                            continue            # queued behind a winner, never started
                        i, v = futs[fut]; rc_v, out_v, sec_v = fut.result(); cls_v, m_v = classify(rc_v, out_v)
                        short_ = ({k: m_v[k] for k in ("valid", "solids", "free_edges", "dv_pct", "dist_p95", "cylinders")}
                                  if m_v else None)
                        record["tried"].append({"env": v, "class": cls_v, "sec": round(sec_v, 1), "metrics": short_})
                        print(f"PROBE {json.dumps(v)} -> {cls_v} ({sec_v:.0f} s){' ' + json.dumps(short_) if short_ else ''}",
                              flush=True)
                        if cls_v == "pass" and winner is None:
                            winner = (i, v, rc_v, out_v)
                            for f_ in futs:
                                f_.cancel()     # the server kills the probe at its deadline: a winner must not wait on the queue
                        elif cls_v != cls_f and cls_v in LADDERS:
                            nxt.append((cls_v, v))
        # build on the least-loosened bases only: on mechparts/31 the absorb-leftovers base spent 12 variants that the
        # exact chamfer split (no loosening) had already made pointless
        n_loose = lambda v: sum(1 for k in v if k in LOOSENING_KEYS)  # noqa: E731
        if nxt:
            fewest = min(n_loose(v) for _, v in nxt)
            nxt = [(c, v) for c, v in nxt if n_loose(v) == fewest]
        frontier = nxt
        if winner or not frontier:
            break
    for i in range(len(record["tried"])):
        cand = out.with_name(f"{out.stem}.probe{i}{out.suffix}")
        if winner and i == winner[0] and cand.exists():
            cand.replace(out)
        else:
            cand.unlink(missing_ok=True)
    if winner:
        record["winner"] = winner[1]; _log(record)
        print(f"PROBE WINNER {json.dumps(winner[1])} after default {cls}", flush=True)
        sys.stdout.write(winner[3])
        sys.exit(winner[2])
    _log(record)
    print(f"PROBE no variant passed (default {cls})", flush=True)
    sys.stdout.write(stdout)
    sys.exit(rc if rc is not None else 3)


def _log(record):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    main()
