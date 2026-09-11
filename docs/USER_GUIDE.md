# mesh2step user guide

For workshop operators, designers, and clinicians. No CAD or programming
knowledge needed.

**What this tool does, in one sentence:** you give it a 3D model made of
small triangles, and it gives you back a CAD file you can open, measure,
and edit in a CAD program.

Two terms used in this guide:

- **Mesh (STL, OBJ, 3MF, PLY):** a 3D model made of many small flat
  triangles. This is what 3D scanners and most downloads produce.
- **STEP file:** the standard file that CAD programs open
  (Fusion, SolidWorks, FreeCAD, Onshape). This is what you get back.

```mermaid
flowchart LR
    A[Upload mesh: STL, OBJ, 3MF or PLY] --> B[Press Convert to CAD]
    B --> C[Download STEP file]
```

---

## 1. Before you start: what you need

### Accepted files and limits

| Rule | Value |
|---|---|
| Accepted file types | `.stl`, `.obj`, `.3mf`, `.ply` |
| Largest file accepted | 200 MB |
| Largest model accepted | 120,000 triangles |
| What you get back | One `.step` file |
| How long files are kept | Deleted from the server after 1 hour — download promptly |

One upload produces one STEP file.

### What makes a good input mesh

A good mesh is **closed**: its surface has no holes or gaps, like a
sealed box. A closed mesh converts to a **sealed solid**, which is what
you want for measuring volume or sending to a workshop.

A mesh with holes, gaps, or extra loose pieces still converts, but the
result is reported as **not a sealed solid** (an open shell). You can
still open it and look at it, but some CAD operations may not work on it.

### Good mesh vs problem mesh (real examples)

| | Good mesh | Problem mesh |
|---|---|---|
| Example | A 12-triangle cube | A 62,028-triangle scanned bracket |
| What happens | Converts in seconds to a tiny file; with Merge on, the 12 triangles become 6 flat faces | Converts (about 26 seconds, 149 MB file), but the STEP file re-opens very slowly in CAD programs because it carries one face per triangle |
| Lesson | Small, clean models just work | Very dense scans work but are heavy — simplify the mesh first if you can (see section 4) |

---

## 2. Web app: step by step

Open `https://mesh2step.nativemedica.it/`. A welcome box explains the
three steps: drop your model, convert, open it in CAD. Press
**Get started** to close it.

1. Press **Choose a model…** (or drag your file onto the picture area).
2. The model appears in the viewer. Drag with the left mouse button to
   turn it, right-drag to move it, scroll to zoom. Tick **Wireframe**
   to see the triangles.
3. Press **Convert to CAD**.
4. Wait. Small models answer at once. Large models show
   "Still converting — this model is large" and finish a little later.
5. Press the **Download** button in the green result card. The file is
   named after your upload (for example `part.step`).

Useful extras: **Trim away parts…** removes pieces you do not want
(see below). **Reset** (top right) clears everything. The sun/moon
button switches light and dark view. The **?** button re-opens the
welcome box.

### Trimming: removing parts you do not need

Press **Trim away parts…** after loading a model. Four tools appear:

| Tool | What it does |
|---|---|
| Box | Keeps or removes everything inside a box you type in (X, Y, Z numbers under "Numbers") |
| Slice | Cuts everything on one side of a flat plane (direction: across / along / height, plus position) |
| Freehand | You draw around an area on the screen to select it |
| Loose part | Splits the model into separate pieces, colors them, and lets you click one, then **Keep only this** or **Remove it** |

The **Keep / Remove** switch decides whether your selection is kept or
deleted. Press **Apply** to confirm each trim, **Done** when finished.
**Undo**, **Redo**, and **Start over** correct mistakes. Trimming
happens before conversion, so the STEP file contains only what is left.

### Options (under "Options")

You can convert without touching any of these. Defaults suit most users.

