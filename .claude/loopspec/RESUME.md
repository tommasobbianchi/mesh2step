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

AA. **n37/n38: FixSameParameter at the validity gate ships no cylinders -- the gate is not
   the blocker.** Binary a47b14d30b55, today's base flags, off/on STL2STEP_N37_FIXSAMEPARAM:
   part 9 on: "N37_FIXSAMEPARAM shellAlreadyValid" -- the shell is VALID at the gate, yet
   smoothCylinders=98, smoothBuiltCylinders=0, smoothAdoptedNoCyl=1, smoothMaxEdgeTolMM=3.623 --
   the 98 cylinder faces are removed inside buildFaces (their boundary edges are mesh chords up
   to 3.6 mm off the surface, fact Y) and the component adopts without cylinders. Part 11 on: no
   N37 line (the gate is never reached), smoothPlanes=0 smoothCylinders=0,
   smoothRevertedTrue=1 -- with this flag set (no N29_ARCH_MAXTRI / N22_NOQUORUM) part 11 reverts
   before the shell exists. Both parts therefore come back to the same place: the analytic edge
   at cylinder boundaries (fact Z). n37 stays unshipped; its first copy inside the sewing block
   was unreachable without STL2STEP_N13_SEW_FREE and has been removed.

AB. **How far refused pairs miss the existing constructions (N40_GAP, binary 43431a0885f1).**
   tol = max(epsPlane, maxVertexDev) as in cylCylTangentContact / planeCylSideContact.
     part 11 cyl|cyl 270: 260 have parallel axes (<0.01 deg), ALL FilletStrip|FilletStrip; the
       tangent-contact miss min(|d-(Ra+Rb)|, |d-|Ra-Rb||)/tol is <=10 for 228 and <=100 for 32.
       Example: R 18.617 / 17.940, d 0.853, internal gap 0.176, tol 0.0246 (7x). Reads as one fillet
       split into strips fitted with ~4% different radius and offset axis.
     part 11 plane|cyl 27: 23 with axis within 3 deg of the plane (CylGrow), |gap|/tol <=10 for 22
       (e.g. R 16.61, axis 1.32 deg off plane, gap -0.77, tol 0.13).
     part 9 cyl|cyl 111, all CylGrow|CylGrow: 52 "parallel" only by the 8 deg test -- the samples
       tilt 4.6-6.2 deg per step with radii growing 3.06 -> 3.25 -> 3.52 -> 3.90; miss/tol <=10 for 51.
       68 rows have >=5 deg between axes. Reads as a cone or bend approximated by cylinders.
     part 9 plane|cyl 9: miss/tol <=2 for 3, <=100 for 2, >100 for 4.
   Grouped (regions linked by refused parallel pairs):
     part 11: 260 rows = 39 region pairs, 45 regions, 6 groups of 3/4/6/9/10/13 strips. All
       internal tangency. Radius spread per group 47%, 45%, 39% (13, 10, 9 strips) -- radius
       changing monotonically along parallel, offset axes is an EXTRUDED non-circular profile, not
       a fillet split in pieces; only the 3-strip (2.8%) and 6-strip (7.3%) groups look like one
       fillet fitted in pieces.
     part 9: 52 rows = 26 pairs, 46 regions, 20 groups (16 are pairs), radius spread 6-39%, axes
       ~5 deg apart: not one cylinder in pieces either.

AC. **The refused cylinder boundary chains are tiny, and their mesh vertices already lie on
   BOTH fitted surfaces (N41_CHAIN, binary e37c21e9e6da).**
     part 11: cyl|cyl 270 -- every one a 2-vertex chain (a single mesh edge); max vertex distance
       to both fitted surfaces <=0.01 mm for 260, <=0.05 for 10. plane|cyl 27 -- 17 are 2-vertex,
       9 planar circle-like with unequal chords, 1 straight; all <=0.2 mm.
     part 9: cyl|cyl 111 -- 55 planar circle-like (3-5 verts, unequal chords), 50 two-vertex,
       5 straight, 1 planar non-circle; 102 of 111 have every vertex <=0.05 mm from both surfaces.
       plane|cyl 9 -- 8 two-vertex, 1 planar circle; <=0.01 mm for 6, <=0.2 for 3.
   None of them matches the user's "long run of equal chords turning by a constant angle" (chains
   are 2-5 vertices). Consequence: the vertices are ON the true edge; what leaves the surface
   (fact Y: up to 3.6 mm) is the straight chord drawn between them. Planned fix: when the
   analytic intersection is refused but every chain vertex lies on both surfaces within tolerance,
   build the edge from the chain -- a generator line along the axis for a 2-vertex chain parallel
   to it, else a curve through points lifted onto both surfaces -- instead of the mesh polyline.
   Rule 8: third attempt on this issue (n37 FixSameParameter, DeepSeek PCURVE_PROJ, Kimi
   J6_KEEP_OPEN all failed) -> second opinion requested from Kimi before writing it.

AD. **Where the cylinders go (N25_DIAG, binary e37c21e9e6da).** First recover pass:
     part 9 (base flags): chains 11498, failed 69, regionsHit 129; smoothCylinders 98,
       smoothBuiltCylinders 0, smoothAdoptedNoCyl 1, maxEdgeTol 3.623 mm. Refusals: plane|plane 132,
       cyl|cyl 112, plane|cyl 12.
     part 11 (base + N29_ARCH_MAXTRI=200000 + N22_NOQUORUM): chains 4422, failed 58, regionsHit 86;
       smoothCylinders 6 (not 34/1742 -- different flag set from n5f11), built 0, adoptedNoCyl 1,
       maxEdgeTol 9.755 mm. Refusals: plane|plane 108, cyl|cyl 40, plane|cyl 8.
   chainEdgeFail is set only for plane|plane and plane|cyl refusals (refit_build.cpp near the
   "IntAna none: cyl|cyl is legal polyline" comment), so on part 9 at most 12 chains can hit a
   cylinder through that arm; most of the 98 are lost elsewhere (cascade/blanket arms, or MakeFace /
   BRepCheck on faces bounded by cyl|cyl polylines). The per-cylinder loss ledger is Kimi's Q1.

