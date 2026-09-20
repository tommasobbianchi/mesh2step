"""The second opinion must be harsher than the radius test where it matters: on invention.

`backing.backed_fraction` exists to answer a support-only rejection with mesh evidence at the
face's own location. Its licence to do that depends entirely on refusing a face the mesh does not
carry, so that is what these test: a cylinder built where there is wall is backed, the same
cylinder moved into the air is not, and one sliced out of a cone is not.
"""
import numpy as np
import trimesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

from mesh2step.backing import backed_fraction


def _cyl(r, h, at=(0.0, 0.0, 0.0)):
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*at), gp_Dir(0, 0, 1)), r, h).Shape()


def _mesh_cyl(r, h, at=(0.0, 0.0, 0.0)):
    m = trimesh.creation.cylinder(radius=r, height=h, sections=96)
    m.apply_translation((at[0], at[1], at[2] + h / 2))
    return m.vertices[m.faces]


def test_a_cylinder_the_mesh_carries_is_backed():
    frac, backed, total = backed_fraction(_cyl(5.0, 20.0), _mesh_cyl(5.0, 20.0))
    assert total == 1 and backed == 1 and frac == 1.0


def test_the_same_cylinder_in_the_air_is_not_backed():
    """Right radius, wrong place -- the failure a radius test cannot see."""
    frac, backed, _ = backed_fraction(_cyl(5.0, 20.0, at=(40.0, 0.0, 0.0)), _mesh_cyl(5.0, 20.0))
    assert backed == 0 and frac == 0.0


def test_a_cylinder_sliced_out_of_a_cone_is_not_backed():
    """How a slicer invents a staircase. The cone's wall normal is not radial, so it cannot back
    a cylinder even where it passes through the right radius."""
    m = trimesh.creation.cone(radius=10.0, height=20.0, sections=96)
    tri = m.vertices[m.faces]
    frac, backed, total = backed_fraction(_cyl(5.0, 2.0, at=(0.0, 0.0, 9.0)), tri)
    assert total == 1 and backed == 0 and frac == 0.0


def test_a_shape_with_no_cylinder_is_not_scored():
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    frac, backed, total = backed_fraction(BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape(),
                                          _mesh_cyl(5.0, 20.0))
    assert total == 0 and frac == 1.0


def test_a_bore_is_backed_by_the_wall_of_its_hole():
    plate = trimesh.creation.box(extents=(40.0, 40.0, 10.0))
    bore = trimesh.creation.cylinder(radius=5.0, height=12.0, sections=96)
    holed = trimesh.boolean.difference([plate, bore])
    tri = np.asarray(holed.vertices)[np.asarray(holed.faces)]
    frac, backed, total = backed_fraction(_cyl(5.0, 10.0, at=(0.0, 0.0, -5.0)), tri)
    assert total == 1 and backed == 1 and frac == 1.0
