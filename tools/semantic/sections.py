"""Sections of a mesh for a VLM: cut the part and look at the cut outline (owner, 2026-09-30).

In a cut a fillet is a ROUND corner of the outline, a chamfer a short straight BEVEL across a corner, a hole a circle,
a pocket a notch, and a section across an extrusion is its base sketch. A crisp 2D outline carries none of the
shading ambiguity of a rendered view.

Cuts: across each axis at its mid-plane (SECTION_FRACS for more). All cuts along one axis share one frame and scale, so
heights compare directly. Each cut is drawn filled with a black outline and a mm scale bar; tiles (g x g windows of the
same frame, 800 px each) enlarge small corners.

usage: sections.py <mesh> <out_dir> <grid>"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402

AXES = {"X": ([1, 0, 0], 1, 2), "Y": ([0, 1, 0], 2, 0), "Z": ([0, 0, 1], 0, 1)}   # cut normal, sketch u, sketch v
# default: the three mid-plane cuts; more cuts only where a model asks for one (owner: "midplane sections, or whatever
# is needed"), never a sweep. SECTION_FRACS=0.25,0.5,0.75 for more.
import os  # noqa: E402
FRACS = tuple(float(x) for x in os.environ.get("SECTION_FRACS", "0.5").split(","))
OVERLAP = 1.08


def cut(m, axis, frac):
    """The section's polygons in the (u, v) frame of the axis (u, v = world coordinates), or []."""
    nrm, iu, iv = AXES[axis]
    k = "XYZ".index(axis)
    h = m.bounds[0][k] + frac * (m.bounds[1][k] - m.bounds[0][k])
    s = m.section(plane_origin=[h if i == k else 0 for i in range(3)], plane_normal=nrm)
    if s is None:
        return h, []
    polys = []
    for ent_pts in s.discrete:                       # closed loops in 3D, on the plane
        polys.append(np.asarray(ent_pts)[:, [iu, iv]])
    return h, polys


def draw(polys, out_png, center, half_span, label, px=800):
    fig = plt.figure(figsize=(px / 100, px / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_aspect("equal"); ax.axis("off")
    ax.set_xlim(center[0] - half_span, center[0] + half_span); ax.set_ylim(center[1] - half_span, center[1] + half_span)
    # even-odd fill: material between an outline and its holes is grey, holes stay white
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch
    if polys:
        verts = np.concatenate([np.vstack([p, p[:1]]) for p in polys])
        codes = np.concatenate([[MPath.MOVETO] + [MPath.LINETO] * (len(p) - 1) + [MPath.CLOSEPOLY] for p in polys])
        ax.add_patch(PathPatch(MPath(verts, codes), facecolor="#c9ccd2", edgecolor="black", lw=1.6))
    bar = _bar(2 * half_span)
    x0, y0 = center[0] - half_span * 0.88, center[1] - half_span * 0.88
    ax.plot([x0, x0 + bar], [y0, y0], color="black", lw=3)
    ax.text(x0 + bar / 2, y0 + half_span * 0.03, f"{bar:g} mm", ha="center", va="bottom", fontsize=11)
    ax.text(center[0] - half_span * 0.96, center[1] + half_span * 0.96, label, ha="left", va="top", fontsize=11)
    fig.savefig(out_png, facecolor="white"); plt.close(fig)


def _bar(span):
    raw = span / 5
    e = 10 ** np.floor(np.log10(raw))
    return float(min((1, 2, 5, 10), key=lambda k: abs(k * e - raw)) * e)


def all_sections(mesh_path, out, grid):
    """{axis: [(label, png), ...]}: per axis its 3 cuts, each as an overview then its g x g tiles."""
    m = trimesh.load(str(mesh_path), force="mesh")
    out = Path(out) / f"sect_g{grid}"; out.mkdir(parents=True, exist_ok=True)
    res = {}
    for axis, (_n, iu, iv) in AXES.items():
        lo, hi = m.bounds[0][[iu, iv]], m.bounds[1][[iu, iv]]
        c = (lo + hi) / 2; hs = float((hi - lo).max() / 2 * 1.10) or 1.0
        uv = "XYZ"[iu] + "XYZ"[iv]
        items = []
        for f in FRACS:
            h, polys = cut(m, axis, f)
            base = f"cut{axis}_{int(f * 100)}"
            k = "XYZ".index(axis)
            lab = (f"cut across {axis}, {h - m.bounds[0][k]:.1f} mm from the -{axis} side ({int(f * 100)} %), "
                   f"horizontal {uv[0]}, vertical {uv[1]}")
            p = out / f"{base}.png"
            if not p.exists():
                draw(polys, p, c, hs, lab)
            items.append((base, str(p)))
            if grid > 1:
                step = 2 * hs / grid
                for i in range(grid):
                    for j in range(grid):
                        cen = (c[0] - hs + (j + 0.5) * step, c[1] + hs - (i + 0.5) * step)
                        pt = out / f"{base}_r{i + 1}c{j + 1}.png"
                        if not pt.exists():
                            draw(polys, pt, cen, step / 2 * OVERLAP, f"{lab}\ntile r{i + 1}c{j + 1} of {grid}x{grid}")
                        items.append((f"{base} r{i + 1}c{j + 1}", str(pt)))
        res[axis] = items
    return res


if __name__ == "__main__":
    for a, t in all_sections(sys.argv[1], sys.argv[2], int(sys.argv[3])).items():
        print(a, len(t))
