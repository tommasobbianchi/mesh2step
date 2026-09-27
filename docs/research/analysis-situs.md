# Analysis Situs feature recognition: what it offers the design-history engine

Studied 2026-09-27 (research agent; pages and GitLab sources read directly, **[inf]** = inference). Site
pages: analysissitus.org/features/features_<name>.html for feature-recognition-framework,
recognition-principles, aag, check-dih-angles, recognize-fillets, suppress-blends, suppress-faces,
recognize-drill-holes, recognize-shafts, recognize-cavities, isolate-features, maximize-faces, afr-qna,
recognize-cnc-milling-features, components. Code: gitlab.com/ssv/AnalysisSitus (master),
src/asiAlgo/{features,blends,editing}.

## What the framework does

- **AAG (`asiAlgo_AAG`)**: one node per face (surface type), one arc per adjacent face pair (however many shared
  edges), carrying a dihedral-angle attribute (`asiAlgo_FeatureAttrAngle`: Convex, Concave, Smooth,
  SmoothConvex, SmoothConcave, NonManifold) computed from wire orientation (`asiAlgo_CheckDihedralAngle`, with a
  smoothness tolerance). Graph operations: `PushSubgraph`/`PopSubgraph`, `GetConnectedComponents`,
  `FindConvexOnly`/`FindConcaveOnly`, and `Collapse()`, which hides faces but stitches their neighbours ("look
  across blends and chamfers"). Recognised features are node attributes.
- **Recognizer/Rule pattern**: a cursor over seed faces; a Rule propagates to neighbours through dihedral angles
  and surface tests, marks the faces it visits, then commits or rolls back. Graph isomorphism against a pattern
  dictionary then refines connected components (e.g. counterbored vs countersunk holes).
- **Open-source recognizers**: blends (`asiAlgo_RecognizeBlends`, `RecognizeEBF`/`RecognizeVBF` = edge/vertex
  blends); drilled holes (`RecognizeDrillHoles[Rule]`: coaxial cylinders and cones, concave self-adjacency, full
  round, bottom/base faces); shafts; cavities (`RecognizeCavities`: seeds whose inner loop is convex-only,
  propagation through inner edges; output = feature faces plus their **base faces**); isolated features
  (`RecognizeIsolated`: remove the capping faces from the AAG; a new connected component touching only their
  inner contours is a feature).
- **Blend rule** (`RecognizeEBF.cpp`, `FindSpringEdges.cpp`): planes are skipped (left to chamfers), cones off by
  default. For a candidate face: its *smooth* edges; *spring* edges, where at the edge midpoint the face's
  curvature across the edge dominates its curvature along it (`|a2| > |a1|`) and beats the neighbour's by 1.5x
  (`|a2| > 1.5 |b2|`), radius `1/|a2|` capped by `maxRadius`; vexity (all-concave, or the side of the
  cylinder/torus the material is on); *cross* and *terminating* edges. Spring edges give the **support faces**.
  Neighbourhood refinement follows (an edge blend may become a vertex blend); chains are grouped by
  connectivity and radius (`BlendChain`).
- **Suppression** (Venkataraman 2002; `SuppressBlendChain.cpp`, `BlendTopoConditionFF*`): each chain is matched to
  a topological condition (ordinary, isolated, cliff, ...); Euler operators kill the cross edges and the blend
  face (KEF/KEV); every affected edge is recomputed by intersecting the extended support surfaces
  (`asiAlgo_RebuildEdge`, "frozen" vertices), and a zero-length edge is killed with KEV. `SuppressBlendsInc`
  removes **one chain at a time**, rebuilding the AAG after each; a failing chain is marked non-suppressible and
  skipped, so the loop always finishes. This differs from OCCT `BRepAlgoAPI_Defeaturing`, which extends surfaces
  for a whole face set at once. suppress-faces separates **soft** features (topologically isolated: just delete)
  from **hard** ones (neighbours must be extended and trimmed).
- **Stated limits**: the input must be a valid solid with faces **maximized** and canonical; scan-faceted solids
  are out of scope.

## Mapping to our weak points

**1. Fillets.** `finish.groups` classifies rounds by surface type and selects edges by proximity or by the
axis-plus-planes-at-r test. The AS rule is the missing test: a round is a face joined by **smooth edges** whose
**across curvature dominates** that of its support faces, and its two spring neighbours *are* the faces the
fillet joins, which is exactly our language's `fillet(edges selected by the faces they join)`. OCP, about 150
lines: `TopExp.MapShapesAndAncestors_s` for edge-to-face adjacency, `BRepLProp_SLProps`
(`CurvatureDirections`, `Min/MaxCurvature`), `ShapeAnalysis_Surface.ValueOfUV` for the midpoint on each face,
`BRep_Tool.Continuity_s` or a normal test for smoothness. For undo: stop passing big face sets to
`BRepAlgoAPI_Defeaturing`; pass **one recognised chain per call, re-derive the evidence after each, skip
failures** (the `SuppressBlendsInc` loop). **[inf]** This removes the "returns unchanged" failure of mixed
wall-and-blend sets and bounds memory per call. Port the Euler plus edge-rebuild suppressor only if per-chain OCCT
defeaturing still fails.

**2. Structure.** Cavities and isolated features give each local feature its **base face**: its normal is the
sketch plane, and the vexity of its inner loop says cut (concave) or pad/boss (convex), the expert's "cut the
hole from XY". Pipeline: `Collapse` the blend chains, remove the capping planes, take connected components.
**[inf]** The result is separable features in designer order (base, then attached features, then finishes); each
component becomes an ILP candidate or a sub-problem, so one global cell decomposition is no longer required. The
holes/shafts rules (coaxial cylinder, cone and torus grouping) supply revolve and hole candidates with axis and
extent. Mirror is not covered (no symmetry recognizer in AS); **[inf]** `find-isomorphous-faces` plus a
reflection check could propose mirror or pattern pairs.

**3. Evidence noise.** Their precondition is ours: **maximize faces** first (`asiAlgo_UnifySameDomain`; in OCP
`ShapeUpgrade_UnifySameDomain` with linear and angular tolerances). **[inf]** OCCT merges only patches on the same
surface within tolerance, so our 4-patch rounds first need one common cylinder fitted (the `AXIS_JOIN` cluster)
and substituted. The spring-edge test rejects near-flat huge-radius cylinders on principle (their across
curvature does not beat a neighbouring plane's by 1.5x, and `maxRadius` caps the rest), a local criterion that
replaces the bounding-box `rmax` rule.

## Licensing and reuse

The open-source core is **BSD-3-Clause** (GitLab licence metadata and `LICENSE`): commercial shipping of the code
or derivatives is allowed if the copyright notice is kept and their name is not used to endorse. The CNC
extensions (production fillet/chamfer chains, milling pockets, slots, shoulders) are **commercial**. There are
**no Python bindings**, and they build against their own **OCCT 7.6** fork while we run **OCP 7.9.3**, so linking
in-process is out. Options: (a) **port the ideas to Python/OCP** (BSD allows this, even line by line); (b) build
`asiAlgo` without Qt/VTK and run it as a subprocess over BREP files through its Tcl batch commands
(`recognize-blends`, `kill-blends-inc`, `recognize-cavities`, `dump-aag-json`), **[inf]** at the cost of a second
OCCT build. (a) is preferred.

## Top 3 ideas, ranked

1. **Smooth-edge and spring-edge blend recognition, with support faces.** Rounds identified by what joins them,
   not by surface type: the edge selector becomes the exact support face pair, noise cylinders are rejected, and
   fewer staircase slivers as the structure sees rounds as finishes. Effort 1-2 days, Python/OCP.
2. **Per-chain incremental undo** (the `SuppressBlendsInc` loop around `BRepAlgoAPI_Defeaturing`: one chain per
   call, skip failures, rebuild the adjacency). Exact bases on parts where the undo is refused or unchanged,
   bounded memory per call. About 1 day (the full Euler plus `RebuildEdge` port: 1-2 weeks, only if needed).
3. **AAG with base-face features** (cavity and isolated recognition, `Collapse` across blends). Candidates in
   designer order feeding the ILP (base sketch, then cuts and bosses on their base-face planes), smaller
   sub-problems. 3-5 days including corpus evaluation.

Other findings: no symmetry recognizer in AS (mirror stays ours); no help on scan-faceted solids (part 19's 39k
faces); their blend test dataset and report (linked from the suppress-blends page) could be an extra check for
idea 1.
