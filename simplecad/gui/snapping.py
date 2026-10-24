"""Screen-space inference, with exact coplanarity for drawing."""
from contextlib import contextmanager
from dataclasses import dataclass
import math

import FreeCAD  # noqa: F401  Load the application before its native modules.
import numpy as np
import Part
from pivy import coin
from ..core.geometry import EPS, V, Plane, point_on_face
from ..core import preferences, geometry
from ..document import guides, visibility

# Guide look-ahead and angular guard supplement the configurable capture radii.
MIDPOINT_HINT_RADIUS = 60
ENDPOINT_HINT_RADIUS = 40
# Within this many pixels a vertex beats nearby centers and midpoints,
# unless one of those is more than the margin nearer the pointer.
VERTEX_PRIORITY_RADIUS = 12
VERTEX_PRIORITY_MARGIN = 6
AXIS_ANGLE = math.sin(math.radians(8))
AXES = (("X", V(1, 0, 0)), ("Y", V(0, 1, 0)), ("Z", V(0, 0, 1)))


def ray(view, pos):
    width, height = view.getSize()
    camera = view.getCameraNode()
    volume = camera.getViewVolume(float(width) / max(height, 1))
    near, far = volume.projectPointToLine(coin.SbVec2f(pos[0] / max(width, 1), pos[1] / max(height, 1)))
    origin, end = V(*near.getValue()), V(*far.getValue())
    if not camera.isOfType(coin.SoPerspectiveCamera.getClassTypeId()):
        # Empty/hidden geometry can collapse the clip range. Its near/far
        # difference is then zero or too short for a reliable plane hit.
        return origin, view.getViewDirection()
    return origin, end - origin


def screen(view, point):
    return tuple(view.getPointOnScreen(point))[:2]


def sight(view, point):
    """Unit direction from the eye through a point, into the scene."""
    if hasattr(view, "getCameraNode"):
        direction = V(ray(view, screen(view, point))[1])
    else:
        direction = V(view.getViewDirection())
    return direction / direction.Length


def camera_state(view):
    """What screen projection depends on: camera type, pose, zoom and viewport.

    Screen positions cached under an equal state are still exact.
    """
    camera = view.getCameraNode() if hasattr(view, "getCameraNode") else None
    if camera is None:
        return None
    values = [str(camera.getTypeId().getName())]
    for name in ("position", "orientation", "focalDistance", "height", "heightAngle", "aspectRatio"):
        field = camera.getField(name)
        if field is not None:
            value = field.getValue()
            values.append(tuple(value.getValue()) if hasattr(value, "getValue") else value)
    return tuple(values), tuple(view.getSize()) if hasattr(view, "getSize") else None


def screen_distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


_shared_hits = None
# (view and camera state, {point: screen position}) of the latest snap grid.
_projections = None


@contextmanager
def shared_picks():
    """Ask the view for the objects under each pointer position only once.

    One mouse move picks the same pixel for the snap, the center hint and the
    midpoint hint; each native ray pick of a large part takes milliseconds.
    Use this only while the document and camera stay unchanged.
    """
    global _shared_hits
    outer, _shared_hits = _shared_hits, {}
    try:
        yield
    finally:
        _shared_hits = outer


def objects_info(view, pos):
    key = (id(view), int(pos[0]), int(pos[1]))
    if _shared_hits is not None and key in _shared_hits:
        return _shared_hits[key]
    hits = view.getObjectsInfo((int(pos[0]), int(pos[1]))) or []
    if _shared_hits is not None:
        _shared_hits[key] = hits
    return hits


def pick(view, doc, pos, face_only=False, prefer_boundary=False):
    hits = objects_info(view, pos)
    if not prefer_boundary:
        # Dense imports can return hundreds of hits along a ray. Resolve only
        # the chosen subshape, keeping support-profile priority and native hit
        # order. Materializing every occluded FaceN on each move is expensive.
        owners, candidates = {}, []
        for hit in hits:
            name = hit.get('Component', '')
            if hit.get('Document') != doc.Name or '.' in name or (face_only and not name.startswith('Face')):
                continue
            owner = hit.get('Object', '')
            if owner not in owners:
                obj = doc.getObject(owner)
                owners[owner] = ((obj, obj.Shape, 0 if 'SC_Support' in obj.PropertiesList else 1)
                                 if obj and hasattr(obj, 'Shape') else None)
            data = owners[owner]
            if data is not None:
                candidates.append((data, name, hit))
        candidates.sort(key=lambda candidate: candidate[0][2])
        for (obj, source, _), name, hit in candidates:
            if not visibility.element_visible(obj, name):
                continue
            try:
                point = V(hit['x'], hit['y'], hit['z'])
                shape = source.getElement(name) if name else source
                return obj, shape, point, name
            except (KeyError, IndexError, RuntimeError, ValueError):
                continue
        return None
    found = []
    for hit in hits:
        if hit.get("Document") != doc.Name:
            continue
        obj = doc.getObject(hit.get("Object", ""))
        name = hit.get("Component", "")
        if not obj or not hasattr(obj, "Shape") or "." in name:
            continue
        if not visibility.element_visible(obj, name):
            continue
        if face_only and not name.startswith("Face"):
            continue
        try:
            shape = obj.Shape.getElement(name) if name else obj.Shape
            point = V(hit["x"], hit["y"], hit["z"])
        except (KeyError, IndexError, RuntimeError, ValueError):
            continue
        found.append((obj, shape, point, name))
    # A drawing on a face shares its depth; make the small profile pickable.
    found.sort(key=lambda item: 0 if "SC_Support" in item[0].PropertiesList else 1)
    if prefer_boundary and found:
        direction = view.getViewDirection()
        front = min(item[2].dot(direction) for item in found)
        near = [item for item in found if abs(item[2].dot(direction)-front) < 1e-6]
        return min(near, key=lambda item: {'Vertex': 0, 'Edge': 1, 'Face': 2}.get(item[1].ShapeType, 3))
    return found[0] if found else None


def on_face(face, point):
    """A picked point moved onto the surface of the face it was picked on.

    The view reports picks in single precision: on a face 300 mm from the
    origin that is about 2e-6 mm off the surface, enough to leave a hairline
    step where a moved part should sit flush.
    """
    try:
        if isinstance(face.Surface, Part.Plane):
            return Plane.from_face(face).project(point)
        u, v = face.Surface.parameter(point)
        return face.valueAt(u, v)
    except (AttributeError, Part.OCCError, RuntimeError, ValueError):
        return point


@dataclass
class Snap:
    point: object
    label: str
    axis: str = ""
    direction: object = None  # of the straight edge or guide line the point is on


def straight(edge):
    """Unit direction of a straight edge, or None for a curve."""
    if not isinstance(getattr(edge, "Curve", None), Part.Line) or edge.Length <= EPS:
        return None
    first, last = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    return geometry.unit(last - first) if (last - first).Length > EPS else None


