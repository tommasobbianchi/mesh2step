# RESUME — state at 2026-09-13 08:55, for `claude --continue`

Client (behemoth) was restarted; nativedev, the jobs and this transcript were not affected.

## Live service

v1.8.0-fc0d7911ba1b, `active`. Drop-in: ~/.config/systemd/user/mesh2step.service.d/native.conf
Rollback chain: `native.conf.v180-rollback` (v1.6.0) · `.v170-rollback` · `.v160-rollback`
Engine dir: ~/.local/share/mesh2step-native-v1.8.0-fc0d7911ba1b/{stl2step,lib,run.sh}

## Agents that were running — CHECK THESE FIRST

    ~/.claude/scripts/job status kimi3      # Kimi: keep-open exit + t4 skip for open shells
    ~/.claude/scripts/job status ocds3      # DeepSeek: part-11 exit path + UV pcurve

Outputs (all on nativedev, /tmp survives since nativedev did not reboot):
    SCR=/tmp/claude-1000/-home-tommaso-projects-mesh2step/55ed36d6-4f09-4e83-a602-2227174fbd8a/scratchpad
    $SCR/n19/kimi3.out                 $SCR/wt-kimi/FINDINGS-CLOSURE.md   (Kimi, incremental)
    $SCR/n19/ocds3.out                 $SCR/wt-ds/                        (DeepSeek)
    $SCR/wt-p84/                       my own worktree (n19..n28)

Worktrees are snapshotted as patches in .claude/loopspec/patches/ in case /tmp is ever lost:
    n19-n28-engine-arms.patch     my tree
    wip-kimi-closure.patch        Kimi, in flight at snapshot time
    wip-deepseek-closure.patch    DeepSeek, in flight at snapshot time

## THE GOAL (unchanged)

Every cylinder, torus and fillet present in the mesh must appear in the STEP, on the
user's own parts in ~/corpora/mechparts (40 files). Runtime is NOT a concern -- the user
said so explicitly. Corpus gate that must not regress: cadbench normal **73.67**,
fine **50.13** (scripts/radius_audit.py + scripts/cadscore.py).

## Where the user's parts stand

| part | tris | curved% | cylinders shipped |
|---|---|---|---|
| 22 | 23,364 | 77 | **3** (was 0 -- the v1.8.0 win) |
| 15 | 1,784 | 7.8 | 1 |
| 8 | 1,832 | 4.8 | 2 |
| 26 / 2 / 34 / 13 | 2-3k | 42-62 | 1 / 2 / 3 / 2 |
| **9** | 46,104 | 88 | **0** — 98 cylinder regions recognised, 0 built |
| **11** | 46,674 | 98 | **0** — 56 recognised, 0 built |
| 29 / 31 / 3 / 5 | 3-6k | 34-57 | 0 |
| 37 others | | | **never measured** |

No part ships a TORUS. 3 parts exceed the 120k-triangle app limit (12, 23, 39).

## Next actions, in order

1. Read both agents' output. Kimi's keep-open approach is the most promising line: a
   labelled keep-open exit that preserves built analytic faces, with t4 volume
   verification skipped FOR THAT EXIT ONLY (open-shell volume is meaningless -- a
   167-free-edge shell integrates 15,139 vs a true 97,838 mm3) and t3 validity kept strict.
2. Relay to DeepSeek: `line=6038` is NOISE. Kimi established it is inside the `addId`
   lambda, so it is not part 11's real return-false. I had passed it on as if it were.
3. Any candidate fix must clear: mechparts/9 and /11 cylinders > 0, no regression on
   15/8/22, and cadbench normal 73.67 / fine 50.13 unchanged.

## Refuted this session — do NOT retry (each with its measurement)

1. L08_pillow_block 15.06% volume error -- does not exist; 203 normal + 281 fine models all
   within 0.05%. It was the in-memory figure n17 already discredited.
2. The ungated fprintf at refit_fillet.cpp:772 dominating runtime -- 28 lines per run.
3. Seed-triple combinatorial explosion -- mechparts/29 has 367 triples, the FAST corpus
   model L04_pillow has 4,944.