AE. **Kimi second opinion on the edge fix (scratchpad/wt-kimi/FINDINGS-EDGE.md, read-only
   review, citations into wt-p84/src/refit_build.cpp; claims to verify, not measurements).**
   - Cylinders are removed by explode arms, not by BRepCheck: (1) chainEdgeFail consumer in
     recoverPass 0 explodes BOTH regions of every failed chain; (2) open-shell blanket when keepCyl
     is false; (3) per-build face gate failRidHits. Which arm kills each of part 9's 98 is not
     decidable from code: run part 9 with STL2STEP_DIAG_FBF + STL2STEP_J6_DIAG (n43, running).
   - The chord deviation (0.06/1.46/3.62 mm) is absorbed by the SameParameter pass with spCap
     floored at 25 mm, so the shell "passes" with hidden slack. FixSameParameter and pcurve
     re-projection failed because they act AFTER arm 1 already exploded the cylinder faces.
   - For part 11's 2-vertex parallel chains the code already builds a chain-anchored generator
     (meshAnchoredCylGenerator via bestCylCylConstructed) but it is likely killed by the dual-side
     identicLine / constructedLinOnBothCylinders check, because each face constructs its own line
     and the axes are offset by up to 10x tol. Fix must be ONE shared edge built from the chain,
     not another per-side candidate. Gate on the chord being parallel to BOTH axes (part 9's
     "parallel" pairs are 4.6-6.2 deg apart inside the 8 deg test).
   - For 3-5 vertex chains: alternating-projection BSpline through the chain points; needs a BSpl
     kind in AnalyticCurve and the BSpline routed to the projected-pcurve branch like the ellipse,
     never the chord pcurve.
   - Smallest step: case (a) only behind STL2STEP_CHAIN_EDGE; proof smoothBuiltCylinders 0 -> >0 on
     part 9, with the caveat that part 9's 9 plane|cyl refusals may still explode regions.
   Verified against the code (not trusting the review):
   - TRUE: spCap = max(..., 25.0) in the SameParameter pass; bestCylCylConstructed does consider
     meshAnchoredCylGenerator for both cylinders when axesNearParallel8.
   - FALSE: "identicLine compares two per-side constructions". identicLine only exempts a Lin whose
     two terminals coincide (ia == ib or distance <= Precision::Confusion) when MakeEdge returned
     null; it never compares faces' lines. So the review's "likely killer" is not the mechanism.
   - OPEN: bestCylCylConstructed gets acceptR >= 1 mm for cyl|cyl (intAnaAcceptResidual starts at
     max(sewTol*50, 1.0)), and the chain vertices sit within 0.01 mm of both surfaces, yet all four
     candidates were refused on part 11. N44_CYLCYL (running) prints chord direction vs both axes
     and each candidate's residual against acceptR.


AF. **Why the existing cyl|cyl constructions refuse (N44_CYLCYL, binary 8e264cde7d28).**
     part 11 (270 refused): every chain is a single mesh edge ~25 mm long (265 >= 20 mm) at 90 deg to
       BOTH axes, i.e. a chord across ~90 deg of arc on strips of R 18-31 mm; best candidate residual
       >10x acceptR (1 mm) for 260 (e.g. 12.47 mm). No axis-parallel line can follow it and the
       tessellation is too coarse to recover the true curve -- together with fact AB (radius spread up to
       47% along the chain) these are coarse variable-radius blend strips, not a fixable cylinder edge.
       Kimi's case (a) "2-vertex chord parallel to both axes" matches NONE of them.
     part 9 (111 refused): chords mostly <20 mm (22 under 1 mm, 3 under 0.1 mm); 91 run <80 deg to the
       farther axis; best candidate residual <=acceptR for 29 (they would pass, but
       bestCylCylConstructed only runs under cylCylParallelOffset), <=2x for 19, <=10x for 63.
       Samples: 0.05-0.24 mm chords along one cylinder's axis -- geometrically harmless as polylines.
   Conclusion: refused cyl|cyl edges do not explain part 9's 98 lost cylinders either; the explode
   ledger (n43, DIAG_EXPLODE) decides.

