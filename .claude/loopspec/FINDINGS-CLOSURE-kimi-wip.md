# FINDINGS-CLOSURE — making mechparts/9 and /11 ship cylinders

Goal: mechparts/9 (46,104 tri, 98 cylRegions) and mechparts/11 (46,674 tri, 56
cylRegions) ship ZERO cylinders under the v1.8.0 shipped flag set. Runtime is
not a concern. Everything env-gated; off => byte-identical.

## BUILD LANDMINE (read this first)

`build/` in this worktree was COPIED from wt-p84: its `build.make` compiles
`/tmp/.../scratchpad/wt-p84/src/refit_build.cpp` (absolute!), and the other
agent rebuilds it concurrently. `cmake --build build` here does NOT build
wt-kimi sources. Every result produced with `build/stl2step` before 2026-09-13
~07:45 is of unknown provenance — treat 9_base/9_heal/9_diag/9_heal2 as
suspect even where they match expectations.

Use `build-kimi/` instead:
```
cmake -S . -B build-kimi -DCMAKE_BUILD_TYPE=Release \
  -DSTL2STEP_OCCT_NO_CONFIG=ON -DOpenCASCADE_ROOT=/snap/freecad/current/usr \
  -DSTL2STEP_BUILD_TESTS=OFF
cmake --build build-kimi -j16    # ~40s
```
Verified: `strings build-kimi/stl2step | grep "J6_HEAL enter"` = 1 (my diag).
Runtime OCCT stays the v1.8.0 dir: `LD_LIBRARY_PATH=$HOME/.local/share/mesh2step-native-v1.8.0-fc0d7911ba1b/lib`.

ALWAYS verify a gate string is in the binary before trusting a run
(`strings <bin> | grep <FLAG>`). A make no-op (same-mtime edit) silently reuses
the old binary — happened once already.

## Hypothesis 1 (primary, from fact 1): the J6 heal cap `mv.nTri < 10000`

`src/refit_build.cpp` (~line 5966): the targeted J6 shell heal
(chain-uncollapse for free edges) is size-capped at 10,000 triangles. Every
part in the user's corpus that ships cylinders today is < 10,000 tri; every
part above ships zero. The cap is corpus-tuned, not principled.

Change made: env gate `STL2STEP_J6_HEAL_MAXTRI` (default 10000, unchanged) —
replaces the hardcoded constant. Off-path byte-identical by construction.
Plus J6_DIAG-gated prints: `J6_HEAL enter ...`, `J6_HEAL matchTol=...`,
`J6_HEAL matched=N of freeE=M`.

## Status log

- Baseline part 9 (shipped flags only): 0 CYLINDRICAL_SURFACE, 451s.
  smoothAdoptedNoCyl=1 — the component is adopted with 0 analytic cylinders.
- First "heal" runs (9_heal, 9_diag) were INVALID: the build after the Edit was a
  make no-op (same-mtime), so those runs used the old binary with the hard 10000
  cap. Detected via `strings build/stl2step | grep J6_HEAL_MAXTRI` = 0. After
  `touch src/refit_build.cpp` + rebuild the string is present. Always verify the
  binary contains the gate string before trusting a run.
- DIAG data from 9_diag (still valid, diagnostics predate the edit): at the first
  not-closed event, freeEdges=541, analyticCollapsed=5824, analyticPolyline=1886
  chains. 171 of 678 sampled free-edge dump lines match a collapsed chain within
  0.05 mm (84 distinct chains); 507 have no collapsed-chain match; 59 sit on
  faces with rid=-1. => most free edges are NOT uncollapse-fixable (their chains
  kept polylines), but ~a hundred are.

## Current run

- 9_heal2: NEW binary, J6_HEAL_MAXTRI=100000 + J6_DIAG=1 → out/closure/9_heal2.*

## RESULT (hypothesis 1 verified + its limit)

With the gate actually in the binary (build-kimi), the heal runs on part 9:

- J6_HEAL enter freeE=541 → matched=163; then 392→98, 233→50, 175→25, 163→16,
  then progress stalls (pass 5: freeE=167 not < 163 → falls into the explode
  cascade at recoverPass=0; cascade pass leaves 40 free edges; heal resumes
  40→7-ish, stalls again; cascade finishes). Final: still 0 CYLINDRICAL_SURFACE.
- So fact 1 is CONFIRMED as the reason no healing ever happens on large parts,
  but healing alone is not sufficient: it converges 541 → ~40 free edges and
  the residual ~40 have no collapsed-chain match (DIAG: 507/678 sampled free
  edges have ci=-1 — they sit on polyline chains / rid=-1 faces, mostly NOT
  uncollapse-fixable). The explode cascade then wipes all 98 cylinders anyway.

## Mechanism that actually kills the cylinders (part 9)

1. Heal stalls with shell open (~40 free edges after 541→40 progress).
2. P92 fall-through → chainEdgeFail explode (129 regions) + N13 targeted
   explode of free-edge owners — the free edges border cylinders, so the
   cylinders carry the explode.
