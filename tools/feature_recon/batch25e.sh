S=$HOME/projects/mesh2step/tools/feature_recon
for p in 14 39; do
  out=$S/b25e/p$p.out
  AXIS=2 timeout 2400 python3 $S/auto25e.py $HOME/corpora/mechparts/$p.stl $S/b25e/p$p.step 60 > $out 2>&1; rc=$?
  echo "p$p rc=$rc | $(grep -m1 '^chosen axis' $out) | $(grep -c '^  level' $out) levels"
  grep -E '^part diagonal|face valid after|^final shape' $out | sort | uniq -c | head -6
  echo "     $(grep -m1 '^model valid' $out | sed 's/ faces {/ | /; s/}//' | cut -c1-170) | $(grep -m1 '^mesh->model' $out | cut -c20-80) | $(grep -m1 '^STEP' $out | cut -c1-40) $(grep -m1 -E 'Error|Exception|StdFail' $out | cut -c1-110)"
done
D=$HOME/snap/freecad/common/fc25e; mkdir -p $D
for p in 14 39; do f=$S/b25e/p$p.step; [ -f $f ] || continue; cp -p $f $D/part.step
  sed "s#^path = .*#path = \"$D/part.step\"#" $HOME/projects/mesh2step/tools/feature_recon/freecad_check.py > $D/check.py
  echo "FreeCAD p$p: $(timeout 280 /snap/bin/freecad.cmd $D/check.py 2>&1 | grep -E '^shape type|^INVALID faces' | tr '\n' ' ' | cut -c1-200)"; done
rm -rf $D
