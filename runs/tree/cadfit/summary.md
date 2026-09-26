# CADFit on the 39 mechparts, measured with our scorer (bd projects-wtge, 2026-09-26)

CADFit fb31f63 (github ghadinehme/CADFit, CC BY-NC 4.0 + provisional patent), default settings
(`run_pipeline.py <dir>`, 1 residual iteration, no `--fillet-chamfer`); nativedev (3 pipelines x 5 inner workers)
and behemoth (parts 8, 30-37, run in /tmp/cadfit-worker, 8 inner workers, outputs copied back). Each final script
`out/<n>/best_greedy_parallel_iterative.py` was converted to the tree IR by `tools/tree/cadquery_ir.py` (box frame
undone) and measured with `analyse.measure`: score = IoU + 0.5 (explained - extra), merit = score - 0.001 steps,
same tolerance as analyse. "+ our edge_mods/prune" = the converted tree passed through `PR.edge_mods` + `PR.prune`
(analyse's finishing), then measured again. Current = runs/tree/corpus v6, else v5; reverse_steps = the coordinator's
reference numbers for 7, 21, 22, 24, 2. WIN = best CADFit merit above every reference merit.

"CADFit solid score" measures CADFit's own solid (its stacked solids fused and cleaned); it differs from the tree
where planes are off the principal axes (dropped by the converter) or where OCCT's fused solid keeps seams that the
sampled deviation counts as extra. "CADFit own IoU" is CADFit's final_iou.json (its metric, after alpha-wrap).

| part | current run | current score/steps (merit) | reverse_steps score/steps (merit) | CADFit solid score | CADFit tree score/steps (merit) | + our edge_mods/prune | our IoU | CADFit own IoU | min | not mapped |
|---|---|---|---|---|---|---|---|---|---|---|
| 7 | v6 | 1.4984/3 (1.4954) | 1.5000/3 (1.4970) | 1.4561 | 1.4561/1 (1.4551) | 1.4561/1 (1.4551) | 0.991 | 0.977 | 9.8 |  |
| 21 | v6 | 1.4988/3 (1.4958) | 1.4991/3 (1.4961) | 1.4383 | 1.4382/1 (1.4372) | 1.4980/3 (1.4950) | 0.9903 | 0.975 | 1.9 |  |
| 22 | v6 | 1.4978/3 (1.4948) | 1.4997/3 (1.4967) | 1.2523 | 1.2517/1 (1.2507) | 1.4005/3 (1.3975) | 0.9393 | 0.919 | 5.2 |  |
| 24 | v6 | 1.4998/3 (1.4968) | 1.4994/3 (1.4964) | 1.4717 | 1.4714/1 (1.4704) | 1.4714/1 (1.4704) | 0.9939 | 0.988 | 5.9 |  |
| 2 | v6 | 1.4333/16 (1.4173) | 1.4407/7 (1.4337) | 1.1253 | 1.1256/5 (1.1206) | 1.1333/10 (1.1233) | 0.8879 | 0.849 | 13.3 |  |
| 1 | v6 | 1.4720/48 (1.4240) |  | 0.8462 | 0.8458/1 (0.8448) | 0.8431/2 (0.8411) | 0.7768 | 0.753 | 32.6 |  |
| 3 | v6 | 1.4831/26 (1.4571) |  | 1.2123 | 1.2605/13 (1.2475) | 1.3434/11 (1.3324) | 0.9261 | 0.885 | 28.3 |  |
| 4 | v6 | 1.4798/19 (1.4608) |  | 1.2655 | 1.2638/5 (1.2588) | 1.2638/6 (1.2578) | 0.9392 | 0.539 | 27.2 |  |
| 5 | v6 | 1.4538/21 (1.4328) |  | -0.5 | 1.0922/7 (1.0852) | 1.1064/15 (1.0914) | 0.874 | 0.863 | 23.0 | pad skipped: sketch plane normal [0.991, -0.0, 0.136] is off the principal axes; pad skipped: sketch plane normal [0.78, 0.0, -0.626] is off the principal axes |
| 6 | v6 | 1.4370/31 (1.4060) |  | 0.6343 | 0.6338/1 (0.6328) | 0.6338/1 (0.6328) | 0.6059 | 0.609 | 14.1 |  |
| 8 | v5 | 1.4971/9 (1.4881) |  | 1.435 | 1.4351/5 (1.4301) | 1.4348/7 (1.4278) | 0.9622 | 0.943 | 7.2 |  |
| 9 | v6 | 1.4994/7 (1.4924) |  | 1.0167 | 1.0167/1 (1.0157) | 1.0167/1 (1.0157) | 0.9013 | 0.919 | 11.5 |  |
| 10 | v6 | 1.4955/5 (1.4905) |  | 1.4297 | 1.4299/1 (1.4289) | 1.4296/4 (1.4256) | 0.9783 | 0.977 | 10.5 |  |
| 11 | v5 | 1.4976/2 (1.4956) |  | 1.1747 | 1.1056/10 (1.0956) | 1.1085/13 (1.0955) | 0.9302 | 0.908 | 15.3 | pad skipped: sketch plane normal [0.866, 0.5, -0.0] is off the principal axes; pad skipped: sketch plane normal [0.866, 0.5, -0.0] is off the principal axes |
| 12 | v5 | 1.4962/10 (1.4862) |  | 1.14 | 1.2672/5 (1.2622) | 1.2682/8 (1.2602) | 0.9945 | 0.948 | 19.5 |  |
| 13 | v5 | 1.5000/4 (1.4960) |  | 1.4861 | 1.4861/1 (1.4851) | 1.4861/2 (1.4841) | 0.9861 | 0.943 | 2.0 |  |
| 14 | v5 | 1.4999/5 (1.4949) |  | 1.1703 | 1.1703/1 (1.1693) | 1.2718/3 (1.2688) | 0.8688 | 0.866 | 45.8 |  |
| 15 | v5 | 1.5000/4 (1.4960) |  | 1.5 | 1.5000/1 (1.4990) | 1.5000/1 (1.4990) **WIN** | 1.0 | 0.995 | 1.7 |  |
| 16 | v5 | 1.4989/4 (1.4949) |  | 0.7453 | 0.7450/2 (0.7430) | 0.8709/3 (0.8679) | 0.933 | 0.831 | 4.6 |  |
| 17 | v5 | 1.5000/2 (1.4980) |  | 1.4252 | 1.4252/1 (1.4242) | 1.4252/1 (1.4242) | 0.96 | 0.952 | 8.1 |  |
| 18 | v5 | 1.5000/4 (1.4960) |  | 1.4465 | 1.4466/3 (1.4436) | 1.4994/7 (1.4924) | 0.9913 | 0.972 | 6.2 |  |
| 19 | v5 | 1.4870/6 (1.4810) |  | 0.9202 | 0.9204/2 (0.9184) | 0.9207/4 (0.9167) | 0.7824 | 0.848 | 3.2 |  |
| 20 | v5 | 1.4964/5 (1.4914) |  | 1.4425 | 1.4426/1 (1.4416) | 1.4714/4 (1.4674) | 0.9701 | 0.913 | 8.3 |  |
| 23 | v5 | 1.4828/9 (1.4738) |  | 0.9946 | 0.9946/1 (0.9936) | 0.9946/1 (0.9936) | 0.9908 | 0.859 | 30.8 |  |
| 25 | v5 | 1.4961/6 (1.4901) |  | 0.834 | 0.8169/5 (0.8119) | 0.9430/5 (0.9380) | 0.7595 | 0.783 | 29.4 | pad skipped: sketch plane normal [0.0, 1.0, -0.003] is off the principal axes; pad skipped: sketch plane normal [0.0, 1.0, -0.003] is off the principal axes |
| 26 | v6 | 1.4993/11 (1.4883) |  | 0.4866 | 0.4863/1 (0.4853) | 0.4901/2 (0.4881) | 0.6416 | 0.665 | 30.3 |  |
| 27 | v6 | 1.1588/14 (1.1448) |  | 0.9312 | 0.9312/1 (0.9302) | 1.1143/6 (1.1083) | 0.7694 | 0.728 | 17.9 |  |
| 28 | v5 | 1.5000/7 (1.4930) |  | 1.4379 | 1.4379/1 (1.4369) | 1.4996/3 (1.4966) **WIN** | 0.9876 | 0.979 | 3.3 |  |
| 29 | v5 | 1.4976/2 (1.4956) |  | 1.1956 | 1.1024/5 (1.0974) | 1.1024/5 (1.0974) | 0.943 | 0.907 | 26.2 | pad skipped: sketch plane normal [-0.247, 0.969, 0.001] is off the principal axes; pad skipped: sketch plane normal [-0.474, -0.88, -0.001] is off the principal axes |
| 30 | v6 | 1.4887/4 (1.4847) |  | 1.2413 | 1.2413/1 (1.2403) | 1.2413/1 (1.2403) | 0.9947 | 0.917 | 4.5 |  |
| 31 | v5 | 1.4953/6 (1.4893) |  | 1.478 | 1.4778/3 (1.4748) | 1.4798/4 (1.4758) | 0.9941 | 0.965 | 5.9 |  |
| 32 | v5 | 1.4981/5 (1.4931) |  | 1.2372 | 1.2375/10 (1.2275) | 1.2813/11 (1.2703) | 0.929 | 0.887 | 6.1 |  |
| 33 | v6 | 1.4927/10 (1.4827) |  | 1.2882 | 1.2880/1 (1.2870) | 1.2880/1 (1.2870) | 0.9983 | 0.963 | 4.4 |  |
| 34 | v5 | 1.4905/11 (1.4795) |  | 1.4124 | 1.4129/5 (1.4079) | 1.4133/6 (1.4073) | 0.9834 | 0.913 | 7.3 |  |
| 35 | v5 | 1.4983/5 (1.4933) |  | 1.3151 | 1.3150/2 (1.3130) | 1.3150/6 (1.3090) | 0.8854 | 0.888 | 2.7 |  |
| 36 | v5 | 1.4899/5 (1.4849) |  | 0.7022 | 0.7022/2 (0.7002) | 1.2649/1 (1.2639) | 0.5475 | 1.085 | 6.0 |  |
| 37 | v5 | 1.4967/8 (1.4887) |  | 1.4566 | 1.4562/1 (1.4552) | 1.4964/3 (1.4934) **WIN** | 0.9941 | 0.951 | 2.0 |  |
| 38 | v5 | 1.4653/46 (1.4193) |  | 0.6861 | 0.9620/8 (0.9540) | 0.9604/9 (0.9514) | 0.8403 | 0.866 | 25.9 | pad skipped: sketch plane normal [0.0, 0.23, 0.973] is off the principal axes; pad skipped: sketch plane normal [-0.0, -0.151, 0.989] is off the principal axes |
| 39 | v5 | 1.4992/4 (1.4952) |  | 1.2754 | 1.2753/1 (1.2743) | 1.2753/1 (1.2743) | 0.8982 | 0.826 | 14.4 |  |

measured 39, CADFit failed [], wins [15, 28, 37]

## Findings

- **39/39 parts ran, 0 CADFit failures**; median 8.3 min/part (max 45.8, part 14). Every script executed and
  converted. Ops emitted over the corpus: 131 extrudes as pads, 11 as pockets; **no revolve, fillet or chamfer**
  (finishing is off by default; revolve was never selected). Off-axis sketch planes on 5 parts (5, 11, 25, 29, 38)
  are dropped by the converter (the tree IR has only X/Y/Z sketch axes).
- **Wins on merit: 3/39** (15, 28, 37), all through fewer steps: 15 raw (1.5000 in 1 step vs 4), 28 and 37 only
  after our edge_mods/prune adds the rounds (3 steps vs 7 and 8). Near ties: 21 (1.4950 vs 1.4958/1.4961), 18
  (1.4924 vs 1.4960).
- **Owner's reference parts: no win.** 7 1.4551, 24 1.4704 (one extrude; our finishing pass adds nothing there), 22 1.3975, 2 1.1233, against 1.495-1.497 (7, 21, 22, 24) and 1.4337 (2).
- **Pattern**: CADFit gets the body in one or few extrudes (median IoU 0.94 on our grid) but never the finishes, so
  explained lags; its sketches are resampled polylines/arcs, not the designer's primitives. It loses badly on
  parts 1, 6, 16, 26, 36 (IoU 0.55-0.78).
- **CADFit's own IoU is not reliable as a gate**: part 36 reports 1.085, part 4 0.539 where our grid says 0.94.
- CAD-Recode was dropped by the owner the same day (0/39 merit wins); see docs/PATH1-LEARNED-PROPOSER.md.