def closest_on_lines(p, d, q, e):
    """Where two endless lines through p and q along unit d and e meet, or None."""
    normal = d.cross(e)
    if normal.Length < 1e-9:
        return None  # Parallel.
    w = p - q
    b = d.dot(e)
    s = (b * e.dot(w) - d.dot(w)) / (1 - b * b)
    t = (e.dot(w) - b * d.dot(w)) / (1 - b * b)
    first, second = p + d * s, q + e * t
    scale = max(1.0, abs(first.x), abs(first.y), abs(first.z))
    return (first + second) * .5 if (first - second).Length <= 1e-6 * scale else None


def on_span(p, d, span, point):
    """Whether a point on the guide through p along d lies within its span; None is endless."""
    return span is None or span[0] - EPS <= (point - p).dot(d) <= span[1] + EPS


def axis_point(view, pos, anchor, direction):
    """Closest point on an anchor axis to the cursor ray, also in perspective.

    Near view-parallel axes cannot give a stable mouse distance. Their explicit
    locks can still be used with a typed length, but automatic inference skips
    them. Perspective targets behind the camera are rejected, but an
    orthographic view can extend beyond its current (auto-adjusted) clip range.
    """
    origin, ray_direction = ray(view, pos)
    camera = view.getCameraNode()
    perspective = camera.isOfType(coin.SoPerspectiveCamera.getClassTypeId())
    if not perspective:
        # The near/far points can be almost coincident in an empty view.
        # Use the camera direction to avoid amplifying their float roundoff.
        ray_direction = view.getViewDirection()
    ray_direction = ray_direction / ray_direction.Length
    alignment = direction.dot(ray_direction)
    denominator = 1 - alignment * alignment
    if denominator < 1e-4:
        return None
    offset = origin - anchor
    distance = (direction.dot(offset) - alignment * ray_direction.dot(offset)) / denominator
    point = anchor + direction * distance
    if not math.isfinite(distance):
        return None
    if perspective:
        eye = V(*camera.position.getValue())
        if (point - eye).dot(ray_direction) <= 0:
            return None
    return point


def pull_drag(view, pos, anchor, normal, down_pos, step):
    """Signed cap distance and a face-on fallback scale for surface snapping."""
    a, b = screen(view, anchor), screen(view, anchor + normal * step)
    dx, dy = b[0] - a[0], b[1] - a[1]
    size = dx * dx + dy * dy
    if size > 4:
        point = axis_point(view, pos, anchor, normal)
        if point is not None:
            return (point - anchor).dot(normal), None
        return (((pos[0] - down_pos[0]) * dx + (pos[1] - down_pos[1]) * dy) * step / size, None)
    p, _ = ray(view, pos)
    q, _ = ray(view, (pos[0] + 100, pos[1]))
    scale = (q - p).Length / 100
    return (pos[1] - down_pos[1]) * scale, scale


def snap_pull(view, distance, stop, anchor, normal, fallback_scale, radius):
    """Capture an exact face, but release it when the pointer goes farther."""
    if fallback_scale is None:
        pixels = screen_distance(screen(view, anchor + normal * distance),
                                 screen(view, anchor + normal * stop))
    else:
        pixels = abs(distance - stop) / max(fallback_scale, EPS)
    return stop if pixels <= radius else distance


def circle_center(edges):
    """Center of a round edge or arc, or of a faceted loop that fits a circle."""
    if len(edges) == 1 and isinstance(getattr(edges[0], "Curve", None), (Part.Circle, Part.ArcOfCircle)):
        return V(edges[0].Curve.Center)
    if len(edges) < 8 or not all(isinstance(getattr(e, "Curve", None), Part.Line) for e in edges):
        return None
    from ..mesh.curved import fit_circle_loop
    fit = fit_circle_loop([v.Point for e in edges for v in e.Vertexes], preferences.precision())
    return fit['center'] if fit else None


def circle_centers(shape, faces, hidden=()):
    """Centers of every round edge and of faceted round loops on flat faces."""
    centers = []

    def add(center):
        if center is not None and not any((center - known).Length < EPS for known in centers):
            centers.append(center)
    for edge in shape.Edges:
        if isinstance(getattr(edge, "Curve", None), (Part.Circle, Part.ArcOfCircle)):
            add(V(edge.Curve.Center))
    for i, face in enumerate(faces, 1):
        if i in hidden or not isinstance(face.Surface, Part.Plane):
            continue
        for wire in face.Wires:
            # Holes of converted parts are polygons of many short sides.
            if len(wire.Edges) >= 8:
                add(circle_center(wire.Edges))
    return centers


class PointGrid:
    """Points bucketed by position, for exact near-duplicate tests without a full scan."""
    def __init__(self, cell=1e-3):
        self.cell, self.cells = cell, {}

    def key(self, point):
        return (math.floor(point.x / self.cell), math.floor(point.y / self.cell), math.floor(point.z / self.cell))

    def add(self, point):
        self.cells.setdefault(self.key(point), []).append(point)

    def discard(self, point):
        bucket = self.cells.get(self.key(point), [])
        for i, known in enumerate(bucket):
            if (known - point).Length == 0:
                del bucket[i]
                return

    def copy(self):
        result = PointGrid(self.cell)
        result.cells = {key: list(points) for key, points in self.cells.items()}
        return result

    def near(self, point, distance):
        x, y, z = self.key(point)
        return any((point - known).Length < distance
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                   for known in self.cells.get((x + dx, y + dy, z + dz), ()))


_objects = {}


def prune(doc_name, present):
    """Release cached snaps of objects no longer in the document."""
    for key in [key for key in _objects if key[0] == doc_name and key[1] not in present]:
        del _objects[key]


def forget_document(name):
    prune(name, ())


def snap_options(settings):
    """The settings that decide what a snap collection contains."""
    return settings.endpoints, settings.centers, settings.midpoints, settings.edges


def snap_targets(doc, exclude=()):
    """Visible plain Part objects outside containers, which drawing snaps to."""
    excluded = {obj.Name for obj in exclude}
    for obj in doc.Objects:
        if obj.Name in excluded or not hasattr(obj, "Shape") or not obj.ViewObject.Visibility:
            continue
        if obj.TypeId != "Part::Feature":
            continue
        if any(parent.hasExtension("App::GeoFeatureGroupExtension") for parent in obj.InList):
            continue
        yield obj


