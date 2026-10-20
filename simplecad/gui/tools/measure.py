"""Measure: pick one or two vertices, edges, faces or holes and read the results.

Measuring never edits the document. Results show in a small panel and as a
dimension in the view; Keep leaves that dimension visible while you go on
editing, until Clear kept.
"""
import FreeCADGui as Gui
import Part
from pivy import coin
from ...core import geometry as geo
from ...inspection import measuring
from ..previews.overlay import label_font, outline
from ..snapping import pick, ray, screen
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel

DIMENSION = (1.0, 0.55, 0.12)
HIGHLIGHT = (0.25, 0.72, 1.0)
VERTEX_REACH = 12  # pixels; a vertex this close to the pointer is picked

_kept = []  # (view, Overlay) left visible after the tool ends


class Overlay:
    """Unpickable target outlines and a dimension, drawn over the model.

    The dimension line has arrowheads at both ends and, when placed with an
    offset, extension lines back to the measured points, as in SketchUp.
    Arrows and gaps are sized in screen pixels and follow zoom.
    """
    def __init__(self, view):
        self.view = view
        self.state = None
        self.sensor = None
        self.root = coin.SoSeparator()
        pick_style = coin.SoPickStyle()
        pick_style.style = coin.SoPickStyle.UNPICKABLE
        depth = coin.SoDepthBuffer()
        depth.function = coin.SoDepthBuffer.ALWAYS
        depth.write = False
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        for node in (pick_style, depth, light):
            self.root.addChild(node)
        self.groups = {}
        for name, rgb, width in (('outline', HIGHLIGHT, 2.5), ('dimension', DIMENSION, 2.0), ('extra', DIMENSION, 1.2)):
            group = coin.SoSeparator()
            color = coin.SoBaseColor()
            color.rgb = rgb
            style = coin.SoDrawStyle()
            style.lineWidth = width
            style.pointSize = 9
            if name == 'extra':
                style.linePattern = 0x0F0F
            coords, lines, dots = coin.SoCoordinate3(), coin.SoLineSet(), coin.SoPointSet()
            for node in (color, style, coords, lines, dots):
                group.addChild(node)
            self.root.addChild(group)
            self.groups[name] = (coords, lines, dots)
        layer = coin.SoSeparator()
        color = coin.SoBaseColor()
        color.rgb = DIMENSION
        self.position = coin.SoTranslation()
        self.text = coin.SoText2()
        self.text.justification = coin.SoText2.CENTER
        for node in (color, self.position, label_font(18), self.text):
            layer.addChild(node)
        self.root.addChild(layer)
        view.getSceneGraph().addChild(self.root)

    def lines(self, name, polylines, dots=0):
        coords, lines, points = self.groups[name]
        values = [tuple(p) for line in polylines for p in line]
        coords.point.setValues(0, len(values), values)
        coords.point.setNum(len(values))
        lines.numVertices.setValues(0, len(polylines), [len(line) for line in polylines])
        lines.numVertices.setNum(len(polylines))
        points.numPoints = dots

    def pixel(self, point):
        """Model length of one screen pixel at a point, for the current camera."""
        try:
            plane = geo.Plane.from_normal(point, self.view.getViewDirection())
            x, y = screen(self.view, point)
            return max((plane.intersect(*ray(self.view, (x + 1, y))) - plane.intersect(*ray(self.view, (x, y)))).Length,
                       geo.EPS)
        except (AttributeError, ValueError, TypeError, RuntimeError, ZeroDivisionError):
            return .05

    def side(self, point, direction):
        """A unit direction across the line in the view, pointing up the screen."""
        try:
            across = self.view.getViewDirection().cross(direction)
            if across.Length < geo.EPS:
                return None
            across = geo.unit(across)
            if screen(self.view, point + across)[1] < screen(self.view, point)[1]:
                across = across * -1
            return across
        except (AttributeError, ValueError, TypeError, RuntimeError):
            return None

    def dimension(self, line, offset):
        """Polylines of the dimension and where its label goes."""
        a, b = line
        A, B = a + offset, b + offset
        middle = (A + B) * .5
        pixel = self.pixel(middle)
        if (B - A).Length <= pixel:
            return [], A
        along = geo.unit(B - A)
        if offset.Length > pixel * 2:
            across = geo.unit(offset)
        else:
            across = self.side(middle, along) or geo.Plane.from_normal(A, along).u
        polylines = [[A, B]]
        if offset.Length > pixel * 2:
            # Extension lines start a little off the measured points and run
            # just past the dimension line.
            for point, end in ((a, A), (b, B)):
                polylines.append([point + across * (pixel * 4), end + across * (pixel * 6)])
        size = pixel * 11
        if (B - A).Length > size * 2.5:
            for tip, inward in ((A, along), (B, along * -1)):
                polylines.append([tip + inward * size + across * (size * .35), tip, tip + inward * size - across * (size * .35)])
        return polylines, middle + across * (pixel * 12)

    def show(self, targets, measurement, offset=None):
        self.state = (targets, measurement, offset)
        self.lines('outline', [line for target in targets for line in target.outline])
        line = measurement.line if measurement is not None else None
        polylines, at = self.dimension(line, offset or geo.V()) if line else ([], targets[0].point if targets else None)
        self.lines('dimension', polylines)
        self.lines('extra', [list(pair) for pair in (measurement.extra if measurement else ())])
        if at is not None:
            self.position.translation = tuple(at)
        self.text.string = measurement.label if measurement is not None and polylines else ''
        self.follow_camera()
        self.view.redraw()

    def follow_camera(self):
        """Redraw when the view zooms or turns, so arrows keep their screen size."""
        if self.sensor is not None:
            return
        try:
            camera = self.view.getCameraNode()
        except AttributeError:
            return
        self.sensor = coin.SoNodeSensor(lambda *unused: self.state and self.show(*self.state), None)
        self.sensor.attach(camera)

    def close(self):
        if self.sensor is not None:
            self.sensor.detach()
            self.sensor = None
        try:
            self.view.getSceneGraph().removeChild(self.root)
            self.view.redraw()
        except (RuntimeError, ReferenceError, AttributeError):
            pass


