"""Unpickable Coin wire overlay, removed as a single scene-graph node."""
import math

import FreeCADGui as Gui

from pivy import coin
from ...core.geometry import EPS, Plane
from ..snapping import ray, screen

AXIS_COLORS = {"X": (1.0, 0.25, 0.2), "Y": (0.2, 0.9, 0.25), "Z": (0.25, 0.5, 1.0)}
LINE_COLOR = (0.1, 0.85, 0.65)
# Preview lines behind faces, as SketchUp shows hidden geometry: dimmer and dashed.
HIDDEN_COLOR = (0.06, 0.6, 0.46)
HIDDEN_PATTERN = 0x0F0F
SEE_THROUGH = "SimpleCADSeeThrough"


def pixel_ratio():
    """Physical pixels per logical pixel of the main window.

    Coin draws SoText2 in physical pixels, so on a Retina screen a font size
    must be doubled to read at the size it names.
    """
    try:
        return max(1.0, float(Gui.getMainWindow().devicePixelRatioF()))
    except (AttributeError, RuntimeError, TypeError):
        return 1.0


def label_font(points):
    font = coin.SoFont()
    font.name = "Helvetica:Bold"
    font.size = points * pixel_ratio()
    return font


class SnapGuide:
    """An unpickable, fixed-size target with an exact-capture confirmation."""
    def __init__(self, view, parent, label, rgb, text_rgb, diamond=False, square=False):
        self.view, self.label, self.diamond, self.square = view, label, diamond, square
        self.switch = coin.SoSwitch()
        self.switch.whichChild = coin.SO_SWITCH_NONE
        hint = coin.SoSeparator()
        depth = coin.SoDepthBuffer()
        depth.function = coin.SoDepthBuffer.ALWAYS
        depth.write = False
        hint.addChild(depth)
        self.coords = coin.SoCoordinate3()
        self.lines = coin.SoLineSet()
        self.dot_coords = coin.SoCoordinate3()
        self.dots = []
        # Dark outline keeps the target visible on cyan selection highlights.
        for layer_rgb, width, size in (((0.04, 0.06, 0.07), 5.5, 15), (rgb, 2.5, 10)):
            layer = coin.SoSeparator()
            color = coin.SoBaseColor()
            color.rgb = layer_rgb
            layer.addChild(color)
            style = coin.SoDrawStyle()
            style.lineWidth = width
            style.pointSize = size
            layer.addChild(style)
            layer.addChild(self.coords)
            layer.addChild(self.lines)
            layer.addChild(self.dot_coords)
            dot = coin.SoPointSet()
            dot.numPoints = 0
            layer.addChild(dot)
            self.dots.append(dot)
            hint.addChild(layer)
        self.texts = []
        self.text_positions = []
        for layer_rgb in ((0.04, 0.06, 0.07), text_rgb):
            layer = coin.SoSeparator()
            color = coin.SoBaseColor()
            color.rgb = layer_rgb
            layer.addChild(color)
            position = coin.SoTranslation()
            layer.addChild(position)
            layer.addChild(label_font(14))
            text = coin.SoText2()
            layer.addChild(text)
            self.text_positions.append(position)
            self.texts.append(text)
            hint.addChild(layer)
        self.switch.addChild(hint)
        parent.addChild(self.switch)

    def update(self, center, snapped):
        self.switch.whichChild = 0 if center is not None else coin.SO_SWITCH_NONE
        if center is None:
            return
        # Camera-facing geometry gives the target a fixed pixel size at every
        # zoom, on both orthographic and perspective views. This UI glyph
        # ignores depth; preview lines keep their normal occlusion (Push/Pull's
        # opt-in see-through pass draws their hidden parts again, dashed).
        plane = Plane.from_normal(center, self.view.getViewDirection())
        x, y = screen(self.view, center)
        origin = plane.intersect(*ray(self.view, (x, y)))
        u = plane.intersect(*ray(self.view, (x + 1, y))) - origin
        v = plane.intersect(*ray(self.view, (x, y + 1))) - origin
        if self.diamond:
            outline = [center + u * 12, center + v * 12, center - u * 12,
                       center - v * 12, center + u * 12]
        elif self.square:
            outline = [center + u * 9 + v * 9, center - u * 9 + v * 9, center - u * 9 - v * 9,
                       center + u * 9 - v * 9, center + u * 9 + v * 9]
        else:
            outline = [center + u * (11 * math.cos(i * math.tau / 24))
                       + v * (11 * math.sin(i * math.tau / 24)) for i in range(25)]
        cross = [[center - u * 5, center + u * 5], [center - v * 5, center + v * 5]]
        lines = [outline] + cross
        points = [tuple(point) for line in lines for point in line]
        self.coords.point.setValues(0, len(points), points)
        self.coords.point.setNum(len(points))
        self.lines.numVertices.setValues(0, 3, [len(line) for line in lines])
        self.dot_coords.point.setValue(tuple(center))
        for dot in self.dots:
            dot.numPoints = 1 if snapped else 0
        for index, (position, text) in enumerate(zip(self.text_positions, self.texts)):
            offset = 1 if index == 0 else 0
            # Put midpoint and endpoint text above the target, center text below it.
            text_y = 16 if self.diamond or self.square else -6
            position.translation = tuple(center + u * (16 + offset) + v * (text_y - offset))
            text.string = self.label + (" snapped" if snapped else "")


