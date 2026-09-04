# CUDA plan for the TrueForm engine — and why the answer is "not CUDA"

Author: profiling session 2026-09-04, `main` @ 41068f6, host `nativedev`.
Status: **recommendation against CUDA, with a measured alternative that exceeds the target.**

---

## 0. The one-paragraph verdict

The target is a 10x speedup of TrueForm. **CUDA cannot deliver it: the measured
accelerable fraction is 0.72%, which puts the Amdahl ceiling for any GPU work at
1.007x — not 10x, but a rounding error.** The reason is not that the kernels would be
badly written; it is that an 80-second TrueForm conversion contains **289 Mflop of
actual floating-point arithmetic**, about **5 ms of RTX 3090 time**. The other 99.3% of
the wall clock is CPython interpreter and numpy dispatch overhead, which a GPU cannot
touch. Measured directly: `np.cross` on a 3-vector costs **16,260 ns**, while the same
cross product as a CUDA kernel round trip costs **14,021 ns** and **40,398 ns** with a
host↔device transfer — the GPU is *slower than the numpy call it would replace*, and
**92x slower than the 153 ns scalar Python** that is the actual right answer.
**However, the 10x target is comfortably reachable by another route.** The C++ reference
at `refs/stl2step` runs the identical algorithm on the same host, single-threaded and
GPU-free, **20.5x faster on Body11 (81.95 s vs 1681 s) and 35x faster on handle-lock
(2.34 s vs 82.2 s)**. The win is "stop being interpreted", not "start using the GPU".
A three-change prototype that removes some of the interpreter overhead already measured
**2.08x on handle-lock with bit-identical output, and 2.64x on Body11**, in one
afternoon, without touching the GPU. Sampling profiles of both fixtures put **OCCT at
0.0% of self time** and numpy 3-vector dispatch overhead at over half of it.

**Recommendation: do not pursue CUDA. Ship the job queue, then buy the 10x by
compiling the hot path — with `refs/stl2step` as both the blueprint and the oracle.**

---

## 1. Hardware reality on nativedev

`nativedev` **does** have a usable NVIDIA GPU, so the premise that it might not is
settled — the constraint is the workload, not the hardware.

| Item | Value | Command |
|---|---|---|
| GPU | NVIDIA GeForce RTX 3090, 24 GB (GA102) | `nvidia-smi`, `lspci \| grep -i nvidia` |
| Driver | 580.159.03, CUDA runtime 13.0 | `nvidia-smi` |
| Already in use | ollama holding 7,748 MiB | `nvidia-smi` |
| `nvcc` | **not on PATH**, no `/usr/local/cuda*` | `nvcc --version`, `ls -d /usr/local/cuda*` |
| PyTorch | **2.10.0+cu128, CUDA works** | `python3 -c "import torch"` |
| CuPy / Numba / Warp / Taichi / PyOpenCL / Cython | **none installed** | import probe |
| CPU | 16 cores, 62 GB RAM | `nproc`, `free -g` |
| numpy / scipy | 2.4.2 / 1.17.0, scipy-openblas 0.3.31 | `numpy.show_config()` |

So a GPU stack is *available* (PyTorch ships its own CUDA runtime; CuPy or Numba would
need `nvcc`, i.e. installing `cuda-toolkit`). Nothing needs installing to prove the point
below, because PyTorch already answered it.

Note the fp64 caveat that would matter *if* the arithmetic mattered: the RTX 3090 runs
double precision at **1/64 of its fp32 rate (0.556 TFLOP/s)**. TrueForm is entirely
float64 and cannot be demoted to float32 without destroying parity on the first
comparison. A 3090 is close to the worst consumer card for this kind of work.

---

## 2. The measured profile

### 2.1 Fixture choice

`tests/data/corpus/` holds six fixtures. Measured TrueForm wall times (`python3 -m
mesh2step.cli <F>.stl -o /tmp/out.step --engine trueform --unify-angle 5 --quiet`,
timed with `/usr/bin/time`):

