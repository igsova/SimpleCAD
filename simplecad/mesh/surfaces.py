"""Rebuild a dense mesh as a few fitted CAD faces: planes and smooth B-splines.

surface_fit groups the triangles into patches and fits one surface to each.
Here every shared patch boundary becomes one curve lying on both neighboring
surfaces, every patch one trimmed face, and the faces one validated shell or
solid. Any failure raises ValueError, so the caller can keep the existing
flat-face reconstruction instead.
"""
import math

import numpy as np
import FreeCAD as App
import Part

from ..surfaces import fit as surface_fit


def _vector(value):
    return App.Vector(*map(float, value))


def _surface(fit):
    if fit.kind == 'plane':
        return Part.Plane(_vector(fit.origin), _vector(fit.normal))
    poles = fit.poles()
    uknots, umults = np.unique(fit.uknots, return_counts=True)
    vknots, vmults = np.unique(fit.vknots, return_counts=True)
    surface = Part.BSplineSurface()
    surface.buildFromPolesMultsKnots([[_vector(q) for q in row] for row in poles],
                                     umults.tolist(), vmults.tolist(), uknots.tolist(), vknots.tolist(),
                                     False, False, surface_fit.DEGREE, surface_fit.DEGREE)
    return surface


def _spacing(surface):
    if surface.kind != 'bspline':
        return math.inf
    return min(np.diff(surface.ubreaks).min(), np.diff(surface.vbreaks).min())/2


def _between(points, surfaces):
    """Midpoints of the points' projections onto the surfaces, and their gap."""
    projected = [surface.project(points) for surface in surfaces]
    return np.mean(projected, axis=0), float(np.max(np.linalg.norm(projected[0]-projected[-1], axis=1)))


def _chain_points(facets, chain, patches, tolerance):
    """Points along one chain between its neighboring surfaces, and the gap.

    The mesh chain lies on both neighbors within their fitting limits.
    Each sample moves to the midpoint of its projections onto the two
    surfaces, so the curve stays within half their gap of each. The end
    vertices stay where they are, shared with the neighboring chains.

    Between smooth neighbors the mesh edges step from triangle to triangle.
    There the path is smoothed within the left surface by up to half the
    height of the triangles along it, then put back between the surfaces,
    unless their gap grows past half the tolerance: a curve following every
    step would show as a jagged edge on a smooth part. Each surface also
    follows its neighbor's first row of triangles (surface_fit.fit), so
    both still describe the mesh where the curve now runs.

    Across a sharp edge the surfaces cross, and each sample moves on to
    their intersection where alternating projections reach it nearby: the
    edge then lies on both faces, and a circular rim comes out exactly
    circular. A loose closed chain has no shared end vertex to keep.
    """
    xyz = facets.points[chain.vertices]
    surfaces = [patches[chain.left].surface] + ([patches[chain.right].surface] if chain.right >= 0 else [])
    lengths = np.linalg.norm(np.diff(xyz, axis=0), axis=1)
    spacing = max(min(_spacing(s) for s in surfaces), lengths.sum()/400, facets.extent*1e-5)
    count = np.clip(np.ceil(lengths/spacing), 1, 64).astype(np.int64)
    index = np.repeat(np.arange(len(lengths)), count)
    t = ((np.arange(count.sum())-np.repeat(np.cumsum(count)-count, count))/np.repeat(count, count))[:, None]
    points = np.vstack((xyz[index]*(1-t)+xyz[index+1]*t, xyz[-1:]))
    moved, gap = _between(points, surfaces)
    gap = max(gap, max(float(s.distance(xyz).max()) for s in surfaces))
    if chain.smooth and len(xyz) > 2:
        halves = np.asarray(chain.halves)
        sides = np.stack((facets.owner[halves], facets.owner[facets.twin[halves]]))
        heights = 2*facets.areas[sides]/np.maximum(lengths, 1e-300)
        amount = max(min(float(np.median(heights.min(axis=0))), float(np.median(lengths)))/2, tolerance/4)
        flat = surfaces[0].parameters(moved)
        if surfaces[0].kind == 'cylinder':
            flat[:, 0] = np.unwrap(flat[:, 0], period=surfaces[0].period)
        fitted = surface_fit.fit_curve(flat, amount)
        along = np.linspace(0, 1, len(moved))[:, None]
        flat = flat[0]*(1-along)+flat[-1]*along if fitted is None else surface_fit.curve_points(fitted, len(moved))
        smoothed, smooth_gap = _between(surfaces[0].at(flat), surfaces)
        if smooth_gap <= max(gap, tolerance/2):
            moved, gap = smoothed, max(gap, smooth_gap)
    elif len(surfaces) == 2:
        exact = moved
        for _ in range(40):
            following = surfaces[0].project(surfaces[1].project(exact))
            change = float(np.max(np.linalg.norm(following-exact, axis=1)))
            exact = following
            if change <= 1e-6*tolerance:
                break
        good = ((surfaces[1].distance(exact) <= 1e-3*tolerance)
                & (np.linalg.norm(exact-moved, axis=1) <= tolerance/2))
        moved = np.where(good[:, None], exact, moved)
    if chain.loose:
        moved[-1] = moved[0]
    else:
        moved[0], moved[-1] = xyz[0], xyz[-1]
    return moved, gap


