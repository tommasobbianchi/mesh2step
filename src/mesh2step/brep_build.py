"""Faceted B-Rep construction: one planar OCCT face per input triangle, with vertices
and edges SHARED across triangles by construction (not reconstructed later by a sewing
pass -- see SELECTION.md).

Algorithm
---------
1. One `TopoDS_Vertex` per (already deduped) mesh vertex, cached by index.
2. One `TopoDS_Edge` per unique *unordered* vertex-index pair, cached by
   `(min(i,j), max(i,j))`. A triangle whose winding visits the edge as `(j, i)`
   (i.e. `i > j`) gets the cached edge's `.Reversed()`. Because real triangle meshes
   (STL/OBJ/3MF/PLY) wind consistently (every shared edge is walked in opposite
   directions by its two adjacent triangles), this reversal is exactly what makes the
   resulting faces consistently outward-oriented -- verified against a trimesh box
   primitive (12 triangles, OCCT-computed volume within float64 noise of the
   analytic 8.0).
3. Building the edge cache costs nothing extra to also produce an edge-usage count:
   an edge used by exactly 2 triangles is interior (shared), by 1 is a boundary
   (open) edge, by >=3 is non-manifold. This directly answers "is this watertight"
   with no separate topology-exploration pass and no BRepBuilderAPI_Sewing call.
4. Faces assemble into one `TopoDS_Shell`. If every edge has usage count exactly 2
   (closed manifold) and `BRepBuilderAPI_MakeSolid` produces a shape with positive
   volume once oriented, the result is a `TopoDS_Solid`. Otherwise the shell is
   returned as-is and reported as open -- never silently wrapped as a fake solid.

Scope limit: the whole input file is treated as one body (one shell), matching the
reference tools. Detecting and splitting multiple disconnected islands within a single
file is not implemented (would need a face-adjacency flood fill) -- see
`_count_connected_shells`.
"""
from dataclasses import dataclass, field

import numpy as np
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeSolid,
    BRepBuilderAPI_MakeVertex,
    BRepBuilderAPI_MakeWire,
)
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shell, TopoDS_Shape


@dataclass
class BuildResult:
    shape: TopoDS_Shape
    n_faces_built: int
    n_faces_failed: int
    n_unique_edges: int
    n_boundary_edges: int      # used by exactly 1 triangle
    n_nonmanifold_edges: int   # used by >=3 triangles
    watertight: bool           # every edge used exactly twice
    is_solid: bool             # watertight AND MakeSolid produced a valid positive-volume solid
    volume: float | None = field(default=None)
    n_shells: int = 1


def build_faceted_shape(verts: np.ndarray, tris: np.ndarray) -> BuildResult:
    if len(tris) == 0:
        raise ValueError("no triangles to build")

    vertex_cache: dict[int, object] = {}

    def get_vertex(i: int):
        v = vertex_cache.get(i)
        if v is None:
            p = verts[i]
            v = BRepBuilderAPI_MakeVertex(gp_Pnt(float(p[0]), float(p[1]), float(p[2]))).Vertex()
            vertex_cache[i] = v
        return v

    edge_cache: dict[tuple[int, int], object] = {}
    edge_usage: dict[tuple[int, int], int] = {}

    def get_edge(i: int, j: int):
        key = (i, j) if i < j else (j, i)
        edge_usage[key] = edge_usage.get(key, 0) + 1
        e = edge_cache.get(key)
        if e is None:
            e = BRepBuilderAPI_MakeEdge(get_vertex(key[0]), get_vertex(key[1])).Edge()
            edge_cache[key] = e
        return TopoDS.Edge_s(e.Reversed()) if i > j else e

    builder = BRep_Builder()
    shell = TopoDS_Shell()
    builder.MakeShell(shell)

    n_built = 0
    n_failed = 0
    for tri in tris:
        a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
        try:
            wire = BRepBuilderAPI_MakeWire(get_edge(a, b), get_edge(b, c), get_edge(c, a)).Wire()
            face_maker = BRepBuilderAPI_MakeFace(wire)
            if not face_maker.IsDone():
                n_failed += 1
                continue
            builder.Add(shell, face_maker.Face())
            n_built += 1
        except Exception:
            n_failed += 1

    n_boundary = sum(1 for v in edge_usage.values() if v == 1)
    n_nonmanifold = sum(1 for v in edge_usage.values() if v >= 3)
    watertight = n_boundary == 0 and n_nonmanifold == 0 and len(edge_usage) > 0

    n_shells_in_shape = _count_connected_shells(shell)

    shape: TopoDS_Shape = shell
    is_solid = False
    volume = None

    if watertight and n_shells_in_shape == 1:
        mk_solid = BRepBuilderAPI_MakeSolid(shell)
        if mk_solid.IsDone():
            solid = mk_solid.Solid()
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(solid, props)
            vol = props.Mass()
            if vol < 0:
                solid = TopoDS.Solid_s(solid.Reversed())
                vol = -vol
            if vol > 0:
                shape = solid
                is_solid = True
                volume = vol

    return BuildResult(
        shape=shape,
        n_faces_built=n_built,
        n_faces_failed=n_failed,
        n_unique_edges=len(edge_usage),
        n_boundary_edges=n_boundary,
        n_nonmanifold_edges=n_nonmanifold,
        watertight=watertight,
        is_solid=is_solid,
        volume=volume,
        n_shells=n_shells_in_shape,
    )


def _count_connected_shells(shell: TopoDS_Shell) -> int:
    """Cheap proxy: a single TopoDS_Shell built by one BRep_Builder session is always
    topologically one shell container even if it holds disconnected face islands.
    Real disjoint-body detection would need a face-adjacency flood fill; out of scope
    for this converter (it treats the whole input file as one body, matching what the
    reference tools do). Kept as a single explicit function so that scope limit is one
    grep away instead of buried in build logic."""
    exp = TopExp_Explorer(shell, TopAbs_FACE)
    has_any = exp.More()
    return 1 if has_any else 0
