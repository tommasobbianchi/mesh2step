"""Was this band tessellated from a curved surface, or designed with flat sides?

A tessellator applies ONE chord tolerance to a whole model. For a band of radius R
approximated by `sides` flat facets, the sagitta

    s = R * (1 - cos(pi / sides))

IS that tolerance, realised on this band. So every band that came out of the
tessellator agrees on s to within its own fitting residual, and a band whose s is
far above the model's is not an approximation of anything -- it is the designed
shape, and rebuilding it as its circumscribed cylinder adds material that was
never there.

Measured on the fixture in tests/test_intent.py: a designed 24-gon of r=12.3 has
s = 0.105mm beside a 200-facet cylinder at s = 0.00099mm -- a factor of 106. The
old code rebuilt both and moved the volume +0.81%, silently, because that is under
the webapp's 2% acceptance gate. This module is what makes that impossible.

Nothing here is learned. The separation on the corpus is measured in
docs/ -- if it ever fails to separate, the ambiguous band is WARNED, never rebuilt.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

# A band may realise the model tolerance a little worse than the finest band does:
# the tessellator rounds the facet count up, a small radius rounds harder, and the
# angular limit often binds before the linear one.
#
# MEASURED, not chosen. Over the 57-model ground-truth corpus, 52 bands that the
# B-Rep truth calls cylinders spread from 1.0x to 3.24x their own model's estimated
# tolerance -- so 3.0 would have warned on two genuine cylinders in L09_gear_blank
# and L06_adapter_plate, the second being one of the largest wins on the corpus
# (volume error 36.94 -> 0.0001 mm3). The synthetic designed prism measures 106x.
# 8.0 sits 2.5x above every real band observed and an order of magnitude below the
# designed-polygon population.
REBUILD_MAX_RATIO = 8.0

# Below this many distinct sides a "circle" is a polygon by anyone's reading.
MIN_SIDES = 6

# There is deliberately NO absolute "too few sides to rebuild" floor here. One was
# written and then removed: canonize breaks a chain wherever it turns more than
# DEFAULT_TURN_DEG = 20 degrees, so a polygon of fewer than 18 sides never becomes a
# circle, never becomes a band, and never reaches this module. Measured on 12-, 10-
# and 8-sided prisms across four radii: zero bands every time. A floor above that is
# unreachable code, and its test passed with the floor disabled -- which is the only
# reason it was caught.


_AZIMUTH_TOL_RAD = math.radians(0.5)   # two facets closer than this share a side

_NEED_SOURCE = "band_evidence needs either step_path or normals"


@dataclass(frozen=True)
class BandEvidence:
    radius: float
    sides: int          # DISTINCT facet normals around the band, not triangles
    sagitta: float      # the chord tolerance this band realises
    turn_deg: float     # 360 / sides
    faces: int          # raw face count, for the report


def face_normals(step_path) -> dict[int, np.ndarray]:
    """1-based face index -> unit normal, for the planar faces only."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    reader = STEPControl_Reader()
    reader.ReadFile(str(step_path))
    reader.TransferRoots()
    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(reader.OneShape(), TopAbs_FACE, fm)
    out: dict[int, np.ndarray] = {}
    for i in range(1, fm.Extent() + 1):
        surf = BRepAdaptor_Surface(TopoDS.Face_s(fm.FindKey(i)))
        if surf.GetType() != GeomAbs_Plane:
            continue
        d = surf.Plane().Axis().Direction()
        out[i] = np.array([d.X(), d.Y(), d.Z()])
    return out


def count_sides(band, normals: dict[int, np.ndarray]) -> int:
    """Distinct facet orientations around the band's axis.

    `verbatim + no_unify` writes one face per TRIANGLE, so a 24-sided prism arrives
    as 48 faces and a raw count would report the sagitta 4x too small. What decides
    the geometry is how many distinct directions the wall turns through.
    """
    axis = np.array(band.axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    # any two vectors spanning the plane perpendicular to the axis
    seed = np.array([1.0, 0.0, 0.0])
    if abs(float(seed @ axis)) > 0.9:
        seed = np.array([0.0, 1.0, 0.0])
    u = np.cross(axis, seed)
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)

    angles = []
    for idx in band.face_indices:
        n = normals.get(idx)
        if n is None:
            continue
        planar = n - axis * float(n @ axis)
        norm = float(np.linalg.norm(planar))
        if norm < 1e-9:
            continue
        planar /= norm
        angles.append(math.atan2(float(planar @ v), float(planar @ u)) % (2 * math.pi))
    if not angles:
        return 0
    angles.sort()
    sides = 1
    for prev, cur in pairwise(angles):
        if cur - prev > _AZIMUTH_TOL_RAD:
            sides += 1
    # the wrap-around pair closes the ring
    if sides > 1 and (angles[0] + 2 * math.pi) - angles[-1] <= _AZIMUTH_TOL_RAD:
        sides -= 1
    return sides


