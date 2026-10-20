"""Read-only measurements of picked vertices, edges, faces and holes.

Nothing here edits a document. A picked element resolves to a Target; one
target is described on its own, two are measured against each other. Faceted
holes of converted parts are fitted, so a click on one rim edge or one wall
facet reports the hole's diameter like an analytic cylinder does.
"""
from dataclasses import dataclass, field
import math

import FreeCAD as App
import Part

from ..core import geometry as geo

V = App.Vector
PARALLEL = 1e-6  # Directions within this of each other count as parallel.
WALL_REACH = 60.0  # mm; faceted walls searched farther than this are not holes.


@dataclass
class Target:
    kind: str                # 'Vertex', 'Circle', 'Edge' or 'Face'
    label: str               # shown to the user, such as 'Hole Ø6.000'
    shape: object            # the element measured against for distances
    point: object            # a representative point: vertex, center or centroid
    radius: float = None     # circles, arcs and cylinders
    axis: object = None      # circle and cylinder axis
    depth: float = None      # cylinder length along its axis
    normal: object = None    # flat faces
    direction: object = None  # straight edges
    outline: list = field(default_factory=list)  # polylines to highlight


@dataclass
class Row:
    name: str
    value: object            # float, or a Vector for coordinates and axes
    unit: str = 'mm'

    def text(self):
        if isinstance(self.value, str):
            return self.value
        if isinstance(self.value, App.Vector):
            if self.unit == '':
                return '(%.4f, %.4f, %.4f)' % tuple(self.value)
            return 'X %s  Y %s  Z %s' % tuple(length(v) for v in self.value)
        if self.unit == '°':
            return '%.3f°' % self.value
        if self.unit == 'mm²':
            return '%.3f mm²' % self.value
        return length(self.value)


@dataclass
class Measurement:
    rows: list
    line: tuple = None       # the main dimension, from one point to another
    label: str = ''          # its value, shown in the view
    extra: list = field(default_factory=list)  # further dimension lines


def length(value):
    return '%.3f mm' % value


def circle_points(center, axis, radius, count=64):
    u, v = geo.Plane.from_normal(center, axis).u, geo.Plane.from_normal(center, axis).v
    return [center + u * (radius * math.cos(i * math.tau / count)) + v * (radius * math.sin(i * math.tau / count))
            for i in range(count + 1)]


def _circle(label, shape, center, axis, radius, depth=None):
    axis = geo.unit(V(axis))
    outline = [circle_points(center, axis, radius)]
    if depth:
        outline.append(circle_points(center + axis * depth, axis, radius))
    return Target('Circle', label, shape, V(center), radius=radius, axis=axis, depth=depth, outline=outline)


def _faceted_loop(shape, edge):
    """The circle a straight edge belongs to as one side of a faceted round loop,
    and the wall face beside it."""
    from ..mesh.curved import fit_circle_loop
    from ..core.preferences import precision
    owners = shape.ancestorsOfType(edge, Part.Face)
    for face in owners:
        if not isinstance(face.Surface, Part.Plane):
            continue
        for wire in face.Wires:
            if len(wire.Edges) >= 8 and any(e.isSame(edge) for e in wire.Edges):
                fit = fit_circle_loop([v.Point for e in wire.Edges for v in e.Vertexes], precision())
                if fit is not None:
                    return fit, next((other for other in owners if not other.isSame(face)), None)
    return None, None


def faceted_wall(shape, face):
    """The cylinder a flat facet belongs to as part of a faceted wall, and the
    wall's facets, or None.

    Only nearby faces are searched, found through the shape's face index; the
    region grows until the wall found no longer reaches its border.
    """
    from ..modeling import analytic
    # A wall facet is a narrow strip meeting its neighbours at gentle creases.
    if face.countElement('Edge') > 6:
        return None
    normal = geo.face_normal(face)
    creased = any(.85 < geo.face_normal(other).dot(normal) < .9999
                  for edge in face.Edges for other in shape.ancestorsOfType(edge, Part.Face)
                  if not other.isSame(face) and isinstance(other.Surface, Part.Plane))
    if not creased:
        return None
    index = geo.face_index(shape)
    # A hole's facets are narrow: its circumference is many facet widths.
    # Start near the facet and grow; a wall still reaching the border at
    # hole size belongs to a large curved surface, not a hole.
    reach = max(4 * min(edge.Length for edge in face.Edges), .5)
    while True:
        if reach > WALL_REACH:
            return None
        region = face.BoundBox
        region.enlarge(reach)
        nearby = [index.faces[i] for i in index.near(region)]
        wall = analytic._expand_wall_faces(Part.makeCompound(nearby), [face])
        bounds = Part.makeCompound(wall).BoundBox
        if all(getattr(bounds, a + 'Min') > getattr(region, a + 'Min') + 1e-6
               and getattr(bounds, a + 'Max') < getattr(region, a + 'Max') - 1e-6 for a in 'XYZ'):
            break
        reach *= 3
    if len(wall) < 6:
        return None
    try:
        fit = analytic._fit_cloud(analytic._sample_points(wall), analytic.FIT_TOLERANCE, faces=wall)
    except ValueError:
        return None
    return (fit, wall) if fit['height'] > geo.EPS else None


