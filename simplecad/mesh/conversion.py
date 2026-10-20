"""Convert mesh snapshots to validated, ordinary Part geometry off the GUI thread."""
import hashlib
import math
import numpy as np

import FreeCAD as App
import Mesh
import Part

MAX_FACETS = 100000


def is_mesh(obj):
    return obj is not None and obj.isDerivedFrom('Mesh::Feature')


def indexed(mesh):
    """Mesh vertices and triangles as NumPy arrays (float64, int64)."""
    points, facets = mesh.Topology
    return (np.asarray([tuple(p) for p in points], dtype=float).reshape(-1, 3),
            np.asarray(facets, dtype=np.int64).reshape(-1, 3))


def digest(points, facets):
    """The fingerprint of indexed arrays (as returned by indexed())."""
    # Byte-identical to packing each point '<ddd' and facet '<III' in turn.
    value = hashlib.sha256()
    value.update(np.ascontiguousarray(points, dtype='<f8').tobytes())
    value.update(np.ascontiguousarray(facets, dtype='<u4').tobytes())
    return value.hexdigest()


def fingerprint(mesh):
    """Exact geometry and placement check; labels and visibility are independent."""
    return digest(*indexed(mesh))


class Fingerprints:
    """Exact mesh fingerprints, recomputed only after the mesh may have changed.

    Hashing a large mesh on every context poll or revision request stalls the
    GUI. Every property change, including Undo and edits from other tools,
    passes through the document observer, so a cached fingerprint stays
    exact until one of them arrives.
    """
    PROPERTIES = ('Mesh', 'Placement')

    def __init__(self):
        self.values = {}
        self.observing = False

    def get(self, obj):
        cached = self.values.get((obj.Document.Name, obj.Name))
        return cached[1] if cached is not None and cached[0] == obj else self.refresh(obj)

    def refresh(self, obj, arrays=None):
        """Hash the mesh now, as a snapshot the cached value then follows.

        Pass indexed(obj.Mesh) when the caller needs the arrays too, so a
        dense mesh is read from FreeCAD only once.
        """
        if not self.observing:
            App.addDocumentObserver(self)
            self.observing = True
        value = fingerprint(obj.Mesh) if arrays is None else digest(*arrays)
        self.values[(obj.Document.Name, obj.Name)] = (obj, value)
        return value

    def forget(self, doc_name, obj_name=None):
        for key in [key for key in self.values if key[0] == doc_name and obj_name in (None, key[1])]:
            del self.values[key]

    def slotChangedObject(self, obj, prop):
        if prop in self.PROPERTIES:
            self.forget(obj.Document.Name, obj.Name)

    def slotDeletedObject(self, obj):
        self.forget(obj.Document.Name, obj.Name)

    def slotUndoDocument(self, doc):
        self.forget(doc.Name)

    slotRedoDocument = slotUndoDocument
    slotDeletedDocument = slotUndoDocument


cached_fingerprints = Fingerprints()


