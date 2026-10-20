"""Conservative analytic reconstruction for closed cylindrical mesh components.

STL stores triangles rather than design intent. This module only replaces a
component when its normals, circular boundary and enclosed volume agree with
one complete cylinder. It can also replace a verified through-hole inside an
otherwise planar solid. Anything partial, noisy or ambiguous remains on the
existing validated triangle/planar reconstruction path.
"""
import math

import numpy as np
import FreeCAD as App
import MeshPart
import Part


def _triangle_data(mesh):
    points, triangles = mesh.Topology
    xyz = np.asarray([tuple(point) for point in points], dtype=float)
    indices = np.asarray(triangles, dtype=int)
    corners = xyz[indices]
    cross = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    lengths = np.linalg.norm(cross, axis=1)
    good = lengths > 1e-12
    if not np.all(good):
        return None
    normals = cross / lengths[:, None]
    centers = corners.mean(axis=1)
    return xyz, indices, corners, normals, centers, lengths


def _basis(axis):
    seed = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(seed, axis))) > .85:
        seed = np.array([0.0, 1.0, 0.0])
    u = seed - axis * float(np.dot(seed, axis))
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    return u, v


def _fit_circle(points, axis):
    origin = points.mean(axis=0)
    u, v = _basis(axis)
    xy = np.column_stack(((points - origin) @ u, (points - origin) @ v))
    # 2*c.x*x + 2*c.y*y + c.rhs = x*x + y*y
    matrix = np.column_stack((2 * xy[:, 0], 2 * xy[:, 1], np.ones(len(xy))))
    rhs = np.einsum('ij,ij->i', xy, xy)
    try:
        solution, _, rank, _ = np.linalg.lstsq(matrix, rhs, rcond=None)
    except np.linalg.LinAlgError:
        return None
    if rank < 3:
        return None
    cx, cy, constant = solution
    radius_squared = float(constant + cx * cx + cy * cy)
    if not math.isfinite(radius_squared) or radius_squared <= 1e-12:
        return None
    radius = math.sqrt(radius_squared)
    center = origin + u * cx + v * cy
    radial = np.linalg.norm((points - center) - axis * ((points - center) @ axis)[:, None], axis=1)
    residual = float(np.max(np.abs(radial - radius)))
    angles = np.mod(np.arctan2((points - center) @ v, (points - center) @ u), 2 * math.pi)
    angles = np.unique(np.round(np.sort(angles), 10))
    if len(angles) < 8:
        return None
    gaps = np.diff(np.r_[angles, angles[0] + 2 * math.pi])
    return center, radius, residual, float(np.max(gaps)), u, v


def _mesh_volume(corners, origin):
    relative = corners - origin
    return abs(float(np.einsum('ij,ij->i', relative[:, 0],
                               np.cross(relative[:, 1], relative[:, 2])).sum() / 6))


