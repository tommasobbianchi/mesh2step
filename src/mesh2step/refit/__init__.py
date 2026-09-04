"""TrueForm analytic refit — port of the stl2step reference engine's refit stage
(refs/stl2step/src/refit_*.cpp), planar subset (M2).

Public entry points:
    segment(mv, params)            -> RegionSet | None   (P1, pure math)
    build_faces(mv, rs, verts)     -> (ok, faces)        (P2, OCCT topology)

See mesh_view.py for the per-component MeshView contract and segment.py / build.py
for the stage-by-stage port notes.
"""
from .build import build_faces
from .mesh_view import MeshView, build_mesh_view
from .prism import PrismLevels, PrismTols, detect_prismatic
from .prism_build import PrismBuild, PrismDiag, PrismResult, build_prism_solid, try_stage_p
from .profile import Profile, ProfLoop, ProfSeg, fit_profile, slice_profiles
from .segment import RegionSet, SegmentParams, segment
from .stats import RefitStats

__all__ = [
    "MeshView",
    "PrismBuild",
    "PrismDiag",
    "PrismLevels",
    "PrismResult",
    "PrismTols",
    "ProfLoop",
    "ProfSeg",
    "Profile",
    "RefitStats",
    "RegionSet",
    "SegmentParams",
    "build_faces",
    "build_mesh_view",
    "build_prism_solid",
    "detect_prismatic",
    "fit_profile",
    "segment",
    "slice_profiles",
    "try_stage_p",
]
