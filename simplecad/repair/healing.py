"""Heal a finished shape to the modeling precision without changing its design.

Converted meshes and edits on them leave faces tilted by micro-radians,
vertices microns off their planes and holes a hair off square. Each is below
the precision, yet together they inflate tolerances and break later booleans.
Healing aligns every flat face and hole axis that is within the precision of
being parallel, axis-aligned or coplanar, moves each vertex onto the aligned
planes that meet there and rebuilds the edges and faces on them. Topology and
face order are kept. Faces of other curved types, and every vertex they touch,
are left exactly as they are.
"""
import math

import numpy as np
import FreeCAD as App
import Part

from ..core import geometry as geo
from ..mesh.planar import regularize_planes
from .slivers import perimeter

V = App.Vector


def _index(items):
    table = {}
    for index, item in enumerate(items):
        table.setdefault(hash(item), []).append((index, item))

    def find(item):
        return next(index for index, other in table.get(hash(item), ()) if other.isSame(item))
    return find


def _roundtrip(shape):
    copy = Part.Shape()
    copy.importBrepFromString(shape.exportBrepToString())
    # The reader returns a generic shape; hand back the same kind.
    if copy.ShapeType == 'Face' and copy.Faces:
        return copy.Faces[0]
    if copy.ShapeType == 'Solid' and copy.Solids:
        return copy.Solids[0]
    return copy