def options(tolerance=.01, simplify=0):
    for value, name, low in ((tolerance, 'Surface / repair tolerance', 1e-6), (simplify, 'Simplification error', 0)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= 1:
            raise ValueError(name + ' must be between %g and 1 mm.' % low)
    return float(tolerance), float(simplify)


def weld(mesh, tolerance):
    """Merge vertices closer than the tolerance and drop collapsed triangles.

    Scanned and exported meshes carry sub-precision slivers: edges of a few
    microns and corner triangles far smaller than anything modeled. Left in,
    they become tiny faces whose tolerances overlap and break booleans. A
    weld that would make the mesh non-manifold, e.g. across a wall thinner
    than the tolerance, is refused and the original mesh is kept.
    """
    points, facets = mesh.Topology
    # Greedy seeds, not transitive merging: a finely tessellated curve with
    # points closer than the tolerance must not collapse along its length.
    seeds, cluster, cells = [], [], {}
    for point in points:
        key = tuple(int(math.floor(c / tolerance)) for c in point)
        found = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for seed in cells.get((key[0]+dx, key[1]+dy, key[2]+dz), ()):
                        if (points[seeds[seed]] - point).Length < tolerance:
                            found = seed
                            break
                    if found is not None:
                        break
                if found is not None:
                    break
            if found is not None:
                break
        if found is None:
            found = len(seeds)
            seeds.append(len(cluster))
            cells.setdefault(key, []).append(found)
        cluster.append(found)
    if len(seeds) == len(points):
        return mesh
    sums = [App.Vector() for _ in seeds]
    counts = [0] * len(seeds)
    for index, seed in enumerate(cluster):
        sums[seed] += points[index]
        counts[seed] += 1
    centers = [total * (1.0 / count) for total, count in zip(sums, counts)]
    location = {index: centers[seed] for index, seed in enumerate(cluster)}
    root = cluster.__getitem__
    triangles = [[location[i] for i in facet] for facet in facets
                 if len({root(i) for i in facet}) == 3]
    welded = Mesh.Mesh(triangles)
    welded.removeDuplicatedPoints()
    welded.removeDuplicatedFacets()
    if not welded.CountFacets or welded.hasNonManifolds() or (mesh.isSolid() and not welded.isSolid()):
        return mesh
    welded.harmonizeNormals()
    return welded


def sole_solid(shape):
    """Unwrap a compound holding exactly one solid and nothing else.

    Boolean and cleanup steps may return their single solid wrapped in a
    compound. Such a wrapper can fail validation later although the solid is
    sound, so later steps always receive the solid itself.
    """
    if (shape.ShapeType == 'Compound' and len(shape.Solids) == 1
            and len(shape.Faces) == len(shape.Solids[0].Faces)):
        return shape.Solids[0]
    return shape


def _surface(mesh, tolerance, progress):
    faces = []
    for triangle in mesh.Facets:
        points = [App.Vector(*p) for p in triangle.Points]
        faces.append(Part.Face(Part.makePolygon(points + [points[0]])))
    progress('Joining triangle boundaries')
    shell = Part.makeShell(faces)
    closed = mesh.isSolid()
    shape = Part.makeSolid(shell) if closed else shell
    if not shape.isValid():
        progress('Repairing small boundary defects')
        shape.fix(min(.001, tolerance), 1e-7, tolerance)
    if not shape.isValid() or (closed and (not shape.isClosed() or not shape.Solids)):
        raise ValueError('This mesh could not form valid CAD geometry. Repair intersecting, folded or damaged triangles in Mesh Design, then try again. No surfaces were removed.')
    if closed and shape.Volume < 0:
        shape.reverse()
    return shape


def convert(mesh, tolerance=.01, simplify=0, surfaces=False, progress=lambda message: None):
    """Rebuild a mesh as validated CAD geometry; returns (shape, report).

    With surfaces, each component is first rebuilt from a few fitted
    planes, cylinders and smooth B-spline faces (mesh_surfaces), within the
    tolerance.
    Where that fails, the component falls back to flat regions, analytic
    holes and the remaining triangles, with a warning in the report.
    """
    tolerance, simplify = options(tolerance, simplify)
    if not isinstance(surfaces, bool):
        raise ValueError('Fit smooth surfaces must be true or false.')
    smooth = surfaces  # `surfaces` later names the open components.
    if not 0 < mesh.CountFacets <= MAX_FACETS:
        raise ValueError('Choose a mesh with 1 to %d triangles. Simplify larger meshes in Mesh Design first.' % MAX_FACETS)
    original_facets = mesh.CountFacets
    working = mesh.copy()
    working.removeDuplicatedPoints()
    working.removeDuplicatedFacets()
    working.fixDegenerations()
    if not working.CountFacets or working.hasNonManifolds():
        raise ValueError('The mesh has empty or non-manifold geometry. Repair it in Mesh Design before converting.')
    working.harmonizeNormals()
    progress('Merging details smaller than the modeling precision')
    working = weld(working, tolerance)
    components = working.getSeparateComponents()
    if len(components) > 64:
        raise ValueError('This mesh contains more than 64 disconnected components. Split or clean it in Mesh Design first.')
    shapes = []
    warnings = []
    planar = {'planar_regions': 0, 'planar_triangles': 0, 'max_plane_deviation': 0.0}
    curved = {'cylinders': 0, 'analytic_holes': 0, 'max_cylinder_radius_deviation': 0.0}
    fitted = {'fitted_planes': 0, 'fitted_smooth': 0, 'fitted_cylinders': 0, 'max_fit_deviation': 0.0}
    simplified = False
    for component in components:
        progress('Building editable faces')
        component_analytic = component_fitted = False
        from .curved import reconstruct_cylinder
        try:
            shape, detail = reconstruct_cylinder(component, tolerance, progress)
        except (ValueError, RuntimeError, Part.OCCError):
            # Analytic recognition is an optimization, never a reason to
            # reject an otherwise convertible mesh component.
            shape, detail = None, {}
        curved['cylinders'] += detail.get('cylinders', 0)
        component_analytic = bool(detail.get('cylinders', 0))
        curved['max_cylinder_radius_deviation'] = max(
            curved['max_cylinder_radius_deviation'],
            detail.get('max_cylinder_radius_deviation', 0))
        if shape is None and smooth:
            from .surfaces import reconstruct as fit_surfaces
            try:
                points, triangles = indexed(component)
                shape, detail = fit_surfaces(points, triangles, component.isSolid(), tolerance, progress)
                component_fitted = True
                fitted['fitted_planes'] += detail['fitted_planes']
                fitted['fitted_smooth'] += detail['fitted_smooth']
                fitted['fitted_cylinders'] += detail['fitted_cylinders']
                fitted['max_fit_deviation'] = max(fitted['max_fit_deviation'], detail['max_vertex_deviation'],
                                                  detail['max_facet_deviation'])
            except (ValueError, RuntimeError, ArithmeticError, IndexError, np.linalg.LinAlgError, Part.OCCError):
                # Like analytic recognition, fitting is an improvement, never
                # a reason to reject an otherwise convertible component.
                shape = None
                warnings.append('Smooth surfaces could not be fitted to a component within the tolerance; '
                                'it was rebuilt from flat faces and triangles instead.')
        if shape is None:
            from .planar import reconstruct
            try:
                shape, detail = reconstruct(component, tolerance, progress)
                planar['planar_regions'] += detail.get('planar_regions', 0)
                planar['planar_triangles'] += detail.get('planar_triangles', 0)
                planar['max_plane_deviation'] = max(planar['max_plane_deviation'], detail.get('max_plane_deviation', 0))
                if shape is not None and detail.get('circular_loops'):
                    from .curved import imprint_circular_holes
                    shape, holes = imprint_circular_holes(
                        component, shape, detail['circular_loops'], tolerance, progress)
                    curved['analytic_holes'] += holes
                    component_analytic = bool(holes)
            except (ValueError, RuntimeError, Part.OCCError):
                shape = None
                warnings.append('Some flat regions could not be reconstructed safely; original triangles were kept for a component.')
        if shape is None:
            shape = _surface(component, tolerance, progress)
        if simplify and not component_analytic and not component_fitted:
            progress('Reducing triangles for editing')
            # Simplify a tessellation of the validated shape. Simplifying a
            # damaged input mesh first can preserve its invalid boundaries.
            reduced = Mesh.Mesh(shape.tessellate(min(simplify, .1)))
            reduced.decimate(simplify, .8)
            try:
                candidate = _surface(reduced, tolerance, progress)
                if bool(candidate.Solids) != bool(shape.Solids):
                    raise ValueError('Simplification changed surface closure.')
                shape = candidate
                simplified = True
            except (ValueError, RuntimeError, Part.OCCError):
                warnings.append('Simplification could not preserve valid geometry; the validated surface was kept for a component.')
        if component_fitted:
            # Fitted faces are already whole regions; nothing to merge.
            shapes.append(sole_solid(shape))
            continue
        progress('Merging coplanar triangles')
        try:
            # On a copy: the cleanup shares sub-shapes and may retune their
            # tolerances, which must not invalidate the kept original.
            refined = shape.copy().removeSplitter()
            if (refined.isValid() and bool(refined.Solids) == bool(shape.Solids)
                    and (not shape.Solids or (refined.isClosed() and abs(refined.Volume-shape.Volume) <= max(1e-6,abs(shape.Volume)*1e-6)))):
                shape = refined
            else:
                warnings.append('Final divider cleanup failed validation; the validated faces were kept.')
        except Part.OCCError:
            warnings.append('Some coplanar dividers could not be merged.')
        shapes.append(sole_solid(shape))
    # Separate closed components may describe nested cavity shells. Subtract
    # nested shells instead of filling the cavities as independent solids.
    solids = [s for s in shapes if s.Solids]
    surfaces = [s for s in shapes if not s.Solids]
    parents = {}
    containers = {i: [] for i in range(len(solids))}
    for i, first in enumerate(solids):
        for j in range(i + 1, len(solids)):
            second = solids[j]
            if not first.BoundBox.intersect(second.BoundBox):
                continue
            overlap = first.common(second).Volume
            small, large = (i, j) if first.Volume < second.Volume else (j, i)
            epsilon = max(1e-6, solids[small].Volume * 1e-6)
            if abs(overlap - solids[small].Volume) <= epsilon:
                if abs(first.Volume - second.Volume) <= epsilon:
                    raise ValueError('Mesh components overlap completely. Remove duplicate shells before converting.')
                containers[small].append(large)
            elif overlap > epsilon:
                raise ValueError('Mesh components overlap. Repair their intersections before converting.')
    for i, owners in containers.items():
        if owners:
            parents[i] = min(owners, key=lambda j: solids[j].Volume)
    def depth(index):
        return 0 if index not in parents else 1 + depth(parents[index])
    parts = list(surfaces)
    for i, solid in enumerate(solids):
        if depth(i) % 2:
            continue
        for child, parent in parents.items():
            if parent == i:
                solid = solid.cut(solids[child])
        if not solid.isValid():
            raise ValueError('The mesh cavity could not be converted to valid geometry.')
        parts.append(solid)
    result = parts[0] if len(parts) == 1 else Part.makeCompound(parts)
    if not result.isValid():
        raise ValueError('The converted shape failed validation. The original mesh is unchanged.')
    if surfaces:
        warnings.append('The mesh has open boundaries. Converted faces are editable surfaces, not a watertight solid.')
    return result, {'triangles': original_facets, 'faces': len(result.Faces),
                    'solids': len(result.Solids), 'open_surfaces': len(surfaces),
                    'simplified': simplified, 'simplification_error': simplify if simplified else 0,
                    'surface_tolerance': tolerance, 'smooth_surfaces': smooth, **planar, **curved, **fitted,
                    'warnings': warnings}