| fixture | triangles | mesh2step wall | reference wall | ratio |
|---|---:|---:|---:|---:|
| S09 | 54 | 1.96 s | 0.17 s | 11.5x |
| nonprismatic-control | 96 | 2.16 s | 0.14 s | 15.4x |
| **handle-lock** | **908** | **82.2 s** | **2.34 s** | **35.1x** |
| Body28 | 14,126 | 30–60 min | — | — |
| Body11 | 15,300 | 1681 s | **81.95 s** | **20.5x** |

**I profiled `handle-lock`.** It is the right fixture: at 908 triangles it exercises the
full law-band recognition path (17 cylinders, 11 distinct radii recovered — the same
machinery Body11 spends its 28 minutes in), yet it completes in 82 s, so an experiment
takes ~1.5 minutes instead of ~28. Its cost per triangle (90 ms) is the same order as
Body11's (110 ms), so it is representative rather than a toy. S09 and
nonprismatic-control are too small — the latter reverts to faceted and never runs the
interesting stage at all.

### 2.2 Where the time goes

`cProfile` on handle-lock (159.1 s under the profiler, 82.2 s without — 1.94x profiler
overhead, so read the *ratios*, not the absolute seconds).
**292,526,544 function calls for a 908-triangle mesh.** That number is the whole story.

Aggregated by module (`tottime`):

| bucket | tottime | share | ncalls |
|---|---:|---:|---:|
| numpy dispatch machinery | 63.90 s | **40.2%** | 75,577,107 |
| `refit/lawband.py` | 45.39 s | 28.5% | 28,081,732 |
| `refit/segment.py` | 15.31 s | 9.6% | 502,759 |
| `ndarray.dot` (3-vectors) | 8.58 s | 5.4% | 11,886,564 |
| builtins (`len`, `abs`, `issubclass`, `hypot`…) | ~11 s | ~7% | >100M |
| **OCCT / OCP** | **0.00 s** | **0.0%** | 0 |

**`build.py` and OCCT do not appear in the profile at all.** The brief asked whether the
time might be in OCCT rather than in numeric Python — it is not. It is *entirely* numeric
Python, and specifically the interpreter overhead around it.

Call-tree, mesh2step functions by cumulative time:

| function | cumtime | share | ncalls |
|---|---:|---:|---:|
| `lawband.py:770 law_chain_accept` | 129.90 s | **81.6%** | 6,352 |
| `lawband.py:550 extract_chain` | 83.84 s | 52.7% | 6,352 |
| `segment.py:1907 _grow_leftover_law_bands` | 55.58 s | 34.9% | 1 |
| `lawband.py:702 _test_common_axis` | 45.69 s | 28.7% | 6,345 |
| `lawband.py:311 unique_positions` | 34.77 s | 21.8% | 6,352 |
| `segment.py:1990 _absorb_leftover_into_bands` | 23.25 s | 14.6% | 1 |
| `segment.py:2652 _build_tri_path_chain` | 19.97 s | 12.6% | 5 |
| `lawband.py:250 recover_axis_dir` | 16.53 s | 10.4% | 6,352 |
| `segment.py:2640 _tri_in_patch_neighbors` | 13.77 s | 8.7% | 28,439 |

One function, `law_chain_accept`, is **81.6% of the run**. It is called 6,352 times
because the growing loops in `segment.py` (lines 1959, 1970, 2025, 2055, 2135, 2147)
re-run the *entire* chain extraction from scratch for each candidate triangle addition:
`law_chain_accept(mv, [*b.tris, t_add], ...)`. That is an O(n²) shape in a greedy loop.

### 2.2b Corroborated on Body11 by sampling (no profiler distortion)

To rule out cProfile distortion and confirm the shape holds on the fixture that actually
hurts, I sampled a full **Body11** run with `py-spy record -r 50 --format raw` (near-zero
overhead — 86,251 samples over 1,725 s, matching the 1,681 s baseline).

Self time (leaf frame):

| frame | self |
|---|---:|
| `numpy/linalg/_linalg.py norm` (4 lines) | **11.8%** |
| `numpy/_core/numeric.py cross` (5 lines) | **9.1%** |
| `numpy` `normalize_axis_tuple` + `moveaxis` + genexpr | **11.9%** |
| `lawband.py:316 unique_positions` | 5.4% |
| `build.py:1788 _orient_face_walk` | 4.9% |
| `build.py:1920 rebuild_mesh_edges` | 2.8% |
| `mesh_view.py:103 tri_area` | 2.1% |