def object_snaps(obj, options, finish=True):
    """An object's snap geometry, collected again only after it changes.

    With finish=False an unfinished collection is returned for warm-up to
    advance; a later call finishes whatever is left of it.
    """
    key = (getattr(getattr(obj, "Document", None), "Name", None), obj.Name)
    shape = obj.Shape
    hidden = frozenset(visibility.hidden_faces(obj))
    cached = _objects.get(key)
    if not (cached is not None and cached.obj == obj and cached.hidden == hidden
            and cached.options == options and cached.shape.isSame(shape)):
        change = geometry.change_to(shape)
        if (change is not None and cached is not None and cached.done and cached.obj == obj
                and cached.options == options and not hidden and not cached.hidden
                and shape.ShapeType in ("Solid", "Shell") and cached.shape.isSame(change.source)):
            cached = _objects[key] = ObjectSnaps.derived(cached, shape, change)
        else:
            reuse = cached if cached is not None and cached.options == options else None
            cached = _objects[key] = ObjectSnaps(key, obj, shape, hidden, options, reuse)
    if finish:
        cached.finish()
    return cached


def warm(doc, options):
    """Collect the document's snaps a little at a time, yielding between slices.

    Opening a drawing tool on a converted part of thousands of faces then
    finds its snaps ready. A collection replaced by a newer one is dropped.
    """
    for obj in list(snap_targets(doc)):
        try:
            snaps = object_snaps(obj, options, finish=False)
        except (ReferenceError, RuntimeError):
            continue
        while not snaps.done and _objects.get(snaps.key) is snaps:
            snaps.step()
            yield


class ObjectSnaps:
    """One object's snap points, drawing faces and edge segments.

    Collecting them visits every face and edge, which takes seconds on a
    converted part of thousands of triangles. Faces and edges that survive
    an edit keep their native identity, so their data is reused from the
    previous collection and only new pieces are sampled. Collection runs in
    slices so warm-up can spread it over idle time.
    """
    SLICE = 256

    def __init__(self, key, obj, shape, hidden, options, previous=None):
        self.key, self.obj, self.shape, self.hidden, self.options = key, obj, shape, hidden, options
        self.face_data, self.edge_data = {}, {}
        self.done = False
        self._work = self.collect(previous)

    def step(self):
        """Advance the collection by one slice."""
        try:
            next(self._work)
        except StopIteration:
            self.done = True

    def finish(self):
        while not self.done:
            self.step()

    def collect(self, previous):
        centers, segments = self.options[1], self.options[3]
        shape, hidden = self.shape, self.hidden
        # An unfinished previous collection still lends what it measured.
        old_faces = previous.face_data if previous is not None else {}
        old_edges = previous.edge_data if previous is not None else {}
        hidden_edges, hidden_vertices = visibility.hidden_elements(shape, hidden)
        faces = shape.Faces
        yield
        self.start()
        bounds, planar = [], []
        for i, face in enumerate(faces, 1):
            if i % self.SLICE == 0:
                yield
            data = self.remember(self.face_data, old_faces, face, lambda: self.face(face, centers))
            bounds.append(data[4])
            planar.append(data[0])
            self.add_face(face, data, visible=i not in hidden)
        edges = shape.Edges
        yield
        for i, edge in enumerate(edges, 1):
            if i % self.SLICE == 0:
                yield
            data = self.remember(self.edge_data, old_edges, edge, lambda: self.edge(edge, segments))
            self.add_edge(edge, data, visible=i not in hidden_edges)
        if hidden_vertices or shape.ShapeType not in ("Solid", "Shell", "Face", "Wire", "Edge"):
            # Loose points of a compound belong to no edge.
            self.corners = {id(v): v.Point for i, v in enumerate(shape.Vertexes, 1) if i not in hidden_vertices}
        self.finish_lists()
        if geometry.face_index(shape, build=False) is None:
            # Line splits find their faces through the same bounds.
            geometry.remember_face_index(geometry.FaceIndex(shape, faces, bounds, planar))

    @classmethod
    def derived(cls, previous, shape, change):
        """The previous collection patched with a recorded local edit.

        Only the removed and added faces, and the edges they lose or gain,
        are read: listing a dense part's faces and edges again would cost
        most of a second after every line.
        """
        self = cls.__new__(cls)
        self.key, self.obj, self.shape, self.hidden, self.options = (
            previous.key, previous.obj, shape, frozenset(), previous.options)
        centers, segments = self.options[1], self.options[3]
        # The previous collection is being replaced: take over its memo
        # rather than copy tens of thousands of entries.
        self.face_data, self.edge_data = previous.face_data, previous.edge_data
        previous.face_data, previous.edge_data = {}, {}

        def keyed(items):
            result = {}
            for item in items:
                result.setdefault(hash(item), []).append(item)
            return result

        def within(keys, item):
            return any(item.isSame(known) for known in keys.get(hash(item), ()))

        def drop(memo, item):
            bucket = memo.get(hash(item), [])
            found = [data for known, data in bucket if known.isSame(item)]
            bucket[:] = [entry for entry in bucket if not entry[0].isSame(item)]
            if not bucket:
                memo.pop(hash(item), None)
            return found
        grid = getattr(previous, "_center_grid", None)
        grid = grid.copy() if grid is not None else None
        for face in change.removed:
            for data in drop(self.face_data, face):
                if grid is not None and data[1] is not None:
                    grid.discard(data[1])
        for face in change.added:
            data = self.face(face, centers)
            self.face_data.setdefault(hash(face), []).append((face, data))
            if grid is not None and data[1] is not None:
                grid.add(data[1])
        self._center_grid = grid
        old_edges = geometry.native_unique([e for f in change.removed for e in f.Edges])
        new_edges = geometry.native_unique([e for f in change.added for e in f.Edges])
        old_keys, new_keys = keyed(old_edges), keyed(new_edges)
        for edge in old_edges:
            if not within(new_keys, edge):
                drop(self.edge_data, edge)
        for edge in new_edges:
            if not within(old_keys, edge):
                self.edge_data.setdefault(hash(edge), []).append((edge, self.edge(edge, segments)))
        self.start()
        for items in self.face_data.values():
            for face, data in items:
                self.add_face(face, data)
        for items in self.edge_data.values():
            for edge, data in items:
                self.add_edge(edge, data)
        self.finish_lists()
        self.done, self._work = True, iter(())
        return self

    def start(self):
        self.faces, self.face_bounds, self.face_centers, self.rings, self.seams = [], [], [], [], {}
        self.segment_starts, self.segment_ends, self.segment_edges = [], [], []
        self.midpoints, self.edge_to_midpoint = [], {}
        self.circles, self.corners = [], {}

    def add_face(self, face, data, visible=True):
        planar, center, loops, seam_edges, bounds = data
        for edge in seam_edges:
            self.seams.setdefault(hash(edge), []).append(edge)
        if not visible or not planar:
            return
        self.faces.append(face)
        self.face_bounds.append(bounds)
        if self.options[1]:
            self.face_centers.append(center)
            self.rings.extend(loops)

    def add_edge(self, edge, data, visible=True):
        """Faces come first: their seam edges are left out here."""
        parts, midpoint, ends, center = data
        if center is not None:
            self.circles.append(center)
        for point in ends:
            self.corners.setdefault((point.x, point.y, point.z), point)
        if not visible or any(edge.isSame(seam) for seam in self.seams.get(hash(edge), ())):
            return
        if self.options[3]:
            for start, end in parts:
                self.segment_starts.append(start)
                self.segment_ends.append(end)
                self.segment_edges.append(edge)
        if self.options[2] and midpoint is not None:
            self.midpoints.append((edge, midpoint))
            self.edge_to_midpoint.setdefault(hash(edge), []).append((edge, midpoint))

    def finish_lists(self):
        self.endpoints = list(self.corners.values()) if self.options[0] else []
        self.circle_centers = []
        if self.options[1]:
            known = PointGrid()
            for center in self.circles + self.rings:
                if not known.near(center, EPS):
                    known.add(center)
                    self.circle_centers.append(center)
        del self.corners, self.circles, self.rings, self.seams

    def center_grid(self):
        if getattr(self, "_center_grid", None) is None:
            self._center_grid = PointGrid()
            for point in self.face_centers:
                self._center_grid.add(point)
        return self._center_grid

    @staticmethod
    def remember(memo, previous, element, compute):
        """The element's data from the previous collection, or computed now."""
        key = hash(element)
        for known, data in previous.get(key, ()):
            if known.isSame(element):
                break
        else:
            data = compute()
        memo.setdefault(key, []).append((element, data))
        return data

    @staticmethod
    def face(face, centers):
        """(flat, center, centers of faceted round loops, seam edges, bounds) of one face."""
        planar = isinstance(face.Surface, Part.Plane)
        box = face.BoundBox
        bounds = (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)
        if not planar:
            return False, None, [], [edge for edge in face.Edges if edge.isSeam(face)], bounds
        if not centers:
            return True, None, [], [], bounds
        loops = []
        # Holes of converted parts are polygons of many short sides.
        if face.countElement("Edge") >= 8:
            for wire in face.Wires:
                if len(wire.Edges) >= 8:
                    center = circle_center(wire.Edges)
                    if center is not None:
                        loops.append(center)
        return True, face.CenterOfMass, loops, [], bounds

    @staticmethod
    def edge(edge, segments):
        """(screen-testable segments, midpoint, end vertices, circle center) of one edge."""
        try:
            curve = edge.Curve
        except (RuntimeError, ValueError, TypeError, Part.OCCError):
            curve = None  # A degenerated edge has no 3D curve.
        center = V(curve.Center) if isinstance(curve, (Part.Circle, Part.ArcOfCircle)) else None
        if isinstance(curve, Part.Line):
            # Most edges of a converted part: skip integrating a length and
            # listing vertices, both costly across thousands of edges.
            first, last = edge.firstVertex().Point, edge.lastVertex().Point
            start, end = edge.ParameterRange
            parts = [(tuple(first), tuple(last))] if segments and (last - first).Length > EPS else []
            return parts, edge.valueAt((start + end) / 2), (first, last), center
        ends = tuple(v.Point for v in edge.Vertexes)
        parts = []
        if segments and not edge.Degenerated and edge.Length > EPS:
            try:
                points = edge.discretize(Angular=math.radians(5), Curvature=.1, Minimum=2)
            except (RuntimeError, ValueError, TypeError, Part.OCCError):
                points = []
            parts = [(tuple(p), tuple(q)) for p, q in zip(points, points[1:]) if (q - p).Length > EPS]
        try:
            midpoint = edge.valueAt(edge.getParameterByLength(edge.Length / 2))
        except (RuntimeError, ValueError):
            midpoint = None
        return parts, midpoint, ends, center


