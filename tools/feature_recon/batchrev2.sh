S=$HOME/projects/mesh2step/tools/feature_recon
for p in 26 5 38; do
  out=$S/brev2/p$p.out
  timeout 1800 python3 $S/autorev.py $HOME/corpora/mechparts/$p.stl $S/brev2/p$p.step 400 > $out 2>&1; rc=$?
  echo "p$p rc=$rc | $(grep -m1 '^spin axis' $out) | $(grep -m1 '^profile' $out | cut -c1-110)"
  echo "     $(grep -m1 '^envelope valid' $out | sed 's/ faces {/ | /; s/}//' | cut -c1-170) | $(grep -m1 '^mesh->envelope' $out | cut -c23-90) $(grep -m1 -E 'Error|Exception|StdFail' $out | cut -c1-110)"
done