**Self-time split: numpy 54.5%, mesh2step Python 45.4%, OCCT/OCP 0.0%, other 0.1%.**

On-stack (inclusive): `segment` 53.8%, `law_chain_accept` 35.1%, `_claim_law_bands_l`
31.4%, `_grow_leftover_law_bands` 31.2%, `_grow_provisional_a2` 23.3%, `tri_area` 22.7%,
`_test_common_axis` 15.5%, `extract_chain` 14.9%, `unique_positions` 14.6%.

Two conclusions the big fixture adds. First, **OCCT is 0.0% on Body11 as well** — the
"maybe it's all in `build.py`/OCCT" hypothesis is dead on both fixtures. Second, the
`build.py` frames that *do* appear (`_orient_face_walk`, `rebuild_mesh_edges`, 7.7%
combined) are **interpreted Python inside `build.py`**, not OCCT calls — so they belong to
the same diagnosis and the same cure, not a different one.

### 2.3 The two primitives that dominate, and their true cost

| call | ncalls in one run | measured cost each |
|---|---:|---:|
| `np.cross` on a 3-vector | 1,380,992 | **16,260 ns** |
| `np.linalg.norm` on a 3-vector | 11,886,564 | **1,134 ns** |
| `ndarray.dot` on a 3-vector | 11,886,564 | 410 ns |

Against hand-written scalar Python doing the identical arithmetic:

| operation | numpy | scalar Python | speedup |
|---|---:|---:|---:|
| 3-vector cross | 16,260 ns | **153 ns** | **106.2x** |
| 3-vector norm | 1,134 ns | **107 ns** | **10.6x** |

`np.cross` spends 99% of its time in `moveaxis` (7,980 ns/call), `normalize_axis_tuple`,
`ravel`, `transpose` and `list.insert` — generic n-dimensional axis plumbing, to compute
nine multiplications. The codebase already knows this: `lawband.py:407 _dot3` and
`lawband.py:416 _modulus3` exist precisely because `np.dot`/`np.linalg.norm` were the
wrong arithmetic for parity (PORT-MAP §7f, §7j). **The parity fix and the performance fix
are the same fix**, which is the single most useful structural fact in this document.

Call-site attribution for the two hot primitives:

`np.cross` — `lawband.py:702 _test_common_axis` (824,694), `lawband.py:146
_unit_tri_normal` (276,128), `mesh_view.py:101 tri_area` (103,279), `segment.py:365
pca_plane` (77,517), `mesh_view.py:111 tri_normal` (72,248).

`np.linalg.norm` — **`lawband.py:311 unique_positions` (9,543,271 = 80% of all norm
calls)**, `_test_common_axis` (1,649,388), `_unit_tri_normal` (276,128),
`extract_chain` (133,571).

`unique_positions` is a literal O(n²) Python loop that calls `np.linalg.norm(p - q)` for
every pair — 9.5 million times, from only 6,352 invocations (~1,500 norm calls each).

---

## 3. Amdahl, stated numerically — the CUDA ceiling

The accelerable fraction for a GPU is the fraction of wall time spent doing arithmetic
that a GPU could do. Counting every floating-point operation the run actually performs,
from the profiler's own call counts:

| primitive | calls | flops each | flops |
|---|---:|---:|---:|
| `np.cross` | 1,380,992 | 9 | 12,428,928 |
| `np.linalg.norm` | 11,886,564 | 6 | 71,319,384 |
| `ndarray.dot` | 11,886,564 | 5 | 59,432,820 |
| `math.hypot` | 19,167,136 | 4 | 76,668,544 |
| `_dot3` | 2,194,443 | 5 | 10,972,215 |
| `wrap_pi` | 19,327,582 | 3 | 57,982,746 |
| **total** | | | **288,804,637 (289 Mflop)** |

Apply a **10x safety margin** for everything not counted → 2.89 Gflop.