def halfway(points):
    """The point half way along a polyline and the segment it lies on."""
    remaining = sum((b - a).Length for a, b in zip(points, points[1:])) / 2
    for a, b in zip(points, points[1:]):
        step = (b - a).Length
        if step >= EPS and remaining <= step:
            return a + (b - a) * (remaining / step), (a, b)
        remaining -= step
    return None, None


def beside(start, end, middle, text, ratio=1.0, away=None):
    """Screen centre of a text box beside a segment, across from its middle.

    ``start``, ``end`` and ``middle`` are screen positions, y up. The box goes
    to the side of the segment away from the screen point ``away``, such as
    out of a rectangle; without one, or with ``away`` on the line, it goes up
    the screen, or right of an upright segment. It is just far enough that
    the text clears the line at any angle.
    """
    dx, dy = end[0] - start[0], end[1] - start[1]
    size = math.hypot(dx, dy)
    nx, ny = (-dy / size, dx / size) if size > 1e-9 else (0.0, 1.0)
    side = 0.0 if away is None else nx * (middle[0] - away[0]) + ny * (middle[1] - away[1])
    if side < -1e-9 or (abs(side) <= 1e-9 and (ny < -1e-9 or (abs(ny) <= 1e-9 and nx < 0))):
        nx, ny = -nx, -ny
    # Bold 14 pt digits are about 8 px wide and 10 px tall.
    width, height = 8 * len(text) * ratio, 10 * ratio
    reach = 6 * ratio + abs(nx) * width / 2 + abs(ny) * height / 2
    return middle[0] + nx * reach, middle[1] + ny * reach


class LengthLabel:
    """A size of the shape being drawn, beside the midpoint of the line it measures.

    Like the snap labels it keeps its pixel size and draws over faces, in the
    preview line's color with a dark outline so it reads on any background.
    """
    def __init__(self, view, parent):
        self.view = view
        self.switch = coin.SoSwitch()
        self.switch.whichChild = coin.SO_SWITCH_NONE
        label = coin.SoSeparator()
        depth = coin.SoDepthBuffer()
        depth.function = coin.SoDepthBuffer.ALWAYS
        depth.write = False
        label.addChild(depth)
        self.colors, self.positions, self.texts = [], [], []
        for rgb in ((0.04, 0.06, 0.07), LINE_COLOR):
            layer = coin.SoSeparator()
            color = coin.SoBaseColor()
            color.rgb = rgb
            position = coin.SoTranslation()
            text = coin.SoText2()
            text.justification = coin.SoText2.CENTER
            for node in (color, position, label_font(14), text):
                layer.addChild(node)
            self.colors.append(color)
            self.positions.append(position)
            self.texts.append(text)
            label.addChild(layer)
        self.switch.addChild(label)
        parent.addChild(self.switch)

    def update(self, points=(), text="", rgb=LINE_COLOR, away=None):
        middle, segment = halfway(list(points)) if text else (None, None)
        self.switch.whichChild = 0 if middle is not None else coin.SO_SWITCH_NONE
        if middle is None:
            return
        ratio = pixel_ratio()
        x, y = beside(screen(self.view, segment[0]), screen(self.view, segment[1]),
                      screen(self.view, middle), text, ratio,
                      screen(self.view, away) if away is not None else None)
        # SoText2 sits on its baseline: lower it to centre the digits.
        y -= 4 * ratio
        plane = Plane.from_normal(middle, self.view.getViewDirection())
        base = plane.intersect(*ray(self.view, (x, y)))
        # The outline copy is one pixel right and down.
        shadow = plane.intersect(*ray(self.view, (x + 1, y - 1)))
        self.colors[1].rgb = rgb
        for position, node, at in zip(self.positions, self.texts, (shadow, base)):
            position.translation = tuple(at)
            node.string = text


