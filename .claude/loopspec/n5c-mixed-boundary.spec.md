# n5c — the mixed analytic/faceted boundary (seamed360)

**Status: PROPOSAL. Two options, scoped separately. Do not start before n5a.**

## 0. MEASURED (P9: mechanism confirmed, number refuted)

`L04_cyl_bottom_chamf` emits `seamed360: BRepCheck invalid on seamed face` and
`J6: shell not closed freeEdges=51`.

| quantity | measured |
|---|---|
| chamfer ring | **243** slanted facets over **117** azimuths, \|nz\| = 0.697 (~45 deg cone) |
| cylinder wall | 104 facets over **52** distinct azimuths |
| `freeEdges` | **51 = 52 - 1** |

The chamfer IS a cone and TrueForm has no cone primitive, so the ring stays faceted: a 360
deg analytic arc then has nothing analytic to close against. **Confirmed.**

P9's number was wrong in an instructive way: `freeEdges` is NOT the neighbour's facet count
(243, or 117 azimuths). It is the ANALYTIC face's own segment count less the seam — the
chords the 360 deg face failed to absorb. So the defect is counted on the analytic side,
not the faceted one, and a fix must reconcile the analytic face's boundary with whatever
the neighbour is, faceted or not.

## 1. TWO OPTIONS — SCOPE SEPARATELY, DO NOT COMBINE

**(a) Faceted-arc transition ring.** Keep the neighbour faceted and give the analytic face
a boundary made of the neighbour's chords. Cheap, local, no new surface type. Those
vertices already sit on the fitted cylinder to ~2e-7 mm (measured in n4's
`ARC_VERTEX_TOL_MM` work), so the ring closes without moving anything.

**(b) Cone primitive.** Recognise the chamfer as a cone and rebuild it analytically. Larger
change, fixes the class rather than the seam, and would also remove the 45 cone faces seen
in KiCad parts from the "unrecognised" pile.

## 2. GATES

- [ ] `L04_cyl_bottom_chamf`: no `seamed360` warning, no `J6: shell not closed`, solid valid;
- [ ] corpus recall >= baseline everywhere, strictly better on >= 1;
- [ ] zero false rebuilds; negatives not rebuilt;
- [ ] for (b) only: a cone is not rebuilt as a cylinder anywhere on the corpus.

---

## 3. SYNTHESIS (added 2026-09-06; arms + predictions, no implementation)

**Claim.** The seamed360 failure is not a tolerance that needs loosening. It is a boundary
built from the WRONG curve: the 360° analytic face carries its own parametric seam, while
the material it must join is a chain of mesh chords. The free edges are counted on the
ANALYTIC side (`freeEdges = 51 = 52 − 1`, the cylinder's own segment count less the seam),
so the fix is to build the seamed face's boundary from the ACTUAL SHARED MESH EDGES at the
junction, with edge tolerance set to the local sagitta — which for a consistent band is
≤ d, the same fingerprint n5a and the audit already fit. One fingerprint, three decisions.

**Arms.**
- C1 *the junction is mixed by construction*: TrueForm recognises planes, cylinders and
  fillet strips. A chamfer is a cone; there is no cone primitive, so the ring stays
  faceted. Any cylinder that meets a chamfer therefore has a faceted neighbour, and this
  is the common case in real CAD, not an edge case.
- C2 *the seam is parametric, the chords are geometric*: a 360° face closes on itself at
  u=0. The engine already lands that seam on a facet generator (`refit.hpp:126-128`,
  XDirection set to a real mesh vertex azimuth) precisely so it does not bisect a facet —
  evidence this class of problem was anticipated on the analytic side and not on the
  junction side.
- C3 *tolerance is not the lever*: the rim vertices already sit on the fitted cylinder to
  ~2e-7 mm (measured in n4, `ARC_VERTEX_TOL_MM`). A boundary that fails to close by 51
  edges is not failing by 2e-7 mm; it is failing because the edges are not shared objects.

**Predictions (write results, never edit the prediction).**
- P11: every `seamed360: BRepCheck invalid` in the corpus is accompanied by a non-analytic
  neighbour at that junction, and never occurs between two analytic faces. | check: for
  each corpus model emitting the warning, classify the faces adjacent to the failing
  cylinder's rims as analytic or faceted | result: pending
- P12: `freeEdges` equals the analytic face's own `nSides − 1` in every case, not the
  neighbour's facet count. Confirmed once (52 → 51, `L04_cyl_bottom_chamf`); the
  prediction is that it holds across every seamed360 failure in the corpus. | check: the
  cause census output plus `nSides` per failing region | result: pending
- P13: building the seamed face's boundary from the shared mesh edges — rather than from
  the surface's own parametric bounds — closes the shell WITHOUT changing any vertex
  position, i.e. the resulting solid's volume differs from the faceted one by exactly the
  band's `dVolPredicted` and by nothing else. | check: implement behind a flag in the fork
  and compare volumes on `L04_cyl_bottom_chamf` | result: pending — **this is the one
  prediction that needs code, and it comes last.**

**Option (b), the cone primitive, is NOT in scope here.** It would remove the mixed
junction for chamfers specifically, but P11 must first establish how much of the corpus is
chamfer-adjacent versus mixed for other reasons. Scoping them together would make the
result unattributable, which is the mistake n5 was split to avoid.
