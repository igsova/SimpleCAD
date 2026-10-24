"""Guides: dashed construction lines and points that drawing snaps to.

Measure Tape leaves them, as SketchUp's Tape Measure does. A guide has no
shape, so modeling tools, selection windows and exports pass it by; only
snapping and the view use it. A document's guides sit in one Guides group,
where they can be hidden or deleted together.
"""
import FreeCAD as App
from ..core import geometry as geo

MARK = 'SC_Guide'
GROUP_MARK = 'SC_Guides'


class Guide:
    """Proxy of a guide: the Point it passes through and, for a line, its Direction."""
    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty('App::PropertyVector', 'Point', 'Guide', 'A point the guide passes through')
        obj.addProperty('App::PropertyVector', 'Direction', 'Guide',
                        'Direction of a guide line; zero for a guide point')
        obj.addProperty('App::PropertyBool', MARK, 'Guide', 'Marks a SimpleCAD guide')
        obj.setEditorMode(MARK, 2)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _has(obj, mark):
    try:
        return mark in getattr(obj, 'PropertiesList', ())
    except (ReferenceError, RuntimeError):
        return False


def is_guide(obj):
    return _has(obj, MARK)


def is_group(obj):
    return _has(obj, GROUP_MARK)


def line(obj):
    """(point, unit direction) of a guide line, or (point, None) of a guide point."""
    direction = geo.V(obj.Direction)
    return geo.V(obj.Point), (geo.unit(direction) if direction.Length > geo.EPS else None)


def shown(obj):
    if not App.GuiUp:
        return True
    view = getattr(obj, 'ViewObject', None)
    return view is not None and view.Visibility


def visible(doc):
    """(point, direction or None) of each guide shown in the document."""
    for obj in doc.Objects:
        if is_guide(obj) and shown(obj) and all(shown(parent) for parent in obj.InList if is_group(parent)):
            yield line(obj)


def group(doc):
    """The document's Guides group, made when the first guide is added."""
    found = next((obj for obj in doc.Objects if is_group(obj)), None)
    if found is None:
        found = doc.addObject('App::DocumentObjectGroup', 'Guides')
        found.Label = 'Guides'
        found.addProperty('App::PropertyBool', GROUP_MARK, 'Guide', 'Holds the SimpleCAD guides')
        found.setEditorMode(GROUP_MARK, 2)
    return found


def add(doc, point, direction=None):
    """Add a guide line through a point, or a guide point, in one Undo step."""
    from .operations import transaction
    point = geo.V(point)
    if direction is not None:
        if direction.Length < geo.EPS:
            raise ValueError('A guide line needs a direction.')
        direction = geo.unit(direction)
    with transaction(doc, 'Guide'):
        obj = doc.addObject('App::FeaturePython', 'Guide')
        Guide(obj)
        obj.Point = point
        obj.Direction = direction if direction is not None else geo.V()
        obj.Label = 'Guide' if direction is not None else 'Guide point'
        group(doc).addObject(obj)
        if App.GuiUp:
            from ..gui.guide_view import GuideView
            GuideView(obj.ViewObject)
    return obj


def remove(objects):
    """Delete guides, or whole Guides groups with their guides, in one Undo step."""
    from .operations import transaction
    objects = [obj for obj in objects if is_guide(obj) or is_group(obj)]
    if not objects:
        return False
    doc = objects[0].Document
    names = []
    for obj in objects:
        names += [child.Name for child in obj.Group if is_guide(child)] if is_group(obj) else []
        names.append(obj.Name)
    with transaction(doc, 'Delete guides'):
        for name in dict.fromkeys(names):
            if doc.getObject(name) is not None:
                doc.removeObject(name)
    return True
