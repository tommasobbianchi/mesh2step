# DELEGATION SPECIFICATION: repair the invalid `stepped` solids of mechparts 39 and 6

Self-contained. You do not see the conversation that produced this. Work in
`/home/tommaso/projects/mesh2step`. **No commits, no pushes, no deploys, no service restarts.**

## 1. TARGET GOAL

**Objective.** `tools/feature_recon/auto25g.py` builds geometrically correct solids for
mechparts/39 and mechparts/6 that OCCT rejects as invalid. Make both produce ONE valid closed
solid without changing the geometry it already gets right.

**Writable scope:** `tools/feature_recon/auto25g.py` only. Everything else is read-only.
Do NOT touch: `refs/`, `tests/`, `webapp/`, `src/`, corpus data, any `truth.json`.

**Open bindings:** if a fix requires editing a file outside the scope, STOP and report it
instead of widening the scope.

## 2. MEASURED FACTS — do not re-theorise these; re-measure if you doubt them

Build command (AXIS=2 is required):

```bash
cd /home/tommaso/projects/mesh2step/tools/feature_recon
AXIS=2 python3 auto25g.py /home/tommaso/corpora/mechparts/39.stl /tmp/o39.step 60
AXIS=2 python3 auto25g.py /home/tommaso/corpora/mechparts/6.stl  /tmp/o6.step  60
```

Current BRepCheck_Analyzer results:

```
part 39: overall valid=False  SOLID 1/1 invalid  SHELL 1/1 invalid
         FACE 12 of 232 invalid   WIRE 12 of 274 invalid   EDGE 0 of 572 invalid
part  6: overall valid=False  SOLID 1/1 invalid  SHELL 1/1 invalid
         FACE  8 of 916 invalid   WIRE  8 of 930 invalid   EDGE 0 of 2458 invalid
```

Geometry is already good and must not regress:
- part 39: 128 cylinders, 104 planes, volume 2551931497.76 vs mesh 2548963289.86 (dV +0.116%), dist_p95 5.449, diag 8162.5
- part 6: 282 cylinders, 634 planes, volume 290621.55 vs mesh 279656.27 (dV +3.921%), dist_p95 1.336, diag 200.2

**Key observation: every EDGE is valid, and the invalid FACE and WIRE counts are equal
(12/12 and 8/8).** That points at wire-level problems inside a few faces — ordering,
orientation, or a seam on a periodic surface — not at broken curves.

Runtimes measured: part 39 ≈ 180 s, part 6 ≈ 81 s. Anything longer than ~10 minutes must be
launched under
`~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- '<cmd> > <log> 2>&1'`
and checked with `~/.claude/scripts/job status <name>`. **Never** use `pgrep`/`ps` to answer
"is it still running", never `nohup`/`setsid`/`&`.

## 3. VERIFICATION COMMANDS

**STEP 0 — DO THIS FIRST, BEFORE ANYTHING ELSE.** `/tmp/o39.step` and `/tmp/o6.step` do NOT
exist yet. You must build them before any diagnostic can read them, or every check silently
prints nothing:

```bash
cd /home/tommaso/projects/mesh2step/tools/feature_recon
AXIS=2 python3 auto25g.py /home/tommaso/corpora/mechparts/39.stl /tmp/o39.step 60   # ~180 s
AXIS=2 python3 auto25g.py /home/tommaso/corpora/mechparts/6.stl  /tmp/o6.step  60   # ~81 s
ls -l /tmp/o39.step /tmp/o6.step        # both MUST exist before you continue
```

These take minutes. Run them in the FOREGROUND and wait; do not background them, and do not
proceed until `ls` shows both files. If a build command exceeds your shell timeout, re-run it
under `~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- '<cmd> > <log> 2>&1'` and poll
`~/.claude/scripts/job status <name>` until it reports finished.

1. Diagnose which subshapes are invalid (write this yourself as a scratch script, outside the repo).

   **API detail — a previous attempt wasted its whole budget here, so follow it exactly.**
   Do NOT introspect or print the `BRepCheck_Status` enum class itself: dumping its members
   (`BRepCheck_NoError = 0`, `BRepCheck_InvalidWire = 20`, …) tells you nothing about the parts.
   You want the status of each *subshape*. Working shape:

   ```python
   from OCP.BRepCheck import BRepCheck_Analyzer
   from OCP.TopAbs import TopAbs_FACE, TopAbs_WIRE
   from OCP.TopExp import TopExp
   from OCP.TopTools import TopTools_IndexedMapOfShape

   an = BRepCheck_Analyzer(shape)
   for label, t in (("FACE", TopAbs_FACE), ("WIRE", TopAbs_WIRE)):
       m = TopTools_IndexedMapOfShape(); TopExp.MapShapes_s(shape, t, m)
       for i in range(1, m.Extent() + 1):
           sub = m.FindKey(i)
           if an.IsValid(sub):
               continue
           res = an.Result(sub)                  # BRepCheck_Result for THIS subshape
           sl = list(res.StatusOnShape(sub))     # iterate the returned status list
           print(label, i, [s.name for s in sl]) # .name -- str(s) is not the enum name
   ```

   If `StatusOnShape` is unavailable in this OCP build, fall back to `res.Status()` and iterate
   it the same way. Verify the loop actually prints lines before trusting it: the counts must
   come out as 12 invalid faces for part 39 and 8 for part 6.

   **Report the resulting status names before attempting any fix.**
2. Rebuild: the two `AXIS=2 python3 auto25g.py ...` commands above.
3. Re-measure validity and geometry with the repo's own measure:
   ```bash
   cd /home/tommaso/projects/mesh2step && python3 -c "
   import sys; sys.path.insert(0,'.')
   from mesh2step.feature import _mesh, measure
   for p,o in (('39','/tmp/o39.step'),('6','/tmp/o6.step')):
       print(p, measure(o, _mesh(f'/home/tommaso/corpora/mechparts/{p}.stl')))"
   ```
4. Lint only what you touched: `ruff check tools/feature_recon/auto25g.py`.
   Baseline is NON-ZERO repo-wide; the gate is "no NEW diagnostic code, no rising count",
   never absolute zero.

## 4. TERMINATION CRITERIA — all must hold, each backed by captured stdout

- [ ] part 39: `valid=True`, `solids=1`, `free_edges=0`
- [ ] part 6:  `valid=True`, `solids=1`, `free_edges=0`
- [ ] neither part's `dv_pct` gets worse than the baseline above (39: +0.116%, 6: +3.921%)
- [ ] neither part's cylinder count drops (39: 128, 6: 282) — **a "fix" that deletes faces to
      reach validity is a FAILURE**, the cylinders are the product
- [ ] `ruff check tools/feature_recon/auto25g.py` introduces no new diagnostic
- [ ] the diff touches only `tools/feature_recon/auto25g.py`

## 5. GUARDRAILS

- **Report the BRepCheck status enums BEFORE proposing a fix.** Diagnosis first, then the patch.
- Prefer `ShapeFix_Wire` / `ShapeFix_Face` / `ShapeFix_Shell` over rebuilding geometry, and say
  which one solved it and why.
- Minimal diff. No refactors, no new dependencies, no reformatting of untouched lines.
- Never widen a tolerance just to pass a check; if a tolerance change is genuinely the fix, say
  so explicitly and show the measurement that justifies it.
- If after 3 iterations both parts are not valid, STOP and report: the status enums found, what
  you tried, and the remaining failure. A partial result with a correct diagnosis is worth more
  than a guess.
- Completion is never declared without stdout and exit codes.
