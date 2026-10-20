"""Reconstruct bounded planar regions before creating a dense CAD triangle shell."""
import math

import numpy as np
import FreeCAD as App
import MeshPart
import Part

# Facets of a tessellated curve turn by whole degrees; noise tilts a wide
# triangle by a hair. A region whose wide triangles turn by more than this
# is part of a curve and keeps its exact facets.
FACET_ANGLE = math.radians(.5)


def regularize_planes(planes, extent, tolerance, level_tolerance=None):
    """Make nearly parallel, axis-aligned or coplanar fits exactly so.

    Each region is fitted independently, so a flat plate's two sides come out
    tilted by micro-radians and at offsets differing by microns. OCC then
    absorbs the mismatch in inflated vertex tolerances, and booleans fail.
    A tilt that moves no point of the model by more than the tolerance is
    noise: directions within that angle share one direction (a world axis
    when it qualifies) and offsets within the tolerance share one plane.
    ``planes`` holds ``(normal, center, weight)``; the result holds each
    region's aligned ``(normal, offset)`` with ``normal . x == offset``.
    ``level_tolerance`` (default: the tolerance) limits coplanar merging.
    """
    level_tolerance = tolerance if level_tolerance is None else level_tolerance
    angle = tolerance / max(extent, tolerance)
    limit = np.cos(angle)
    directions = []
    for index in sorted(range(len(planes)), key=lambda i: -planes[i][2]):
        normal, _, weight = planes[index]
        for cluster in directions:
            dot = float(cluster['seed'] @ normal)
            if abs(dot) >= limit:
                cluster['members'].append((index, 1.0 if dot > 0 else -1.0))
                cluster['sum'] += normal * weight * (1.0 if dot > 0 else -1.0)
                break
        else:
            directions.append({'seed': normal, 'members': [(index, 1.0)], 'sum': normal * weight})
    result = [None] * len(planes)
    for cluster in directions:
        direction = cluster['sum'] / np.linalg.norm(cluster['sum'])
        axis = np.eye(3)[int(np.argmax(np.abs(direction)))] * np.sign(direction[np.argmax(np.abs(direction))])
        if float(axis @ direction) >= limit:
            direction = axis
        levels = []
        for index, sign in sorted(cluster['members'], key=lambda m: -planes[m[0]][2]):
            _, center, weight = planes[index]
            # Measure the region's center along the shared direction, so
            # re-aligning pivots the region about its own center.
            level = float(direction @ center)
            for group in levels:
                # Opposite sides of a wall thinner than the tolerance face
                # opposite ways; merging them would collapse the wall.
                if group['sign'] == sign and abs(group['level'] - level) <= level_tolerance:
                    group['members'].append((index, sign))
                    group['total'] += level * weight
                    group['weight'] += weight
                    break
            else:
                levels.append({'level': level, 'sign': sign, 'members': [(index, sign)],
                               'total': level * weight, 'weight': weight})
        for group in levels:
            level = group['total'] / group['weight']
            for index, sign in group['members']:
                result[index] = (direction * sign, level * sign)
    return result


def project_vertices(xyz, memberships, planes, tolerance):
    """Move each vertex onto every plane it belongs to, within the tolerance.

    A vertex on one plane moves along its normal, on two onto their shared
    line and on three onto their corner. The least-norm correction keeps the
    move as small as possible; a vertex needing more than the tolerance keeps
    its original position rather than distorting the model.
    """
    moved = xyz.copy()
    for vertex, members in memberships.items():
        normals = np.asarray([planes[i][0] for i in members])
        offsets = np.asarray([planes[i][1] for i in members])
        point = xyz[vertex]
        correction = np.linalg.pinv(normals) @ (offsets - normals @ point)
        candidate = point + correction
        if (np.linalg.norm(correction) <= tolerance
                and np.max(np.abs(normals @ candidate - offsets)) <= 1e-9 * max(1.0, np.max(np.abs(offsets)))):
            moved[vertex] = candidate
    return moved


