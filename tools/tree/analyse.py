"""Mesh -> best feature tree: the free single-extrusion proposal first; the cheap planner only when that does not
explain the part (< 97 %). The better tree by volume IoU + surface match wins. Run it in its own process with a
memory cap (the server does): OCCT on a bad sketch can take tens of GB.
usage: analyse.py <mesh> <out_dir>      writes out_dir/tree.json and out_dir/analysis.json
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import plan as PL                                      # noqa: E402
import propose as PR                                   # noqa: E402
import tree as T                                       # noqa: E402

GOOD = 0.97


def measure(tree, m, tol, occ):
    s, notes = T.compile_tree(tree, tol)
    if s is None:
        return {"score": -1.0}
    d = T.deviation(m, s, tol)
    iou = T.volume_iou(m, s, tol, occ)
    return {"score": round(iou + 0.5 * (d["explained"] - d["extra"]), 4), "iou": round(iou, 4),
            "explained": round(d["explained"], 4), "extra": round(d["extra"], 4), "notes": notes}


def main(stl, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    tree, m, tol = PR.propose(stl)
    occ = T.occupancy(m, m.bounds, n=60)
    info = {"tol": tol, "proposal": measure(tree, m, tol, occ), "planner": None, "chosen": "proposal", "cost_usd": 0.0}
    # a stack of many thin layers traces the shape but is no designer's history: ask the planner then too
    layered = sum(f["op"] == "pad" and f.get("label", "").startswith("Level") for f in tree["features"]) > 3
    info["layered"] = layered
    if info["proposal"].get("explained", 0) < GOOD or layered:
        try:
            t2, _, _, pi = PL.plan_tree(stl, str(out))
            info["cost_usd"] = pi["cost"]
            if t2:
                info["planner"] = dict(measure(t2, m, tol, occ), skipped=pi["skipped"])
                # the history matters more than the last points of match: a planner tree that holds the volume
                # (IoU >= 0.9) replaces a layer stack even when the stack traces the surface closer
                if info["planner"]["score"] > info["proposal"]["score"] or (layered and info["planner"].get("iou", 0) >= 0.9):
                    tree, info["chosen"] = t2, "planner"
        except Exception as e:                         # noqa: BLE001 -- the free proposal still stands
            info["planner"] = {"error": f"{type(e).__name__}: {e}"[:300]}
    info["seconds"] = round(time.time() - t0, 1)
    (out / "tree.json").write_text(json.dumps(tree, indent=1))
    (out / "analysis.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
