# Why mesh-seeded bands rebuild to an invalid solid — measured diagnosis (2026-09-19)

Part: L09_valve_body_normal.stl, band 0 (r=2.0000006, base=(-18,-10.5,-10.5), axis=(0,1,0), h=21).

## The failure mechanism (measured, diag/open_edges.log)

Applying band 0 alone:

1. `faces 427, 428, 523: wire-not-done` — three surviving (non-member) faces whose wire
   contains exactly one rim chord of the band. rebuild.py:461-467 swaps that chord for the
   band's FULL-circle rim edge, leaving the face's other two edges dangling off the circle;
   MakeWire fails, the face is kept unchanged (rebuild.py:475-478).
2. The kept face still carries the original chord chain; the new cylinder face carries the
   circle. They do not share edges -> `free edges after sewing: 10`, sewed shape is a
   SHELL, `valid after fix: False`.

Face 427 vertices (diag/rim_coverage.log): two on the band's rim circle at z=0, third at
axial z=-0.445, rho=1.9505 (OFF the cylinder, inside it). It is a junction triangle where
the rim meets a cross-hole. Its normal is (-0.111,-0.111,-0.988): |n·axis| = 0.111.

## Why the rim is not a rim (measured)

Member faces' vertices on the rim circles at both ends (z=0 and z=21):

    rim z=0.0: 14 vertices on circle; max angular gap: 270.0 deg
    rim z=21.0: 14 vertices on circle; max angular gap: 270.0 deg

The wall exists on only a 90-degree arc. The other 270 degrees of the "cylinder" at those
planes is breached by the perpendicular cross-holes (bands 1,2,5,8,9 are Z-axis holes and
bands 10-13 X-axis holes through the SAME corner points). This part's r=2 features are
three mutually intersecting cross-holes at each corner; no r=2 hole has a complete rim.

So `_rim_chord_levels` finding "exactly 2 clean levels" (fact 5) only proves SOME member
face carries a chord at that level — not that the chords form a closed loop. The extent
snap cannot create the guarantee the rebuild needs.

## What find_bands guarantees that bands_from_patches did not (the answer)

1. **Both rims exist as CLOSED chains of circle edges in the shape.** find_bands builds a
   band only from circles find_circles fitted to closed edge chains (canonize.find_circles
   returns `closed` circles; fact 1 notes "both closed"). Therefore at each band end every
   bordering face meets the wall along a COMPLETE chord chain — rebuild.py:461-467's
   swap of the chain for one circular edge is exactly what the docstring at rebuild.py:320-324
   relies on ("every neighbouring face that borders the band has its chain of rim chords
   replaced ... so the edge is shared by construction"). bands_from_patches snapped the
   extent to chord LEVELS (_rim_chord_levels, rebuild.py:157) but never checked the chords
   at those levels close into a loop.
2. **Members are only wall strips parallel to the axis** (rebuild.py:120-128): planar,
   |normal·axis| <= 1e-3. This excludes junction triangles like 427/428/523
   (|n·axis| = 0.111). bands_from_patches' membership test (rebuild.py:258-265) is purely
   radial/axial with tol = max(tol_mm, 2%*r), which is one rounding decision away from
   admitting them (427's inner vertex is 0.0495 off the fitted radius vs tol 0.05).

Axis sign / base convention: verified NOT the cause. Bands land in the right place
(fact 7, and band 0's geometry above is exactly on the hole). face_indices contents:
verified true wall strips on this part. The missing piece is the closed-rim guarantee.

## Fix

In bands_from_patches: (a) require each snapped extent end to be a closed rim — every edge
in the shape satisfying the SAME predicate rebuild swaps on (_is_rim_chord with tol_mm,
not the loose membership tol) must chain into a single closed loop; (b) restrict members
to planar faces with |normal·axis| <= 1e-3 like find_bands; (c) require member strips to
bridge the snapped extent with no mid-wall gap, same covered-interval test as
find_bands (rebuild.py:140-152). All three only REJECT unbuildable seeded bands; they
never relax or tighten any acceptance gate.

Result on L09: all 14 seeded bands rejected (every corner is a cross-hole intersection —
no closed r=2 rim exists, and walls are breached at the ends). Rebuild honestly reports
"no cylinder bands found" instead of returning an invalid solid.

Verified: clean through-bore seeded from quads.classify patches -> bands=1, valid=True,
ok=True (positive control); 30mm box with three crossing 2mm holes, hand-built
full-length patch -> rejected by the continuity check (both outer rims verify closed, the
mid-wall breach is what stops it); tests/test_rebuild.py + tests/test_intent.py 16/16;
full suite: 131 passed, 4 failed + 1 error all pre-existing on base c45d11d
(engine-version dependent, unrelated to rebuild.py).
