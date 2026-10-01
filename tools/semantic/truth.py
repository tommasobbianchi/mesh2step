"""Reference answers for the VLM benchmark, from the feature trees the owner graded 5/5 (a designer would model the part
this way): runs/engine/grade_set_v15 on feat/interview-preview.

Per part: turned (a revolve) or extruded, holes (circles in sketches: every circle loop that is not the outline of a
disc-shaped pad), extruded levels (pads), fillets present, chamfers present.

usage: truth.py                    (prints the table; truth() is imported by vlm_bench.py)"""
import glob
import json
from pathlib import Path

import numpy as np

GRADES = Path.home() / "projects/mesh2step/.worktrees/interview/runs/engine/grade_set_v15/grades"


def is_circle_loop(loop):
    """True when the loop is a single circle segment, or a faceted polygon (>=8 line segments)
    whose start points lie on one circle (algebraic least-squares fit, RMS radial residual < 2 % of radius)."""
    if len(loop) == 1 and loop[0]["t"] == "circle":
        return True
    if len(loop) < 8 or any(g["t"] != "line" for g in loop):
        return False
    pts = np.array([g["p"][0] for g in loop], dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    # Algebraic circle fit: x^2 + y^2 = A*x + B*y + C  (A=2a, B=2b, C=r^2-a^2-b^2)
    A_mat = np.column_stack([x, y, np.ones_like(x)])
    b_vec = x**2 + y**2
    sol, _, _, _ = np.linalg.lstsq(A_mat, b_vec, rcond=None)
    a, b = sol[0] / 2.0, sol[1] / 2.0
    r = np.sqrt(sol[2] + a**2 + b**2)
    residuals = np.sqrt((x - a)**2 + (y - b)**2) - r
    rms = np.sqrt(np.mean(residuals**2))
    return rms < 0.02 * r


def loop_centre(loop):
    """Return the centre [x, y] of a circle loop, or None if the loop is not a circle."""
    if len(loop) == 1 and loop[0]["t"] == "circle":
        return [float(loop[0]["c"][0]), float(loop[0]["c"][1])]
    if len(loop) < 8 or any(g["t"] != "line" for g in loop):
        return None
    pts = np.array([g["p"][0] for g in loop], dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    A_mat = np.column_stack([x, y, np.ones_like(x)])
    b_vec = x**2 + y**2
    sol, _, _, _ = np.linalg.lstsq(A_mat, b_vec, rcond=None)
    return [float(sol[0] / 2.0), float(sol[1] / 2.0)]


def count_distinct_holes(centres, threshold=0.5):
    """Greedy dedupe: count centres more than `threshold` mm apart as distinct holes."""
    count = 0
    used = []
    for c in centres:
        if all(float(np.linalg.norm(np.array(c) - np.array(u))) > threshold for u in used):
            count += 1
            used.append(c)
    return count


def facts(tree):
    feats = tree["features"]
    centres = []
    for f in feats:
        if f["op"] not in ("pad", "pocket") or not isinstance(f.get("loops"), list):
            continue
        for i, loop in enumerate(f["loops"]):
            # a pad's outline (loop 0) that is a circle is a disc or boss, not a hole; a pocket's circle is a hole
            if is_circle_loop(loop) and (i > 0 or f["op"] == "pocket"):
                c = loop_centre(loop)
                if c is not None:
                    centres.append(c)
    holes = count_distinct_holes(centres)
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
