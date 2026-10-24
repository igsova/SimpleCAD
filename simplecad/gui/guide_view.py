"""How guides look: long dashed lines, and crosses at guide points with dashed tails.

Fit All frames the model, not the guides: FreeCAD leaves a skip-bounding
group out of the bounds while it fits the view. At other times the group
counts, which keeps a guide inside the depth range the view draws. Only
BOUNDS of each line counts there, not its full REACH: a perspective view
keeps its near plane at a fixed fraction (about 1/4096) of its far plane,
so 100 m of line would clip anything within 25 mm of the camera. Bounds
would also cull a line where it runs away from its point, so guides are
never culled when drawing or picking.
"""
from pivy import coin
from .. import ROOT
from ..document import guides

COLOR = (0.36, 0.58, 0.86)
REACH = 1e5  # mm each way a guide line is drawn: past the model at any zoom that shows it
BOUNDS = 1e4  # mm each way of it that counts for the view's depth range
DASHES = 0x0F0F


def fill(coords, points):
    coords.point.setNum(len(points))
    coords.point.setValues(0, len(points), [tuple(point) for point in points])


class GuideNodes:
    """Scene nodes for dashed guide lines, short dashed segments and guide-point crosses."""
    def __init__(self, pickable=True):
        self.root = coin.SoSeparator()
        self.root.renderCulling = self.root.pickCulling = coin.SoSeparator.OFF
        if not pickable:
            style = coin.SoPickStyle()
            style.style = coin.SoPickStyle.UNPICKABLE
            self.root.addChild(style)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        color = coin.SoBaseColor()
        color.rgb = COLOR
        group = coin.SoType.fromName('SoSkipBoundingGroup').createInstance()
        for node in (light, color, group):
            self.root.addChild(node)
        # What counts for the depth range, neither drawn nor picked.
        counted, hidden, unpickable = coin.SoSeparator(), coin.SoDrawStyle(), coin.SoPickStyle()
        hidden.style = coin.SoDrawStyle.INVISIBLE
        unpickable.style = coin.SoPickStyle.UNPICKABLE
        self.bounds = coin.SoCoordinate3()
        for node in (hidden, unpickable, self.bounds, coin.SoPointSet()):
            counted.addChild(node)
        crosses, self.points = coin.SoSeparator(), coin.SoCoordinate3()
        marks = coin.SoMarkerSet()
        marks.markerIndex = coin.SoMarkerSet.CROSS_9_9
        crosses.addChild(self.points)
        crosses.addChild(marks)
        # Lines at their full reach, then left out of every bounding box.
        dashed, style, self.coords, self.lines = (coin.SoSeparator(), coin.SoDrawStyle(),
                                                  coin.SoCoordinate3(), coin.SoLineSet())
        dashed.renderCulling = dashed.pickCulling = coin.SoSeparator.OFF
        style.lineWidth = 1.5
        style.linePattern = DASHES
        reset = coin.SoResetTransform()
        reset.whatToReset = coin.SoResetTransform.BBOX
        for node in (style, self.coords, self.lines, reset):
            dashed.addChild(node)
        for node in (counted, crosses, dashed):
            group.addChild(node)

    def set(self, segments=(), lines=(), points=()):
        """Show [start, end] segments, endless (point, unit direction) lines and guide points."""
        drawn = [list(segment) for segment in segments] + [[p - d * REACH, p + d * REACH] for p, d in lines]
        fill(self.coords, [point for segment in drawn for point in segment])
        self.lines.numVertices.setNum(len(drawn))
        self.lines.numVertices.setValues(0, len(drawn), [2] * len(drawn))
        fill(self.points, points)
        fill(self.bounds, [point for segment in segments for point in segment] + list(points)
             + [p + d * reach for p, d in lines for reach in (-BOUNDS, BOUNDS)])


class GuideView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.object = vobj.Object
        vobj.RootNode.renderCulling = vobj.RootNode.pickCulling = coin.SoSeparator.OFF
        self.nodes = GuideNodes()
        vobj.addDisplayMode(self.nodes.root, 'Guide')
        self.update(self.object)

    def update(self, obj):
        try:
            point, direction = guides.line(obj)
        except (AttributeError, ReferenceError, RuntimeError):
            return
        if direction is None:
            start = guides.tail(obj)
            self.nodes.set([[start, point]] if start is not None else [], points=[point])
        else:
            self.nodes.set(lines=[(point, direction)])

    def updateData(self, obj, prop):
        if prop in ('Point', 'Direction', 'Start'):
            self.update(obj)

    def getDisplayModes(self, vobj):
        return ['Guide']

    def getDefaultDisplayMode(self):
        return 'Guide'

    def setDisplayMode(self, mode):
        return mode

    def onChanged(self, vobj, prop):
        pass

    def getIcon(self):
        return str(ROOT / 'Resources' / 'icons' / 'guide.svg')

    def dumps(self):
        return None

    def loads(self, state):
        return None
