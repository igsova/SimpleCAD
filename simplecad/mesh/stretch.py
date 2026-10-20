"""Native mesh adapter for two-plane stretch and end-region movement."""
import numpy as np
import FreeCAD as App
import Mesh

from .transform import Plan, vector
from .conversion import is_mesh
from ..document import locking
from . import slicing as mesh_slicing
from .handles import rotations


def check_source(source):
    if not is_mesh(source):
        raise ValueError('Select an original STL mesh to edit.')
    if locking.whole(source):
        raise ValueError('Unlock the mesh before editing it.')
    if not source.Document.UndoMode:
        raise ValueError('Enable Undo for this document before editing the mesh.')
    if source.InList or source.ExpressionEngine:
        raise ValueError('Choose an independent mesh outside containers, without expressions or dependent features.')
    if not 0 < source.Mesh.CountFacets <= mesh_slicing.MAX_FACETS:
        raise ValueError('Choose a mesh with 1 to 500000 triangles.')


def orient_plane(base, points, rotation=(0, 0, 0)):
    """Rotate both planes about the preset's common origin, preserving offsets."""
    matrix, _ = rotations(rotation)
    normal = matrix @ tuple(base.normal)
    levels = (np.asarray(points) - tuple(base.center)) @ normal
    return mesh_slicing.Plane(App.Vector(*map(float, normal)), base.center,
                             float(levels.min()), float(levels.max()), base.size)


def control_plane(mesh, axis='Main', rotation=(0, 0, 0)):
    base = mesh_slicing.plane(mesh, axis)
    return orient_plane(base, [tuple(p) for p in mesh.Topology[0]], rotation)


def parameters(source, axis='Main', lower=None, upper=None, distance=None, delta=None, reverse=False,
               rotation=(0, 0, 0)):
    check_source(source)
    plane = control_plane(source.Mesh, axis, rotation)
    span = plane.upper - plane.lower
    lower = plane.lower + span / 3 if lower is None else mesh_slicing.finite(lower, 'First plane')
    upper = plane.upper - span / 3 if upper is None else mesh_slicing.finite(upper, 'Second plane')
    if (distance is None) == (delta is None):
        raise ValueError('Specify either an axial distance or an XYZ displacement.')
    if not isinstance(reverse, bool):
        raise ValueError('Moving negative side must be true or false.')
    if distance is not None:
        movement = plane.normal * (mesh_slicing.finite(distance, 'Length change') * (-1 if reverse else 1))
    else:
        movement = App.Vector(*map(float, vector(delta, 'Displacement')))
    if movement.Length < 1e-9:
        raise ValueError('Enter a nonzero movement. The original mesh is unchanged.')
    inverse = source.Placement.inverse()
    return {'origin': list(inverse.multVec(plane.center)),
            'normal': list(inverse.Rotation.multVec(plane.normal)),
            'lower': lower, 'upper': upper, 'delta': list(inverse.Rotation.multVec(movement)),
            'reverse': reverse}


def stretch(mesh, origin, normal, lower, upper, delta, reverse=False, progress=lambda text: None):
    progress('Checking mesh and preparing control planes')
    if mesh.hasNonManifolds() or mesh.hasNonUniformOrientedFacets():
        raise ValueError('Repair non-manifold edges or inconsistent triangle orientation before stretching.')
    closed = mesh.isSolid()
    points, triangles = mesh.Topology
    plan = Plan([tuple(p) for p in points], triangles, origin, normal, lower, upper, reverse)
    progress('Moving the region and stretching the transition')
    moved = plan.transform(delta)
    if float(np.linalg.norm(vector(delta, 'Displacement'))) < 1e-9:
        raise ValueError('Enter a nonzero movement. The original mesh is unchanged.')
    degenerate = plan.validate_areas(moved)
    progress('Creating the native mesh')
    # This overload requires native vectors AND triangle tuples. It silently
    # skips ordinary coordinate lists, leaving indices into an empty vertex
    # array and crashing in C++ instead of raising a Python exception.
    result = Mesh.Mesh(([App.Vector(*point) for point in moved.tolist()],
                        [tuple(face) for face in plan.triangles.tolist()]))
    progress('Validating the native mesh boundary')
    if (result.CountFacets != len(plan.triangles) or result.hasNonManifolds()
            or result.hasNonUniformOrientedFacets() or result.isSolid() != closed):
        raise ValueError('The movement could not preserve the mesh boundary. Original mesh unchanged.')
    # The field has positive axial derivative everywhere. It is injective,
    # so it preserves existing intersections rather than introducing new
    # ones; no expensive all-triangle intersection test is needed per frame.
    warnings = [] if closed else ['Existing open surfaces remain open.']
    if plan.degenerate_before:
        warnings.append('%d pre-existing degenerate triangles retained without removing their connectivity.' % plan.degenerate_before)
    report = {'triangles_before': mesh.CountFacets, 'triangles': result.CountFacets,
              'degenerate_triangles_before': plan.degenerate_before, 'degenerate_triangles': degenerate,
              'closed': closed, 'moving_vertices': int(np.count_nonzero(plan.weights == 1)),
              'fixed_vertices': int(np.count_nonzero(plan.weights == 0)),
              'transition_vertices': int(np.count_nonzero((plan.weights > 0) & (plan.weights < 1))),
              'warnings': warnings}
    return result, report
