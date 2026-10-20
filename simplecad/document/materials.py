"""Keep native surface materials attached to geometry across topology edits.

Snapshots and writes live inside the geometry transaction so Undo/Redo restores
both together. No polling, document observer, or persistent second material list.
"""
from collections import Counter
import FreeCAD as App
import Part
from . import appearance

TOL = 1e-7


def capture(doc, groups=()):
    if not App.GuiUp:
        return ()
    result = []
    for obj in doc.Objects:
        if not hasattr(obj, 'Shape') or not hasattr(obj.ViewObject, 'ShapeAppearance'):
            continue
        values = tuple(obj.ViewObject.ShapeAppearance)
        if values and obj.Shape.countElement('Face'):
            result.append((obj.Name, obj.Shape, values))
    # For a surface intersection, the first owner retains geometry from all
    # selected owners. Map against their combined pre-edit material snapshot.
    snapshots = {name: (shape, values) for name, shape, values in result}
    for group in groups:
        faces, materials = [], []
        for obj in group:
            shape, values = snapshots[obj.Name]
            current = shape.Faces
            faces.extend(current)
            materials.extend(values if len(values) == len(current) else values[:1] * len(current))
        result = [entry for entry in result if entry[0] != group[0].Name]
        result.append((group[0].Name, Part.makeCompound(faces), tuple(materials)))
    return result


def bounds(face):
    b = face.optimalBoundingBox(False, False)
    return (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)


def overlapping(a, b):
    return all(a[i] <= b[i+3]+TOL and b[i] <= a[i+3]+TOL for i in range(3))


def mapped(original, current, values):
    if len(values) == 1 or current.isPartner(original):
        return values
    old = original.Faces
    if len(values) != len(old):
        return values[:1]
    # A genuinely new surface gets the object's predominant style, never the
    # material accidentally sitting at its new FaceN index.
    styles = appearance.fingerprint(values, precision=6)
    default = Counter(styles).most_common(1)[0][0]
    special = {i for i, style in enumerate(styles) if style != default}
    default = values[styles.index(default)]
    native = {}
    for i, face in enumerate(old): native.setdefault(hash(face), []).append(i)

    class Lazy(dict):
        """Exact bounds or areas of old faces, measured only when compared."""
        def __init__(self, measure):
            super().__init__()
            self.measure = measure

        def __missing__(self, i):
            self[i] = value = self.measure(old[i])
            return value
    # Most faces keep their native identity; measuring every old face first
    # takes seconds on a dense converted part.
    boxes, areas = Lazy(bounds), Lazy(lambda face: face.Area)
    result = []
    for face in current.Faces:
        matched = next((i for i in native.get(hash(face), ()) if face.isSame(old[i])), None)
        if matched is not None:
            result.append(values[matched]); continue
        area = face.Area; box = bounds(face)
        candidates = [i for i in special if overlapping(box, boxes[i])]
        best, overlap = None, max(TOL, area*1e-9)
        # Exact same-region candidates first; descendants then inherit their
        # containing source. A merged region uses its largest contributing face.
        candidates.sort(key=lambda i: abs(areas[i]-area))
        def common_area(i):
            other = old[i]
            if type(face.Surface) is not type(other.Surface): return 0.0
            # Reject faces on other planes without a boolean operation.
            if isinstance(face.Surface, Part.Plane):
                normal = face.normalAt(face.ParameterRange[0],face.ParameterRange[2])
                other_normal = other.normalAt(other.ParameterRange[0],other.ParameterRange[2])
                if abs(normal.dot(other_normal)) < 1-1e-7 or abs((face.CenterOfMass-other.CenterOfMass).dot(normal)) > TOL:
                    return 0.0
            return face.common(other).Area
        for i in candidates:
            common = common_area(i)
            if common > overlap:
                best, overlap = i, common
            if abs(common-area) <= max(TOL,area*1e-9): break
        if best is not None and abs(overlap-area) > max(TOL,area*1e-9):
            # Only a merge touching a specially styled region needs comparisons
            # with ordinary faces; unchanged/default descendants need none.
            for i in range(len(old)):
                if i in special or not overlapping(box,boxes[i]): continue
                common = common_area(i)
                if common > overlap: best, overlap = i, common
        result.append(values[best] if best is not None else default)
    result_styles = appearance.fingerprint(result, precision=6)
    if result and all(style == result_styles[0] for style in result_styles):
        return result[:1]
    return result


def restore(doc, captured):
    for name, original, values in captured:
        obj = doc.getObject(name)
        if obj is None or obj.Shape.isSame(original): continue
        result = mapped(original, obj.Shape, values)
        if result and appearance.fingerprint(obj.ViewObject.ShapeAppearance, precision=6) != appearance.fingerprint(result, precision=6):
            obj.ViewObject.ShapeAppearance = result