| Option | Default | What it does | When to change it |
|---|---|---|---|
| Engine: Smart — rebuild circles and faces | On (default) | Rebuilds flat areas and round holes as true flat and round CAD surfaces. Slower on large models. | Switch to **Exact — keep every triangle** if you want a one-to-one copy of the mesh with no rebuilding. |
| Unify angle (degrees) | 5 | Only shown with the Exact engine. Merges nearly-flat neighboring triangles below this angle. Range 0.1–45. | Raise it to get a smaller file; leave it hidden/off for an exact copy. |
| Repair mesh | Off (exact) | Tries to fix a broken mesh before converting. | **Weld** if the result says the model is not sealed and you suspect duplicate points. **Weld + fill holes** if the mesh visibly has holes. **Solidify** only as a last resort: it rebuilds the shape and the shape can change. |
| Merge co-planar faces | Off | Merges neighboring flat triangles into single faces (a cube goes from 12 triangles to 6 faces). Needs an angle, default 5 degrees, range 0.1–45. | Turn on for large flat models to get a smaller, faster STEP file. Leave off for an exact copy. |
| STEP format | AP214 | The STEP version written. Choices: AP203, AP214, AP242. | Change only if your CAD program or workshop asks for a specific version. |

### What you get back (web app)

- A result card saying **Ready to download** (sealed solid) or
  **Converted, but not a sealed solid** (the input had gaps — the file
  is still usable for viewing).
- Numbers: faces built, whether the mesh is watertight (fully closed:
  yes/no), solid (yes/no), and volume.
- Yellow warning boxes when something needs attention, for example a
  note that a very dense faceted file will re-open slowly, or that a
  round feature was left faceted with its measurements.
- The **Download** button. Files expire after 1 hour.

---

## 3. Command line version (for assisted setups)

Your IT person installs it once with:

```sh
pip install -e ".[web]"
```

For mesh repair support, add the repair extra:

```sh
pip install mesh2step[repair]
```

Then convert with one command. The STEP file lands next to the input:

```sh
mesh2step part.stl
```

| Task | Command |
|---|---|
| Basic conversion (exact copy, AP214) | `mesh2step part.stl` |
| Smart rebuild of flat and round areas | `mesh2step part.stl --engine trueform` |
| Merge flat triangles (smaller file) | `mesh2step part.stl --merge-coplanar` (default angle 5 degrees; `--merge-coplanar 1.0` sets 1 degree) |
| Newer STEP version | `mesh2step part.stl --format ap242` |
| Fix a broken mesh | `mesh2step part.stl --repair weld` (`fill` also closes holes; `solidify` rebuilds and can change the shape) |
| Keep only the biggest piece | `mesh2step part.stl --cut-largest` |
| Name the output yourself | `mesh2step part.stl -o output.step` |
| Convert a whole folder | `mesh2step ./parts_dir/ --output-dir ./step_out/` |
| Quiet output (one result line only) | `mesh2step part.stl --quiet` |

Defaults: exact-copy engine, no repair, no merging, AP214 format.
Input types and the 120,000-triangle guidance are the same as the web app.

---

## 4. If it fails or looks wrong

| Problem | What it means | What to do |
|---|---|---|
| "This model has … triangles. The converter handles up to 120,000" | Model too dense | Simplify (Decimate/Simplify) in your CAD program or slicer, then upload again |
| "File exceeds 200 MB limit" | File too big | Same as above: simplify and retry |
| "The converter is full … send it again in a few minutes" | Server busy | Wait a few minutes and retry; nothing was lost |
| "This model did not finish within 15 minutes" | Model too heavy for one run | Simplify the mesh and retry, or retry when the server is quiet |
| "Could not read mesh" | File is corrupt or an unsupported variant | Re-export from the source program as STL and retry |
| "Converted, but not a sealed solid" | Input mesh has holes or gaps | Try Repair: Weld, then Weld + fill holes; or fix holes in your CAD program |
| STEP file opens very slowly | Normal for dense exact copies (one CAD face per triangle) | Reconvert with Merge co-planar on, or simplify the mesh first |
| "Cut operations removed all triangles" | A trim deleted everything | Press Start over in the trim bar and re-trim |

Your files are converted on the server and deleted after an hour.
