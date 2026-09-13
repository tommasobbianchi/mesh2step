"""Iso render of each remaining (3D) part, tiled into one contact sheet. usage: grid3d.py <outdir> part..."""
import sys, os, struct, numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
sys.path.insert(0, os.path.dirname(__file__)); from slice import load
out = sys.argv[1]; parts = sys.argv[2:]
fig = plt.figure(figsize=(16, 16))
for k, p in enumerate(parts):
    tri = load(os.path.expanduser("~/corpora/mechparts/%s.stl" % p))
    if len(tri) > 60000: tri = tri[np.random.default_rng(0).choice(len(tri), 60000, replace=False)]
    lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
    shade = 0.25 + 0.75 * np.abs(nrm @ (np.array([0.4, -0.5, 0.77]) / np.linalg.norm([0.4, -0.5, 0.77])))
    ax = fig.add_subplot(4, 4, k + 1, projection="3d")
    ax.add_collection3d(Poly3DCollection(tri, facecolors=np.c_[shade * .75, shade * .8, shade * .9], edgecolors="none"))
    c = (lo + hi) / 2; r = (hi - lo).max() / 2
    ax.set_xlim(c[0] - r, c[0] + r); ax.set_ylim(c[1] - r, c[1] + r); ax.set_zlim(c[2] - r, c[2] + r)
    ax.view_init(28, -55); ax.set_axis_off(); ax.set_title("part %s  %s" % (p, np.round(hi - lo, 1)), fontsize=10)
    print("rendered", p, flush=True)
fig.tight_layout(); fig.savefig(os.path.join(out, "remaining_3d.png"), dpi=70); print("wrote sheet")
