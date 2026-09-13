S=$HOME/projects/mesh2step/tools/feature_recon
for p in 7 9 10 11 12 13 15 16 18 19 20 21 22 23 24 25 28 29 30 31 32 33 35 36 37; do
  out=$S/batch/p$p.out
  timeout 1800 python3 $S/auto2d.py $HOME/corpora/mechparts/$p.stl $S/batch/p$p.step > $out 2>&1; rc=$?
  ax=$(grep -m1 '^axis' $out | cut -c1-60)
  loops=$(grep -m1 '^mid loops' $out | cut -c11-40)
  arcs=$(grep -E '^  loop [0-9]+:' $out | awk '{s+=$5} END {print s+0}')
  tr=$(grep -m1 '^end start treatments' $out | sed 's/np.float64(\([0-9.]*\))/\1/g' | cut -c29-140)
  model=$(grep -m1 '^model valid' $out | sed 's/ faces {/ | /; s/}//' | cut -c1-170)
  dist=$(grep -m1 '^mesh->model' $out | cut -c20-80)
  step=$(grep -m1 '^STEP' $out | cut -c1-40)
  err=$(grep -m1 -E 'Error|Traceback|NOT AN EXTRUSION|StdFail|Standard_' $out | cut -c1-120)
  echo "p$p rc=$rc | $ax | loops $loops | arcs $arcs | $tr"
  echo "     $model | $dist | $step ${err:+| ERR: $err}"
done
