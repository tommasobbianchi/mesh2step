# n11 + the axis-coherence veto, measured against the deployed 70.11 baseline

2026-09-11. Both arms of the "detection" family are now closed on measurement.

## n11 — RANSAC cylinder fallback: +0.15 CADScore

DS4 built it to spec (`src/refit_ransac.cpp`, 782 lines; 11 lines of integration in
`CMakeLists.txt` / `refit_internal.hpp` / `refit_segment.cpp`). I re-applied P92 on top so the
A arm IS the deployed engine, and ran the full 203-model corpus A/B:

| arm | CADScore | recall | precision | matched | built | valid solids |
|---|---|---|---|---|---|---|
| A — deployed (n6 + P92) | **70.11** | 58.88 % | 86.65 % | 305 | 352 | 200/203 |
| B — A + `STL2STEP_N11_RANSAC_FALLBACK=1` | **70.26** | 59.07 % | 86.69 % | 306 | 353 | 200/203 |

One model changed: `L10_idler_bracket_normal`, 0 -> 1 cylinder. Zero models worse. B-Rep
health identical, so the `J6: shell not closed freeEdges=12` warning DS4 flagged costs no
valid solid — that model was already in the invalid 3.

Gate A2 (flag off => bit-identical) verified independently by DS4 on 20 models, DATA-section
md5. **Not deployed**: 782 lines and a new env gate for +0.15 is not a trade worth the
maintenance surface. The code stays in the worktree as the record that the arm was tried.

**Why it is inert.** The fallback fires only where Phase B claimed zero cylinders — 31 of 203
models. On 30 of those, RANSAC *does* find the cylinders (P95/P97 already showed that) and the
faces still never appear, because `buildFaces` rejects them downstream: partial arcs
(`FaceBuildFailed`), corner fillets that are not standalone cylinders, and component-wide
reverts. Detection was never the binding constraint. This is the fourth independent
confirmation, and the first one measured end-to-end inside the real engine rather than in a
prototype.

## Axis-coherence (normal-projection) veto: ceiling +4.0, realistic +0.5. Not built.

The veto was measured at `s3/s2 <= 0.0126`: keeps 71/76 real patches (93.4 %), rejects
360/390 fabricated (92.3 %). Applied to the engine's own faces the arithmetic is decided
before any code:

- Built 352, matched 305, so **fabricated = 47**.
- A *perfect* filter — delete all 47, keep every real face — gives P = 100 %, R = 58.88 %,
  **CADScore 74.12**. That is the hard ceiling of the entire precision axis: **+4.0**.
- The filter as measured: matched' = 305 x 0.934 = 285, built' = 285 + 47 x 0.077 = 288.5.
  R = 55.0 %, P = 98.7 %, **CADScore 70.65 — +0.54**, because it pays 20 real faces to remove 43
  fabricated ones.

So the veto cannot justify its wiring. The ceiling computation needs no transfer assumption
and no build, which is why it was done before the build and not after.

## What this settles

Precision is worth at most +4.0 in total. Recall is worth +31 (58.88 % -> 90 %). Every further
token goes to recall, and inside recall to **P99** (`n5e-pinch-refuted.spec.md`): orientation
of 1-6 triangle planar slivers, 13 reproducers, +75 faces, ~+12.7 CADScore — larger than the
whole precision axis by a factor of three.