4. n20 law-band seed dedup -- costs mechparts/15 its only cylinder.
5. "ShapeFix opens the shell" -- free edges do not rise across fix.Perform(); it was unify.
6. n21 sagitta/radius gate -- removes 89% of cylinder REGIONS on part 11 (56 -> 6).
   WITHDRAWN from production after being deployed for ~50 minutes.
7. n21 contagion form (drop only when an edge-adjacent cylinder is >=10x finer) -- fires on
   neither model.
8. n22 law-band quorum bypass -- total cylinders 15 -> 27 across 6 parts but two parts go to
   zero; the quorum is load-bearing.
9. U2 cascade brake (n24) -- decideCascade's U2 path never executes on part 9 (0 hits traced).
10. Blanket-explode brake (n26) -- explodes 3,777 -> 157, cylinders stay 0, because refusing
    to explode routes to heal-discard which bins the build.
11. Keeping built faces at heal-discard (n26b) -- fires, but the cylinders were already
    exploded in the first targeted pass. Too late.
12. **n28: raising the 10,000-triangle J6 heal cap (STL2STEP_N28_HEAL_MAXTRI) -- NO EFFECT
    on parts 9 or 11.** The perfect correlation "every part shipping cylinders is < 10k
    triangles" is a coincidence of which parts are small, not causation.
13. "Mass edge-construction failure" -- DIAG_PARTIAL_EDGE is a per-edge TRACE of the
    diagnostic walk (refit_build.cpp:2061), not a failure counter. 11,800 meant 11,800 edges
    examined. Real number: N25_CHAINFAIL chains=11498 **failed=69** regionsHit=129.

14. **N14_NONREGION on mechparts/11** (DeepSeek, 2026-09-13) -- component KEPT, all four
    gates pass (t1..t4=1), but builtFaces=33,836 are ALL planes: builtCyl=0,
    smoothCylinders=3 planned. The loss is before the gates (56 regions -> 3 planned).
15. **N28_FIX_ISLE_PC on mechparts/11** (DeepSeek) -- worse: decision=REVERT,
    firstFail=t1_bf (buildFaces returned nothing), smoothCylinders=0.
