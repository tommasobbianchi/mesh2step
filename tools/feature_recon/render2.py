"""Render an STL from several views (flat-shaded) for semantic inspection. usage: render.py <stl> <outdir>"""
import sys, struct, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
data = open(sys.argv[1], "rb").read()
if data[:5] == b"solid" and b"facet" in data[:400]:
    pts = [tuple(map(float, l.split()[1:4])) for l in data.decode(errors="ignore").splitlines() if l.strip().startswith("vertex")]
    tri = np.array(pts, dtype=float).reshape(-1, 3, 3)
else:
    n = struct.unpack("<I", data[80:84])[0]
    tri = np.frombuffer(data[84:84 + 50 * n], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))["v"].reshape(-1, 3, 3).astype(float)
lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
print("triangles", len(tri), "bbox min", lo.round(3), "max", hi.round(3), "size", (hi - lo).round(3))
nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
views = {"iso": (30, -60), "iso_back": (30, 120), "top": (90, -90), "bottom": (-90, -90), "front": (0, -90), "side": (0, 0)}
for name, (elev, azim) in views.items():
    fig = plt.figure(figsize=(10, 10)); ax = fig.add_subplot(111, projection="3d")
    e, a = np.radians(elev), np.radians(azim)
    light = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)]) + np.array([0.3, 0.2, 0.5])
    light /= np.linalg.norm(light)
    shade = 0.25 + 0.75 * np.clip(np.abs(nrm @ light), 0, 1)
    pc = Poly3DCollection(tri, facecolors=np.c_[shade * 0.75, shade * 0.8, shade * 0.9], edgecolors="none")
    ax.add_collection3d(pc)
    c = (lo + hi) / 2; r = (hi - lo).max() / 2
    ax.set_xlim(c[0] - r, c[0] + r); ax.set_ylim(c[1] - r, c[1] + r); ax.set_zlim(c[2] - r, c[2] + r)
    ax.view_init(elev=elev, azim=azim); ax.set_box_aspect((1, 1, 1))
    ax.set_xlabel("X"); ax.set_ylabel("Y"); ax.set_zlabel("Z"); ax.set_title("%s - %s" % (__import__("os").path.basename(sys.argv[1]), name))
    fig.savefig("%s/%s_%s.png" % (sys.argv[2], __import__("os").path.basename(sys.argv[1]).split(".")[0], name), dpi=80, bbox_inches="tight"); plt.close(fig)
    print("wrote", name, flush=True)
