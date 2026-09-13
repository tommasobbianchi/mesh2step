S=$HOME/projects/mesh2step/tools/feature_recon
for p in 34 2; do
  out=$S/b25b/p$p.out
  AXIS=2 timeout 2400 python3 $S/auto25b.py $HOME/corpora/mechparts/$p.stl $S/b25b/p$p.step 60 > $out 2>&1; rc=$?
  echo "p$p rc=$rc | $(grep -m1 '^chosen axis' $out) | $(grep -c '^  level' $out) levels"
  grep '^  level' $out | cut -c1-120
  echo "     $(grep -m1 '^model valid' $out | sed 's/ faces {/ | /; s/}//' | cut -c1-170) | $(grep -m1 '^mesh->model' $out | cut -c20-80) | $(grep -m1 '^STEP' $out | cut -c1-40) $(grep -m1 -E 'Error|Exception|StdFail' $out | cut -c1-110)"
done
