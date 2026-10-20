"""Native, saved face materials. Surface opacity is the inverse of transparency."""
import math
import re
import FreeCAD as App
from . import operations

FIELDS = ('DiffuseColor', 'AmbientColor', 'SpecularColor', 'EmissiveColor', 'Shininess', 'Transparency')
_previewing = set()


def clone(material):
    result = App.Material()
    for field in FIELDS:
        setattr(result, field, getattr(material, field))
    return result


def _material_tuple(m, precision):
    def scalar(val):
        return val if precision is None else round(val, precision)

    def vector(val):
        return tuple(scalar(c) for c in val) if isinstance(val, (tuple, list)) else scalar(val)

    return (
        vector(m.DiffuseColor),
        vector(m.AmbientColor),
        vector(m.SpecularColor),
        vector(m.EmissiveColor),
        scalar(m.Shininess),
        scalar(m.Transparency),
    )


def fingerprint(materials, precision=None):
    if not materials:
        return ()
    return tuple(_material_tuple(m, precision) for m in materials)


def expanded(obj, materials=None):
    values = list(obj.ViewObject.ShapeAppearance if materials is None else materials)
    if not values:
        raise ValueError('This object has no surface material.')
    count = len(obj.Shape.Faces)
    return [clone(values[i] if len(values) == count else values[0]) for i in range(count)]


def describe(obj, index=None):
    if not hasattr(obj.ViewObject, 'ShapeAppearance') or not obj.Shape.Faces:
        return None
    values = obj.ViewObject.ShapeAppearance
    if not values:
        return None
    if index is not None:
        values = [values[index-1] if len(values) == len(obj.Shape.Faces) else values[0]]
    colors = [tuple(m.DiffuseColor[:3]) for m in values]
    opacities = [round(100*(1-m.Transparency), 4) for m in values]
    return {'color': list(colors[0]) if all(c == colors[0] for c in colors) else None,
            'opacity': opacities[0] if all(o == opacities[0] for o in opacities) else None}


def describe_all(obj):
    """Read the native material list once for the whole tree, not once per row."""
    values = getattr(obj.ViewObject, 'ShapeAppearance', None)
    if values is None:
        return None, ()
    count = len(obj.Shape.Faces)
    if not count or not values:
        return None, ()
    if len(values) == 1:
        st = {'color': list(values[0].DiffuseColor[:3]), 'opacity': round(100*(1-values[0].Transparency), 4)}
        return st, (st,) * count
    states = tuple({'color': list(m.DiffuseColor[:3]), 'opacity': round(100*(1-m.Transparency),4)} for m in values)
    faces = states if len(states) == count else (states[0],)*count
    first = states[0]
    whole = {key: first[key] if all(s[key] == first[key] for s in states) else None
             for key in ('color','opacity')}
    return whole, faces


def prepare(selection):
    grouped = {}
    doc = None
    for obj, names in selection:
        operations.editable(obj)
        if not App.GuiUp or not hasattr(obj.ViewObject, 'ShapeAppearance') or not obj.Shape.Faces:
            raise ValueError('Select faces or objects with surfaces to change their appearance.')
        if doc is not None and obj.Document != doc:
            raise ValueError('Select faces or objects from one document.')
        doc = obj.Document
        indices = set()
        for name in names:
            match = re.fullmatch(r'Face([1-9][0-9]*)', name)
            if not match or int(match[1]) > len(obj.Shape.Faces):
                raise ValueError('Select faces or whole objects, not edges or vertices.')
            indices.add(int(match[1])-1)
        prior = grouped.get(obj, set())
        grouped[obj] = None if not names or prior is None else prior | indices
    if not grouped:
        raise ValueError('Select a face or whole object, then choose Color & opacity.')
    return [(obj, obj.Shape, indices, tuple(obj.ViewObject.ShapeAppearance))
            for obj, indices in grouped.items()]


def validate(color, opacity):
    if color is not None:
        if (not isinstance(color, (list, tuple)) or len(color) != 3 or
                any(isinstance(c, bool) or not isinstance(c, (int, float)) or
                    not math.isfinite(c) or not 0 <= c <= 1 for c in color)):
            raise ValueError('Color must have three RGB components from 0 to 1.')
    if opacity is not None and (isinstance(opacity, bool) or not isinstance(opacity, (int, float)) or
                                not math.isfinite(opacity) or not 0 <= opacity <= 100):
        raise ValueError('Opacity must be from 0% to 100%.')


def plan(targets, color=None, opacity=None):
    validate(color, opacity)
    planned = []
    for obj, shape, indices, original in targets:
        if not obj.isValid() or not obj.Shape.isSame(shape):
            raise ValueError('The shape changed. Select its faces and open Color & opacity again.')
        values = expanded(obj, original)
        for i in range(len(values)) if indices is None else indices:
            if color is not None:
                values[i].DiffuseColor = tuple(float(c) for c in color)
            if opacity is not None:
                values[i].Transparency = 1-opacity/100
        # Keep uniform objects uniform, so future faces inherit that appearance.
        first_tuple = _material_tuple(values[0], None)
        if all(_material_tuple(m, None) == first_tuple for m in values):
            values = values[:1]
        planned.append((obj, values))
    return planned


