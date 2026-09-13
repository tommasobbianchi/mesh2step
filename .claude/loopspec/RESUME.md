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
   the plane; plane-distance probe (N34_PLANEEDGE) running.

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
