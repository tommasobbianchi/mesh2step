# The design-history engine

Decided with the owner on 2026-09-26: we build an interpreter/solver/decision engine. We do not solve parts for it.
A part that comes out wrong is evidence of a defect in the **language**, the **objective**, the **evidence** or
the **solver**. It is never a case to patch. No rule may name a shape ("boss", "slot", "part 2's slope").

## 1. Language L (the interpreter)

A program is a sequence of operations. It compiles to one exact solid (OCCT, `tools/tree/tree.py`, which is
extended as L grows):

| op | arguments |
|---|---|
| `sketch` | plane (normal, offset) and loops of `line`/`arc`/`circle` |
| `extrude` | sketch, from level a to level b, `add` or `cut` |
| `revolve` | sketch, axis, angle, `add` or `cut` |
| `mirror` | operations, plane |
| `pattern` | operations, direction or axis, count, step |
| `fillet` / `chamfer` | edges selected by the faces they join, size |

L knows nothing about particular shapes. It grows only when the evidence (section 3) proves that corpus parts
need an operation L lacks, counted over the corpus, never for a single part.

Today the tree IR covers extrusions along X/Y/Z (`pad`/`pocket`), `round`/`chamfer` on loops or holes, and
`mirror_of`. `revolve`, `pattern` and sketches on general planes are not in it yet.

## 2. Objective J (the decision maker)

`J(program) = score - STEP_COST * steps`, where `score = IoU + 0.5 * (explained - extra)` on the real solid
(`tools/tree/analyse.py`: `measure` and `merit`) and `STEP_COST = 0.001`.

This is the minimum-description-length choice: the shortest program that reproduces the mesh. Every
preference we hand-wrote before now follows from J and is no longer coded:

- a round costs fewer steps than a stack of extrusions, so a thin residue becomes a finish;
- one sketch extruded to several levels is cheaper than several sketches;
- a mirror is cheaper than drawing the copy again.

J is the only arbiter between candidate programs, and it is always evaluated on the exact solid. Voxels only
pre-rank candidates.

## 3. Evidence E (candidate generation)

Candidates come from the exact surfaces the production converter fits to the mesh (the served STEP:
trueform plus the feature pass). They are never guessed:

| surface | yields |
|---|---|
| planar face | a sketch-plane normal; a level (its offset) on that normal |
| full or half cylinder, axis parallel to a normal | a circle on that plane (hole or boss) with its radius |
| partial cylinder/torus between two faces | a fillet candidate (edge, radius) |
| narrow plane between two faces | a chamfer candidate (edge, size) |
| cylinder/cone/torus sharing one axis | a revolve candidate (axis) |
| faces that repeat under a reflection/translation | a mirror/pattern candidate |

Profiles are sections of the mesh at the evidence levels, fitted with lines and arcs whose radii come from the
evidence. `tools/engine/evidence.py` builds this; `tools/engine/fetch_steps.py` gets the STEPs.

## 4. Solver

A search over programs of L, scored by J:

- **forward**: add the operation that most improves J;
- **backward** (the owner's reverse logic, `tools/tree/reverse_steps.py`): undo the part down to one or two
  sketch planes, and replay the undo sequence in reverse.

Both directions draw moves only from E. Evaluation is voxel pre-ranking plus an exact check of the finalists.
The search is deterministic and bounded in time.

## 5. Learned prior (later)

Davide's point: if point cloud -> mesh -> local solids -> global solid holds, so does the inverse. L generates
random programs, the interpreter compiles them to meshes, and we get labelled pairs for free. A model learns to
order the solver's moves from the mesh. It never decides: J does.

## 6. How a change is accepted

Only on the whole corpus (39 parts, `/home/tommaso/corpora/mechparts`), run in parallel from a frozen snapshot:
mean J, wins and losses against the baseline (`runs/tree/reverse/baseline.json`, the best of v5/v6), and wall
time. A change that helps one part and costs two is reverted. Looking at a single part is allowed for
diagnosis, never for acceptance. Once the engine matches the old rule-based paths (`propose.py`), those paths
are deleted, not maintained.

## Milestones

1. E: `evidence.py` (STEP surfaces -> planes, levels, circles, fillets, chamfers, axes), with a corpus census:
   how many parts need revolve, general planes or patterns.
2. Solver on E: forward and backward in one search, J only; measured against the baseline.
3. L grows as the census demands (revolve, pattern, general planes).
4. Synthetic programs and the learned move prior.

## Findings (2026-09-26)

- **The evidence is exact.** The production STEP (trueform + feature pass) scores 1.4963-1.5000 against the
  mesh on parts 1, 2, 3 and 7. Program generation is the whole gap; the input is not.
- **Fast J ranks like exact J.** `tools/engine/jfast.py` (a program rasterized on the grid, no OCCT) agrees with
  the exact J on 18/20 within-part pairs of saved corpus trees (`jfast_check.py`). It may replace thresholds in
  the inner loop; finalists are still judged exactly.
- **Exact undo works for local features, not for walls.** `BRepAlgoAPI_Defeaturing` removes rounds (tori),
  chamfers (cones), holes: parts 7 and 22 reach an exact one-plane base, part 2 an exact two-plane base
  (`undo_census.py`). Asked to remove the faces one axis cannot explain on a two-axis solid, it returns IsDone and
  an unchanged solid (`exact_census.py`: 0 real undos on parts 3 and 4).
- **The two-axis step is a known problem**: alternating sum of volumes (Woo 1982; Tang and Woo, CVGIP 1991) and
  B-rep to CSG conversion (Shapiro and Vossler, CAD 1991/1993). The standard way to minimal programs is a cell
  decomposition over the exact levels, in/out classification, candidate prisms from the cells, and a minimum
  set cover / ILP. Next solver component; its objective is J.
