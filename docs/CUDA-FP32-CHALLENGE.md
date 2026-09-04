# Challenge: can a bit-exact geometric-reconstruction engine be restructured so a GPU helps at all?

You are being asked to solve a hard systems/numerics problem. Read the whole brief before
answering. Everything you need is here; you have no access to the repository, and you must not
assume facts that are not stated below.

**A correct answer may well be "no, and here is the proof." That answer is welcome and will be
judged on the quality of its argument, not on its polarity.** A recommendation to abandon the GPU
entirely is a legitimate deliverable. So is a restructuring that makes the GPU pay. What will not
be accepted is an unquantified answer in either direction.

---

## 1. The system

`mesh2step` reconstructs analytic CAD surfaces — planes, cylinders, fillets — from a triangle
mesh, and emits STEP and DXF. Its "TrueForm" engine is a **bit-exact Python port of an existing
C++ reference implementation**. The port's acceptance criterion is not "close enough": the test
suite asserts that the engine's RESULT invariants match the reference field for field in double
precision, and that the produced DXF is **byte-identical** to the reference's. One ULP of
difference in a radius has, in practice, cost entire engineering sessions to chase.

The engine is float64 throughout, single-threaded, written in CPython over numpy.

Measured wall times on the target host (Xeon W-2245, 8 cores, AVX-512+FMA; RTX 3090, 24 GB):

| fixture | triangles | Python engine | C++ reference | ratio |
|---|---:|---:|---:|---:|
| handle-lock | 908 | 82.2 s | 2.34 s | 35.1x |
| Body11 | 15,300 | 1681 s | 81.95 s | 20.5x |

So: ~0.1 s per triangle. A user-facing conversion of a moderately sized part takes 28 minutes.
The stated target is a **10x** speedup. Someone proposed CUDA. This document asks you whether
that proposal can be rescued by restructuring, and if so how, with numbers.

## 2. The measured profile (do not re-derive; these are facts)

`cProfile` on handle-lock and a near-zero-overhead `py-spy` sampling run on Body11 agree:

- **292,526,544 Python function calls** for a 908-triangle mesh.
- Self time split on Body11: **numpy 54.5%, interpreted Python 45.4%, OCCT/CAD kernel 0.0%.**
  The CAD kernel does not appear in the profile at all; the cost is entirely numeric Python.
- One function, `law_chain_accept` (in `refit/lawband.py`), is **81.6% of the run** (cumulative).
  It is called 6,352 times because the greedy growing loops in `refit/segment.py` re-run the
  *entire* chain extraction from scratch for each candidate triangle addition:
  `law_chain_accept(mv, [*band.tris, t_add], ...)`. That is an O(n²) shape inside a greedy loop.
- Its children: `extract_chain` 52.7%, `_test_common_axis` 28.7%, `unique_positions` 21.8%,
  `recover_axis_dir` 10.4%.
- `unique_positions` is a literal O(n²) Python loop that calls `np.linalg.norm(p - q)` for every
  pair of 3-vectors — **9.5 million calls, 80% of all norm calls in the run**.

Primitive counts in one run, and their measured per-call cost **on 3-element vectors**:

| call | calls per run | numpy cost | equivalent scalar Python |
|---|---:|---:|---:|
| `np.linalg.norm` (3-vector) | 11,886,564 | 1,134 ns | **107 ns** |
| `np.cross` (3-vector) | 1,380,992 | **16,260 ns** | **153 ns** |
| `ndarray.dot` (3-vector) | 11,886,564 | 410 ns | — |
| `math.hypot` | 19,167,136 | — | — |

`np.cross` spends ~99% of its 16,260 ns in `moveaxis`, `normalize_axis_tuple`, `ravel`,
`transpose` and `list.insert` — generic n-dimensional axis plumbing wrapped around nine
multiplications.

## 3. The Amdahl fraction

Counting every floating-point operation the run actually performs, from profiler call counts
(cross=9 flops, norm=6, dot=5, hypot=4, wrap_pi=3, …): **288.8 Mflop for an 80-second run.**
Multiply by a 10x safety margin for anything uncounted: 2.89 Gflop.