def band_evidence(band, step_path=None, *, normals: dict[int, np.ndarray] | None = None
                  ) -> BandEvidence:
    if normals is None:
        if step_path is None:
            raise ValueError(_NEED_SOURCE)
        normals = face_normals(step_path)
    sides = count_sides(band, normals)
    sagitta = band.radius * (1.0 - math.cos(math.pi / sides)) if sides >= 3 else float("inf")
    return BandEvidence(
        radius=float(band.radius),
        sides=int(sides),
        sagitta=float(sagitta),
        turn_deg=(360.0 / sides) if sides else 0.0,
        faces=len(band.face_indices),
    )


def model_tolerance(evidences) -> float:
    """The chord tolerance the model was tessellated at, robust to designed prisms.

    The plain median breaks on the two-band case that matters most -- one prism and
    one cylinder puts the median halfway between them, which is neither. Taking the
    median of the LOWER half keeps the estimate on the tessellated side whenever the
    coarse bands are the minority, and degenerates to the value itself when every
    band agrees.
    """
    sags = sorted(e.sagitta for e in evidences if math.isfinite(e.sagitta) and e.sagitta > 0)
    if not sags:
        return 0.0
    mid = float(np.median(sags))
    lower = [s for s in sags if s <= mid]
    return float(np.median(lower)) if lower else mid


def classify(ev: BandEvidence, model_tol: float) -> tuple[str, str]:
    """-> (verdict, human reason carrying the numbers that decided it).

    Verdicts: "rebuilt" (the facets approximate a cylinder) or "warned" (they may
    be a designed polygon, so the facets are kept and the user is told why).
    A wrong rebuild is worse than no rebuild, so every doubt resolves to "warned".
    """
    if ev.sides < MIN_SIDES:
        return "warned", (
            f"{ev.sides}-sided band r={ev.radius:.2f}mm: too few sides to be a "
            f"tessellated circle -- kept faceted (designed polygon?)"
        )
    if model_tol <= 0 or not math.isfinite(ev.sagitta):
        return "warned", (
            f"{ev.sides}-sided band r={ev.radius:.2f}mm: no model tolerance could be "
            f"established -- kept faceted"
        )
    ratio = ev.sagitta / model_tol
    if ratio <= REBUILD_MAX_RATIO:
        return "rebuilt", (
            f"{ev.sides}-sided band r={ev.radius:.2f}mm: sagitta {ev.sagitta:.4f}mm "
            f"vs model tolerance {model_tol:.4f}mm ({ratio:.1f}x) -- rebuilt"
        )
    return "warned", (
        f"{ev.sides}-facet band r={ev.radius:.2f}mm: sagitta {ev.sagitta:.4f}mm vs "
        f"model tolerance {model_tol:.4f}mm ({ratio:.0f}x too coarse) -- kept faceted "
        f"(designed prism?)"
    )


# --- auditing what the ENGINE rebuilt, from the mesh it was given ----------------
#
# Class (a) is decided in the C++ before any of the above runs. Phase-B seeds a
# cylinder from any band whose per-facet step falls in [5, 60] degrees, so a designed
# 8-gon (45 degrees) becomes a cylinder and its facets are GONE from the STEP -- P1
# and P2 in the n4 spec measured this, including that --smooth-tol and --smooth-angle
# do not reach the decision. Nothing downstream can decline what it never receives.
#
# What survives is the pair (mesh, STEP). Every cylindrical face the engine emitted
# can be measured back against the facets it replaced, and a band that was never a
# tessellation says so in two independent ways: an angular step no tessellator would
# emit, and a volume delta equal to the circumscribed-polygon ratio.
#
# Corpus-grounded, not tuned: over the 57-model ground-truth corpus the largest
# angular step among 52 real tessellated bands is 13.85 degrees. 20 degrees is above
# every one of them and far below the 45 of the archetype.
MAX_TESSELLATION_TURN_DEG = 20.0

# When the model has a second band to calibrate against, a band this many times
# coarser than the model's own tolerance is not the same tessellation. The corpus
# maximum over real bands is 3.24x, the synthetic designed prism measures 106x.
ENGINE_AUDIT_RATIO = 8.0

