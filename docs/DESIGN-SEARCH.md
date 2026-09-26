# Fewest-steps design search — the method

The owner: *"in a human mind all the potential approaches are tested in parallel in a fraction of second, and the
approach with less number of steps is chosen."* This is a method for any part, not a solution for one: every rule
below applies unchanged to every mesh, and the owner's grades tune only the global cost weights.

**Principle.** Among all designs that reproduce the part within tolerance, choose the one with the lowest design
cost: the fewest and simplest steps.

## 1. Evidence (read from the mesh, never from the part's name)

- **Frame and planes**: flat faces clustered by normal and offset. The part is first turned into the frame of its
  dominant planes; directions left over are tilted sketch planes.
- **Levels**: along each direction, where flat faces sit and where walls start and stop (`propose.wall_heights`).
- **2D profiles**: sections at those levels, fitted as primitives: lines, arcs, whole circles (an arc of >= 150 deg,
  or concentric with a hole), rectangles, slots.
- **Axes of revolution**: from cylindrical and conical patches.
- **Symmetry**: mirror planes and repeated copies, found by matching profiles.
- **Edges**: each edge's finish (round or chamfer), measured on sections (`propose.edge_mods`).

## 2. Vocabulary (a designer's operations)

Pad (a 2D element extruded to a level), pocket (cut from a face down to a level), revolve, mirror, pattern,
round/chamfer. A candidate step is one operation applied to one piece of evidence: a few hundred per part, never
blind permutations.

## 3. Cost ("shortest / easiest")

1 per step, plus a little per sketch primitive: a whole circle or rectangle is cheap, a 40-segment outline is not; a
mirror costs less than a second copy. This is what picks the owner's half-inscribed circle over an arc drawn on
another outline, and "extrude to the top, then cut" over a stack of slabs.

## 4. Evaluation (many approaches at once)

Candidates are scored on a voxel model of the part: adding or cutting an element is a masked sum over prefix sums
along its axis, microseconds each. Extents snap to the part's true levels. Only the winner is built in OCCT.

## 5. Search

A beam of designs grown in the designer's order: base elements, cuts, symmetry, finishes. Cut candidates are also
generated from each partial design's own error ("extruded too far here: cut it back"). While pads are chosen, extra
material counts at a reduced weight, because a later cut can remove it. The lowest-cost design that meets the
tolerance wins.

## 6. Verification

The winner is compiled in OCCT and measured against the real surface; finishes are fitted there; it competes with
the other candidates on `analyse.merit` (score - cost per step).

## Status

`tools/tree/search.py`. Done: evidence on the principal axes, whole circles, voxel scoring, beam search, residual
cuts, level snapping, finishes on pad holes and hole cuts. To do: frame alignment and tilted planes, revolve,
mirror/pattern, finishes inside the search.