- RTX 3090 at fp64 (0.556 TFLOP/s): **5.19 ms**
- one CPU core at a generous 5 GFLOP/s: **578 ms**
- measured wall time of that run: **80,000 ms**

**Accelerable fraction = 578 / 80,000 = 0.72%. Amdahl ceiling with the moved work made
completely free = 1.007x.** Not 9x short of the 10x target — three orders of magnitude short.
The remaining 99.3% is CPython interpreter and numpy dispatch overhead, which no GPU touches.

## 4. The GPU's own numbers on this workload

Measured with PyTorch 2.10+cu128 on the 3090, float64 3-vectors:

| quantity | value |
|---|---:|
| `torch.linalg.cross`, launch only | 8,535 ns |
| … + `cuda.synchronize()` (a real round trip) | **14,021 ns** |
| … + host→device→host transfer | **40,398 ns** |
| the scalar Python it would replace | **153 ns** |
| handle-lock vertex data (908 tri, f64) | 0.07 MB → 3.3 µs over PCIe4 x16 |
| Body11 vertex data (15,300 tri) | 1.10 MB → 55 µs |

The engine's control flow is data-dependent (greedy region growing, first-hit-wins merging, path
chaining), so a synchronise is forced after essentially every operation: 14,021 ns is the honest
per-op figure. **A GPU round trip is 92x slower than the scalar Python it replaces, 264x with a
transfer.** Naively moving `unique_positions`' 9.5M norms to CUDA takes the run from 82 seconds
to an estimated **37 hours**. Data volume is irrelevant here; granularity is everything.

## 5. The precision situation — the one place the GPU has real headroom

The RTX 3090 (GA102) runs fp64 at **1/64** of its fp32 rate: ~0.556 TFLOP/s, against roughly
**1.0 TFLOP/s fp64 on the host's 8-core Xeon with AVX-512 + FMA. In double precision the CPU is
faster than the GPU.** Only fp32 (~35 TFLOP/s) offers a hardware advantage — a ~60x swing, and
the only reason this document exists.

But fp32 cannot naively hold the algorithm's decisions at part scale. The decision threshold in
the hot growing loop is

```python
tau = max(5e-5, 4.0 * mv.weld_tol, 1e-6 * mv.diag, K_LAW_R_REL_GROW * b.radius)   # segment.py:2037
```

so the floor is **5e-5 mm**. fp32 ULP at a 306 mm coordinate (the real maximum in the handle-lock
fixture) is **3.05e-5 mm — 61% of the threshold**; at a 1000 mm coordinate it is 6.1e-5 mm,
*larger* than the threshold. Near-threshold membership tests become coin flips, and a flipped
membership changes the face count, which changes RESULT.

**However, the precision is being spent in the wrong place.** The algorithm never cares about the
306 mm coordinate itself; it asks whether a *residual* is within 5e-5 mm. On a centred residual of
magnitude 1e-3 mm, fp32 ULP is **1.16e-10 mm** — seven orders of margin. Translating to a local
origin before demoting to fp32 puts the precision where the question is. This is the standard
render-relative-to-eye / geodesy trick, and it is the strongest argument on the pro-GPU side.

Whatever happens, **final coordinates must be reproduced by the CPU in the reference's exact
arithmetic.** The GPU may decide *nothing* that it cannot prove; the parity contract is not
negotiable (see §8).

## 6. What has already been tried and measured — do not re-propose these

1. **Write CUDA kernels for the hot primitives.** Refuted by §3 and §4: 1.007x ceiling, and each
   kernel is 92x slower than the code it replaces.
2. **"GPU proposes, CPU verifies" as a filter, with the GPU doing the proposing.** The pattern is
   right, the placement is wrong: the GPU *adds* 14,021 ns per candidate to save 153 ns, so the
   filter loses before a single survivor is re-verified. The rejection rate is irrelevant — even a
   100%-rejecting filter is 92x slower than doing the work directly.
