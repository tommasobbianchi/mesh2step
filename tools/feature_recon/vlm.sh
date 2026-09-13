S=/tmp/claude-1000/-home-tommaso-projects-mesh2step/55ed36d6-4f09-4e83-a602-2227174fbd8a/scratchpad
M=$(curl -s -m 10 http://127.0.0.1:11434/api/tags | python3 -c "import json,sys; ms=[m['name'] for m in json.load(sys.stdin).get('models',[])]; vl=[m for m in ms if 'vl' in m.lower() or 'llava' in m.lower() or 'vision' in m.lower()]; print(vl[0] if vl else '')")
echo "model: ${M:-NONE}"
[ -n "$M" ] || exit 3
python3 - "$M" "$S/sem" <<'PY'
import base64, json, sys, urllib.request
model, d = sys.argv[1], sys.argv[2]
imgs = [base64.b64encode(open(f"{d}/p9_{v}.png", "rb").read()).decode() for v in ("top", "iso", "bottom")]
prompt = ("These are three renders (top view, isometric view, bottom view) of ONE machined mechanical part, "
          "overall size 114 x 114 x 20 mm. Describe it as a CAD engineer would, feature by feature: the base shape, "
          "every hole, bore, slot, keyway, tooth/spline, boss, pocket, chamfer or fillet you can see. For each feature give "
          "its type, count, approximate size relative to the part, position, and whether it goes all the way through. "
          "Then list which surfaces are cylindrical (with approximate radius) and which are planar. Be concise, use a numbered list.")
body = json.dumps({"model": model, "stream": False, "messages": [{"role": "user", "content": prompt, "images": imgs}],
                   "options": {"temperature": 0.1}}).encode()
req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=body, headers={"Content-Type": "application/json"})
r = json.load(urllib.request.urlopen(req, timeout=1500))
print(r.get("message", {}).get("content", r))
PY
