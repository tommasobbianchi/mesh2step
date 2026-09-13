S=$HOME/projects/mesh2step/tools/feature_recon
D=$HOME/snap/freecad/common/fc25g; mkdir -p $D
for p in 14 39 17; do
  AXIS=2 timeout 1800 python3 $S/auto25g.py $HOME/corpora/mechparts/$p.stl $S/b25g/p$p.step 60 > $S/b25g/p$p.out 2>&1
  echo "p$p $(grep -m1 '^model valid' $S/b25g/p$p.out | sed 's/ faces {/ | /; s/}//' | cut -c1-170) | $(grep -m1 '^mesh->model' $S/b25g/p$p.out | cut -c20-80) | $(grep -m1 '^STEP' $S/b25g/p$p.out)"
  if [ -f $S/b25g/p$p.step ]; then cp -p $S/b25g/p$p.step $D/part.step
    sed "s#^path = .*#path = \"$D/part.step\"#" $HOME/projects/mesh2step/tools/feature_recon/freecad_check.py > $D/check.py
    echo "   FreeCAD: $(timeout 280 /snap/bin/freecad.cmd $D/check.py 2>&1 | grep -E '^shape type|^INVALID faces' | tr '\n' ' ' | cut -c1-180)"; fi
done
rm -rf $D