3. **Multiprocessing across mesh components.** ~1x on the fixtures that matter: handle-lock has
   one component, and Body11's cost sits inside a single sequential growing loop.
4. Already banked on the CPU, without a GPU, bit-identical where noted: an edge→triangle adjacency
   map (1.03x, provably identical), a squared-distance prefilter in `unique_positions` with the
   exact original arithmetic re-run on survivors (1.29x, bit-identical), and replacing numpy
   3-vector ops with scalar Python at audited call sites (1.62x). Combined: **2.08x on
   handle-lock, 2.64x on Body11.** Any proposal must be measured against *that* baseline, not the
   naive one.

## 7. The questions you must answer

**Q1 — Can the arithmetic be hoisted out of the sequential loop at all?**
The 11.9M norms are individually tiny and collectively enormous. They are demanded one at a time
by greedy region growing, whose result is **order-dependent**: it is a graph traversal, not a map.
Can that stage be reformulated — speculative/bulk-synchronous evaluation, frontier expansion in
waves, precomputing every candidate quantity up front and discarding the unused ones, or something
better — so the arithmetic becomes one large array operation while **the accepted sequence remains
provably identical to the greedy order**? If yes, give the reformulation, the argument for why the
accepted sequence is unchanged (an argument, not an assertion), and the wasted-work factor: how
many speculative evaluations per useful one, and at what mesh size does that ratio become fatal?
If no, say precisely which dependency makes it impossible, and whether a weaker restructuring
(batching *within* one `law_chain_accept` call rather than across calls) recovers anything.

**Q2 — Does centred-fp32 filtering with a rigorous error bound work?**
Compute in fp32 on locally-translated coordinates; escalate to exact CPU fp64 anything within a
proven error bound of a threshold. Derive that bound — I want the actual forward error analysis for
the relevant expression (a residual distance from a candidate axis, magnitude ~1e-3 mm, computed
from coordinates up to ~306 mm before centring), not a gesture at one. Say what makes the filter
**conservative** rather than merely approximate: what must be true for "fp32 says clearly outside"
to imply "fp64 would also say outside". Then give the break-even escalation rate: above what
fraction of escalated candidates does the scheme stop paying, given §4's launch costs?

**Q3 — Is the framing wrong?**
The C++ reference runs the *identical algorithm*, single-threaded, GPU-free, 20.5x faster. The
whole 10x target may simply be "stop being interpreted". If your honest conclusion is that
compilation (Cython, a C++ extension, Numba) dominates every GPU path on this workload, say so and
defend it with the same rigour you would apply to a kernel design — including what, if anything,
would still be left for a GPU *after* compilation removes the interpreter tax, and what measurement
would have to come back before revisiting the GPU.

## 8. The invariant you cannot trade

**Byte-identical output.** RESULT fields must match the reference in double precision, and the DXF
must be byte-identical. GPUs reorder reductions and apply FMA aggressively; the decision gates in
this engine compare things like `tilt * length > lim * 8.0` and `abs(dot) < 0.98`, where one ULP
changes which triangles join a band, which changes the face count, which changes the output. A
proposal that relaxes bit-exactness has not solved this problem — it has replaced it with an
easier one, and will be scored as a non-answer.

## 9. How your answer will be judged

- **Every claim quantified.** Expected speedup derived from the 0.72% accelerable fraction (or a
  justified new fraction, if your restructuring changes it — then show the new arithmetic). The
  batch size at which a kernel beats 153 ns per element of scalar Python, given a 14,021 ns
  synchronised round trip. The escalation rate a filter tolerates. Error bounds with their
  derivation.
- **"GPUs are massively parallel", "modern GPUs handle this well", or any unquantified appeal to
  parallelism is a failed answer.**
- State your assumptions explicitly and mark anything you could not derive from the numbers above.
- If two of your proposals conflict, say which you would actually do and why.
- Be brief where you are certain and detailed where the risk is. A short, correct "no" beats a long
  hopeful "yes".

Deliverable: a reasoned recommendation answering Q1, Q2 and Q3, with the numbers that make it
falsifiable, and an explicit statement of what measurement would prove you wrong.
