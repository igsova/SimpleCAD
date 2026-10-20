"""Native adapter for region edits; all topology work stays on indexed meshes."""
from collections import Counter
import numpy as np
import FreeCAD as App
import Mesh
from .region import Topology, RegionPlan, resolve
from .stretch import check_source
from .transform import vector


def from_mesh(mesh):
    points,triangles = mesh.Topology
    return Topology([tuple(p) for p in points],triangles)


_cache = [None, None]


def topology_for(source):
    """Indexed topology of a document mesh, reused until it changes.

    One entry, keyed by the observer-maintained exact fingerprint (which
    includes Placement). Starting the tool, MCP inspection and Apply then
    share one build instead of rebuilding a dense mesh on the GUI thread.
    """
    from .conversion import cached_fingerprints
    key = (source.Document.Name, source.Name, cached_fingerprints.get(source))
    if _cache[0] != key:
        _cache[:] = [key, from_mesh(source.Mesh)]
    return _cache[1]


def snapshot(source):
    """Fresh exact fingerprint and topology, reading the mesh only once."""
    from .conversion import cached_fingerprints, indexed
    arrays = indexed(source.Mesh)
    value = cached_fingerprints.refresh(source, arrays)
    key = (source.Document.Name, source.Name, value)
    if _cache[0] != key:
        _cache[:] = [key, Topology(*arrays)]
    return value, _cache[1]


class CollisionError(ValueError):
    """A rejected edit, with the result triangles (0-based) that intersect."""
    def __init__(self, message, triangles=()):
        super().__init__(message)
        self.triangles = list(triangles)


def intersection_geometry(mesh):
    """Count the exact triangles involved in existing native intersections.

    Triangle numbers change during extrusion and native mesh construction.
    Compare coordinates instead, with no tolerance/rounding: only unchanged
    defective geometry may survive an edit. Count duplicate triangles too.
    FreeCAD returns (facet A, facet B, intersection start, intersection end)
    records: two zero-based integers followed by two FreeCAD.Vectors. Only the
    facet indices identify triangles; the intersection points are not indices.
    """
    if not mesh.hasSelfIntersections():
        return Counter()
    records = mesh.getSelfIntersections()
    error = 'Could not identify the mesh self-intersections. Repair the mesh before editing regions.'
    if not isinstance(records,(tuple,list)) or not records:
        raise ValueError(error)
    indices = set()
    for record in records:
        if not isinstance(record,(tuple,list)) or len(record)!=4:
            raise ValueError(error)
        pair = record[:2]
        if any(type(i) is not int or not 0<=i<mesh.CountFacets for i in pair):
            raise ValueError(error)
        indices.update(pair)
    points,faces = mesh.Topology
    points = [tuple(p) for p in points]
    return Counter(tuple(sorted(points[v] for v in faces[i])) for i in indices)


def colliding(result, faces, keys, limit=20000):
    """Indices into faces of the new/changed intersecting triangles.

    Only reported when the native mesh kept the submitted triangle order, so
    the preview can mark exactly these triangles; otherwise none.
    """
    points,facets = result.Topology
    if len(facets)!=len(faces) or not np.array_equal(np.asarray(facets,dtype=np.int64).reshape(-1,3),faces):
        return []
    points = [tuple(p) for p in points]
    found = set()
    for record in result.getSelfIntersections():
        for i in record[:2]:
            if tuple(sorted(points[v] for v in faces[i])) in keys: found.add(int(i))
    return sorted(found)[:limit]


def parameters(source, triangles=None, seed_triangle=None, selection='Flat', crease=15, grow=0,
               mode='Move', rings=1, delta=(0,0,0), axis=None, angle=0, distance=0, pivot=None):
    check_source(source)
    topology = topology_for(source)
    selected = resolve(topology,triangles,seed_triangle,selection,crease,grow)
    plan = RegionPlan(topology,selected,rings)
    # Preview validation before starting a worker; the worker checks native
    # topology and self-intersections before any document change.
    points,faces = plan.transform(mode,delta,axis,angle,distance,pivot)
    plan.validate(points,faces,mode)
    if mode!='Extrude' and np.max(np.linalg.norm(points-topology.points,axis=1))<1e-9:
        raise ValueError('Enter a nonzero movement or rotation.')
    inverse = source.Placement.inverse()
    def local(value, point=False):
        if value is None: return None
        value = App.Vector(*map(float,vector(value,'Coordinates')))
        return list(inverse.multVec(value) if point else inverse.Rotation.multVec(value))
    return dict(triangles=[int(i)+1 for i in plan.selected],mode=mode,rings=rings,
                delta=local(delta),axis=local(axis),angle=angle,distance=distance,pivot=local(pivot,True))


def edit(mesh, triangles, mode='Move', rings=1, delta=(0,0,0), axis=None, angle=0, distance=0,
         pivot=None, progress=lambda text: None):
    progress('Checking the source mesh')
    if mesh.hasNonManifolds() or mesh.hasNonUniformOrientedFacets():
        raise ValueError('Repair non-manifold edges or inconsistent orientation before editing regions.')
    existing_intersections = intersection_geometry(mesh)
    closed = mesh.isSolid()
    topology = from_mesh(mesh)
    plan = RegionPlan(topology,topology.indices(triangles),rings)
    progress('Transforming the selected region')
    points,faces = plan.transform(mode,delta,axis,angle,distance,pivot)
    plan.validate(points,faces,mode)
    if mode!='Extrude' and np.max(np.linalg.norm(points-topology.points,axis=1))<1e-9:
        raise ValueError('Enter a nonzero movement or rotation.')
    plan.validate_shell_orientation(points,faces,mode)
    progress('Creating the native mesh')
    result = Mesh.Mesh(([App.Vector(*p) for p in points.tolist()],list(map(tuple,faces.tolist()))))
    progress('Checking mesh boundaries and self-intersections')
    if (result.CountFacets!=len(faces) or result.hasNonManifolds()
            or result.hasNonUniformOrientedFacets() or result.isSolid()!=closed):
        raise ValueError('The edit could not preserve the mesh boundary. Original mesh unchanged.')
    intersections = intersection_geometry(result)
    changed_intersections = intersections - existing_intersections
    if changed_intersections:
        unchanged = sum((intersections & existing_intersections).values())
        advice = ('Reduce the extrusion distance or change its direction.' if mode=='Extrude' else
                  'Reduce the movement, grow the selected region, or increase Transition rings.')
        raise CollisionError('This edit creates or changes self-intersections '
                         '(%d new or changed intersecting triangles; %d unchanged pre-existing). '
                         '%s If the selected region already intersects itself, repair it first. '
                         'Original mesh unchanged.' % (sum(changed_intersections.values()),unchanged,advice),
                         colliding(result,faces,changed_intersections))
    warnings = [] if closed else ['Existing open surfaces remain open.']
    if intersections:
        warnings.append('%d triangles with pre-existing self-intersections were left unchanged.' % sum(intersections.values()))
    report = dict(triangles_before=mesh.CountFacets,triangles=result.CountFacets,closed=closed,
                  self_intersecting_triangles_before=sum(existing_intersections.values()),
                  self_intersecting_triangles=sum(intersections.values()),
                  mode=mode,region=plan.summary(),warnings=warnings)
    return result,report
