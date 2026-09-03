# Port map — the model of stl2step we are reproducing

Working document for the v2 parity port. **Read this before touching the refit code.**
It exists because the port was for a long time driven by symptoms: measure a wrong
counter, instrument the code, discover a rule that was already written down in the
reference. Everything below was already knowable from `refs/stl2step/` without running
anything.

Sources: `refs/stl2step/docs/METHOD.md`, `AGENTS.md`, the 18 `FINDINGS-*.md` lane
reports, `refit_segment.cpp` (the 85-line spine), and diagnostics run against the
reference binary on 2026-09-03.

---

## 1. What the engine is

Two stages, user-selected, sharing one front end (read, weld, split into manifold
components, sew dirty components, build, unify coplanar, write STEP).

| Stage | Mode | Produces |
|---|---|---|
| 1 | `verbatim` (default) | Byte-faithful faceted B-Rep. One planar face per triangle, coplanar merge afterwards. Never invents geometry. |
| 2 | `trueform` (`--smooth`) | Stage 1 **plus** analytic recovery: tessellated curved regions become real `Geom_CylindricalSurface` faces. |

Only clean components are refit. A component needing the sewing repair path is skipped
(`smoothSkippedComponents`), never refit.

## 2. The central idea

A CAD-exported mesh is not a noisy sample; it is the deterministic output of a
tessellator that followed a **law**. It caps chordal deviation at some `d` and normal
change at some `α`, then divides an arc of extent `Φ` into `N = ceil(Φ/θmax)` equal
steps. Therefore, for a chain of strips of chord `w` meeting at dihedral `θ`:

```
R = w / (2 sin(θ/2))
```

This is an *inverse*, not a fit: it reproduces the CAD radius to mesh precision. Two
disciplines make it robust, and both are load-bearing in the port:

1. **The law's parameters are never assumed** — `d` and `α` are estimated from the
   mesh's own band statistics (`lawCalibrate`).
2. **The law is also the validity test** — a chain is an arc only if its strips really
   do satisfy an equal-step law, which is what separates arcs from coincidental
   near-flat geometry.

> METHOD.md §3: *grouping, not fitting, is the hard part.* The two characteristic
> failures are **absorption** (a shallow arc swallowed by an adjacent plane) and
> **chimeras** (strips of two different cylinders merged and fitted to a blended
> radius belonging to neither). This is why stage L runs before plane growth.

## 3. The pipeline — `refit_segment.cpp:runStages`

```
adaptCoarseSegmentParams   <-- MUTATES PARAMS BEFORE ANYTHING (see §5)
deriveTols
  A1  chartsA1             sharp-edge charts (union-find on dihedral <= thetaSharp)
  A2  growProvisionalA2    running-PCA provisional planes, TOTAL partition
  L   claimLawBandsL       tessellation-law arc bands   <-- BEFORE B1 and A3
  B1  claimCylindersB1     cylinder seeds + G1..G5 gates
  C1  claimFilletsC1       plane-plane fillet strips (if doFillets)
  A3  commitPlanesA3       plane commit, + peelLargeArcStripsA2b inside it
  D   buildTopologyD       boundary chains, loops, and the RefitStats census
```

Then, per component, in `stl2step.cpp`:

```
refit::buildFaces  ->  probe: IsClosed && BRepCheck valid && volume within budget
                       accept -> usedRefit = true
                       reject -> R2 revert: rebuild verts/edges FRESH, faceted build
```

And **over the top of all of it**, the prismatic route (§4), which for a qualifying
component replaces the whole 3D face-building problem.

## 4. Three routes a component can take

This is the distinction the port missed for a long time.

**Route P — prismatic rebuild** (`refit_prism.cpp`, `refit_prism_build.cpp`,
`refit_profile.cpp`). Detected from the recognition results: all cylinder axes
parallel, planes split cleanly into caps (normal along axis) and laterals. Then:
slice at cap levels, fit each level's closed 2D profile as lines and arcs using the
same inverse law, extrude, fuse. *Curved walls are analytic by construction — there is
nothing to repair afterwards.* METHOD.md §4.

**Route G — general analytic build** (`refit_build.cpp`). Per-region faces with
analytic boundary chains: plane|plane, plane|cylinder and cylinder|cylinder
intersection curves, pcurves and seams on cylindrical surfaces, the explode ladder
when a region will not build.

**Route R — revert to faceted.** The probe fails; the component is rebuilt verbatim.
`usedRefit` stays false and **every `smooth*` counter contributes zero**
(`stl2step.cpp:821`).

### Measured route per corpus fixture (2026-09-03, reference binary)

| fixture | tris | prism `ok` | route | notes |
|---|---:|---|---|---|
| cube | 12 | 0 (`failedCond=1`) | G | 6 planes, trivial |
| S09 | 54 | 0, both components | G | 28 planes, 14 facet faces, 8 cylinder seeds rejected |
| nonprismatic-control | 96 | 0 (`failedCond=3`, `nOblique=1`) | **R** | segmentation finds 2 planes + 2 cylinders, build reverts |
| handle-lock | 908 | **1** | **P** | `nCyl=15 nPlane=13 nCap=3 nLat=10` |
| Body11 | 15300 | — | G | reference itself builds only 127 of 583 cylinders |
| Body28 | — | — | G | |