AG. **Part 9 explode ledger: where the 98 cylinders die (n43, binary e37c21e9e6da, base flags +
   N25_DIAG + DIAG_FBF + J6_DIAG).** DIAG_EXPLODE in log order, cumulative (planes / cylinders):
     1. round 0 per-face build failure (28 DIAG_FBF rows, all type=1): 0 / 28. They are small partial
        cylinders: nTris 5-28, spanU 0.73-2.10 rad, R 2.86-17.86, maxVertexDev 0.004-0.078, origin
        CylGrow, lawBand 0.
     2. chainEdgeFail arm (N25_CHAINFAIL failed=69 regionsHit=129): 126 / 29.
     3. N13 targeted explode (N13_TARGETED freeE=541 regions=258): 259 / 39.
     4. final blanket: 3679 / 98 -- every remaining region, including 59 cylinders that never failed.
   So there are two independent losses: 28 cylinders whose own face build fails, and 59 lost to the
   final all-regions explode. The refused-intersection work (Y, Z, AB, AC, AF) explains neither
   directly. Next: the trigger of step 4, and the failure condition behind DIAG_FBF.
   Step 4 trigger: J6 "shell not closed freeEdges=541 faces=26533 recover=0", then after the targeted
   explode "freeEdges=137 faces=28686 recover=1" -> recoverPass 1 blanket explodeAll (refit_build.cpp
   `else if (recoverPass < 2 && !n26BlanketWouldWipe(rs, exploded) && explodeAll())`).
   Open edges by owner face (DIAG_J6 freeE rows, type from DIAG_EXPLODE):
     recover 0 (541): plane zero-length 170, plane no-chain(ci=-1) 176, plane chain 91; cylinder
       no-chain 25, chain 20, zero-length 10; unknown 49. 265 faces, 32 of them cylinders.
     recover 1 (137): plane zero-length 37, no-chain 31, chain 25; cylinder no-chain 17, chain 11,
       zero-length 6; unknown 10. 78 faces, 19 cylinders.
   The shell stays open mainly because of PLANE faces with zero-length and chain-less edges.
   Pairing by coordinates (DIAG_J6 pa/pb; "ci" is only a 0.05 mm endpoint match against COLLAPSED
   chains, so ci=-1 means "not a collapsed analytic chain", not "no geometry"):
     recover 0 (541): zero-length 197, all sitting on an endpoint of another free edge; of 344
       non-zero, 242 have a partner free edge with the same endpoints within 0.001 mm (24 on
       cylinder faces), 271 within 0.1, 314 within 0.5.
     recover 1 (137): zero-length 45 (all on endpoints); of 92 non-zero, 40 partnered within
       0.001 mm (12 cylinder), 60 within 0.1, 75 within 0.5; 17 unpartnered. Every endpoint is used
       by 2 or 4 free edges -> they form closed gap loops.
   So most of the opening is duplicated, unshared edges plus degenerate zero-length edges -- a
   SHARING problem, not missing geometry. STL2STEP_N13_SEW_FREE (sewing arm) is not in the base flag
   set; part 9 with it on: n47 running.
   Prior measurement (live run.sh v1.8.0 notes): N13_SEW_FREE at N27_SEW_TOL_MM=0.1 on mechparts/9
   "541 free edges; sewing reports closed=0 accepted=0" -- so it was measured and not shipped.
   Why a sew that pairs the 242 exact duplicates still does nothing (refit_build.cpp, n13Sew block):
   acceptance is all-or-nothing -- `ok = !ns.IsNull() && nf == built.size() && IsClosed(ns) &&
   (nsValid || !strict)`. A sew that REDUCES free edges but leaves any open is discarded, and the
   targeted/blanket cascade then runs on the unsewn shell. n47 (DIAG_FBF on) prints
   "N13_SEW freeE=<before>-><after>" to measure how much the sew closes before it is thrown away.
   MEASURED (n47, binary c02cf4c7c84e, base + N13_SEW_FREE + N13_SEW_WHY + DIAG_FBF):
     recover 0: N13_SEW faces=26533->26533 freeE=541->54 closed=0 accepted=0 tol=0.1
     recover 1: N13_SEW faces=28686->28686 freeE=137->31 closed=0 accepted=0
     N27_FIXFACE reject changed=1 closed=0 valid=0 (both passes)
     sewn shell's invalid faces (N13_SEW_WHY): 91 status 27 UnorientableShape, 18 status 32
     BadOrientationOfSubshape, 1 status 23.
     Outcome unchanged: explodes 3679 planes / 98 cylinders, smoothBuiltCylinders 0.
   Sewing closes 90% (541->54) and 77% (137->31) of the gap and is discarded because it is not 100%.
   Keeping a partial sew would leave 54 edges for the targeted arm instead of 541, but it also exposes
   110 orientation-invalid faces that the final gate would reject (status 23 is
   BRepCheck_InvalidImbricationOfWires; 27 UnorientableShape; 32 BadOrientationOfSubshape).
   An accepted sew sets `sh = ns; shClosed = true;`, and the J6 free-edge census + targeted heal that
   follow read `sh`. Experiment n48 (STL2STEP_N48_SEW_PARTIAL, running on part 9): keep a sew that
   preserves the face count and strictly reduces free edges, adopt it as `sh` but leave shClosed false,
   so the targeted arm sees only the unpaired edges and every closure/validity gate still applies.



   The 28 DIAG_FBF cylinders: 27 have a single Outer loop of 4-10 chains, 1 has Outer+Inner.
   Existing switch STL2STEP_N26_NO_BLANKET holds the blanket and (n26b) keeps the built faces as an
   open shell; not yet measured on part 9 after n26b (n45 running). Exit line inside
   buildPartialCylinder for the 28: N46_PCYL_FAIL probe (n46 running).


AH. **n45: part 9 with STL2STEP_N26_NO_BLANKET ships 0 cylinders (binary 8e264cde7d28).**
   N26_BLANKET_HELD candidates=3479 cyls=98 alreadyExploded=39 (x2), then
   N26_KEEP_BUILT faces=28686 (shell left open) -- yet RESULT: smoothRevertedTrue=1,
   smoothCylinders=0, smoothBuiltCylinders=0, watertight=true, 44436 facet faces. The kept open
   shell is reverted downstream: buildFaces returns true with BUILDFACES-EXIT:kept-built-open-shell,
   then stl2step.cpp:922 `ok = BRep_Tool::IsClosed(probe); if (!ok) revCause = "shell-not-closed"`
   reverts the component. Accepting open shells there would be suppressing a revert, which the
   project forbids -- so the route for the 59 cylinders is to CLOSE the shell (the plane-face
   zero-length and chain-less open edges), not to keep it open.
   Ran 2m49s CPU vs ~10 min normally: the early keep-built exit skips the later recovery passes.
   n46: N46_PCYL_FAIL captured the wrong thing -- all 28 exitLine values are buildOneRegion's own
   returns (5507/5511/5518), so buildPartialCylinder does not set g_bfExitLine on its failure
   paths. Its real exit needs a local reason code (reading its return sites).
   Resolved from existing COLLAPSE_DIAG logs (scratchpad/n30/off.log = DeepSeek baseline, and
   scratchpad/n19/m9.log): all 28 DIAG_FBF cylinders print `DIAG_PARTIAL rid=<id> all-failed` -- every
   tryAllSurfs attempt in buildPartialCylinder (forward wire, reversed wire, refreshed wire) fails.
   Other DIAG_PARTIAL reasons there: valid 199-207, ensure-invalid 300, max 300 (both print-capped).
   Consistent with fact Y: the faces are invalid because their boundary edges are slanted mesh chords
   off the cylinder, so no wire orientation helps.


