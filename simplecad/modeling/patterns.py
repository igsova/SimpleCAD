"""Placements for grid, radial and along-a-path arrays of whole objects.

Pure math: each function returns the world placements of the copies, without
the original (which stays where it is). A copy's Placement is
``placement.multiply(original.Placement)``. Counts include the original.
"""
import FreeCAD as App
import Part

V = App.Vector
LIMIT = 500  # copies per pattern; more is almost always a typo
KINDS = ('grid', 'radial', 'path')


def _check(total):
    if total < 2:
        raise ValueError('Use a count of at least 2 to make copies.')
    if total > LIMIT + 1:
        raise ValueError('A pattern can make at most %d copies.' % LIMIT)


def grid(counts, spacing):
    """Copies spaced along world X, Y and Z: counts (nx, ny, nz), spacing in mm."""
    counts = [int(n) for n in counts]
    if len(counts) != 3 or len(spacing) != 3 or min(counts) < 1:
        raise ValueError('Give a count of 1 or more and a spacing for X, Y and Z.')
    for n, step in zip(counts, spacing):
        if n > 1 and abs(step) < 1e-9:
            raise ValueError('Give a spacing other than zero along each direction with more than one copy.')
    _check(counts[0] * counts[1] * counts[2])
    result = []
    for k in range(counts[2]):
        for j in range(counts[1]):
            for i in range(counts[0]):
                if i or j or k:
                    result.append(App.Placement(V(i * spacing[0], j * spacing[1], k * spacing[2]), App.Rotation()))
    return result


def radial(count, axis, center, angle=360.0):
    """Copies turned around an axis through center.

    A full turn spreads count instances evenly; a partial angle places the
    last copy at that angle.
    """
    count = int(count)
    _check(count)
    axis = V(axis)
    if axis.Length < 1e-12:
        raise ValueError('Choose an axis direction.')
    if abs(angle) < 1e-9 or abs(angle) > 360 + 1e-9:
        raise ValueError('Use an angle between -360 and 360 degrees, other than zero.')
    step = angle / count if abs(abs(angle) - 360) < 1e-9 else angle / (count - 1)
    return [App.Placement(V(), App.Rotation(axis, step * i), V(center)) for i in range(1, count)]


def _wire(path):
    if path.ShapeType == 'Wire':
        return path
    edges = list(path.Edges)
    if not edges:
        raise ValueError('Select an edge or connected edges as the path.')
    try:
        groups = Part.sortEdges(edges)
    except Exception as error:
        raise ValueError('The path edges must connect end to end.') from error
    if len(groups) != 1:
        raise ValueError('The path edges must connect end to end, without branches or gaps.')
    return Part.Wire(groups[0])


def along(path, count, align=True):
    """Copies moved along a path, spaced evenly by length.

    The original stays at the path's start; each copy keeps the original's
    offset from the path. With align, copies also turn with the path.
    """
    count = int(count)
    _check(count)
    wire = _wire(path)
    if wire.Length < 1e-6:
        raise ValueError('The path has no length.')
    closed = wire.isClosed()
    detail = 16
    samples = count * detail + 1 if closed else (count - 1) * detail + 1
    points = wire.discretize(Number=samples)

    edges = wire.OrderedEdges

    def tangent(index):
        """The exact tangent of the edge under the sample, in path direction."""
        before = points[index - 1] if index > 0 else (points[-2] if closed else points[index])
        after = points[index + 1] if index < len(points) - 1 else (points[1] if closed else points[index])
        rough = after - before
        point = points[index]
        edge = min(edges, key=lambda e: e.distToShape(Part.Vertex(point))[0])
        try:
            exact = edge.tangentAt(edge.Curve.parameter(point))
        except (Part.OCCError, RuntimeError):
            exact = rough
        if exact.Length < 1e-12:
            return V(1, 0, 0)
        exact = exact.normalize()
        return exact * -1 if exact.dot(rough) < 0 else exact

    start, first = points[0], tangent(0)
    result = []
    for i in range(1, count):
        index = i * detail
        rotation = App.Rotation(first, tangent(index)) if align else App.Rotation()
        result.append(App.Placement(points[index] - start, rotation, start))
    return result