def write(planned):
    for obj, values in planned:
        if fingerprint(obj.ViewObject.ShapeAppearance) != fingerprint(values):
            obj.ViewObject.ShapeAppearance = values


def commit(targets, color=None, opacity=None):
    if color is None and opacity is None:
        raise ValueError('Choose a color or opacity to apply.')
    planned = plan(targets, color, opacity)
    if all(fingerprint(obj.ViewObject.ShapeAppearance) == fingerprint(values) for obj, values in planned):
        return False
    with operations.transaction(targets[0][0].Document, 'Color & opacity'):
        write(planned)
    return True


def face_material_nodes(root):
    """Find the material state actually used by native face sets, not edges."""
    found = []
    def walk(node, current=None):
        name = str(node.getTypeId().getName())
        if name == 'Material' or name == 'SoMaterial':
            return node
        if name == 'SoBrepFaceSet' and current is not None:
            if not any(current == old for old in found):
                found.append(current)
        if hasattr(node, 'getNumChildren'):
            state = current
            for i in range(node.getNumChildren()):
                state = walk(node.getChild(i), state)
            # Separator restores the state when leaving its children.
            if 'Separator' not in name:
                return state
        return current
    walk(root)
    return found


def sync_transparency(obj):
    """Repair FreeCAD's global Transparency callback flattening face alpha.

    The native material list remains the saved source of truth. Updating only
    Coin's alpha array avoids document edits, extra Undo entries or new geometry.
    """
    if (obj.Document.Name, obj.Name) in _previewing:
        return
    values = obj.ViewObject.ShapeAppearance
    if len(values) <= 1 or len(values) != len(obj.Shape.Faces):
        return
    expected = tuple(m.Transparency for m in values)
    for node in face_material_nodes(obj.ViewObject.RootNode):
        if node.diffuseColor.getNum() == len(values) and tuple(node.transparency.getValues()) != expected:
            node.transparency.setNum(len(expected))
            node.transparency.setValues(list(expected))


def sync_display(obj, previous=None):
    """Refresh native render caches after edits, Undo or reopening a file."""
    if (obj.Document.Name, obj.Name) in _previewing:
        return previous
    current = (obj, obj.ViewObject.RootNode, fingerprint(obj.ViewObject.ShapeAppearance))
    if current != previous:
        # Material fields alone can leave a restored view's cached colors in
        # use. Native update refreshes that representation without a model edit.
        obj.ViewObject.update()
        current = (obj, obj.ViewObject.RootNode, fingerprint(obj.ViewObject.ShapeAppearance))
    sync_transparency(obj)
    return current


class Preview:
    """Temporary Coin material state; never edits the document or Redo history."""
    def __init__(self):
        self.saved = []
        self.keys = set()
        self.faces = []
        self.objects = []

    def apply(self, planned):
        from pivy import coin
        self.close()
        for obj, values in planned:
            # Invalidate native render caches before writing temporary state.
            obj.ViewObject.update()
            self.objects.append(obj)
            key = (obj.Document.Name, obj.Name)
            self.keys.add(key); _previewing.add(key)
            def bindings(node):
                if str(node.getName()) == 'FaceBind':
                    self.saved.append((node.value, node.value.getValue(), False))
                    node.value.setValue(coin.SoMaterialBinding.PER_PART if len(values)>1 else coin.SoMaterialBinding.OVERALL)
                if str(node.getTypeId().getName()) == 'SoBrepFaceSet':
                    self.faces.append(node)
                if hasattr(node, 'getNumChildren'):
                    for i in range(node.getNumChildren()): bindings(node.getChild(i))
            # Shared display branches may contain the same binding more than
            # once. Restore in reverse order so its original state wins.
            bindings(obj.ViewObject.RootNode)
            for node in face_material_nodes(obj.ViewObject.RootNode):
                for field, source in (('diffuseColor','DiffuseColor'), ('ambientColor','AmbientColor'),
                                      ('specularColor','SpecularColor'), ('emissiveColor','EmissiveColor'),
                                      ('shininess','Shininess'), ('transparency','Transparency')):
                    prop = getattr(node,field)
                    old = list(prop.getValues())
                    if field.endswith('Color'): old = [tuple(c.getValue()) for c in old]
                    self.saved.append((prop,old,True))
                    changed = [getattr(m,source) for m in values]
                    if field.endswith('Color'): changed = [tuple(c[:3]) for c in changed]
                    prop.setNum(len(changed)); prop.setValues(changed)
        for node in self.faces: node.touch()
        from ..gui.controller import instance
        instance().seams.refresh()

    def close(self):
        for field, values, multiple in reversed(self.saved):
            if multiple: field.setNum(len(values)); field.setValues(values)
            else: field.setValue(values)
        for node in self.faces: node.touch()
        self.saved.clear(); self.faces.clear()
        _previewing.difference_update(self.keys); self.keys.clear()
        for obj in self.objects:
            if obj.isValid():
                obj.ViewObject.update()
                sync_transparency(obj)
        self.objects.clear()
        from ..gui.controller import instance
        instance().seams.refresh()
