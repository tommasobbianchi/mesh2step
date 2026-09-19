"""Confirm: band-0 rim chords do not form a closed loop (cross-hole interruption)."""
import sys, tempfile, math
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path("tools/feature_recon").resolve()))
sys.path.insert(0, str(Path("src").resolve()))

from mesh2step.feature import _mesh
from mesh2step.native import convert_native
from mesh2step import rebuild as R
from quads import classify

stl = Path.home() / "corpora/cadbench/L09_valve_body_normal.stl"
tri = _mesh(stl)
pats = [(o[2], o[3], tri[list(o[4])].reshape(-1, 3)) for o in classify(tri)[2] if o[0] == "cylinder"]

td = tempfile.TemporaryDirectory()
tdp = Path(td.name)
e = tdp / "e.step"
convert_native(stl, e, engine="trueform", timeout=600)

from OCP.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape

reader = STEPControl_Reader()
reader.ReadFile(str(e))
reader.TransferRoots()
unify = ShapeUpgrade_UnifySameDomain(reader.OneShape(), True, True, True)
unify.Build()
merged = tdp / "m.step"
w0 = STEPControl_Writer()
w0.Transfer(unify.Shape(), STEPControl_AsIs)
w0.Write(str(merged))

bands = R.bands_from_patches(merged, pats, tol_mm=R.DEFAULT_TOL_MM, known=[])
band = bands[0]
base, axis, r = np.array(band.base), np.array(band.axis), band.radius

reader2 = STEPControl_Reader()
reader2.ReadFile(str(merged))
reader2.TransferRoots()
shape = reader2.OneShape()
fmap = TopTools_IndexedMapOfShape()
TopExp.MapShapes_s(shape, TopAbs_FACE, fmap)

def face_verts(idx):
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_VERTEX
    vm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(fmap.FindKey(idx), TopAbs_VERTEX, vm)
    out = []
    for i in range(1, vm.Extent() + 1):
        p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vm.FindKey(i)))
        out.append(np.array([p.X(), p.Y(), p.Z()]))
    return out

def face_normal(idx):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    a = BRepAdaptor_Surface(TopoDS.Face_s(fmap.FindKey(idx)))
    if a.GetType() != GeomAbs_Plane:
        return None
    d = a.Plane().Axis().Direction()
    return np.array([d.X(), d.Y(), d.Z()])

print(f"band0 base={band.base} axis={band.axis} r={r} h={band.height}")
print(f"members: {band.face_indices}")

# angular coverage of member vertices on each rim circle
u = np.cross(axis, [1.0, 0, 0])
if np.linalg.norm(u) < 0.1:
    u = np.cross(axis, [0, 1.0, 0])
u /= np.linalg.norm(u)
v = np.cross(axis, u)
for level in (0.0, band.height):
    angs = []
    for idx in band.face_indices:
        for p in face_verts(idx):
            d = p - base
            z = d @ axis
            rho = np.linalg.norm(d - z * axis)
            if abs(z - level) < 1e-6 and abs(rho - r) < 1e-6:
                angs.append(math.atan2(d @ v, d @ u))
    angs.sort()
    print(f"rim z={level}: {len(angs)} vertices on circle")
    if angs:
        gaps = [(angs[(i + 1) % len(angs)] - angs[i]) % (2 * math.pi) for i in range(len(angs))]
        big = [g for g in gaps if g > math.radians(20)]
        print(f"  max angular gap: {math.degrees(max(gaps)):.1f} deg; gaps>20deg: {len(big)} -> {[round(math.degrees(g),1) for g in big]}")

# the failing neighbour faces: vertices and normals
for idx in (427, 428, 523):
    vs = face_verts(idx)
    n = face_normal(idx)
    print(f"face {idx}: normal={None if n is None else np.round(n,3)}")
    for p in vs:
        d = p - base
        z = d @ axis
        rho = np.linalg.norm(d - z * axis)
        print(f"   vert z_axial={z:8.3f} rho={rho:8.3f}  p={np.round(p,3)}")
