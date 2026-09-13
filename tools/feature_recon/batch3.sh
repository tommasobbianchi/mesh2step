S=$HOME/projects/mesh2step/tools/feature_recon
mkdir -p $S/batch3
delta_of() { grep -m1 '^model valid' $1 | grep -o 'delta [-0-9.]*%' | grep -o '[-0-9.]*' ; }
for p in 16 18 21 25 32; do
  best=""; bestd=1000
  for ax in auto 0 1 2; do
    out=$S/batch3/p$p.ax$ax.out
    if [ $ax = auto ]; then timeout 1800 python3 $S/auto2d.py $HOME/corpora/mechparts/$p.stl $S/batch3/p$p.ax$ax.step > $out 2>&1
    else AXIS=$ax timeout 1800 python3 $S/auto2d.py $HOME/corpora/mechparts/$p.stl $S/batch3/p$p.ax$ax.step > $out 2>&1; fi
    d=$(delta_of $out); valid=$(grep -m1 '^model valid' $out | awk '{print $3}')
    if [ -n "$d" ] && [ "$valid" = True ]; then
      ad=$(python3 -c "print(abs($d))")
      if python3 -c "import sys; sys.exit(0 if $ad < $bestd else 1)"; then best=$out; bestd=$ad; fi
      python3 -c "import sys; sys.exit(0 if $ad < 0.5 else 1)" && break
    fi
  done
  if [ -z "$best" ]; then
    out=$S/batch3/p$p.axauto.out
    echo "p$p FAILED | $(grep -m1 '^axis' $out | cut -c1-60) | $(grep -E 'Error|Exception|StdFail|NOT AN' $out | tail -1 | cut -c1-140)"
  else
    echo "p$p $(basename $best .out) | $(grep -m1 '^axis' $best | cut -c1-58) | $(grep -m1 '^mid loops' $best | cut -c11-38) | $(grep -m1 '^end start' $best | sed 's/np.float64(\([0-9.]*\))/\1/g' | cut -c29-120)"
    echo "     $(grep -m1 '^model valid' $best | sed 's/ faces {/ | /; s/}//' | cut -c1-175) | $(grep -m1 '^mesh->model' $best | cut -c20-80) | $(grep -m1 '^STEP' $best | cut -c1-40)"
  fi
done
