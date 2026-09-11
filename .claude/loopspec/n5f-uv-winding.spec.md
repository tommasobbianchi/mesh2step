# n5f — P100, written BEFORE the probe. Status: pending.

2026-09-11, successor to `n5e-pinch-refuted.spec.md`.

## Correction to the recorded signature

`n5e-pinch-refuted.spec.md` reports "`BadOrientationOfSubshape` 124 (exactly 2 per reversed
face)". That 2 is a printing artefact: `dumpShellCheck` calls `dumpBRepStatuses` twice per
face — once on the shell analyzer's result `fr`, once on the standalone `fan.Result(f)`. Each
face carries **one** `BadOrientationOfSubshape`, and it is present in BOTH contexts, so the
face is invalid **on its own**, not merely inconsistent with its neighbours. `faceValid=0` on
all 64 confirms it. This strengthens the case rather than weakening it: the defect is inside
one face and can be fixed without reasoning about the shell.

## What OCCT means by it here

`BRepCheck_Face::Perform` -> `OrientationOfWires`. With a single wire (measured: `wires=1`,
`maxShare=2` on all 64) the only way to earn this status is that the wire, in the face's UV
parameterisation, encloses the *infinite* region — the winding is backwards, so the face's
material is everything except the sliver.

## Why P99's stated mechanism cannot be the cause

P99 blamed a near-tie in the outward-normal sum `sum area_t * (n_t . n_plane)`. For a PLANAR
region every triangle normal is parallel to the fitted plane normal by construction, so that
sum is `+/- total area` — decisive, never a tie. P99 is refuted on inspection, before
measurement, and this arm replaces it.

## Where the real near-tie lives

`refit_build.cpp:2639` already computes `wireSignedAreaInPlane(ow, plForArea)` and flips the
outer wire when its sign disagrees with `r.outwardNormal` (the n5d rule), counting an exact
zero as `g_bfSkips[-53]` and NOT flipping it. That is a sampled-curve area. On a region of 1-6
triangles the enclosed area is minuscule, so this is the quantity that can tie or take the
wrong sign, and it is the quantity BRepCheck then disagrees with.

## P100

For the 64 invalid faces, the outer wire's signed area **in the face's own UV
parameterisation** (shoelace over the pcurves, the quantity `BRepTopAdaptor_FClass2d`
effectively judges) has the wrong sign relative to the face orientation, while valid planar
faces on the same model have the right sign.

- **Confirmed if** the invalid faces are separated from the valid planar controls by the sign
  of `uvArea * (ori == FORWARD ? +1 : -1)`, with few or no exceptions.
- **Refuted if** the signs overlap — in which case the winding is right and the status comes
  from something else in `OrientationOfWires` (a degenerate pcurve, a zero-area UV loop),
  which the same probe will show as `|uvArea|` at or near zero.

Either outcome names the fix. The probe also reports `|uvArea|` against the region's mesh
area, so a collapsed-wire third case is visible rather than inferred.

## Prize, unchanged

13 ladder-exhausted models, 75 resolvable cylinder faces, 61.5 % -> 79.3 % on that subset,
roughly **+12.7 CADScore** — against a total of +4.0 available from the entire precision axis
(`n11-measured.spec.md`).

---

## P100: REFUTED. Orientation is not the lever.

Two probes, both env-gated on `STL2STEP_N5F_UV`, both proven reachable (950 and 202 rows) on
`L09_valve_body_normal` with P92 on.

**Probe 1 — UV shoelace of every planar face's outer wire, valid ones included as controls.**
950 observations, 4 shell-check blocks:

| valid | face ori | sign(uvArea) | outwardNormal | count |
|---|---|---|---|---|
| yes | F | + | 1 | 886 |
| no  | F | + | 1 | 2 |
| no  | **R** | + | **1** | **62** |

Every pcurve present (`missPc=0` on all 205 faces), every probe call clean. The winding is
POSITIVE on all 950 — invalid and valid alike. P100 predicted the invalid faces would be
separated by the sign. They are not.

