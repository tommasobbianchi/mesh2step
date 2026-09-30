"""Reference answers for the VLM benchmark, from the feature trees the owner graded 5/5 (a designer would model the part
this way): runs/engine/grade_set_v15 on feat/interview-preview.

Per part: turned (a revolve) or extruded, holes (circles in sketches: every circle loop that is not the outline of a
disc-shaped pad), extruded levels (pads), fillets present, chamfers present.

usage: truth.py                    (prints the table; truth() is imported by vlm_bench.py)"""
import glob
import json
from pathlib import Path

GRADES = Path.home() / "projects/mesh2step/.worktrees/interview/runs/engine/grade_set_v15/grades"


def facts(tree):
    feats = tree["features"]
    holes = 0
    for f in feats:
        if f["op"] not in ("pad", "pocket") or not isinstance(f.get("loops"), list):
            continue
        for i, loop in enumerate(f["loops"]):
            circle = len(loop) == 1 and loop[0]["t"] == "circle"
            # a pad's outline (loop 0) that is a circle is a disc or boss, not a hole; a pocket's circle is a hole
            if circle and (i > 0 or f["op"] == "pocket"):
                holes += 1
    # rounded corners drawn IN a sketch (arcs of an outline or a pocket), as opposed to fillet OPERATIONS on edges: a
    # designer draws a sprocket's scallops or a pocket's corners as arcs (parts 4, 14), and the VLM sees both as round
    arcs = any(g["t"] == "arc" for f in feats if f["op"] in ("pad", "pocket") and isinstance(f.get("loops"), list)
               for loop in f["loops"] for g in loop)
    return {"turned": any("revolve" in f for f in feats), "sketch_arcs": arcs,
            "holes": holes,
            "levels": sum(1 for f in feats if f["op"] == "pad"),
            "fillets": any(f["op"] == "round" for f in feats),
            "chamfers": any(f["op"] == "chamfer" for f in feats)}


def truth():
    out = {}
    for g in glob.glob(str(GRADES / "*.json")):
        d = json.load(open(g))
        if d.get("reviewer") == "tommaso" and d.get("overall") == 5 and Path(d["tree_file"]).exists():
            out[d["part"]] = facts(json.load(open(d["tree_file"])))
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


if __name__ == "__main__":
    for k, v in truth().items():
        print(k, v)
