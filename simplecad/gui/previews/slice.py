"""Transient shaded pieces and an unpickable cutting-plane guide."""
from pivy import coin
from .shaded import RoundPreview


class SlicePreview(RoundPreview):
    def __init__(self, view):
        super().__init__(view)
        self.guide = coin.SoSeparator()
        self.root.addChild(self.guide)

    def show_plane(self, plane, offset):
        points = [tuple(vertex.Point) for vertex in plane.face(offset).Vertexes]
        self.guide.removeAllChildren()
        light = coin.SoLightModel(); light.model = coin.SoLightModel.BASE_COLOR
        self.guide.addChild(light)
        fill = coin.SoSeparator()
        material = coin.SoMaterial()
        material.diffuseColor = (.18, .8, .95)
        material.transparency = .85
        fill.addChild(material)
        coords = coin.SoCoordinate3(); coords.point.setValues(points)
        fill.addChild(coords)
        face = coin.SoFaceSet(); face.numVertices.setValue(4)
        fill.addChild(face)
        self.guide.addChild(fill)
        lines = coin.SoSeparator()
        color = coin.SoBaseColor(); color.rgb = (.18, .8, .95)
        lines.addChild(color)
        style = coin.SoDrawStyle(); style.lineWidth = 2
        lines.addChild(style)
        center = plane.center + plane.normal * offset
        tip = center + plane.normal * (plane.size * .15)
        coords = coin.SoCoordinate3(); coords.point.setValues(points + points[:1] + [tuple(center), tuple(tip)])
        lines.addChild(coords)
        wire = coin.SoLineSet(); wire.numVertices.setValues([5, 2])
        lines.addChild(wire)
        self.guide.addChild(lines)
        self.view.redraw()