- On the RTX 3090 at 0.556 TFLOP/s fp64: **5.19 ms**
- On one CPU core at a generous 5 GFLOP/s: **578 ms**
- Measured wall time of that same run: **80,000 ms**

**Accelerable fraction = 578 / 80,000 = 0.72%.**

Amdahl, with the moved part becoming *completely free*:

```
speedup_max = 1 / (1 - 0.0072) = 1.007x
```

For reference, the fractions the brief named: 90% → 10x, 80% → 5x, 70% → 3.3x.
**We are at 0.72% → 1.007x.** The GPU is not 9x short of the target; it is three orders
of magnitude short. No kernel, no batching strategy, no stream configuration changes
this, because there is no arithmetic there to accelerate.

### 3.1 The transfer and launch cost, for the sizes actually involved

Even at the 200 MB upload cap the data is trivially small, and the launch overhead
dwarfs everything:

| quantity | value |
|---|---:|
| handle-lock vertex data (908 tri, float64) | 0.07 MB → 3.3 µs over PCIe4 x16 |
| Body11 vertex data (15,300 tri) | 1.10 MB → 55 µs |
| 200 MB STL upload cap (~4M tri) | 288 MB → 14.4 ms |
| `torch.linalg.cross` on a 3-vector, launch only | **8,535 ns** |
| … + `cuda.synchronize()` (a real round trip) | **14,021 ns** |
| … + host→device→host on a 3-vector | **40,398 ns** |
| the scalar Python it would replace | **153 ns** |

The engine's data-dependent control flow (greedy region growing, first-hit-wins merging,
`walk_from` path chaining) forces a synchronise after essentially every operation, so
14,021 ns is the honest per-op figure, not 8,535 ns. **A GPU call is 92x slower than the
scalar Python and 264x slower with a transfer.** Moving `unique_positions`' 9.5 million
norms to the GPU would take the run from 82 seconds to roughly **37 hours**.

---

## 4. The parity tax, and why it points away from the GPU anyway

Bit-exactness is the acceptance criterion (`tests/test_parity.py::test_result_invariants_
match_reference`, `tests/test_dxf.py::test_dxf_byte_identical`). GPUs change reduction
order and use FMA aggressively; PORT-MAP §7f/§7j record that *one ULP* from `np.dot` vs
`gp_XYZ::Dot`, and from `np.linalg.norm` vs `gp_XYZ::Modulus`, cost an entire session.

Classifying the stages as the brief asks:

- **Decision stages** — `law_chain_accept`'s four gates (`_test_equal_theta`,
  `_test_r_cons`, `_test_common_axis`, `_test_on_surface`), and the accept/reject in the
  growing loops. Output is a discrete classification. **These are not safe just because
  they end in a comparison**: `_test_common_axis` compares `tilt * length > lim * 8.0`
  and `abs(dot) < 0.98` — a near-tie flipped by one ULP changes which triangles join the
  band, which changes the face count, which changes RESULT. A GPU here is a correctness
  hazard, not merely a numerical one.
- **Coordinate stages** — `extract_chain`/`recover_axis_dir`/`ls_bisector_center` produce
  axis directions, origins and radii that are written into OCCT geometry and printed into
  RESULT and the DXF. Bit-exactness is required literally.
- **Provably parity-neutral** — `segment.py:2640 _tri_in_patch_neighbors` is **pure
  integer work**: it scans edge indices and returns `sorted(nb)`, a set of triangle IDs.
  There is no floating point in it at all, so an equivalent implementation is provably
  identical, not merely empirically identical. This is the only stage where the safety
  argument is a proof rather than a test.

**The filter pattern (GPU proposes, CPU verifies) — evaluated seriously and rejected.**
It is the right *pattern*, and the plan below uses it — but on the CPU, not the GPU. The
economics: for it to pay, the GPU must remove more time than the surviving re-verification
adds. Here the GPU *adds* 14,021 ns per candidate to save 153 ns, so the filter loses
before any survivor is re-verified. The rejection rate is irrelevant: even a filter
rejecting 100% of candidates would be 92x slower than doing the work directly.

