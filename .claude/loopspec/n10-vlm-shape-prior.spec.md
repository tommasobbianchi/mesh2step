# n10 — a VLM as the shape prior that tells the fitter what to look for

Opened 2026-09-11. Tommaso: *"we try the Moria route. VLM."*, following the earlier framing
*"we need someone that indicates the algo the shapes to reconstruct"*.

## The job the VLM was given

NOT counting cylinders, and NOT measuring them. n9 established that a cylinder-only RANSAC
recovers `test01`'s four cylinders to 0.03 % but fabricates 360 faces corpus-wide, **251 of
them on 27 models that have no cylindrical face at all** — spheres, cones, chamfered blocks. A
detector with one primitive must describe a dome as a stack of tubes; nothing competes for
those facets.

So the VLM's job is the discrimination the geometry cannot make on its own: *does this part
contain cylindrical faces at all?* A veto, one inference per model, before any fitting runs.

## Apparatus

- **Renderer**: `scratchpad/vlm/render.py`, a z-buffered software rasteriser in numpy, four
  isometric views Lambert-shaded and tiled into one PNG. No GL on nativedev (no pyrender, no
  OSMesa) and a painter's-algorithm matplotlib plot draws back faces over front ones on exactly
  the concave features — bores, pockets — whose shape is the question. Tile size env-driven.
- **Inference**: Ollama. nativedev is CPU-only and was thrashing (an unrelated 26 GB
  `qwen3.6:35b` resident), so the work moved to **behemoth** (RTX 4070 Ti SUPER, 52 GB free).
  0.5-1.0 s per part on GPU.
- **Population, fixed before any inference ran**: all 27 corpus models with no truth cylinder
  that RANSAC fabricated on, plus all 109 that do have truth cylinders. The entire population of
  both classes — no sampling step, so there is nothing to fit the result to.

## The gate, stated before measuring

Asymmetric on purpose. A **missed veto** costs only what n9 already loses. A **wrong veto**
destroys a real cylinder the current engine would have shipped, so that is the disqualifying
number. For the veto to be usable, wrong vetoes must be ~0.

## P98 — measured

| model | tile px | correct veto (of 27) | **wrong veto (of 109)** |
|---|---|---|---|
| `qwen3-vl:4b` | 384 | 18 | **30** |
| `qwen3-vl:4b` | 640 | 17 | **31** |
| `qwen3-vl:8b` | 384 | 23 | **22** |
| `qwen3-vl:30b-a3b` | 384 | 20 | **12** |

A pilot on 10 hand-picked parts scored 8/10 and was **not** predictive of the full population —
recorded because it is exactly the trap the fixed-population rule exists to prevent.

### The resolution hypothesis was mine, and it was wrong

The 4b's wrong vetoes were almost all flat plates with small holes (`L02_blind_hole`,
`L06_grid_plate`, `L06_strip_holes`, `L08_angle_plate`, `L09_spacer_block`). At 384 px a 3 mm
hole in a 120 mm plate is a few pixels, so the obvious reading was that the feature was not in
the image. Re-rendered all 136 at 640 px — **four times the pixels, no change** (30 → 31 wrong).
The renderer was not the limit. Two failed attempts on this sub-problem; per Rule 8 no third
variation was tried.

### What does move it: model capacity

4b → 8b, same prompt, same images, same population: veto 18 → 23, wrong veto 30 → **22**. Size
is the live axis. `qwen3-vl:30b-a3b` pull in flight at time of writing.

## The ceiling, which no VLM quality changes

**A perfect veto adds zero recall.** It only prevents fabrication. RANSAC + a flawless veto is
still ~75 truth-matched cylinders against the **220** the current engine already ships. This
combination cannot replace the segmenter, and improving the VLM does not alter that arithmetic.

Its value is confined to one shape: the **guarded fallback**. On a mesh where the existing
segmenter returns zero cylinder regions — `test01`'s signature, where the engine ships nothing
and RANSAC recovers 4/4 — ask the VLM whether cylinders are present, and only then let RANSAC
run. Blast radius is limited to models that currently produce nothing, so it cannot regress the
200 that work.

And it leaves the larger half untouched: over the 63 reverted models, segmentation already
proposes 561 cylinder regions against the 137 faces needed (4.1x). Those faces are found and
then discarded during solid assembly. No detector — dihedral, RANSAC, learned, or VLM — can
recover a face that is found and then thrown away.

