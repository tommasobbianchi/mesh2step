"""Does J_fast rank trees like the exact J? Every saved corpus tree with its exact measure (v5, v6 analyse runs;
reverse runs), J_fast computed, Spearman correlation overall and pairwise agreement within each part."""
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jfast as JF                                     # noqa: E402

R = Path(__file__).resolve().parents[2] / "runs" / "tree"


def exact_from_log(log):
    for line in open(log):
        if line.startswith('{"tol"'):
            d = json.loads(line)
            r = d.get(d.get("chosen")) or {}
            return r if "score" in r else None
        if line.startswith('{"grid"'):
            d = json.loads(line)
            return {"score": d["score"], "iou": None} if "score" in d else None
    return None


samples = {}
for v in ("v5", "v6"):
    for log in glob.glob(str(R / f"corpus/{v}/out/*.log")):
        n = os.path.basename(log)[:-4]
        t = R / f"corpus/{v}/out/{n}/tree.json"
        ex = exact_from_log(log)
        if ex and t.exists():
            samples.setdefault(n, []).append((v, t, ex))
for log in glob.glob(str(R / "reverse/v2/*.log")):
    n = os.path.basename(log)[:-4]
    t = R / f"reverse/v2/{n}.json"
    ex = exact_from_log(log)
    if ex and t.exists():
        samples.setdefault(n, []).append(("rev", t, ex))

xs, ys, agree, pairs = [], [], 0, 0
for n in sorted(samples, key=int):
    m = trimesh.load(f"/home/tommaso/corpora/mechparts/{n}.stl", force="mesh")
    V, c, h = JF.SE.voxels(m)
    rows = []
    for tag, t, ex in samples[n]:
        tree = json.load(open(t))
        jf = JF.jfast(tree, V, c)
        steps = len(tree["features"])
        jx = ex["score"] - 0.001 * steps
        rows.append((tag, jf["j_fast"], round(jx, 4), jf["iou_fast"], ex.get("iou")))
        xs.append(jf["iou_fast"]); ys.append(ex["score"])
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if abs(rows[i][2] - rows[j][2]) > 0.002:
                pairs += 1
                agree += (rows[i][1] > rows[j][1]) == (rows[i][2] > rows[j][2])
    print(n, rows, flush=True)


def rank(a):
    return np.argsort(np.argsort(a))


rho = np.corrcoef(rank(np.array(xs)), rank(np.array(ys)))[0, 1] if len(xs) > 2 else float("nan")
print(json.dumps({"samples": len(xs), "spearman_iou_fast_vs_exact_score": round(float(rho), 3),
                  "within_part_pairs": pairs, "pair_agreement": round(agree / max(pairs, 1), 3)}))
