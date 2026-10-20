"""Copy, cut and paste whole objects as plain geometry, one Undo step per edit.

The clipboard holds copies taken at Copy or Cut time, so later edits to the
originals, or deleting them, do not change what Paste puts back.
"""
from collections import namedtuple

import FreeCAD as App

from . import locking
from . import operations as ops

Item = namedtuple('Item', 'type_id name label placement geometry view')
VIEW = ('DisplayMode', 'ShapeAppearance', 'LineColor', 'LineWidth', 'PointColor', 'PointSize')


def copyable(obj):
    """Plain Part shapes and raw meshes outside Part containers."""
    if obj.TypeId == 'Mesh::Feature':
        return (obj.Mesh.CountFacets > 0
                and not any(parent.hasExtension('App::GeoFeatureGroupExtension') for parent in obj.InList))
    try:
        ops.editable(obj)
    except ValueError:
        return False
    return True


def snapshot(objects):
    """Independent copies of each object's geometry, placement and look."""
    if not objects:
        raise ValueError('Select objects to copy.')
    for obj in objects:
        if not copyable(obj):
            raise ValueError(f'{obj.Label} is not a plain shape or mesh.')
    items = []
    for obj in objects:
        mesh = obj.TypeId == 'Mesh::Feature'
        view = {}
        if App.GuiUp and obj.ViewObject is not None:
            view = {name: getattr(obj.ViewObject, name) for name in VIEW if hasattr(obj.ViewObject, name)}
        items.append(Item(obj.TypeId, obj.Name, obj.Label, App.Placement(obj.Placement),
                          obj.Mesh.copy() if mesh else obj.Shape.copy(), view))
    return items


def cut(objects):
    """Take the objects out of their document in one Undo step; return their copies."""
    items = snapshot(objects)
    doc = objects[0].Document
    if any(obj.Document != doc for obj in objects):
        raise ValueError('Select objects from one document.')
    for obj in objects:
        locking.require_unlocked(obj)
    ops.apply_plan(doc, [(obj, None) for obj in dict.fromkeys(objects)], 'Cut')
    return items


def paste(doc, items):
    """Add new copies of the items where they were copied from, in one Undo step."""
    if not items:
        raise ValueError('Nothing to paste. Copy objects first.')
    results = []
    with ops.transaction(doc, 'Paste'):
        for item in items:
            obj = doc.addObject(item.type_id, item.name)
            obj.Label = item.label
            if item.type_id == 'Mesh::Feature':
                obj.Mesh = item.geometry.copy()
                obj.Placement = item.placement
            else:
                obj.Shape = item.geometry.copy()
            if App.GuiUp:
                for name, value in item.view.items():
                    setattr(obj.ViewObject, name, value)
            results.append(obj)
    return results