16. **J6_KEEP_OPEN alone on mechparts/9** (Kimi's 08:50 binary) -- 0 cylinders,
    revertCauses brepcheck-invalid: t3 fails on leftover degenerate sliver faces
    (rid=-1, zero-length edges, 0.01-0.09 mm2). Kimi's purge of those slivers is the
    follow-up (binary c60b4bd82890; its log line needs STL2STEP_J6_DIAG=1 to print).

## Verified facts from the resume session (2026-09-13 ~09:20)

A. **The law-band cylinder finder is OFF above 8,000 triangles.** refit_internal.hpp:
   `archChainBand(mv) { return mv.nTri >= 500 && mv.nTri <= 8000; }`, comment "upper bound
   ~8000 excludes Body11 file (15300 tris)". Every heavily curved user part is above it;
   mechparts/11 logs `DIAG_LAWDECLINE reason=out_of_band nTri=46674`. Made overridable as
   STL2STEP_N29_ARCH_MAXTRI (default 8000, byte-identical) -- measurement on part 11 pending.
B. **Part 11 is discarded for a CLOSED but INVALID shell (site B).** refit_build.cpp:6216
   `if (BRep_Tool::IsClosed(sh) && !shValid)` -> :6232 `if (plan.hostR2 || cascadeSt.u2Done
   || !shValid)` -> :6296 `return false`. With shipped flags: cylRegions=56, 232 face-build
   explodes of which 56 are exactly the cylinders, then the whole build is discarded.
C. **Part 9 and part 11 share the blocker: an invalid shell, not a missing cylinder.**
   Part 9 under Kimi's keep-open + sliver purge (binary c60b4bd82890) still ends
   revertCauses brepcheck-invalid, 0 cylinders.

D. **Lifting the 8,000-triangle limit (N29) lets the finder run on part 11 -- then it declines
   at the consistency check.** DIAG_LAWSEEDS nStrips=10499 triples=140885; DIAG_LAWCAL nD=734
   nA=17 empty=1 -> DIAG_LAWDECLINE reason=empty_cal nCand=1742. 1,742 candidate cylinder bands
   are discarded because they do not share one tessellation law -- a check a real part with many
   different cylinders cannot pass. Still 0 cylinders. Next test: N29 + N22_NOQUORUM together.
E. **Part 11's recognised "cylinders" are not real bores.** Of 56 exploded cylinder regions, 8
   failed their own build (7 are FilletStrip, origin=2: 3-6 facets, span median 2.05 rad,
   chordSagitta/R median 0.50) and 48 were collateral -- but those 48 are tiny too (median 3
   triangles, 5 sides, none >= 20 triangles). The fillet stage's only shape gate is span
   30-180 deg (refit_fillet.cpp:1364); nothing checks facet count or sagitta. Test running:
   STL2STEP_N30_FILLET_SAGRATIO=0.1 (fillet strips only).
F. **Part 9 after keep-open + purge is still invalid.** 51 bad faces across rounds, 31 with a
   zero-length edge; edges clamped at 25 mm by the spCap floor (refit_build.cpp:5671
   `spCap = std::max(spCap, 25.0)`), so those edges disagree with their surface by >= 25 mm.
   After the purge nowValid=0 with no per-face report; diagnostic run pending (shell codes +
   remaining bad faces).

G. **Removing coarse fillet strips (N30_FILLET_SAGRATIO=0.1) on part 11: 41 strips dropped,
   cylRegions 56 -> 15, explodes 232 -> 188, blanket U2 rungs 37 -> 12 -- still site-B discard
   (line 6296), 0 cylinders.** Fillet strips inflated the cylinder count; they are not why the
   shell is invalid.
H. **Part 9 bad faces are ORIENTATION failures:** 41 x status 27 (BRepCheck_UnorientableShape),
   10 x status 32 (BRepCheck_BadOrientationOfSubshape). After keep-open + purge, shell, faces and
   wires all report no status, yet the analyzer is invalid -> fault is at edge/vertex level
   (dump running). Keep-open's rounds exploded 30 cylinder regions + 39 planes on part 9.
I. **DeepSeek V4.1 Flash relaunched** (job ocflash1, worktree wt-ds, 90-min timeout) on the
   orientation defect: replace bindCylPCurves' straight UV lines with pcurves projected from the
   3D edges, env-gated, measured on part 9. Findings -> wt-ds/FINDINGS-PCURVE.md.

J. **Part 11's 37 bad shell faces are mostly tiny PLANES, and none has a pinch vertex.**
   Baseline site-B dump: 21 planes (median 5 tris), 11 cylinders (median 4), 5 unowned facets;
   every face-level code seen is 27 UnorientableShape, and most carry no face-level code at all
   (fault on sub-shapes). N5E_FACEPINCH on all 37: pinchVerts=0, wires=1, maxShare=2. The
   n5e pinch-vertex defect is NOT the cause here. DeepSeek's cylinder-pcurve angle can cover at
   most the 11 cylinder faces on part 11.

K. **Part 11 with the size limit AND the consistency check lifted (N29 + N22):** all 1,742
   bands are claimed, then **938 are rejected as Span by my own n18 arc-coverage gate** (< 29
   deg), 34 survive, all exploded, 6 planned, 0 shipped. The 1,742 bands collapse into only 52
   distinct radii (0.5 % clusters): **732 bands at R~4.001**, then 61 @ 100.8, 56 @ 79.4, 54 @
   57.5 ... -- one set of cylinders sliced into thin 3-4 facet strips, not tiny features.
L. **Why fragments never merge -- hypothesis, being counted (N31):** lawBandsMergeable
   (refit_lawband.cpp:943) needs matching R, axes parallel to ~1e-6 rad (cdir >= 0.9999995),
   close axis lines, AND triangle-ID ranges that overlap or abut -- a "same original face" proxy
   that holds when an STL writer stores each face's triangles consecutively (synthetic
   exports) and fails on a real mesh.
