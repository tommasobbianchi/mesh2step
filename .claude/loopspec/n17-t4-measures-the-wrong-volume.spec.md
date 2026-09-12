# n17 — t4's premise is unsound: `BRepGProp` on the in-memory shell is not the shipped volume

The pipeline blocker behind the arc arm, isolated with a standalone OCCT instrument
(`scratchpad/volprobe.cpp`, linked against the frozen 7.8 libs, independent of the engine).

## The measurement chain, one run, `Mesh2step_test01.stl` (mesh volume 135807.5086)

```
t4 probe (rf face list)          255 faces   132545.8350
  raw Gauss / as-solid / sewn / ShapeFix_Solid : ALL 132545.8350, infinite point OUT, valid
  unified (shell or solid)       150 faces   132865.8748
shape handed to STEPControl_Writer (STL2STEP_DUMP_WRITE)
                                 150 faces   132865.8748   <- identical to the unified probe
same file, read back             150 faces   135793.1276   <- 0.011 % off the mesh
```

**The file is right and the in-memory shape measures wrong.** 132865.87 is 2.2 % off the mesh;
135793.13 is 0.011 % off. t4 rejects the component on the in-memory number, so a rebuild that
would ship correctly is reverted to faceted output, taking every cylinder in the component
with it.

## What it is NOT — each ruled out by measurement, do not re-theorise

Comparing the in-memory shape against its own STEP round trip:

```
                         in-memory        after round trip
faces                          150                     150
surface area             22367.2356              22367.2356   <- identical to the digit
faces FORWARD/REVERSED       149 / 1                 149 / 1
BRepCheck valid                  1                       1
volume                  132865.8748             135793.1276   <- differs by 2927.2528
```

Same face count, same trimmed area, same orientation flags, both valid. So it is not a missing
face, not a lost region, not a different trimming, and not a whole-shell inversion.

Repairs attempted on the in-memory shape, ALL of which leave the number unchanged at
132865.8748:
- `BRepBuilderAPI_Sewing` (1e-6) then `ShapeFix_Solid`
- `ShapeFix_Shell::FixFaceOrientation`
- `ShapeFix_Shape`
- `BRepLib::OrientClosedSolid`
- `ShapeUpgrade_UnifySameDomain`, as a shell and as a solid
- **per-face orientation by point classification** — step off each face along its oriented
  normal and classify against the solid: `tested=150 flipped=0` and `tested=255 flipped=0`.
  Every face is already outward by the classifier's reckoning.

