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

BA. **Why the closed-but-invalid cascade kills cylinders when planes are the culprits (code,
   refit_build.cpp).** Site B (closed && !shValid) collects culprits correctly (collectFaceCulprits: regions whose
   own face is invalid; collectShellCulprits: owners of bad faces/wires/edges), then cascadeLadderPlan:
     U0 = selectU0Explode(): face-invalid CYLINDERS first, PLUS every cylinder touching >= 2 invalid non-hub
       planes ("join-suspect"); invalid non-hub planes only if that cylinder list is empty; planes touching a
       seamed closed360 hole are unexplodable; at most 2 U0 rounds.
     U1 = cylinderOneHop() of every culprit (the cylinder neighbours).
     U2 = u2BlanketRids(): every non-closed360 analytic region.
   With ~70 invalid planes on part 9 nearly every cylinder is a join-suspect, so the cylinders go first.
   wouldSaturate() counts only cylinders (50% cap). Test n67 (STL2STEP_N67_PLANE_CULPRITS_FIRST): U0 returns the
   invalid non-hub planes first without join-suspect recruitment, and plane-only U0 sets get up to 12 rounds.

BB. **n66: part 11 with the wire fix + closure set nearly closes but not quite (binary 0580f978a399, N61 + sew free +
   N48 + N52 + N60 + N62_VTX_TOL + N64 diag + N29_ARCH_MAXTRI=200000 + N22_NOQUORUM).**
     recover 0: sew 46 -> 18 kept; reshape removes 9 of 9 collapsed -> 9 real free edges remain (not applied).
     recover 1: sew 17 -> 13; removes 8 of 8 collapsed -> 5 real free edges remain.
     DIAG_FBF type=1 = 3; J6 not closed 18 / 13; explodes 1487 planes / 34 cylinders; smoothCylinders 6,
     built 0, adoptedNoCyl 1.
   Part 11 does not reach the closed-but-invalid stage; its blocker is 5-9 real gaps. n68 lists them (J6_DIAG).

BC. **n67: exploding invalid planes first (STL2STEP_N67_PLANE_CULPRITS_FIRST) drains the invalid faces from 86 to 4
   but the last 4 planes are never selected, and the ladder then takes all 98 cylinders (binary 5295b17e91f2, n63
   flags + N64 diag).**
     recover 0: 86 bad (plane 27: 70, 32: 14, 23: 1, edge8 1; cylinder 27: 1) -> N67_U0 planes=80.
     recover 1: 14 bad (plane 27: 13, cylinder 27: 1) -> N67_U0 planes=9.
     recover 2: 6 bad (plane 27: 6) -> N67_U0 planes=2.
     recover 3: 4 bad (plane 27: 4) -> no N67_U0 line: selectU0Explode had no explodable non-hub plane left.
     Each pass the reshape still closes the shell (collapsed 61 / 40 / 39 / 39 removed, freeAfter 0).
     Explodes: planes 91, cylinders 98; reverted; built cylinders 0.
   The remaining 4 invalid planes are skipped by selectU0Explode (touchesClosed360Cyl -> "unexplodable", or hub);
   with an empty plane set the ladder falls to the cylinder paths (join-suspect / U1 / U2). Next n69: log each
   skipped culprit and its reason; STL2STEP_N69_ALLOW_SEAMED lets planes touching a seamed hole be exploded.

BD. **Part 11's residual gap is ONE plane fitted 0.17-0.19 mm off its neighbours (n68, binary 0580f978a399, n66 flags
   + J6_DIAG).** After the kept sew and collapsed-edge removal:
     recover 0: 18 free = 10 zero-length + 8 real: cylinder 12 <-> plane 634 (0.692 mm, offset 0.174); plane 424 <->
       cylinder 83 (58.4 mm, offset 0.194); plane 634 <-> facet (18.87 mm, offset 0.174); a 0.174 mm and a 0.194 mm
       facet step edge. All real pairs are "reversed" (correctly oriented), just over the 0.1 mm sew tolerance.
     recover 1: 13 free = 8 zero-length + 5 real, ALL around plane 634: cyl 12 <-> pln 634 0.692 mm @0.174,
       pln 634 <-> facet 18.87 mm @0.174, and the 0.174 mm facet step.
   Exploding plane 634 to facets would close the shell. It is not selected: the targeted open-shell arm skips a
   free-edge owner that borders an exploded or partial cylinder (the v1.8.0 N27 victim skip), the same class of
   protection that leaves part 9's last 4 invalid planes unexploded (fact BC). Widening the sew tolerance to 0.2
   would also close it but is not an acceptable fix.
   Code (refit_build.cpp, n13Targeted arm in the open-shell recovery): for each region owning a free edge, it is a
   "victim" and skipped if ANY chain neighbour is a cylinder that is exploded OR partial (!closed360). Plane 634 borders
   partial cylinder 12 -> skipped; with did=false the else-branch then explodes every non-closed360 cylinder. The rule's
   premise ("the edge went free because the neighbour cylinder was removed") holds only for an EXPLODED neighbour;
   for a built partial neighbour the gap here is the plane's own 0.174 mm offset. Test n70
   (STL2STEP_N70_VICTIM_EXPLODED_ONLY): victim only when the neighbouring cylinder is exploded.

BE. **n69: the last 4 invalid faces on part 9 are NOT region faces -- the culprit set is empty, so U0 is empty and the
   U2 blanket fires (binary afb4d2dc0e0d, n67 flags + N69 skip log + N24_DIAG).** Both arms (with and without
   STL2STEP_N69_ALLOW_SEAMED) are identical: recover 0-2 drain as in n67 (86 -> 14 -> 6 -> 4, all plane face27 at
   the end); recover 3 "N69_LADDER u0=0 satU0=0 u0Rounds=3 culprits=0 -> leaving U0", "N24_U2_REACHED blanket=97
   cyls=98 exploded=1 sat=1"; no N69_SKIP line at all (no plane was skipped by the closed360/hub rules -- the
   seamed-hole hypothesis of fact BC is REFUTED). Explodes 91 planes / 98 cylinders; reverted.
   N64 counts surface type through BRepAdaptor, so facet triangles (builtRid < 0, from exploded regions) report as
   "plane". collectFaceCulprits and collectShellCulprits skip rid < 0, so an invalid facet yields no culprit -- the
   exact case the ported STL2STEP_N14_NONREGION (collectNonRegionNeighbourhood) targets. It was refuted earlier in a
   different state (shell never closed); site B is only reachable now. n71: n67 flags + N14_NONREGION.

BF. **n70: the exploded-only victim rule (STL2STEP_N70_VICTIM_EXPLODED_ONLY) makes the targeted arm act on part 11, but
   the shell still does not close (binary 5ba69e52207d, n66 flags + N67 + N70).**
     recover 0: sew 46 -> 18 kept; reshape removes 9 collapsed -> 9 real; N13_TARGETED freeE=18 regions=5 ->
       N70_TARGET exploded rid 12 (CYLINDER), 424, 634, 1361 (planes); 1381 still a victim (its cylinder was exploded).
     recover 1: free 9 before sew; sew 9 -> 13 (worse, NOT kept); reshape removes 8 of 13 collapsed -> 5 real remain.
     DIAG_FBF 3; explodes 1487 planes / 34 cylinders (blanket); smoothBuiltCylinders 0.
   Plane 634 is now exploded, but cylinder 12 (a free-edge owner) goes with it, and the rebuild creates 5 new real gaps.
   n72 lists those 5 (J6_DIAG) before choosing the next change.

BG. **n71: N14_NONREGION + plane-first makes part 9's closed shell VALID with 97 cylinders still in it -- then the component
   reverts at a later gate (binary afb4d2dc0e0d, n67 flags + N14_NONREGION).**
     recover 0: 86 bad -> N67_U0 planes=86; recover 1: 11 bad (plane 27: 10, cylinder 27: 1) -> planes=10;
     recover 2: 2 bad (plane 27: 2) -> planes=2; recover 3: N60_RESHAPE_COLLAPSED removed 39 -> freeAfter 0, VALID=1
       (N13_SEW freeE=362->0 closed=1 accepted=1).
     Explodes: 98 planes, 1 cylinder (no blanket). Yet RESULT: smoothRevertedTrue=1, smoothBuiltCylinders 0,
     "analytic rebuild reverted on one component -- kept faceted"; STEP has 0 CYLINDRICAL_SURFACE.
   The revert cause is not in RESULT (revCause -> out.revertCause, stl2step.cpp ~1062). Candidates after a closed valid
   shell: the closed-valid residual detector branch (RULE 2.2-2.4) or the stl2step.cpp gates (shell-not-closed,
   brepcheck-invalid on the full analyzer, volume budget dV). n73 reruns with STL2STEP_DIAG_REVERT + DIAG_PLAN.

BH. **n72: part 11's 0.174 mm gap survives exploding BOTH owners -- it is vertex displacement, not a fit offset (binary
   5ba69e52207d, n70 flags + J6_DIAG). Part 11 PARKED in favour of part 9.**
     recover 0: DIAG_EXPLODE rid 12 (cylinder R 15.87), 424, 634, 1361 right after N70_TARGET (log lines 1084-1091).
     recover 1 J6 census (before sew): 9 free edges, still "owned" by 12 and 634 with the same 0.692 / 18.868 / 0.174 mm
       geometry at 0.174 mm offset, plus a new sliver around plane 1510 (0.004-0.010 mm edges); sew 9 -> 13 (not kept).
   Code: refit_build.cpp:5971 `builtRid.push_back(exp ? rid : -1)` -- facet faces of an EXPLODED region keep its rid, so
   those owners are the facet triangles that replaced 12 and 634. Their mesh vertices still sit 0.174 mm from the
   neighbours' boundary, so the gap comes from shared vertex TShapes being moved by snapping (the meshTolCap / P44
   "two distinct mesh vertices confused into one TVertex" class), not from plane 634's fit (maxVertexDev 0.0149).
   Next step for part 11 (later): trace which snap moves those vertices. Part 9 is one gate from shipping (n73).

BI. **n73: part 9 now passes closure AND BRepCheck with 97 cylinders; it reverts only on the volume budget (binary
   afb4d2dc0e0d, n71 flags + DIAG_REVERT + DIAG_PLAN).** DIAG_REVERT comp=37223 decision=REVERT builtFaces=28200
   builtCyl=97 builtPl=28103 regions=3777 firstFail=t4_volumeBudget: t1 bfReturnedAndNonEmpty=1, t2 shellIsClosed=1,
   t3 brepCheckIsValid=1, t4 volumeBudget=0. shellVol 96169.0163 vs meshVol 97838.6286 -> dV 1669.61 mm3 (1.71%);
   budget 97.84 (= N27_T4_REL 0.001 x meshVol; term A 1e-4 x meshVol 9.78, term B 3 x dVolAbs 46.77, dVolAbs 15.59).
   N17 round-trip volume returned garbage (rtv 2.7e173), so the round-trip rescue cannot apply.
   Raising the budget is forbidden (tolerance widened to pass a gate). A 1.7% shortfall on a closed valid shell is either
   real missing volume or faces counted with the wrong sign; existing switch STL2STEP_N16_ORIENT_T4 measures with
   orientation. n75 reruns with it and keeps the STEP to check its independently re-read volume and cylinder count.
   Code (stl2step.cpp:281 roundTripVolume): wraps the probe shell in a solid, writes it with STEPControl_Writer, reads it
   back and returns fabs(shapeVolume(back)). A returned volume of 2.7e173 means the volume integration of the RE-READ shape
   diverged -- a numerically broken face after transfer (absurd surface/pcurve bounds or tolerances), not a small error.
   The same face could also be what pulls the in-memory volume 1.7% low. If N16 does not resolve t4, the next probe is a
   per-face signed volume/area census on the probe shell to find the anomalous faces.

BJ. **n74: the combined fix set is neutral on the live-release regression parts (binary afb4d2dc0e0d).** live flags vs
   live + N61 + N13_SEW_FREE + N48 + N52 + N60 + N62_VTX_TOL + N67 + N14_NONREGION:
     part 8:  live cyl 2 / built 2 -> new 2 / 2;  part 15: live smoothCylinders 5 built 1 -> new 5 / 1;
     part 22: live 3 / 3 -> new 3 / 3. All six runs: crashed 0, solids 1, watertight, volumeDeltaPct 0.
   No crash and no lost cylinder on the parts v1.8.0 was validated against. Corpus gate still to run once part 9 ships.

