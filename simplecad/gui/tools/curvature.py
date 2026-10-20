"""Curvature map: colour curved faces by how tightly they bend.

A temporary Coin overlay on the view, never part of the document. Running the
command again hides it; it is drawn for the selected objects, or every
visible CAD object when nothing is selected.
"""
import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin

from ...document import operations as ops
from ...surfaces import edit as se

_shown = {}  # document name -> (view, overlay root)


def shown(doc):
    return doc is not None and doc.Name in _shown


def hide(doc):
    view, root = _shown.pop(doc.Name, (None, None))
    if view is not None:
        try:
            view.getSceneGraph().removeChild(root)
            view.redraw()
        except (RuntimeError, ReferenceError):
            pass


def drawn_mesh(obj):
    """(points, triangles of each face) the 3D view draws for the object, in
    the object's own coordinates, or None when the view shows no shaded faces
    (Wireframe, Points) or draws them some other way."""
    face_set = coin.SoType.fromName('SoBrepFaceSet')
    if face_set.isBad() or getattr(obj, 'ViewObject', None) is None:
        return None
    found = []
    for kind in (coin.SoCoordinate3.getClassTypeId(), face_set):
        search = coin.SoSearchAction()
        search.setType(kind)
        search.setInterest(coin.SoSearchAction.ALL)
        search.apply(obj.ViewObject.RootNode)
        paths = search.getPaths()
        found.append([paths[i].getTail() for i in range(paths.getLength())])
    coords, faces = found
    if len(coords) != 1 or len(faces) != 1:
        return None
    points = [tuple(p) for p in coords[0].point.getValues()]
    index = faces[0].getField('coordIndex').getValues()
    parts = faces[0].getField('partIndex').getValues()
    if (len(parts) != len(obj.Shape.Faces) or 4 * sum(parts) != len(index)
            or any(i != -1 for i in index[3::4]) or any(i >= len(points) for i in index)):
        return None
    triangles, start = [], 0
    for count in parts:
        triangles.append([tuple(index[k:k + 3]) for k in range(start, start + 4 * count, 4)])
        start += 4 * count
    return points, triangles


def overlay(objects):
    """(Coin root, tight radius, gentle radius, coloured faces) for the objects."""
    shapes = []
    for obj in objects:
        # The view draws each shape in its own coordinates and moves it by the
        # object's placement, so the map does the same.
        shape = obj.Shape.copy(False)
        shape.Placement = App.Placement()
        try:
            place = obj.getGlobalPlacement()
        except (AttributeError, RuntimeError):
            place = obj.Shape.Placement
        shapes.append((obj, shape, place))
    size = App.BoundBox()
    for obj, _, _ in shapes:
        size.add(obj.Shape.BoundBox)
    tight, gentle = se.curvature_range(size.DiagonalLength)
    root = coin.SoSeparator()
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    root.addChild(pick)
    # The map lies on the very triangles the view shades, so this small pull
    # towards the camera always wins the depth test, at any zoom.
    offset = coin.SoPolygonOffset()
    offset.factor = -1.0
    offset.units = -1.0
    root.addChild(offset)
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
    root.addChild(hints)
    faces = 0
    for obj, shape, place in shapes:
        drawn = drawn_mesh(obj)
        box = shape.BoundBox
        box.enlarge(1e-3 + box.DiagonalLength * 1e-3)
        if drawn and not all(box.isInside(App.Vector(*p)) for p in drawn[0][::max(1, len(drawn[0]) // 50)]):
            drawn = None  # not drawn in the shape's own coordinates; mesh it afresh
        points, triangles, radii = se.curvature_mesh(shape, drawn=drawn)
        if not triangles:
            continue
        faces += sum(1 for f in shape.Faces if type(f.Surface).__name__ != 'Plane')
        group = coin.SoSeparator()
        move = coin.SoTransform()
        move.translation.setValue(place.Base.x, place.Base.y, place.Base.z)
        move.rotation.setValue(*place.Rotation.Q)
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(points), [tuple(p) for p in points])
        material = coin.SoMaterial()
        material.diffuseColor.setValues(0, len(radii), [se.curvature_color(r, tight, gentle) for r in radii])
        binding = coin.SoMaterialBinding()
        binding.value = coin.SoMaterialBinding.PER_VERTEX_INDEXED
        mesh = coin.SoIndexedFaceSet()
        indices = [i for triangle in triangles for i in (*triangle, -1)]
        mesh.coordIndex.setValues(0, len(indices), indices)
        mesh.materialIndex.setValues(0, len(indices), indices)
        for node in (move, coords, material, binding, mesh):
            group.addChild(node)
        root.addChild(group)
    return root, tight, gentle, faces


def toggle(controller):
    doc = App.ActiveDocument
    if doc is None:
        raise ValueError('Open a model first.')
    if shown(doc):
        hide(doc)
        controller.message('Curvature map hidden')
        return False
    objects = controller.selected() or ops.visible_shapes(doc)
    objects = [obj for obj in objects if hasattr(obj, 'Shape') and not obj.Shape.isNull()]
    if not objects:
        raise ValueError('Select CAD objects, or show some, to map their curvature.')
    root, tight, gentle, faces = overlay(objects)
    if not faces:
        raise ValueError('These objects have only flat faces; there is no curvature to map.')
    view = Gui.activeDocument().activeView()
    view.getSceneGraph().addChild(root)
    view.redraw()
    _shown[doc.Name] = (view, root)
    controller.message('Curvature map of %d curved face%s · red: radius %.3g mm or tighter · yellow, green · '
                       'blue: %.3g mm or gentler · flat faces keep their colour · click again to hide'
                       % (faces, '' if faces == 1 else 's', tight, gentle))
    return True


def forget_document(name):
    _shown.pop(name, None)
