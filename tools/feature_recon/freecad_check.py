import sys, collections
import Part
path = "/tmp/claude-1000/-home-tommaso-projects-mesh2step/55ed36d6-4f09-4e83-a602-2227174fbd8a/scratchpad/n19/n82_9.keep.step"
shape = Part.read(path)
print("shape type", shape.ShapeType, "valid", shape.isValid(), "solids", len(shape.Solids), "faces", len(shape.Faces))
byType = collections.Counter(); bad = collections.Counter(); badArea = collections.defaultdict(float); samples = []
for i, f in enumerate(shape.Faces):
    t = type(f.Surface).__name__
    byType[t] += 1
    try:
        ok = f.isValid()
    except Exception:
        ok = False
    if not ok:
        bad[t] += 1
        try:
            a = f.Area
        except Exception:
            a = -1.0
        badArea[t] += a
        if len(samples) < 15:
            samples.append((i, t, round(a, 4), len(f.Edges)))
print("faces by surface type:", dict(byType))
print("INVALID faces by surface type:", dict(bad))
print("area of invalid faces:", {k: round(v, 3) for k, v in badArea.items()})
for s in samples:
    print("  invalid face idx=%d type=%s area=%s edges=%d" % s)
cyl = [f for f in shape.Faces if type(f.Surface).__name__ == "Cylinder"]
areas = sorted((round(f.Area, 3) for f in cyl), reverse=True)
print("cylinder faces:", len(cyl), "largest areas:", areas[:8])