# The coarsest per-facet step among the 52 real tessellated bands of the ground-truth
# corpus. A band above this is outside everything the reference data contains; when the
# model also gives nothing to calibrate against, that is reported as undecidable rather
# than resolved by a rule that has no evidence behind it.
MAX_OBSERVED_TESSELLATION_TURN_DEG = 13.85


@dataclass(frozen=True)
class EngineFinding:
    """One row per band the ENGINE turned into a cylinder. Every band gets a row.

    Reporting only the flagged ones hides the case that most needs a human: a
    designed 24-gon turns 15 degrees per facet, which is outside the corpus's
    observed tessellated range (max 13.85) but not far outside it, and a lone band
    leaves the fingerprint with nothing to calibrate against. No rule settles that.
    `undecidable` marks it, and it is reported rather than quietly accepted.
    """
    radius: float
    sides: int
    turn_deg: float
    sagitta: float
    model_tolerance: float | None
    ratio: float | None          # sagitta / model tolerance, None when undetermined
    volume_delta_pct: float      # model-level: STEP vs mesh
    flagged: bool
    undecidable: bool
    message: str


def audit_engine_cylinders(mesh_path, step_path) -> list[EngineFinding]:
    """Cylindrical faces in `step_path` that the facets in `mesh_path` do not support.

    Returns one finding per suspect band, empty when the engine's rebuilds are all
    consistent with a tessellation. Never modifies anything: the correction needs a
    change in the engine's seeding, which is a fork change, not a post-process.
    """
    import trimesh
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.GProp import GProp_GProps
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    mesh = trimesh.load(str(mesh_path), process=False)
    reader = STEPControl_Reader()
    reader.ReadFile(str(step_path))
    reader.TransferRoots()
    shape = reader.OneShape()

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    step_volume = abs(float(props.Mass()))
    mesh_volume = abs(float(mesh.volume))

    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fm)
    cylinders = []
    for i in range(1, fm.Extent() + 1):
        surf = BRepAdaptor_Surface(TopoDS.Face_s(fm.FindKey(i)))
        if surf.GetType() != GeomAbs_Cylinder:
            continue
        cyl = surf.Cylinder()
        axis = cyl.Axis().Direction()
        loc = cyl.Axis().Location()
        cylinders.append((
            float(cyl.Radius()),
            np.array([axis.X(), axis.Y(), axis.Z()]),
            np.array([loc.X(), loc.Y(), loc.Z()]),
        ))
    if not cylinders:
        return []

    measured = []
    for radius, axis, origin in cylinders:
        sides = _mesh_band_sides(mesh, radius, axis, origin)
        if sides < 3:
            continue
        turn = 360.0 / sides
        measured.append((radius, sides, turn, radius * (1 - math.cos(math.pi / sides))))
    if not measured:
        return []

    sags = sorted(m[3] for m in measured)
    mid = float(np.median(sags))
    lower = [s for s in sags if s <= mid]
    model_tol = float(np.median(lower)) if lower else mid
    determined = len(measured) > 1 and model_tol > 0

    delta_pct = (100.0 * (step_volume - mesh_volume) / mesh_volume) if mesh_volume else 0.0

    findings: list[EngineFinding] = []
    for radius, sides, turn, sagitta in measured:
        ratio = (sagitta / model_tol) if determined else None
        too_coarse = turn > MAX_TESSELLATION_TURN_DEG
        off_fingerprint = ratio is not None and ratio > ENGINE_AUDIT_RATIO
        flagged = bool(too_coarse or off_fingerprint)
        # outside every tessellation this corpus contains, but not provably a prism
        # and with nothing to calibrate against: say so, do not pretend either way
        undecidable = bool(not flagged and not determined
                           and turn > MAX_OBSERVED_TESSELLATION_TURN_DEG)
        against = (f"{model_tol:.4f}mm model tolerance ({ratio:.0f}x)" if determined
                   else "no second band to calibrate against")
        head = (f"the engine rebuilt a {sides}-sided band r={radius:.2f}mm as a cylinder: "
                f"{turn:.0f} degrees per facet, sagitta {sagitta:.4f}mm vs {against}. "
                f"Volume moved {delta_pct:+.2f}% against the mesh")
        if flagged:
            message = f"{head} -- if this was a designed prism, that material was invented."
        elif undecidable:
            message = (
                f"{head}. UNDECIDABLE: {turn:.0f} degrees is coarser than any tessellated "
                f"band in the reference corpus (max {MAX_OBSERVED_TESSELLATION_TURN_DEG:.2f}), "
                f"and this model has no second band to calibrate against -- it may be a "
                f"designed polygon rebuilt as a cylinder. Check it."
            )
        else:
            message = f"{head} -- consistent with a tessellation."
        findings.append(EngineFinding(
            radius=radius, sides=sides, turn_deg=turn, sagitta=sagitta,
            model_tolerance=model_tol if determined else None, ratio=ratio,
            volume_delta_pct=delta_pct, flagged=flagged, undecidable=undecidable,
            message=message,
        ))
    return findings