**Probe 2 — the orientation decision itself** (`refit_build.cpp`, the "prefer
Region::outwardNormal but keep the BRepCheck-valid orientation" block). For every planar
region, both candidate orientations were tested:

```
branch      want 170   neither 32   other 0
wantOk/otherOk   (1,1) x170   (0,0) x32
after: ori=F on all 202,  valid=1 x170,  valid=0 x32
```

**`other` was never taken.** For the 32 defective regions BOTH orientations are invalid
(`wantOk=0, otherOk=0`), so no choice of face orientation can fix them. Orientation is a
symptom, not the cause — and the "keep whichever orientation validates" fallback, which
looked like the suspect, never fires on this model.

## Two facts the probes settled as a by-product

1. **The faces leave `buildFaces` FORWARD and reach the shell REVERSED.** `N5F_AFTER` reports
   `ori=F` for all 32; `DIAG_SHELL_FACE` reports `ori=R` for 62 of the 64 observations of the
   same regions. Something in shell assembly reverses them. That reversal is downstream of a
   face that was already invalid, so it is cosmetic, not causal — but every earlier reading of
   the "62 Reversed" signature as evidence about the defect was reading a downstream artefact.
2. **`rid` is not unique across components.** 64 invalid face observations are 32 distinct
   regions seen in two shell-check passes. Any per-rid tally over a whole log double-counts;
   the 64 / 342 / 2907 figures in the earlier specs are observation counts, not region counts.

## P102, written before the next probe

The face carries one wire, every vertex shared by exactly 2 edges, a nonzero positive UV area,
and is invalid in BOTH orientations. The remaining member of `BRepCheck_Wire`'s
`BadOrientationOfSubshape` family is **edge-to-edge orientation inconsistency inside the
wire**: some edge is stored with an orientation that breaks the head-to-tail chain. A
multiplicity-2 vertex census cannot see this — a reversed edge still touches exactly two
edges — which is why the n5e pinch probe came back clean while the defect was there all along.

- **Check:** walk each bad wire with `BRepTools_WireExplorer`, take `TopExp::Vertices(e, vf,
  vl)` honouring each edge's orientation, and report every index where `vl(i)` is not the same
  TShape as `vf(i+1)`.
- **Confirmed if** every one of the 32 regions has at least one break, and the valid planar
  controls have none.
- **Refuted if** the chains are continuous, which leaves only a geometric cause (pcurve
  inconsistent with the 3D curve) and the probe should then report the 2D/3D endpoint gap.

---

## P102: REFUTED. The wires chain perfectly.

`N5F_CHAIN` walks each built face's wire with `BRepTools_WireExplorer` and compares
`TopExp::Vertices(e, vf, vl, orient=true)` head-to-tail:

```
INVALID regions 29, wires 94   breaks {0: 94}
VALID   regions 173, wires 853  breaks {0: 853}
```

Zero breaks anywhere. No edge is stored against the chain. Three mechanisms are now dead:
pinch vertices (n5e), the outward-normal near-tie (P99), UV sign as built (P100), and
edge-chain inconsistency (P102).

## Stop predicting; interrogate the object

96 defective faces were written to BREP at the moment of construction
(`STL2STEP_N5F_DUMP`), then examined in OCP without another rebuild. That is what should have
happened three predictions ago.

| status | wires | plane frame | `FClass2d::PerformInfinitePoint()` | n |
|---|---|---|---|---|
| `BadOrientationOfSubshape` | 1 | right-handed | **IN** | **89** |
| `UnorientableShape` | 2 | right-handed | OUT | 4 |
| `UnorientableShape` | 1 | right-handed | OUT | 3 |

`PerformInfinitePoint() == IN` means the wire encloses the INFINITE region: the winding is
backwards, and the face's material is everything except the sliver. This is precisely what
`BRepCheck_Face::OrientationOfWires` reports as `BadOrientationOfSubshape`.

It also explains the `wantOk=0, otherOk=0` result that looked like it exonerated orientation:
`BRepCheck_Face` forces the face FORWARD before classifying, so the face's own orientation
flag cannot affect this status. Flipping the FACE was never going to help. **Flipping the
WIRE is.**

## The repair, measured on the dumped faces before any engine change

Three candidate repairs applied to all 96:

| repair | 89 single-wire BadOrientation | 4 two-wire Unorientable | 3 single-wire Unorientable |
|---|---|---|---|
| `ShapeFix_Face` with `FixOrientationMode=1` | **fixes 0** | fixes 4 | 0 |
| rebuild with the wire **Reversed**, `Inside=false` | **fixes 89** | – | 0 |
| rebuild with the same wire, `Inside=false` | 0 | – | 0 |

## The defect, in one token

`refit_build.cpp` already has a "retry reversed wire" fallback:

```cpp
BRepBuilderAPI_MakeFace mfR(asPlane(r), TopoDS::Wire(ow.Reversed()), Standard_True);
```

`Standard_True` is MakeFace's `Inside` flag, which makes MakeFace **re-orient the wire
itself**. Reversing the input is therefore a no-op, and the fallback has never been able to
change its outcome. The `ShapeFix_Face` fallback below it fixes none of this class, so nothing
else caught it.

## P103

Adding the same retry with `Inside=Standard_False`, env-gated, recovers these faces in the
engine as it does on the dumped BREPs.

- **Confirmed if** on `L09_valve_body_normal` the invalid planar regions fall from 32 to
  around 7 (the `UnorientableShape` residue), and matched cylinder faces rise on the 13
  ladder-exhausted models with no model worse corpus-wide.
- **Refuted if** the faces validate individually but the shell does not close, or if any model
  loses matched faces.

---

## P103: CONFIRMED as a repair, REFUTED as a CADScore win. Not deployed.

### Getting it to fire

Two placements failed before the third worked, and the failures are the interesting part:

1. Reversing `ow` — **0 of 543 faces repaired.** The first `MakeFace` ran with `Inside=true`,
   which re-orients the wire, so `ow.Reversed()` rebuilds the identical face.
2. Reversing the wire taken out of `outF`, but placed BEFORE the `ShapeFix_Face` fallback —
   **0 of 543.** `outF` at that point is not yet the face that ends up defective.
3. The same repair placed immediately before the orientation choice, where the BREP dumps were
   taken — **85 of 90 repaired.**

Placement, not mechanism, was the whole difference. The lesson is that "the fix does not work"
was false twice while the fix was right both times.

### On the reproducer

| | invalid planar faces in the shell | `branch=neither` |
|---|---|---|
| P92 only | 64 | 96 |
| P92 + P103 | **1** | **5** |

### On the corpus — 203 models, arm A = the deployed engine

| arm | CADScore | recall | precision | matched | built |
|---|---|---|---|---|---|
| A — deployed | **70.11** | 58.88 % | 86.65 % | 305 | 352 |
| B — A + P103 | **64.74** | 60.62 % | 69.47 % | 314 | 452 |

Recall rises, precision collapses, the net is **−5.4**. Exactly two models move, and they move
in opposite directions:

```
dUnmatched  dMatched  model                          nA   nB
        +0        +9  SpeedTestStructure_normal     130  139
       +86        +5  L09_actuator_mount_normal       0   91
```

`SpeedTestStructure` is a free gain: nine real cylinder faces, zero fabrication.
`L09_actuator_mount` produced NOTHING before and now produces a **valid, closed, free-edge-free
solid with 91 cylinder faces** — of which 86 are radii spread across 2.9655 … 3.0002 against a
truth set of {2.5 ×4, 4.0, 12.0}. That is one cylindrical band (or fillet) shattered into ~86
one-facet patches, each fitted to a slightly different radius. It is a pre-existing
fragmentation defect that the revert had been hiding, not something P103 creates.

**With that one model held at its current output, P103 scores ≈ 71.45 — +1.34.** So the fix is
worth roughly +1.3 once coaxial merging (`n5b-coaxial-merge.spec.md`) collapses those 86 into
one. Shipping it before that trades 5 CADScore for a cleaner solid on one model, which is not
a trade worth making. **Not deployed.**

### The prize estimate was wrong, and this is how we know

`n5e-pinch-refuted.spec.md` valued this arm at "+75 faces, 61.5 % -> 79.3 %, roughly +12.7
CADScore", on the reasoning that the 13 ladder-exhausted models lose their cylinders to
component reverts caused by these invalid faces. P103 takes `L09_valve_body_normal` — the
reproducer the whole arm was measured on — from 64 invalid faces to 1, and that model still
emits **zero** cylinder faces. Eleven of the thirteen do not move at all.

So the invalid planar faces were never what blocked those models. The +12.7 was an inference
from a correlation, and the correlation does not survive the intervention. The measured value
of repairing every one of them is +1.3, and the two models that do move were not among the 13.

### What is actually next

- **`n5b` coaxial merge** is now on the critical path rather than a side arm: it is what
  converts P103 from −5.4 to +1.3, and 86 fabricated faces on one model is a large, isolated,
  reproducible target.
- **The 13 ladder models need a fresh diagnosis.** Every mechanism attributed to them —
  pinch vertices, normal near-ties, UV winding, edge chaining, invalid planar faces — is now
  measured and none of them is the cause. The next step there is not another hypothesis; it is
  to take one of the 13 and trace where its cylinders are lost, the way the BREP dump did here.

---

## The 86 are a TORUS, not a coaxial run. P104, written before the probe.

Axes of `L09_actuator_mount`'s 91 built cylinder faces, from the STEP:

```
91 faces, 91 DISTINCT axes.  86 of them: |Z| = 0.000, radius 2.97-3.00,
directions spread evenly around the XY circle (26 direction pairs).
```

They are not coaxial, so `n5b` cannot merge them. Axes that all lie in one plane, rotate
uniformly, and share a radius are the signature of a **torus** — a rounded circular rim of
tube radius 3 — sliced into one cylinder patch per facet ring. The engine has no torus
primitive, so each slice is locally a perfectly good cylinder fit.

This is also the case the normal-projection test was built for, and it explains why that test
looked worthless earlier: on the deployed arm there are only 47 fabricated faces to remove, so
the ceiling was +4.0. On the P103 arm there are 133, and 86 of them are one clean geometric
class.

**P104.** For a true cylinder every facet normal is perpendicular to the axis, so
`|n_t . axis|` is ~0 across the patch; on a torus slice the normal tilts along the axis, so
the same quantity is bounded away from zero.

- **Confirmed if** on `L09_actuator_mount` the 86 torus slices separate from the 5 real
  cylinder regions by area-weighted RMS `|n_t . axis|`, with a gap wide enough for one
  threshold, and the same threshold leaves a clean model's regions untouched.
- **Refuted if** the distributions overlap — in which case the slices are too small (1-2
  facets) to carry the signal and the discriminator has to be the relation BETWEEN sibling
  patches (equal radius, coplanar rotating axes) rather than anything inside one patch.

## P104: REFUTED. The slices are locally perfect cylinders.

Area-weighted RMS of `|n_t . axis|` over every accepted cylinder region:

| model | group | n | rms min / med / max | median nTri |
|---|---|---|---|---|
| L09_actuator_mount | R ~ 3.0 (the torus) | 81 | 0.00000 / **0.00000** / 0.01434 | 10 |
| L09_actuator_mount | other radii | 12 | 0.00000 / **0.00000** / 0.02295 | 52 |
| L07_bushing | all | 18 | 0.00000 / 0.00423 / 0.00423 | 3 |
| L01_cylinder | all | 1 | 0.00000 / 0.00000 / 0.00000 | 98 |

No separation whatsoever. On a torus whose ring radius is much larger than its tube radius,
each slice IS a cylinder to within the mesh's own precision. No per-patch test can see this,
which retires the whole family of per-patch vetoes — including the `s3/s2` axis-coherence
veto, whose 93.4 %/92.3 % rates were measured on RANSAC patches of a different population.

## P105: the discriminator is BETWEEN siblings

Group accepted cylinder regions by radius. Build the orientation tensor `sum n n^T` of the
group's axis directions (sign-invariant, so antiparallel axes do not cancel) and take its
eigenvalues `L1 >= L2 >= L3`.

- **a bolt circle** — many equal-radius holes — has all axes PARALLEL: `L1` dominant,
  `L2 ~ L3 ~ 0`.
- **a torus sliced into cylinders** has axes spread around a great circle: `L3 ~ 0`
  (coplanar) and `L2 / L1 ~ 1` (spread within that plane).

So the rule is `L3/L1 ~ 0 AND L2/L1` large, on a group of at least a few members.

- **Confirmed if** it fires on `L09_actuator_mount`'s 81-member R~3.0 group and on no group
  in a corpus sweep that currently produces matched faces.
- **Refuted if** any model's real cylinders form such a group, which would mean radius+axis
  geometry alone cannot separate a torus from a legitimate arrangement of cylinders.

---

## P105: CONFIRMED. The stack measures 71.95.

The rule was checked against every radius group of 6 or more across the whole corpus before
it was written into the engine:

| model | n | R | L2/L1 | L3/L1 | fires | is it real? |
|---|---|---|---|---|---|---|
| L07_grooved_shaft | 123 | 1.991 | 1.000 | 0.000 | yes | model builds 0 matched |
| L09_actuator_mount | 81 | 2.966 | 0.963 | 0.000 | yes | the torus |
| L04_puck | 85 | 2.987 | 0.826 | 0.000 | yes | builds 0 matched |
| clamp_half_a | 82 | 1.981 | 0.655 | 0.000 | yes | builds 0 matched |
| L05_concave_block | 22 | 13.354 | 0.847 | 0.007 | yes | builds 0 matched |
| gancio_parametric | 13, 11 | – | 0.68, 0.48 | 0.000 | yes | builds 0 matched |
| L10_cross_slide | 8 | 7.558 | 0.636 | 0.000 | yes | **1 of its 23 is matched** |
| **L04_soap_bar** | **12** | **3.000** | **1.000** | **1.000** | **no** | **12 of 12 matched — protected** |
| L09_clamp | 6 | 2.000 | 1.000 | 1.000 | no | 2 of 2 matched — protected |
| SpeedTestStructure | 139 | 0.200 | 0.000 | 0.000 | no | parallel axes — protected |

`L04_soap_bar` is the case that matters: 12 genuine R=3.0 cylinders that a naive
"many equal-radius patches" rule would have destroyed. Its axes are **isotropic**
(`L3/L1 = 1.0`), not coplanar, so the flatness term spares it. `SpeedTestStructure`'s 139
parallel-axis cylinders are spared by the same term from the other side.

### Corpus result — 203 models, arm A = the deployed engine

| arm | CADScore | recall | precision | matched | built | valid solids |
|---|---|---|---|---|---|---|
| A — deployed v1.2.0 | 70.11 | 58.88 % | 86.65 % | 305 | 352 | 200/203 |
| B — + P103 + P105 | **71.95** | **60.42 %** | **88.92 %** | 313 | 352 | 200/203 |

Recall and precision both rise, and `built` lands back on 352 — the 86 torus faces are gone
and 8 real ones have taken their place. Three models move: `SpeedTestStructure` +9 matched,
`L09_actuator_mount` 0 -> 5 (and 91 -> 10 built, exit 2 -> 0), `L10_cross_slide` 1 -> 0, the
one regression, worth about 0.1.

### Gates

- **fine variant, 78 models: zero change.** matched 265 -> 265, unmatched 16 -> 16, valid
  74/78 both arms. Named sentinels exact: SOT-23 12, SOT-143 16, SuperSOT-3 12, TSOT-23 12.
- **valid closed solids 200/203, unchanged.**
- **Clean-tree parity:** re-ported into `wt-deploy` (0bac065 + P92) without any of the
  diagnostic probes, rebuilt with zero warnings, and re-measured — 71.95 with byte-identical
  per-model deltas.
- Both changes env-gated. With the variables unset the binary is v1.2.0.

Staged at `~/.local/share/mesh2step-native-v1.3.0-n5f/` with `run.sh` exporting all three
flags; verified through `run.sh` end to end. **Not promoted** — the live unit needs Tommaso's
say-so.