AI. **n48: keeping a partial sew (STL2STEP_N48_SEW_PARTIAL) cuts the collateral explodes but ships 0
   cylinders on part 9 (binary c7d79f196bb9, base + N13_SEW_FREE + DIAG_FBF + N25_DIAG).**
     recover 0: sew 541->54, kept; N13_TARGETED freeE=54 regions=20 (was freeE=541 regions=258).
       Cumulative explodes after the targeted arm: planes 135 / cylinders 31 (was 259 / 39).
     recover 1: rebuild brings free edges back to 473 (the rebuild discards the previous sew); sew
       473->39, kept; still open -> final blanket -> 3679 / 98; smoothBuiltCylinders 0,
       smoothAdoptedNoCyl 1.
   The 28 DIAG_FBF cylinders are still exploded first (unchanged). What blocks closure is now 39
   free edges that sewing at 0.1 mm cannot pair; n49 (J6_DIAG on the kept sew) lists them.

AJ. **The 28 all-failed partial cylinders carry pcurves in inconsistent u conventions (measured from
   scratchpad/n30/off.log, DIAG_PARTIAL_EDGE pcUV vs DIAG_PARTIAL_RID u-range; a pcurve edge is
   "in-range" if its mid-u lies in the region's fitted span (x1.3), "2pi-shift" if u+-2pi does,
   "MIRRORED" if -u does).**
     28 failing faces: line in-range 3303, line 2pi-shift 1146, line MIRRORED 645; elips 2pi-shift
       258, MIRRORED 156, in-range 100. 23 of 28 have at least one mirrored edge.
     70 valid faces (contrast): line in-range 4743, 2pi-shift 51, MIRRORED 54; elips in-range 237,
       MIRRORED 78, 2pi-shift 69. 10 of 70 have a mirrored edge.
   Failing faces mix u conventions inside one wire far more often (2pi-shift 1146 vs 51 lines), which
   fits their status 27 UnorientableShape (a UV wire that crosses itself) better than the
   chord-sag explanation alone. The classification is crude near u=0; reading the u computation on
   both pcurve paths (bindCylPCurves regionU vs ShapeFix projection onto cylSurfaceForRegion) next.
   ROOT CAUSE FOUND for the rot-trim attempts (code, verified on rid 239 in scratchpad/n30/off.log):
   tryRotTrimmedSheet builds `trim = Geom_RectangularTrimmedSurface(cylSurfaceForRegion(r) [ax rotated
   by uMin], 0, span, vMin, vMax)` and calls makeFaceBound(trim) -> bindCylPCurves(ow, trim, r).
   bindCylPCurves does `cyl = Handle(Geom_CylindricalSurface)::DownCast(surf)`, which is NULL for the
   trimmed wrapper, so `rotated` is false and toUV uses regionU(r) (unrotated frame). Non-line edges
   go through ShapeFix projection onto the rotated sheet instead. rid 239 (uMin -0.834): line pcurves
   u in [-0.834, 0.019], ellipse pcurves u 0.834..0.853 in the same wire -> uvA -6.99, st=27.
   Attempt tags on the 28: rect-trim fwd/rev 112, untrim 112, rot-trim fwd/rev 108 + rev-hole 14,
   rot-ax 108, seam-box 64 -- all valid=0, so this bug accounts for the rot-trim attempts only; the
   other attempt kinds fail for another reason. Fix under test (n50): STL2STEP_N50_TRIMROT unwraps
   the trimmed surface's BasisSurface() before the DownCast. Part 9: arm a N50 only, arm b N50 +
   N13_SEW_FREE + N48_SEW_PARTIAL.
   All attempt kinds on the 28 fail the same way (off.log DIAG_PARTIAL_TOPO, raw/pre-fix/post-fix/
   ensure phases): rect-trim 63x4, untrim 63x4, rot-ax 60x4, seam-box 32x4 -> UnorientableShape only;
   rot-trim raw 61 UnorientableShape, post-fix 49 + 12 BadOrientationOfSubshape. ShapeFix_Face never
   changes the status. Wire walk: stalls in 80-95 attempts per kind and open wires in 20-83; 56-64
   attempts per kind have missing pcurves. So the rot-trim DownCast bug is one defect among several;
   the shared one is at wire level (stalls, open wires, missing pcurves), not the surface choice.
   REFUTED as the discriminator: micro-edges. First-attempt wires, line edges: 28 failing faces --
   shortest <0.001 mm 2, <0.01 1, <0.1 14, >=0.1 11, mean share of lines <0.1 mm 0.21; 70 valid faces
   -- 3, 1, 52, 14, share 0.24. Valid faces carry micro-edges as often or more.
   REFUTED as the discriminator: slanted chord sag (the fact-Y / DeepSeek causal story at FACE level).
   Line pcurves with du>0.05 rad and dv>1 mm, worst sag R*(1-cos(du/2)), first attempt:
     28 failing: no slanted chord 9, 1-2 chords 2, >2 chords 17; worst sag 0 (9), <1 mm (8), >=1 mm (11).
     70 valid:   1-2 chords 7, >2 chords 63; worst sag <0.01 (2), <0.1 (1), <1 mm (23), >=1 mm (44).
   Valid faces carry MORE and larger chord sag; 9 failing faces have none. Chord sag is not what makes
   the 28 faces unorientable (it still matters for edge tolerance, fact Y).
   DISCRIMINATOR (first raw attempt, off.log DIAG_PARTIAL_TOPO): 70 valid faces -- walk ok 70/70,
   all pcurves 70/70, closed wire 70/70. 28 failing -- walk stalled 11, MISSING pcurves 11, closed wire
   28/28. uvArea sign does not separate them (valid 38 negative / 32 positive; failing 19 / 9).
   Failing faces are wider (span median 1.650 rad vs 1.189) and 1 of 28 has an inner loop (0 of 70).
   So 11 of the 28 have a wire the walker cannot traverse and edges without a pcurve; the other 17
   pass both tests and are still unorientable.
   The 11 "stalled" faces (rids 433 444 445 446 460 508 518 522 618 819 838): for 9 of them the
   DIAG_PARTIAL_EDGE walk records exactly ONE edge before stalling (508: 8, 522: 9) -- the wire
   explorer cannot get past the first edge, i.e. consecutive edges do not share a vertex TShape. The
   "missing pcurves" count is just the edges the walk never reached. Wire-assembly (vertex sharing in
   buildLoopWire) defect, not a pcurve defect.
   NOT a discriminator: UV continuity between consecutive pcurves on complete walks -- failing 17:
   continuous 7, gap<0.1 1, <1 1, >=1 8; valid 70: continuous 40, <0.1 11, <1 7, >=1 12.