def reconstruct(mesh, tolerance, progress):
    from .curved import fit_circle_loop
    points, triangles = mesh.Topology
    xyz = np.asarray([tuple(point) for point in points])
    indices = np.asarray(triangles)
    corners = xyz[indices]
    cross = np.cross(corners[:, 1]-corners[:, 0], corners[:, 2]-corners[:, 0])
    faces, used, deviations, circular_loops = [], set(), [], []
    progress('Recognizing flat surface regions')
    # The native segmentation supplies candidates, not an accuracy guarantee.
    # Independently fit each candidate and bound every source vertex in mm.
    candidates = []
    for group in mesh.getPlanarSegments(min(.01, tolerance)):
        if len(group) < 2:
            continue
        samples = xyz[np.unique(indices[group])]
        center = samples.mean(axis=0)
        _, singular, axes = np.linalg.svd(samples-center, full_matrices=False)
        if singular[1] <= 1e-10:
            continue
        normal = axes[-1]
        deviation = float(np.max(np.abs((samples-center) @ normal)))
        if deviation > tolerance:
            continue
        if normal @ cross[group].sum(axis=0) < 0:
            normal = -normal
        area = float(np.abs(cross[group] @ normal).sum()/2)
        # The segmentation joins adjacent facets of a fine curve into one
        # region within its deviation. Flattening those would distort the
        # curve and its later analytic fit, so only noisy planes are aligned.
        # Noise cannot tilt a triangle many tolerances wide by more than a
        # hair, while a curve's facets turn by degrees; slivers carry no
        # direction and are not judged.
        lengths = np.linalg.norm(cross[group], axis=1)
        tri = corners[group]
        longest = np.max(np.linalg.norm(tri - np.roll(tri, 1, axis=1), axis=2), axis=1)
        judged = lengths >= 10 * tolerance * np.maximum(longest, 1e-12)
        tilts = (cross[group] @ normal)[judged] / lengths[judged]
        flat = bool(np.all(tilts >= math.cos(FACET_ANGLE)))
        candidates.append((group, normal, center, area, flat))
    progress('Aligning flat surfaces to the modeling precision')
    extent = float(np.linalg.norm(xyz.max(axis=0) - xyz.min(axis=0)))
    aligned = [index for index, candidate in enumerate(candidates) if candidate[4]]
    planes = [(normal, float(normal @ center)) for _, normal, center, _, _ in candidates]
    for index, plane in zip(aligned, regularize_planes(
            [(candidates[i][1], candidates[i][2], candidates[i][3]) for i in aligned], extent, tolerance)):
        planes[index] = plane
    memberships = {}
    for index in aligned:
        group = candidates[index][0]
        for vertex in np.unique(indices[group]):
            members = memberships.setdefault(int(vertex), [])
            if not any(np.allclose(planes[m][0], planes[index][0]) and abs(planes[m][1] - planes[index][1]) < 1e-12
                       for m in members):
                members.append(index)
    flat = project_vertices(xyz, memberships, planes, tolerance)
    moved = np.flatnonzero(np.any(flat != xyz, axis=1))
    # Mesh points are single precision; moving them in the mesh would put
    # them microns off their planes again. Keep exact coordinates here and
    # rebuild each boundary from them.
    lookup = {tuple(point): index for index, point in enumerate(xyz.tolist())}
    xyz = flat
    points = [App.Vector(*point) for point in xyz]
    corners = xyz[indices]
    cross = np.cross(corners[:, 1]-corners[:, 0], corners[:, 2]-corners[:, 0])

    def exact(wire):
        loop = [lookup[tuple(vertex.Point)] for vertex in wire.OrderedVertexes]
        return Part.makePolygon([points[index] for index in loop] + [points[loop[0]]])
    for index, (group, _, _, _, _) in enumerate(candidates):
        normal, offset = planes[index]
        samples = xyz[np.unique(indices[group])]
        deviation = float(np.max(np.abs(samples @ normal - offset)))
        if deviation > tolerance:
            continue
        try:
            wires = MeshPart.wireFromSegment(mesh, group)
            if not wires or any(not wire.isClosed() for wire in wires):
                continue
            wires = [exact(wire) for wire in wires]
            center = samples.mean(axis=0)
            center = center - normal * (center @ normal - offset)
            plane = Part.Plane(App.Vector(*center), App.Vector(*normal))
            face = Part.Face(plane, wires)
            # Keep repair precision small: using the fitting deviation here
            # collapses short shared boundary edges and prevents shell sewing.
            face.fix(1e-7, 1e-7, tolerance)
            if not face.isValid() or len(face.Wires) != len(wires):
                continue
            # Signed: aligning a region may fold a sliver triangle inside it.
            # The folded part cancels, exactly as it does in the boundary.
            area = float((cross[group] @ normal).sum()/2)
            # In particular, reject a face maker that drops an inner loop or
            # picks the wrong outside wire on a region with multiple holes.
            if abs(face.Area-area) > max(1e-6, area*1e-5):
                continue
            if face.normalAt(0, 0).dot(App.Vector(*normal)) < 0:
                face.reverse()
            faces.append(face)
            for wire in wires:
                fit = fit_circle_loop([vertex.Point for vertex in wire.Vertexes], tolerance)
                if fit is not None:
                    circular_loops.append(fit)
            used.update(group)
            deviations.append(deviation)
        except (KeyError, RuntimeError, ValueError, Part.OCCError):
            # A difficult region retains its original triangles; it must not
            # prevent the other, ordinary flat surfaces from being merged.
            continue
    if not used:
        return None, {}
    merged = len(faces)
    for index, triangle in enumerate(triangles):
        if index not in used:
            vertices = [points[i] for i in triangle]
            faces.append(Part.Face(Part.makePolygon(vertices+[vertices[0]])))
    progress('Joining reconstructed surface boundaries')
    shell = Part.makeShell(faces)
    # Sewing may leave stale pcurves on tiny edges. Fix the assembled shell,
    # using the same bounded tolerance, before judging its validity. A fix
    # that breaks an already valid, closed shell apart is discarded.
    repaired = shell.copy()
    repaired.fix(1e-7, 1e-7, tolerance)
    if (repaired.ShapeType == 'Shell' and repaired.isValid() and repaired.isClosed()) or not (
            shell.ShapeType == 'Shell' and shell.isValid() and shell.isClosed()):
        shell = repaired
    if (shell.ShapeType != 'Shell' or not shell.isValid()
            or len(shell.Faces) != len(faces)
            or (mesh.isSolid() and not shell.isClosed())):
        raise ValueError('Planar reconstruction could not preserve the complete surface boundary.')
    result = Part.makeSolid(shell) if mesh.isSolid() else shell
    if result.Volume < 0 and mesh.isSolid():
        result.reverse()
    if not result.isValid():
        raise ValueError('Reconstructed planar surfaces failed solid validation.')
    if mesh.isSolid():
        origin = xyz.mean(axis=0)
        relative = corners-origin
        volume = abs(float(np.einsum('ij,ij->i', relative[:, 0], np.cross(relative[:, 1], relative[:, 2])).sum()/6))
        area = float(np.linalg.norm(cross, axis=1).sum()/2)
        if abs(result.Volume-volume) > max(1e-6, volume*1e-6, tolerance*area):
            raise ValueError('Planar reconstruction changed too much enclosed volume.')
    return result, {'planar_regions': merged, 'planar_triangles': len(used),
                    'max_plane_deviation': max(deviations),
                    'circular_loops': circular_loops}