def fit_circle_loop(points, tolerance):
    """Fit an analytic circle to one planar polygon boundary, or return None."""
    samples = []
    seen = set()
    for point in points:
        value = tuple(float(x) for x in point)
        if value not in seen:
            seen.add(value)
            samples.append(value)
    if len(samples) < 8:
        return None
    xyz = np.asarray(samples, dtype=float)
    origin = xyz.mean(axis=0)
    try:
        _, singular, axes = np.linalg.svd(xyz - origin, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    if singular[1] <= 1e-10:
        return None
    normal = axes[-1]
    deviation = float(np.max(np.abs((xyz - origin) @ normal)))
    if deviation > max(tolerance * 2, .002):
        return None
    u, v = _basis(normal)
    xy = np.column_stack(((xyz - origin) @ u, (xyz - origin) @ v))
    matrix = np.column_stack((2 * xy[:, 0], 2 * xy[:, 1], np.ones(len(xy))))
    rhs = np.einsum('ij,ij->i', xy, xy)
    try:
        solution, _, rank, _ = np.linalg.lstsq(matrix, rhs, rcond=None)
    except np.linalg.LinAlgError:
        return None
    if rank < 3:
        return None
    cx, cy, constant = solution
    radius_squared = float(constant + cx * cx + cy * cy)
    if radius_squared <= 1e-12 or not math.isfinite(radius_squared):
        return None
    radius = math.sqrt(radius_squared)
    center = origin + u * cx + v * cy
    radial = np.linalg.norm((xyz - center) - normal * ((xyz - center) @ normal)[:, None], axis=1)
    residual = float(np.max(np.abs(radial - radius)))
    if residual > max(tolerance * 2, radius * .0015):
        return None
    angles = np.mod(np.arctan2((xyz - center) @ v, (xyz - center) @ u), 2 * math.pi)
    angles = np.unique(np.round(np.sort(angles), 10))
    if len(angles) < 8:
        return None
    gaps = np.diff(np.r_[angles, angles[0] + 2 * math.pi])
    if float(np.max(gaps)) > math.radians(80):
        return None
    return {'center': App.Vector(*center), 'normal': App.Vector(*normal),
            'radius': radius, 'residual': residual}


def _circular_loops(mesh, tolerance):
    loops = []
    for group in mesh.getPlanarSegments(.01):
        if len(group) < 2:
            continue
        try:
            wires = MeshPart.wireFromSegment(mesh, group)
        except (RuntimeError, ValueError, Part.OCCError):
            continue
        for wire in wires or []:
            if not wire.isClosed():
                continue
            points = [vertex.Point for vertex in wire.Vertexes]
            fit = fit_circle_loop(points, tolerance)
            if fit is not None:
                loops.append(fit)
    return loops


def _has_cylindrical_wall(data, first, second, tolerance):
    xyz, indices, corners, normals, centers, lengths = data
    axis = second['center'] - first['center']
    axis.normalize()
    distance = first['center'].distanceToPoint(second['center'])
    if distance <= max(tolerance * 2, first['radius'] * .01):
        return False
    radial = xyz - np.asarray(tuple(first['center']))
    axial = radial @ np.asarray(tuple(axis))
    radial_distance = np.linalg.norm(radial - np.asarray(tuple(axis)) * axial[:, None], axis=1)
    lo, hi = -tolerance * 3, distance + tolerance * 3
    side = ((np.abs(normals @ np.asarray(tuple(axis))) <= .22)
            & (axial[indices].mean(axis=1) >= lo)
            & (axial[indices].mean(axis=1) <= hi))
    side &= np.max(np.abs(radial_distance[indices] - first['radius']), axis=1) <= max(tolerance * 3, first['radius'] * .003)
    if int(side.sum()) < 8:
        return False
    selected = np.mod(np.arctan2(radial[indices[side]] @ np.asarray(tuple(_basis(np.asarray(tuple(axis)))[1])),
                                 radial[indices[side]] @ np.asarray(tuple(_basis(np.asarray(tuple(axis)))[0]))), 2 * math.pi)
    angles = np.unique(np.round(np.sort(selected.ravel()), 8))
    if len(angles) < 8:
        return False
    gaps = np.diff(np.r_[angles, angles[0] + 2 * math.pi])
    return float(np.max(gaps)) <= math.radians(85)


def _noise(shape, tolerance):
    tiny = sum(1 for face in shape.Faces if face.Area < tolerance ** 2)
    short = sum(1 for edge in shape.Edges if edge.Length < tolerance * .1)
    loose = max((vertex.Tolerance for vertex in shape.Vertexes), default=0.0)
    return tiny, short, loose


def _adds_noise(before, after, tolerance):
    """Whether a rebuild leaves detail below the modeling precision.

    An analytic hole must make the model cleaner. A rebuild that splits
    faces into specks, leaves hairline edges or inflates vertex tolerances
    would break later booleans, so the faceted hole is kept instead.
    """
    tiny, short, loose = _noise(before, tolerance)
    tiny_after, short_after, loose_after = _noise(after, tolerance)
    return (tiny_after > tiny or short_after > short
            or loose_after > max(loose, tolerance * .1))


def imprint_circular_holes(mesh, shape, loops, tolerance, progress):
    """Cut verified through-hole cylinders into a reconstructed solid."""
    if not shape or not shape.Solids or len(shape.Solids) != 1 or len(loops) < 2:
        return shape, 0
    data = _triangle_data(mesh)
    if data is None:
        return shape, 0
    result, count = shape, 0
    for index, first in enumerate(loops):
        for second in loops[index + 1:]:
            if abs(abs(first['normal'].dot(second['normal'])) - 1) > .01:
                continue
            if abs(first['radius'] - second['radius']) > max(tolerance * 3, first['radius'] * .003):
                continue
            delta = second['center'] - first['center']
            if delta.Length <= tolerance:
                continue
            # The centers must line up along the rims' normal. Measuring the
            # offset against the line between the centers themselves always
            # gives zero, and let every pair of equal circles reach the
            # triangle scan below.
            normal = App.Vector(first['normal'])
            normal.normalize()
            center_offset = delta - normal * delta.dot(normal)
            if center_offset.Length > max(tolerance * 4, first['radius'] * .01):
                continue
            axis = App.Vector(delta)
            axis.normalize()
            if not _has_cylindrical_wall(data, first, second, tolerance):
                continue
            distance = first['center'].distanceToPoint(second['center'])
            try:
                # Preferred path: rebuild both rims and the wall analytically.
                rebuilt = replace_hole(result, first['center'], axis, first['radius'],
                                       distance, tolerance)
                if (rebuilt.ShapeType == 'Compound' and len(rebuilt.Solids) == 1
                        and len(rebuilt.Faces) == len(rebuilt.Solids[0].Faces)):
                    rebuilt = rebuilt.Solids[0]
                # A hole that cannot be rebuilt as one valid closed solid
                # stays faceted; it must not invalidate the whole conversion.
                if (not rebuilt.isValid() or not rebuilt.isClosed()
                        or len(rebuilt.Solids) != len(result.Solids)
                        or _adds_noise(result, rebuilt, tolerance)):
                    continue
                result = rebuilt
            except (ValueError, RuntimeError, Part.OCCError):
                # Conservative boolean fallback for unusual face structures.
                base = first['center'] - axis * (tolerance * 4)
                cutter = Part.makeCylinder(first['radius'], distance + tolerance * 8, base, axis)
                try:
                    candidate = result.cut(cutter)
                except (RuntimeError, ValueError, Part.OCCError):
                    continue
                removed = result.Volume - candidate.Volume
                if (not candidate.isValid() or not candidate.isClosed() or len(candidate.Solids) != 1
                        or removed <= max(1e-7, result.Volume * 1e-9)
                        or removed >= result.Volume * .75
                        or _adds_noise(result, candidate, tolerance)):
                    continue
                result = candidate
            count += 1
            progress('Recognized analytic circular hole')
    return result, count


def replace_hole(shape, base, axis, radius, height, tolerance=.01):
    """Rebuild one faceted cylindrical hole inside a shape as analytic geometry.

    Both faceted rims become single circle edges on their carrying faces and
    the faceted wall becomes one cylindrical face, sewn back into a valid
    solid.  This also converts faceted cylindrical bosses, because no material
    is added or removed beyond the slivers between the polygon and its fitted
    circle.  ValueError is raised whenever the hole does not have this plain
    divided-face structure, so callers keep their conservative fallbacks.
    """
    base = App.Vector(base)
    axis = App.Vector(axis)
    if axis.Length > 1e-9:
        axis = axis.normalize()
    if height <= 1e-9 or radius <= 1e-9:
        raise ValueError('The fitted cylinder has no length.')
    near = max(.01, tolerance * 2, radius * .001)

    was_valid = shape.isValid()
    try:
        candidate = _rebuild_hole_brep(shape, base, axis, radius, height, tolerance, near)
        if candidate is not None and (candidate.isValid() or not was_valid):
            if not shape.Solids or candidate.isClosed() or not shape.isClosed():
                return candidate
    except Exception:
        pass

    solids = shape.Solids
    if solids:
        mid = base + axis * (height * 0.5)
        is_hole = not shape.isInside(mid, 1e-4, False)
        if is_hole:
            high = base + axis * height
            probe_dist = max(0.05, tolerance * 4)
            is_base_open = not shape.isInside(base - axis * probe_dist, 1e-4, False)
            is_high_open = not shape.isInside(high + axis * probe_dist, 1e-4, False)

            fill_extra = max(0.05, radius * 0.01)
            filler = Part.makeCylinder(radius + fill_extra, height, base, axis)
            try:
                filled = shape.fuse(filler).removeSplitter()
            except Exception:
                filled = None

            if filled is not None and filled.isValid() and filled.Solids:
                extend = max(0.5, radius * 0.05)
                c_base = base - axis * (extend if is_base_open else 0.0)
                c_height = height + (extend if is_base_open else 0.0) + (extend if is_high_open else 0.0)
                cutter = Part.makeCylinder(radius, c_height, c_base, axis)
                # A fitted radius sits within a hair of exact rim vertices,
                # such as a chamfer's lower edge. Below OCC's own tolerance
                # the plain cut is ambiguous, so treat that gap as contact.
                candidate = None
                for fuzzy in (1e-5, None):
                    try:
                        candidate = (filled.cut(cutter, fuzzy) if fuzzy else filled.cut(cutter)).removeSplitter()
                        break
                    except Exception:
                        candidate = None

                if (candidate is not None and candidate.isValid() and candidate.isClosed()
                        and len(candidate.Solids) == len(solids)):
                    change = abs(shape.Volume - candidate.Volume)
                    bound = math.pi * radius ** 2 * height * .35 + near * math.tau * radius * (height + 2 * near)
                    if change <= bound:
                        return candidate
        else:
            high = base + axis * height
            probe_dist = max(0.05, tolerance * 4)
            is_base_in = shape.isInside(base - axis * probe_dist, 1e-4, False)
            is_high_in = shape.isInside(high + axis * probe_dist, 1e-4, False)
            boss_base = base
            boss_high = high
            boss_axis = axis
            if not is_base_in and is_high_in:
                boss_base, boss_high = high, base
                boss_axis = axis * -1.0

            boss_near = max(0.02, tolerance * 4, radius * 0.02)
            base_face = None
            for f in shape.Faces:
                try:
                    s = f.Surface
                except Exception:
                    continue
                if isinstance(s, Part.Plane) and abs(abs(f.normalAt(0, 0).dot(boss_axis)) - 1.0) < 0.05:
                    if abs((f.CenterOfMass - boss_base).dot(boss_axis)) < boss_near:
                        has_rim_verts = any(abs(((v.Point - boss_base) - boss_axis * ((v.Point - boss_base).dot(boss_axis))).Length - radius) < boss_near for v in f.Vertexes)
                        if has_rim_verts:
                            base_face = f
                            break

            if base_face is not None:
                outer_wire = max(base_face.Wires, key=lambda w: w.Length)
                inner_wires = [w for w in base_face.Wires if not w.isSame(outer_wire)]

                def is_rim_wire(w):
                    pts = [v.Point for v in w.Vertexes]
                    return all(abs(((p - boss_base) - boss_axis * ((p - boss_base).dot(boss_axis))).Length - radius) < boss_near for p in pts)

                other_inner = [w for w in inner_wires if not is_rim_wire(w)]
                circle_wire = Part.Wire([Part.makeCircle(radius, boss_base, boss_axis * -1)])
                try:
                    new_base_face = Part.Face(base_face.Surface, [outer_wire] + other_inner + [circle_wire])
                    if new_base_face.normalAt(0, 0).dot(base_face.normalAt(0, 0)) < 0:
                        new_base_face.reverse()
                    if not new_base_face.isValid():
                        circle_wire = Part.Wire([Part.makeCircle(radius, boss_base, boss_axis)])
                        new_base_face = Part.Face(base_face.Surface, [outer_wire] + other_inner + [circle_wire])
                        if new_base_face.normalAt(0, 0).dot(base_face.normalAt(0, 0)) < 0:
                            new_base_face.reverse()
                except Exception:
                    new_base_face = None

                if new_base_face is not None and new_base_face.isValid():
                    top_circle = Part.Wire([Part.makeCircle(radius, boss_high, boss_axis)])
                    top_face = Part.Face(top_circle)
                    if top_face.normalAt(0, 0).dot(boss_axis) < 0:
                        top_face.reverse()

                    cyl = Part.makeCylinder(radius, height, boss_base, boss_axis)
                    cyl_wall = next((f for f in cyl.Faces if isinstance(f.Surface, Part.Cylinder)), None)

                    if cyl_wall is not None:
                        keep = [f for f in shape.Faces
                                if not f.isSame(base_face)
                                and not all(-boss_near <= (v.Point - boss_base).dot(boss_axis) <= height + boss_near
                                            and ((v.Point - boss_base) - boss_axis * ((v.Point - boss_base).dot(boss_axis))).Length <= radius + boss_near
                                            for v in f.Vertexes)]
                        try:
                            shell = Part.makeShell([new_base_face, top_face, cyl_wall] + keep)
                            shell.fix(1e-7, 1e-7, boss_near)
                            solid = Part.makeSolid(shell)
                            if solid.isValid() and solid.isClosed() and len(solid.Solids) == len(solids):
                                change = abs(shape.Volume - solid.Volume)
                                bound = math.pi * radius ** 2 * height * .35 + near * math.tau * radius * (height + 2 * near)
                                if change <= bound:
                                    return solid
                        except Exception:
                            pass
    raise ValueError('The hole could not be replaced.')


def _rebuild_hole_brep(shape, base, axis, radius, height, tolerance, near):
    """Direct BRep replacement so hole rims become single, continuous analytic circle edges."""
    u, v = (App.Vector(*w) for w in _basis(np.asarray(tuple(axis), dtype=float)))
    high = base + axis * height

    def rim_wire(face, center):
        """One complete circular rim wire of this face, with its vertex offsets."""
        for wire in face.Wires:
            offsets = [vertex.Point - center for vertex in wire.Vertexes]
            if len(offsets) < 8:
                continue
            if any(abs(o.dot(axis)) > near or abs(math.hypot(o.dot(u), o.dot(v)) - radius) > near
                   for o in offsets):
                continue
            angles = sorted({round(math.atan2(o.dot(v), o.dot(u)) % math.tau, 9) for o in offsets})
            if len(angles) < 8:
                continue
            gaps = [b - a for a, b in zip(angles, angles[1:])]
            gaps.append(angles[0] + math.tau - angles[-1])
            if max(gaps) > math.radians(60):
                continue
            return wire, offsets
        return None

    wall_faces, rim_faces, rims = [], [], []
    for face in shape.Faces:
        points = [vertex.Point for vertex in face.Vertexes]
        if not points:
            continue
        offsets = [point - base for point in points]
        if all(-near <= o.dot(axis) <= height + near
               and abs(math.hypot(o.dot(u), o.dot(v)) - radius) <= near for o in offsets):
            wall_faces.append(face)  # one complete faceted wall patch
            continue
        for center in (base, high):
            found = rim_wire(face, center)
            if found is not None:
                rim_faces.append(face)
                rims.append((face, center) + found)
    if not wall_faces or not rims:
        raise ValueError('The faceted hole wall and rims could not be identified.')
    centers = [entry[1] for entry in rims]
    if len(rims) > 2 or len(set(round(c.Length, 6) for c in centers)) != len(centers) or any(
            c.distanceToPoint(base) > near and c.distanceToPoint(high) > near for c in centers):
        raise ValueError('The hole rims must be the two complete circles of one hole.')

    solids = shape.Solids
    if solids:
        if (len(shape.Faces) != sum(len(s.Faces) for s in solids)
                or len(shape.Edges) != sum(len(s.Edges) for s in solids)):
            raise ValueError('The shape carries loose geometry beside its solids.')
        affected = wall_faces + rim_faces
        owners = [index for index, solid in enumerate(solids)
                  if any(candidate.isSame(face) for face in solid.Faces for candidate in affected)]
        if len(owners) != 1:
            raise ValueError('The selected hole must belong to exactly one solid.')
        source = solids[owners[0]]
        others = [solid for index, solid in enumerate(solids) if index != owners[0]]
    else:
        source, others = shape, []

    cylinder = Part.makeCylinder(radius, height, base, axis)
    wall = next((f for f in cylinder.Faces if isinstance(f.Surface, Part.Cylinder)), None)
    if wall is None:
        raise ValueError('The analytic wall could not be created.')
    cyl_circles = [e for e in wall.Edges if isinstance(e.Curve, Part.Circle)]

    rebuilt, keep = [], []
    for face in source.Faces:
        entry = next((r for r in rims if r[0].isSame(face)), None)
        if entry is not None:
            center = entry[1]
            c_edge = next((e for e in cyl_circles if (e.CenterOfMass - center).Length < max(near, 0.05)), None)
            rebuilt.append(_rebuild_rim_face(face, entry, radius, axis, u, v, near, circle_edge=c_edge))
        elif not any(wall_face.isSame(face) for wall_face in wall_faces):
            keep.append(face)

    seam = max(1e-7, tolerance)
    for flip in (False, True):
        face = wall.copy()
        if flip:
            face.reverse()
        shell = Part.makeShell(keep + rebuilt + [face])
        shell.fix(1e-7, 1e-7, seam)
        candidate = Part.makeSolid(shell) if solids else shell
        if candidate.Volume < 0 and solids:
            candidate.reverse()
        try:
            return _verified_hole(source, candidate, others, radius, height, near, bool(solids))
        except ValueError:
            continue
    raise ValueError('The rebuilt hole did not form a valid closed solid.')


def _rebuild_rim_face(face, rim, radius, axis, u, v, near, circle_edge=None):
    """One carrying face with its polygonal rim wire replaced by a circle."""
    _, center, wire, offsets = rim
    ordered_verts = getattr(wire, 'OrderedVertexes', None) or wire.Vertexes
    ordered_offsets = [v.Point - center for v in ordered_verts]
    xy = [(o.dot(u), o.dot(v)) for o in ordered_offsets]
    signed = sum(x1 * y2 - x2 * y1
                 for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1])) / 2
    if abs(signed) < 1e-6:
        sorted_offsets = sorted(offsets, key=lambda o: math.atan2(o.dot(v), o.dot(u)))
        xy_sorted = [(o.dot(u), o.dot(v)) for o in sorted_offsets]
        signed = sum(x1 * y2 - x2 * y1
                     for (x1, y1), (x2, y2) in zip(xy_sorted, xy_sorted[1:] + xy_sorted[:1])) / 2
    ring = math.pi * radius ** 2 - abs(signed)
    try:
        surface = face.Surface
    except Exception:
        raise ValueError('The hole rim must lie on flat faces.')
    if not isinstance(surface, Part.Plane):
        raise ValueError('The hole rim must lie on flat faces.')
    # The face maker classifies wires by direction: keep the rim's role as an
    # outer or inner wire by matching its signed area around the hole axis.
    direction = axis if signed > 0 else axis * -1
    circle = Part.Wire([circle_edge]) if circle_edge is not None else Part.Wire([Part.makeCircle(radius, center, direction)])
    wires = [circle if w.isSame(wire) else w.copy() for w in face.Wires]
    rebuilt = None
    try:
        rebuilt = Part.makeFace(wires, "Part::FaceMakerBullseye")
    except Exception:
        pass
    if rebuilt is None or not rebuilt.isValid() or len(rebuilt.Wires) != len(wires):
        try:
            rebuilt = Part.Face(surface, wires)
        except Exception:
            pass
    if rebuilt is None or not rebuilt.isValid() or len(rebuilt.Wires) != len(wires):
        circle_rev = circle.reversed()
        wires_rev = [circle_rev if w.isSame(wire) else w.copy() for w in face.Wires]
        try:
            rebuilt = Part.makeFace(wires_rev, "Part::FaceMakerBullseye")
        except Exception:
            try:
                rebuilt = Part.Face(surface, wires_rev)
            except Exception:
                pass
    baseline_area = face.Area
    try:
        baseline_face = Part.makeFace([w.copy() for w in face.Wires], "Part::FaceMakerBullseye")
        if baseline_face is not None and baseline_face.isValid() and len(baseline_face.Wires) == len(face.Wires):
            baseline_area = baseline_face.Area
    except Exception:
        pass

    area_diff = min(abs(rebuilt.Area - face.Area), abs(rebuilt.Area - baseline_area)) if rebuilt is not None else 1e9
    max_area_change = ring + max(.05, face.Area * 1e-5, near * radius * 8)
    face_valid = face.isValid()
    if (rebuilt is None or (face_valid and not rebuilt.isValid()) or len(rebuilt.Wires) != len(wires)
            or area_diff > max_area_change):
        raise ValueError('A rim face could not be rebuilt with its analytic circle.')
    if rebuilt.normalAt(0, 0).dot(face.normalAt(0, 0)) < 0:
        rebuilt.reverse()
    return rebuilt


