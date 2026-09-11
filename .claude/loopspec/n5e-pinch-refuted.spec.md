# n5e — the pinch-vertex attribution is REFUTED. The defect is orientation on tiny planar slivers.

2026-09-11. Measured in `scratchpad/wt-p84/build-p93`, P92 on, on `L09_valve_body_normal`
(one of the 13 ladder-exhausted models that together lose **75 resolvable cylinder faces** —
the largest single item in the recall gap, 61.5 % -> 79.3 %).

## What was believed

`n6-post-build-oracle.spec.md` §3 attributes all 342 invalid planar faces to *"the n5e
pinch-vertex defect"*, and `n5e-wire-chaining.spec.md` defines it as **one mesh vertex visited
twice by a region's outer walk** — a U whose arms meet at a point. The prescribed fix was to
split such a region into two faces along the shortest interior edge path from the pinch vertex
to the opposite boundary.

## What is measured

Two new env-gated probes, both proven reachable before their zeros were believed.

**1. Stage D (`refit_chains.cpp`, before `classifyAndPush`).** Walk every loop's vertex
sequence and count vertices visited more than once:

```
N5E_SEEN  regions walked on L09_valve_body : 328
N5E_PINCH loops with a repeated vertex     :   0
```

**2. Face level (`refit_build.cpp`, at the invalid-face dump).** In a closed manifold wire
every vertex is shared by exactly 2 edges; a pinch is shared by 4+. Over all 64 invalid faces:

```
wires per invalid face : 1     (all 64)
max vertex share       : 2     (all 64)
pinch vertices         : 0     (all 64)
```

**There is no pinch, at either level.** Every invalid face carries a single, topologically
perfect, manifold wire. The prescribed split has nothing to split, and building it would have
consumed the arm and changed nothing.

## What the defect actually is

Full signature of the 64 invalid faces:

| property | distribution |
|---|---|
| type | `pln` 64 / `cyl` 0 |
| **triangles per region** | **1:2 · 2:8 · 3:36 · 4:16 · 6:2 — every one is 1-6 triangles** |
| orientation | **Reversed 62** / Forward 2 |
| statuses | `BadOrientationOfSubshape` **124** (exactly 2 per reversed face) · `UnorientableShape` 4 |

So: **tiny planar slivers, almost all built Reversed, each reporting exactly two
`BadOrientationOfSubshape`.** This is an ORIENTATION defect on degenerate-size regions, not a
wire-topology defect, and `SelfIntersectingWire` — 98 of them corpus-wide in the earlier
aggregate — does not appear on this model at all.

Note how the aggregate misled: 2907 `UnorientableShape` across 13 models sounded like the
dominant failure, but on this model the dominant status is `BadOrientationOfSubshape` at 124
against 4. The corpus-level histogram hid a per-model structure.

## Prediction P99, written before the next measurement

The two statuses per face are the face and its wire disagreeing. For a region of 1-6
triangles the outward-normal determination — `sign(sum area_t * (n_t . rho_hat))` for
cylinders, and the equivalent winding/area test for planes — has too little area to be
reliable, so the face is marked Reversed while its loop was wound for the Forward sense.

**Check:** for each invalid face, the region's computed outward/plane-normal sign, the sum it
came from, and the loop winding sense. **Confirmed if** the reversed faces are those whose
orientation sum is near zero relative to its terms (a near-tie), and the 2 Forward ones are
not. **Refuted if** the sums are decisive, in which case the orientation is being chosen
correctly and lost somewhere after the region.

## Consequence for the arm

`n5e-wire-chaining` as specified is closed: its mechanism is not present. The successor is
orientation of small planar regions, on the same 13 reproducers and the same 75 faces. The
prize is unchanged and remains the largest available: **+75 faces, 61.5 % -> 79.3 %, roughly
+12.7 CADScore**, more than everything else measured this session combined.