M. **Part 9 after keep-open + purge is clean at every OWN-status level** -- 48,710 edges,
   20,375 vertices, shell and all faces report no code -- yet still brepcheck-invalid. The
   remaining fault must be context status (edge-on-face / wire-on-face / vertex-on-edge, i.e.
   StatusOnShape(ctx)), which no dump has read yet; being measured.

N. **Part 11's bad planes are invalid ON THEIR OWN -- compared pass by pass.** Census
   (STL2STEP_N5F_UV) vs site-B flags agree 19/19 in pass 0 and 2/2 in pass 1: standalone
   valid=0. Pass-0 bad planes have simple 5-6 edge outlines, positive UV area (16-25), no
   missing pcurve; pass 1 has one inverted outline (uvArea -104.5) and one reversed 10-edge
   face; passes 2-3 have no bad planes (remaining invalidity is on cylinders/facets). An
   earlier "all standalone-valid" reading was wrong: it kept only the LAST census pass per rid,
   after those faces had been exploded and rebuilt. Suspect: edge-on-face status (a curve
   borrowed from a neighbour not lying in the plane); probe N32_FACECTX running.

O. **DeepSeek V4.1 Flash confirmed the straight-UV pcurve defect with citations and built a
   gated fix (wt-ds, STL2STEP_PCURVE_PROJ, binary 09:39).** bindCylPCurves
   (refit_build.cpp:2514, called from makeFaceBound :3300-3301) writes a straight Geom2d_Line
   in (u,v) between the radially projected endpoints of every non-circle/ellipse edge
   (:2590-2592). Only a chord parallel to the axis maps to a straight UV segment; slanted chords
   diverge and the UV wire self-intersects (st=27/32). Evidence from m9.log: the 98 failing
   faces = the 98 cylinder regions; 10,813 line edges, chord p50 1.62 mm, p90 15.9 mm, max
   20.8 mm, 4,762 > 3 mm. Fix: GeomProjLib::Curve2d on the edge's real 3D curve, UpdateEdge +
   Range, fallback to the straight line on null/throw; off => unchanged. Part-9 measurement
   pending. Review notes: (1) SEAM RISK, narrowed after reading the code -- the old path's
   unwrapU (refit_build.cpp:2530-2536) shifts u2 by +/-2*pi only when the region does NOT
   straddle the seam (or the surface frame is rotated); for seam-straddling regions such as
   rid=391 the old path does not unwrap either. So the projected path newly skips period
   alignment only for non-straddling regions, where GeomProjLib::Curve2d returns the surface's
   natural 0..2*pi period and may disagree with neighbours; on straddling regions neither path
   aligns; (2) it labels the change "N30", colliding
   with STL2STEP_N30_FILLET_SAGRATIO in wt-p84; (3) duplicate #include.

P. **Part 9's LAST blocker after keep-open + purge is 3 edges with InvalidSameParameterFlag.**
   In-face statuses (StatusOnShape) on the purged shell: edgeOnFace code 11 on 6 entries -- 3
   edges, each seen from its two faces -- and nothing else (no wire-on-face, no vertex-on-edge;
   all 48,710 edges / 20,375 vertices clean on their own). Samples: tol=25 sameParam=0 (x4, the
   spCap ceiling), tol=0.1166 sameParam=0 (x2). BRepCheck_Status (0-based, from the OCCT header):
   8 InvalidCurveOnSurface, 10 InvalidSameRangeFlag, 11 InvalidSameParameterFlag,
   27 UnorientableShape, 32 BadOrientationOfSubshape. Hypothesis: these are cylinder-face edges
   whose straight-UV pcurve (bindCylPCurves) cannot be reconciled with the 3D chord -- i.e. the
   defect DeepSeek's STL2STEP_PCURVE_PROJ targets. Owner/pcurve probe running.