So the classifier and `BRepGProp` disagree about the same shape, and only serialising through
STEP reconciles them. This is the same phenomenon recorded in `n12-ladder13-triage.spec.md` §4
("`BRepGProp::VolumeProperties` can be 4.2 % wrong on a closed, manifold, BRepCheck-valid
shell"), now pinned to a shape where every other OCCT opinion says the geometry is fine.

## Consequence for the target

t4 is not a wrong threshold to widen — its INPUT is unreliable, so tuning the budget would be
tuning against a number that does not describe the part. Two sound routes, in order of cost:

1. **Per-region volume attribution instead of a component verdict** (upstream's own design,
   `collectResidualCulprits`, and already item 7 of `n14-external-prior-art.spec.md`). Each
   region is compared against its OWN closed-form predicted defect, so one mis-integrating
   face shows up as one region's anomaly rather than condemning the component. This also
   sidesteps the global GProp number entirely.
2. **Move the volume verdict after the write**, using the re-read volume the engine already
   computes as `stepVolumeMM3`. Guaranteed to measure what ships, at the cost of a write+read
   for components that fail the cheap pre-filter.

Route 1 is the better fix and is the one to build: it is the reference's design, it is
per-region (so it degrades gracefully), and it does not depend on a serialisation round trip
to tell the truth.

## Instrument

`scratchpad/volprobe.cpp` — loads a BREP or STEP and reports volume, area, face count,
FORWARD/REVERSED counts, infinite-point classification, and the result of each repair above.
Build:
```
L=$HOME/.local/share/mesh2step-native/lib
g++ -std=c++17 -O1 volprobe.cpp -o volprobe -I/snap/freecad/current/usr/include/opencascade \
    $(ls $L/libTK*.so.7.8) -Wl,-rpath,$L
LD_LIBRARY_PATH=$L:/snap/freecad/current/usr/lib:/snap/freecad/current/usr/lib/x86_64-linux-gnu ./volprobe <file>
```
`STL2STEP_DUMP_WRITE=<path>` (added to the worktree, NOT in the deployed v1.4.0 binary) dumps
the exact shape handed to the writer, which is what made the comparison possible.

## The fix, measured: round-trip the probe (n17) + arc-coverage gate (n18)

### n17 — ask the authoritative measure when the cheap one fails

`STL2STEP_N17_ROUNDTRIP_T4`: when `|shellVol - meshVol| > budget`, serialise the probe
through the same writer/reader the customer's file goes through and re-test with the
**same budget**. Only components the cheap test already rejected pay the cost.

On `Mesh2step_test01` it rescues the component outright:
```
N17_ROUNDTRIP rescued root=743 inMemory=132545.8350 roundTrip=135793.0910
              mesh=135807.5086 budget=31.5173
-> ships 2 cylinders at R=11.5882 and R=13.7518 against a reference STEP's 11.6 / 13.8,
   volume 0.011 % off the mesh, watertight, no revert (baseline ships 0)
```

Corpus, n17 alone on top of the deployed N15: normal 71.95 -> 71.57, recall 60.42 -> 61.00
but precision 88.92 -> 86.58 (built 352 -> 365, matched 313 -> 316). The whole precision cost
is ONE model: `L10_cross_slide` ships 11 cylinders where truth has 4 faces at R=2.0 --
1x R=2.0 (the match), 1x R=7.2111, **7x R=7.2539**, 2x R=9.7021. One curved wall sliced into
narrow strips: volume right, radii invented. `L06_slotted_plate` is a pure gain (0 -> 2 built,
0 -> 2 matched).

### n18 — the arc-coverage gate that removes exactly those strips

`STL2STEP_N18_ARCCOV=29` (ScanRuler's constant, restated mechanism only): drop a partial
cylinder whose span is under ~30 degrees, because over that span the arc is barely curved and
the radius and axis are guesses. `closed360` regions are exempt by definition.

```
cross_slide     11 faces -> 3   (all eight at R=7.21/7.25 dropped, the R=2.0 match kept)
slotted_plate    2 faces -> 2   (untouched)
at 45 deg        cross_slide -> 0, i.e. it also kills the real R=2.0 -- 29 is the right value
```

### Both together, corpus A/B against the DEPLOYED v1.4.0 (N15 on in both arms)

```
normal 203   A 71.95 (r 60.42  p 88.92  m 313  built 352)
             B 73.40 (r 60.89  p 92.40  m 316  built 342)      +1.45
             valid closed solids 200/203 in both
             better L09_crank_arm 2 -> 4 | WORSE L08_pillow_block 5 -> 4
fine 78      A 50.13 / B 50.13, identical
sentinels    SOT-23 12 / SOT-143 16 / SuperSOT-3 12 / TSOT-23 12, unchanged
```

Recall AND precision both rise, and the built count FALLS 352 -> 342: fewer faces, more of
them real. Shipped-volume error on the changed models: `slotted_plate` 0.0113 %,
`cross_slide` 0.0341 %, `crank_arm` 0.1217 %.

### One large volume error found, and it is PRE-EXISTING

`L08_pillow_block` ships at **15.06 % volume error with no flags at all** — baseline,
deployed v1.4.0, and n17 all identical, and `t4 passes it` (`reverted=0`). n18 moves it to
15.22 % while dropping 5 of its 10 cylinders.

So t4, today, **rejects a component whose shipped file is 0.011 % correct and accepts one that
is 15 % wrong.** That is the clearest statement of why its input, not its budget, is the
defect. Filed as the next target; not introduced by this work.
