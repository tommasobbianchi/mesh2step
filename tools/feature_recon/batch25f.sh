S=$HOME/projects/mesh2step/tools/feature_recon
for v in "NOUNIFY=1" "FIXWRITE=1" "NOUNIFY=1 FIXWRITE=1"; do
  tag=$(echo $v | tr ' =' '__')
  env AXIS=2 $v timeout 1800 python3 $S/auto25f.py $HOME/corpora/mechparts/14.stl $S/b25f/p14_$tag.step 60 > $S/b25f/p14_$tag.out 2>&1
  echo "p14 [$v] $(grep -m1 '^model valid' $S/b25f/p14_$tag.out | sed 's/ faces {/ | /; s/}//' | cut -c1-160) | $(grep -m1 '^STEP' $S/b25f/p14_$tag.out)"
done
