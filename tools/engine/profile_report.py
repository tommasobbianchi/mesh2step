"""Aggregate cgprof samples: per stage (from the MARK lines) and per process class, wall s, CPU s, cores used, idle
share of the host's cores, peak memory. -> one JSON document on stdout.

usage: profile_report.py <profile_dir> [cores]
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

CLASSES = [("engine binary (stl2step)", r"stl2step|mesh2step-native|run\.sh"), ("edgebuild probe", r"probe\.py"),
           ("edgebuild build", r"edgebuild\.py"), ("feature: extrude", r"auto2d\.py"), ("feature: stepped", r"auto25g\.py"),
           ("feature: turned envelope", r"autorev\.py"), ("feature: turned cut", r"autorev_cut4\.py"),
           ("feature: block", r"autoblock2\.py"), ("feature controller", r"mesh2step\.feature"),
           ("design-history engine", r"engine/run\.py"), ("FreeCAD", r"freecad|FreeCAD|xvfb|Xvfb"),
           ("converter service (in-process: load, gates, post-passes)", r"convbench\.py"), ("FreeCAD export driver", r"fc_snippet")]


def klass(cmd):
    return next((k for k, rx in CLASSES if re.search(rx, cmd)), "other: " + cmd.split()[0].rsplit("/", 1)[-1] if cmd else "other")


def load(pre):
    S = [json.loads(ln) for ln in open(str(pre) + ".jsonl")]
    marks = defaultdict(dict)
    for ln in open(str(pre) + ".marks"):
        _, name, what, t = ln.split()
        marks[name].setdefault(what, []).append(float(t))
    return S, marks


def window(S, t0, t1, cores):
    """Cgroup CPU and memory between t0 and t1, and CPU per process class (from per-process tick deltas)."""
    W = [s for s in S if t0 - 0.6 <= s["t"] <= t1 + 0.6 and s["cpu_us"] is not None]
    if len(W) < 2:
        return {"wall_s": round(t1 - t0, 1), "cpu_s": 0.0, "cores": 0.0, "idle_pct": 100.0, "peak_mb": 0, "by_process": {}}
    cpu = (W[-1]["cpu_us"] - W[0]["cpu_us"]) / 1e6
    dt = max(W[-1]["t"] - W[0]["t"], 1e-6)
    last, byp = {}, defaultdict(float)
    for s in W:
        for pid, cmd, ticks, _ in s["procs"]:
            if pid in last:
                byp[klass(cmd)] += max(ticks - last[pid], 0.0)
            last[pid] = ticks
    cpu += byp.get("FreeCAD", 0.0)                        # outside the cgroup (snap): counted from its processes
    return {"wall_s": round(t1 - t0, 1), "cpu_s": round(cpu, 1), "cores": round(cpu / dt, 2),
            "idle_pct": round(100 * (1 - cpu / dt / cores), 1), "peak_mb": max(s["mem_mb"] or 0 for s in W),
            "by_process": {k: round(v, 1) for k, v in sorted(byp.items(), key=lambda x: -x[1]) if v >= 0.5}}


def main():
    d, cores = Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 16
    rep = {}
    for pre in sorted({p.with_suffix("") for p in d.glob("*.jsonl")}):
        S, marks = load(pre)
        if not S:
            continue
        part, stage = pre.name.split(".", 1)
        whole = window(S, S[0]["t"], S[-1]["t"], cores)
        sub = {}
        for name, m in marks.items():
            for k, (a, b) in enumerate(zip(m.get("start", []), m.get("end", []))):
                sub[name + (f"#{k + 1}" if len(m.get("start", [])) > 1 else "")] = window(S, a, b, cores)
        rep.setdefault(part, {})[stage] = {"total": whole, "stages": sub}
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
