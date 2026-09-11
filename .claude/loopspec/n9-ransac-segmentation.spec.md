# n9 — RANSAC primitive detection as a replacement for the dihedral seed band

Opened 2026-09-11, after P94 refuted the fixed seed floor. Tommaso: *"test ransac. if it does
not fit, we will move to a vlm."*

## Why RANSAC was worth testing

The Phase B seed band asks "does this facet turn between 5 deg and 60 deg from its neighbour".
That question has a tessellation term in it, so the answer changes when the user re-exports the
same part at a different resolution — measured this morning on `test01`: 4 cylinders at 348
triangles, 3 at 484, **0 at 1308**. RANSAC asks a different question — "do these facets lie on a
common cylinder" — which has no tessellation term at all. That is the entire hypothesis.

## What was built

`scratchpad/ransac/ransac_cyl.py`, ~170 lines of numpy: Schnabel-2007 shape. Cylinder sampled
from two oriented points (axis = n1 x n2, centre = intersection of the two normal lines in the
plane perpendicular to it), scored by inlier facets within a radial band AND a normal-agreement
cone, kd-tree-localised sampling, least-squares refit, greedy extract-and-remove. Deterministic
seed. **Cylinders only** — this matters, see the verdict.

Parameters after one sweep: `eps_frac=0.0015` (band as a fraction of bbox diagonal),
`alpha=10 deg`, `min_spread=45 deg` of arc, `min_frac=0.005` of facets.

## P95 — RANSAC recovers the cylinders the seed band loses to fine tessellation

**CONFIRMED, on the reproducer.** Truth radii `11.5882 / 13.7518 / 16.6858 / 39.8345`.

| mesh | triangles | engine cylinders | RANSAC matched | RANSAC fabricated |
|---|---|---|---|---|
| OCCT diag/1000 | 348 | 4 | **4 / 4** | 0 |
| OCCT diag/2000 | 484 | 3 | 2 / 4 | 0 |
| user's export | 1308 | **0** | **4 / 4** | 2 |

On the user's own file RANSAC returns `11.5859 / 13.7489 / 16.6823 / 39.8261` — every radius
within **0.03 %** of the CAD. The engine returns nothing at all on that file. The recall is not
monotonically decreasing in tessellation density, which is the property the seed band lacks.

## P96 — RANSAC as a general replacement for the segmenter

**REFUTED.** Full main corpus, 203 models at `normal`, 0 timeouts, same matching rule as
`radius_audit.py` (within `max(0.5 %, 1e-4)`, each truth radius consumed once):

```
truth radii 186   RANSAC matched 75 (40 %)   fabricated 360
  109 models that HAVE truth cylinders:  186 truth, 75 matched, 109 fabricated
   27 models with NO truth cylinder at all:            251 fabricated
engine arm A (P92), same corpus, shipped truth-matched: 220
```

Six invented cylinders for every real one found. Not shippable, and not close.

### The fabrication is one specific, explainable failure — and it is mine, not RANSAC's

The models it fabricates on are not random:

```
L01_sphere 15   L01_sphere_recon 15   L01_hemisphere 16   L01_cone 14
L01_trunc_cone 13/12   L04_chamf_cube_recon 21   L04_chamf_hex_recon 26
L09_cross_block_recon 26   L04_soap_bar 17   L05_boss_hole_recon 17   L04_pillow 16
```

Every heavy fabricator is a **sphere, a cone, a fillet or a chamfer**. A detector that can only
propose cylinders will describe a sphere as a stack of cylinders, and each one has genuine
inliers and a genuine arc — the score function cannot reject it, because nothing better is
competing for those facets.

This is exactly what Efficient RANSAC's multi-primitive design exists to prevent: CGAL's
implementation fits plane, sphere, cylinder, cone and torus **simultaneously** and lets them
compete for the same points, so a sphere's facets are claimed by the sphere. **The corpus test
above therefore does NOT measure RANSAC. It measures a cylinder-only detector**, and the result
it produced is the one that design guarantees.

Where the competition problem does not arise, the prototype is exact: `L02_washer` 2/2,
`L02_thick_washer` 2/2, `L07_collar` 3/3, `L07_stepped_shaft` 3/3, `L07_shoulder_bolt` 3/3,
`L07_bushing` 2/2, all with zero fabrication.

The genuine misses cluster elsewhere: small blind holes on coarse meshes (`L02_blind_hole`,
`L02_counterbore`, `L02_block_hole`, `L06_*` plate families) where a hole has too few facets to
clear `min_frac` and `min_spread`.

## P97 — RANSAC does not address the second failure mode

**CONFIRMED, and it bounds every detector-side investment.** `monitor.stl` (from the user's
3mf, 2664 triangles): RANSAC finds **10** cylinders, in clean symmetric pairs
(`5.2958 x2, 8.2959 x2, 21.7558 x2, 24.7481 x2, 13.0987, 16.0987`). The current segmenter
**also** finds 10 regions on that file and loses all of them to component revert.

Detection on `monitor` is already correct. The loss is downstream, in shell assembly. No
segmenter — RANSAC, learned, or otherwise — can recover a face that is found and then discarded.
This is the same conclusion the measured loss ledger reached from the other direction: over the
63 reverted models, segmentation proposes 561 cylinder regions against the 137 faces needed,
**4.1x** what is required.

## Failed attempt, recorded

**Facet-size-adaptive band.** A chord of length `h` on radius `r` sits `h^2/(8r)` inside the true
surface, so a coarse mesh is legitimately further from the surface than a fine one and a band
scaled to the bounding box over-constrains it. Implemented as `sag_k * h^2/(8r)`; swept
`sag_k` in {1,2,4} against alpha {10,14} and arc {45,90}. **Every cell got worse** — best
adaptive row was 3/4+3fake vs the fixed band's 4/4+0fake on coarse. Physically sensible, measured
wrong, not pursued further. Per Rule 8 no third variation was attempted.

## Verdict

RANSAC **fits the defect it was tested for and fails as a drop-in replacement**, and those are
two separate findings that must not be collapsed:

1. It solves the fine-tessellation failure exactly, at 0.03 % radius accuracy, on the file the
   engine scores zero on. That capability is real and reproducible.
2. As a cylinder-only detector it is far worse than the current segmenter corpus-wide
   (75 vs 220 matched, 360 fabricated). This is a property of the prototype's single primitive,
   not evidence about Efficient RANSAC, and the test should not be cited as such.
3. It cannot help `monitor.stl` or any of the 63 revert-losses, which is where the measured
   90 %-goal gap actually lives.

**Open decision for Tommaso** — three options, none taken:

- **(a) Multi-primitive RANSAC.** Build CGAL (needs `libcgal-dev` + boost + eigen, none present
  on nativedev) and re-run P96 with plane/sphere/cylinder/cone competing. The prediction to
  write down first: fabrication on the sphere/cone/chamfer families collapses toward zero while
  the 75 matched holds or rises. If that prediction fails, RANSAC is finished as a direction.
- **(b) RANSAC as a narrow fallback**, not a replacement: run it only when the existing
  segmenter returns zero cylinder regions on a mesh whose median cylinder-band turn is below the
  seed floor — i.e. exactly the `test01` signature. Small blast radius, recovers the user's file,
  cannot regress the 200 models that already work because it never runs on them.
- **(c) VLM**, per Tommaso's standing instruction if RANSAC did not fit.

Note that (b) is available regardless of what happens to (a) and (c), and it is the only one of
the three whose cost is bounded today.
