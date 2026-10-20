"""Shaded, unpickable rounding preview without document/view-property edits."""
from pivy import coin

from ...core import geometry as geo, preferences


class NativeMask:
    def __init__(self, obj):
        self.root = obj.ViewObject.RootNode
        self.switch = coin.SoSwitch()
        self.switch.whichChild = coin.SO_SWITCH_NONE
        children = [self.root.getChild(i) for i in range(self.root.getNumChildren())]
        for child in children:
            self.switch.addChild(child)
        self.root.removeAllChildren()
        self.root.addChild(self.switch)

    def close(self):
        index = self.root.findChild(self.switch)
        if index >= 0:
            children = [self.switch.getChild(i) for i in range(self.switch.getNumChildren())]
            self.root.removeChild(self.switch)
            for offset, child in enumerate(children):
                self.root.insertChild(child, index + offset)


def surfaces_only(node):
    if hasattr(node, "getNumChildren"):
        for index in reversed(range(node.getNumChildren())):
            child = node.getChild(index)
            if child.isOfType(coin.SoLineSet.getClassTypeId()) or child.isOfType(coin.SoPointSet.getClassTypeId()):
                node.removeChild(index)
            else:
                surfaces_only(child)


def representation(obj, shape):
    source = coin.SoInput()
    source.setBuffer(shape.writeInventor())
    mesh = coin.SoDB.readAll(source)
    if mesh is None:
        raise ValueError("The shape preview could not be displayed.")
    surfaces_only(mesh)
    # Draw the preview in the colours the viewport style shows the object in.
    from ..controller import instance
    viewport = instance().viewport_style
    root = coin.SoSeparator()
    surface = coin.SoSeparator()
    offset = coin.SoPolygonOffset()
    offset.factor = 1
    offset.units = 1
    surface.addChild(offset)
    material = coin.SoMaterial()
    material.diffuseColor = viewport.shown_face(obj.ViewObject.ShapeColor)
    material.transparency = obj.ViewObject.Transparency / 100.0
    material.setOverride(True)
    surface.addChild(material)
    surface.addChild(mesh)
    root.addChild(surface)
    lines = coin.SoSeparator()
    light = coin.SoLightModel(); light.model = coin.SoLightModel.BASE_COLOR
    lines.addChild(light)
    color = coin.SoBaseColor(); color.rgb = viewport.shown_edge(obj.ViewObject.LineColor)
    lines.addChild(color)
    style = coin.SoDrawStyle(); style.lineWidth = obj.ViewObject.LineWidth
    lines.addChild(style)
    show_seams = preferences.load().show_seams
    curves = [edge.discretize(Deflection=max(geo.EPS * 10, shape.BoundBox.DiagonalLength / 1000))
              for edge in shape.Edges if show_seams or not geo.is_seam_edge(shape, edge)]
    coords = coin.SoCoordinate3()
    coords.point.setValues([tuple(p) for curve in curves for p in curve])
    lines.addChild(coords)
    wire = coin.SoLineSet(); wire.numVertices.setValues([len(curve) for curve in curves])
    lines.addChild(wire)
    root.addChild(lines)
    return root


class RoundPreview:
    def __init__(self, view):
        self.view = view
        self.root = coin.SoSeparator()
        pick = coin.SoPickStyle(); pick.style = coin.SoPickStyle.UNPICKABLE
        pick.setOverride(True)
        self.root.addChild(pick)
        self.models = coin.SoSeparator()
        self.root.addChild(self.models)
        self.masks = []
        view.getSceneGraph().addChild(self.root)

    def clear(self):
        self.models.removeAllChildren()
        for mask in self.masks:
            mask.close()
        self.masks.clear()
        self.view.redraw()

    def show(self, planned):
        # Build every mesh before hiding any originals. Invalid radii never
        # leave a partial or stale preview masquerading as the requested size.
        models = [representation(obj, shape) for obj, shape in planned]
        self.clear()
        for (obj, _), model in zip(planned, models):
            self.masks.append(NativeMask(obj))
            self.models.addChild(model)
        self.view.redraw()

    def close(self):
        try:
            self.clear()
            self.view.getSceneGraph().removeChild(self.root)
            self.view.redraw()
        except (RuntimeError, ReferenceError):
            pass