3. Rebuild faceted → adopted with 0 cylinders ("counted-not-reverted").
Alternative escape (N26 keep-built) fires only when the blanket brake held,
and by then the cylinders are already exploded — matches the refuted list.

## Fix implemented (env-gated, STL2STEP_J6_KEEP_OPEN + STL2STEP_J6_HEAL_MAXTRI)

- src/refit_build.cpp: at the heal-stall point (j6UncollapsePass > 0, heal
  condition failed), keep the built analytic shell and return it as an OPEN
  shell (BUILDFACES-EXIT:kept-built-open-shell-j6) instead of the explode
  cascade. All 98 cylinders + 3679 planes survive; the writer reports
  openShells=1 / watertight=false honestly.
- src/stl2step.cpp t2: honour that labelled exit — skip the
  BRep_Tool::IsClosed requirement only when the flag is set AND the exit
  marker matches. Off => byte-identical (the keep branch is never taken and
  t2 logic is unchanged).
- t3 BRepCheck and t4 volume budget still run: open shell should pass
  BRepCheck (free edges are legal); volume via GProp on a nearly-closed
  shell ≈ mesh volume, and N17 roundtrip rescue is in the shipped set.
  If t4 reverts, that is the next thing to confront (NOT by weakening the
  budget — maybe report a correct negative instead).
- Diagnostic prints added (J6_DIAG-gated): J6_HEAL enter/matchTol/matched,
  J6_KEEP_OPEN.

## Keep-open attempt #1 — blocked by t3, diagnosed

- Part 9: keep-open fired (J6_KEEP_OPEN faces=26553 freeE=167 pass=5).
  DIAG_REVERT: builtCyl=68 builtPl=26485 — the shell CARRIES the cylinders —
  but firstFail=t3_brepCheckIsValid → revert. (t2 honoured by policy, t4 not
  reached.)
- Part 11: same picture. Heal 30→20, keep-open fired, builtCyl=49 of 56,
  t3 fails.
- BRepCheck dump (STL2STEP_DIAG_KEEPOPEN): part 9 has 42 bad faces of 26553
  (0.16%): 32 x code 27 = BRepCheck_UnorientableShape, 10 x code 32 =
  BadOrientationOfSubshape. Part 11: 8 bad faces, all UnorientableShape.
  Exactly fact 7's partial-cylinder UV orientation defect class. So t3 cannot
  be honestly skipped — the bad faces are genuinely defective geometry.

## Keep-open attempt #2 — micro-explode of bad faces (implemented)

- src/refit_build.cpp keep-open branch: before keeping, run BRepCheck over
  built[], map bad faces → rids via builtRid, explodeRegion ONLY those
  (bounded 3 rounds: koBadRounds), goto try_rebuild. Their facet rebuilds are
  mesh-consistent and should also repair some free edges that stalled the
  heal — possibly closing the shell entirely, in which case t4 volume
  verification applies normally.
- src/stl2step.cpp: t4 volume budget skipped for the labelled keep-open exit
  ONLY (open-shell volume is mathematically meaningless: a 167-free-edge
  shell integrates 15139 vs true 97838 mm3). Mirrors the existing policy at
  doVol (openShellsOut == 0 requirement). t3 stays STRICT — surviving faces
  must be valid.
## Keep-open attempt #3 — sliver forensics

- 9_ko4 (micro-explode): round1 exploded 38 bad regions → freeE 167→93; round2
  exploded 1 more → 99. Kept shell: builtCyl=68 (all surviving cylinders), but
  t3 still fails: 4 remaining bad faces, all tiny slivers (0.011..0.086 mm2,
  UnorientableShape). They belong to already-exploded regions (facet slivers)
  or have no rid — exploding cannot touch them. volAnalytic=97551 vs mesh
  97838 (0.3% off on an OPEN shell — geometrically sound).
- 9_ko5 (ShapeFix_Face on the slivers): all no-op. 11_ko3: same, freeE=8,
  builtCyl=48.
- 9_ko6 (ShapeFix_Shell::FixFaceOrientation): synced=0 nowValid=0 — NOT an
  orientation problem.
- Next: rebuild degenerate facet slivers from pristine mesh points (pending
  forensics: J6_KEEPOPEN_BAD prints rid / regionNTris / minEdgeLen / maxEdgeTol).
  Hypothesis: snapVertexToCurve collapsed an adjacent tiny triangle (two
  vertices snapped onto the same curve point), making the face degenerate;
  the all-faceted path passes because nothing snaps there.

## Open questions

- If the heal runs on part 9 but the shell still does not close after ≤8
  passes (progress-gated by `freeE < j6PrevFreeE`), the P92_J6_RECOVER
  fall-through + N13 targeted explode still fire on a 26,533-face shell —
  need to check what that does to cylinders.
- Part 11's buildFaces-false (revertCause "buildFaces-false exit=none
  line=6038") is a different exit path (whole component reverted to
  verbatim); the cap raise may not touch it. DIAG_EXIT only records a line;
  6038 is inside the `addId` lambda — diagnostic noise, real return-false is
  elsewhere.