def _verified_hole(source, candidate, others, radius, height, near, solid):
    """Validate a rebuilt hole against its source and assemble the result."""
    was_valid = source.isValid()
    if candidate.isNull() or (was_valid and not candidate.isValid()):
        raise ValueError('The rebuilt hole is invalid.')
    if solid:
        if len(candidate.Solids) != 1 or (source.isClosed() and not candidate.isClosed()):
            raise ValueError('The rebuilt hole did not stay one closed solid.')
        # Holes lose the slivers between polygon and circle, bosses regain them.
        change = abs(source.Volume - candidate.Volume)
        bound = math.pi * radius ** 2 * height * .35 + near * math.tau * radius * (height + 2 * near)
        if change > bound:
            raise ValueError('The rebuilt hole changed more than the faceted slivers.')
    elif len(candidate.Faces) >= len(source.Faces):
        raise ValueError('The rebuilt hole did not merge the faceted wall.')
    parts = [candidate] + others
    result = parts[0] if len(parts) == 1 else Part.makeCompound(parts)
    if was_valid and not result.isValid():
        raise ValueError('The rebuilt shape failed validation.')
    return result


def reconstruct_cylinder(mesh, tolerance, progress):
    """Return ``(shape, detail)`` for a confidently closed cylindrical mesh.

    The complete-component requirement is deliberate: replacing a partial
    cylindrical wall or a cylinder fused to another part with a new primitive
    would silently change the model.  Those cases return ``(None, {})``.
    """
    if not mesh.isSolid() or mesh.CountFacets < 12:
        return None, {}
    data = _triangle_data(mesh)
    if data is None:
        return None, {}
    xyz, indices, corners, normals, centers, lengths = data

    # The least-variance normal direction is the cylinder axis.  Caps can be
    # numerous, so test all three eigenvectors and retain the candidate with
    # the strongest side-normal population and the best circular fit.
    covariance = normals.T @ normals
    try:
        _, _, eigenvectors = np.linalg.svd(covariance)
    except np.linalg.LinAlgError:
        return None, {}
    candidates = [row / np.linalg.norm(row) for row in eigenvectors]
    side_angle = .22  # about 13 degrees, allowing imperfect STL normals
    best = None
    for axis in candidates:
        side = np.abs(normals @ axis) <= side_angle
        side_count = int(side.sum())
        if side_count < max(8, int(len(normals) * .2)):
            continue
        fit = _fit_circle(xyz[np.unique(indices[side])], axis)
        if fit is None:
            continue
        center, radius, residual, largest_gap, u, v = fit
        # A complete circular rim has no large unobserved arc.  This rejects
        # partial cylindrical patches and cylinders fused into other geometry.
        if largest_gap > math.radians(70):
            continue
        score = (side_count, -residual)
        if best is None or score > best[0]:
            best = (score, axis, side, fit)
    if best is None:
        return None, {}

    _, axis, side, fit = best
    center, radius, residual, _, _, _ = fit
    axial = (xyz - center) @ axis
    amin, amax = float(axial.min()), float(axial.max())
    height = amax - amin
    if height <= max(1e-7, tolerance * .5):
        return None, {}
    # The fitted circle must be much closer than the user-selected tolerance;
    # tolerance is a repair bound, not permission to turn a rounded polygon
    # into a cylinder with visibly different dimensions.
    radial_limit = max(tolerance * 2.0, radius * .001)
    if residual > radial_limit:
        return None, {}

    cap = np.abs(normals @ axis) >= .86
    undecided = ~(side | cap)
    if int(undecided.sum()) > max(2, int(len(normals) * .03)):
        return None, {}
    cap_centers = (centers - center) @ axis
    low_cap = cap & (np.abs(cap_centers - amin) <= max(tolerance * 3, height * .01))
    high_cap = cap & (np.abs(cap_centers - amax) <= max(tolerance * 3, height * .01))
    if not low_cap.any() or not high_cap.any():
        return None, {}

    base = App.Vector(*(center + axis * amin))
    direction = App.Vector(*axis)
    try:
        shape = Part.makeCylinder(radius, height, base, direction)
    except (RuntimeError, ValueError, Part.OCCError):
        return None, {}
    if not shape.isValid() or not shape.Solids:
        return None, {}
    source_volume = _mesh_volume(corners, center)
    # A faceted circumference underestimates the analytic volume slightly.
    if abs(shape.Volume - source_volume) > max(shape.Volume * .03, tolerance * sum(lengths) * 3):
        return None, {}
    progress('Recognized analytic cylinder')
    return shape, {'cylinders': 1, 'max_cylinder_radius_deviation': residual}
