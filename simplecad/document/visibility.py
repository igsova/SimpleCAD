"""Saved view-only face visibility, guarded against changed face numbering."""
import hashlib
import json
import FreeCAD as App

PROPERTY = 'SC_FaceVisibility'
_cache = {}
_elements = {}


def signature(shape):
    # A BREP byte hash changes after harmless floating-point location updates.
    # Compare local geometry and ordered face boundaries at modeling tolerance.
    local = shape.copy()
    local.Placement = App.Placement()
    def scalar(value): return round(float(value), 7) or 0.0
    def point(value): return tuple(scalar(v) for v in (value.x, value.y, value.z))
    def edge(value):
        samples = [point(value.valueAt(value.FirstParameter + (value.LastParameter-value.FirstParameter)*i/8)) for i in range(9)]
        return type(value.Curve).__name__, scalar(value.Length), samples
    faces = [(type(face.Surface).__name__, face.Orientation, scalar(face.Area),
              point(face.CenterOfMass), [edge(e) for e in face.Edges]) for face in local.Faces]
    data = (faces, [edge(e) for e in local.Edges], [point(v.Point) for v in local.Vertexes])
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()


def hidden_faces(obj):
    if not App.GuiUp or not obj.ViewObject:
        return set()
    raw = getattr(obj.ViewObject, PROPERTY, '')
    if not raw:
        return set()
    key = (obj.Document.Name, obj.Name)
    shape = obj.Shape
    if shape.isNull():
        return set()
    cached = _cache.get(key)
    if cached and cached[0] == raw and shape.isSame(cached[1]):
        return set(cached[2])
    try:
        state = json.loads(raw)
        hidden = {int(i) for i in state['hidden'] if isinstance(i, int) and 1 <= i <= len(shape.Faces)}
        if state['shape'] != signature(shape):
            hidden.clear()
    except (ValueError, TypeError, KeyError, RuntimeError):
        hidden = set()
    _cache[key] = (raw, shape, hidden)
    return set(hidden)


def set_hidden(obj, hidden):
    """Store only display metadata; never replace or split the model's Shape."""
    view = obj.ViewObject
    if PROPERTY not in view.PropertiesList:
        view.addProperty('App::PropertyString', PROPERTY, 'SimpleCAD', 'Hidden faces and their source shape; managed by the eye controls')
        view.setEditorMode(PROPERTY, 2)
    hidden = sorted(set(hidden))
    setattr(view, PROPERTY, json.dumps({'shape': signature(obj.Shape), 'hidden': hidden}) if hidden else '')


def hidden_elements(shape, faces):
    """Only hide a boundary when none of its adjoining faces remain visible."""
    hidden_edges, hidden_vertices = set(), set()
    if not faces:
        return hidden_edges, hidden_vertices
    visible = [f for i, f in enumerate(shape.Faces, 1) if i not in faces]
    hidden = [f for i, f in enumerate(shape.Faces, 1) if i in faces]
    for result, elements, attr in ((hidden_edges, shape.Edges, 'Edges'),
                                  (hidden_vertices, shape.Vertexes, 'Vertexes')):
        kept, removed = {}, {}
        for group, members in ((kept, visible), (removed, hidden)):
            for face in members:
                for element in getattr(face, attr):group.setdefault(hash(element), []).append(element)
        for i, element in enumerate(elements, 1):
            if any(element.isSame(e) for e in removed.get(hash(element), ())) and not any(element.isSame(e) for e in kept.get(hash(element), ())):
                result.add(i)
    return hidden_edges, hidden_vertices


def object_hidden_elements(obj, hidden):
    """hidden_elements for an object's current shape, kept until either changes."""
    key = (obj.Document.Name, obj.Name)
    shape = obj.Shape
    cached = _elements.get(key)
    if cached and cached[0] == hidden and shape.isSame(cached[1]):
        return cached[2]
    result = hidden_elements(shape, hidden)
    _elements[key] = (frozenset(hidden), shape, result)
    return result


def element_visible(obj, name):
    if not obj.ViewObject.Visibility:
        return False
    hidden = hidden_faces(obj)
    if not hidden or not name:
        return True
    if name.startswith('Face'):
        return int(name[4:]) not in hidden
    # Checked once per face-browser row or snap candidate: rebuilding the
    # whole shape's hidden edges for each one scales with the element count.
    edges, vertices = object_hidden_elements(obj, hidden)
    if name.startswith('Edge'):
        return int(name[4:]) not in edges
    if name.startswith('Vertex'):
        return int(name[6:]) not in vertices
    return True


def forget_document(name):
    for cache in (_cache, _elements):
        for key in list(cache):
            if key[0] == name:
                del cache[key]
