"""The baseline the engine must beat: per part, the best merit (score - 0.001 * steps) any earlier approach
reached, with its source. Sources: analyse v5/v6 (steps counted from the saved tree when the log lacks them),
the rule-based reverse search (runs/tree/reverse/v2), CADFit raw and finished (runs/tree/cadfit).

usage: baseline.py [out.json]   (default runs/tree/reverse/baseline.json, the file compare.py reads)
"""
import glob
import json
import os
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[2] / "runs" / "tree"
best = {}


def offer(n, src, score, steps):
    if score is None or steps is None:
        return
    m = round(score - 0.001 * steps, 4)
    if n not in best or m > best[n][4]:
        best[n] = (src, "", round(score, 4), int(steps), m)


for v in ("v5", "v6"):
    for f in glob.glob(str(R / f"corpus/{v}/out/*.log")):
        n = os.path.basename(f)[:-4]
        t = R / f"corpus/{v}/out/{n}/tree.json"
        for line in open(f):
            if line.startswith('{"tol"'):
                d = json.loads(line)
                r = d.get(d.get("chosen")) or {}
                st = r.get("steps") or (len(json.load(open(t))["features"]) if t.exists() else None)
                offer(n, f"analyse {v}", r.get("score"), st)
for f in glob.glob(str(R / "reverse/v2/*.log")):
    n = os.path.basename(f)[:-4]
    for line in open(f):
        if line.startswith('{"grid"'):
            d = json.loads(line)
            offer(n, "reverse search", d.get("score"), d.get("steps"))
for f in glob.glob(str(R / "cadfit/*.json")):
    b = os.path.basename(f)
    n = b.split(".")[0]
    if not n.isdigit() or b.endswith(".tree.json"):
        continue
    d = json.load(open(f))
    if b.endswith(".finished.json"):
        offer(n, "CADFit + finishing", d.get("score"), d.get("steps"))
    else:
        tr = d.get("tree") or {}
        offer(n, "CADFit", tr.get("score"), tr.get("steps"))

out = Path(sys.argv[1]) if len(sys.argv) > 1 else R / "reverse" / "baseline.json"
json.dump(best, open(out, "w"), indent=1)
src = {}
for v in best.values():
    src[v[0]] = src.get(v[0], 0) + 1
print(json.dumps({"parts": len(best), "best_source_counts": src}))
