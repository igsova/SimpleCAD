"""Printable round studs and matching blind sockets, before slice separation."""
from dataclasses import dataclass, replace
import math
import FreeCAD as App
import Part
from ..core import geometry as geo

V = App.Vector
MAX_STUDS = 8


@dataclass(frozen=True)
class StudJoint:
    diameter: float = 6.0
    length: float = 4.0
    clearance: float = .10
    count: int = 2
    spacing: float = 0.0  # Center distance; 0 spreads the studs evenly over the cut face.
    across: float = 0.0  # Shift along the stud row, the cut face's long direction.
    up: float = 0.0  # Shift across the row.
    wall: float = 1.2
    flip: bool = False
    grid: bool = False  # Two rows across the cut face instead of one.

    def validate(self):
        if not all(math.isfinite(value) for value in (self.diameter, self.length, self.clearance,
                       self.spacing, self.across, self.up, self.wall)):
            raise ValueError("Joint dimensions must be finite lengths.")
        if min(self.diameter, self.length, self.wall) <= geo.EPS * 10:
            raise ValueError("Stud diameter, length and minimum wall must be greater than zero.")
        if not 1 <= self.count <= MAX_STUDS or (self.grid and self.count % 2):
            raise ValueError("Choose 1 to %d studs in a row, or an even number in a two-row grid." % MAX_STUDS)
        if self.socket_radius <= geo.EPS * 10:
            raise ValueError("That negative clearance would close the socket. Use a looser fit.")
        if self.spacing < 0:
            raise ValueError("Stud spacing must be zero (automatic) or positive.")
        if self.count > 1 and 0 < self.spacing < self.pitch:
            raise ValueError("The studs are too close. Increase spacing to leave a wall between sockets.")
        return self

    @property
    def radius(self):
        return self.diameter / 2

    @property
    def socket_radius(self):
        return self.radius + self.clearance

    @property
    def lead(self):
        return min(.4, self.length * .15, self.radius * .2, self.socket_radius * .2)

    @property
    def socket_depth(self):
        # Bottom relief lets the two cut shoulders meet before the stud bottoms out.
        return self.length + max(.2, self.clearance)

    @property
    def pitch(self):
        """The closest center distance leaving a wall between two sockets."""
        return 2 * max(self.socket_radius + self.lead, self.radius) + self.wall

    @property
    def margin(self):
        """The closest a socket center may come to the edge of the cut face."""
        return self.socket_radius + self.lead + self.wall

    def positions(self, length=None, width=None):
        """(along, across) stud centers. ``length``/``width`` are the room on
        the cut face along and across the row, used for automatic spacing."""
        columns = self.count // 2 if self.grid else self.count
        rows = 2 if self.grid else 1
        along = [(i - (columns - 1) / 2) * self.gap(columns, length) for i in range(columns)]
        across = [(i - (rows - 1) / 2) * self.gap(rows, width) for i in range(rows)]
        return [(u, v) for u in along for v in across]

    def gap(self, count, room):
        if count < 2:
            return 0.0
        if self.spacing > 0 or room is None:
            return self.spacing or 10.0
        # Equal shares of the face, but never closer to its edge than the wall.
        return min(room / count, (room - 2 * self.margin) / (count - 1))


def solid(shape):
    geo.validate(shape)
    if len(shape.Solids) != 1 or len(shape.Faces) != len(shape.Solids[0].Faces) or len(shape.Edges) != len(shape.Solids[0].Edges):
        raise ValueError("Studs need two closed solid pieces. Use no joint for open surfaces or cuts making more pieces.")
    result = shape.Solids[0].copy()
    if result.Volume < 0:
        result.reverse()
    return geo.validate(result, solid=True)


def interface(first, second, origin, normal):
    def caps(shape):
        return [f for f in shape.Faces if isinstance(f.Surface, Part.Plane)
                and abs(geo.face_normal(f).dot(normal)) > 1 - 1e-8
                and abs((f.CenterOfMass - origin).dot(normal)) < 1e-5]
    a, b = caps(first), caps(second)
    if not a or not b:
        raise ValueError("The two pieces need a shared flat cut face for this joint.")
    section = Part.makeCompound(a).common(Part.makeCompound(b))
    if not section.Faces or section.Area < geo.EPS:
        raise ValueError("The two pieces do not touch at this cut plane.")
    return section


def fits(envelope, shape):
    missing = envelope.cut(shape)
    return sum(abs(s.Volume) for s in missing.Solids) <= max(1e-6, envelope.Volume * 1e-8)


def stud_and_socket(point, normal, params):
    root = params.wall / 2
    pin = Part.makeCylinder(params.radius, params.length - params.lead + root,
                            point - normal * root, normal)
    tip = Part.makeCone(params.radius, params.radius - params.lead, params.lead,
                         point + normal * (params.length - params.lead), normal)
    pin = solid(pin.fuse(tip))
    overlap = max(geo.EPS * 100, params.length * 1e-6)
    hole = Part.makeCylinder(params.socket_radius, params.socket_depth + overlap,
                             point - normal * overlap, normal)
    entry = Part.makeCone(params.socket_radius + params.lead, params.socket_radius, params.lead,
                          point, normal)
    return pin, solid(hole.fuse(entry))


