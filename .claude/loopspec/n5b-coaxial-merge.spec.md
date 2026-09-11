# n5b — coaxial band merge before edge construction

**Status: PROPOSAL, and BLOCKED ON EVIDENCE. Do not start before n5a lands.**

## 0. WHAT IS AND IS NOT KNOWN

Observed on `07_all_four_types_truth`: ~80 `smooth: IntAna cyl|cyl empty/same — keeping
mesh polyline` plus 6 `smooth: analytic MakeEdge failed`, with 2 reverted components.

**P8 predicted** these are coaxial equal-radius pairs — one cylinder split by a seam or a
crossing feature — so no intersection curve exists and IntAna is right to return empty.

**P8 was REFUTED AS A CHECK.** The output STEP holds 1 cylindrical face (truth: 1) and 1
coaxial pair, not ~80: the two components were reverted, so the artifact no longer contains
the geometry the warnings describe. **The over-segmentation hypothesis is currently
unsupported by any measurement**, and the coaxial-merge fix must not be built on it.

## 1. WHAT WOULD SETTLE IT

The pre-revert region set. That needs the minimum instrumentation — dump the committed
cylinder regions (axis, radius, extent) before the revert decision — which is exactly what
n5a makes safe to add, since after n5a these components are no longer reverted and the
geometry survives into the output where it can be measured with no engine change at all.

**Therefore: n5a first, then re-run P8's check on the n5a output.** If the pairs appear
there, this spec proceeds; if they do not, the IntAna warnings have another cause and this
spec is withdrawn.

## 2. IF IT PROCEEDS

Merge coaxial, equal-radius, edge-sharing cylindrical regions into one band before analytic
edge construction, so no intersection is attempted between a surface and itself. Gates as
n5a, plus: the IntAna warning count on `07_all_four_types_truth` drops to ~0 and its
cylindrical face count stays equal to `truth.json`'s `cyl_faces`.