AK. **After the kept sew, part 9's shell has NO real gap: every remaining free edge is zero-length
   (n49, binary c7d79f196bb9, base + N13_SEW_FREE + N48_SEW_PARTIAL + J6_DIAG).**
     recover 0: 54 free edges = 54 zero-length (facet/unknown owner 28, plane 20, cylinder 6), 22 owner
       faces (cylinders 456, 519, 822). No non-zero free edge at all.
     recover 1: 39 free edges = 39 zero-length (facet 22, plane 12, cylinder 5), 13 owner faces
       (cylinders 456, 519).
   So the final blanket that kills the 59 healthy cylinders fires on degenerate edges only. Test n52
   (STL2STEP_N52_DROP_ZEROLEN): when every free edge of the sewn shell is shorter than 1e-4 mm, drop
   them with ShapeFix_Wireframe::FixSmallEdges, re-test closure, remap faces through the fix context;
   the existing validity rule still applies.

AL. **n50: fixing the trimmed-surface rotation check (STL2STEP_N50_TRIMROT) makes 20 of the 28
   failing partial cylinders build -- failed cylinder face builds 28 -> 8 (binary ad543757e772).**
     arm a (N50 only): FBF type=1 8; N25 failed=70 regionsHit=131; J6 freeEdges 725 (recover 0) ->
       256 (recover 1); N13_TARGETED freeE=725 regions=344; final explodes 3679 / 98; built cyl 0.
     arm b (N50 + N13_SEW_FREE + N48_SEW_PARTIAL): FBF 8; sew 725->84 kept, N13_TARGETED freeE=84
       regions=38; recover 1 sew 613->65 kept; still open -> blanket -> 3679 / 98; built cyl 0.
   More faces built means more free edges before sewing (541 -> 725), so closure is still the blocker.
   Next: n53 = N50 + sew partial + N52_DROP_ZEROLEN (+ J6_DIAG residual census).