def _mesh_band_sides(mesh, radius: float, axis: np.ndarray, origin: np.ndarray) -> int:
    """Distinct facet orientations of the mesh band that became this cylinder."""
    axis = axis / np.linalg.norm(axis)
    centres = mesh.triangles_center
    normals = mesh.face_normals
    d = centres - origin
    z = d @ axis
    rho = np.linalg.norm(d - np.outer(z, axis), axis=1)
    # a wall facet faces away from the axis and sits at the cylinder's radius; the
    # facet centre of an inscribed polygon sits at radius*cos(pi/n), so allow 10%
    on_band = np.logical_and(np.abs(np.abs(normals @ axis)) < 1e-3,
                             np.abs(rho - radius) <= 0.10 * radius + 1e-9)
    wall = normals[on_band]
    if len(wall) == 0:
        return 0
    seed = np.array([1.0, 0.0, 0.0])
    if abs(float(seed @ axis)) > 0.9:
        seed = np.array([0.0, 1.0, 0.0])
    u = np.cross(axis, seed)
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    angles = sorted(math.atan2(float(n @ v), float(n @ u)) % (2 * math.pi) for n in wall)
    sides = 1
    for prev, cur in pairwise(angles):
        if cur - prev > _AZIMUTH_TOL_RAD:
            sides += 1
    if sides > 1 and (angles[0] + 2 * math.pi) - angles[-1] <= _AZIMUTH_TOL_RAD:
        sides -= 1
    return sides


@dataclass(frozen=True)
class VolumeFinding:
    volume_delta_pct: float
    volume_delta_mm3: float
    explained_by_rebuild: float     # mm3 the analytic rebuilds legitimately account for
    budget_mm3: float
    message: str


def unaccounted_volume_move(mesh_path, step_path, stats=None) -> VolumeFinding | None:
    """A volume move that no analytic rebuild accounts for. None when it is explained.

    Same arithmetic as the corrected section-2b gate, applied at conversion time:

        |V_step - V_mesh|  <=  SUM over rebuilt bands of V_band*(1 - (n/2pi)*sin(2pi/n))
                               + max(1e-4*V_mesh, 3*dVolPredAbs)

    Replacing an n-gon band by its circle MUST move the volume, and by a computable amount;
    what must not happen silently is a move with nothing analytic to explain it. Measured on
    L07_flanged_bushing_recon: 258 faces, every one a plane, against a truth holding 32
    non-planar faces -- 245 of those planes absorb facets deviating up to 1.99 deg, against
    the engine's ABSOLUTE 2.0 deg near-flat gate. Area barely moves; volume moves 1.70 %.
    That is a cone flattened into planes, and it is a state-2 case exactly as a designed
    octagon is.
    """
    import trimesh
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.GProp import GProp_GProps
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    mesh = trimesh.load(str(mesh_path), process=False)
    mesh.merge_vertices()                       # exact weld, as the engine does
    reader = STEPControl_Reader()
    if reader.ReadFile(str(step_path)) != 1:
        return None
    reader.TransferRoots()
    shape = reader.OneShape()

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    v_step = abs(float(props.Mass()))
    v_mesh = abs(float((stats or {}).get("meshVolumeMM3") or mesh.volume))
    if v_mesh <= 0:
        return None

    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fm)
    explained = 0.0
    for i in range(1, fm.Extent() + 1):
        surf = BRepAdaptor_Surface(TopoDS.Face_s(fm.FindKey(i)))
        if surf.GetType() != GeomAbs_Cylinder:
            continue
        cyl = surf.Cylinder()
        axis = cyl.Axis()
        a = np.array([axis.Direction().X(), axis.Direction().Y(), axis.Direction().Z()])
        o = np.array([axis.Location().X(), axis.Location().Y(), axis.Location().Z()])
        radius = float(cyl.Radius())
        height = abs(surf.LastVParameter() - surf.FirstVParameter())
        sides = _mesh_band_sides(mesh, radius, a, o)
        if sides >= 3 and height > 0:
            explained += (math.pi * radius * radius * height
                          * (1 - (sides / (2 * math.pi)) * math.sin(2 * math.pi / sides)))

    pred = abs(float((stats or {}).get("smoothVolPredictedMM3") or 0.0))
    budget = explained + max(1e-4 * v_mesh, 3.0 * pred)
    delta = abs(v_step - v_mesh)
    if delta <= budget:
        return None

    pct = 100.0 * delta / v_mesh
    return VolumeFinding(
        volume_delta_pct=pct, volume_delta_mm3=delta, explained_by_rebuild=explained,
        budget_mm3=budget,
        message=(
            f"the solid's volume moved {pct:.2f}% ({delta:.4f} mm3) against the mesh, and "
            f"no analytic rebuild accounts for it ({explained:.4f} mm3 explained, budget "
            f"{budget:.4f} mm3). Curvature flattened into planes? Cones, spheres and tori "
            f"have no analytic form here and are absorbed into planar faces when their "
            f"per-facet angle falls under the engine's near-flat threshold -- the geometry "
            f"is kept as produced, but check it."
        ),
    )