Q. **Stage order** (refit_segment.cpp:57-67): claimLawBandsL -> claimCylindersB1 ->
   claimFilletsC1 -> claimArcBandsN15 -> rejectTorusSlicesN5F -> rejectLowCoverageN18 ->
   rejectCoarseArcN21. On part 11, 1,742 bands are claimed (710 at R~4.001) but only 972
   cylinder regions reach n18 and none of n18's 938 drops is at R~4.0: ~770 bands leave before
   n18. Prime suspect: rejectTorusSlicesN5F (shipped on) -- groups >= 6 regions within 2% radius
   and rejects them as torus slices when their axes are coplanar-and-spread (or isotropic with
   sliver areas, P109). Probe running with STL2STEP_N5F_AXCOH=1.
R. **n18 drops on part 11 are fragments of real cylinders.** 938 drops, arc per band median
   4.7 deg (934 under 10 deg); per radius they sum to ~100-150 deg (R~66.2: 28 bands 143 deg;
   R~60.0: 26 bands 148 deg; R~55.2: 26 bands 153 deg; R~53.2: 20 bands 146 deg).

S. **Band-merge rejections on part 11, counted (N31, N29+N22 on):** lawBandsMergeable was
   called on 2,940 edge-adjacent band pairs: failR 2,222 (76 %), failAxisDir 637 (22 %),
   failTriIdProxy 57 (2 %), merged (cvOk) 24, failAxisSep 0, shortFrag 0. **The triangle-ID
   "same original face" proxy hypothesis (L) is REFUTED** -- it blocks only 57 pairs. The
   radius test rejects most; the ~1e-6 rad axis-direction test catches 637 pairs that had
   already passed the radius test, which are the likeliest true fragments.
   Tolerances (refit_lawband.cpp:28-31): kRelRMax = 5e-4 (radii within 0.05 % -- 0.03 mm at
   R=60), kCvThetaMax = 1e-3, kTauSurfFloor = 5e-5; axis direction cdir >= 0.9999995 (~1e-6
   rad). Independently fitted fragments of a coarse real mesh plausibly differ by more than
   that; a distance histogram of the rejected pairs (N33) is running to decide whether a
   looser tolerance would reunite fragments or merge different features.

T. **Part 11's bad faces fail the same way part 9 finally does: unreconciled straight edges.**
   In-face probe (N32_FACECTX) on 37 bad shell faces, paired with their type:
     plane    edge code 11 InvalidSameParameterFlag: 17   wire code 18 SelfIntersectingWire: 4
     cylinder edge code 11: 8                              wire code 18: 3
     facet    edge code 11: 1                              wire code 18: 4
   No vertex-on-edge errors. Every edge on these faces is a straight line (a few ellipses).
   BRepCheck_Status 15-21 from the header: 15 InvalidRange, 16 EmptyWire, 17 RedundantEdge,
   18 SelfIntersectingWire, 19 NoSurface, 20 InvalidWire, 21 RedundantWire.
   A straight edge on a PLANE should be trivially same-parameter unless its 3D line is not in
   the plane. REFUTED by N34_PLANEEDGE (binary 8db5954f177f, 18 plane edges): the 3D lines lie
   in their planes to <=1.5 um at start, middle and end. What the edges share instead: they are
   MICRO-EDGES, 0.09-0.31 mm long; SameParameter flag is FALSE; tolerance sits at the 25 mm
   spCap ceiling; pcurve is Geom2d_BSplineCurve with range equal to the 3D range. Part 9's
   remaining bad edges look the same (sameParam=0, tol=25 on 4 of 6). So the defect is a failed
   same-parameter computation on tiny edges, not geometry off the surface. Next: on a copy of
   each bad face, test which repair makes it valid (reset tolerance + BRepLib::SameParameter;
   ShapeFix_Edge::FixSameParameter; exact straight pcurve + SameParameter).

