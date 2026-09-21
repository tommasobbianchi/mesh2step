# invalid-feedback — tell the model WHY its solid is invalid, and try the existing repair

## Context
In a real run (mechparts/17) the model's rounds 2 and 3 matched the mesh almost perfectly (every
feature, p95 0.058 mm, volume within 0.006 %) but were BRepCheck-invalid; the report only said
`"valid": false`, so the model could not tell what to fix, and those rounds were discarded. The
project already has a deterministic repair, `repair_step_shape` in
`/home/tommaso/projects/mesh2step/tools/feature_recon/auto25g.py`, which converts the edges of
INVALID faces only and re-runs SameParameter/ShapeFix.

## Change ONLY `recon_loop.py`. Do not edit anything under `tests/`. Do not add dependencies.

## Required behaviour (acceptance test: `tests/test_invalid.py` — read it first)

1. Add module-level `invalid_face_report(shape, limit=10) -> list[dict]`: for each face of `shape`
   that fails `BRepCheck_Analyzer(face).IsValid()`, a dict with `"type"` (plane, cylinder, cone,
   torus, sphere, bspline, or other — from `BRepAdaptor_Surface(face).GetType()`), `"area"`
   (float, via `BRepGProp.SurfaceProperties_s`) and `"centre"` (list of 3 floats: the face's
   bounding-box centre via `BRepBndLib.Add_s` + `Bnd_Box.Get()`). At most `limit` entries.
   Guard each face with try/except so one bad face cannot crash the report.
2. Add module-level `try_repair(shape) -> (shape, bool)`: if `BRepCheck_Analyzer(shape).IsValid()`,
   return `(shape, False)` unchanged. Otherwise import `repair_step_shape` from the path above
   (insert that directory on `sys.path`), call it (it may return a shape or a tuple whose first item
   is the shape), and return `(repaired, True)` only if the repaired shape is valid; else
   `(shape, False)`. Guard with try/except: any exception -> `(shape, False)`.
3. In `gate(step)`, when the solid is invalid:
   - call `try_repair`; if it returns `repaired=True`, write the repaired shape to
     `<step stem>.repaired.step` next to `step` (STEPControl_Writer, AsIs), re-run the gate's
     measurements on that file, and set `rep["repaired"] = True` in the returned report (the
     round's measurements are then those of the repaired solid; also make the round's STEP used for
     `best.step` be the repaired file);
   - otherwise add `rep["invalid_faces"] = invalid_face_report(shape)`.
   A valid solid gets `rep["repaired"] = False` and no `invalid_faces`.
4. In the feedback text sent back to the model, after the sentence about `feature_misses`, add:
   "If 'valid' is false, 'invalid_faces' lists the faces that make your solid invalid (type, area,
   location): rebuild those features so every face is valid."
   Change nothing else in the prompt.

## Do not change
`select_best`, the stop rule, `represent_detail`, the quota/retry logic, or the other measurements.

## Check
`cd <worktree> && python3 -m pytest -q tests/` must pass (all test files, not only the new one).