The same pattern *on the CPU* is a clear win, and I measured it (§5.2): in
`unique_positions`, prefilter on squared distance (`dx²+dy²+dz² > (merge·1.0000001)²`
⇒ provably farther than `merge`, skip with no `sqrt`), then run **the exact reference
arithmetic on the survivors**. Decisions are produced by the original code path in every
case that could possibly be a near-tie. Measured: **RESULT bit-identical, 1.29x faster.**

---

## 5. Measured alternatives — what actually beats CUDA

### 5.1 The existence proof: the same algorithm, compiled

`refs/stl2step` is the parity oracle, runs on this host, is single-threaded and uses no
GPU. Measured with `/usr/bin/time` via `refs/stl2step/RUN.sh <F>.stl --engine trueform
--unify-angle 5`:

| fixture | reference | mesh2step | **compiled speedup** |
|---|---:|---:|---:|
| S09 | 0.17 s | 1.96 s | 11.5x |
| nonprismatic-control | 0.14 s | 2.16 s | 15.4x |
| handle-lock | 2.34 s | 82.2 s | **35.1x** |
| Body11 | **81.95 s** | 1681 s | **20.5x** |

**The 10x target is already exceeded by an artefact sitting in the repo.** This is not an
estimate; it is the same algorithm producing the same answers 20–35x faster, and its
output *is* the definition of correct. That reframes the whole exercise: the gap is not
"missing hardware acceleration", it is "20x of CPython interpreter tax".

### 5.2 Prototyped now, bit-identical, no GPU

Three changes, applied as **runtime monkeypatches** in the scratchpad (no source file was
edited), on handle-lock, comparing the full RESULT dict field by field:

| variant | wall | vs baseline | RESULT |
|---|---:|---:|---|
| baseline | 82.31 s | 1.00x | — |
| **A** `_tri_in_patch_neighbors` → precomputed edge→triangle adjacency | 79.97 s | 1.03x | **IDENTICAL** |
| **B** `unique_positions` → squared-distance prefilter + exact sqrt on survivors | 63.66 s | **1.29x** | **IDENTICAL** |
| **S** `np.cross`/`np.linalg.norm` on 3-vectors → scalar | 51.03 s | **1.62x** | 1 field, 2 ULP |
| **A+B+S combined** | **38.39 s** | **2.08x** | 1 field, 2 ULP |

Repeated on **Body11** (under `watchjob`, concurrently with the py-spy run, so if
anything pessimistic): **1681 s → 637.38 s = 2.64x.** The win grows with mesh size, as
expected for fixes that attack O(n²) inner loops. Note Body11 currently reverts both
components to faceted (a known port gap, PORT-MAP §7e/§7h), so this run is a **timing**
measurement; its RESULT is not a parity check and is not claimed as one. Body11 at 637 s
against the reference's 81.95 s leaves **7.8x still on the table**, which is exactly the
remaining interpreter tax that §5.1 says compilation collects.

The single divergent field under S is `smooth_max_edge_tol_mm`:
`2.118382793276948e-05` → `2.1183827932769533e-05`. A and B alone are bit-identical; the
2 ULPs come **only** from the blanket `norm` substitution. That is precisely the §7j
hazard: where the reference calls `gp_XYZ::Modulus`, scalar `sqrt(x²+y²+z²)` is the
*correct* spelling and `np.linalg.norm` is the bug; where it calls something else, it is
not. **The fix is the per-call-site audit the port already does**, using `_dot3`/
`_modulus3`, verified by the existing parity tests — not a blanket patch. So S is worth
1.62x and is *parity-improving* when done properly, but it must be done one call site at
a time.

### 5.3 The alternatives, ranked

