"""Saved SimpleCAD geometry locks, with face references independent of numbering."""
import json
import FreeCAD as App
import Part
from ..core import coincident

OBJECT = 'SC_Locked'
FACES = 'SC_FaceLocks'
_cache = {}


def whole(obj):
    return bool(getattr(obj, OBJECT, False))


def state(obj):
    """Return explicitly locked face numbers and whether references are stale.

    Save local BREP references rather than FaceN: unrelated topology edits may
    renumber faces. Cache matching once per shape/metadata change, not per row.
    Unmatched/corrupt references fail closed until explicitly cleared.
    """
    raw = getattr(obj, FACES, '')
    if not raw:
        return set(), False
    shape = obj.Shape
    key = (obj.Document.Name, obj.Name)
    cached = _cache.get(key)
    if cached and cached[0] == raw and shape.isEqual(cached[1]):
        return set(cached[2]), cached[3]
    indices, stale = set(), False
    try:
        references = json.loads(raw)
        if not isinstance(references, list): raise ValueError('Invalid face locks')
        local = shape.copy(); local.Placement = App.Placement()
        faces = local.Faces
        for brep in references:
            reference = Part.Shape(); reference.importBrepFromString(brep)
            matches = {i for i, face in enumerate(faces, 1) if coincident.same(face, reference)}
            indices.update(matches)
            stale = stale or not matches
    except Exception:
        stale = True
    _cache[key] = (raw, shape, frozenset(indices), stale)
    return indices, stale


def require_unlocked(obj, names=()):
    indices, stale = state(obj)
    if whole(obj) or stale or (not names and indices) or any(
            n.startswith('Face') and int(n[4:]) in indices for n in names):
        raise ValueError(f'{obj.Label} contains locked geometry. Unlock it before editing.')


def require_face_unlocked(obj, face):
    indices, stale = state(obj)
    if whole(obj) or stale or any(coincident.same(obj.Shape.Faces[i-1], face) for i in indices):
        raise ValueError(f'{obj.Label} contains locked geometry. Unlock it before editing.')


def set_locked(targets, locked):
    """Explicit, atomic lock/unlock; parent targets take precedence."""
    from . import operations as ops
    grouped = {}
    doc = None
    for obj, names in targets:
        ops.editable(obj)
        if doc is not None and doc != obj.Document: raise ValueError('Select one document.')
        doc = obj.Document
        names = set(names)
        for name in names:
            if not name.startswith('Face') or not name[4:].isdigit() or not 1 <= int(name[4:]) <= len(obj.Shape.Faces):
                raise ValueError('Locks apply to faces or whole objects.')
        previous = grouped.get(obj, set())
        grouped[obj] = None if not names or previous is None else previous | names
    if not grouped: raise ValueError('Select a face or object to lock.')
    if not doc.UndoMode: raise ValueError('Enable document Undo before changing geometry locks.')
    planned = []
    for obj, names in grouped.items():
        indices, stale = state(obj)
        if names is not None:
            if whole(obj): raise ValueError(f'Unlock the object {obj.Label} first.')
            if stale: raise ValueError(f'{obj.Label}: face references changed outside SimpleCAD. Unlock the whole object to clear them.')
            selected = {int(n[4:]) for n in names}
            indices = indices | selected if locked else indices - selected
        local = obj.Shape.copy(); local.Placement = App.Placement()
        raw = json.dumps([local.Faces[i-1].exportBrepToString() for i in sorted(indices)]) if indices else ''
        planned.append((obj, names, '' if stale and not locked else raw))
    with ops.transaction(doc, 'Lock geometry' if locked else 'Unlock geometry'):
        for obj, names, raw in planned:
            if names is None:
                if OBJECT not in obj.PropertiesList:
                    obj.addProperty('App::PropertyBool', OBJECT, 'SimpleCAD', 'Protect geometry from SimpleCAD editing tools')
                    obj.setEditorMode(OBJECT, 1)
                    obj.setPropertyStatus(OBJECT, 'Output')
                setattr(obj, OBJECT, bool(locked))
            # Do not silently replace unresolved references while locking.
            if names is not None or (not locked and state(obj)[1]):
                if FACES not in obj.PropertiesList:
                    obj.addProperty('App::PropertyString', FACES, 'SimpleCAD', 'Protected face geometry references')
                    obj.setEditorMode(FACES, 2)
                    obj.setPropertyStatus(FACES, 'Output')
                setattr(obj, FACES, raw)


def capture(doc):
    result = []
    for obj in doc.Objects:
        if not hasattr(obj, 'Shape') or not (whole(obj) or getattr(obj, FACES, '')): continue
        indices, stale = state(obj)
        shape = obj.Shape
        result.append((obj.Name, obj.Label, shape, whole(obj) or stale,
                       [shape.Faces[i-1] for i in sorted(indices)]))
    return result


def same_shape(first, second):
    # Recomputing a plain Part feature after metadata changes can rebuild its
    # topology. Identity alone would incorrectly reject Unlock itself.
    if first.ShapeType != second.ShapeType or first.Orientation != second.Orientation: return False
    if len(first.Solids) != len(second.Solids) or len(first.Shells) != len(second.Shells): return False
    if first.Placement.Matrix.A != second.Placement.Matrix.A: return False
    for attr in ('Faces', 'Edges'):
        before, after = getattr(first, attr), getattr(second, attr)
        if len(before) != len(after): return False
        if any(a.Orientation != b.Orientation or not coincident.same(a, b) for a, b in zip(before, after)): return False
    return len(first.Vertexes) == len(second.Vertexes) and all(
        (a.Point-b.Point).Length <= 1e-7 for a,b in zip(first.Vertexes,second.Vertexes))


def validate(doc, captured):
    for name, label, original, entire, faces in captured:
        obj = doc.getObject(name)
        if obj is not None and obj.Shape.isEqual(original): continue
        if obj is not None and entire and same_shape(original, obj.Shape): continue
        if obj is None or entire or any(not any(face.Orientation == candidate.Orientation and coincident.same(face, candidate) for candidate in obj.Shape.Faces) for face in faces):
            raise ValueError(f'{label} contains locked geometry. Unlock it before editing. No changes were kept.')


def forget_document(name):
    for key in list(_cache):
        if key[0] == name: del _cache[key]