BK. **n75: orientation-aware volume (STL2STEP_N16_ORIENT_T4) gives the SAME shell volume on part 9 -- not a sign error; the
   1669.6 mm3 shortfall is real (binary afb4d2dc0e0d, n71 flags + DIAG_REVERT + N16_ORIENT_T4).** decision=REVERT builtCyl 97
   builtPl 28103 firstFail t4_volumeBudget, t1-t3 = 1, shellVol 96169.0163 (identical to n73), meshVol 97838.6286, budget 97.84.
   Hypothesis (to measure, not assume): expected tessellation sagitta. Coarse cylinders on part 9 have nSides 13-16 and
   chordSag 0.19-0.29 mm (DIAG_FBF rows); facets lie inside the true arc, so for holes/concave fillets (material outside) the
   analytic surface removes material the chordal mesh kept. Rough size: ~340 mm2 x ~0.17 mm x ~30 coarse cylinders ~ 1.7e3 mm3.
   The budget's predicted term uses dVolAbs 15.59 (term B 46.8), so it may not model chord sagitta at all. Next n78: per
   cylinder region, sum over its mesh triangles of area x radial deviation of the triangle centroid from the fitted cylinder,
   signed by outwardNormal -- compare the total with dV 1669.6. If it matches, the fix is the prediction, not the tolerance.

BL. **n77 per-face volume census is INVALID (probe bug), but its areas refute the sagitta hypothesis (binary b766089a6967).**
   The probe called BRepGProp::VolumeProperties(face, props, OnlyClosed=Standard_True); a single face is never closed, so every
   face volume is 0 (sumVol 0 for both types, every TOP row vol=0). Areas are valid: cylinder faces sumArea 288.6891 mm2 (97
   faces), plane faces 22355.6453 mm2. With only 289 mm2 of cylinder surface, chord sagitta (<= ~0.3 mm) can account for at most
   ~87 mm3 -- not the 1669.6 mm3 shortfall, so fact BK's tessellation-sagitta explanation is implausible (n78b measures it
   exactly). (The job's exit=1 is the trailing `grep N76_FACEVOL threw` finding nothing, not a failure.)
   Next n79: fixed-origin signed volume, GProp_GProps(O) + VolumeProperties(face, OnlyClosed=false), grouped as cylinder faces /
   analytic plane faces / 3-edge facet faces, against the mesh triangles' signed volume about the same O grouped by region
   (built cylinder / built plane / exploded-or-island) -- the class whose face and mesh volumes differ holds the shortfall.

BM. **n78b REFUTES tessellation sagitta as the source of part 9's volume shortfall (binary 766d3a8823d9, n71 flags +
   DIAG_REVERT + N78_SAGVOL).** Over all 98 cylinder regions, sum of (triangle area x radial deviation of the centroid below R),
   signed by outwardNormal: bosses 71 (+141.2126 mm3), holes 27 (32.6471 mm3, i.e. -32.6), predictedSigned +108.5654,
   predictedAbs 173.8597. Observed shell - mesh = -1669.6123. Wrong sign and ~15x too small: the cylinder faces do not
   explain the missing volume. n79 (fixed-origin signed volume per face class vs per mesh-region class) locates it.

BN. **n79: cylinder FACES cover 61% more area than their mesh regions on part 9 (binary 2bad84b24589, n71 flags +
   N79_CLASSVOL).** Per-face volume about a fixed origin is again unusable (faceVolSum 739.9 vs shellVol 96169.0: plane
   -0.16, facet3 0.72, cylinder 739.4), but the mesh side sums exactly (97838.6286) and the AREAS are valid:
     shell faces: cylinder 288.6891 mm2, facet3 9168.4437, plane 13187.2016 (total 22644.3)
     mesh tris:   cylinder regions 179.8338, exploded 7324.4267 + island 1850.0489 (9174.5), plane 13216.2595 (total 22570.5)
   Plane faces -29 mm2 and facets -6 mm2 vs their mesh, but cylinder faces +109 mm2 (+61%). Hypothesis (unmeasured): some
   partial cylinder faces are trimmed on the COMPLEMENTARY arc (2pi - span) -- a boss built that way becomes a dent and
   removes material, which could produce a loss of this size. Next n80: at each accepted partial cylinder face, log rid,
   face area vs region mesh area, span, R, outwardNormal and the winning attempt tag.

BO. **n80: three rot-trim partial cylinder faces are built far larger than their regions -- the likely source of part 9's
   volume loss (binary 308e69ded0e9, n71 flags + N80_PCYLAREA).** 97 accepted faces (last build per region), faceArea sum
   293.882 vs meshArea 179.834. Classification against R x span x vH vs R x (2pi - span) x vH: 92 match the fitted span,
   5 have no area -- the COMPLEMENT-ARC hypothesis of fact BN is REFUTED. Ratio face/mesh: <=1.1 84, <=1.5 8, <=3 2, >3 3.
   The three outliers, all tag rot-trim/fwd, outward 1:
     rid 445 R 10.11 span 1.889 vH 10.08: face 128.17 mm2 vs mesh 1.92 (66.7x); trim rectangle R*span*vH 192.63
     rid 838 R 3.25 span 1.634 vH 2.29:   face 14.77 vs mesh 0.97 (15.3x); rectangle 12.15
     rid 388 R 9.65 span 2.099 vH 9.65:   face 16.87 vs mesh 2.14 (7.9x); rectangle 195.51
   These regions are narrow strips of a few triangles whose fitted u/v box is large; the rot-trim attempt (MakeFace on a
   Geom_RectangularTrimmedSurface) produced a face covering most of the trim rectangle instead of the small wire -- a spurious
   curved sheet inside the part. rot-trim is exactly the path with the trimmed-surface rotation bug fixed by N50_TRIMROT
   (fact AL), which is NOT in the current flag set. n81 adds STL2STEP_N50_TRIMROT and re-measures the three faces and t4.

BP. **USER DIRECTIVE (2026-09-13): shape recognition over exact volume.** "our goal is not having exact volume. our goal is to
   reconstruct a shape. you must prioritize 2d or 3d shapes. once we have a valid 3d brep, getting exact measures is trivial."
   Consequences: (1) the t4 volume budget must not discard a closed, BRepCheck-valid analytic B-rep -- n82
   (STL2STEP_N82_T4_ADVISORY) logs the mismatch and keeps the shell when t2 and t3 already passed; closure and validity stay
   mandatory. (2) A large volume gap is still investigated when it reveals a SHAPE defect: part 9's three rot-trim faces built
   up to 67x their regions (fact BO) are malformed surfaces and get fixed (n81 tests N50_TRIMROT). Saved as auto-memory
   feedback_shape_over_volume.

BQ. **First STEP of part 9 carrying cylinders -- 97 CYLINDRICAL_SURFACE -- but the written B-rep is INVALID (n82, binary
   4f0a342c6522, n71 flags + DIAG_REVERT + N82_T4_ADVISORY).** N82_T4_ADVISORY kept the shell (dV 1669.6, budget 97.8,
   rtv 2.7e167); DIAG_REVERT decision=KEEP builtCyl 97 builtPl 28103, t1-t4 = 1. Post-build pipeline: unify 28,200 -> 27,255
   faces, "check INVALID (ran during write)", warning "smooth: B-Rep invalid after build -- no ShapeFix rewrite on smooth runs",
   B-Rep volume 96168.833; STEP 75.7 MB written with 97 CYLINDRICAL_SURFACE / 27,255 ADVANCED_FACE; verify re-read 27,282
   faces with a garbage volume (2.8e167 %). So the in-memory shell passed BRepCheck (t3) but the unified/written shape does not;
   the three oversized rot-trim faces (fact BO) are still in it. Kept file: scratchpad/n19/n82_9.keep.step; n83 checks it with
   FreeCAD (invalid faces by surface type and area).
   **n81 (+N50_TRIMROT, no N82): the three faces are fixed but face building gives up (binary 308e69ded0e9).** N80 ratios rid 445
   0.979, 838 1.058, 388 0.989 (face area sum 164.8 vs mesh 179.8; all 97 within 1.5x). DIAG_REVERT decision=REVERT builtFaces=0
   firstFail=t1_bfReturnedAndNonEmpty, cause "buildFaces-false exit=none line=7055 regions=3777". N50 changes the recovery flow
   enough that buildFaces returns false. refit_build.cpp:7055 is the site-B discard: the shell is CLOSED but invalid and
   `if (plan.hostR2 || cascadeSt.u2Done || !shValid) { ... restoreShared(); out.clear(); return false; }` -- the culprit
   ladder was exhausted without making it valid. n84 reruns with N50 + N82 + N64_VALID_DIAG + N67/N24 ladder diagnostics.

BR. **The 97-cylinder STEP breaks in the write/read round trip, on its cylinder trims (n83b: FreeCAD re-read of
   scratchpad/n19/n82_9.keep.step).** Re-read: 1 Solid, isValid False, 27,282 faces = 27,182 Plane + 100 Cylinder (97 written).
   INVALID: 7 cylinder faces (area 5941.4 mm2 in total) and 120 plane faces (4116.2 mm2). Cylinder face areas after re-read:
   6038.2, 3821.3, 981.4, 695.3, 450.0, 69.5, 28.3, 14.3 ... and negative-area (inverted) faces (-7.02, -3.06); in memory the
   cylinder faces totalled ~294 mm2 and their mesh regions 180 mm2. So some cylinder faces lose their trimming on export and
   re-import spanning large parts of the full cylinder -- which also explains the garbage round-trip volumes (rtv 2.7e167).
   n82 did not have N50_TRIMROT: its rot-trim faces carry pcurves in the wrong frame on a Geom_RectangularTrimmedSurface; OCCT
   tolerates that in memory, but STEP stores the basis surface + pcurves and the trim re-reads wrong (the external advice:
   never hand the builder a trimmed surface). n84 = N50 + N82 is running; fallback built next as STL2STEP_N85_NO_RECTTRIM
   (rot-trim attempt on the untrimmed rotated Geom_CylindricalSurface).

BS. **n84: with N50_TRIMROT the last closed-but-invalid culprit on part 9 is ONE cylinder face, and the U0 round limit sends
   the ladder to the blanket (binary 4f0a342c6522, n71 flags + N50 + N82 + N64/N67/N24 diagnostics).** N67_U0 planes 84
   (faceInvalidCyls 2) -> 9 (2) -> 3 (1); then "N69_LADDER u0=1 satU0=0 u0Rounds=3 culprits=1 -> leaving U0",
   "N24_U2_REACHED blanket=97 cyls=98 exploded=1 sat=1"; explodes 96 planes / 98 cylinders; buildFaces-false (t1=0); STEP
   0 cylinders (valid faceted fallback). The N67 extra rounds (12) apply only when u0 is all planes; a lone face-invalid
   cylinder gets the default 2 rounds, so the ladder escalates U1 -> U2 and destroys every partial cylinder to remove one.
   Next n87 (STL2STEP_N87_U0_ANYTYPE): allow up to 12 U0 rounds for any region type while the set does not saturate
   (wouldSaturate still guards) -- the per-region fallback of the external advice.

BT. **n86: STL2STEP_N85_NO_RECTTRIM (rot-trim on the untrimmed rotated cylinder) changes nothing in memory on part 9 (binary
   a79b0f517297, n84 flags + N85).** Identical to n84: N67_U0 planes 84 -> 9 -> 3, then one face-invalid cylinder,
   N69_LADDER u0=1 u0Rounds=3 -> leaving U0, N24_U2_REACHED blanket=97 sat=1, explodes 96 planes / 98 cylinders, t1=0,
   STEP 0 cylinders (valid faceted). N85 is aimed at the write/re-read trim failure of fact BR, which only matters once a
   STEP with cylinders is written; the in-memory blocker is the U0 round limit (n87 running with N87_U0_ANYTYPE).

BU. **n87: STL2STEP_N87_U0_ANYTYPE stops the ladder from blanketing -- part 9 keeps 96 cylinders -- but the kept shape is wrong
   (binary 433a984bb1e0, n84 flags + N87).** N67_U0 planes 84 -> 9 -> 3; explodes 96 planes / 2 cylinders; DIAG_REVERT
   decision=KEEP builtCyl 96 builtPl 28121, t1-t3 = 1; N82 advisory: shellVol 207794.07 vs mesh 97838.63 (2.1x), rtv 1.08e168.
   Write: "check INVALID", STEP 96 CYLINDRICAL_SURFACE, verify volume garbage. FreeCAD re-read: 1 Solid isValid False, 28,221
   faces (96 Cylinder), INVALID 8 cylinder faces (11286.8 mm2 total; 837.6, 449.9, 694.7, 430.6, 3912.5, 1141.4, 3819.0 ...)
   and 24 plane faces (2657.4 mm2, including -374.2 and -0.73 negative areas). All cylinder mesh regions total 180 mm2, so these
   faces have lost their trim and span large parts of the full cylinder -- already in memory (volume doubled), while in-memory
   BRepCheck still passes. The cylinder trim is the core shape defect even with N50. n88 tests N85_NO_RECTTRIM on top; fallback
   n89 (STL2STEP_N89_AREA_GUARD): reject a partial cylinder face whose area exceeds 3x its mesh region (shape consistency, not
   volume) so the region becomes facets instead of a wrong surface.