| approach | measured/estimated | parity risk | effort | verdict |
|---|---|---|---|---|
| **Compile the hot path (Cython / C++ ext / Numba-CPU) covering `lawband.py` + `segment.py` hot functions** | **10–20x** (bounded below by the reference's 20.5x) | Low — same arithmetic, same order; C is *closer* to the reference than numpy is | High | **Recommended endpoint** |
| **Call-site scalarisation (`_dot3`/`_modulus3` everywhere)** | **1.62x measured** | Low, and *reduces* divergence | Low | **Do first** |
| **Algorithmic: `unique_positions` prefilter, adjacency map, memoise `law_chain_accept`** | **1.29–1.35x measured** | None (proven for A, exact-equivalent for B) | Low | **Do first** |
| Job queue in `webapp/` | 0x latency, fixes the product | None | Low | Already planned; orthogonal |
| Multiprocessing across components | **~1x on the fixtures that matter** — handle-lock has 1 component, Body11's cost is inside one growing loop; the greedy growth is inherently sequential | None | Medium | **Does not pay here** |
| **CUDA** | **1.007x ceiling; realistically 100–1000x slower** | Severe (FMA/reduction order vs a ULP-exact contract) | Very high | **Reject** |

On the reference's `parallelFor`: I searched `refs/stl2step` for `parallelFor`,
`std::thread`, `OSD_Parallel` and `omp` and found **no such parallelism in the engine
source** — the only hits were unrelated lines in `tests/`. The reference achieves its
20.5x single-threaded. Parallelism is not where its advantage comes from, which reinforces
the diagnosis: the gap is interpretation, not concurrency.

---

## 6. The deployment picture

`webapp/server.py:94` calls `convert_trueform(...)` **synchronously inside the request
handler** (`POST /api/convert`, `MAX_UPLOAD_BYTES = 200 MB`, 285 lines total). A Body11
conversion blocks a uvicorn worker for 28 minutes.

Per the coordinator's direction, the job queue is **planned and assumed**, and users are
few, so GPU multi-tenancy is a non-problem and throughput is not the metric. Taking that
as given:

- **The metric is single-conversion latency**, and the ranking in §5.3 is already on that
  metric. Only the compiled-hot-path work and the §5.2 fixes move it. CUDA does not.
- **The queue is what saves the HTTP request, not the kernel.** A 28-minute synchronous
  request dies at a proxy regardless of speed. Even at full reference speed Body11 takes
  **81.95 s**, which is still past a comfortable HTTP timeout, and the 200 MB cap admits
  meshes ~260x larger than Body11. So the queue is necessary *independently of any
  optimisation*, and no amount of speedup removes the need for it. **I explicitly do not
  build the CUDA case on rescuing the timeout.**
- **Product risk to flag:** with the current synchronous path and no timeout, a single
  large upload can pin a worker for an unbounded time. That is the highest-severity item
  in this document and it is fixed by the queue, cheaply. Recommend it ships before any
  performance work.
- **GPU serialisation** is moot under this recommendation, since nothing goes on the GPU.
  Worth noting that ollama already holds 7.7 GB of the 3090 anyway.

---

## 7. Staged proposal

Each stage names the command that verifies it. The pass criterion throughout is the
existing contract: **RESULT fields match the reference exactly and the DXF is
byte-identical.**

```bash
# Fast gate (~11 min, currently 86 passed / 1 failed — that 1 is the known pre-existing
# failure; the criterion is "no NEW failure and the same 86 pass")
python3 -m pytest -q tests/ -k "not Body11 and not Body28"

# Targeted parity gate
python3 -m pytest -q tests/test_parity.py::test_result_invariants_match_reference \
                     tests/test_dxf.py::test_dxf_byte_identical

# Fixture-level A/B (bit-exact RESULT diff against the reference)
./refs/stl2step/RUN.sh tests/data/corpus/handle-lock.stl -o /tmp/ref.step --engine trueform --unify-angle 5
python3 -m mesh2step.cli tests/data/corpus/handle-lock.stl -o /tmp/ours.step --engine trueform --unify-angle 5 --quiet
```

### Milestone 0 — kill or confirm, ~1 day

Land change **A** (`_tri_in_patch_neighbors` → precomputed edge→triangle adjacency map,
~20 lines in `segment.py`). It is pure integer work, so identity is provable, and it is
already prototyped and measured bit-identical.

*Pass criterion:* fast suite still 86 passed / 1 failed; handle-lock RESULT
byte-identical to the current output. *Expected:* ~1.03x. Its value is not the speed — it
is that it establishes the measure-patch-verify loop on a change that cannot be wrong.

### Milestone 1 — the cheap measured win, ~3 days

Land **B** (`unique_positions` squared-distance prefilter, exact arithmetic on
survivors) and begin **S** as a per-call-site audit: replace `np.cross`/`np.linalg.norm`/
`np.dot` on 3-vectors with `_cross3`/`_modulus3`/`_dot3` **only where the C++ reference
uses the corresponding `gp_XYZ` method**, one call site at a time, running the parity gate
after each. Start with the five sites the profile names: `_test_common_axis`,
`_unit_tri_normal`, `tri_area`, `tri_normal`, `pca_plane`.

*Pass criterion:* parity gate green after **every individual** call site; the
`smooth_max_edge_tol_mm` field must return to `2.118382793276948e-05`.
*Expected:* **2.08x measured on handle-lock, 2.64x on Body11** (Body11 1681 s → 637 s),
with parity strictly improved rather than risked.

**This milestone alone is worth more than the entire CUDA programme's theoretical
ceiling** (2.0x vs 1.007x), which is the cheapest possible way to prove the
recommendation.

### Milestone 2 — the decision point, ~1 week

Re-profile after Milestone 1 and re-derive the remaining distribution. Then choose
between (a) continuing targeted Python-level work for another ~1.5–2x, and (b) compiling
`lawband.py`'s hot functions (`extract_chain`, `_test_common_axis`, `unique_positions`,
`recover_axis_dir` — the four that are 81.6% of the run) as a Cython or C++ extension.