def _seam_angle(facets, fit, chains, loops):
    """Where a cylinder face's seam goes: the middle of the widest angular
    gap of its loops that do not go around the axis (its holes, or the
    outline of a partial face), so none of them straddles the seam."""
    angles = []
    for runs in loops:
        vertices = np.concatenate([(chains[chain].vertices if forward else chains[chain].vertices[::-1])[:-1]
                                   for chain, forward in runs])
        theta = fit.parameters(facets.points[vertices])[:, 0]/fit.radius
        step = (np.diff(np.r_[theta, theta[:1]])+math.pi) % (2*math.pi)-math.pi
        if abs(step.sum()) < math.pi:
            angles.append(theta)
    if not angles:
        return 0.0
    ordered = np.sort(np.concatenate(angles))
    gaps = np.diff(np.r_[ordered, ordered[0]+2*math.pi])
    widest = int(np.argmax(gaps))
    return float(ordered[widest]+gaps[widest]/2)


def _start_at_seam(points, fit):
    """A closed seam around a cylinder's axis, restarted exactly on the
    cylinder's seam line, where OCC joins a band's two rims."""
    theta = (fit.parameters(points)[:, 0]/fit.radius-fit.seam+math.pi) % (2*math.pi)-math.pi
    step = np.diff(theta)
    if abs(((step+math.pi) % (2*math.pi)-math.pi).sum()) < math.pi:
        return points
    crossing = np.flatnonzero(((theta[:-1] < 0) != (theta[1:] < 0)) & (np.abs(step) < math.pi))
    if not len(crossing):
        return points
    i = int(crossing[0])
    point = points[i]+(points[i+1]-points[i])*(theta[i]/(theta[i]-theta[i+1]))
    height, radial = fit._split(point[None])
    point = (fit.origin+height[0]*fit.axis
             + np.linalg.norm(radial)*(math.cos(fit.seam)*fit.x+math.sin(fit.seam)*fit.y))
    return np.vstack((point, points[i+1:-1], points[:i+1], point))


class _Frame:
    """Coordinates of a patch surface's parameter plane."""

    def __init__(self, fit, surface):
        self.fit = fit
        if fit.kind == 'plane':
            origin = surface.value(0, 0)
            self.origin = np.asarray(tuple(origin))
            self.axes = np.asarray([tuple(surface.value(1, 0)-origin), tuple(surface.value(0, 1)-origin)])

    def local(self, points):
        if self.fit.kind == 'plane':
            return (points-self.origin) @ self.axes.T
        return self.fit.local(points)[0]


def _signed_area(points):
    x, y = points[:, 0], points[:, 1]
    return .5*float(np.sum(x*np.roll(y, -1)-np.roll(x, -1)*y))


