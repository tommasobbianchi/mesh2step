"""Speed oracle for the analysis (tools/tree/analyse.py): wall time and quality on fixed parts, pass/fail.

The gate (multi-body, planner path) is the target: its recorded planner replies are replayed (PLAN_REPLAY), so
the run is deterministic in structure and costs no model call; the live planner adds ~40 s on top.
Pass = gate analysis under GATE_BUDGET_S AND every part keeps its quality (volume IoU, surface explained) within
the stated floor AND the same path is chosen. Exit 0 on pass, 1 on fail. Prints one JSON line per part + a verdict.
usage: python3 tools/tree/bench.py [--only gate]
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = Path.home() / "corpora" / "tree_bench"
GATE_BUDGET_S = 220                                     # + ~40-60 s live planner: margin under the 300 s goal; 180 -> 220 on 2026-09-25 for the mandatory orthogonal-plane scans (ct_scan, ~20 s on the critical path)
PARTS = {                                               # floors: measured baseline minus a sampling margin
    "gate": {"stl": "gate.stl", "replay": HERE / "bench" / "gate_plans.json", "chosen": "planner",
             "iou": 0.89, "explained": 0.77},
    "clamp": {"stl": "clamp.stl", "chosen": "proposal", "iou": 0.97, "explained": 0.99},
    "m16": {"stl": "m16.stl", "chosen": "proposal", "iou": 0.95, "explained": 0.99},
}


def run(name, p):
    out = Path(tempfile.mkdtemp(prefix=f"bench_{name}_"))
    env = dict(os.environ, PLAN_REPLAY=str(p["replay"])) if p.get("replay") else dict(os.environ)
    t0 = time.time()
    r = subprocess.run([sys.executable, str(HERE / "analyse.py"), str(CORPUS / p["stl"]), str(out)],
                       capture_output=True, text=True, env=env, timeout=3600)
    wall = time.time() - t0
    try:
        a = json.loads((out / "analysis.json").read_text())
    except (OSError, ValueError):
        return {"part": name, "ok": False, "wall_s": round(wall, 1), "error": (r.stderr or "")[-600:]}
    m = a["planner"] if a["chosen"] == "planner" else a["proposal"]
    fails = []
    if a["chosen"] != p["chosen"]:
        fails.append(f"chose {a['chosen']}, expected {p['chosen']}")
    for k in ("iou", "explained"):
        if (m.get(k) or 0) < p[k]:
            fails.append(f"{k} {m.get(k)} < {p[k]}")
    if name == "gate" and wall > GATE_BUDGET_S:
        fails.append(f"wall {wall:.0f} s > {GATE_BUDGET_S} s")
    return {"part": name, "ok": not fails, "wall_s": round(wall, 1), "chosen": a["chosen"],
            "iou": m.get("iou"), "explained": m.get("explained"), "fails": fails}


if __name__ == "__main__":
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    res = [run(n, p) for n, p in PARTS.items() if only in (None, n)]
    for r in res:
        print(json.dumps(r))
    ok = all(r["ok"] for r in res)
    print(json.dumps({"verdict": "PASS" if ok else "FAIL", "total_wall_s": round(sum(r["wall_s"] for r in res), 1)}))
    sys.exit(0 if ok else 1)