AM. **External OCCT advice (user's friend, 2026-09-13) -- recommendations, checked against our data.**
   - Never pass Geom_RectangularTrimmedSurface to the face builders; trim only by wires. CONFIRMED by
     fact AL (n50: the trimmed wrapper hid the rotation from bindCylPCurves; fixing it 28 -> 8 FBF).
   - Align the cylinder X axis to the patch's mid angle so U stays in (-span/2, span/2): equivalent to
     cylSurfaceForRegion rotating X to uMin (U in [0, span]) as long as span < 2pi.
   - Consecutive wire edges must share the same TopoDS_Vertex TShape; pre-create junction vertices;
     sanitize with ShapeFix_Wire FixReorder / FixConnected / FixEdgeCurves / FixDegenerated. Matches
     fact AJ-stall (9 of 11 stalled faces walk one edge); n51 probe measures broken joints.
   - Zero-length edges after sewing: ShapeFix_Wireframe::FixSmallEdges may break closure/orientation.
     Preferred: (A) ShapeFix_Wire::FixSmall per face BEFORE sewing (precision = sew tolerance); or
     (B) ShapeFix_Shape on the sewn shell with FixWireTool()->FixSmallMode/FixConnectedMode/
     FixDegeneratedMode = 1, FixFaceTool()->FixOrientationMode = 1, faces tracked via Context().
     n52 (Wireframe, guarded by freeAfter==0 + face count + validity) runs first; (B) then (A) next.
   - Replace global explode with local patch substitution (hybrid shell: analytic faces + faceted
     patches), and use analytic intersections between primitives, mesh chords only against freeform.
     The engine already intersects first and falls back to chords on refusal (facts Z, AF).
   - For complex UV loops: BOPAlgo_BuilderFace / BRepTopAdaptor_FClass2d orientation checks.
   Follow-up from the same source:
   - ShapeFix_Wire::FixConnected is a repair, not a substitute for building shared vertices; construct
     one TopoDS_Vertex per junction and reuse it in both edges.
   - Analytic|analytic boundaries: exact S1 x S2, never mesh -> projected polyline -> fitted curve.
     Analytic|freeform: keep mesh-node correspondence, piecewise-linear or low-degree UV curve.
   - BRepLib::SameParameter only reparameterises curves that already describe the same edge; it does
     not reconcile independently approximated 2D and 3D curves.
   - Distinguish geometrically tiny edges (distinct close vertices) from topologically collapsed ones
     (both ends the same vertex after sewing); use a separately justified edgeRemovalTolerance, not the
     sewing tolerance (n52/n54 use 1e-4 mm vs sew 0.1 mm). Classify each collapsed edge (isolated
     artifact / merge neighbours / rebuild / legitimate degenerate) and replace via BRepTools_ReShape
     with local validation, rather than dropping edges blindly after sewing.
   - Per-region fallback with a quality chain (wire valid -> face valid -> sews -> shell valid, else a
     local triangulated patch) instead of all-or-nothing; adjacency classes ANALYTIC_ANALYTIC /
     ANALYTIC_FREEFORM / FREEFORM_FREEFORM each with a fixed boundary policy.
   To measure next: for the post-sew zero-length free edges, same vertex TShape at both ends
   (collapsed) or distinct vertices (tiny).


AN. **Broken wire joints separate failing partial cylinders from built ones (n51, binary
   4f9f65922432, base flags + N51_WIREJOIN, part 9).** A joint is broken when the last vertex of edge i
   and the first vertex of edge i+1 of the outer wire are not the same TShape.
     28 failing (DIAG_FBF) faces: 16 have broken joints, 12 none. 36 broken joints, all Line>Line;
       gaps >=0.1 mm 29, <0.1 mm 6, 0 (same point, different TShape) 1.
     70 built faces: 1 has broken joints (2 joints: gap <0.1 and 0).
   So for 16 of the 28 the wire edges from adjacent chains end at different points (mostly >=0.1 mm
   apart), which is what stalls BRepTools_WireExplorer (fact AJ-stall) and matches the external advice
   that consecutive edges must share one TopoDS_Vertex. The other 12 failing faces have a connected
   wire (N50 trimmed-rotation fix already rescues 20 of 28). n55 prints, per broken joint, the two
   chains, whether each edge is collapsed (analytic) or polyline, region pairs, terminal mesh vertices.
   n54 (STL2STEP_N54_SHAPEFIX_SMALL, ShapeFix_Shape variant of the zero-length drop) built:
   binary bd73a7cdd582, not yet run.

AO. **n52: ShapeFix_Wireframe::FixSmallEdges does not remove the post-sew zero-length edges (binary
   c83e072dca09, part 9, base + N13_SEW_FREE + N48_SEW_PARTIAL + N52_DROP_ZEROLEN).**
     recover 0: free=54 zero=54 -> freeAfter=47, applied=0.  recover 1: free=39 zero=39 -> freeAfter=38.
   Only 7 and 1 dropped; shell stays open; outcome unchanged (FBF 28, explodes 3679/98, built cyl 0).
   As the external advice warned. Next n57: ShapeFix_Shape small/connected/degenerated modes
   (STL2STEP_N54_SHAPEFIX_SMALL, binary 1187644f33b5 which also counts collapsed = same vertex TShape
   at both ends), arm a without and arm b with N50_TRIMROT.

AP. **n53: N50 rotation fix + N13_SEW_FREE + N48_SEW_PARTIAL + N52 (Wireframe) on part 9 -- 0 cylinders
   (binary c83e072dca09).** FBF type=1 8 (vs 28 without N50).
     recover 0: sew 725->84 kept; N52 free=84 zero=59 -> not applied (needs all zero-length);
       N13_TARGETED freeE=84 regions=38.
     recover 1: sew 613->65 kept; N52 free=65 zero=47 -> not applied.
     J6 residual census: block 0 84 = 59 zero-length + 25 non-zero (longest 6.2973 mm);
       block 1 65 = 47 zero + 18 non-zero. Final blanket 3679 / 98; smoothBuiltCylinders 0.
   So the 20 cylinder faces that N50 rescues bring REAL gaps (non-zero free edges up to 6.3 mm) that
   sewing at 0.1 mm cannot pair -- closure needs those edges to match their neighbours, not only the
   zero-length cleanup.
   Residual detail (J6_DIAG rows, owner type from DIAG_EXPLODE):
     recover 0 non-zero 25: owners plane 9, cylinder 8, facet 8; lengths 0.007-0.105 mm (11),
       1.2-2.0 mm (8), 6.2-6.3 mm (6); nearest partner free edge within 0.1 mm 13, 0.5 mm 10, 2 mm 1,
       farther 1; every endpoint touches another free edge within 0.01 mm (closed gap loops).
     recover 1 non-zero 18: owners cylinder 7, plane 6, facet 5; partner within 0.1 mm 11, 0.5 mm 6,
       farther 1. Cylinder owners 445, 456, 467 -- all three rescued by N50 (not in DIAG_FBF).
   Gaps sit around a handful of rescued cylinders and come in near-coincident pairs just outside the
   0.1 mm sew tolerance. Widening the sew tolerance is not the fix (it would weld 0.5 mm offsets);
   those faces' boundary edges must meet their neighbours.
   Pairing of the 18 recover-1 non-zero free edges (nearest partner by endpoints, n53 log):
     ORIENTATION CONFLICT (identical segment, both faces traverse it in the SAME direction, gap 0):
       cylinder 445 <-> plane 844 (6.297 mm); cylinder 456 <-> facet (6.196 mm). Sewing will not merge
       same-direction duplicates, so these rescued cylinder faces carry the wrong orientation.
     SPURS INSIDE ONE FACE (partner on the same face): cylinder 467 three edges 0.007-0.027 mm;
       cylinder 456 two 0.019 mm edges traversed back and forth (out-and-back spur in the wire).
     OFFSETS JUST OVER SEW TOL (reversed, i.e. correctly oriented): planes 1407 <-> 2794 at 0.170 mm
       (two pairs, 1.2 and 2.0 mm long); plane 1813 <-> facet at 0.105 mm; two 0.085 mm facet edges.
   All cylinder owners (445, 456, 467) are faces the N50 fix rescued: some rescued faces come out
   inverted or with spurs. Next: n58 lets the ShapeFix_Shape repair (FixOrientationMode, small,
   connected, degenerated) run when non-zero free edges remain (STL2STEP_N58_REPAIR_ANY), still
   accepted only if freeAfter == 0, same face count, validity rule; plus STL2STEP_N13_SEW_ORIENT.



AQ. **The broken wire joints are ORDER/DIRECTION defects, not geometric offsets (n55, binary
   e4cd7a5f2ac4, base flags, part 9).** 36 broken joints on the 28 failing faces (2 on other faces).
     gap: 0 -> 1, <0.1 mm 6, <1 mm 2, <5 mm 14, >=5 mm 13 -- most are whole-edge lengths (5-15 mm).
     edge kinds at the joint (collapsed analytic A,B): polyline/polyline 21, analytic/polyline 8,
       polyline/analytic 5, analytic/analytic 2. Same chain on both sides of the joint: 7.
     Every joint vertex resolves to a mesh vertex; region pairs mix pln|cyl, facet|cyl, cyl|cyl.
   Pattern in the samples: the vertex at the joint is a terminal of the right chain but the WRONG end
   (e.g. rid 460 joint 2/7: chain 2653 edge ends at mv 7317 while the next chain 2717 (7563>7615)
   starts at 7615, its far end; rid 388: next chain 2264 (6990>6991) starts at 6991 while the previous
   edge ends at 6990). So a chain is traversed backwards or the loop's chain order is not a cycle --
   i.e. Loop::reversed / Loop::chainIdx (refit_chains.cpp loop extraction) or the wire assembly, not
   the analytic curves. Next: N59 dumps, per failing face, loop position -> chain, reversed flag,
   chain terminals, and each wire edge's first/last mesh vertex.

AR. **Loop stitching is consistent; the failing faces concentrate on the seam-straddle path.**
   Code (refit_chains.cpp loop stitcher): the next chain must START, in its region-side direction
   (reversed = chain.regB == region), exactly at the previous chain's end vertex, and a loop is kept
   only if it returns to its start -- so Loop::chainIdx/reversed are consistent at mesh-vertex level.
   Broken joints therefore arise in wire assembly. buildPartialCylinder's refreshOuterWire re-adds the
   outer wire's edges through BRepBuilderAPI_MakeWire when seamStraddleU(r) || nOuterCh > 6, which can
   reorder edges (and invalidates the N55 edge->chain mapping on those faces).
   Measured (off.log, first DIAG_PARTIAL_RID per rid): 28 failing -- seam straddle 14, nOuterCh>6 14,
   MakeWire-rebuild path 26; 70 built -- straddle 5, nOuterCh>6 23, rebuild path 28. Seam straddle is
   the discriminator (14/28 vs 5/70), matching the external advice to keep the patch off the seam.
   The 8 faces still failing WITH N50 (n53 DIAG_FBF): rids 242 257 388 508 522 618 819 838 -- straddle 3,
   nOuterCh>6 5, inward (outward=0) 4, one inner loop. The 20 rescued: straddle 11, nOuterCh>6 9, inward 3.
   REFUTED as discriminators for face-build failure (off.log, first attempt):
     - fitted u-range edge at the seam (|uMin| or |uMax| < 0.01): 8/8 failing, 17/20 rescued, 51/70 built
       -- the range starts at a real mesh-vertex azimuth by construction, so this is the normal case.
     - tilted end plane (ellipse edges in the wire; external question "is the terminating plane parallel
       to the section plane"): 1/8 failing, 9/20 rescued, 33/70 built -- built faces have MORE ellipse
       edges. Tilted caps do matter on another path: plane|cyl IntAna ellipses refused by the residual gate
       (fact Z: 9 on part 9, 27 on part 11) set chainEdgeFail and explode both regions.
   Edge types on the 8: 242 elips 2 + line 6; 257/388/508/522 lines only; 618/819/838 walk only 1 edge.


AS. **n57: every post-sew zero-length free edge is COLLAPSED, and ShapeFix_Shape does not close the
   shell (binary 1187644f33b5, part 9, sew partial + N52 + N54_SHAPEFIX_SMALL).**
     arm a (no N50): recover 0 free=54 zero=54 collapsed=54 -> ShapeFix_Shape facesAfter=26538 (was 26533,
       it SPLIT faces) freeAfter=34 -> not applied; recover 1 free=39 zero=39 collapsed=39 -> faces 27321
       (was 27317) freeAfter=31. FBF 28, explodes 3679/98, built cyl 0.
     arm b (+N50): recover 0 free=84 zero=59 collapsed=58; recover 1 free=65 zero=47 collapsed=46 ->
       all-zero guard blocks the repair (N58 not set). FBF 8, built cyl 0.
   Collapsed = the same vertex TShape at both ends: the external advice's dangerous case. Generic tools
   fail on it (Wireframe dropped 7/54; ShapeFix_Shape splits faces). Next n60
   (STL2STEP_N60_RESHAPE_COLLAPSED): remove each collapsed free edge through a ShapeBuild_ReShape context
   -- it is a zero-length loop in one face's wire, so its neighbours stay joined at that vertex -- then the
   same acceptance (freeAfter 0, same face count, validity). Arm a without N50, arm b with N50 + N58.

AT. **n58: ShapeFix_Shape on the MIXED residual (+N50, +N13_SEW_ORIENT, STL2STEP_N58_REPAIR_ANY) does not
   close part 9 either (binary ecc7a5a55871).** recover 0: free=84 zero=59 collapsed=58 -> faces 26363 ->
   26370, freeAfter 56, not applied; recover 1: free=65 zero=47 collapsed=46 -> faces 27173 -> 27178,
   freeAfter 47. No N13_SEW_ORIENT line (the orientation fix only runs on a sewn shell that closes). FBF 8,
   explodes 3679/98, built cylinders 0. ShapeFix_Shape both splits faces and removes only about a third of
   the free edges; the inverted rescued cylinder faces and in-face spurs (fact AP) are not repaired by it.

AU. **The broken wires collapse onto one vertex after the first chain (n59, binary 27fe785ac87b,
   N59_LOOPDUMP, part 9).** Loop order and flags are right ("flags connect to next" for all 109 positions).
   But the wire edges do not carry the chain terminals: 76 positions "wire ends != chain terminals",
   29 follow the flag, 4 opposite. Samples: rid 388 pos 0 chain 2264 first 6991 last 6990 (correct); from
   pos 1 on EVERY edge's first and last vertex resolve to mesh vertex 6990. rid 427: from pos 1 on all
   11962. rid 433: from pos 1 on all 7302. All three take the refreshOuterWire MakeWire rebuild (seam
   straddle or nOuterCh > 6). Hypothesis: BRepBuilderAPI_MakeWire::Add merges vertices whose (snap-bumped)
   tolerance spheres overlap, collapsing distinct vertices -> broken joints -> stalled walk ->
   UnorientableShape. Test n61: STL2STEP_N61_NO_MAKEWIRE skips that rebuild; part 9 without / with N50.

AV. **Removing collapsed edges through ShapeBuild_ReShape almost closes part 9 (n60d, binary
   782841947d82, sew partial + N52 + N60_RESHAPE_COLLAPSED; n60b crashed with SIGSEGV in BRepGProp on a
   collapsed edge without a 3D curve -- replaced by a null-safe curve sample).**
     arm a (no N50): recover 0 free=54 collapsed=54 removed=51 -> freeAfter 3 (faces unchanged 26533);
       recover 1 free=39 collapsed=39 removed=38 -> freeAfter 1. Shell still not accepted, FBF 28, built 0.
       For comparison ShapeFix_Wireframe on the same shells: 54 -> 47, 39 -> 38.
     arm b (N50 + N58): recover 0 free=84 collapsed=58 removed=57 -> freeAfter 27; recover 1 free=65
       collapsed=46 removed=45 -> freeAfter 20 (the real gaps of fact AP remain). FBF 8, built 0.
   The residual in arm a is exactly the collapsed edges the removal refused: their 3D curve's start, middle
   and end are not within 1e-4 mm. Next n62: remove a collapsed free edge when its whole curve lies inside
   its vertex's tolerance sphere (extent <= max(1e-4, BRep_Tool::Tolerance(vertex))) -- geometrically part of
   the vertex, no tolerance widened -- and log every collapsed edge still kept (type, extent, vertex tol).

AW. **ROOT CAUSE of the 28 failing partial cylinders: the refreshOuterWire BRepBuilderAPI_MakeWire rebuild.
   Skipping it (STL2STEP_N61_NO_MAKEWIRE) takes failed cylinder face builds 28 -> 1 on part 9 (binary
   24ccab61b7a6, base flags + DIAG_FBF + N51_WIREJOIN).**
     arm a (N61): DIAG_FBF type=1 = 1; faces with broken joints: 0 (failed 0 of 1, others 0 of 97).
       J6 freeEdges 654 (recover 0) -> 139 (recover 1); explodes 3679/98; built cylinders 0 (no sewing flags).
     arm b (N61 + N50): DIAG_FBF = 1; broken joints 0; freeEdges 659 -> 188; built 0.
   Mechanism (fact AU): refreshOuterWire re-adds the outer wire's edges through MakeWire when
   seamStraddleU(r) || nOuterCh > 6; MakeWire::Add merges vertices whose tolerance spheres overlap, so on the
   broken faces every edge after the first chain collapsed onto one vertex -> broken joints -> stalled walk
   -> UnorientableShape on every attempt. With the rebuild skipped, N50 no longer changes the count.
   Closure is now the only blocker: next n63 = N61 + N13_SEW_FREE + N48 + N60 + N62 (+ J6_DIAG census).

AX. **n62: judging collapsed edges against their own vertex tolerance CLOSES part 9's sewn shell, but the
   closed shell is invalid (binary e140272e6e17, sew partial + N52 + N60 + N62_VTX_TOL, no N61).**
     arm a (no N50): every recover pass -> collapsed free edges all removed, freeAfter 0, applied=1, same face
       count: recover 0 54/54, recover 1 43/43, recover 2 41/41, recover 3 32/32; N62_KEEP none. N27_FIXFACE at
       recover 3 reports closed=1 valid=0. Explodes: 98 cylinders, 0 planes (the cascade now removes cylinders
       one by one instead of blanket-exploding everything); RESULT smoothRevertedTrue=1, smoothCylinders 0.
     arm b (+N50, N58): real gaps remain -> freeAfter 26 / 19; unchanged blanket; built 0.
   Closure is solved by collapsed-edge removal; VALIDITY of the closed shell is the next blocker. This run
   still contains the 28 wire-broken faces (no N61); n63 (N61 + closure set) shows the shell without them.

AY. **n63: wire fix + closure set CLOSES part 9 on every pass; validity is the last blocker (binary
   e140272e6e17, N61 + N13_SEW_FREE + N48 + N52 + N60 + N62_VTX_TOL).**
     DIAG_FBF type=1 = 1. Per recover pass: sew freeE 654 / 542 / 514 / 346 -> 0 with N60 removing 61 / 55 / 55 /
     36 collapsed edges, N13_SEW closed=1 accepted=1 (face count unchanged); last pass N27_FIXFACE closed=1
     valid=0 and a final sew freeE=8->18. Explodes: 98 cylinders, 0 planes; RESULT smoothRevertedTrue=1,
     smoothBuiltCylinders 0.
   The closed shell is accepted as closed (N13_SEW_STRICT unset) but fails validity downstream, and the cascade
   then removes the cylinders one by one. Next n65: N64_VALID_DIAG + N13_SEW_WHY on the same flags -- BRepCheck
   face/edge status tally per surface type on the closed shell.

AZ. **The closed part-9 shell is invalid because of PLANE faces, not cylinders -- yet the cascade explodes the
   cylinders (n65, binary 0580f978a399, n63 flags + N64_VALID_DIAG + N13_SEW_WHY).** Status tally on the
   reshape-closed shell, per surface type (face status / edge-in-face status):
     recover 0: 86 bad faces -- plane face27 UnorientableShape 70, plane face32 BadOrientationOfSubshape 14,
       plane face23 InvalidImbricationOfWires 1, plane edge8 InvalidCurveOnSurface 1, cylinder face27 1.
     recover 1: 69 -- plane 27: 55, 32: 12, 23: 1, edge8 1; cylinder 27: 1.
     recover 2: 66 -- plane 27: 54, 32: 11, 23: 1, edge8 1; cylinder 0.
     recover 3: 37 -- plane 27: 30, 32: 7, edge8 1; cylinder 0.
   Sewn shell before reshape (N13_SEW_WHY): 263 x27, 45 x32, 3 x23. FBF 1; explodes 98 cylinders, 0 planes;
   reverted. So the culprit cascade removes healthy cylinders as victims while the invalid plane faces stay;
   the bad-plane count falls only because exploding a cylinder rebuilds its neighbours.
   Two directions: (1) point the closed-but-invalid cascade at the regions that own invalid faces (planes
   become facets, cylinders stay) -- the external advice's per-region fallback; (2) find why those plane
   faces are unorientable (likely the same wire-assembly class as the cylinders, fact AW).

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