BV. **n88: adding STL2STEP_N85_NO_RECTTRIM to the n87 configuration changes NOTHING (binary 433a984bb1e0).** Bit-identical to n87:
   shellVol 207794.0694, explodes 96 planes / 2 cylinders, KEEP builtCyl 96, write "check INVALID", STEP 96 cylinders; FreeCAD
   re-read identical (8 invalid cylinder faces 11286.8 mm2 with the same areas 837.6 / 449.9 / 694.7 / 430.6 / 3912.5 / 1141.4 /
   3819.0, 24 invalid planes 2657.4 mm2). So the oversized cylinder faces in the kept shell are NOT produced by the rot-trim
   RectangularTrimmedSurface path (or that path yields the same face either way). They may come from another attempt
   (untrim / rect-trim / rot-ax / seam-box) or from the closed360 builders (trySeamed360 / tryTwoHalves), which the n89 area
   guard -- partial cylinders only -- would not cover. n90 (N89 area guard) is running and will show which.

BW. **n90: the partial-cylinder area guard (STL2STEP_N89_AREA_GUARD, 3x mesh region) rejects NOTHING on part 9 and the result is
   bit-identical to n87/n88 (binary 3479a90dc1bf).** "area guard rejections: 0"; shellVol 207794.0694; KEEP builtCyl 96; FreeCAD
   re-read with the same 8 invalid cylinder faces (837.6 / 449.9 / 694.7 / 430.6 / 3912.5 / 1141.4 / 3819.0 mm2). So every partial
   cylinder face is within 3x its mesh region WHEN buildPartialCylinder accepts it: the oversized faces either come from the
   closed360 builders (trySeamed360 / tryTwoHalves; n91 logs every built cylinder face with builtAs) or are corrupted AFTER build --
   sewing, or N60 collapsed-edge removal through ShapeBuild_ReShape, which could break a cylinder wire's pcurve continuity so the
   face loses its trim. n92 measures cylinder face areas on the final accepted shell to compare with the at-build areas.

BX. **n91: every cylinder face is correct AT BUILD on part 9 -- the oversized faces appear after the build (binary 0960ba96a9ab,
   n87 flags + N91_FACEAREA, hook after every builtRid.push_back).** 97 cylinder regions built, builtAs Single 97 (no
   Seamed360 / TwoHalves), faces > 3x mesh area: 0, total face area 164.79 vs mesh 179.83. So neither buildPartialCylinder nor
   the closed360 builders produce the 430-5816 mm2 faces seen after re-read (fact BU). They are created later inside buildFaces --
   sewing, N27 ShapeFix_Face, or N60 collapsed-edge removal via ShapeBuild_ReShape -- since the in-memory probe volume at t4 is
   already 207794 mm3. Prime suspect N60: removing a collapsed edge from a cylinder wire can break its pcurve continuity so the
   face loses its trim. n92 compares final-shell cylinder areas with build areas; fallback built as STL2STEP_N93_RESHAPE_SKIP_CYL
   (N60 removes collapsed edges only from non-cylindrical faces).

BY. **n92: cylinder faces are still correct on the FINAL accepted shell inside buildFaces (binary dc0b3f3feca9, n87 flags + N91 +
   N92_FINALAREA).** At build 97 faces, on the final shell (entry of the closed-and-valid branch) 96 faces; total face area 163.56
   vs mesh 177.89; faces that grew >3x between build and final shell: 0; faces >3x at build: 0. So sewing, N27 ShapeFix_Face and
   N60 collapsed-edge removal do NOT inflate face areas. Yet stl2step.cpp's t4 probe volume on the returned faces is 207794 mm3 and
   the STEP re-read shows 430-5816 mm2 cylinder faces. The defect is therefore in how the faces are represented, not in their
   in-memory area: prime suspect the cylinder SEAM. cylSurfaceForRegion rotates X to uMin, so every partial patch starts exactly at
   u = 0 and pcurves can carry negative u; a STEP reader rebuilds boundaries into [0, 2pi) and a wire on the seam can be read as the
   complementary face. External advice: keep the patch away from the periodic seam. Candidate test: rotate X to (theta_mid - pi) so
   U stays in [pi - span/2, pi + span/2].

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

## BZ — n94: skipping collapsed-edge reshape on cylinder faces changes nothing (2026-09-13)
N93_RESHAPE_SKIP_CYL=1 on the best config gives the same result: KEEP, 96 cylinders, shellVol 207794 (2.1x the mesh), and on FreeCAD re-read 8 invalid cylinder faces plus 24 invalid planes, with identical areas. Refuted. Next: n95 (N16_ORIENT_T4, still running), then n96 (binary 8ded569fd67e, STL2STEP_N96_SEAM_AWAY: frame X rotated to theta_mid-pi so patches avoid u=0), built but not run.

## CA — n95: orientation-aware volume identical (2026-09-13)
STL2STEP_N16_ORIENT_T4 is reached (stl2step.cpp:1009 selects orientedShapeVolume, which runs ShapeFix_Shell::FixFaceOrientation and an inside-out check). shellVol is still 207794.07, the same to the digit. Inverted faces are refuted as the cause of the 2.1x volume (caveat: the function returns early when the probe is not a TopAbs_SHELL). The remaining lead is the seam hypothesis; n96 (SEAM_AWAY) is running.

## CB — n96: moving the partial-cylinder seam mid-period makes it worse (2026-09-13)
STL2STEP_N96_SEAM_AWAY=1 (binary 8ded569fd67e) on the best config: t1 fails (bfReturnedAndNonEmpty=0), decision REVERT, 0 cylinders in the STEP. N24_U2 exploded=4 of 98 cylinders. The seam at u=0 is not what makes the round-trip invalid, and rotating the frame breaks face building. Refuted and not to be enabled. Round-trip invalidity now has three refuted attempts (n94 reshape skip, n95 orientation, n96 seam), so per Rule 8 it goes to a second opinion (Kimi) before any further fix.

## CC — Kimi second opinion: two separate defects, one of them proven in the STEP file (2026-09-13)
Findings: scratchpad n19/kimi_roundtrip.findings.md. Checked against the code before accepting.
- D2 (verified): in the n94 STEP, 58 of 96 cylinder faces have outer-wire pcurve u-spans > 6 rad, up to 14.29 rad (about 2.3 turns), so on re-read a 1-4 mm2 patch bounds nearly the whole cylinder (the 5,816 mm2 face and the garbage round-trip volume). Source: in bindCylPCurves (refit_build.cpp:2825) any edge that is not linear on the cylinder goes to addPcurvesOnSurface (ShapeFix FixAddPCurve projection), which has no u-unwrap; unwrapU (:2815) only covers the linear path. In memory the faces look right because the edge ranges carry them.
- D1 (hypothesis, being attributed): the 2.1x in-memory volume comes from faces whose outer wire winds clockwise about their own normal (FreeCAD shows plane areas of -374 and -0.73). BRepCheck, ShapeFix_Shell orientation and a global flip cannot see this. Candidates: the want/other pick (refit_build.cpp:3380), which flips the flag against outwardNormal when only that orientation validates; the MakeFace Inside=true fallbacks; and the fallback inner loops that skip orientInnerAgainstOuter.
- Proposed fixes: F2 unwrap projected pcurves (D2 root cause); F1 UV-span audit; F3 new acceptance t5 on per-face signed area (closes the t3 blind spot); F4 repair chosen by attribution.
Running now: n97d, the same binary with only diagnostic flags added (N79_CLASSVOL N76_FACEVOL N78_SAGVOL N5F_UV), to attribute D1.

## CD — FreeCAD u-span probe on the n94 STEP: 8 wrapped faces, not 58, and they are exactly the 8 invalid ones (2026-09-13)
Script n19/uvprobe.py (FreeCAD ParameterRange on every re-read cylinder face). 8 of 96 cylinder faces have u-span >= 2*pi (14.54, 13.37, 12.57, 7.64, 7.18, 6.285, 6.285, 6.283 rad). They include all 8 invalid cylinders plus the 5,816 mm2 face (idx 457, which reads as valid). Every one of them has 2-6 edges that are 3D ellipses (plane-cylinder cuts at an angle); the sane faces (u-span about 2 rad) have almost only 3D lines. Kimi's count of 58 is not confirmed. What the probe does support is that the ellipse edges are involved: in bindCylPCurves those edges take the ShapeFix projection branch (refit_build.cpp:2825), not the unwrapped Geom2d_Line branch. Pcurve types in the re-read are not informative (the writer emits every pcurve as a B-spline). Still open: whether the wrap already exists in memory or appears at write/read. In-memory N92 areas look sane, which points to write/read, but no in-memory UV bounds have been measured yet.