### The 30b closes the gap but does not reach zero

`qwen3-vl:30b-a3b`, 2.2 s/part (spills past the 16 GB GPU, partly CPU): correct veto 20/27,
**wrong veto 12/109**. Note the two large models are NOT ordered the same way on both axes --
8b catches more negatives (23 vs 20), 30b loses far fewer positives (12 vs 22). They sit at
different operating points of the same classifier, 30b being readier to answer "cylinder
present". For a veto, 30b's bias is the useful one.

12 wrong vetoes out of 109 is 11 % of models losing real cylinders. **As a global gate that is
still disqualifying** and no further model size is available to try.

## The finding that changes the conclusion

The gate above was specified for a GLOBAL veto — consulted on every model. In the guarded
fallback role it is a different question, and the asymmetry inverts:

**The fallback only consults the VLM on models where the segmenter already returned zero
cylinder regions.** On those models a wrong veto costs *nothing*, because the engine is
shipping nothing there already. There is no recall to lose. The only thing the veto can do is
prevent RANSAC from fabricating.

That removes the disqualifying number entirely. The 12 wrong vetoes are all models
(`SpeedTestStructure`, `gancio_parametric`, `L04_pillow`, `L08_angle_plate`, ...) where the
engine DOES find cylinders, so the fallback never runs and the VLM is never asked.

On the reproducer the chain is correct end to end: `test01` -> engine finds 0 -> VLM says
cylinders present -> RANSAC returns 4/4 at 0.03 % radius accuracy.

## Re-measured on the TARGET host — nativedev has a GPU after all

Tommaso, twice: *"why are you computing on behemoth? mesh2step is a tool of Nativedev!!!!"*
and *"nativedev has a rtx 3090 24 gb"*. Both correct. `lspci` found an **RTX 3090 at
0000:65:00.0** with **no kernel module and no driver package installed** — so `nvidia-smi`
failed, Ollama reported `size_vram 0.0` on every model, all inference ran on CPU, and a 26 GB
model sat in system RAM. That RAM starvation is what had been OOM-killing background jobs all
session. "nativedev is CPU-only" was my inference from CLAUDE.md's silence plus observed
slowness; it was wrong, and the whole "too heavy for the target host" argument rested on it.

Installed with Tommaso's authorisation (`nvidia-driver-595-open` + `nvidia-utils-595`,
SecureBoot disabled so no signing, DKMS clean against 6.8.0-139, `modprobe` — **no reboot**,
therefore no majordomo restoration needed). Result: driver 595.84, CUDA 13.2, 24576 MiB
available; system RAM 39 GB used -> 10 GB.

| host | model | correct veto /27 | wrong veto /109 | s/part |
|---|---|---|---|---|
| behemoth (4070 Ti S, 16 GB) | 30b-a3b | 20 | 12 | 2.2 |
| **nativedev (3090, 24 GB)** | 30b-a3b | **21** | **11** | **11.3** |

Accuracy reproduces within noise across hosts, which is the claim that justified measuring it
remotely at all. **Latency does not**, and the reason is a deployment constraint, not raw speed:

### The GPU on nativedev is shared, and a 23 GB model does not fit beside its neighbours

Ollama logged `total="24.0 GiB" available="1.3 GiB"` and `llama runner started in 7.25 seconds`
*mid-run* — the VLM is evicted and reloaded whenever any other model is requested on this host
(supermemory's embedder, among others). The 11.3 s/part is mostly reload, not inference. A
30b-a3b can run on nativedev, but not as a co-tenant of a box that also serves other models
unless it is pinned or the neighbours are bounded.

## Status and recommendation

Measurement complete. Nothing in the engine has been touched by this arm.

**Recommended, and bounded:** the guarded fallback, `engine==0 cylinders` AND
`VLM says cylinders present` -> run RANSAC, take its cylinders as seeds. It cannot regress any
model the engine already handles, because it never runs on one.

**Not recommended:** a VLM veto anywhere in the main path (11 % of models would lose real
cylinders), and a VLM cylinder COUNT anywhere at all — counts were wrong on the very first
probe (2 for `test01`'s 4, 4 for the washer's 2) and were never used as a gate here.

**Still the larger prize, untouched by this arm:** 561 cylinder regions already found across
the 63 reverted models against 137 needed. Those die in solid assembly, not detection.
