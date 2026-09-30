"""Tiled views of a mesh for a VLM: each view as one 800 px overview plus a g x g grid of 800 px tiles.

The DeepSeek API downsizes every image to about 800 px, so one 800 px view hides everything under about 1 % of the
part (owner, 2026-09-30: "tile 4x4 800px images for each view"). A tile is rendered directly as its own window of the
view, at 800 px with an 8 % overlap so a feature on a seam is whole in one tile, and carries a burned-in label
(view, row, column). No wireframe: tessellation lines describe the mesh, not the design, and blacken a scan.
Renderer: the deepseek-vision skill's lib_render.

usage: tiles.py <mesh> <out_dir> <grid>        (grid 1 = overview only; writes <view>.png and <view>_r<i>c<j>.png)"""
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.expanduser("~/.claude/skills/deepseek-vision/scripts"))
import lib_render as LR  # noqa: E402

VIEWS = ["PX", "NX", "PY", "NY", "PZ", "NZ", "ISO"]
OVERLAP = 1.08


def view_tiles(verts, faces, view, out, grid, px=800):
    """[(label, path)] for one view: the overview first, then the tiles row by row."""
    right, up, _look = LR._basis(LR.VIEWS[view])
    pts = np.stack([verts @ right, verts @ up], axis=1)
    c = (pts.min(axis=0) + pts.max(axis=0)) / 2
    hs = (np.abs(pts - c).max() * 1.10) or 1.0
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    res = [(view, str(out / f"{view}.png"))]
    if not Path(res[0][1]).exists():
        LR.render(verts, faces, view, res[0][1], px=px, center=c, half_span=hs, wireframe=False)
    if grid <= 1:
        return res
    step = 2 * hs / grid
    for i in range(grid):                    # rows, top to bottom
        for j in range(grid):                # columns, left to right
            cen = (c[0] - hs + (j + 0.5) * step, c[1] + hs - (i + 0.5) * step)
            lab = f"{view} r{i + 1}c{j + 1}"
            p = str(out / f"{view}_r{i + 1}c{j + 1}.png")
            if not Path(p).exists():
                LR.render(verts, faces, view, p, px=px, center=cen, half_span=step / 2 * OVERLAP,
                          title_extra=f"  tile r{i + 1}c{j + 1} of {grid}x{grid}", wireframe=False)
            res.append((lab, p))
    return res


def all_views(mesh_path, out, grid):
    verts, faces = LR.load_mesh(str(mesh_path))
    return {v: view_tiles(verts, faces, v, Path(out) / f"g{grid}", grid) for v in VIEWS}


if __name__ == "__main__":
    for v, t in all_views(sys.argv[1], sys.argv[2], int(sys.argv[3])).items():
        print(v, len(t))