## CE — n97d attribution: face areas match the mesh, yet the volume is 2.1x (2026-09-13)
Same binary as n94, with diagnostics only. Built face area by class: plane 13,197 vs mesh 13,210 mm2, cylinder 163.6 vs 177.9, facet 9,182 (mesh exploded 7,333 + island 1,850). There are no oversized or duplicated faces in memory. The per-face volume sum is 86.6 mm3, which is not comparable (N76 volumes are per-face relative figures; all planes read 0). N78 predicted sag dV is 108.6 vs observed 109,955. Plane orientation picks: 20,868 want, 21 other (flipped against outwardNormal, Kimi's mechanism 1 exists), 222 neither. Since area is right and volume is wrong, the suspect is orientation or flux: some faces contribute with the wrong sign. Next: fluxprobe.py on the in-memory BREP dump (n97r). Test 1: does the volume change under translation (origin dependence proves an inconsistent shell)? Test 2: net area-weighted normal, plus flip candidates.

## CF — in-memory BREP dump: no cylinder face wraps; the wrap enters at STEP write/read (2026-09-13)
STL2STEP_N97_DUMP_BREP (binary 52b4a201b21e; dumps the exact shape given to the STEP writer). Same KEEP, 96 cylinders, shellVol 207,794, writer check INVALID. In the dump, 0 of 96 cylinder faces have u-span > 6.3 rad. Faces with ellipse edges (idx 239, 399, 408) have u-span of about 2 rad, area of about 2 mm2, and are valid, whereas the same faces in the STEP re-read span 6.28-14.5 rad. So Kimi's F2 (unwrapping pcurves in bindCylPCurves) targets the wrong stage; D2 is a STEP-transfer defect. Separately, the in-memory shape is already invalid (writer check) and 2.1x in volume, so D1 is in memory. A flux probe on the STEP re-read is not usable (the re-read volume is 1e177). Next: check, flux and u-span probes on the dump itself.

## CG — dump probes: faces, edges and shell are valid, the SOLID is not, and net flux is +1075.6 mm2 along Z (2026-09-13)
FreeCAD on n97r_9.brep: shell closed True, valid True; 0 invalid faces, edges or vertices; check(True) "No error"; but Solid.isValid False. Net area-weighted normal (1.0, 16.0, 1075.6): a closed shell must be 0, so faces carrying +Z area of about 538 mm2 have inverted material side. dV / flux_z = 109,955 / 1,075.6 = 102.2, consistent with horizontal faces at about 102 mm counted with the wrong sign. The top flip candidates are a cluster of Z-normal plane faces with idx 11743-11983, areas 50-104 mm2. The FreeCAD STEP writer given the same dump also produces 5 wrapped and 8 invalid cylinder faces, so D2 does not come from our writer settings. Next: an OCP analysis of the dump to get the solid-level BRepCheck status, the Z of the flip cluster, and per-edge orientation consistency.

## CH — OCP orientation audit of the dump: 522 shared edges have the same orientation in both faces (2026-09-13)
orientprobe.py on n97r_9.brep. BRepCheck_Analyzer.IsValid False, yet solid and shell statuses are both NoError. All 48,478 edges are used exactly twice (topologically closed). 522 edges carry the SAME orientation in both adjacent faces, which is an orientation inconsistency that BRepCheck's shell status does not report. Unioning faces across consistent edges leaves a single component, so the shell cannot be repaired by flipping whole face groups. The examples involve cylinder faces (236, 343, 400, 408, 418) and small plane facets at z of about 19.5 and 0.6. One plane face has negative surface mass (-0.557). Plane-only net flux is (-2.2, 19.5, 838.6). Next: orientprobe2.py, which splits the faces touching those edges into all-edges-bad (a flipped face, fixable) and partly-bad (an internally inconsistent wire), with a self-test on a known good and a known flipped shell.

## CI — census: no face is simply flipped; 806 faces have only SOME edges inconsistent (2026-09-13)
orientprobe2.py (self-test: a good solid gives 0 bad edges; a one-face-flipped shell gives 4). On the dump: 522 bad edges, 806 faces touched, 0 with all edges bad, 806 partly bad (790 planes, 16 cylinders). Bad pairs: 504 plane-plane, 18 cylinder-plane. Examples: small plane facets of about 0.74 mm2 with 12 edges, 5 of them bad, at z=0 and z of about 20 (the part sits near x 3000-3100, y 2000-2130). Flipping faces cannot fix this (which explains why N16 FixFaceOrientation left the volume unchanged); the defect is at edge level. The final shell came from the N13_SEW sew (tol 0.1, freeE 375->28, accepted) followed by N27_FIXFACE (fixed=28217). N13_SEW_ORIENT is not in the config and would not trigger anyway, since the sewn shell reads as valid. Next: orientprobe3.py, which tells a fold (both faces on the same side of the edge) from a twist at each bad edge.

## CJ — the bad edges are folds: coplanar faces with opposite normals lying on the same side of the edge (2026-09-13)
orientprobe3.py on the dump, 522 bad edges: fold (normal dot -0.999) 488, twist (normal dot > 0.5) 26, crease 8. Most folds involve a sliver face (0.2-0.7 mm2, centroid within 0.02-0.07 mm of the edge) folded back onto a neighbour along a long edge (4-17 mm). Several neighbours are the cylinder faces seen invalid or wrapped on STEP re-read (342, 400, 408), at z of about 0.56 and 19.3-19.8, i.e. where fillet and bore patches meet the planar caps. So these are zero-thickness fins or folds at the cylinder-to-plane junctions, not flipped faces. That links D1 and D2: the fins sit exactly where the STEP transfer wraps the cylinder patches. Running: n98 a/b/c (binary 2209c0fa59a2). Arm a: N98_EDGE_CENSUS, the same-orientation edge count before and after N27_FIXFACE. Arm b: plus N98_FIXFACE_NOORIENT (ShapeFix_Face does not re-orient wires). Arm c: plus N98_ORIENT_GATE (refuse a per-face fix that adds bad edges). All three dump BREP.

## CK — n98a early census: the folds exist before N27_FIXFACE (2026-09-13)
First sew round of n98a (binary 2209c0fa59a2, N98_EDGE_CENSUS): N98_EDGE_CENSUS stage=n27fixface before=1674 after=1727 (fixface rejected that round: closed=0). N27_FIXFACE adds only 53 same-orientation edges, while the sewn shell already had 1,674. So N27's wire re-orientation is a minor contributor at most; the folds come from the N13 sew (tol 0.1 mm, freeE 659->48) or are already present in the built faces. Arm c (ORIENT_GATE) never registered with watchjob and is not relaunched, since the gate can only undo the 53. Next: a census before and after sew.Perform (stage=sew in/out) to split "built faces" from "sewing".

## CL — N27_FIXFACE is ruled out as the source of the folds (2026-09-13)
n98a and n98b census, later sew rounds: stage=n27fixface before=541 after=541, then 531/531, and the final dump shows 522. Only the first round (open shell, fix rejected) added edges (1674->1727). n98b (N98_FIXFACE_NOORIENT) gives identical counts, so it is refuted. The folds are present in the sewn shell itself. Running: n99a (binary 137fd90d4b59, stage=sew in/out census, which splits built faces from sewing) and n99b (the same with N27_SEW_TOL_MM=0.01 instead of 0.1). Sliver widths at the fold edges measure 0.018-0.07 mm, below the 0.1 mm sew tolerance.

## CM — the sew creates the folds: census in=1 -> out=522 (2026-09-13)
n99a (binary 137fd90d4b59): stage=sew counts are in=552 out=1674 (round 1), in=1 out=541, in=4 out=531, in=1 out=522, and final in=1 out=522 (freeE 375->28, accepted). The shell assembled by construction has about 1 same-orientation edge. BRepBuilderAPI_Sewing(tol 0.1, cutting on) introduces the 522, consistent with sliver faces 0.018-0.07 mm wide lying below the 0.1 mm tolerance. The attempts targeting N27 (noorient, gate) have both failed, so per Rule 8 this goes to Kimi (prompt n19/kimi_sew.md) before any fix. Tolerance-sensitivity measurements run in parallel: n99b at tol 0.01 and n99c at tol 0.03.

## CN — n99b, sew tol 0.01: more folds, and the shell stays open (2026-09-13)
Round 1 census: in=552 out=1714 (at tol 0.1: out=1674). Round 2: in=871 out=1215. N13_SEW gives closed=0 accepted=0 in both rounds, so the component falls back to facets: 0 cylinders, 44,436 faces, valid, volume exact. A smaller tolerance does NOT reduce the folds; the sew creates them even at 0.01 mm, below the measured sliver widths (0.018-0.07 mm). The premise "folds come from slivers thinner than the sew tolerance" is weakened: tolerance is not the lever. Kimi #2 (job kimi-sew) was launched before this result; its tolerance-based claims need checking against it. n99c (tol 0.03) is still running.

## CO — n99c, sew tol 0.03: identical to 0.01 (2026-09-13)
Census: in=552 out=1714, then in=871 out=1215, with closed=0 in both rounds, so the component falls back to facets with 0 cylinders. The fold count is the same at 0.01 and 0.03 and barely lower at 0.1 (1674), so tolerance does not govern the folds. Per the user's request I searched the web for alternatives to BRepBuilderAPI_Sewing: BRepTools_Quilt (explicit Bind of edge pairs, no geometric pairing), BOPAlgo_MakerVolume (adds every face in both orientations and classifies solids, so orientation is consistent by construction), BRepBuilderAPI_FastSewing (naturally bounded faces only, probably unsuitable), ShapeFix_FixSmallFace (strip removal; weak given that tolerance does not matter), and the sewing knobs cutting=false, FloatingEdgesMode and Min/MaxTolerance. Next: an N99_DUMP_PRESEW dump, then try each option offline in OCP on the pre-sew shell (census + closed + valid + cylinder count) before any 8-minute run.

## CP — Kimi #2 stopped on its usage quota; its OCCT-source report is saved (2026-09-13)
Report: n19/kimi_sew.occt_source_report.txt (OCCT V7_8_0 upstream sources, file:line cited, still to be verified against the source). Claims:
(1) Sewing gathers only free edges (one owning face) as weld candidates. The weld direction comes purely from point-sequence distance (isForward = distFor < distRev). No face-side or normal consistency check runs: the only function computing normals, EvaluateAngulars, is dead code. So sewing can weld two faces lying on the same side of an edge.
(2) BRepCheck_Shell::Orientation does detect BadOrientationOfSubshape, but only when checked in the context of a SOLID. The analyzer skips bare shells. This matches our shell-level NoError. Being tested now in brepcheck_ctx.py.
(3) ShapeFix_Shell only flips whole faces and cannot split along an edge.
(4) Suggested remedies: avoid welding those pairs (local tolerances), or delete the slivers before sewing.
Verified in our code: acceptance at refit_build.cpp:6769 requires validity only under STL2STEP_N13_SEW_STRICT, and shellIsValid (:2647) is a plain BRepCheck_Analyzer on the shell. Kimi's other claim, that the 552 folds of round 1 are pre-existing in the built shell, holds for round 1 only: the final round's input has 1.

## CQ — verified: BRepCheck catches a flipped face only in a solid context (2026-09-13)
brepcheck_ctx.py (a box shell with one face reversed): BRepCheck_Analyzer(bare shell).IsValid() = True, BRepCheck_Analyzer(solid containing that shell).IsValid() = False (while the shell's own status list still reads NoError). Kimi's claim 2 holds. Consequence: the engine's shellIsValid (t3 and the sew acceptance) runs on a bare shell and cannot see orientation defects. Wrapping the probe shell in a TopoDS_Solid before BRepCheck is a cheap, correct detection gate. It is not a repair: on part 9 it would reject the shell and lose the cylinders, so it has to ship together with a gluing fix.

## CR — offline gluing A/B on the pre-sew dump (n100a_presew.brep, about 7 s per variant) (2026-09-13)
glueab.py. Input shell before the sew: 375 free edges, 1 same-orientation edge, volume 97,664.8 (mesh 97,838.6), so the built faces are right. The sew is the break:
- Default sew (tol 0.1, cutting on): free 30, 522 folds, volume 207,803.5. This reproduces the engine exactly.
- Cutting off: free 187, 425 folds, volume 208,501.
- FloatingEdgesMode and LocalTolerancesMode: identical to the default.
- BOPAlgo_MakerVolume without intersection (fuzzy 0.1): empty result, no errors.
No sewing option fixes it. Next: glueab2.py, covering the anatomy of the 375 free edges and their faces (lengths, strip widths), dropping faces with width 2A/P below 0.05/0.1/0.2 mm before sewing, and MakerVolume with intersection at fuzzy 0.2.

## CS — free-edge anatomy; dropping thin faces is refuted (2026-09-13)
glueab2.py on the pre-sew dump. There are 375 free edges: length median 0.119 mm, p25 0.095, p75 6.17, max 20.6. They belong to 242 faces (27 cylinders, 215 planes); those faces' width 2A/P has p10 0.028, median 0.083, p90 0.107. 2A/P is useless as a sliver test: 24,087 of the 28,217 faces are narrower than 0.05 mm, because the planes are 0.1 mm mesh triangles. Dropping by width destroys the shell. drop<0.05: free 3,728, 122 folds, 87 cylinders. drop<0.10: 42 shells. drop<0.20: 5 cylinders. Refuted. Next: glueab3.py, a sew tolerance sweep on this pre-sew input (input folds = 1) and gap filling with planar patch faces over free-bound wires (ShapeAnalysis_FreeBounds + MakeFace OnlyPlane + ShapeFix_Shell), which avoids welding altogether. BOPAlgo_MakerVolume with intersection at fuzzy 0.2 is still running (glueabmx).

## CT — the folds do not depend on sew tolerance even on the pre-sew input; gap filling refuted (2026-09-13)
glueab3.py on n100a_presew.brep (input: 1 fold, 375 free edges). Sew results by tolerance: 0.005 -> 522 folds / free 17; 0.01 -> 522 / 19; 0.02 -> 522 / 31; 0.05 -> 510 / 32; 0.1 -> 522 / 30; 0.2 -> 521 / 30. Volume is about 207,800 in every case. Even a 5 um weld produces the same folds, so the welded free edges are already coincident: the pre-sew shell most likely contains overlapping, coincident faces (double walls) whose boundary edges are free. These are not gaps. Filling with planar patches over ShapeAnalysis_FreeBounds wires (tol 0.05/0.1/0.2) finds only 10-15 closed free-bound edges of the 375 and leaves 380+ free edges (7-13 shells after ShapeFix_Shell). The free edges do not bound holes. Refuted. Next: glueab4.py tests whether the 242 free-edge owners overlap another face (projection + BRepClass_FaceClassifier, normal dot), then drops the overlapping owners and sews.

## CU — double walls are refuted as the main cause; negative-area faces exist before sewing (2026-09-13)
glueab4.py. Of the 242 free-edge owners, only 11 overlap another face (9 same-normal, 1 opposite, 1 oblique). Dropping those 11 and sewing gives 501 folds; dropping them plus their partners (21 faces) gives 477. Still far from 0, so overlap is not the main mechanism. The overlap sample did expose pre-sew faces with NEGATIVE signed area (-0.2012, -0.5478, -0.2368): wires wound against their surface normal, which is Kimi's round-1 mechanism. Next: glueab5.py counts negative-area faces before sewing, correlates the post-sew fold edges with negative-area faces against the base rate, and runs reverse-negative-then-sew and drop-negative-then-sew.

## CV — negative-area faces are refuted as the main cause (2026-09-13)
glueab5.py. Before sewing there are 11 negative-area faces (all planes, total -4.45 mm2), and 4 of the 242 free-edge owners are among them. After sewing, only 7 of the 522 fold edges (1%) touch a negative-area face (base rate 0.04%). Reversing them before sewing still yields 522 folds; dropping them yields 500. Refuted as the main mechanism. Next hypothesis (glueab6.py): the pre-sew shell is several orientation-consistent patches separated by free-edge cracks, some facing opposite to their neighbour. Test: components via shared edges, free-edge pairing by endpoints with a same/opposite-direction count, 2-colouring flips of components before sewing, and the origin of the post-sew fold edges (pre-sew free, pre-sew shared, or new from splitting). BOPAlgo_MakerVolume with intersection is still running.

## CW — the pre-sew shell is one orientation-consistent component (2026-09-13)
glueab6.py (first stage, before a script import error): components joined by shared edges number 4, sizes [28214, 1, 1, 1], with 1 inconsistent shared edge. So the 375 free edges are slits inside a single consistently oriented surface, not seams between opposite-facing patches. The patch-flip hypothesis is refuted. The script now continues (import fixed) with endpoint pairing of free edges (same- vs opposite-direction) and the origin of the post-sew folds.

## CX — DECISIVE: 488 of 522 post-sew folds sit on edges that were SHARED and consistent before sewing (2026-09-13)
glueab6.py on n100a_presew.brep and n100a_9.brep. Fold-edge origin (midpoint match to a pre-sew edge within 0.05 mm): 488 on pre-sew SHARED edges, 34 on pre-sew free edges. Free-edge endpoint pairing (tol 0.1): 375 free edges give 235 pairs, 111 SAME-direction and 124 opposite, with 4 unmatched. 106 of the same-direction pairs lie inside the one big consistent component. Flipping components (2-colouring) before sewing still gives 522.
Mechanism consistent with every measurement: a same-direction coincident pair means the two faces lie on the same side of the edge, so the pair is NOT a true seam. BRepBuilderAPI_Sewing welds it anyway (direction is geometric, with no side check, per Kimi's source report). Accepting the weld reverses the use of a face, and every edge that face already shared correctly becomes same-orientation: that is the 488.
Next: glueab7.py describes the same- vs opposite-direction pairs (same face? types, lengths, areas, end gaps), then welds ONLY the opposite pairs ourselves via ShapeBuild_ReShape (vertex clusters + edge replacement, no Sewing), plus variants with a sew afterwards and with all pairs welded.

## CY — our own weld beats BRepBuilderAPI_Sewing: free 7, 54 bad edges, volume right, 96 cylinders (2026-09-13)
glueab7.py on n100a_presew.brep. Pair anatomy: the SAME-direction pairs (111) have short edges (median 0.078 mm) with end gaps median 0.020 mm (max 0.099). The OPPOSITE pairs (124) have edges median 6.1 mm with end gap 0.000. Weld ONLY opposite pairs via ShapeBuild_ReShape (120 welds): free 135, 11 bad edges, volume 97,663. Adding a sew afterwards: 554 bad edges, volume 206,041, so sewing breaks it again. Weld ALL pairs (184): free 7, 54 bad edges, volume 97,671 (mesh 97,839), 96 cylinders, versus the sew's free 30, 522 bad, 207,803.
Suspected artifact: same-direction pairs have edges SHORTER than the 0.1 mm pairing tolerance, so both direction tests pass and the script's first branch picked "same". Sewing may decide direction just as ambiguously. Next: glueab8.py, a best-partner global greedy pairing with direction chosen by min(dF, dR), plus a count of direction-ambiguous pairs and of welds predicted to produce bad edges.

## CZ — best-partner pairing: 137 true opposite pairs weld cleanly; 50 same-direction pairs are exact coincidences (2026-09-13)
glueab8.py (global greedy by distance, direction from min(dF, dR)): 187 pairs, 137 opposite and 50 same-direction. Only 3 pairs are direction-ambiguous and 1 edge is unpaired. The 50 same-direction pairs have end gap 0.0000 (exactly coincident), none on the same face, 41 plane-plane and 9 cylinder-plane: real, not a tolerance artifact. Weld only the opposite pairs (137 welds, 0 predicted bad): free 101, 1 bad edge (the pre-existing one), volume 97,660, 96 cylinders. Weld all pairs: free 1, 51 bad, same volume. So our own weld of true seams keeps the shell consistent (1 bad edge instead of sewing's 522). The remaining 100 free edges are the 50 same-direction coincident pairs. Hypothesis: at those spots 4 free edges coincide (two pairs), so the correct pairing is crosswise and opposite. Next: glueab9.py, a co-location census (free edges sharing both endpoints with others) plus OPP_FIRST=1 pairing that prefers opposite partners.

## DA — the 44 same-direction pairs are genuine 1:1 coincidences (2026-09-13)
glueab9.py with OPP_FIRST=1. Co-location census: each free edge has exactly one exactly-coincident partner (the "2" is a double count), except 9 with none, so the pairs are 1:1 with no alternative partner. Opposite-first pairing: 143 opposite, 44 same-direction (exact, end gap 0.0000; 38 plane-plane, 6 cylinder-plane), 1 unpaired. Welding the opposite pairs gives free 89, 1 bad edge, volume 97,660, 96 cylinders. Welding all gives free 1, 45 bad. The 44 cannot be fixed by re-pairing: at each one a face lies on the wrong side of an exactly shared edge. Next: glueab10.py describes these pairs (areas, normal dot, centroid gap), drops the smaller non-cylinder face of each, re-pairs, repeats, then welds the opposite pairs.

## DB — dropping faces at same-direction pairs is refuted (2026-09-13)
glueab10.py. Four drop rounds (46+13+2+1 = 62 non-cylinder faces) raise free edges 375 -> 400 -> 432 -> 442, and the final weld leaves free 314 (1 bad edge, volume 97,488, 96 cylinders): every drop opens holes. Caveat: glueab10's grid keyed only the start point of each use, so it missed reversed matches (114 pairs instead of 187); its counts are not comparable with glueab9's, but the hole-opening effect of dropping is structural. Descriptions of same-direction pairs: small partial-cylinder faces (area 0.8-2.3 mm2) against plane facets, edges 0.04-0.11 mm or about 6.2 mm; the 6.2 mm ones meet negative-area facets (-0.24, -0.20). Suspicion: vertices snapped onto the fitted cylinder fold the adjacent facet over the cylinder patch. Next: glueab11.py, which at each same-direction pair tests fold versus hole directly by offsetting 4 um into each face and classifying on the other face, and whether the far side of the edge is covered.

## DC — the 44 same-direction pairs are FOLD + HOLE: a facet folded over its neighbour, with an uncovered mirror region (2026-09-13)
glueab11.py (4 um offsets on each side of the shared edge, classified with BRepClass_FaceClassifier): 38 are A-ok|B-ok|overlap|other:hole, 2 A-side-wrong|overlap|hole, 1 B-side-wrong|overlap|hole, 1 overlap|covered, 1 no-overlap|hole, 1 normal failure. So 42 of 43 have face B (usually a plane facet, ~0.1 mm) lying on top of face A (a partial cylinder or plane) while the region across the edge is a hole. Normals are near-parallel (dot 0.5-0.999). Gluing cannot fix this: the defect is in face construction. The geometry fits a facet corner displaced ACROSS the boundary line, flipping the thin triangle over its neighbour. Candidate cause: mesh vertices snapped onto the analytic boundary curve (cylinder/plane intersection), whose deviation reaches about 0.07 mm (DIAG_FBF maxVertexDev), more than the facets' width. Repair concept: put the folded facet's apex back on the boundary line (the facet degenerates and the mirror hole closes with it), or refuse a snap that inverts an adjacent facet. Next: find where the engine moves shared mesh vertices onto analytic curves.

## DD — the snap does not move vertices; hypothesis refined to "analytic edge bulges past a thin facet" (2026-09-13)
Code check: snapVertexToCurve (refit_build.cpp:611) only calls bumpVertexTol (:588), i.e. it widens the TVertex tolerance and never moves the point. makeEllipseArc (:1496) sets vertex parameters on the new edge and does not move points either. So the "vertex dragged across the boundary" idea (DC) is refuted at the code level. Refined hypothesis: the shared boundary EDGE between the analytic region and the facet strip is an analytic curve (ellipse/line of the cylinder/plane cut) spanning mesh vertices. Its bulge from the chord (up to about 0.07 mm, cf. DIAG_FBF maxVertexDev) exceeds the height of the adjacent thin facet (about 0.1 mm triangles), so the facet region bounded by that curve folds over its neighbour and leaves the mirror hole. Test: glueab12.py reports, per same-direction pair, the 3D curve types of both edge uses, the sagitta of each, and the far-corner height of each face above the chord.

## DE — the bulge hypothesis is refuted: fold edges are straight and the faces are large (2026-09-13)
glueab12.py. Of the 44 same-direction pairs: 40 line/line with sagitta 0.0000 and facet height above sagitta, 3 ellipse/ellipse with sagitta 0.0001, 1 line/line where sagitta exceeds facet height. Far-corner heights: smaller face median 3.29 mm (p90 5.05), the other 10-16 mm. These are merged regions with 4-13 edges, not thin facets. So analytic edges do not bulge past thin facets. Refuted. What remains: tiny straight edges (0.04-0.12 mm, about one mesh edge) where both faces lie on one side (overlapping within 4 um) and the other side is a hole. Hypothesis: the holes are missing input triangles and the fold edges form small closed loops. Test: glueab13.py builds the connectivity of the same-direction edges (loops, sizes, perimeters) and matches closed 3-edge loops against the triangles of ~/corpora/mechparts/9.stl.

## DF — the fold edges are isolated, not loops, and no missing input triangle matches (2026-09-13)
glueab13.py. The 44 same-direction edges form 43 components: 42 single edges and 1 pair of edges, none closed. Perimeter median 0.109, max 6.24. No closed 3-edge loop exists, so nothing matches any of the 46,104 STL triangles. The missing-triangle hypothesis is refuted. Each defect is one isolated short edge whose two faces lie on the same side, with a hole locally on the other side. Hypotheses refuted this round: double-wall overlap, negative-area faces, patch flip, face drop, analytic bulge, missing-triangle loops. Stopping hypothesis-driven probes. Next: draw 4 folds (faces within 0.3 mm tessellated, projected onto the local plane, edge-use arrows) and dump the vertex fans at both ends (edges/faces incident, shared vs duplicated vertex TShapes).

## DG — visual inspection of the folds: collinear short boundary segments used in the SAME direction by faces on both sides, plus spurs (2026-09-13)
plotfold.py renders faces within 0.25 mm of a fold, projected onto the local plane, with use-direction arrows; images n19/fold_{0,1,2,3,5}.png. What they show:
(a) Along the fold line the boundary is a run of short collinear segments (about 0.04-0.11 mm) belonging to several faces above AND below the line, all with the SAME arrow direction. A correct seam has opposite directions on the two sides. The faces use the chain's own orientation on both sides.
(b) Spurs: a face boundary running out and back along the same line (fold 0, plane B), and a cylinder face with thin wedge triangles overlapping its neighbours (fold 1).
Vertex fans at the fold start vertex show three coincident free edges of identical length (e.g. 3 x 0.0429 mm, all used by 1 face) plus longer edges, so the earlier 1:1 reading of the co-location census may undercount; the triples need rechecking.
This points to wire assembly (a missing Reversed() for one side of a boundary chain, or independently built edges along a chain) rather than to gluing. Env-only arms launched to attribute it: n101m61 (without N61_NO_MAKEWIRE), n101m14 (without N14_NONREGION), n101m50 (without N50_TRIMROT). Each dumps its pre-sew shell for glueab9 pair analysis.

## DH — PIVOT (user direction): macroscopic semantic reading of part 9; the engine never recognised its real cylinders (2026-09-13)
User: "an accurate semantic description from a vlm would be very helpful ... by drawing cylinders without messing with multiple tiny triangle bad fittings" / "you are proving that the microscopic way is worser than a macroscopic sense of shape". Renders: sem/p9_{iso,iso_back,top,bottom,front,side}.png. Reading: part 9 is a FLAT SPLINED RING, bbox 114.3 x 114.2 x 20 mm, centre about (3066.2, 2090.9). A central bore (radius about 39) with one rectangular keyway notch; an outer ring with 10 rectangular teeth; small edge breaks on the top and bottom edges. All faces are extrusions along Z.
Checked against the engine's recognition (N91_FACE on n97d): 97 cylinder regions, total mesh area 179.8 mm2, radii scattered 0.2-23.7 (no cluster), none closed360. The bore alone should be about 2*pi*39*20 = 4,900 mm2. So the engine recognised NONE of the real cylinders (bore, outer ring arcs). Its "cylinders" are noise fits on edge-break strips, and the whole sewing/fold investigation (CB-DG) was patching around those. The micro path is abandoned for this part.
Plan: slice the mesh at mid-height (and near z=0/20 for edge breaks), read each loop as lines + arcs (equal-chord/equal-turn, i.e. circle fits), then build the solid from features (extruded profile, bore, teeth, keyway, edge breaks) in OCP, valid by construction, and validate against the mesh. Script: sem/slice.py.

## DI — part 9 measured as features from slices; the edge break is an exact R2 fillet (2026-09-13)
sem/slice9.out and sem/profile9.out, centre (3066.215, 2090.868), with bore and root arcs fitting within 0.008 mm:
- Ring thickness 20.
- Bore R 37.338 (constant for z 2-18).
- Keyway: width 17.78 (half 8.89), flanks 4.12, bottom at 40.38 from the centre, towards +Y.
- Outer root arcs R 51.556 (10 arcs of 16.1 deg each).
- 10 rectangular teeth: width 17.78, flat tops at 57.15 (= bbox half-size 114.3/2), flanks 6.36, 36 deg pitch starting at +X (the y extent 114.2 matches the corner of the 72 deg tooth).
- Edge breaks: bore extra radius against z is 1.128 / 0.677 / 0.268 / 0.064 at z = 0.2 / 0.5 / 1.0 / 1.5, i.e. rho - sqrt(rho^2 - (rho - z)^2) with rho = 2.000 exactly. The same holds on the root and mirrored at the top: an R2 fillet on every edge of the top and bottom faces. Vertical edges are sharp at z = 10.
Minor unexplained: 160 deg R 3.248 arcs at three spots near z = 1 and z = 19.
Next: sem/build9.py, a CSG model (root cylinder + 10 tooth boxes, minus bore + keyway, unify, R2 fillets on the top and bottom edges) validated for validity, volume against the mesh, vertex distance, and STEP round trip.

## DJ — FEATURE-LEVEL RECONSTRUCTION OF PART 9 WORKS: valid solid, 77 cylinders, STEP round trip valid in OCCT and FreeCAD (2026-09-13)
sem/build9.py (scratchpad) builds, from the DI measurements only: root cylinder R 51.556 + 10 tooth boxes, minus bore R 37.338 + keyway, UnifySameDomain, then R2 fillets on the 88 edges of the top and bottom faces, placed at the measured centre. Run time 1.3 s.
- Model BRepCheck valid True, volume 97,821.466 against mesh 97,838.629 (-0.018%). Faces: 35 planes, 77 cylinders, 22 tori (the fillets along the circular edges).
- STEP AP214: 11,325 entities (the micro path's file was about 79 MB). OCCT re-read valid True, volume 97,821.517, same face census.
- FreeCAD round trip (n83_check.py): Solid valid True, 134 faces {Plane 35, Cylinder 77, Toroid 22}, 0 invalid faces. Largest cylinder face 3,466.4 mm2 = the bore (2*pi*37.338*16*332.5/360 = 3,467).
- A two-sided surface distance (mesh -> model faces, model -> mesh triangles) is running (sem/dist9.py). The first distance number was taken against the solid, so points inside the solid read 0; it is not reported as fidelity.
Contrast with the micro path: 96 fake "cylinders" (180 mm2 total, random radii), an invalid STEP, 2.1x volume.

## DK — part 9 model fidelity: mesh->model within 0.0078 mm; model->mesh residual only at tooth-corner fillet blends (2026-09-13)
sem/dist9.py measures distance to model faces, not to the solid. Mesh -> model over 2000 vertices + 1000 centroids: mean 0.0018, p95 0.0063, p99 0.0073, max 0.0078 mm (tessellation level). Model -> mesh over 3000 tessellation nodes: mean 0.0129, p95 0.0091, p99 0.300, max 0.468. sem/worst9.py puts every node above 0.05 mm (135 of 3000) at z<0.6 or z>19.4, r 55.6-57.1, at angles +/-8 deg around each tooth top corner, i.e. the vertex blends where the R2 top/bottom fillets meet a sharp vertical tooth corner. OCCT's corner blend differs from the source CAD's by up to 0.47 mm there. Cosmetic and local, no missing feature. The R3.25 arcs at z = 1/19 are probably slices through the same blends. Next: survey all 40 mechparts for extrusion-type (2.5D) geometry, to see how far the slice-and-feature path generalises.

## DL — corpus survey: 24 of the 39 mechparts are extrusions (identical cross-sections at 30/50/70%) (2026-09-13)
sem/survey.py. Per axis: relative variation of the section perimeter at 30/50/70% height, plus the axis-aligned share of triangle area.
- Perimeter variation <= 0.007 along one axis (Z for all but part 20, which is X) for 24 parts: 7, 9, 10, 11, 12, 13, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25, 28, 29, 30, 31, 32, 33, 35, 36, 37.
- Genuinely 3D or non-prismatic (variation 0.05-0.49): 1, 2, 3, 4, 5, 6, 8, 14, 17, 26, 27, 34, 38, 39.
- The axis-aligned-area score mislabels filleted extrusions (part 9 scores 0.836), so the section-invariance test is the classifier.
So the slice-and-feature path directly covers most of the user's corpus: extrude the mid-section profile, then add end-face edge treatments measured from near-face slices. Next: sem/auto2d.py, a fully automatic version (mid-slice loops -> exact lines/arcs -> OCC wires/face -> prism -> per-loop fillet/chamfer from area deficit vs z -> validate -> STEP), checked first against the hand-built part 9 model, then run on the 24 extrusion parts.

## DM — auto2d.py reproduces part 9 with no hand input (2026-09-13)
sem/auto2d.py on mechparts/9, 2.0 s. It finds axis Z (section variation 0.00000). Mid loops: outer (30 lines, 10 arcs R 51.68-51.71) and bore (3 lines, 1 arc R 37.336). The prism is valid. End treatments measured per loop from the slice area deficit: fillet 2.0 (outer) and 2.05 (bore) at both ends. 88 fillets applied. Model valid, volume 97,816.9 against mesh 97,838.6 (-0.022%), faces {plane 35, cylinder 77, torus 22}. Mesh -> model faces over 800 vertices: mean 0.0061, p95 0.0183, max 0.0214. STEP re-read valid. Slightly looser than the hand model (max 0.0078) because each root arc is fitted on its own; a later step can snap concentric equal arcs to a shared centre and radius. Running now: batch over the 24 extrusion parts (sem/batch.sh -> sem/batch.summary).

## DN — first batch over the 24 extrusion parts: 5 exact, 1 wrong axis, 18 failed on one construction bug (2026-09-13)
sem/batch.summary (auto2d, first version):
- Exact, each valid with STEP re-read valid:
  - p9: -0.022%, 77 cyl, fillet 2.0
  - p11: +0.097%, 22 cyl, fillet 3.95, mesh->model max 0.032
  - p29: +0.061%, 9 cyl + 18 cones, chamfer 2.0, max 0.012
  - p35: -0.022%, 27 cyl, fillet 1.0 on one loop, max 0.018
  - p36: -0.059%, 47 cyl, max 0.16
- Wrong axis: p20 (a 160x45x5 plate) was extruded along X, giving -71.9% volume.
- Failed (7, 10, 12, 13, 15, 16, 18, 19, 21, 22, 23, 24, 25, 28, 30, 31, 32, 33, 37): all StdFail_NotDone from GC_MakeArcOfCircle. A loop that is ONE full circle (round hole) hands the 3-point arc the same start and end point.
Fixes: a single-arc loop becomes a full gp_Circ edge; degenerate arcs fall back to a segment; an AXIS env override lets the batch retry the other axes when |dV| > 0.5%, keeping the best valid build. Rerunning as batch2 (sem/batch2.summary). Visual check sem/p9_auto_iso.png: the automatic model looks like the part (cylinders on bore and root, tori on fillets).

## DO — batch2: 23 of the 25 extrusion-candidate parts rebuilt as valid feature models (2026-09-13)
sem/batch2.summary (auto2d with full-circle loops + axis retry). Every accepted build is BRepCheck valid with STEP re-read valid:
| part | dV | cyl | torus | cone | treatments | mesh->model max |
|---|---|---|---|---|---|---|
| 7 | -0.014% | 31 | 1 | 0 | none | 0.015 |
| 9 | -0.022% | 77 | 22 | 0 | fillet 2.0 | 0.021 |
| 10 | +0.027% | 30 | 0 | 14 | chamfer 2.0 on one loop | 0.017 |
| 11 | +0.097% | 22 | 8 | 0 | fillet 3.95 | 0.032 |
| 12 | -0.057% | 14 | 20 | 0 | fillets 2.0-2.2 | 0.083 |
| 13 | +0.015% | 16 | 0 | 0 | none | 0.014 |
| 15 | -0.000% | 3 | 0 | 0 | none | 0.000 |
| 18 | +0.014% | 5 | 4 | 0 | fillet 6.0 | 0.003 |
| 19 | +0.007% | 34 | 33 | 0 | none (2 'other' faces) | 0.152 |
| 20 | +0.062% | 14 | 4 | 0 | fillet 2.0 (axis retry picked Z) | 0.011 |
| 21 | -0.013% | 7 | 2 | 0 | fillet 6.0 | 0.004 |
| 23 | +0.037% | 25 | 38 | 0 | fillets 2.95-3.25 | 0.103 |
| 24 | -0.056% | 17 | 2 | 0 | fillet 4.2 | 0.081 |
| 25 | +0.042% | 20 | 24 | 0 | fillets 5.9-6.0 | 0.113 |
| 28 | +0.039% | 6 | 2 | 0 | fillet 3.95 | 0.015 |
| 29 | +0.061% | 9 | 0 | 18 | chamfer 2.0 | 0.012 |
| 30 | +0.650% | 26 | 0 | 0 | none | 0.028 |
| 31 | -0.018% | 7 | 0 | 14 | chamfers 2.0-2.1 | 0.094 |
| 32 | -0.021% | 10 | 6 | 0 | fillet 6.0 | 0.006 |
| 33 | +0.437% | 30 | 0 | 0 | none | 0.148 |
| 35 | -0.022% | 27 | 8 | 0 | fillet 1.0 | 0.018 |
| 36 | -0.059% | 47 | 17 | 0 | none | 0.161 |
| 37 | -0.028% | 25 | 26 | 0 | fillet 3.95 | 0.165 |
NOT solved:
- p16 (+8.2%, 632 planes): a link with FULL-ROUND edges (radius = half the 20 mm thickness). The mid-slice is the widest outline and the treatment search capped rho at 6 and t at 0.3T.
- p22 (+8.8%, 437 planes): a triangular plate with large tapered/sloped regions (bore and outer faces), not a pure extrusion.
Treatment values near 6.0 may be capped by the search range; to re-check. Next: extend the treatment search to T/2 (full rounds), run the FreeCAD round trip on all 23 STEP files, and inspect p22.

## DP — FreeCAD round trip: all 23 rebuilt STEP files read back as valid single solids, 0 invalid faces (2026-09-13)
sem/fcbatch.out (n83_check.py on each part's best build from batch2). Every one reports "Solid valid True solids 1" and INVALID faces {} (none):
p7 37 faces (31 cyl), p9 134 (77 cyl), p10 50 (30 cyl, 14 cone), p11 41 (22 cyl), p12 38 (14 cyl, 20 torus), p13 23 (16 cyl), p15 17 (3 cyl), p18 13 (5 cyl), p19 72 (34 cyl, 33 torus, 2 B-spline), p20 25 (14 cyl), p21 17 (7 cyl), p23 68 (25 cyl, 38 torus), p24 23 (17 cyl), p25 50 (20 cyl, 24 torus), p28 10 (6 cyl), p29 50 (9 cyl, 18 cone), p30 32 (26 cyl), p31 53 (7 cyl, 14 cone), p32 18 (10 cyl), p33 33 (30 cyl), p35 48 (27 cyl), p36 102 (47 cyl), p37 61 (25 cyl).
Total: 23 parts, 556 cylinder faces, all valid in both OCCT and FreeCAD.

## DQ — widening the treatment search to T/2 is refuted; p16 moves to the 3D bucket (2026-09-13)
batch3 (rho/chamfer search up to T/2, t up to 0.49T):
- p18: fillet 6.45, max dist 0.185, dV -0.146% (batch2: 6.0 / 0.003 / +0.014%)
- p21: fillet 6.4, 0.164, -0.201% (batch2: 6.0 / 0.004 / -0.013%)
- p25: fillets 5.9-6.75, 0.310, -0.266% (batch2: 0.113 / +0.042%)
- p32: fillets 6.75-7.0, 0.414, -1.023% (batch2: 0.006 / -0.021%)
Every part got WORSE. The area-deficit offset proxy d = dA/P over-estimates at large offsets, so the 6 mm cap was not truncating real values. p16 is still wrong (fillet 9.7, +10.7%, 422 cylinder facets): a full-round link is not a prism plus fillets. Reverted auto2d to the batch2 range (copy in sem/auto2d.batch2.py); the batch2 results stand as the accepted builds.
Status: 23 of 39 parts solved by the extrusion path. Remaining (16): 1, 2, 3, 4, 5, 6, 8, 14, 16, 17, 22, 26, 27, 34, 38, 39, which are 3D, full-round or tapered.

## DR — semantic reading of the 16 remaining parts (contact sheet sem/r3d/remaining_3d.png) and the methods they need (2026-09-13)
- A, stepped extrusions (one axis, several height levels): 2 (link with raised ring boss + fork), 4 (claw plate), 8 (bracket plates), 14 (lugged ring with hub), 17 and 39 (large thin levers with spokes/rings), 34 (two-level bracket), probably 3 (clevis). Method: sem/auto25.py. Slice at N heights, group equal-signature runs into levels, prism per level from its mid slice (nested loops -> faces with holes), fuse, unify.
- B, turned: 5, 26, 38 (shafts with flanges, flats, cross holes). Method: revolve the radial profile r(z), then cut flats and holes.
- C, full-round edges: 16 (link), 27 (holed ring disc). Method: inset profile by rho, prism of height T-2rho, rounded offset by rho.
- D, holes along several axes: 1 (housing block). Method: intersect extrusions along axes, then cut bores.
- E, tapered: 22 (countersink/taper). Method: extrusion + cone detection.
- F, broken mesh: 6 (spiky triangles). Report, do not reconstruct.
Starting with A.

## DS — first attempts at the stepped and turned paths: numerically close but not recognition (2026-09-13)
auto25 (batch25.summary): all 8 valid, STEP valid, dV within 0.5%, BUT the axis chooser picked X or Y (across the plate) for 2, 34, 4, 8 (X) and 14, 3, 17, 39 (Y). The result is 8-28 staircase levels, 53-931 planes, p95 distance 0.4-1.2 mm (p14/p17/p39 at large model scale: 49-55). That is voxel-like approximation, not features. Cause: along the plate normal, fillet/chamfer transition samples each count as a level. Rerunning forced to Z (batch25z).
autorev v1 (batchrev.summary): p26 -62%, p5 +64%, p38 -60%. The bore used the min distance of ALL section points, so cross holes and flats read as a bore; p5's centre came from all points (biased). Fixed: bore = innermost loop that encloses the axis (with at least 2 enclosing loops), centre fitted on the outer loop only. autoround (p16, p27) is running.

## DT — autoround (offset-based full rounds) failed on both parts (2026-09-13)
p16: thickness Z = 20, flat band 9.6-10.4 -> rho 9.6. The inset produced 3 wires from 3 loops, but BRepOffsetAPI_MakeOffsetShape on the 0.8 mm core raised StdFail_NotDone. p27: band 0.278-9.18 -> rho 2.504 (the perimeter test misreads this holed ring), and the inset of the 12-loop face returned 0 wires. Offset-solid construction is brittle for thin cores. Next idea: take the outline from a slice inside the round (e.g. 0.2T, smooth), offset it outward in 2D by the analytic d(t) to recover the widest outline, prism it, and fillet the end edges at about 0.49T. Parked until the stepped/turned reruns report.

## DU — turned-part envelope fixed: it matches the turned surfaces; the subtractive features are still missing (2026-09-13)
autorev with the enclosing-loop bore and outer-loop centre (batchrev2.summary):
- p26: axis X, 7 outer profile vertices, no bore. Envelope valid, +14.8%, faces {3 cyl, 2 cone, 2 plane}. mesh->envelope p50 0.000, p90 8.39: half the surface lies exactly on the turned envelope; the excess is the flats and cross holes.
- p38: axis X, 17 outer vertices. Valid, +7.9%, {7 cyl, 9 cone}, p50 3.17 at this model's scale (7.7 m long).
- p5: axis Y, centre score 0.05, +49.6%. p5 is mainly a milled body with a turned section, not a turned part, so a revolve is the wrong base.
Next for B: find the mesh regions away from the envelope and fit planes (flats) and cylinders (cross holes) there, then subtract them from the envelope.

## DV — local VLM (qwen3-vl:30b-a3b on nativedev CPU) timed out after 25 min on 3 renders (2026-09-13)
sem/vlm.sh via the Ollama /api/chat endpoint: urllib raised TimeoutError after 1500 s. nativedev has no GPU driver, so inference runs on CPU, and 3 x 80-dpi renders plus a long prompt is too slow. The semantic reading was done from the renders directly in this session instead (DH, DR). To use the local VLM, send one small image with a short prompt, or run it on behemoth's GPU.

## DW — stepped extrusion with bisected level boundaries works; sloped regions still become staircases (2026-09-13)
auto25b (AXIS=2, 60 samples, 14-step bisection per boundary):
- p34: 8 levels. Valid, dV -0.072% (unbisected: +2.034%), faces {27 plane, 18 cyl}, mesh->model mean 0.0054, p95 0.038, max 0.038, STEP valid. Levels 1-5 (z 0-7.58, area 2457 -> 2638, rising steadily) are a sloped region approximated by 5 steps.
- p2: 22 levels, +1.871% (unbisected +2.967%), {192 plane, 58 cyl}, max 0.50. Three runs of thin levels with monotonic area (z 5-9.8, 9.8-15, 15-20) are chamfers/tapers staircased at 0.5-1 mm.
Next: auto25c merges runs of thin consecutive levels with the same loop count and monotonic area into ONE ruled loft (BRepOffsetAPI_ThruSections) between the sections at the run's two boundaries.

## DX — lofting "taper" runs is refuted; bisected stepped extrusion (auto25b) stays the method (2026-09-13)
auto25c (ruled ThruSections between the boundary sections of runs of thin monotonic levels):
- p34: 4 groups (one loft over z 0-7.58). dV -0.183%, max distance 1.136 (auto25b: -0.072%, max 0.038). Faces {16 plane, 8 cyl, 3 other}.
- p2: the lofts at z 5-9.8 and 15.5-20 worked, but z 9.8-15 fell back on a loop-count mismatch. dV -0.810%, max 5.0 (auto25b: +1.871%, max 0.50). 12 'other' faces.
The sloped regions are not straight ruled tapers (and a plain loft does not pair the loop geometry reliably), so lofting makes the shape worse. Refuted. auto25b is the accepted stepped method; running it on the remaining stepped parts 14, 4, 3, 8, 17, 39 (b25b2).

## DY — full round by "outline inside the round, 2D offset, fillet 0.495T": valid for p16 but over-segmented (2026-09-13)
autoround2 on p16 (T 20, rho 10; slice at t = 5 with analytic inset d = 1.3397; outward 2D offset with arc joins; prism; fillet 0.495T): offset wires 3, fillet on 748 edges done. Model valid, dV -1.426%, STEP re-read valid. BUT faces {196 plane, 568 cyl, 6 torus, 354 other}, mesh->model p95 0.12, max 3.19. The loop segmentation (LINE/ARC tol 0.02) split the outline into hundreds of short primitives: the section through the round is noisier than 0.02. Numerically close but not a clean feature model. Rerunning with SEGTOL 0.05/0.08/0.12.

## DZ — p16 segmentation tolerance sweep: SEGTOL 0.12 gives a feature-level outline; holes wrongly rounded (2026-09-13)
autoround2 with SEGTOL (line/arc fit tolerance):
- 0.05: 52 fillet edges, {19 plane, 42 cyl, 14 torus, 2 other}
- 0.08: 54 edges, {19, 43, 14, 4}
- 0.12: 20 edges, {2 plane, 9 cyl, 14 torus, 4 other}, dV -1.361%, mesh->model mean 0.111, p95 0.042, max 3.19
In all three, in-memory BRepCheck says invalid while the STEP re-read says valid. The persistent max 3.19 and dV of about -1.4% come from the construction: offsetting the WHOLE face also shrinks the two holes by d, and the 0.495T fillet is applied to the hole edges too, although the holes have straight walls. Fix in autoround3: offset the outer loop only, take the holes from the mid slice unchanged, and fillet only the end edges not lying on a hole.

## EA — p16 full round, outer boundary only: dV +0.110%, max 0.062 mm (2026-09-13)
autoround3 (SEGTOL 0.12). Outline at t = 0.25T offset outward by the analytic d = 1.3397 (outer loop only, 1 wire); holes taken unchanged from the mid slice; prism T = 20; fillet 0.495T on the 16 outer end edges only. Faces {2 plane, 9 cyl, 10 torus, 4 other}, dV +0.110%, mesh->model mean 0.026, p95 0.041, max 0.062. In-memory BRepCheck: False. OCCT STEP re-read: valid True. FreeCAD round trip is being checked to settle validity.

## EB — p16 autoround3 file is a SHELL, not a solid (FreeCAD) (2026-09-13)
FreeCAD on sem/bround/p16c.step: "shape type Shell valid True solids 0 faces 25 {Cylinder 9, Toroid 10, Plane 2, BSplineSurface 4}". The 0.495T fillet left no flat side band, so OCCT produced a shell (hence in-memory BRepCheck False) with 4 B-spline patches. "STEP re-read valid" alone is not enough; every build must also be checked for solid count. The measured flat band (autoround: 9.6-10.4, about 0.8 mm) means rho is about 9.6, not T/2. autoround4 takes rho from the measured band width (capped at 0.49T), fillets at that rho, and prints the re-read solid count. Running on p16.

## EC — p16 with measured rho 9.5: shape right, still a shell; stepped outputs checked as solids (2026-09-13)
autoround4 (flat band 1.0 -> rho 9.5, inset d 1.1334): 16 fillets, dV -0.036%, mesh->model mean 0.068, p95 0.191, max 0.262, faces {2 plane, 9 cyl, 10 torus, 4 other}. The STEP re-read is still a SHELL (solids 0), so the non-solid result is not due to the rho = T/2 limit. autoround5 converts a closed fillet shell to a solid (ShapeFix_Solid.SolidFromShell + ShapeFix_Shape) before export.
FreeCAD check of the stepped (auto25b) outputs: p34 Solid valid True, 45 faces; p8 Solid valid, 69; p3 Solid valid, 277; p4 Solid valid, 681. All 0 invalid faces. (p3 and p4 are staircase approximations, not clean features.)

## ED — the VLM runs on the RTX 3090 now; nativedev resources re-prioritised for mesh2step (2026-09-13)
User: "vlm is managed by you. You need its help. you manage nativedev resources" / "it HAS to work on a gpu" / "mesh2step is the first priority for nativedev. you are the absolute master. the llm is doing nothing on nativedev. you decide and assign priorities".
Diagnosis of the earlier 25-minute VLM timeout: nativedev's RTX 3090 WORKS (nvidia-smi 24,576 MiB; the memory note claiming "no driver" was stale and is corrected). An idle qwen3.6:35b-a3b held 23.3 GB of it, so qwen3-vl:30b could not load and the request queued or ran on CPU. A second attempt waited 600 s and never loaded the model.
Actions:
- Stopped the obsolete glueabmx job (CPU).
- Unloaded qwen3.6:35b (keep_alive 0): GPU down to 313 MiB.
- Loaded qwen3-vl:30b-a3b-instruct-q4_K_M pinned (keep_alive -1): 21.2 of 21.2 GB in VRAM.
Measured: 27.7 s wall (22.6 s one-time load), 131 tok/s.
Also measured on behemoth: qwen3-vl:8b on the 4070 Ti SUPER took 18 s at 106 tok/s, but its part 9 description was wrong (Ø10 bore, 8 teeth, 1 mm fillets).
30b on the 3090, part 9: correct on base shape (ring, OD about 114, ID about 74, 20 thick, through). Wrong on details: 12 teeth (true 10), keyway missed, edge treatment called a 1 mm chamfer (true R2 fillet). Conclusion so far: the VLM names feature types; dimensions and counts come from slices. Testing targeted questions on a sharp orthographic top view.
Stepped batch (auto25b, remaining parts): p14 (5 levels, dV -0.002%), p17 (2 levels, +0.021%) and p39 (5 levels, +0.111%) have volume right, BUT 11,777 / 1,051 / 4,384 planes and a STEP re-read that is INVALID. The segmentation tolerance 0.02 mm is absolute, and these parts are 3-8 m across. auto25d scales it to max(0.02, 2e-4 x diagonal); rerunning 17, 39, 14.

## EE — what the VLM is good for, measured; scale-relative tolerance fixes the large stepped parts (2026-09-13)
qwen3-vl:30b on the 3090 (keep_alive -1, <1 s per call once loaded):
- Targeted questions on a shaded sharp top view of p9: TEETH=8 (true 10), KEYWAY=no (true yes). The render was checked visually and shows all 10 teeth and the keyway, so the model is wrong, not the input.
- Pure black silhouette (no triangle seams): TEETH=12 (still wrong), KEYWAY=yes (right).
- As a part-category classifier (A flat extrusion, B stepped, C turned, D full-round, E multi-axis) on 8 parts with known labels: 4/8. Right: 26 C, 38 C, 16 D, 1 E. Wrong: every flat/stepped plate (9 A, 22 A, 34 B, 4 B) came back as E "3D milled".
Decision: the VLM does NOT count or measure. Flat-vs-stepped routing uses the deterministic section-invariance/level tests. The VLM decides turned / full-round / multi-axis when the geometry tests fail. Dimensions always come from slices.
auto25d (tolerance max(0.02, 2e-4 x diagonal)):
- p17: diag 5378, tol 1.08. 2 levels, {51 plane, 50 cyl}, dV +0.208%, STEP re-read VALID (auto25b had 1,051 planes and an invalid re-read).
- p39: tol 1.63. 5 levels, {240 plane, 213 cyl}, +0.111%, re-read still invalid.
- p14: tol 1.37. 5 levels, {134 plane, 166 cyl}, +0.007%, max 1.15 at 6.8 m scale, re-read still invalid.
FreeCAD check on p14/p39/p17 is running.

## EF — FreeCAD on the scaled-tolerance stepped parts: p17 solved; p14/p39 have invalid planar faces (2026-09-13)
- p17: Solid valid True, 101 faces, 0 invalid. p17 is solved as a stepped extrusion: 2 levels, 51 planes + 50 cylinders, dV +0.208%.
- p14: Solid valid False, 300 faces, 25 invalid planes (7.64e6 mm2).
- p39: Solid valid False, 453 faces, 34 invalid planes (1.19e6 mm2).
Likely cause: at the coarse tolerance (1.37 / 1.63) a simplified outline crosses a hole on some level faces. auto25e checks each level face with BRepCheck while building it and rebuilds at tolerance /4, /16, /64 until valid, then runs ShapeFix_Shape on the fused result if still invalid. Rerunning p14 and p39 with the FreeCAD check.

## EG — p16: the fillet algorithm produces the broken faces, not the solid conversion (2026-09-13)
diag16.py: the pre-fillet prism is a SOLID and valid. BRepFilletAPI_MakeFillet (rho 9.5 on the 16 outer end edges of a 20 mm plate) returns a COMPOUND holding 1 solid / 1 shell / 25 faces, valid False: 3 faces with BRepCheck_UnorientableShape (1 cylinder, 2 planes). ShapeFix_Solid cannot help (there is a solid, it is just bad), and the STEP writer then emits a shell. So a near-full round is beyond what OCCT's fillet does reliably. autoround6 builds it directly, with no fillet: core = prism of the outline inset by rho (full T); 2 rims = a circle of radius rho piped along the inset outline at z0+rho and z0+T-rho; band = prism of the widest outline over the flat band; fuse, then cut straight holes. Running on p16.

## EH — p16 direct construction produced an empty solid; p14 re-read failure is UnorientableShape; DeepSeek vision model found (2026-09-13)
autoround6 (core + piped rims + band, fused, holes cut): pieces built in 1.3 s, but the fused result has solids 0 and volume 0 (the boolean with the piped rims failed silently). Not solved yet.
p14 STEP re-read: 25 faces BRepCheck_UnorientableShape (one of 6.78e6 mm2 with 26 edges), edge tolerances 1e-7, no edge errors. The in-memory model was valid, so the orientation breaks across the write/re-read of the fused, unified stepped solid. Testing NOUNIFY and a ShapeFix_Shape before write (auto25f).
Observation: parts 8, 14, 17, 38, 39 have bbox dimensions that are exact multiples of 25.4 (p8 70x130x32, p39 305x100x16, p38 170x60x60 in /25.4). These STLs look like inch geometry written as mm-scaled values.
User: "opencode has a vision model, search for it is from deepseek family". `opencode models deepseek --verbose` lists image input on deepseek/deepseek-v4-flash-vision-exp, deepseek/deepseek-flash and deepseek/deepseek-v4-flash (not v4-pro). Testing vision-exp on the same p9 counting questions and the 8-part category test.

## EI — DeepSeek v4-flash-vision-exp (via opencode) is the VLM to use: correct counts, 7/8 categories (2026-09-13)
User pointer: "opencode has a vision model ... from deepseek family". Tests via `opencode run --pure -m deepseek/deepseek-v4-flash-vision-exp "<question>" -f <image>` (question BEFORE -f, because -f is an array flag and swallows later positionals):
- p9 silhouette teeth: TEETH=10, correct. It annotated the image itself (wrote p9_annot.png with markers) and counted at 36 degree spacing. 43 s.
- p9 keyway: KEYWAY=yes, correct. 9 s.
- Categories on 8 known parts, 7-12 s each: 9 A, 26 C, 16 D, 1 E, 34 B, 38 C, 22 A all correct; 4 answered A (truth B, a stepped claw plate) wrong. 7/8, with sound reasons (for example "34: raised central region ... stepped-down lower tongue").
Local qwen3-vl:30b on the 3090 scored 4/8 and miscounted teeth (8, then 12). Decision: DeepSeek vision is the semantic reader. Local qwen VL is unloaded, leaving the 3090 free. Next: DeepSeek category + feature list for all 39 parts, feeding the routing to reconstruction methods.

## EJ — p14 STEP invalidity is not coordinate magnitude, precision or pcurves: STEP translation itself breaks 25 faces (2026-09-13)
sem/stepexp.py on the valid in-memory shape (p14_mem.brep): in memory valid (1 solid); BREP round trip valid; STEP as-is 25 UnorientableShape faces; translated to origin before writing 26; write.precision.mode=1 25; write.surfacecurve.mode=0 (no pcurves) 25. Refuted: coordinate magnitude, writer precision mode, pcurve writing. The OCCT native BREP keeps it valid, so the STEP face/wire representation is losing orientation. Next suspect: planar faces with several disjoint outer loops or touching inner loops, produced by the level fusion/unify, which STEP FACE_OUTER_BOUND/FACE_BOUND cannot express. Wire census running.
Note: the SauronsEye-style qwen3-vl:8b got loaded on nativedev (11.4 GB) by another client after the 30b was unloaded; left alone.

## EK — p14 STEP failure traced to sliver ring faces from fusing near-identical level outlines (2026-09-13)
Wire census of the valid in-memory p14: 166 cylinders (1 wire), 75 planes with 1 wire, 56 planes with 2 wires, and 3 planes with 8/10/20 wires. 55 of the 2-wire planar faces have two loops of near-equal area (731,660.2 vs 731,622.1; 518,847.3 vs 518,821.3; 12,666.9 vs 12,665.8): thin annular faces about 0.01 mm wide. Adjacent stepped levels are traced from different slices, their outlines differ by about 0.01 mm, and the fuse leaves these ring slivers plus micro side walls, which the STEP translation turns into UnorientableShape faces. Fix in auto25g: a loop matching one already used by an earlier level (area within 0.2%, centroid and sampled points within 5x tol) reuses that level's polyline verbatim, so the level walls coincide and unify merges them. Rerunning p14, p39 and p17 (regression check) with the OCCT and FreeCAD round trips.

## EL — loop snapping does not fix p14 (31 invalid after STEP); Rule 8, second opinion requested (2026-09-13)
auto25g on p14: faces {80 plane, 113 cyl} (fewer, as intended), dV +0.005%, mesh->model max 0.75, but the STEP re-read has 31 invalid faces and FreeCAD reports Solid valid False with 31 invalid planes (worse than 25). The sixth failed attempt on this STEP invalidity (translation, precision mode, no pcurves, no unify, ShapeFix before write, loop snapping). Per Rule 8, no seventh solo attempt: Kimi hand-off at sem/kimi_step14.md (measured facts, refuted attempts, files). p14/p39 are parked; the main line continues with routed reconstruction over all 39 parts once the DeepSeek classification finishes. First DeepSeek categories: p1 E, p2 A, p3 E, p4 A.

## EM — Kimi is quota-blocked, so the p14 second opinion escalates to DeepSeek v4-pro via opencode; loop snapping helps p39 (2026-09-13)
kimi_run on sem/kimi_step14.md: EXIT 1, "QUOTA: Kimi usage limit reached". Per Rule 8 escalation, the same hand-off goes to opencode (oc_run.sh, deepseek/deepseek-v4-pro), job ds-step14.
auto25g, rest of batch:
- p39: 5 levels, {104 plane, 128 cyl}, dV +0.116%, STEP re-read 12 invalid faces (auto25e: 34). FreeCAD: Solid valid False, 12 invalid planes.
- p17: still valid (FreeCAD Solid valid True, 99 faces, 0 invalid). No regression.
Loop snapping removes some sliver faces (p39 34 -> 12) but not all, and p14 got worse (25 -> 31), so it is not the complete mechanism.

## EN — DeepSeek vision classification of all 39 parts; routed reconstruction started (2026-09-13)
sem/dsv/all/results.txt (8-15 s per part, combined category + features prompt):
- A: 2 4 7 9 10 11 12 13 17 18 19 20 21 22 23 24 25 28 29 31 32 33 35 36 37 39
- B: 8 14 15 30 34
- C: 5 26 38
- D: 16 27
- E: 1 3 6
Matches my reading for turned (5, 26, 38), full round (16, 27) and multi-axis (1, 3, 6; 6 is really a damaged mesh). A/B is confused: 2 and 4 are stepped but labelled A; 15 is flat but labelled B. Feature counts in the combined prompt are unreliable (p9 teeth:12, although the dedicated counting question gave 10), so counts need dedicated single questions and dimensions come from slices.
Routing in sem/recon.sh therefore always tries auto2d first (its section-invariance test is deterministic) and additionally runs the stepped path for A or B, autorev for C and autoround5 for D. A build is kept only if FreeCAD reads a single valid solid with 0 invalid faces; the best |dV| wins. Job recon-all is running.

## EO — routed reconstruction over all 39 mechparts: 25 solved, 2 approximate, 7 wrong-shape, 5 none (2026-09-13)
sem/recon/summary.txt (recon.sh: auto2d always; auto25g for A/B; autorev for C; autoround5 for D; a build is kept only if FreeCAD reads a single valid solid with 0 invalid faces; best |dV| wins):
- SOLVED (valid solid, |dV| <= 0.65%), 25 parts, with method and cylinder count:
  - 7 A 31, 8 B 2, 9 A 77, 10 A 30, 11 B 41, 12 B 43, 13 A 16, 15 A 3
  - 17 B 49, 18 A 5, 19 A 34, 21 A 7, 23 A 25, 24 A 17, 25 A 20, 28 B 17
  - 29 A 9, 30 A 26 (0.65%), 31 A 7, 32 A 10, 33 A 30 (0.44%), 34 B 18, 35 A 27, 36 A 47, 37 A 25
- APPROX, valid but staircased: 2 (B, 1.87%, 49 cyl), 4 (B, 1.67%, 13 cyl).
- WRONG-SHAPE, valid solid but large dV, not accepted as reconstructions: 5 (turned envelope, 49.6%), 16 (A fallback, 8.2%), 20 (A picked axis X, -71.9%; the axis retry used in batch2 gave +0.062%, now added to recon.sh), 22 (A, 8.8%, tapered), 26 (C envelope, 14.8%), 27 (D, 30.5%), 38 (C envelope, 7.9%).
- NONE: 1 (E), 3 (E), 6 (E, damaged mesh), 14 (B, STEP invalid, second opinion running), 39 (B, STEP invalid).
Every valid build from the stepped path is FreeCAD-verified; the stepped path now wins on 11, 12, 28 where it beats auto2d.

## EP — axis retry in recon.sh solves p20: 26 parts solved (2026-09-13)
recon.sh on p20 with auto2d retried under AXIS=0/1/2: A (auto axis X) -71.9%, A0 -71.9%, A1 build failed, A2 (Z) +0.062% with 14 cylinders and FreeCAD valid. p20 is SOLVED, bringing the total to 26 of 39 (valid solid, |dV| <= 0.65%). Also started: sem/autorev_cut.py, which cuts flats (planar clusters of cut-surface triangles inside the turned envelope) and cross holes (fitted cylinders) out of the turned envelope. Running on p26.

## EQ — turned parts: cutting the detected flats roughly halves the error; holes and slots still missing (2026-09-13)
autorev_cut.py (flat clusters need >= 10 triangles and >= 1% of the cut area):
- p26: 542 cut-surface triangles, 2 flats (both normal +Z, at -9.65 with 116 triangles and at 12.7 with 150), 0 hole candidates. Valid, dV +4.689% (envelope alone +14.793%), faces {9 plane, 4 cyl, 2 cone}, STEP valid.
- p38: 2 flats (+Z at 76.2 with 14 triangles and at 152.4 with 146), 0 holes. Valid, +4.739% (envelope +7.932%), {8 plane, 7 cyl, 9 cone}, STEP valid.
Both flats of p26 carry the SAME normal direction, so one of them is a pocket/slot floor, not an outer flat. The half-space box cut is right for an outer flat only. DeepSeek lists a through hole and a blind hole (p26) and a keyway (p38), none detected: the hole detector looks for one common axis direction across all remaining triangles, which breaks with several features. Not solved (|dV| > 1%). Needed: a feature classifier that separates outer flats, slots/pockets and cylindrical holes per connected cluster, with the correct cut side per cluster.

## ER — per-patch feature map finds the real holes, bosses and flats exactly (2026-09-13)
sem/featmap.py: connected patches of non-envelope triangles (joined across smooth dihedrals < 20 deg), each fitted as plane or cylinder:
- p26 (turned X): plane +Z @12.70 (152 tris), 2 side planes +/-Y @6.35, cross HOLE R 4.826 along Z (span 22.35, dev 0.000; two half-patches), plane +Z @-9.652.
- p38 (turned X): planes +Z @152.4 and @76.2, side planes, HOLE R 76.2 along X (4 half-patches, span 304.8, i.e. an axial bore) and HOLE R 76.2 along Z (2 halves, span 355.6), plane @-203.2.
- p1 (all triangles): HOLE R 25.4 along Y (span 57.15), HOLE R 12.7 along Z; several "other" patches (dev 10-20) = merged fillet/boss areas, plus planes.
- p3 (all): HOLE R 7.874 along Y, HOLE R 7.112 along Z, BOSS R 15.875 along Z, and paired planes.
Cylinders come as half-patch pairs (mesh seams) and must be merged. This is the subtractive-feature evidence the turned (C) and multi-axis (E) parts need. Next: sem/features.py (patches + half merge) feeding autorev_cut2 (envelope minus flats minus holes) for p26/p38.