def heal_isolated(shape, tolerance, timeout=900, remove_slivers=False):
    """Heal in a separate FreeCAD Python process.

    Kernel repairs on damaged geometry can crash natively, which no Python
    handler catches. A crash in the worker only fails this call; FreeCAD and
    the open model stay safe.
    """
    import json
    import subprocess
    import shutil
    import tempfile
    from pathlib import Path
    from .. import ROOT
    from ..jobs.runtime import runtime, environment
    folder = Path(tempfile.mkdtemp(prefix='simplecad-heal-'))
    try:
        shape.exportBrep(str(folder / 'source.brep'))
        (folder / 'options.json').write_text(json.dumps({'tolerance': tolerance, 'remove_slivers': remove_slivers}))
        try:
            completed = subprocess.run([runtime(), str(ROOT / 'scripts' / 'heal_worker.py'), str(folder)],
                                       env=environment(), capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ValueError("Healing took too long and was stopped; the shape is unchanged.")
        result = folder / 'result.json'
        if not result.is_file():
            raise ValueError("Healing stopped unexpectedly in its worker (code %s); the shape is unchanged."
                             % completed.returncode)
        report = json.loads(result.read_text())
        if 'error' in report:
            raise ValueError(report['error'])
        healed = Part.Shape()
        healed.read(str(folder / 'result.brep'))
        if shape.Solids:
            if len(healed.Solids) != 1:
                raise ValueError("Healing did not return one solid; the shape is unchanged.")
            healed = healed.Solids[0]
        return healed, report
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def check_errors(shape):
    """Number of problems the boolean checker reports; 0 for a clean shape.

    An invalid shape counts as worse than any valid one: the checker stops at
    the first invalid face and would hide every problem behind it.
    """
    if not shape.isValid():
        return math.inf
    try:
        shape.check(True)
        return 0
    except Exception as error:  # Part reports check findings as one exception
        return max(1, str(error).count('\n'))


def mesh_issues(shape, deflection=.05):
    """Edges of the printed mesh not shared by exactly two triangles.

    This is what slicers report as open or non-manifold edges. Points closer
    than 0.01 um count as one, as when a mesh file is read back.
    """
    from collections import Counter
    points, triangles = shape.tessellate(deflection)
    index, ids = {}, []
    for point in points:
        ids.append(index.setdefault((round(point.x, 5), round(point.y, 5), round(point.z, 5)), len(index)))
    uses = Counter()
    for triangle in triangles:
        a, b, c = (ids[i] for i in triangle)
        for edge in ((a, b), (b, c), (c, a)):
            uses[(min(edge), max(edge))] += 1
    return sum(1 for count in uses.values() if count != 2)


def _count(issues):
    return 'invalid geometry' if issues == math.inf else '%d boolean check issues' % issues


def verdict(original, result):
    """Before/after cleanliness; raises unless ``result`` is no worse than ``original``."""
    before_errors, after_errors = check_errors(original), check_errors(result)
    worst_before = max(v.Tolerance for v in original.Vertexes)
    worst_after = max(v.Tolerance for v in result.Vertexes)
    if after_errors > before_errors or (after_errors == before_errors and worst_after > worst_before * (1 + 1e-6)):
        raise ValueError("Healing could not improve this shape (%s, largest tolerance %.3g mm "
                         "before; %s and %.3g mm after); the shape is unchanged."
                         % (_count(before_errors), worst_before, _count(after_errors), worst_after))
    return {'max_tolerance_before': worst_before, 'max_tolerance_after': worst_after,
            'check_issues_before': -1 if before_errors == math.inf else before_errors,
            'check_issues_after': -1 if after_errors == math.inf else after_errors}


def _vec(values):
    return V(*(float(value) for value in values))


def heal(shape, tolerance, remove_slivers=False):
    """Return (healed shape, report); the input shape is not modified.

    Faces and holes are aligned. Removing details smaller than the precision
    first is experimental and off by default: on heavily edited parts it does
    not yet reliably leave fewer check issues.
    """
    from .holes import rebuild_fragmented
    removed = {}
    cleaned, rebuilt = rebuild_fragmented(shape, tolerance)
    if remove_slivers:
        from .slivers import collapse
        cleaned, removed = collapse(cleaned, tolerance)
    try:
        healed, report = align(cleaned, tolerance, original=shape)
    except ValueError:
        if not rebuilt:
            raise
        # Alignment could not improve on the rebuilt holes; keep those alone.
        healed = cleaned
        report = {'faces': len(shape.Faces), 'aligned_faces': 0, 'axis_aligned_faces': 0, 'aligned_holes': 0,
                  'moved_vertices': 0, 'max_vertex_move': 0.0, **verdict(shape, cleaned)}
    report['rebuilt_holes'] = rebuilt
    report['mesh_issues_before'], report['mesh_issues_after'] = mesh_issues(shape), mesh_issues(healed)
    report.update({key: value for key, value in removed.items() if key != 'kept_faces'})
    return healed, report


def align(shape, tolerance, original=None):
    """Align faces and holes of ``shape``; compare cleanliness to ``original``."""
    original = shape if original is None else original
    if shape.isNull() or not shape.Faces:
        raise ValueError("Healing needs a shape with faces.")
    if len(shape.Solids) > 1 or (shape.Solids and len(shape.Faces) != len(shape.Solids[0].Faces)):
        raise ValueError("Separate compound solids or mixed solid/surface objects before healing.")
    faces, edges, vertices = shape.Faces, shape.Edges, shape.Vertexes
    edge_of, vertex_of = _index(edges), _index(vertices)
    face_edges = [[edge_of(edge) for edge in face.Edges] for face in faces]
    edge_vertices = [[vertex_of(vertex) for vertex in edge.Vertexes] for edge in edges]
    face_vertices = [sorted({v for e in face_edges[i] for v in edge_vertices[e]}) for i in range(len(faces))]
    vertex_faces, edge_faces = {}, {}
    for i in range(len(faces)):
        for v in face_vertices[i]:
            vertex_faces.setdefault(v, []).append(i)
        for e in face_edges[i]:
            edge_faces.setdefault(e, []).append(i)

    kinds = []
    for face in faces:
        surface = face.Surface
        kinds.append('plane' if isinstance(surface, Part.Plane)
                     else 'cylinder' if isinstance(surface, Part.Cylinder) else 'other')
    def curve_of(edge):
        try:
            return None if edge.Degenerated else edge.Curve
        except (TypeError, ValueError, AttributeError):
            return None

    # Lines and circles are rebuilt. An ellipse where a hole wall meets a
    # slightly tilted face becomes a circle once the wall is squared; any
    # other edge, and an ellipse whose hole cannot be squared, pins its ends.
    def rim(e):
        return any(kinds[i] == 'cylinder' for i in edge_faces.get(e, ()))

    base_pinned = set()
    for index, kind in enumerate(kinds):
        if kind == 'other':
            base_pinned.update(face_vertices[index])
    ellipses = set()
    for index, edge in enumerate(edges):
        curve = curve_of(edge)
        if isinstance(curve, (Part.Line, Part.Circle)):
            continue
        if isinstance(curve, Part.Ellipse) and rim(index):
            ellipses.add(index)
            continue
        base_pinned.update(edge_vertices[index])
    extent = shape.BoundBox.DiagonalLength

    def solve(pinned):
        movable = [i for i, kind in enumerate(kinds)
                   if kind == 'plane' and not pinned.intersection(face_vertices[i])]
        fits = [(np.asarray(tuple(geo.face_normal(faces[i]))), np.asarray(tuple(faces[i].CenterOfMass)), faces[i].Area)
                for i in movable]
        planes = {}
        # On a finished model, parallel faces a sizable fraction of the
        # precision apart are a real step; only micron drift is merged.
        aligned = regularize_planes(fits, extent, tolerance, level_tolerance=tolerance * .01) if fits else []
        for i, (normal, offset) in zip(movable, aligned):
            planes[i] = (normal, float(offset))
        # Hole walls follow their rims: a cylinder square to its aligned rim
        # planes takes their exact direction, so its rims become circles on them.
        cylinders = {}
        for i, kind in enumerate(kinds):
            if kind != 'cylinder' or pinned.intersection(face_vertices[i]):
                continue
            surface = faces[i].Surface
            axis = np.asarray(tuple(surface.Axis))
            rims = {j for e in face_edges[i] for j in edge_faces.get(e, ()) if j in planes}
            size = max(faces[i].BoundBox.DiagonalLength, tolerance)
            square = [planes[j][0] for j in rims if abs(float(planes[j][0] @ axis)) >= math.cos(tolerance / size)]
            if not square:
                continue
            direction = square[0] * (1.0 if float(square[0] @ axis) > 0 else -1.0)
            if any(abs(float(d @ direction)) < 1 - 1e-12 for d in square):
                continue
            cylinders[i] = (np.asarray(tuple(surface.Center)), direction, surface.Radius)
        return planes, cylinders

    # Edges whose tolerance grew beyond a hair of the precision no longer
    # meet their faces exactly. Rebuilding them resets that tolerance.
    loose_edges = {e for e, edge in enumerate(edges)
                   if max([edge.Tolerance] + [vertices[v].Tolerance for v in edge_vertices[e]]) > tolerance * 1e-3}
    sewn_result = [None]

    def sew(new_faces):
        """Join the faces; return the faces around any gap, or [] when closed."""
        sewn = Part.Compound(new_faces)
        sewn.sewShape(max(1e-6, tolerance * 1e-3))
        rebuilt = [i for i in range(len(faces)) if not new_faces[i].isSame(faces[i]) and i not in kept]
        if len(sewn.Shells) != 1 or len(sewn.Shells[0].Faces) != len(faces):
            main = sewn.Shells[0] if sewn.Shells else None
            loose = [i for i in rebuilt if main is None or not any(
                new_faces[i].distToShape(other)[0] < 1e-9 and abs(new_faces[i].Area - other.Area) < 1e-6
                for other in main.Faces)]
            return loose or rebuilt
        # Sewing may reorder faces; keep FaceN numbering (and face colors) stable.
        pool = list(sewn.Shells[0].Faces)
        ordered = []
        for face in new_faces:
            best = min(range(len(pool)), key=lambda k: ((pool[k].CenterOfMass - face.CenterOfMass).Length,
                                                          abs(pool[k].Area - face.Area)))
            ordered.append(pool.pop(best))
        result = Part.Shell(ordered)
        if shape.Solids:
            if not result.isClosed():
                gaps = result.getFreeEdges().Edges
                near = [i for i in rebuilt if any(new_faces[i].distToShape(gap)[0] < 1e-6 for gap in gaps)]
                return near or rebuilt
            result = Part.makeSolid(result)
            if result.Volume < 0:
                result.reverse()
        sewn_result[0] = result
        return []

    pinned = set(base_pinned)
    kept = set()
    # A face that cannot be rebuilt keeps its geometry: pin its vertices,
    # so its neighbors adapt to it, and solve again.
    for attempt in range(8):
        for _ in range(3):
            planes, cylinders = solve(pinned)
            # Unsquared hole walls, and the ellipses on them, stay as they are.
            stuck = {v for e in ellipses if not any(i in cylinders for i in edge_faces.get(e, ()))
                     for v in edge_vertices[e]}
            stuck |= {v for i, kind in enumerate(kinds) if kind == 'cylinder' and i not in cylinders
                      for v in face_vertices[i]}
            stuck -= pinned
            if not stuck:
                break
            pinned |= stuck

        def supported(edge):
            e = edge_of(edge)
            curve = curve_of(edge)
            return isinstance(curve, (Part.Line, Part.Circle)) or (
                e in ellipses and any(i in cylinders for i in edge_faces.get(e, ())))

        xyz = np.asarray([tuple(vertex.Point) for vertex in vertices])
        moved = xyz.copy()
        for v in range(len(vertices)):
            if v in pinned:
                continue
            members = []
            for i in vertex_faces.get(v, ()):
                if i in planes:
                    normal, offset = planes[i]
                    if not any(np.allclose(normal, other[0]) and abs(offset - other[1]) < 1e-12 for other in members):
                        members.append((normal, offset))
            if not members:
                continue
            normals = np.asarray([m[0] for m in members])
            offsets = np.asarray([m[1] for m in members])
            correction = np.linalg.pinv(normals) @ (offsets - normals @ xyz[v])
            point = xyz[v] + correction
            # A vertex on a hole rim also lies on the hole wall's cylinder.
            for i in vertex_faces.get(v, ()):
                if i in cylinders:
                    center, direction, radius = cylinders[i]
                    radial = (point - center) - direction * float((point - center) @ direction)
                    length = float(np.linalg.norm(radial))
                    if length > 1e-12:
                        point = point + radial * (radius / length - 1.0)
            # Noise is corrected by about the vertex's distance from its
            # planes. Nearly parallel planes that disagree meet far away; a
            # move much larger than that distance keeps the vertex in place.
            off = float(np.max(np.abs(normals @ xyz[v] - offsets)))
            for i in vertex_faces.get(v, ()):
                if i in cylinders:
                    center, direction, radius = cylinders[i]
                    radial = (xyz[v] - center) - direction * float((xyz[v] - center) @ direction)
                    off = max(off, abs(float(np.linalg.norm(radial)) - radius))
            move = float(np.linalg.norm(point - xyz[v]))
            if move <= tolerance and move <= 2 * off + 1e-9:
                moved[v] = point
        shift = np.linalg.norm(moved - xyz, axis=1)

        def plane_of_edge(e):
            return next((planes[i] for i in edge_faces.get(e, ()) if i in planes), None)

        new_edges = []
        for e, edge in enumerate(edges):
            ends = [_vec(moved[v]) for v in edge_vertices[e]]
            # An edge carrying an inflated tolerance is rebuilt exactly too.
            unchanged = all(shift[v] == 0 for v in edge_vertices[e]) and e not in loose_edges
            curve = curve_of(edge) if supported(edge) else None
            if isinstance(curve, Part.Line):
                # A converted mesh can leave a zero-length edge; keep it as is.
                degenerate = len(ends) < 2 or (ends[-1] - ends[0]).Length <= 1e-9
                new_edges.append(edge.copy() if unchanged or degenerate else Part.makeLine(ends[0], ends[-1]))
                continue
            if not isinstance(curve, (Part.Circle, Part.Ellipse)):
                new_edges.append(edge.copy())
                continue
            center = np.asarray(tuple(curve.Center))
            axis = np.asarray(tuple(curve.Axis))
            radius = curve.Radius if isinstance(curve, Part.Circle) else curve.MinorRadius
            wall = next((cylinders[i] for i in edge_faces.get(e, ()) if i in cylinders), None)
            support = plane_of_edge(e)
            if wall is not None:
                base, direction, radius = wall
                axis = direction
                if support is not None:
                    normal, offset = support
                    center = base + direction * ((offset - float(normal @ base)) / float(normal @ direction))
                else:
                    center = base + direction * float((center - base) @ direction)
            elif support is not None:
                normal, offset = support
                axis = normal if float(normal @ axis) >= 0 else -normal
                center = center - normal * (float(normal @ center) - offset)
            if (isinstance(curve, Part.Circle) and unchanged and np.allclose(center, tuple(curve.Center))
                    and np.allclose(axis, tuple(curve.Axis))):
                new_edges.append(edge.copy())
                continue
            circle = Part.Circle(_vec(center), _vec(axis if float(np.dot(axis, tuple(curve.Axis))) >= 0 else -axis), radius)
            if edge.isClosed() or len(edge_vertices[e]) == 1:
                seam = ends[0]
                parameter = circle.parameter(seam)
                new_edges.append(Part.Edge(circle, parameter, parameter + 2 * math.pi))
            else:
                middle = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
                m = np.asarray(tuple(middle))
                local = (m - center) - np.asarray(tuple(circle.Axis)) * float((m - center) @ np.asarray(tuple(circle.Axis)))
                m = center + local * (radius / max(float(np.linalg.norm(local)), 1e-12))
                chord = ends[-1] - ends[0]
                bulge = (_vec(m) - ends[0]).cross(chord).Length / max(chord.Length, 1e-12)
                if chord.Length <= 1e-9 or bulge <= 1e-9:
                    # Three nearly collinear points make a degenerate arc.
                    new_edges.append(edge.copy())
                else:
                    new_edges.append(Part.Arc(ends[0], _vec(m), ends[-1]).toShape())

        def rebuild_wire(wire):
            return Part.Wire(Part.__sortEdges__([new_edges[edge_of(edge)] for edge in wire.Edges]))

        def rebuild_face(i, face):
            if i in cylinders:
                center, direction, radius = cylinders[i]
                surface = Part.Cylinder()
                surface.Radius = radius
                surface.Center = _vec(center)
                surface.Axis = _vec(direction if float(np.dot(direction, tuple(face.Surface.Axis))) >= 0 else -direction)
                if any(edge.isSeam(face) for edge in face.Edges):
                    # A full wall between two rims: its parameter band.
                    heights = [float((moved[v] - center) @ np.asarray(tuple(surface.Axis))) for v in face_vertices[i]]
                    rebuilt = surface.toShape(0, 2 * math.pi, min(heights), max(heights))
                else:
                    rebuilt = Part.Face(surface, [rebuild_wire(face.OuterWire)] + [
                        rebuild_wire(w) for w in face.Wires if not w.isSame(face.OuterWire)])
            elif i in planes:
                normal, offset = planes[i]
                origin = np.asarray(tuple(face.CenterOfMass))
                origin = origin - normal * (float(normal @ origin) - offset)
                rebuilt = Part.Face(Part.Plane(_vec(origin), _vec(normal)), [rebuild_wire(face.OuterWire)] + [
                    rebuild_wire(w) for w in face.Wires if not w.isSame(face.OuterWire)])
            else:
                surface = face.Surface
                rebuilt = Part.Face(surface, [rebuild_wire(face.OuterWire)] + [
                    rebuild_wire(w) for w in face.Wires if not w.isSame(face.OuterWire)])
            if not rebuilt.isValid():
                rebuilt.fix(1e-7, 1e-7, tolerance)
            # OCC can leave a freshly built face fragile in memory; a BREP
            # round trip gives an independent, consistent copy to measure.
            rebuilt = _roundtrip(rebuilt)
            if rebuilt.ShapeType != 'Face':
                if len(rebuilt.Faces) != 1:
                    raise ValueError('Face rebuild split the face.')
                rebuilt = rebuilt.Faces[0]
            # Keep each face's outward side.
            u0, u1, v0, v1 = face.ParameterRange
            before = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
            probe = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
            distance, pairs, _ = rebuilt.distToShape(Part.Vertex(probe))
            uv = rebuilt.Surface.parameter(V(pairs[0][0]) if pairs else probe)
            if rebuilt.normalAt(*uv).dot(before) < 0:
                rebuilt.reverse()
            # A face moves by at most its largest vertex move.
            reach = max([float(shift[v]) for v in face_vertices[i]]
                        + [edges[e].Tolerance for e in face_edges[i] if e in loose_edges]
                        + [vertices[v].Tolerance for e in face_edges[i] if e in loose_edges for v in edge_vertices[e]])
            if not rebuilt.isValid() or abs(rebuilt.Area - face.Area) > (reach + 1e-7) * max(perimeter(face), 1.0) + 1e-6:
                raise ValueError('Face rebuild changed the face.')
            return rebuilt

        new_faces, failed = [], []
        for i, face in enumerate(faces):
            touched = (any(shift[v] > 0 for v in face_vertices[i]) or i in planes or i in cylinders
                       or (kinds[i] == 'plane' and loose_edges.intersection(face_edges[i])))
            if not touched or i in kept:
                new_faces.append(face.copy())
                continue
            try:
                new_faces.append(rebuild_face(i, face))
            except Exception:  # OCC reports rebuild failures in many types
                failed.append(i)
                new_faces.append(face.copy())
        if not failed:
            failed = sew(new_faces)
            if not failed:
                break
        kept |= set(failed)
        pinned |= {v for i in failed for v in face_vertices[i]}
    else:
        raise ValueError("Healing could not rebuild some faces; the shape is unchanged.")
    result = sewn_result[0]

    if not result.isValid():
        repaired = result.copy()
        repaired.fix(1e-7, 1e-7, tolerance)
        if not repaired.isValid():
            raise ValueError("Healing produced invalid geometry; the shape is unchanged.")
        result = repaired
    # Each face moves by at most its largest vertex move, which bounds the
    # possible change of area and volume.
    change = 1e-6 + sum(face.Area * max((float(shift[v]) for v in face_vertices[i]), default=0.0)
                        for i, face in enumerate(faces))
    if abs(result.Area - shape.Area) > change or (shape.Solids and abs(result.Volume - shape.Volume) > change):
        raise ValueError("Healing would change the shape by more than the precision; the shape is unchanged.")
    # Healing must leave the shape cleaner: never more boolean check errors
    # or larger vertex tolerances than before.
    cleanliness = verdict(original, result)
    snapped = sum(1 for normal, _ in planes.values() if np.max(np.abs(normal)) == 1.0)
    report = {'faces': len(faces), 'aligned_faces': len(planes), 'axis_aligned_faces': snapped,
              'aligned_holes': len(cylinders), 'moved_vertices': int(np.count_nonzero(shift)),
              'max_vertex_move': float(shift.max()) if len(shift) else 0.0, **cleanliness}
    return result, report