def clear_kept():
    while _kept:
        _kept.pop()[1].close()


class MeasureSession:
    def __init__(self, controller):
        self.c = controller
        self.targets, self.measurement = [], None
        self.placing = False
        self.overlay = Overlay(controller.view)
        self.dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self.dialog.setObjectName('SimpleCADMeasure')
        self.dialog.setWindowTitle('Measure')
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        layout = QtWidgets.QVBoxLayout(self.dialog)
        hint = QtWidgets.QLabel('Click a vertex, edge, face or hole. Click a second one to measure between '
                                'them; a third click starts over. Place moves the dimension off the part and '
                                'leaves it in view. Nothing in the model changes.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.picked = QtWidgets.QLabel()
        self.picked.setWordWrap(True)
        layout.addWidget(self.picked)
        self.table = QtWidgets.QTreeWidget()
        self.table.setObjectName('SimpleCADMeasureResults')
        self.table.setColumnCount(2)
        self.table.setHeaderLabels(['Measurement', 'Value'])
        self.table.setRootIsDecorated(False)
        self.table.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        layout.addWidget(self.table)
        buttons = QtWidgets.QHBoxLayout()
        self.place_button = QtWidgets.QPushButton('Place')
        self.place_button.setToolTip('Move the pointer to offset the dimension, then click to leave it in view')
        self.clear_button = QtWidgets.QPushButton('Clear placed')
        copy = QtWidgets.QPushButton('Copy')
        copy.setToolTip('Copy these results as text')
        close = QtWidgets.QPushButton('Close')
        for button in (self.place_button, self.clear_button, copy, close):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.place_button.clicked.connect(self.place)
        self.clear_button.clicked.connect(self.clear)
        copy.clicked.connect(self.copy)
        close.clicked.connect(controller.cancel)
        self.dialog.rejected.connect(controller.cancel)
        self.dialog.setMinimumWidth(380)
        self.refresh()
        anchor_panel(self.dialog).show()

    def target_at(self, pos):
        """The element under the pointer; a nearby vertex wins, as when drawing."""
        snapper = self.c.snapper
        if snapper is not None:
            near = [(distance, point) for distance, point, label in snapper.screen_points(pos, VERTEX_REACH)
                    if label == 'Endpoint']
            if near:
                point = min(near, key=lambda item: item[0])[1]
                return measuring.Target('Vertex', 'Vertex', Part.Vertex(point), point, outline=[[point, point]])
        hit = pick(self.c.view, self.c.doc, pos, prefer_boundary=True)
        if not hit or not hasattr(hit[0], 'Shape'):
            return None
        return measuring.resolve(hit[0].Shape, hit[3], hit[2])

    def offset_at(self, pos):
        """How far the pointer moves the dimension off the measured points.

        The dimension moves in the plane through the measured line that faces
        the view, square to the line.
        """
        a, b = self.measurement.line
        if (b - a).Length <= geo.EPS:
            return geo.V()
        along = geo.unit(b - a)
        view = self.c.view.getViewDirection()
        facing = view - along * view.dot(along)
        if facing.Length <= 1e-6:
            return geo.V()
        try:
            point = geo.Plane.from_normal(a, facing).intersect(*ray(self.c.view, pos))
        except ValueError:
            return geo.V()
        offset = point - a
        return offset - along * offset.dot(along)

    def hover(self, pos):
        if self.placing:
            self.c.preview.show_endpoint(None)
            self.c.preview.update()
            self.overlay.show(self.targets, self.measurement, self.offset_at(pos))
            return
        # Outline only: fitting a faceted hole waits for the click.
        snapper = self.c.snapper
        vertex = None
        if snapper is not None:
            near = [(distance, point) for distance, point, label in snapper.screen_points(pos, VERTEX_REACH)
                    if label == 'Endpoint']
            vertex = min(near, key=lambda item: item[0])[1] if near else None
        self.c.preview.show_endpoint(vertex, vertex is not None)
        if vertex is not None:
            self.c.preview.update()
            return
        hit = pick(self.c.view, self.c.doc, pos, prefer_boundary=True)
        if hit and hit[1].ShapeType in ('Edge', 'Face'):
            self.c.preview.update(outline(hit[1]))
        else:
            self.c.preview.update()

    def click(self, pos):
        if self.placing:
            self.keep(self.offset_at(pos))
            return
        target = self.target_at(pos)
        if target is None:
            raise ValueError('Click a vertex, edge, face or hole of a Part object.')
        self.targets = [target] if len(self.targets) != 1 else self.targets + [target]
        self.measurement = (measuring.describe(self.targets[0]) if len(self.targets) == 1
                            else measuring.between(*self.targets))
        self.refresh()
        self.c.message(' · '.join(row.name + ' ' + row.text() for row in self.measurement.rows[:2]) +
                       (' · Click a second element to measure between them' if len(self.targets) == 1 else ''))

    def refresh(self):
        self.picked.setText('<b>1</b>: %s<br><b>2</b>: %s' % tuple(
            self.targets[i].label if i < len(self.targets) else '—' for i in range(2)))
        self.table.clear()
        for row in self.measurement.rows if self.measurement else ():
            QtWidgets.QTreeWidgetItem(self.table, [row.name, row.text()])
        self.place_button.setEnabled(self.measurement is not None and self.measurement.line is not None
                                     and not self.placing)
        self.clear_button.setEnabled(bool(_kept))
        self.overlay.show(self.targets, self.measurement)

    def place(self):
        if self.measurement is None or self.measurement.line is None:
            return
        self.placing = True
        self.refresh()
        self.c.focus_view()
        self.c.message('Move the pointer to offset the dimension · Click to place it · Esc ends Measure')

    def keep(self, offset=None):
        """Leave the dimension in the view; a fresh overlay takes the next one."""
        if self.measurement is None:
            return
        self.overlay.show([], self.measurement, offset)
        _kept.append((self.c.view, self.overlay))
        self.overlay = Overlay(self.c.view)
        self.targets, self.measurement, self.placing = [], None, False
        self.refresh()
        self.c.message('Dimension placed · It stays in view while you edit · Clear placed removes it')

    def clear(self):
        clear_kept()
        self.refresh()

    def copy(self):
        if self.measurement is not None:
            QtWidgets.QApplication.clipboard().setText(measuring.summary(self.measurement, self.targets))
            self.c.message('Measurement copied')

    def close(self):
        self.overlay.close()
        self.dialog.blockSignals(True)
        self.dialog.hide()
        self.dialog.deleteLater()
