#!/bin/bash
# Route every mechparts STL to a feature-level reconstruction method and keep the best VALID SOLID.
# Routing: the deterministic section-invariance test decides flat extrusions (auto2d); the DeepSeek vision category
# (dsv/all/results.txt, CAT=A..F) decides the rest: B -> stepped (auto25g), C -> turned envelope (autorev),
# D -> full round (autoround5, currently unreliable), E/F -> no feature path yet (reported, not built).
# Every candidate is validated: OCCT build valid + FreeCAD round trip must be a single valid Solid with 0 invalid faces.
# usage: recon.sh [part ...]   (default: all 39)
S=$HOME/projects/mesh2step/tools/feature_recon
OUT=$S/recon; mkdir -p $OUT
D=$HOME/snap/freecad/common/recon; mkdir -p $D
CHECK=$HOME/projects/mesh2step/tools/feature_recon/freecad_check.py
parts=${*:-$(seq 1 39)}

freecad_ok() {  # $1 step -> prints "Solid valid True solids 1 ... INVALID {}" summary, returns 0 if single valid solid
  cp -p "$1" $D/part.step
  sed "s#^path = .*#path = \"$D/part.step\"#" $CHECK > $D/check.py
  r=$(timeout 280 /snap/bin/freecad.cmd $D/check.py 2>&1 | grep -E '^shape type|^INVALID faces' | tr '\n' ' ')
  echo "$r"
  echo "$r" | grep -q 'shape type Solid valid True solids 1' && echo "$r" | grep -q 'INVALID faces by surface type: {}'
}

for p in $parts; do
  stl=$HOME/corpora/mechparts/$p.stl
  cat=$(grep -m1 "^p$p " $S/dsv/all/results.txt 2>/dev/null | grep -o 'CAT=[A-F]' | cut -c5)
  best=""; bestdv=999; tried=""
  try() {  # $1 label, $2 step path, $3 log path
    local dv
    dv=$(grep -m1 -E '^model valid True' "$3" | grep -o 'delta [-0-9.]*%' | grep -o '[-0-9.]*')
    [ -n "$dv" ] && [ -f "$2" ] || { tried="$tried $1:build-failed"; return; }
    fc=$(freecad_ok "$2"); ok=$?
    if [ $ok -eq 0 ]; then
      adv=$(python3 -c "print(abs($dv))")
      tried="$tried $1:ok(dV=$dv%)"
      if python3 -c "import sys; sys.exit(0 if $adv < $bestdv else 1)"; then best="$1 $2"; bestdv=$adv; fi
    else
      tried="$tried $1:freecad-invalid"
    fi
  }
  # 1. flat extrusion (deterministic test inside auto2d; it refuses non-extrusions)
  timeout 1800 python3 $S/auto2d.py $stl $OUT/p${p}_A.step > $OUT/p${p}_A.log 2>&1
  try A $OUT/p${p}_A.step $OUT/p${p}_A.log
  # axis retry: the section-invariance test can pick a wrong axis on thin plates (p20: -71.9% along X)
  for axr in 0 1 2; do
    AXIS=$axr timeout 1800 python3 $S/auto2d.py $stl $OUT/p${p}_A$axr.step > $OUT/p${p}_A$axr.log 2>&1
    try A$axr $OUT/p${p}_A$axr.step $OUT/p${p}_A$axr.log
  done
  # 2. category-specific paths
  case "$cat" in
    B|A) AXIS=2 timeout 1800 python3 $S/auto25g.py $stl $OUT/p${p}_B.step 60 > $OUT/p${p}_B.log 2>&1; try B $OUT/p${p}_B.step $OUT/p${p}_B.log ;;
    C) timeout 1800 python3 $S/autorev.py $stl $OUT/p${p}_C.step 400 > $OUT/p${p}_C.log 2>&1
       sed -i 's/^envelope valid/model valid/' $OUT/p${p}_C.log; try C $OUT/p${p}_C.step $OUT/p${p}_C.log ;;
    D) SEGTOL=0.12 timeout 900 python3 $S/autoround5.py $stl $OUT/p${p}_D.step 0.25 > $OUT/p${p}_D.log 2>&1; try D $OUT/p${p}_D.step $OUT/p${p}_D.log ;;
  esac
  cyl=""; [ -n "$best" ] && cyl=$(grep -m1 '^model valid' $OUT/p${p}_$(echo $best | cut -d' ' -f1).log | grep -o "'cylinder': [0-9]*")
  tier=NONE; [ -n "$best" ] && tier=$(python3 -c "print('SOLVED' if $bestdv <= 1.0 else 'APPROX' if $bestdv <= 3.0 else 'WRONG-SHAPE')")
  echo "p$p cat=${cat:-?} | $tier | best=$(echo ${best:-NONE} | cut -d' ' -f1) | |dV|=$bestdv% | $cyl | tried:$tried"
done
rm -rf $D