def _hole_word(wall, axis_point, axis):
    """'Hole' when the wall faces its axis, 'Cylinder' for a boss or rod.

    A face's normal points out of the material: into a hole, away from a boss.
    """
    if wall is None:
        return 'Circle'
    try:
        u0, u1, v0, v1 = wall.ParameterRange
        point = wall.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
        normal = wall.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    except (Part.OCCError, RuntimeError):
        return 'Circle'
    offset = point - axis_point
    radial = offset - axis * offset.dot(axis)
    if radial.Length <= geo.EPS:
        return 'Circle'
    return 'Hole' if normal.dot(radial) < 0 else 'Cylinder'


def resolve(shape, name, picked=None):
    """What a picked element of a shape measures as."""
    element = shape.getElement(name)
    kind = element.ShapeType
    if kind == 'Vertex':
        point = element.Point
        return Target('Vertex', 'Vertex', element, point, outline=[[point, point]])
    if kind == 'Edge':
        try:
            curve = element.Curve
        except (TypeError, RuntimeError, Part.OCCError):
            curve = None
        if isinstance(curve, (Part.Circle, Part.ArcOfCircle)):
            walls = [face for face in shape.ancestorsOfType(element, Part.Face)
                     if not isinstance(face.Surface, Part.Plane)] if shape.countElement('Face') else []
            word = _hole_word(walls[0], curve.Center, geo.unit(V(curve.Axis))) if walls else 'Circle'
            if word == 'Circle' and not element.isClosed():
                word = 'Arc'
            target = _circle('%s Ø%.3f' % (word, 2 * curve.Radius), element, curve.Center, curve.Axis, curve.Radius)
            target.outline = [element.discretize(Angular=math.radians(5), Curvature=.1, Minimum=2)]
            return target
        if isinstance(curve, Part.Line):
            fit, wall = _faceted_loop(shape, element) if shape.countElement('Face') else (None, None)
            if fit is not None:
                word = _hole_word(wall, fit['center'], geo.unit(fit['normal']))
                return _circle('%s Ø%.3f (faceted)' % (word, 2 * fit['radius']), element,
                               fit['center'], fit['normal'], fit['radius'])
            ends = [v.Point for v in element.Vertexes]
            direction = geo.unit(ends[-1] - ends[0]) if (ends[-1] - ends[0]).Length > geo.EPS else None
            return Target('Edge', 'Edge %.3f mm' % element.Length, element,
                          (ends[0] + ends[-1]) * .5, direction=direction, outline=[ends])
        return Target('Edge', 'Curve %.3f mm' % element.Length, element,
                      element.valueAt((element.FirstParameter + element.LastParameter) / 2),
                      outline=[element.discretize(Angular=math.radians(5), Curvature=.1, Minimum=2)])
    if kind == 'Face':
        surface = element.Surface
        if isinstance(surface, Part.Cylinder):
            axis = geo.unit(V(surface.Axis))
            spans = [(v.Point - surface.Center).dot(axis) for v in element.Vertexes] or [0.0]
            low, high = min(spans), max(spans)
            base = surface.Center + axis * low
            word = _hole_word(element, base, axis)
            return _circle('%s Ø%.3f' % (word, 2 * surface.Radius), element, base,
                           axis, surface.Radius, depth=high - low)
        if isinstance(surface, Part.Plane):
            found = faceted_wall(shape, element)
            if found is not None:
                fit = found[0]
                word = _hole_word(element, fit['base'], geo.unit(fit['axis']))
                return _circle('%s Ø%.3f (faceted)' % (word, 2 * fit['radius']), element, fit['base'],
                               fit['axis'], fit['radius'], depth=fit['height'])
            return Target('Face', 'Flat face', element, element.CenterOfMass,
                          normal=geo.face_normal(element), outline=[e.discretize(Angular=math.radians(5), Curvature=.1, Minimum=2)
                                                                    for e in element.Edges])
        point = picked if picked is not None else element.CenterOfMass
        return Target('Face', type(surface).__name__.replace('Surface', '') + ' face', element, point,
                      outline=[e.discretize(Angular=math.radians(5), Curvature=.1, Minimum=2) for e in element.Edges])
    raise ValueError('Pick a vertex, edge or face.')