U. **Tori cannot reach the STEP at all: the engine has no torus primitive.** Measured on part 11
   (n5f11, STL2STEP_N5F_AXCOH=1): 728 bands at R~4 mm, every axis with z=0 and in-plane axis
   angles spread evenly over 0-180 deg -- slices of R~4 tubes swept around Z (fillet tori), only
   23 of them axis-aligned. rejectTorusSlicesN5F (refit_grow.cpp:1375) groups cylinders by radius
   ALONE (2% rel), so all of them fall in one group (N5F_TORUS drop n=739 R=3.8212 L3/L1=0.0000)
   and are dropped wholesale, facets handed back. That is the ~770 bands that "vanish before
   n18". Even if kept, refit_build.cpp:5208 rejects SurfType::Torus as TorusNYI (as are Cone and
   Sphere), and refit_fillet.cpp:1213 emits TorusNYI. The goal "every torus in the output" needs
   a torus fit + face build; no gate or tolerance change can deliver it.

V. **Part 11 law-band merge refusals, measured (N33_MERGEHIST, binary f416fa4145ac).** Histograms
   count every call (2940). Relative radius difference: <5e-4 718, <1e-3 278, <2e-3 160, <5e-3 89,
   <1e-2 26, >=1e-2 1669. failR=2222 = 2940-718 exactly, so kRelRMax = 5e-4: every refusal is at
   >=0.05%, 438 of them within 0.2% (near-misses), 1669 genuinely different radii. Axis angle,
   over the 718 that pass radius: <1e-5 14, <1e-4 49, <1e-3 18, >=1e-2 637; failAxisDir=637, so
   every axis refusal is >=0.57 deg -- different axes, i.e. the torus slices of fact U, not noise.
   Note: the cutoff `cdir < 0.9999995` is ~1.0e-3 rad; its "~1e-6 rad" comment
   (refit_lawband.cpp:996) is wrong. Consequence: loosening axis tolerance cannot merge these
   bands; only a torus primitive can. The radius near-misses are a separate, smaller lever.

SCOPE (user, 2026-09-13): tori and spheres are NOT today's issue -- they go to the next version.
   Today: full cylinders and fractions of cylinders (fillets and similar partial cylinders) must be
   reconstructed. Fact U stays as a record for the next version; the torus sweep and torus code
   map were cancelled. Dropping torus slices (n5f) is correct for today's scope.

W. **ShapeFix_Edge::FixSameParameter repairs every same-parameter face on part 11 (N35_REPAIR,
   binary 37a2860c81c1).** 26 bad faces; each deep-copied, BRepCheck_Analyzer on the copy:
   no repair 0/26 valid; reset tolerance to 1e-4 + BRepLib::SameParameter(forced) 17/26;
   ShapeFix_Edge::FixSameParameter on every edge 26/26; drop + re-project pcurves then forced
   SameParameter 23/26. Min edge length on these faces 0.089-0.125 mm. Next: apply
   FixSameParameter (env-gated) to the sewn shell before the validity gate, then run parts 11
   and 9 and the corpus.

X. **Part 11's 938 arc fragments dropped by n18 are NOT pieces of cylinders -- dropping them is
   correct for today's scope.** N18_ARCCOV with axis (binary 8141b9a9cf3b, n5f11 flag set incl.
   N29_ARCH_MAXTRI=200000 + N22_NOQUORUM): all 938 are law bands (origin CylGrow, law=1), 3-6 deg
   each. Grouped by radius (0.2%), the 14 groups summing 150-250 deg have a DIFFERENT axis
   direction and axis point for almost every member (e.g. R 57.3: 41 members, no direction shared
   by more than 2), axial mid-positions spread over ~5 m. They are local cylinder fits to a doubly
   curved surface (sphere/torus/freeform), which is out of today's scope. Cylinder work on part 11
   is therefore the shell-validity problem (W), not band merging.