@dataclass(frozen=True)
class FlatteningFinding:
    faces_absorbing: int
    max_absorbed_deg: float
    model_alpha_deg: float          # the model's own median curved-band facet angle
    absorbed_area_share: float
    message: str


# The engine's near-flat gate is ABSOLUTE (2.0 deg/facet by default): a cone or torus
# tessellated below it is absorbed into planar regions and its facets re-projected onto the
# fitted plane. Area barely changes, so the volume can stay silent while the SHAPE is wrong
# -- a conical seat emerges as forty planes. Measured over the corpus: 18 of 57 models
# flatten some curvature, twelve of them with a volume move of ~0.
_NEAR_FLAT_DEG = 2.0
_ABSORB_MIN_DEG = 1.0               # below this a facet really is coplanar


def flattening_suspected(mesh_path, step_path) -> FlatteningFinding | None:
    """Planar output faces that absorbed facets carrying real curvature. None if clean."""
    import trimesh
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    mesh = trimesh.load(str(mesh_path), process=False)
    mesh.merge_vertices()
    reader = STEPControl_Reader()
    if reader.ReadFile(str(step_path)) != 1:
        return None
    reader.TransferRoots()
    shape = reader.OneShape()
    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fm)

    planes, cyl_sides = [], []
    for i in range(1, fm.Extent() + 1):
        surf = BRepAdaptor_Surface(TopoDS.Face_s(fm.FindKey(i)))
        if surf.GetType() == GeomAbs_Plane:
            d = surf.Plane().Axis().Direction()
            planes.append(np.array([d.X(), d.Y(), d.Z()]))
        elif surf.GetType() == GeomAbs_Cylinder:
            cyl = surf.Cylinder()
            ax = cyl.Axis()
            a = np.array([ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()])
            o = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()])
            n = _mesh_band_sides(mesh, float(cyl.Radius()), a, o)
            if n >= 3:
                cyl_sides.append(360.0 / n)
    if not planes:
        return None

    normals, areas = mesh.face_normals, mesh.area_faces
    lo = math.cos(math.radians(_NEAR_FLAT_DEG))
    hi = math.cos(math.radians(_ABSORB_MIN_DEG))
    absorbed = np.zeros(len(normals), dtype=bool)
    worst, faces_absorbing = 0.0, 0
    for n in planes:
        dot = normals @ n
        sel = np.logical_and(dot > lo, dot < hi)
        if sel.any():
            faces_absorbing += 1
            absorbed |= sel
            worst = max(worst, math.degrees(math.acos(max(-1.0, min(1.0, float(dot[sel].min()))))))
    if faces_absorbing == 0:
        return None

    share = float(areas[absorbed].sum() / max(areas.sum(), 1e-30))
    alpha = float(np.median(cyl_sides)) if cyl_sides else float("nan")
    alpha_txt = (f"{alpha:.2f} deg" if cyl_sides else
                 "unknown (no analytic band survived to measure it)")
    return FlatteningFinding(
        faces_absorbing=faces_absorbing, max_absorbed_deg=worst, model_alpha_deg=alpha,
        absorbed_area_share=share,
        message=(
            f"{faces_absorbing} planar faces absorbed mesh facets deviating up to "
            f"{worst:.2f} deg ({100 * share:.1f}% of the surface) in a model whose analytic "
            f"bands are tessellated at {alpha_txt}: curvature flattened? Cones, spheres and "
            f"tori have no analytic form here, so a curved seat can emerge as many planes "
            f"with very nearly the right volume and the wrong shape. Geometry kept as "
            f"produced."
        ),
    )
