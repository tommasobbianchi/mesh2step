"""S4 compile: turn an S2 plan + deterministic mesh sections into a feature tree."""
import sys
from pathlib import Path

import numpy as np

_TREE_DIR = str(Path(__file__).resolve().parent.parent / "tree")
if _TREE_DIR not in sys.path:
    sys.path.insert(0, _TREE_DIR)

import probes  # noqa: E402
import propose  # noqa: E402

_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


def _shoelace_area(loop):
    """Absolute area of a 2D closed loop via the shoelace formula."""
    x, y = loop[:, 0], loop[:, 1]
    return 0.5 * abs(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def _total_area(loops):
    """Even-odd enclosed area: largest loop is outer, the rest are holes."""
    if not loops:
        return 0.0
    areas = [_shoelace_area(lp) for lp in loops]
    max_i = int(np.argmax(areas))
    return areas[max_i] - sum(a for i, a in enumerate(areas) if i != max_i)


def compile_plan(plan, mesh):
    """Turn an S2 plan plus deterministic mesh sections into a feature tree."""
    # 1. Determine axis
    axis = plan.get("base", {}).get("axis")
    if axis not in ("X", "Y", "Z"):
        b = probes.bbox(mesh)
        axis = ("X", "Y", "Z")[int(np.argmin(b["size"]))]

    idx = _AXIS_INDEX[axis]
    b = probes.bbox(mesh)
    lo = b["min"][idx]
    hi = b["max"][idx]
    extent = hi - lo

    # 2. Take cuts at fractions 0.05, 0.10, ..., 0.95
    fracs = [0.05 * i for i in range(1, 20)]
    cuts = []  # list of (frac, loops)
    for f in fracs:
        loops = probes.section_loops(mesh, axis, f)
        if loops:
            cuts.append((f, loops))

    if not cuts:
        return {"units": "mm", "features": []}

    # 3. Group consecutive cuts into levels (area change > 3 % starts a new level)
    areas = [_total_area(loops) for _, loops in cuts]
    levels = []  # list of (start_idx, end_idx) into cuts
    level_start = 0
    for i in range(1, len(cuts)):
        if abs(areas[i] - areas[level_start]) > 0.03 * areas[level_start]:
            levels.append((level_start, i - 1))
            level_start = i
    levels.append((level_start, len(cuts) - 1))

    # 4. Build one feature per level
    features = []
    for k, (s, e) in enumerate(levels, 1):
        # z0
        if k == 1:
            z0 = lo
        else:
            prev_last_frac = cuts[levels[k - 2][1]][0]
            curr_first_frac = cuts[s][0]
            z0 = lo + (prev_last_frac + curr_first_frac) / 2.0 * extent

        # z1
        if k == len(levels):
            z1 = hi
        else:
            curr_last_frac = cuts[e][0]
            next_first_frac = cuts[levels[k][0]][0]
            z1 = lo + (curr_last_frac + next_first_frac) / 2.0 * extent

        # Middle cut loops, largest-area first
        mid_idx = (s + e) // 2
        loops = cuts[mid_idx][1]
        loop_areas = [_shoelace_area(lp) for lp in loops]
        order = sorted(range(len(loops)), key=lambda i: -loop_areas[i])
        sorted_loops = [loops[i] for i in order]

        # Convert each loop to primitives
        prims = [propose.loop_prims(axis, lp, native=True) for lp in sorted_loops]

        features.append({
            "id": "F%d" % k,
            "op": "pad",
            "label": "Level %d" % k,
            "axis": axis,
            "at": z0,
            "length": z1 - z0,
            "loops": prims,
        })

    # 5. Return tree
    return {"units": "mm", "features": features}