def _arc(points, tolerance, largest, cylinder=None):
    """A circle or circular arc edge within tolerance of the points, or None.

    Hole rims and other turned edges are circles; an exact circle keeps
    them round and measurable. A closed chain becomes a whole circle, which
    no other chain touches; an open one runs exactly between its end
    points, which its neighboring chains share. A whole circle around a
    cylinder is made coaxial with it and starts on its seam line.
    """
    if len(points) < 5:
        return None
    center, normal, flat = surface_fit._plane(points)
    if flat > tolerance:
        return None
    helper = np.eye(3)[int(np.argmin(np.abs(normal)))]
    e1 = np.cross(normal, helper)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(normal, e1)
    middle, radius = surface_fit._circle_2d(np.c_[(points-center) @ e1, (points-center) @ e2])
    if not tolerance < radius <= largest:
        return None
    closed = np.linalg.norm(points[0]-points[-1]) <= 1e-9
    try:
        if closed:
            middle = center+middle[0]*e1+middle[1]*e2
            if cylinder is not None:
                # Only a coaxial circle starts exactly on the seam line.
                height, radial = cylinder._split(points)
                middle = cylinder.origin+float(height.mean())*cylinder.axis
                normal = cylinder.axis
                radius = float(np.linalg.norm(radial, axis=1).mean())
            circle = Part.Circle(_vector(middle), _vector(normal), radius)
            start = points[0]-middle
            circle.XAxis = _vector(start-(start @ normal)*normal)
        else:
            circle = Part.ArcOfCircle(*(_vector(points[i]) for i in (0, len(points)//2, -1)))
    except (RuntimeError, Part.OCCError):
        return None
    axis, origin = np.asarray(tuple(circle.Axis)), np.asarray(tuple(circle.Center))
    relative = points-origin
    height = relative @ axis
    within = relative-np.outer(height, axis)
    if np.max(np.hypot(np.linalg.norm(within, axis=1)-circle.Radius, height)) > tolerance:
        return None
    if not closed:
        # The points must run along the arc itself, not around the rest of
        # its circle: their angles from the start grow up to the end's.
        angles = np.unwrap(np.arctan2(np.cross(within[0], within) @ axis, within @ within[0]))
        span = circle.LastParameter-circle.FirstParameter
        if abs(angles[-1]-span) > 1e-6 or np.any(np.diff(angles) < -4*tolerance/circle.Radius):
            return None
    return circle.toShape()


def _curve(points, tolerance, largest=math.inf, cylinder=None):
    """A 3D line, circular arc or cubic B-spline edge through the points,
    exact at both ends."""
    fitted = surface_fit.fit_curve(points, tolerance)
    if fitted is None:
        return Part.LineSegment(_vector(points[0]), _vector(points[-1])).toShape()
    arc = _arc(points, tolerance, largest, cylinder)
    if arc is not None:
        return arc
    knots, poles = fitted
    values, mults = np.unique(knots, return_counts=True)
    curve = Part.BSplineCurve()
    curve.buildFromPolesMultsKnots([_vector(q) for q in poles], mults.tolist(), values.tolist(),
                                   False, surface_fit.DEGREE)
    return curve.toShape()


def _tessellated(shape, tolerance):
    """Area and enclosed volume of the shape's tessellation.

    OCC integrates area and volume over a B-spline face with a fixed number
    of points, which misses several percent on surfaces with many knots;
    the tessellation follows the trimmed faces within the tolerance.
    """
    points, triangles = shape.tessellate(tolerance)
    if not triangles:
        return 0.0, 0.0
    points = np.asarray([tuple(point) for point in points])
    corners = points[np.asarray(triangles)]
    cross = np.cross(corners[:, 1]-corners[:, 0], corners[:, 2]-corners[:, 0])
    volume = float(np.einsum('ij,ij->i', corners[:, 0], cross).sum())/6
    return float(np.linalg.norm(cross, axis=1).sum())/2, volume


def _cylinder_face(fit, loops, seams, edges, tolerance):
    """One face of a cylinder patch: a band around the axis, or a part of
    the cylinder bounded by one outer loop.

    Loops are measured in unwrapped (arc length, height) coordinates. A loop
    that goes once around the axis bounds a band; a band needs exactly two
    of them. OCC then adds the seam between the two rims, along the seam
    line chosen by _seam_angle, where both rims start. Wires are built
    counterclockwise about the cylinder's outward normal, and the face is
    reversed afterwards for a hole, whose triangles face the axis.
    """
    sign = 1.0 if fit.outward else -1.0
    wires, areas, around = [], [], []
    for runs in loops:
        points = np.vstack([(seams[chain] if forward else seams[chain][::-1])[:-1] for chain, forward in runs])
        flat = fit.parameters(points)
        step = np.diff(np.r_[flat[:, 0], flat[:1, 0]])
        step = (step+fit.period/2) % fit.period-fit.period/2
        winding = step.sum()/fit.period
        wire = Part.Wire([edges[chain] if forward else edges[chain].reversed() for chain, forward in runs])
        wires.append(wire if fit.outward else wire.reversed())
        around.append(abs(winding) > .5)
        unwrapped = np.c_[flat[0, 0]+np.r_[0, np.cumsum(step[:-1])], flat[:, 1]]
        areas.append(sign*_signed_area(unwrapped))
    bands = [wire for wire, loop in zip(wires, around) if loop]
    others = [(wire, area) for wire, area, loop in zip(wires, areas, around) if not loop]
    outer = [wire for wire, area in others if area > 0]
    if not ((len(bands) == 2 and not outer) or (not bands and len(outer) == 1)):
        raise ValueError('A fitted cylinder face has no single outer boundary.')
    direction = math.cos(fit.seam)*fit.x+math.sin(fit.seam)*fit.y
    circle = Part.Circle(_vector(fit.origin), _vector(fit.axis), fit.radius)
    circle.XAxis = _vector(direction)
    surface = Part.Cylinder(circle)
    holes = [wire for wire, area in others if area <= 0]
    try:
        if bands:
            face = Part.Face(surface, bands[0])
            face.cutHoles(bands[1:]+holes)
            fixer = Part.ShapeFix.Face(face)
            fixer.perform()
            face = fixer.face()
        else:
            face = Part.Face(surface, outer[0])
            if holes:
                face.cutHoles(holes)
        face.fix(1e-7, 1e-7, tolerance)
    except (RuntimeError, Part.OCCError):
        face = None
    # The seam joins a band's two rims into one wire.
    if face is None or face.isNull() or not face.isValid() or len(face.Wires) != len(wires)-len(bands)//2:
        raise ValueError('A fitted cylinder face could not be trimmed to its boundary.')
    if not fit.outward:
        face.reverse()
    return face


def _face(patch, loops, seams, edges, tolerance):
    """One face of the patch surface, trimmed by the shared seam edges."""
    if patch.surface.kind == 'cylinder':
        return _cylinder_face(patch.surface, loops, seams, edges, tolerance)
    surface = _surface(patch.surface)
    frame = _Frame(patch.surface, surface)
    wires, areas = [], []
    for runs in loops:
        outline = [frame.local(seams[chain] if forward else seams[chain][::-1])[:-1] for chain, forward in runs]
        wires.append(Part.Wire([edges[chain] if forward else edges[chain].reversed() for chain, forward in runs]))
        areas.append(_signed_area(np.vstack(outline)))
    outer = int(np.argmax(areas))
    if areas[outer] <= 0 or sum(area > 0 for area in areas) != 1:
        raise ValueError('A fitted face has no single outer boundary.')
    try:
        face = Part.Face(surface, wires[outer])
        holes = [wire for index, wire in enumerate(wires) if index != outer]
        if holes:
            face.cutHoles(holes)
        face.fix(1e-7, 1e-7, tolerance)
    except (RuntimeError, Part.OCCError):
        face = None
    if face is None or face.isNull() or not face.isValid() or len(face.Wires) != len(wires):
        raise ValueError('A fitted face could not be trimmed to its boundary.')
    return face


def reconstruct(mesh_points, mesh_faces, closed, tolerance, progress=lambda message: None):
    """Return (shape, detail) built from fitted surfaces, or raise ValueError.

    When a part with fitted cylinders cannot be joined, it is fitted once
    more with smooth surfaces in their place.
    """
    progress('Finding smooth surface patches')
    facets = surface_fit.Facets(mesh_points, mesh_faces)
    patches = surface_fit.fit_patches(facets, tolerance, progress)
    try:
        return _assemble(facets, patches, closed, tolerance, progress)
    except ValueError:
        if not any(patch.surface.kind == 'cylinder' for patch in patches):
            raise
    progress('Fitting smooth surfaces without cylinders')
    patches = surface_fit.fit_patches(facets, tolerance, progress, cylinders=False)
    return _assemble(facets, patches, closed, tolerance, progress)


def _assemble(facets, patches, closed, tolerance, progress):
    labels = np.empty(len(facets.faces), dtype=np.int64)
    for index, patch in enumerate(patches):
        labels[patch.triangles] = index
    progress('Joining %d fitted surfaces' % len(patches))
    chains, loops = surface_fit.boundaries(facets, labels)
    for index, patch in enumerate(patches):
        if patch.surface.kind == 'cylinder':
            patch.surface.seam = _seam_angle(facets, patch.surface, chains, loops[index])
    seams, edges, edge_gap = [], [], 0.0
    for chain in chains:
        points, gap = _chain_points(facets, chain, patches, tolerance)
        cylinder = None
        if chain.loose:
            cylinder = next((patches[side].surface for side in (chain.left, chain.right)
                             if side >= 0 and patches[side].surface.kind == 'cylinder'), None)
            if cylinder is not None:
                points = _start_at_seam(points, cylinder)
        seams.append(points)
        edges.append(_curve(points, tolerance/4, facets.extent, cylinder))
        edge_gap = max(edge_gap, gap)
    if edge_gap > tolerance:
        raise ValueError('Neighboring fitted surfaces do not meet within the tolerance.')
    progress('Trimming fitted faces')
    faces = []
    for index, patch in enumerate(patches):
        face = _face(patch, loops[index], seams, edges, tolerance)
        area = float(facets.areas[patch.triangles].sum())
        if abs(_tessellated(face, tolerance)[0]-area) > max(area*.05, tolerance*face.Length):
            raise ValueError('A fitted face does not cover its triangles.')
        faces.append(face)
    progress('Joining fitted faces')
    shell = Part.makeShell(faces)
    shell.sewShape(max(2*edge_gap, 1e-4))
    if shell.ShapeType != 'Shell' or len(shell.Faces) != len(faces):
        raise ValueError('Fitted faces could not be joined into one shell.')
    if not shell.isValid():
        shell.fix(1e-7, 1e-7, tolerance)
    if not shell.isValid() or (closed and not shell.isClosed()):
        raise ValueError('Fitted faces did not form a valid closed shell.')
    shape = Part.makeSolid(shell) if closed else shell
    volume_change = 0.0
    if closed:
        volume = _tessellated(shape, tolerance)[1]
        if volume < 0:
            shape.reverse()
        corners = facets.points[facets.faces]
        expected = abs(float(np.einsum('ij,ij->i', corners[:, 0],
                                       np.cross(corners[:, 1], corners[:, 2])).sum())/6)
        # A mean offset within the tolerance over the whole surface.
        volume_change = abs(volume)-expected
        if abs(volume_change) > tolerance*float(facets.areas.sum()):
            raise ValueError('The fitted solid does not enclose the mesh volume.')
    if not shape.isValid():
        raise ValueError('The fitted solid failed validation.')
    deviation = 0.0
    for patch in patches:
        corners = facets.points[facets.faces[patch.triangles]]
        samples = np.vstack((facets.points[np.unique(facets.faces[patch.triangles])], corners.mean(axis=1),
                             (corners+np.roll(corners, 1, axis=1)).reshape(-1, 3)/2))
        deviation = max(deviation, float(patch.surface.distance(samples).max()))
    kinds = [patch.surface.kind for patch in patches]
    return shape, {'fitted_faces': len(patches), 'fitted_planes': kinds.count('plane'),
                   'fitted_smooth': kinds.count('bspline')+kinds.count('cylinder'),
                   'fitted_cylinders': kinds.count('cylinder'),
                   'max_vertex_deviation': max(patch.surface.error for patch in patches),
                   'max_facet_deviation': deviation, 'max_edge_gap': edge_gap, 'volume_change': volume_change}