Option (b) is what reaches 10x. Its parity argument is unusually strong: writing these
functions in C means writing *the reference's own arithmetic in the reference's own
language*, so the port becomes more faithful rather than less. `refs/stl2step` supplies
both the source to transcribe and the oracle to check against.

*Pass criterion:* full suite including Body11 and Body28, plus
`test_dxf_byte_identical`. *Target:* Body11 under 170 s (10x), with the reference's
81.95 s as the stretch goal and natural floor.

### Explicitly not planned

No CUDA work. If it is ever revisited, the trigger condition should be stated as a
measurement, not a preference: **CUDA becomes worth reconsidering only if a future
profile shows >50% of wall time in dense float64 array operations on arrays of ≥10⁵
elements.** Today that figure is 0.72% on arrays of 3.

---

## 8. Reproducing every number here

All experiments ran on `nativedev`; scratchpad artefacts in
`/tmp/claude-1000/-home-tommaso-projects-mesh2step/55ed36d6-4f09-4e83-a602-2227174fbd8a/scratchpad/`.
No source file was modified — the optimisation experiments are runtime monkeypatches
(`combo.py`, `optexp.py`, `scalarize.py`) that import the real engine and replace
functions in-process.

| number | how |
|---|---|
| GPU inventory | `nvidia-smi`, `lspci \| grep -i nvidia`, `nvcc --version` |
| fixture wall times | `/usr/bin/time -f "wall %e s" python3 -m mesh2step.cli … --engine trueform --unify-angle 5 --quiet` |
| reference wall times | `/usr/bin/time -f "REF wall %e s" ./refs/stl2step/RUN.sh … --engine trueform --unify-angle 5` |
| the handle-lock profile | `cProfile` around `convert_trueform`, dumped to `hl.pstats`, aggregated with `pstats` |
| the Body11 profile | `py-spy record -r 50 --format raw` (installed to the scratchpad, not the system env); 86,251 samples aggregated as collapsed stacks |
| primitive costs | `timeit`, 200,000 iterations each |
| GPU launch/transfer costs | `torch.linalg.cross` on a float64 3-vector with `torch.cuda.synchronize()`, 3,000–20,000 iterations |
| flop count | profiler call counts × flops per primitive, ×10 safety margin |
| A/B/S speedups | `combo.py` / `optexp.py`, full RESULT dict compared field by field |

Long-running jobs (`m2s-body11-pyspy`, `m2s-b11-combo`) were launched under
`~/.claude/skills/watchjob/scripts/watchjob.sh` per repo policy, with child output
redirected to files.