class Snapper:
    # (point, unit direction, span) of each shown guide line. A span is the
    # (first, last) distance along a guide point's tail; None is endless.
    guide_lines = ()

    def __init__(self, doc, view, exclude=(), settings=None, collect=True):
        self.settings = settings or preferences.load()
        self.view = view
        self.doc = doc
        self.points = []
        self.faces = []
        self.face_bounds = []
        self.edges = []
        self.edge_to_midpoint = {}
        # Every visible edge as straight screen-testable segments, with the
        # source edge for exact refinement of curved ones.
        self.segment_starts, self.segment_ends, self.segment_edges = [], [], []
        self._screen_cache_key = None
        self._screen_grid = None
        self._screen_cell_size = 64
        self.guide_lines = []
        # Push/Pull uses its own height-reference index, not drawing anchors.
        if not collect:
            return
        options = snap_options(self.settings)
        collected = []
        for obj in snap_targets(doc, exclude):
            snaps = object_snaps(obj, options)
            collected.append(snaps)
            if self.settings.endpoints:
                self.points.extend((point, "Endpoint") for point in snaps.endpoints)
            self.faces.extend(snaps.faces)
            self.face_bounds.extend(snaps.face_bounds)
            if self.settings.centers:
                self.points.extend((point, "Face center") for point in snaps.face_centers)
                # A disk's or ring's own face center already marks its circle's center.
                self.points.extend((center, "Circle center") for center in snaps.circle_centers
                                   if not any(item.center_grid().near(center, EPS) for item in collected))
            self.segment_starts.extend(snaps.segment_starts)
            self.segment_ends.extend(snaps.segment_ends)
            self.segment_edges.extend(snaps.segment_edges)
            if self.settings.midpoints:
                self.points.extend((midpoint, "Midpoint") for _, midpoint in snaps.midpoints)
                self.edges.extend(snaps.midpoints)
                for key, items in snaps.edge_to_midpoint.items():
                    self.edge_to_midpoint.setdefault(key, []).extend(items)
        prune(getattr(doc, "Name", None), {obj.Name for obj in doc.Objects})
        self._collected = self.faces

        self.index_segments()
        for point, direction, start in guides.visible(doc):
            if direction is not None:
                self.guide_lines.append((point, direction, None))
                continue
            self.points.append((point, "Guide point"))
            if start is not None:
                self.guide_lines.append((start, geometry.unit(point - start), (0.0, (point - start).Length)))
        self.points.extend((point, "Intersection") for point in self.crossings())

    def index_segments(self, edges=()):
        """Freeze collected (plus any given) edges into arrays for fast tests."""
        starts, ends = list(map(tuple, self.segment_starts)), list(map(tuple, self.segment_ends))
        self.segment_starts, self.segment_ends = starts, ends
        for edge in edges:
            self.add_segments(edge)
        self.segment_starts = np.asarray(self.segment_starts, dtype=float).reshape(-1, 3)
        self.segment_ends = np.asarray(self.segment_ends, dtype=float).reshape(-1, 3)

    def add_segments(self, edge):
        if edge.Degenerated or edge.Length <= EPS:
            return
        try:
            points = ([edge.Vertexes[0].Point, edge.Vertexes[-1].Point]
                      if isinstance(edge.Curve, Part.Line) and len(edge.Vertexes) == 2
                      else edge.discretize(Angular=math.radians(5), Curvature=.1, Minimum=2))
        except (RuntimeError, ValueError, TypeError, Part.OCCError):
            return
        for first, second in zip(points, points[1:]):
            if (second - first).Length > EPS:
                self.segment_starts.append(tuple(first))
                self.segment_ends.append(tuple(second))
                self.segment_edges.append(edge)

    def _refine(self, index, point):
        """Exact point on the source edge; a segment only samples a curve."""
        edge = self.segment_edges[index]
        if isinstance(edge.Curve, Part.Line):
            return point
        distance, pairs, _ = edge.distToShape(Part.Vertex(point))
        return V(pairs[0][0]) if pairs else point

    def _covered(self, point, hit):
        """Whether the face under the pointer hides a snap point behind it.

        A corner on the far side of a part can project right beside the
        pointer; clicking there means the face in front, not that corner.
        """
        if not hit:
            return False
        face = hit[1]
        direction = sight(self.view, point)
        center, normal = self._face_data(face)
        if normal is not None:
            facing = direction.dot(normal)
            if abs(facing) < 1e-9:
                return False  # Seen edge-on.
            # Back along the line of sight to the face's plane.
            distance = (point - center).dot(normal) / facing
            if distance <= 1e-4:
                return False
            crossing = Part.Vertex(point - direction * distance)
            region = crossing.BoundBox
            region.enlarge(1e-6)
            if not (face.BoundBox.intersect(region) and face.distToShape(crossing)[0] <= 1e-6):
                return False
            # A line of sight that only grazes the face's outline passes it:
            # the point beyond sits on the silhouette, in view.
            return Part.Compound(face.Wires).distToShape(crossing)[0] > 1e-6
        # A curved face can also hide its own far side: test the line of
        # sight, stopping short of the point so a point on the near side of
        # the face is not covered by the face itself.
        reach = face.BoundBox.DiagonalLength + (point - face.BoundBox.Center).Length
        clear = max(1e-3, reach * 1e-6)
        if reach <= clear:
            return False
        line = Part.LineSegment(point - direction * reach, point - direction * clear).toShape()
        return face.distToShape(line)[0] <= 1e-6

    def _visible(self, point, hit, origin, direction):
        """Reject edge points hidden behind the face under the pointer."""
        if not hit:
            return True
        depth = (point - origin).dot(direction)
        front = (hit[2] - origin).dot(direction)
        return depth <= front + max(1e-3, abs(front) * 1e-6) or point_on_face(hit[1], point, 1e-4)

    def on_edge(self, pos, plane=None, hit=None):
        """The exact edge point nearest the pointer, within the edge radius."""
        found = self.edge_at(pos, plane, hit)
        return None if found is None else found[0]

    def edge_at(self, pos, plane=None, hit=None):
        """(point, edge) of the exact edge point nearest the pointer, within the edge radius."""
        if not self.settings.edges or not len(getattr(self, 'segment_starts', ())):
            return None
        origin, direction = ray(self.view, pos)
        direction = direction / direction.Length
        o, d = np.asarray(tuple(origin)), np.asarray(tuple(direction))
        a, b = self.segment_starts, self.segment_ends
        u = b - a
        w = a - o
        # Closest points between the pointer ray and every segment.
        uu = np.einsum('ij,ij->i', u, u)
        ud = u @ d
        uw = np.einsum('ij,ij->i', u, w)
        dw = w @ d
        denominator = uu - ud * ud
        with np.errstate(divide='ignore', invalid='ignore'):
            t = np.where(denominator > 1e-12, (ud * dw - uw) / denominator, 0.0)
        t = np.clip(t, 0.0, 1.0)
        points = a + u * t[:, None]
        along = (points - o) @ d
        gap = np.linalg.norm(points - (o + np.outer(along, d)), axis=1)
        best = None
        # Only the twelve nearest are refined: select them, then order just
        # those, rather than sorting every segment of a dense model per move.
        nearest = np.argpartition(gap, 11)[:12] if len(gap) > 12 else np.arange(len(gap))
        for index in nearest[np.argsort(gap[nearest])]:
            point = self._refine(int(index), V(*points[index]))
            if plane is not None and abs((point - plane.origin).dot(plane.normal)) > 1e-5:
                continue
            distance = screen_distance(screen(self.view, point), pos)
            if distance > self.settings.edge_radius or not self._visible(point, hit, origin, direction):
                continue
            if best is None or distance < best[0] - 1e-9:
                best = (distance, point, self.segment_edges[int(index)])
        return None if best is None else best[1:]

    def line_crossings(self, anchor, axis, away=False):
        """Exact points where the endless line through anchor along axis crosses an edge.

        With away, a crossing at the anchor itself is left out.
        """
        if not len(getattr(self, 'segment_starts', ())):
            return []
        o, d = np.asarray(tuple(anchor)), np.asarray(tuple(axis / axis.Length))
        a, b = self.segment_starts, self.segment_ends
        u = b - a
        w = a - o
        uu = np.einsum('ij,ij->i', u, u)
        ud = u @ d
        uw = np.einsum('ij,ij->i', u, w)
        dw = w @ d
        denominator = uu - ud * ud
        crossing = denominator > 1e-12 * np.maximum(uu, 1e-300)
        with np.errstate(divide='ignore', invalid='ignore'):
            t = np.where(crossing, (ud * dw - uw) / denominator, -1.0)
        inside = crossing & (t >= -1e-9) & (t <= 1 + 1e-9)
        points = a + u * np.clip(t, 0.0, 1.0)[:, None]
        along = (points - o) @ d
        gap = np.linalg.norm(points - (o + np.outer(along, d)), axis=1)
        scale = max(1.0, float(np.max(np.abs(o))))
        inside &= gap <= 1e-6 * scale
        if away:
            inside &= np.abs(along) > EPS
        found = []
        for index in np.flatnonzero(inside):
            point = V(*(o + d * along[index]))
            edge = self.segment_edges[int(index)]
            if not isinstance(edge.Curve, Part.Line):
                # Intersect the line with the true curve near the sample.
                probe = Part.makeLine(point - axis * 1.0, point + axis * 1.0)
                distance, pairs, _ = edge.distToShape(probe)
                if not pairs or distance > 1e-6 * scale:
                    continue
                point = V(pairs[0][0])
            found.append(point)
        return found

    def crossings(self):
        """Where guide lines and tails cross edges and each other."""
        found = [point for anchor, direction, span in self.guide_lines
                 for point in self.line_crossings(anchor, direction) if on_span(anchor, direction, span, point)]
        for i, (p, d, s) in enumerate(self.guide_lines):
            for q, e, t in self.guide_lines[i + 1:]:
                point = closest_on_lines(p, d, q, e)
                if point is not None and on_span(p, d, s, point) and on_span(q, e, t, point):
                    found.append(point)
        return found

    def axis_on_edge(self, pos, anchor, axis, plane=None, hit=None):
        """Where the line from the anchor along an axis crosses a nearby edge."""
        if not self.settings.edges:
            return None
        origin, direction = ray(self.view, pos)
        direction = direction / direction.Length
        best = None
        for point in self.line_crossings(anchor, axis, away=True):
            if plane is not None and abs((point - plane.origin).dot(plane.normal)) > 1e-5:
                continue
            distance = screen_distance(screen(self.view, point), pos)
            if distance > self.settings.edge_radius or not self._visible(point, hit, origin, direction):
                continue
            if best is None or distance < best[0]:
                best = (distance, point)
        return None if best is None else best[1]

    def axis_on_guide(self, pos, anchor, axis, plane=None, hit=None):
        """Where the line from the anchor along an axis crosses a nearby guide line."""
        origin, direction = ray(self.view, pos)
        direction = direction / direction.Length
        best = None
        for p, d, span in self.guide_lines:
            point = closest_on_lines(anchor, geometry.unit(axis), p, d)
            if point is None or (point - anchor).Length <= EPS or not on_span(p, d, span, point):
                continue
            if plane is not None and abs((point - plane.origin).dot(plane.normal)) > 1e-5:
                continue
            distance = screen_distance(screen(self.view, point), pos)
            if distance > self.settings.edge_radius or not self._visible(point, hit, origin, direction):
                continue
            if best is None or distance < best[0]:
                best = (distance, point)
        return None if best is None else best[1]

    def on_guide(self, pos, plane=None, hit=None):
        """(point, direction) on the guide line or tail nearest the pointer, within the edge radius."""
        if not self.guide_lines:
            return None
        origin, direction = ray(self.view, pos)
        direction = direction / direction.Length
        best = None
        for p, d, span in self.guide_lines:
            facing = d.dot(direction)
            if 1 - facing * facing < 1e-12:
                continue  # Seen end-on.
            w = origin - p
            along = (d.dot(w) - facing * direction.dot(w)) / (1 - facing * facing)
            point = p + d * (along if span is None else min(max(along, span[0]), span[1]))
            if plane is not None and abs((point - plane.origin).dot(plane.normal)) > 1e-5:
                continue
            distance = screen_distance(screen(self.view, point), pos)
            if distance > self.settings.edge_radius or not self._visible(point, hit, origin, direction):
                continue
            if best is None or distance < best[0]:
                best = (distance, point, d)
        return None if best is None else best[1:]

    def _face_data(self, face):
        """(center, normal or None) of a face, measured once per snapshot.

        A face with many holes takes milliseconds to integrate; the hovered
        face is asked for its plane and center on every pointer move.
        """
        cache = self.__dict__.setdefault("_face_data_cache", {})
        bucket = cache.setdefault(hash(face), [])
        for known, orientation, data in bucket:
            if known.isSame(face) and orientation == face.Orientation:
                return data
        try:
            normal = geometry.face_normal(face)
        except ValueError:
            normal = None
        data = (face.CenterOfMass, normal)
        bucket.append((face, face.Orientation, data))
        return data

    def face_center(self, face):
        return V(self._face_data(face)[0])

    def face_plane(self, face):
        """Plane.from_face, without integrating the same face again."""
        center, normal = self._face_data(face)
        if normal is None:
            return Plane.from_face(face)  # Raises the usual message for a curved face.
        return Plane.from_normal(center, normal)

    def faces_at(self, anchor):
        # A concave face's centroid, or a ring's center, may lie outside its
        # material. It still supplies the correct drawing plane for that snap.
        # Both lie within the face's bounds, so a native distance is measured
        # only for faces whose bounds hold the point: measuring every face of
        # a dense part takes over a second per pointer move.
        return [face for face in self.faces_near(anchor) if point_on_face(face, anchor)
                or (self.face_center(face) - anchor).Length < EPS]

    def has_face(self, face):
        """Whether a face is one of the snapshot's drawing faces, by native identity."""
        index = getattr(self, "_face_index", None)
        if index is None or index[0] is not self.faces or index[1] != len(self.faces):
            lookup = {}
            for known in self.faces:
                lookup.setdefault(hash(known), []).append(known)
            index = self._face_index = (self.faces, len(self.faces), lookup)
        return any(face.isSame(known) for known in index[2].get(hash(face), ()))

    def faces_near(self, point, pad=1e-4):
        if len(self.faces) <= 32:
            return self.faces
        bounds = getattr(self, "_face_bounds", None)
        if bounds is None or bounds[0] is not self.faces or len(bounds[1]) != len(self.faces):
            # The collected bounds describe the collected faces; a list
            # replaced or extended afterwards is measured again.
            collected = self.faces is getattr(self, "_collected", None) and len(self.face_bounds) == len(self.faces)
            listed = self.face_bounds if collected else [
                (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax) for b in (face.BoundBox for face in self.faces)]
            bounds = self._face_bounds = (self.faces, np.asarray(listed, dtype=float).reshape(-1, 6))
        p = np.array((point.x, point.y, point.z))
        box = bounds[1]
        inside = np.all((box[:, :3] - pad <= p) & (p <= box[:, 3:] + pad), axis=1)
        return [self.faces[int(i)] for i in np.nonzero(inside)[0]]

    def _build_screen_grid(self):
        grid = {}
        cell_size = 64
        global _projections
        # Each segment rebuilds the snapshot; its points barely change, and
        # projecting tens of thousands one by one took a fifth of a second.
        state = (id(self.view), camera_state(self.view))
        if _projections is None or _projections[0] != state or len(_projections[1]) > 500000:
            _projections = (state, {})
        known = _projections[1]
        for point, label in self.points:
            key = (point.x, point.y, point.z)
            located = known.get(key)
            if located is None:
                located = known[key] = screen(self.view, point)
            sx, sy = located
            cx = int(sx // cell_size)
            cy = int(sy // cell_size)
            grid.setdefault((cx, cy), []).append((point, label, sx, sy))
        return grid, cell_size

    def _get_screen_grid(self):
        cache_key = (camera_state(self.view), id(self.points), len(self.points))
        if self._screen_cache_key != cache_key or self._screen_grid is None:
            self._screen_grid, self._screen_cell_size = self._build_screen_grid()
            self._screen_cache_key = cache_key
        return self._screen_grid, self._screen_cell_size

    def radius(self, label):
        return {"Face center": self.settings.center_radius,
                "Circle center": self.settings.center_radius,
                "Midpoint": self.settings.midpoint_radius,
                "Endpoint": self.settings.endpoint_radius,
                "Guide point": self.settings.endpoint_radius,
                "Intersection": self.settings.endpoint_radius}[label]

    def screen_points(self, pos, reach, plane=None):
        """(distance in pixels, point, label) of snap points within reach of the pointer."""
        if len(self.points) <= 32:
            located = ((point, label, *screen(self.view, point)) for point, label in self.points)
        else:
            grid, cell_size = self._get_screen_grid()
            located = (item for cx in range(int((pos[0] - reach) // cell_size), int((pos[0] + reach) // cell_size) + 1)
                       for cy in range(int((pos[1] - reach) // cell_size), int((pos[1] + reach) // cell_size) + 1)
                       for item in grid.get((cx, cy), ()))
        for point, label, sx, sy in located:
            if plane is not None and abs((point - plane.origin).dot(plane.normal)) > 1e-5:
                continue
            distance = math.hypot(sx - pos[0], sy - pos[1])
            if distance <= reach:
                yield distance, point, label

    def nearby_points(self, pos, plane=None, hit=None):
        priorities = {"Endpoint": 0, "Guide point": 0, "Intersection": 1, "Midpoint": 1,
                      "Circle center": 2, "Face center": 3}
        reach = max(self.settings.center_radius, self.settings.midpoint_radius, self.settings.endpoint_radius)
        candidates = [(distance, priorities.get(label, 3), point, label)
                      for distance, point, label in self.screen_points(pos, reach, plane)
                      if distance <= self.radius(label) and not self._covered(point, hit)]
        if not candidates:
            return []
        nearest = min(candidate[0] for candidate in candidates)

        # Where many faces meet, the centers of thin triangles and midpoints
        # of short edges crowd a vertex on screen. Close to the vertex, the
        # vertex wins, as in SketchUp, unless another target lies clearly
        # nearer the pointer.
        vertex_reach = min(VERTEX_PRIORITY_RADIUS, self.settings.endpoint_radius, nearest + VERTEX_PRIORITY_MARGIN)

        def rank(candidate):
            distance, priority, point, label = candidate
            close = distance <= nearest + 2
            # Resolve almost coincident screen projections in favor of the
            # face under the pointer, without pulling toward distant targets.
            # Only close candidates use it: skip their exact native distance.
            on_face = close and bool(hit and (point_on_face(hit[1], point)
                                     or (label == "Face center" and (self.face_center(hit[1]) - point).Length < EPS)))
            return (0 if label == "Endpoint" and distance <= vertex_reach else 1,
                    0 if close else 1,
                    0 if on_face else 1, distance, priority)

        return [(point, label) for _, _, point, label in sorted(candidates, key=rank)]

    def endpoint_hint(self, pos, plane=None, hit=None):
        """The nearest vertex a little beyond capture, to show where to aim."""
        if not self.settings.endpoints:
            return None
        near = [(distance, point) for distance, point, label in
                self.screen_points(pos, max(ENDPOINT_HINT_RADIUS, self.settings.endpoint_radius), plane)
                if label == "Endpoint" and not self._covered(point, hit)]
        return min(near, key=lambda item: item[0])[1] if near else None

    def center_hint(self, pos, plane=None):
        """Locate the hovered round edge's or face's center before the pointer nears it."""
        if not self.settings.centers:
            return None
        edge_hit = pick(self.view, self.doc, pos, prefer_boundary=True)
        if edge_hit and edge_hit[1].ShapeType == "Edge":
            center = circle_center([edge_hit[1]])
            if center is None:
                # A side of a faceted round loop: use the whole loop's center.
                for face in edge_hit[0].Shape.ancestorsOfType(edge_hit[1], Part.Face):
                    for wire in face.Wires:
                        if len(wire.Edges) >= 8 and any(e.isSame(edge_hit[1]) for e in wire.Edges):
                            center = circle_center(wire.Edges)
                            break
                    if center is not None:
                        break
            if center is not None and (plane is None or abs((center - plane.origin).dot(plane.normal)) <= 1e-5):
                return center
        hit = pick(self.view, self.doc, pos, face_only=True)
        if not hit or not self.has_face(hit[1]):
            return None
        center = self.face_center(hit[1])
        if plane is not None and abs((center - plane.origin).dot(plane.normal)) > 1e-5:
            return None
        return center

    def midpoint_hint(self, pos, plane=None):
        """Guide to the hovered edge, or a nearby midpoint on the hovered face.

        This reveals a target before capture. Only snapshot geometry qualifies.
        """
        if not self.settings.midpoints:
            return None
        hit = pick(self.view, self.doc, pos)
        if not hit or hit[1].ShapeType not in ("Edge", "Face"):
            hit = pick(self.view, self.doc, pos, face_only=True)
        if not hit:
            return None
        shape = hit[1]
        if shape.ShapeType == "Face" and not self.has_face(shape):
            return None
        candidates = []
        if shape.ShapeType == "Edge":
            bucket = self.edge_to_midpoint.get(hash(shape), self.edges)
            for edge, midpoint in bucket:
                if edge.isSame(shape):
                    if plane is not None and abs((midpoint - plane.origin).dot(plane.normal)) > 1e-5:
                        return None
                    return midpoint
            return None
        # shape.ShapeType == "Face"
        face_edges = shape.Edges
        for boundary in face_edges:
            bucket = self.edge_to_midpoint.get(hash(boundary), ())
            for edge, midpoint in bucket:
                if edge.isSame(boundary):
                    if plane is not None and abs((midpoint - plane.origin).dot(plane.normal)) > 1e-5:
                        continue
                    distance = screen_distance(screen(self.view, midpoint), pos)
                    if distance <= max(MIDPOINT_HINT_RADIUS, self.settings.midpoint_radius * 2.5):
                        candidates.append((distance, midpoint))
        return min(candidates, key=lambda item: item[0])[1] if candidates else None

    def snap_start(self, pos, plane, enabled=True):
        """Start any Auto drawing at the exact spatial target and its plane.

        A free line vertex need not lie on XY or have a native face hit. Keep
        the fallback orientation, but move its plane through the snapped point
        so subsequent radius/size previews cannot project it back onto XY.
        """
        if enabled:
            hit = pick(self.view, self.doc, pos, face_only=True)
            for point, label in self.nearby_points(pos, hit=hit):
                faces = self.faces_at(point)
                if faces:
                    chosen = next((face for face in faces if hit and face.isSame(hit[1])), faces[0])
                    return Snap(point, label), self.face_plane(chosen)
                return Snap(point, label), Plane.from_normal(point, plane.normal)
            found = self.edge_at(pos, hit=hit)
            snap = None
            if found is not None:
                snap = Snap(found[0], "On edge", direction=straight(found[1]))
            else:
                found = self.on_guide(pos, hit=hit)
                if found is not None:
                    snap = Snap(found[0], "On guide", direction=found[1])
            if snap is not None:
                faces = self.faces_at(snap.point)
                chosen = next((face for face in faces if hit and face.isSame(hit[1])), faces[0] if faces else None)
                return snap, (self.face_plane(chosen) if chosen is not None
                              else Plane.from_normal(snap.point, plane.normal))
        return self.snap(pos, plane, enabled=enabled), plane

    def line_axis(self, pos, plane, anchor, fixed=False):
        """Choose the nearest projected world axis within a narrow screen cone."""
        if not self.settings.axes:
            return None
        origin = screen(self.view, anchor)
        travel = screen_distance(origin, pos)
        if travel < 18:
            return None
        candidates = []
        for name, direction in AXES:
            in_plane = abs(direction.dot(plane.normal)) < 1e-7
            if fixed and not in_plane:
                continue
            point = axis_point(self.view, pos, anchor, direction)
            if point is None or (point - anchor).Length < EPS:
                continue
            distance = screen_distance(screen(self.view, point), pos)
            if distance <= self.settings.axis_radius and distance / travel <= AXIS_ANGLE:
                candidates.append((distance, in_plane, Snap(point, name + " axis", name)))
        if not candidates:
            return None
        nearest = min(item[0] for item in candidates)
        # Almost overlapping projections favor an axis on the working plane.
        return min(candidates, key=lambda item: (0 if item[0] <= nearest + 2 else 1,
                                                not item[1], item[0]))[2]

    def snap_surface(self, pos, face, hit, enabled=True, project_hit=True):
        """Surface endpoints, midpoints and edges; never a floating face centre."""
        from ..surfaces.line import project, snap_point
        if enabled:
            for point, label in self.nearby_points(pos, hit=hit):
                captured = snap_point(face,point,label)
                if captured is not None:
                    return Snap(captured,label)
            point = self.on_edge(pos, hit=hit)
            captured = snap_point(face,point,'On edge') if point is not None else None
            if captured is not None:
                return Snap(captured,'On edge')
        return Snap(project(face, hit[2]), 'On surface') if project_hit and hit is not None else None

    def snap_line(self, pos, plane, anchor, faces, enabled=True, axis=None, fixed=False):
        """Exact geometric targets first, then world X/Y/Z axis inference.

        Auto can leave the working plane along an axis or a spatial point snap;
        explicit planes accept only their in-plane targets and axes.
        """
        if axis is not None:
            if fixed and abs(axis.dot(plane.normal)) > 1e-7:
                raise ValueError("Choose an axis on the drawing plane, or restart Line in Auto.")
            name = next(name for name, direction in AXES if (axis - direction).Length < EPS)
            point = None if screen_distance(screen(self.view, anchor), pos) <= 2 else axis_point(self.view, pos, anchor, axis)
            if point is not None and enabled:
                hit = pick(self.view, self.doc, pos, face_only=True)
                crossing = self.axis_on_edge(pos, anchor, axis, plane if fixed else None, hit)
                if crossing is not None:
                    return Snap(crossing, name + " axis on edge", name), plane
                crossing = self.axis_on_guide(pos, anchor, axis, plane if fixed else None, hit)
                if crossing is not None:
                    return Snap(crossing, name + " axis on guide", name), plane
            return Snap(anchor if point is None else point, name + " axis locked", name), plane
        hit = pick(self.view, self.doc, pos, face_only=True)
        hovered = next((face for face in faces if hit and face.isSame(hit[1])), None)
        if enabled:
            for point, label in self.nearby_points(pos, plane=plane if fixed else None, hit=hit):
                if fixed or (point - anchor).Length < EPS:
                    return Snap(point, label), plane
                common_faces = [face for face in faces if point_on_face(face, point)]
                if common_faces:
                    chosen = next((face for face in common_faces
                                   if hovered is not None and face.isSame(hovered)), common_faces[0])
                    return Snap(point, label), self.face_plane(chosen)
                return Snap(point, label), plane
        if hovered is not None and not fixed:
            plane = self.face_plane(hovered)
        if enabled:
            inferred = self.line_axis(pos, plane, anchor, fixed)
            if inferred is not None:
                # Following an axis onto an edge ends exactly on that edge.
                direction = dict(AXES)[inferred.axis]
                crossing = self.axis_on_edge(pos, anchor, direction, plane if fixed else None, hit)
                if crossing is not None:
                    return Snap(crossing, inferred.axis + " axis on edge", inferred.axis), plane
                crossing = self.axis_on_guide(pos, anchor, direction, plane if fixed else None, hit)
                if crossing is not None:
                    return Snap(crossing, inferred.axis + " axis on guide", inferred.axis), plane
                return inferred, plane
            found = self.edge_at(pos, plane if fixed else None, hit)
            if found is not None:
                return Snap(found[0], "On edge", direction=straight(found[1])), plane
            found = self.on_guide(pos, plane if fixed else None, hit)
            if found is not None:
                return Snap(found[0], "On guide", direction=found[1]), plane
        return self.snap(pos, plane, anchor, enabled, infer_axes=False), plane

    def snap(self, pos, plane, anchor=None, enabled=True, axis=None, spatial=False, infer_axes=True):
        origin, direction = ray(self.view, pos)
        point = plane.intersect(origin, direction)
        if axis is not None and anchor is not None:
            # Project the axis to screen, then convert the pointer displacement.
            a = screen(self.view, anchor)
            step = 100.0
            b = screen(self.view, anchor + axis * step)
            dx, dy = b[0] - a[0], b[1] - a[1]
            length2 = dx * dx + dy * dy
            if length2 < 1e-8:
                raise ValueError("Axis points into the screen. Orbit the view.")
            return Snap(anchor + axis * (step * ((pos[0] - a[0]) * dx + (pos[1] - a[1]) * dy) / length2), "Axis locked")
        if not enabled:
            return Snap(point, "Plane")
        hit = pick(self.view, self.doc, pos, face_only=True)
        candidates = self.nearby_points(pos, plane=None if spatial else plane, hit=hit)
        if candidates:
            point, label = candidates[0]
            return Snap(point, label)
        if anchor is not None and infer_axes and self.settings.axes:
            axes = (V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)) if spatial else (plane.u, plane.v)
            for i, direction in enumerate(axes):
                candidate = anchor + direction * (point - anchor).dot(direction)
                if ((candidate - anchor).Length > EPS and
                        screen_distance(screen(self.view, candidate), pos) <= self.settings.axis_radius * 2 / 3):
                    return Snap(candidate, ("XYZ"[i] + " axis") if spatial else ("Plane U" if i == 0 else "Plane V"))
        found = self.edge_at(pos, None if spatial else plane, hit)
        if found is not None:
            return Snap(found[0], "On edge", direction=straight(found[1]))
        found = self.on_guide(pos, None if spatial else plane, hit)
        if found is not None:
            return Snap(found[0], "On guide", direction=found[1])
        if hit and (spatial or abs((hit[2] - plane.origin).dot(plane.normal)) <= 1e-5):
            return Snap(on_face(hit[1], hit[2]) if spatial else plane.project(hit[2]), "Face")
        return Snap(point, "Plane")
