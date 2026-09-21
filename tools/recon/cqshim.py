"""Import cadquery on a system where cadquery-ocp-novtk lacks the IVtk* symbols.
cadquery.occ_impl.shapes imports them only for its VTK export helpers, which we never call."""
import importlib
_STUBS = {
    'OCP.IVtkOCC': ['IVtkOCC_Shape', 'IVtkOCC_ShapeMesher'],
    'OCP.IVtkVTK': ['IVtkVTK_ShapeData'],
    'OCP.IVtk': ['IVtk_Types', 'IVtk_SHADING', 'IVtk_WIREFRAME', 'IVtk_MeshType'],
}
for mod, names in _STUBS.items():
    try:
        m = importlib.import_module(mod)
    except Exception:
        continue
    for n in names:
        if not hasattr(m, n):
            setattr(m, n, type(n, (), {}))
import cadquery  # noqa: E402