def row_frame(section, normal):
    """(center, along, across): the cut face's center, its long direction and the one across it."""
    frame = geo.Plane.from_normal(section.CenterOfMass, normal)
    along = frame.u
    try:
        properties = section.Faces[0].PrincipalProperties if len(section.Faces) == 1 else section.PrincipalProperties
        axes = [geo.unit(properties[name] - normal * properties[name].dot(normal))
                for name in ("FirstAxisOfInertia", "SecondAxisOfInertia", "ThirdAxisOfInertia")
                if (properties[name] - normal * properties[name].dot(normal)).Length > .5]
        moments = [properties["Moments"][i] for i, name in enumerate(("FirstAxisOfInertia", "SecondAxisOfInertia",
                                                                       "ThirdAxisOfInertia"))
                   if (properties[name] - normal * properties[name].dot(normal)).Length > .5]
        if len(axes) == 2 and abs(moments[0] - moments[1]) > 1e-6 * max(abs(m) for m in moments):
            # The least moment of inertia lies along the face's long direction.
            along = axes[0] if moments[0] < moments[1] else axes[1]
    except (KeyError, IndexError, ValueError, Part.OCCError):
        pass
    largest = max(range(3), key=lambda i: abs(tuple(along)[i]))
    if tuple(along)[largest] < 0:
        along = -along
    return frame.origin, along, geo.unit(normal.cross(along))


def room(section, center, direction):
    """Length of the cut face along ``direction`` through ``center``, and that span's middle."""
    reach = section.BoundBox.DiagonalLength + 1
    line = Part.makeLine(center - direction * reach, center + direction * reach)
    spans = [(edge.Vertexes[0].Point, edge.Vertexes[-1].Point) for edge in line.common(section).Edges]
    if not spans:
        return 0.0, center
    def distance(span):
        a, b = ((p - center).dot(direction) for p in span)
        return 0.0 if min(a, b) <= 0 <= max(a, b) else min(abs(a), abs(b))
    start, end = min(spans, key=distance)
    a, b = sorted(((p - center).dot(direction) for p in (start, end)))
    return b - a, center + direction * ((a + b) / 2)


def add_studs(pieces, plane, offset, params):
    """Keep side/order identities. Only native copies are edited; no document writes."""
    params.validate()
    if len(pieces) != 2 or {side for side, _ in pieces} != {-1, 1}:
        raise ValueError("Studs need a cut producing exactly two solid pieces from one object.")
    original = {side: solid(shape) for side, shape in pieces}
    male_side = 1 if params.flip else -1
    female_side = -male_side
    male, female = original[male_side], original[female_side]
    normal = plane.normal * -male_side
    origin = plane.center + plane.normal * offset
    section = interface(male, female, origin, normal)
    # Position controls keep the same directions when the male/socket side flips.
    center, along, across = row_frame(section, plane.normal)
    columns = params.count // 2 if params.grid else params.count
    length, middle = room(section, center, along)
    if params.spacing <= 0 and columns > 1:
        center = middle  # An automatic row spans the face evenly.
    width, middle = room(section, center, across) if params.grid else (None, center)
    if params.spacing <= 0 and params.grid:
        center = middle
    center = center + along * params.across + across * params.up
    if params.spacing <= 0 and params.count > 1:
        for count, space, name in ((columns, length, "along"), (2 if params.grid else 1, width, "across")):
            if count > 1 and params.gap(count, space) < params.pitch:
                most = max(1, int((space - 2 * params.margin) // params.pitch) + 1) if space > 2 * params.margin else 0
                raise ValueError("Only %d stud%s of this size fit %s the cut face here. Choose fewer or smaller studs."
                                 % (most, "" if most == 1 else "s", name))
    pins, holes = [], []
    for index, (u, v) in enumerate(params.positions(length, width), 1):
        point = center + along * u + across * v
        anchor = Part.makeCylinder(params.radius + params.wall, params.wall,
                                   point - normal * params.wall, normal)
        surround = Part.makeCylinder(params.socket_radius + params.lead + params.wall,
                                     params.socket_depth + params.wall, point, normal)
        if not fits(anchor, male) or not fits(surround, female):
            raise ValueError("Stud %d does not fit with the requested wall/depth. Move the joint, "
                             "reduce its size/spacing, or flip sides." % index)
        pin, hole = stud_and_socket(point, normal, params)
        pins.append(pin); holes.append(hole)
    try:
        joined = solid(male.fuse(pins))
        socketed = solid(female.cut(holes))
    except (Part.OCCError, ValueError) as error:
        raise ValueError("This joint could not be made as two closed solids. Try a smaller stud or a different position.") from error
    result = {male_side: joined, female_side: socketed}
    return [(side, result[side]) for side, _ in pieces]


def fit_samples(params):
    """Three one-stud pairs, both printing faces up, with clearance labels."""
    from . import slicing
    params.validate()
    clearances = [params.clearance - .1, params.clearance, params.clearance + .1]
    if params.radius + min(clearances) <= geo.EPS * 10:
        raise ValueError("The fit-test clearances would close a socket. Choose a looser clearance.")
    size = 2 * (params.radius + max(0, max(clearances)) + params.lead + params.wall) + 2
    height = params.length + max(.2, max(clearances)) + params.wall + 1
    base = Part.makeBox(size, size, 2 * height)
    plane = slicing.cut_plane([base], "Z")
    pieces = slicing.split(base, plane, 0)
    results = []
    for index, clearance in enumerate(clearances):
        trial = replace(params, clearance=clearance, count=1, across=0, up=0, flip=False, grid=False)
        pair = add_studs(pieces, plane, 0, trial)
        for side, part in pair:
            shape = part.copy()
            if side == 1:
                # Socket opens down after the cut; turn it over for printing.
                shape.rotate(V(size / 2, size / 2, height), V(1, 0, 0), 180)
            box = shape.BoundBox
            shape.translate(V(index * (size + 5) - box.XMin,
                              (size + 5 if side == 1 else 0) - box.YMin, -box.ZMin))
            results.append(("%+.6g mm — %s" % (clearance, "stud" if side == -1 else "socket"),
                            geo.validate(shape, solid=True), clearance))
    return results
