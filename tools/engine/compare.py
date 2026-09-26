"""Corpus acceptance (docs/ENGINE.md section 6): engine results vs the baseline (best of v5/v6), per part and in
aggregate: wins/losses on J, mean J, steps, seconds.

usage: compare.py <engine_out_dir> [baseline.json]
"""
import json
import sys
from pathlib import Path

d = Path(sys.argv[1])
base = json.load(open(sys.argv[2] if len(sys.argv) > 2 else
                      Path(__file__).resolve().parents[2] / "runs/tree/reverse/baseline.json"))
rows = []
for n in range(1, 40):
    log = d / f"{n}.log"
    b = base.get(str(n))
    e = None
    if log.exists():
        for line in open(log):
            if line.startswith("{"):
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    pass
    rows.append((n, e, b))
w = l = t = 0
js, jb = [], []
for n, e, b in rows:
    if not e or "merit" not in e:
        print(f"{n:>2} engine: {'pending' if e is None else 'no program'}   baseline J {b[4] if b else '-'}")
        continue
    bj = b[4] if b else None
    tag = "-" if bj is None else ("WIN" if e["merit"] > bj + 1e-4 else "loss" if e["merit"] < bj - 1e-4 else "tie")
    w, l, t = w + (tag == "WIN"), l + (tag == "loss"), t + (tag == "tie")
    if bj is not None:
        js.append(e["merit"]); jb.append(bj)
    print(f"{n:>2} engine J {e['merit']:.4f} ({e['steps']} steps, {e['seconds']} s, {e['program']})"
          f"   baseline J {bj} ({b[3] if b else '-'} steps)   {tag}")
if js:
    print(json.dumps({"compared": len(js), "wins": w, "losses": l, "ties": t,
                      "mean_J_engine": round(sum(js) / len(js), 4), "mean_J_baseline": round(sum(jb) / len(jb), 4)}))