class Preview:
    def __init__(self, view):
        self.view = view
        self.root = coin.SoSeparator()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        self.root.addChild(pick)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        self.root.addChild(light)
        self.color = coin.SoBaseColor()
        self.color.rgb = LINE_COLOR
        self.root.addChild(self.color)
        style = coin.SoDrawStyle()
        style.lineWidth = 2.5
        style.pointSize = 12
        self.root.addChild(style)
        self.coords = coin.SoCoordinate3()
        self.lines = coin.SoLineSet()
        # A moving outline is sent to Coin once and then only translated, so
        # dragging a dense object does not rewrite all of its points per move.
        moving = coin.SoSeparator()
        self.offset = coin.SoTranslation()
        self.moving_coords = coin.SoCoordinate3()
        self.moving_lines = coin.SoLineSet()
        for node in (self.offset, self.moving_coords, self.moving_lines):
            moving.addChild(node)
        self.moving = None
        self.marker_coords = coin.SoCoordinate3()
        self.marker = coin.SoPointSet()
        drawn = (self.coords, self.lines, moving, self.marker_coords, self.marker)
        # Opt-in (Push/Pull into a solid): the same nodes drawn first without
        # depth test, thinner and dashed, so the parts behind faces show
        # through and the visible parts are drawn over as before.
        self.see_through = coin.SoSwitch()
        self.see_through.setName(SEE_THROUGH)
        self.see_through.whichChild = coin.SO_SWITCH_NONE
        hidden = coin.SoSeparator()
        depth = coin.SoDepthBuffer()
        depth.function = coin.SoDepthBuffer.ALWAYS
        depth.write = False
        color = coin.SoBaseColor()
        color.rgb = HIDDEN_COLOR
        dashes = coin.SoDrawStyle()
        dashes.lineWidth = 2
        dashes.pointSize = 8
        dashes.linePattern = HIDDEN_PATTERN
        dashes.linePatternScaleFactor = round(pixel_ratio())
        for node in (depth, color, dashes) + drawn:
            hidden.addChild(node)
        self.see_through.addChild(hidden)
        for node in (self.see_through,) + drawn:
            self.root.addChild(node)
        self.center_guide = SnapGuide(view, self.root, "Center", (1.0, 0.76, 0.15), (1.0, 0.86, 0.4))
        self.midpoint_guide = SnapGuide(view, self.root, "Midpoint", (0.25, 0.72, 1.0),
                                       (0.6, 0.88, 1.0), diamond=True)
        self.pull_guide = SnapGuide(view, self.root, "Opposite face", (1.0, 0.76, 0.15), (1.0, 0.86, 0.4))
        # Green squares mark vertices, as endpoints are marked in SketchUp.
        self.endpoint_guide = SnapGuide(view, self.root, "Endpoint", (0.3, 0.9, 0.45), (0.6, 1.0, 0.7), square=True)
        self.length_labels = []  # Made as shapes need them: a Rectangle shows two.
        self.lengths = []  # (polyline, own text, away point) of each labelled line
        self.length_color = LINE_COLOR
        view.getSceneGraph().addChild(self.root)

    def update(self, polylines=(), point=None, center=None, center_snapped=False,
               midpoint=None, midpoint_snapped=False, axis="", contact=None, contact_snapped=False,
               contact_label="Opposite face", moving=(), offset=None, see_through=False, lengths=()):
        """Draw the polylines, plus ``moving`` shifted by ``offset``.

        Pass the same ``moving`` list object on every update of a drag: it is
        converted only when a different list arrives. ``see_through`` also
        draws the lines and marker hidden behind faces, dashed. Each of
        ``lengths`` is a (polyline, text) pair labelled beside the polyline's
        midpoint, or (polyline, text, away) to put the text on the side away
        from the point ``away``.
        """
        shown = 0 if see_through else coin.SO_SWITCH_NONE
        if self.see_through.whichChild.getValue() != shown:
            self.see_through.whichChild = shown
        self.color.rgb = self.length_color = AXIS_COLORS.get(axis, LINE_COLOR)
        self.lengths = [(list(entry[0]), entry[1], entry[2] if len(entry) > 2 else None) for entry in lengths]
        self._label()
        self._lines(self.coords, self.lines, polylines)
        if moving is not self.moving:
            self.moving = moving
            self._lines(self.moving_coords, self.moving_lines, moving)
        self.offset.translation = tuple(offset) if offset is not None else (0, 0, 0)
        self.marker.numPoints = 1 if point is not None else 0
        if point is not None:
            self.marker_coords.point.setValue(tuple(point))
        self.center_guide.update(center, center_snapped)
        self.midpoint_guide.update(midpoint, midpoint_snapped)
        self.pull_guide.label = contact_label
        self.pull_guide.update(contact, contact_snapped)
        self.view.redraw()

    def relabel(self, texts=()):
        """Label the drawn lines with other text, such as sizes being typed.

        One text per labelled line, in the order of ``lengths``; a missing
        or empty one keeps that line's own size. The lines are unchanged, and
        the next update shows their own sizes again.
        """
        if not self.lengths:
            return
        self._label(texts)
        self.view.redraw()

    def _label(self, texts=()):
        while len(self.length_labels) < len(self.lengths):
            self.length_labels.append(LengthLabel(self.view, self.root))
        for index, label in enumerate(self.length_labels):
            if index >= len(self.lengths):
                label.update()
                continue
            points, own, away = self.lengths[index]
            typed = texts[index] if index < len(texts) else None
            label.update(points, typed or own, self.length_color, away)

    def show_endpoint(self, point, snapped=False):
        """Mark the vertex under or near the pointer; drawn with the next update."""
        self.endpoint_guide.update(point, snapped)

    @staticmethod
    def _lines(coords, lines, polylines):
        points = [tuple(p) for line in polylines for p in line]
        coords.point.setValues(0, len(points), points)
        coords.point.setNum(len(points))
        lines.numVertices.setValues(0, len(polylines), [len(line) for line in polylines])
        lines.numVertices.setNum(len(polylines))

    def close(self):
        _outlines.clear()
        try:
            self.view.getSceneGraph().removeChild(self.root)
            self.view.redraw()
        except (RuntimeError, ReferenceError):
            pass


_outlines = []


def outline(shape):
    """edges(shape), reused while the same shape is shown again.

    Hover and drag previews redraw one face or object on every mouse move;
    discretizing its boundary each time scales with its edge count. Placement
    is part of shape identity, so a moved shape is sampled again. The same
    list is returned each time, so Preview.update can recognize it as
    ``moving``; copy it before adding lines.
    """
    for known, polylines in _outlines:
        if known.isSame(shape):
            return polylines
    polylines = edges(shape)
    _outlines.insert(0, (shape, polylines))
    del _outlines[8:]
    return polylines


def edges(shape, offset=None):
    result = []
    for edge in shape.Edges:
        # Bound the turn between samples as well as the chord gap: a fixed
        # deflection alone draws a small circle as a triangle or square.
        points = edge.discretize(Angular=math.radians(5), Curvature=0.1, Minimum=2)
        result.append([p + offset for p in points] if offset is not None else points)
    return result
