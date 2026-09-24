"""Edit a feature tree with an LLM, from the error map and the owner's words. The model edits STRUCTURE (a small
JSON), never writes geometry code; the compiler and the mesh check whether the edit helped.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tree as T                                       # noqa: E402

CLAUDE = os.path.expanduser("~/.local/bin/claude")

SYSTEM = """You edit a CAD feature tree (JSON) so that it rebuilds a part the way a designer would model it:
sketch -> extrude -> modify, basic shapes first (prisms, tubes, holes), then modifiers (rounds, chamfers).
""" + T.__doc__ + """
You get: the current tree, where its solid misses the mesh (the scan of the real part), and what the owner said.
Rules:
- Change only what the evidence or the owner asks for. Keep ids of untouched features; new features get new ids.
- Numbers: copy them from the evidence (cluster centres, sizes, fitted radii) or the existing tree; never invent.
- A "missing" cluster is mesh surface the solid does not reach (a boss, a rib, material to add, or a wrong size);
  an "extra" cluster is solid where the mesh has none (a hole, slot or pocket to cut).
- The owner's words win over the evidence about WHAT a feature is; the evidence wins about WHERE and HOW BIG.
Reply with ONLY the complete new tree as one JSON object, no prose."""


def clusters(m, dev, tol, k=8):
    """Where the solid misses the mesh, as a few named blobs the model can act on."""
    from scipy import ndimage
    out = []
    far = np.where(dev["face_dist"] > tol)[0]
    if len(far):                                        # mesh surface the solid does not reach
        P, W, N = m.triangles_center[far], m.area_faces[far], m.face_normals[far]
        out += _blobs(P, W, N, tol, "missing", dev["face_dist"][far])
    ex = dev["solid_dist"] > tol
    if ex.any():                                        # solid surface where the mesh has none
        P = dev["solid_pts"][ex]
        out += _blobs(P, np.ones(len(P)) * (dev["solid_mesh"].area / len(dev["solid_pts"])), None, tol, "extra",
                      dev["solid_dist"][ex])
    out.sort(key=lambda c: -c["area"])
    return out[:k]


def _blobs(P, W, N, tol, kind, dist):
    from scipy import ndimage
    g = 3 * tol
    ijk = np.floor((P - P.min(0)) / g).astype(int)
    grid = np.zeros(ijk.max(0) + 1, bool); grid[tuple(ijk.T)] = True
    lab, n = ndimage.label(grid, structure=np.ones((3, 3, 3)))
    L = lab[tuple(ijk.T)]
    res = []
    for c in range(1, n + 1):
        s = L == c
        a = float(W[s].sum())
        if a < 5 * tol * tol:
            continue
        b = {"kind": kind, "area": round(a, 3), "max_dist": round(float(dist[s].max()), 3),
             "mean_dist": round(float(np.average(dist[s], weights=W[s])), 3), "centre": np.round(np.average(P[s], 0, W[s]), 3).tolist(),
             "bbox_min": np.round(P[s].min(0), 3).tolist(), "bbox_max": np.round(P[s].max(0), 3).tolist()}
        if N is not None:
            nn = np.average(N[s], 0, W[s]); b["mean_normal"] = np.round(nn, 2).tolist()
        res.append(b)
    return res


def ask(prompt, sid=None, model="sonnet", cwd="/tmp"):
    cmd = [CLAUDE, "-p", "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--model", model, "--output-format", "json"]
    cmd += ["--resume", sid] if sid else ["--system-prompt", SYSTEM]
    d = json.loads(subprocess.run(cmd + [prompt], capture_output=True, text=True, timeout=900, cwd=cwd).stdout)
    raw = d.get("result") or ""
    m = re.search(r"\{.*\}", raw, re.S)
    return (json.loads(m.group(0)) if m else None), d.get("session_id"), d.get("total_cost_usd") or 0


def fix(tree, mesh, tol, owner_text, sid=None, model="sonnet", cwd="/tmp"):
    """One edit round. Returns (new_tree or None, stats, sid, cost). Keeps the old tree if the new one is worse
    and the owner did not ask for a structural change."""
    shape, _ = T.compile_tree(tree, tol)
    dev = T.deviation(mesh, shape, tol)
    ev = {"explained": round(dev["explained"], 4), "extra": round(dev["extra"], 4), "tol": round(tol, 4),
          "mesh_bbox": np.round(mesh.bounds, 3).tolist(), "clusters": clusters(mesh, dev, tol)}
    prompt = (f"Current tree:\n{json.dumps(tree)}\n\nEvidence (mesh units):\n{json.dumps(ev)}\n\n"
              f"The owner said: {owner_text or '(nothing: fix what the evidence shows)'}")
    new, sid, cost = ask(prompt, sid, model, cwd)
    if not new or "features" not in new:
        return None, ev, sid, cost
    s2, notes = T.compile_tree(new, tol)
    if s2 is None:
        return None, ev, sid, cost
    d2 = T.deviation(mesh, s2, tol)
    ev2 = {"explained": round(d2["explained"], 4), "extra": round(d2["extra"], 4), "notes": notes}
    return new, {"before": ev, "after": ev2}, sid, cost
