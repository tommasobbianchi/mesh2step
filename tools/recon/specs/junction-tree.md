# junction-tree — signature -> tool, in the brief and in the gate's feedback

## Create `tools/recon/junction_tree.py`; edit `tools/recon/recon_loop.py` only where stated.

## Required behaviour (acceptance test: `tools/recon/tests/test_junction_tree.py`)
1. `TREE: dict[str, dict]`: blend/junction signature -> {"tool": "rt.<name>", "how": "<which junction fields
   give which tool parameters, one line>"}. Every tool must exist in tools/recon/recon_tools.py. Cover at least
   every blend signature produced by tests/junction_shapes.py, plus hole mouths (cylinder|plane|circle|convex),
   chamfers (cone|plane|circle|convex) and counterbore floors (cylinder|plane|circle|concave).
2. `advise(extracted) -> list[str]`: one line per junction/blend that has a TREE entry: signature, radius,
   location, recommended tool with parameters filled where known (e.g. "rt.boss(..., base_fillet=1.5)").
3. recon_loop.py:
   a. run_script's program prelude also imports `recon_tools as rt` (tools/recon on sys.path), so programs can
      call rt.* directly.
   b. At start, run `mesh_junctions.extract(STL)` once (on failure: log and continue without it) and append to
      the brief a section titled "JUNCTIONS" with `advise()` lines (cap 40) and the rt function signatures with
      their docstrings.
   c. Each feature_misses line gets the nearest mesh blend/junction within 2 mm of the missed patch: append
      " -> junction <sig>, use <tool>". Nothing else in the loop changes.

## Rules for every agent on this repo
- Read `docs/JUNCTIONS.md` first: it defines every field and signature. Do not redefine them.
- Do not edit tests. Do not commit. Touch only the files named below.
- Anything that outlives one shell command runs under `~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- <cmd>`;
  never nohup/setsid/&/polling loops; a job is finished only when `~/.claude/scripts/job status <name>` says so.
- OCP (OpenCascade bindings) and cadquery are installed; import `cqshim` before `cadquery` (see tools/recon/cqshim.py).

## Check
`cd <repo> && timeout 1200 python3 -m pytest -q tools/recon/tests/`
