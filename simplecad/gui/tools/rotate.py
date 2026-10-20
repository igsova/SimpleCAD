"""Axis, pivot and angle controls for a reversible rigid rotation."""
import FreeCAD as App
import FreeCADGui as Gui
from ...document import operations as ops
from ...modeling import rotation
from ..previews.rotate import RotatePreview
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel


class RotateSession:
    def __init__(self, controller, targets, selection):
        self.controller, self.targets, self.selection = controller, targets, selection
        self.doc = targets[0][0].Document
        self.closed = False
        self.planned = None
        self.frame_key = None
        self.frames = None
        self.preview = RotatePreview(controller.view, targets)
        self.dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self.dialog.setObjectName("SimpleCADRotate")
        self.dialog.setWindowTitle("Rotate")
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        layout = QtWidgets.QVBoxLayout(self.dialog)
        is_edge_mode = any(getattr(t, "mode", "object") in ("edge", "face") for t in targets)
        self.is_edge_mode = is_edge_mode
        if is_edge_mode:
            count = sum(len(getattr(t, "elements", ())) for t in targets)
            layout.addWidget(QtWidgets.QLabel("%d line/arc edge%s selected" % (count, "" if count == 1 else "s")))
        else:
            layout.addWidget(QtWidgets.QLabel("%d whole object%s selected" % (len(targets), "" if len(targets) == 1 else "s")))
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)
        self.axis = QtWidgets.QComboBox(self.dialog)
        self.axis.setObjectName("SimpleCADRotateAxis")
        if is_edge_mode:
            self.axis.addItem("Face / Plane normal", "FaceNormal")
        for title, key in (("X — world", "X"), ("Y — world", "Y"), ("Z — world", "Z"),
                           ("Object main axis", "Main"), ("Object X — local", "LocalX"),
                           ("Object Y — local", "LocalY"), ("Object Z — local", "LocalZ")):
            self.axis.addItem(title, key)
        self.axis.setCurrentIndex(0 if is_edge_mode else 2)
        form.addRow("Axis", self.axis)
        self.pivot = QtWidgets.QComboBox(self.dialog)
        self.pivot.setObjectName("SimpleCADRotatePivot")
        self.pivot.setToolTip("Together and World origin use one shared axis. For object axes, this is the first selected object's axis.")
        if is_edge_mode:
            self.pivot.addItem("Curve / Hole center", "CurveCenter")
            self.pivot.addItem("Start point", "Start")
            self.pivot.addItem("End point", "End")
            self.pivot.addItem("Selection center", "Selection")
            self.pivot.addItem("World origin — 0, 0, 0", "Origin")
        else:
            for title, key in (("Selection center — together", "Selection"),
                               ("Each object's center", "Each"), ("World origin — 0, 0, 0", "Origin")):
                self.pivot.addItem(title, key)
        form.addRow("Rotate around", self.pivot)
        self.angle = QtWidgets.QLineEdit("0°", self.dialog)
        self.angle.setObjectName("SimpleCADRotateAngle")
        self.angle.setPlaceholderText("45° or -90°")
        form.addRow("Angle", self.angle)
        self.copy_check = QtWidgets.QCheckBox("Keep original (copy)", self.dialog)
        self.copy_check.setObjectName("SimpleCADRotateCopy")
        if is_edge_mode:
            layout.addWidget(self.copy_check)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self.dialog)
        self.slider.setObjectName("SimpleCADRotateSlider")
        self.slider.setRange(-180, 180)
        self.slider.setTickInterval(45)
        self.slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.slider.setStyleSheet("QSlider::groove:horizontal { height: 4px; background: #555; border-radius: 2px; } "
                                 "QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #50d6bb; border-radius: 7px; }")
        layout.addWidget(self.slider)
        presets = QtWidgets.QHBoxLayout()
        self.presets = {}
        for degrees in (-90, -45, 0, 45, 90):
            button = QtWidgets.QPushButton("%+d°" % degrees if degrees else "Reset", self.dialog)
            button.setAutoDefault(False)
            button.clicked.connect(lambda unused=False, value=degrees: self.angle.setText("%d°" % value))
            presets.addWidget(button)
            self.presets[degrees] = button
        layout.addLayout(presets)
        self.note = QtWidgets.QLabel("World axes stay fixed. Object axes follow the object.\nUse a negative angle to turn the other way.")
        self.note.setWordWrap(True)
        self.note.setMaximumWidth(360)
        self.angle.setToolTip("Degrees by default; angular units such as rad also work. Positive turns are counterclockwise looking from the arrow tip toward the center.")
        layout.addWidget(self.note)
        self.status = QtWidgets.QLabel(self.dialog)
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(self.status.fontMetrics().lineSpacing() * 2)
        layout.addWidget(self.status)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.Apply)
        self.apply_button.setAutoDefault(False)
        self.apply_button.clicked.connect(self.apply)
        buttons.rejected.connect(controller.cancel)
        self.dialog.rejected.connect(controller.cancel)
        layout.addWidget(buttons)
        self.pending = QtCore.QTimer(self.dialog)
        self.pending.setSingleShot(True)
        self.pending.timeout.connect(self.update_preview)
        self.axis.currentIndexChanged.connect(self.axis_changed)
        self.pivot.currentIndexChanged.connect(self.changed)
        self.angle.textChanged.connect(self.changed)
        self.angle.returnPressed.connect(self.apply)
        self.slider.valueChanged.connect(lambda value: self.angle.setText("%d°" % value))
        self.dialog.setMinimumWidth(380)

    def open(self):
        Gui.Selection.clearSelection()
        Gui.Selection.clearPreselection()
        anchor_panel(self.dialog).show()
        self.update_preview()
        self.angle.setFocus()
        self.angle.selectAll()

    def axis_changed(self, *unused):
        # Own-axis rotation starts as a spin around each object's own center.
        if self.axis.currentData() in ("Main", "LocalX", "LocalY", "LocalZ"):
            self.pivot.setCurrentIndex(self.pivot.findData("Each"))
        self.changed()

    def changed(self, *unused):
        self.apply_button.setEnabled(False)
        self.pending.start(25)

    def update_preview(self):
        self.pending.stop()
        if self.closed:
            return False
        try:
            self.controller.check_context()
            if self.closed:
                return False
            ops.check_rotation(self.targets)
            angle = rotation.parse_angle(self.angle.text())
            key = (self.axis.currentData(), self.pivot.currentData())
            if self.frames is None or self.frame_key != key:
                self.frames = rotation.frames([shape for _, shape in self.targets], *key, targets=self.targets)
                self.frame_key = key
            self.planned = ops.preview_rotation(self.targets, self.frames, angle)
            self.preview.show_rotation(self.frames, angle, key[0])
            self.preview_angle = angle
            self.slider.blockSignals(True)
            self.slider.setValue(round(rotation.angle_degrees(angle)))
            self.slider.blockSignals(False)
            self.status.setStyleSheet("")
            self.status.setText("Original orientation · nothing will change" if rotation.angle_degrees(angle) == 0 else
                                "Preview: %.6g° · Apply to keep · Esc cancels" % angle)
            self.apply_button.setEnabled(True)
            return True
        except Exception as error:
            self.planned = None
            self.preview.clear()
            self.status.setStyleSheet("color: #e78f70;")
            self.status.setText(str(error))
            self.apply_button.setEnabled(False)
            return False

    def apply(self):
        if not self.update_preview():
            return
        try:
            self.preview.clear()
            copy_mode = self.copy_check.isChecked() if self.is_edge_mode else False
            changed = ops.commit_rotation(self.targets, self.frames, self.preview_angle, copy=copy_mode)
            self.controller.cancel(quiet=True)
            if changed:
                Gui.Selection.clearSelection()
                for obj, _ in self.targets:
                    Gui.Selection.addSelection(obj)
            self.controller.focus_view()
            msg = ("Lines/arcs rotated · Undo with ⌘Z" if self.is_edge_mode else "Objects rotated · Undo with ⌘Z") if changed else "Original orientation kept"
            self.controller.message(msg)
        except Exception as error:
            self.planned = None
            self.status.setText(str(error))
            self.apply_button.setEnabled(False)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.pending.stop()
        self.preview.close()
        self.dialog.blockSignals(True)
        self.dialog.close()
        self.dialog.deleteLater()
        try:
            ops.check_rotation(self.targets)
            if App.ActiveDocument == self.doc:
                for obj, names in self.selection:
                    for name in names or ("",):
                        Gui.Selection.addSelection(obj, name)
        except (ValueError, RuntimeError, ReferenceError):
            pass
