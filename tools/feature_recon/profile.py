"""Measure part 9's features against height with the bore centre fixed.
For each z: bore radius (median distance of inner-loop points outside the keyway), root radius (outer-loop points
on root arcs), tooth-top distance (outer-loop points on tooth tops), keyway bottom distance.
usage: python3 profile.py <stl> cx cy"""
import sys, math, collections
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from slice import load, section, loops, dedupe

tri = load(sys.argv[1]); cx, cy = float(sys.argv[2]), float(sys.argv[3])
zs = sorted(set([0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5, 2.0, 3.0, 5.0, 10.0,
                 15.0, 17.0, 18.0, 18.5, 18.8, 19.0, 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7, 19.8, 19.85, 19.9, 19.95, 19.98]))
print("z      bore_R   root_R   tooth_top  keyway_bottom  tooth_halfwidth  keyway_halfwidth  inner_pts outer_pts")
rows = []
for z in zs:
    L = [dedupe(l) for l in loops(section(tri, z)) if len(l) > 20]
    if len(L) < 2:
        print("%.2f  loops %d" % (z, len(L))); continue
    rad = [np.hypot(l[:, 0] - cx, l[:, 1] - cy) for l in L]
    inner = int(np.argmin([r.mean() for r in rad])); outer = int(np.argmax([r.mean() for r in rad]))
    ri, ro = rad[inner], rad[outer]
    Pi, Po = L[inner] - [cx, cy], L[outer] - [cx, cy]
    # inner: bore points are those within 1.5 mm of the modal radius; keyway bottom = the max radius cluster
    bore = np.median(ri[ri < np.percentile(ri, 60) + 1.0])
    key_pts = Pi[ri > bore + 2.0]
    key_bottom = np.median(np.hypot(key_pts[:, 0], key_pts[:, 1])) if len(key_pts) else float("nan")
    # keyway: bottom is a straight line -> perpendicular distance from centre along its normal
    if len(key_pts) > 3:
        d = key_pts.mean(0); nrm = d / np.linalg.norm(d); t = np.array([-nrm[1], nrm[0]])
        key_dist = np.median(key_pts @ nrm); key_half = (np.max(key_pts @ t) - np.min(key_pts @ t)) / 2
    else:
        key_dist = key_half = float("nan")
    # outer: root arc points ~ lowest-radius band, tooth tops ~ highest band (flat: use projection on the tooth axis)
    root = np.median(ro[ro < np.percentile(ro, 35)])
    ang = np.degrees(np.arctan2(Po[:, 1], Po[:, 0]))
    top_mask = ro > np.percentile(ro, 70)
    # group tooth points by angle sector (10 teeth -> 36 deg); tooth axis = sector mean direction
    tops = []; halfw = []
    for s in range(10):
        m = top_mask & (((ang - ang[top_mask].min() + 18) % 36) < 1e9)
    sect = collections.defaultdict(list)
    for p, a, tm in zip(Po, ang, top_mask):
        if tm: sect[int(((a + 360.0) % 360.0) // 36)].append(p)
    for pts in sect.values():
        pts = np.array(pts)
        if len(pts) < 3: continue
        u = pts.mean(0); u /= np.linalg.norm(u); v = np.array([-u[1], u[0]])
        tops.append(np.median(pts @ u)); halfw.append((np.max(pts @ v) - np.min(pts @ v)) / 2)
    row = (z, bore, root, np.median(tops) if tops else float("nan"), key_dist, np.median(halfw) if halfw else float("nan"),
           key_half, len(Pi), len(Po))
    rows.append(row)
    print("%.2f  %8.4f %8.4f  %8.4f  %8.4f       %8.4f        %8.4f        %d %d" % row, flush=True)