def describe(target):
    """The measurements of one target on its own."""
    rows = []
    if target.kind == 'Vertex':
        rows.append(Row('Position', target.point))
    elif target.kind == 'Circle':
        rows += [Row('Diameter', 2 * target.radius), Row('Radius', target.radius),
                 Row('Center', target.point), Row('Axis', target.axis, '')]
        if target.depth:
            rows.append(Row('Depth', target.depth))
    elif target.kind == 'Edge':
        rows.append(Row('Length', target.shape.Length))
        if target.direction is not None:
            ends = [v.Point for v in target.shape.Vertexes]
            rows.append(Row('Delta', ends[-1] - ends[0]))
    elif target.kind == 'Face':
        rows.append(Row('Area', target.shape.Area, 'mm²'))
        if target.normal is not None:
            rows.append(Row('Normal', target.normal, ''))
        rows.append(Row('Center', target.point))
        if target.normal is None:
            rows += curvature_rows(target.shape, target.point)
    line = None
    if target.kind == 'Edge' and target.direction is not None:
        ends = [v.Point for v in target.shape.Vertexes]
        line = (ends[0], ends[-1])
    elif target.kind == 'Circle':
        u = geo.Plane.from_normal(target.point, target.axis).u
        line = (target.point - u * target.radius, target.point + u * target.radius)
    label = rows[0].text() if rows and target.kind != 'Vertex' else ''
    if target.kind == 'Circle':
        label = 'Ø ' + label
    return Measurement(rows, line, label)


def curvature_rows(face, point):
    """How tightly a curved face bends at a point: its two principal radii."""
    from ..surfaces.edit import curvature
    try:
        bend = curvature(face, point)
    except (ValueError, Part.OCCError, RuntimeError):
        return []
    words = {'flat': 'Flat here', 'convex': 'Bulges outward (convex)', 'concave': 'Hollow (concave)',
             'saddle': 'Saddle: bends both ways'}
    rows = [Row('Curvature', words[bend['kind']], '')]
    for name, radius in (('Tightest radius', bend['tight']), ('Gentlest radius', bend['gentle'])):
        rows.append(Row(name, 'Flat (no bend)', '') if math.isinf(radius) else Row(name, radius))
    return rows


def _angle(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, a.dot(b)))))


def _folded(a, b):
    """Angle between two directions, ignoring their sense: 0 to 90 degrees."""
    angle = _angle(a, b)
    return min(angle, 180 - angle)


def between(first, second):
    """The measurements of two targets against each other."""
    rows, line, label, extra = [], None, '', []
    points = [t.point if t.kind in ('Vertex', 'Circle') else None for t in (first, second)]
    circles = first.kind == 'Circle' and second.kind == 'Circle'
    if all(p is not None for p in points):
        a, b = points
        delta = b - a
        rows.append(Row('Center spacing' if circles else 'Distance', delta.Length))
        rows.append(Row('Delta', delta))
        line, label = (a, b), length(delta.Length)
        if circles and _folded(first.axis, second.axis) < math.degrees(PARALLEL) * 1e3:
            axis = first.axis
            across = delta - axis * delta.dot(axis)
            rows.append(Row('Across the axes', across.Length))
            rows.append(Row('Along the axes', abs(delta.dot(axis))))
            wall = across.Length - first.radius - second.radius
            if wall > geo.EPS:  # Side by side, not rims of one hole.
                rows.append(Row('Wall between', wall))
        elif first.kind != second.kind:
            circle, point = (first, second) if first.kind == 'Circle' else (second, first)
            offset = point.point - circle.point
            rows.append(Row('Distance to the axis', (offset - circle.axis * offset.dot(circle.axis)).Length))
    elif first.normal is not None and second.normal is not None:
        angle = _folded(first.normal, second.normal)
        if angle < 1e-4:
            distance = abs((second.point - first.point).dot(first.normal))
            rows.append(Row('Distance between faces', distance))
            foot = second.point - first.normal * (second.point - first.point).dot(first.normal)
            line, label = (foot, second.point), length(distance)
        rows.append(Row('Angle', angle, '°'))
    elif first.direction is not None and second.direction is not None:
        angle = _folded(first.direction, second.direction)
        rows.append(Row('Angle', angle, '°'))
        if angle < 1e-4:
            offset = second.point - first.point
            across = offset - first.direction * offset.dot(first.direction)
            rows.append(Row('Distance between lines', across.Length))
    else:
        flat, other = (first, second) if first.normal is not None else (second, first)
        if flat.normal is not None and other.kind in ('Vertex', 'Circle'):
            height = (other.point - flat.point).dot(flat.normal)
            rows.append(Row('Distance to the face plane', abs(height)))
            line, label = (other.point - flat.normal * height, other.point), length(abs(height))
            if other.kind == 'Circle':
                rows.append(Row('Axis angle to the face', _folded(other.axis, flat.normal), '°'))
    try:
        distance, pairs, _ = first.shape.distToShape(second.shape)
    except (Part.OCCError, RuntimeError):
        distance, pairs = None, []
    if distance is not None:
        rows.append(Row('Minimum distance', distance))
        if pairs:
            closest = (V(pairs[0][0]), V(pairs[0][1]))
            if line is None:
                line, label = closest, length(distance)
            elif distance > geo.EPS:
                extra.append(closest)
    return Measurement(rows, line, label, extra)


def summary(measurement, targets):
    """Plain text for the clipboard."""
    heading = ' / '.join(target.label for target in targets)
    return heading + '\n' + '\n'.join('%s: %s' % (row.name, row.text()) for row in measurement.rows)
