"""The status-bar controls: tool label, typed value, drawing mode and polygon sides."""
from .. import ROOT
from ..core.geometry import MAX_POLYGON_SIDES
from .qt import QtWidgets


class Controls(QtWidgets.QWidget):
    def __init__(self, controller, parent):
        super().__init__(parent)
        self.controller = controller
        self.setObjectName("SimpleCADControls")
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(6, 0, 6, 0)
        self.label = QtWidgets.QLabel("SimpleCAD", self)
        self.sides_label = QtWidgets.QLabel("Sides", self)
        self.sides = QtWidgets.QSpinBox(self)
        self.sides.setObjectName("SimpleCADPolygonSides")
        self.sides.setRange(3, MAX_POLYGON_SIDES); self.sides.setValue(controller.polygon_sides)
        self.sides.setKeyboardTracking(False)
        self.sides.setToolTip("Number of equal-length polygon sides. Change before or after choosing the center.")
        self.sides.setMaximumWidth(90)
        icons = ROOT / "Resources" / "icons"
        self.sides.setStyleSheet('QSpinBox::up-arrow { image: url("' + (icons / "spin-up.svg").as_posix() +
                                '"); width: 10px; height: 10px; } QSpinBox::down-arrow { image: url("' +
                                (icons / "spin-down.svg").as_posix() + '"); width: 10px; height: 10px; }')
        self.sides.valueChanged.connect(controller.polygon_sides_changed)
        self.sides_label.hide(); self.sides.hide()
        self.elongate_mode = QtWidgets.QComboBox(self)
        self.elongate_mode.addItems(["Ellipse", "Slot"])
        self.elongate_mode.setToolTip("Elongate mode: smooth analytic Ellipse or slotted hole (stadium shape)")
        self.elongate_mode.hide()
        self.drawing_mode = QtWidgets.QComboBox(self)
        self.drawing_mode.setObjectName('SimpleCADDrawingMode')
        self.drawing_mode.addItems(['Draw: Plane', 'Draw: Surface'])
        self.drawing_mode.setToolTip('Plane: ordinary flat drawing and straight 3D lines. Surface: wrap over connected CAD faces of one object with Line, Rectangle, Circle, Polygon or either Arc tool. Select a face first to disambiguate shared boundaries. Snap controls endpoints and midpoints separately.')
        self.drawing_mode.currentIndexChanged.connect(controller.drawing_mode_changed)
        self.plane = QtWidgets.QComboBox(self)
        self.plane.addItems(["Auto", "XY", "XZ", "YZ"])
        self.plane.setToolTip('Plane drawing: Auto uses a flat face, a view-facing plane over curved geometry, or XY in empty space. XY/XZ/YZ select fixed planes through the world origin. While drawing, arrow keys lock a plane through the start point for that drawing: Right YZ (red X), Left XZ (green Y), Up XY (blue Z), Down Auto; after a Line\'s first click they lock its axis. Draw: Surface wraps over connected CAD faces instead and temporarily disables this plane selector.')
        self.plane.activated.connect(controller.plane_chosen)
        self.snap = QtWidgets.QCheckBox("Snap", self)
        self.snap.setChecked(True)
        self.snap.setToolTip("Snap to vertices, edge midpoints, face centers, and nearby axes. Line uses red X, green Y, blue Z. Line, Circle and Polygon show labeled center and midpoint targets.")
        self.value = QtWidgets.QLineEdit(self)
        self.value.setObjectName("SimpleCADMeasurement")
        self.value.setPlaceholderText("Length / width, height")
        self.value.setToolTip("Tab while drawing to enter a size; Enter to apply. Move Vertex accepts dx, dy, dz (mm) or a signed distance along the locked axis. Arc uses radius then signed degrees; 2 Point Arc uses endpoint distance then signed bulge. Circle uses radius; Polygon uses center-to-vertex radius. Units default to mm.")
        self.value.setMaximumWidth(180)
        self.value.returnPressed.connect(controller.numeric)
        self.value.textChanged.connect(controller.typed_size)
        self.selection_filter = QtWidgets.QComboBox(self)
        self.selection_filter.setObjectName("SimpleCADSelectionFilter")
        self.selection_filter.addItems(["Select: All", "Select: Faces", "Select: Edges", "Select: Vertices", "Select: Objects"])
        self.selection_filter.setToolTip("What clicks and selection boxes pick. Objects selects whole objects; a face click in Edges mode takes the nearest edge. Double-click a face or edge to grow it into a hole, loop, flat region or smooth surface")
        self.selection_filter.currentTextChanged.connect(
            lambda text: setattr(controller.selection, 'filter', text.split(': ')[1]))
        self.settings = QtWidgets.QToolButton(self)
        self.settings.setText("Settings…")
        self.settings.setToolTip("SimpleCAD display and snapping settings")
        self.settings.clicked.connect(lambda: controller.start("Settings"))
        for widget in (self.label, self.sides_label, self.sides, self.elongate_mode, self.drawing_mode, self.plane, self.snap, self.value,
                       self.selection_filter, self.settings):
            row.addWidget(widget)

    def configure_drawing(self, tool=None):
        available = tool is None or tool in ('Line','Rectangle','Circle','Polygon','Arc','Arc2Point')
        self.drawing_mode.setVisible(available)
        self.plane.setEnabled(not available or self.drawing_mode.currentIndex() == 0)

    def clear(self):
        self.value.clear()
        self.label.setText("SimpleCAD")
        self.value.setPlaceholderText("Length / width, height")
        self.sides_label.hide(); self.sides.hide()
        self.elongate_mode.hide()
        self.configure_drawing()
