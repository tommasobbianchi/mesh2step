# Junctions: the unit of reverse engineering

Tommaso, 2026-09-22: *"the examples are not overall shape but finer details that stem particular
approaches in RE. Disassemble a shape into all the junctions between planes or curves: those
intersection types are our library; the library creates the toolbox; a decision tree maps
intersection type -> right tool."*

## Why junctions, not whole parts

A part is rarely like another part, but its details repeat everywhere: a boss meeting a floor
through a fillet, a hole with a chamfered mouth, two walls meeting in a rounded edge. What the
reconstruction gets wrong is almost always one of those details (part 6: two convex rounds on a
boss built as revolved splines; parts 12/23: radial fillets), never the overall shape. So the
reusable knowledge is per **junction**, and a part is a set of junctions.

## Definitions

**Face kinds.** `plane`, `cylinder`, `cone`, `torus`, `sphere`, `other` (anything non-analytic).

**Junction.** Where two faces meet along an edge. Recorded as:

| field | meaning |
|---|---|
| `a`, `b` | the two face kinds, sorted alphabetically (`a <= b`) |
| `curve` | the edge's shape: `line`, `circle`, `ellipse`, `other` |
| `tangent` | the faces meet smoothly (normals agree within 2 degrees along the edge) |
| `convex` | not tangent: the material angle at the edge is below 180 degrees (a box edge); `false` = an inside corner; `null` when tangent |
| `angle` | degrees between the two outward normals at the edge midpoint (0 tangent, 90 box edge) |
| `radius` | the edge circle's radius when `curve` is `circle`, else `null` |
| `coaxial` | circle edge on a cylinder/cone/torus face and the circle's axis is that surface's axis; else `null` |
| `centre`, `length` | edge midpoint and length, mm |

Signature: `a|b|curve|state`, with `state` one of `convex`, `concave`, `tangent`.
Example: a box edge is `plane|plane|line|convex`; a through hole's mouth is `cylinder|plane|circle|convex`.

**Blend.** A curved face whose junctions with two different neighbours are both tangent. This is
the fillet or round, the detail that matters most:

| field | meaning |
|---|---|
| `blend` | the blend face's kind (`cylinder` between two planes, `torus` between a plane and a coaxial cylinder, ...) |
| `between` | the two supporting face kinds, sorted |
| `round` | `true` = convex (material bulges out, a rounded edge), `false` = concave fillet (material fills an inside corner) |
| `radius` | blend radius: cylinder radius, torus minor radius, sphere radius |
| `centre` | face centroid |

Signature: `blend:kind|a+b|round` or `blend:kind|a+b|fillet`.
Example: a boss joined to its floor by a fillet is `blend:torus|cylinder+plane|fillet`.

## The three pieces

1. **Library** (`tools/recon/junctions.py`, `tools/recon/mesh_junctions.py`). Take a shape apart
   into junctions and blends. From a B-rep (STEP) exactly; from a mesh (STL) by segmenting it
   into faces first. `junctions.py catalog` runs over every accepted reconstruction and counts
   the signatures actually met, with examples: the library is measured, not imagined.
2. **Toolbox** (`tools/recon/recon_tools.py`, imported in every program as `rt`). One construction
   per junction family, each guaranteed to produce exact analytic faces that survive the STEP
   round trip: `rt.boss`, `rt.hole`, `rt.counterbore`, `rt.ring_fillet`, `rt.edge_round`.
3. **Decision tree** (`tools/recon/junction_tree.py`). Signature -> tool, with how to read the
   tool's parameters off the junction. Used twice: the mesh's junctions go into the model's brief
   with their recommended tool, and the gate names the junction type and the tool for every
   feature the model missed.

The gate is unchanged: a feature counts only when it lands on an exact analytic face.

## Measured library (2026-09-22)

`tools/recon/junction_library.json`: 41 accepted Opus reconstructions (39 mechparts, polydryer, one
archived duplicate), 78 signatures. Blends, most frequent first; `+torus` rows are blend CHAINS (a round
running along a straight edge and turning a corner, e.g. the rim of a rounded-rectangle pad):

| count | blend |
|---|---|
| 172 | `blend:torus|cylinder+plane|round` |
| 127 | `blend:cylinder|plane+plane|round` |
| 60 | `blend:cylinder|plane+plane|fillet` |
| 50 | `blend:cylinder|plane+torus|round` |
| 48 | `blend:torus|plane+torus|round` |
| 48 | `blend:cylinder|cylinder+cylinder|round` |
| 38 | `blend:cylinder|cylinder+plane|fillet` |
| 33 | `blend:cylinder|torus+torus|fillet` |
| 33 | `blend:cylinder|plane+torus|fillet` |
| 29 | `blend:cylinder|cylinder+cylinder|fillet` |
| 24 | `blend:torus|cone+plane|round` |
| 24 | `blend:cylinder|torus+torus|round` |

The toolbox covers the top two families directly (rt.boss / rt.hole / rt.ring_fillet for torus blends on
cylinder+plane; rt.edge_round for plane+plane edges and profile-rim chains).