Y. **DeepSeek V4.1 Flash (medium), part 9, STL2STEP_PCURVE_PROJ: pcurve projection ships 0
   cylinders (off 0 / on 0).** Measured in wt-ds/FINDINGS-PCURVE.md sec. 4-6 (logs scratchpad/n30/):
   projection is active (2237 DIAG_PCBIND_PROJ), cuts BadOrientationOfSubshape rids 15 -> 2 and
   UnorientableShape rows 1508 -> 824, but none of the 98 bad cylinder faces becomes valid. The
   3D edges are straight mesh chords that leave the fitted cylinder: edge tol 0.001628 mm, pcurve
   image vs 3D edge p50 0.0596, p90 1.46, max 3.62 mm; InvalidCurveOnSurface on 3280 edges. Cause
   chain: intersectSurfaces returns no analytic curve (warnings "smooth: IntAna cyl|cyl / plane|cyl
   empty/same -- keeping mesh polyline"), so the edge falls back to the mesh polyline. Hypothesis
   under test: these are TANGENT contacts (fillets meet their neighbours G1), where IntAna is
   ill-conditioned and returns empty when fit noise puts the surfaces a hair apart. Note on n37:
   FixSameParameter works by raising edge tolerance to the measured deviation; fine for part 11's
   0.1 mm in-plane edges, NOT acceptable for part 9's 3.6 mm chords -- report resulting tolerances.

Z. **Refused cylinder boundary intersections, by cause (STL2STEP_P2_DIAG, binary a47b14d30b55,
   today's base flag set).** IntAna_ResultType: 4 = Ellipse, 9 = NoGeometricSolution.
     part 11: plane|cyl 27, all ty=4 (ellipse found, refused by the chainResidual gate in
              pickIntAna / intAnaAcceptResidual), none tangent, side or perpendicular;
              cyl|cyl 270, all ty=9 -- 260 parallel-offset axes (the tangent/offset constructions
              refused), 10 not parallel. Radius pairs come in graded chains (22.1-23.7-25.7-28.0-31.6),
              i.e. stacked bands, not fillet|bore.
     part 9:  plane|cyl 9, all ty=4; cyl|cyl 111, all ty=9 -- 52 parallel-offset, 59 not parallel.
   Existing constructions (planeCylSideContact -> generator, planePerpCylinder -> cap circle,
   cylCylTangentContact / cylCylParallelOffset) use tol = max(epsPlane, maxVertexDev). Probes
   running: N40_GAP (how far each refused pair misses those tests, in units of tol) and N41_CHAIN
   (is the refused mesh chain itself a planar equal-chord arc, a line, an ellipse-like planar curve
   or a space curve; max vertex distance to each fitted surface). User's proposal (2026-09-13):
   recover the edge from the chain's own geometry -- a run of equal chords in one plane turning by
   a constant angle, ending where a third segment joins -- instead of intersecting two fits.

Tooling: DeepSeek delegations via oc_run.sh default to deepseek/deepseek-flash ("DeepSeek V4.1
Flash") at MEDIUM effort (--variant medium), per the user's instruction. Verified: the DeepSeek
API accepts reasoning_effort "medium" for deepseek-flash (HTTP 200); opencode had no "medium"
variant for that model, so one is defined in ~/.config/opencode/opencode.jsonc
(provider.deepseek.models.deepseek-flash.variants.medium = {reasoningEffort: medium}) and
`opencode models deepseek --verbose` now lists low/high/max/medium.

Notes from this resume: DeepSeek session ocds3 ended on its 50-minute timeout (exit 124),
not a conclusion. Kimi stopped on its usage cap (a rolling 5-hour window, not runtime).
Kimi is now run via ~/.claude/skills/ask-kimi/scripts/kimi_run.sh (transcript <= 100 KB);
DeepSeek via oc_run.sh defaults to deepseek/deepseek-flash (V4.1 Flash).

## The pattern worth remembering

The engine destroys valid geometry while reacting to small localised faults, and every fix
that has worked was a PROPORTIONALITY fix, not a geometry fix:
 - 0.6% of chains fail (69 of 11,498) -> 3,777 regions exploded, 98 built cylinders lost
 - one 2-triangle 90-degree patch with an honest 2.93 mm sagitta -> four 144-sided bores
   fitting to 0.0002 mm are exploded
 - six plane faces own free edges they did not cause -> free edges 10 -> 152 -> the whole
   collar reverts to facets

Corollary, learned the hard way twice today: every constant in this engine was fitted to
cadbench, whose parts do not resemble the user's. Measure on ~/corpora/mechparts BEFORE
believing a corpus A/B, and order any census by the property under study, never by file size.
