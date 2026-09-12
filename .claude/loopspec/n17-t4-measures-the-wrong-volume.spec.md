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
