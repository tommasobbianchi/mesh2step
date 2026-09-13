S=$HOME/projects/mesh2step/tools/feature_recon
for p in 2 34 14 4 3 8 17 39; do
  out=$S/b25/p$p.out
  timeout 2400 python3 $S/auto25.py $HOME/corpora/mechparts/$p.stl $S/b25/p$p.step 60 > $out 2>&1; rc=$?
  echo "p$p rc=$rc | $(grep -m1 '^chosen axis' $out) | $(grep -c '^  level' $out) levels"
  echo "     $(grep -m1 '^model valid' $out | sed 's/ faces {/ | /; s/}//' | cut -c1-170) | $(grep -m1 '^mesh->model' $out | cut -c20-80) | $(grep -m1 '^STEP' $out | cut -c1-40) $(grep -m1 -E 'Error|Exception|StdFail' $out | cut -c1-110)"
done