**Only handle-lock takes route P.** Its golden decodes directly from the prism build:

```
DIAG_PRISMBUILD slab=0 faces=30 vol=14668.27 valid=1
DIAG_PRISMBUILD slab=1 faces=10 vol=1200.56  valid=1
DIAG_PRISMBUILD fuse-k=1 faces=40                     -> facesBeforeUnify 40
DIAG_PRISMBUILD usd-try faces P=23->23 C=17->15        -> smoothPlanes 23,
                                                          smoothCylinders 17,
                                                          smoothBuiltCylinders 15
```

So for a prismatic component the `smooth*` counters are **counted off the rebuilt
solid** (`refit_prism_build.cpp:1137,1167` `countSurf` -> `rs.stats`), *not* off
segmentation. No amount of fixing general-path face building can make our
segmentation-derived counters reach them.

## 5. Cross-cutting rules that bite

- **`adaptCoarseSegmentParams`** (`refit_segment.cpp`): in the coarse band it raises
  `thetaPlaneDeg` 2 -> **15** and `thetaCylHiDeg` 60 -> **70**, *before* `deriveTols`.
  A 7.5x change to the plane-growth angle. **Not ported as of 2026-09-03.**
- **Band predicates** (`refit_internal.hpp`): `coarseFusionBand` = 500..1200 tris;
  `archChainBand` = 500..8000. Almost every coarse-band relaxation is gated on these,
  and FINDINGS-INT records that un-gating them breaks the small fillet fixtures. Do
  not widen them.
- **The `smooth-flat` second unify** (`stl2step.cpp:914-931`), gated
  `smooth && !forceSew && 500 <= nTri <= 1200`, exists for *"faceted islands (revert
  fallback and analytic+facet mixes)"*. A reverted component is therefore deliberately
  **not** byte-identical to verbatim.
- **Sort orders are load-bearing.** `sortRegions` on accepted and rejected keeps the
  census stable; the C++ parallelism must become deterministic ordering in Python.
- **Counters, precisely**: `smooth*` come from the D-stage census for route G, from
  `countSurf` on the rebuilt solid for route P, and are all zero for route R.
  `smoothBuilt*` are computed in `stl2step.cpp` after the build.

## 6. What the reference itself does NOT achieve

Targets to not chase past their real ceiling:

- **Body11**: 583 cylinders recognised, **127 built** (`tests/diag/body11/KNOWN-GAP.md`).
- **handle-lock GT**: 28 faces / 15 cylinders ideal; the general path historically
  reached 16 cylinders with an extra ~16 mm duplicate, and FINDINGS-VOLUMEFIX chose
  1 built cylinder + correct volume over 16 + a 121% volume blowout
  (*"correctness over count: volume-true + valid wins"*).
- Cones, spheres, tori are recognised and left faceted. No freeform/NURBS.
- Cylinders only at **N >= 6**; fillet strips 1-3 rows; asymmetric chamfers
  (`sL/sR >= 1.3`) rejected.

## 7. Port status (2026-09-03)

| reference file | lines | ported | notes |
|---|---:|---|---|
| `refit_segment.cpp` | 85 | partial | **`adaptCoarseSegmentParams` missing** |
| `refit_grow.cpp` | 2512 | partial | A1/A2/B1/gates + L driver; `peelLargeArcStripsA2b` missing |
| `refit_lawband.cpp` | 979 | most | `lawband.py`; calibration matches reference exactly |
| `refit_math.cpp` | 1846 | partial | `refineCylinderRadius`, Pratt done; arch-chain family missing |
| `refit_chains.cpp` | 1046 | most | D stage in `segment.py` |
| `refit_build.cpp` | 4605 | ~40% | planes + cylindrical faces + M3c-1 constructors (unwired) |
| `refit_fillet.cpp` | 1612 | no | C1 |
| `refit_prism.cpp` + `refit_prism_build.cpp` + `refit_profile.cpp` | 2855 | **no** | route P — required for handle-lock |
| `dxf_export.cpp` | 326 | no | `--dxf` |

Ours: `segment.py` 2981, `build.py` 2161, `lawband.py` 738, `mesh_view.py` 149,
`stats.py` 34 — about 6.9k Python against 17.9k C++.

## 8. Method rules, learned the expensive way

1. **The reference is a deterministic source of truth. Read it before instrumenting.**
   Every defect diagnosed by measurement this session — the F4 tolerance rule, the
   missing cylinder branch in `ensureFaceValid`, the wire-orientation retry, the
   interval-stabbing calibration — was stated verbatim in the C++ or the FINDINGS.
2. **Translate; do not paraphrase.** Where the port translated, it matched the
   reference to six decimals on the first run. Where it paraphrased what a function
   "seemed to do", it was wrong (`lawCalibrate`).
3. **Know the route before optimising the road.** Hours went into general-path face
   building for a fixture that the reference rebuilds prismatically.
4. **Milestones are a delegation unit, not a porting unit.** Porting a function and
   then discovering it needs its caller is the signature of working without this map.
5. **A counter that cannot move is a routing error, not a tuning problem.**
