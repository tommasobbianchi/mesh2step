S=/tmp/claude-1000/-home-tommaso-projects-mesh2step/55ed36d6-4f09-4e83-a602-2227174fbd8a/scratchpad
D=$HOME/snap/freecad/common/fcbatch; mkdir -p $D
for p in 7 9 10 11 12 13 15 18 19 20 21 23 24 25 28 29 30 31 32 33 35 36 37; do
  best=$(grep -m1 "^p$p " $S/sem/batch2.summary | awk '{print $2}')
  f=$S/sem/batch2/$best.step
  [ -f "$f" ] || { echo "p$p no step ($best)"; continue; }
  cp -p "$f" $D/part.step
  sed "s#^path = .*#path = \"$D/part.step\"#" $S/n19/n83_check.py > $D/check.py
  r=$(timeout 240 /snap/bin/freecad.cmd $D/check.py 2>&1 | grep -E '^shape type|^faces by surface|^INVALID faces' | tr '\n' ' ')
  echo "p$p $r"
done
rm -rf $D
