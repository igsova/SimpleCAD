"""Choose a face-following pattern or a grid with a reversible preview."""
import FreeCAD as App
import FreeCADGui as Gui
from ... import ROOT
from ...document import operations as ops
from ...modeling import subdivision
from ..previews.shaded import RoundPreview
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel


class SubdivideSession:
    def __init__(self, controller, target, selection):
        self.controller, self.target, self.selection = controller, target, selection
        self.doc = target[0].Document
        self.closed = False
        self.planned = None
        self.preview_key = None
        self.preview = RoundPreview(controller.view)
        self.dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self.dialog.setObjectName("SimpleCADSubdivide")
        self.dialog.setWindowTitle("Subdivide face")
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        icons = ROOT / "Resources" / "icons"
        self.dialog.setStyleSheet('QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("' +
                                  (icons / "spin-up.svg").as_posix() + '"); width: 10px; height: 10px; } '
                                  'QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("' +
                                  (icons / "spin-down.svg").as_posix() + '"); width: 10px; height: 10px; }')
        layout = QtWidgets.QVBoxLayout(self.dialog)
        layout.addWidget(QtWidgets.QLabel("%s · Face%d" % (target[0].Label, target[2] + 1)))
        form = self.form = QtWidgets.QFormLayout(); layout.addLayout(form)
        self.profile = subdivision.Profile(target[1].Faces[target[2]])
        self.pattern = QtWidgets.QComboBox(self.dialog)
        self.pattern.setObjectName("SimpleCADSubdividePattern")
        if len(self.profile.convex_corners()) == 3:
            self.pattern.addItem("Triangles", "triangles")
        if self.profile.convex_corners() or self.profile.is_disk():
            self.pattern.addItem("Center fan", "fan")
        self.pattern.addItem("Evenly spaced grid", "spaced")
        self.pattern.addItem("Equal-area grid", "equal_area")
        self.pattern.setCurrentIndex(self.pattern.findData(self.profile.default_pattern()))
        form.addRow("Pattern", self.pattern)
        self.divisions = self.integer(form, "Divisions per side", "PerSide", 3)
        self.fan_steps = 8 if self.profile.is_disk() else 1
        self.previous_pattern = "triangles"
        self.triangle_steps = 3
        self.mode = QtWidgets.QComboBox(self.dialog)
        self.mode.addItems(["Total divisions", "Rows and columns", "Rows only", "Columns only"])
        self.previous_mode = 0
        self.mode.setObjectName("SimpleCADSubdivideMode")
        form.addRow("Set by", self.mode)
        self.total = self.integer(form, "Divisions", "Total", 9)
        self.rows = self.integer(form, "Rows", "Rows", 3)
        self.columns = self.integer(form, "Columns", "Columns", 3)
        self.angle = QtWidgets.QDoubleSpinBox(self.dialog)
        self.angle.setObjectName("SimpleCADSubdivideAngle")
        self.angle.setRange(-180, 180); self.angle.setDecimals(1)
        self.angle.setSingleStep(15); self.angle.setSuffix("°")
        self.angle.setKeyboardTracking(False)
        self.angle.setToolTip("Zero follows the face's longest straight edge. Change this to turn the grid on the face.")
        form.addRow("Grid angle", self.angle)
        note = self.note = QtWidgets.QLabel()
        note.setWordWrap(True); note.setMaximumWidth(360)
        layout.addWidget(note)
        self.status = QtWidgets.QLabel(self.dialog)
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(self.status.fontMetrics().lineSpacing() * 3)
        layout.addWidget(self.status)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.Apply)
        self.apply_button.setAutoDefault(False)
        self.apply_button.clicked.connect(self.apply)
        buttons.rejected.connect(controller.cancel)
        self.dialog.rejected.connect(controller.cancel)
        layout.addWidget(buttons)
        self.pending = QtCore.QTimer(self.dialog)
        self.pending.setSingleShot(True); self.pending.timeout.connect(self.update_preview)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.pattern.currentIndexChanged.connect(self.pattern_changed)
        self.divisions.valueChanged.connect(self.changed)
        self.total.valueChanged.connect(self.changed)
        self.rows.valueChanged.connect(self.changed)
        self.columns.valueChanged.connect(self.changed)
        self.angle.valueChanged.connect(self.changed)
        self.dialog.setMinimumWidth(380)

    def integer(self, form, title, key, default):
        value = QtWidgets.QSpinBox(self.dialog)
        value.setObjectName("SimpleCADSubdivide" + key)
        value.setRange(1, subdivision.MAX_PARTS); value.setValue(default)
        value.setKeyboardTracking(False)
        form.addRow(title, value)
        return value

    def open(self):
        Gui.Selection.clearSelection(); Gui.Selection.clearPreselection()
        self.pattern_changed()
        anchor_panel(self.dialog).show(); self.update_preview()
        field = self.total if self.pattern.currentData() in ("spaced", "equal_area") else self.divisions
        field.setFocus(); field.selectAll()

    def visible(self, field, show):
        field.setVisible(show)
        self.form.labelForField(field).setVisible(show)

    def pattern_changed(self, *unused):
        pattern = self.pattern.currentData()
        if self.previous_pattern == "triangles":
            self.triangle_steps = self.divisions.value()
        elif self.previous_pattern == "fan":
            self.fan_steps = self.divisions.value()
        if pattern in ("triangles", "fan"):
            self.divisions.setValue(self.triangle_steps if pattern == "triangles" else self.fan_steps)
        self.previous_pattern = pattern
        grid = pattern in ("spaced", "equal_area")
        self.visible(self.mode, grid); self.visible(self.total, grid)
        self.visible(self.rows, grid); self.visible(self.columns, grid)
        self.visible(self.divisions, not grid)
        self.visible(self.angle, grid or (pattern == "fan" and self.profile.is_disk()))
        self.form.labelForField(self.angle).setText("Start angle" if pattern == "fan" else "Grid angle")
        self.form.labelForField(self.divisions).setText("Sectors" if pattern == "fan" and self.profile.is_disk() else "Divisions per side")
        self.mode.setItemText(0, "Total grid cells" if pattern == "spaced" else "Total divisions")
        self.form.labelForField(self.total).setText("Grid cells" if pattern == "spaced" else "Divisions")
        self.note.setText({
            "triangles": "Follow all three sides with smaller triangles. 2 divisions per side makes 4 triangles; 3 makes 9.",
            "fan": ("Equal-angle sectors around the circle's center." if self.profile.is_disk() else
                    "Join the center to each corner, then divide each triangle. This preserves the outline's symmetry; areas may differ on irregular polygons."),
            "spaced": "Dividers are equally spaced. Choose Rows only or Columns only for strips. Near the outline, pieces may be smaller or empty; the preview shows the actual face count.",
            "equal_area": "Every piece has equal area. Divider spacing adjusts to the outline, so widths and piece shapes may differ."
        }[pattern])
        self.update_enabled(); self.changed()

    def mode_changed(self, *unused):
        mode = self.mode.currentIndex()
        if mode == 0:
            count = (self.rows.value() if self.previous_mode == 2 else self.columns.value() if self.previous_mode == 3
                     else self.rows.value() * self.columns.value())
            if count <= subdivision.MAX_PARTS:
                self.total.setValue(count)
        elif mode == 1 and self.previous_mode == 0:
            # Switching modes must not depend on the debounce timer having run.
            rows, columns = subdivision.dimensions(self.total.value())
            self.rows.setValue(rows); self.columns.setValue(columns)
        self.previous_mode = mode
        self.update_enabled()
        self.changed()

    def update_enabled(self):
        mode = self.mode.currentIndex()
        grid = self.pattern.currentData() in ("spaced", "equal_area")
        self.visible(self.total, grid and mode == 0)
        self.visible(self.rows, grid and mode != 3); self.visible(self.columns, grid and mode != 2)
        self.total.setEnabled(mode == 0)
        self.rows.setEnabled(mode in (1, 2)); self.columns.setEnabled(mode in (1, 3))

    def changed(self, *unused):
        self.apply_button.setEnabled(False)
        self.pending.start(200)

    def parameters(self):
        pattern = self.pattern.currentData()
        if pattern in ("triangles", "fan"):
            angle = self.angle.value() if pattern == "fan" and self.profile.is_disk() else 0
            return 1, 1, angle, pattern, self.divisions.value()
        if self.mode.currentIndex() == 0:
            rows, columns = subdivision.dimensions(self.total.value())
            for field, number in ((self.rows, rows), (self.columns, columns)):
                field.blockSignals(True); field.setValue(number); field.blockSignals(False)
        mode = self.mode.currentIndex()
        return (1 if mode == 3 else self.rows.value(), 1 if mode == 2 else self.columns.value(),
                self.angle.value(), pattern, self.divisions.value())

    def update_preview(self):
        self.pending.stop()
        if self.closed:
            return False
        try:
            self.controller.check_context()
            if self.closed:
                return False
            ops.check_subdivision(self.target)
            key = self.parameters()
            if self.planned is None or self.preview_key != key:
                planned, regions = ops.preview_subdivision(self.target, *key)
                self.preview.show(planned)
                self.planned, self.regions, self.preview_key = planned, regions, key
            rows, columns, _, pattern, divisions = key
            count = len(self.regions)
            layout = ("%d divisions per side" % divisions if pattern == "triangles" else
                      "%d sectors" % divisions if pattern == "fan" and self.profile.is_disk() else
                      "%d divisions per triangle side" % divisions if pattern == "fan" else
                      "%d rows × %d columns" % (rows, columns))
            areas = [f.Area for f in self.regions]
            area = ("%.6g mm² per face" % areas[0] if max(areas) - min(areas) < max(1e-7, max(areas) * 1e-7) else
                    "Areas vary · equally spaced dividers" if pattern == "spaced" else "Areas follow the outline")
            self.status.setStyleSheet("")
            self.status.setText("1 face · no new divisions" if count == 1 else
                                "%d faces · %s\n%s\nApply to keep · Esc cancels" % (count, layout, area))
            self.apply_button.setEnabled(True)
            return True
        except Exception as error:
            self.planned = None; self.preview.clear()
            self.status.setStyleSheet("color: #e78f70;")
            self.status.setText(str(error)); self.apply_button.setEnabled(False)
            return False

    def apply(self):
        # Spin boxes can still have uncommitted typed text when Apply is clicked.
        for field in (self.total, self.rows, self.columns, self.angle, self.divisions):
            field.interpretText()
        if not self.update_preview():
            return
        try:
            self.preview.clear()
            rows, columns = self.preview_key[:2]
            count = len(self.regions)
            changed = ops.commit_subdivision(self.target, self.planned, rows, columns, region_count=count)
            self.controller.cancel(quiet=True)
            Gui.Selection.clearSelection()
            self.controller.focus_view()
            self.controller.message("%d faces · Click any region to Push/Pull · Undo with ⌘Z" % count
                                    if changed else "Original face kept")
        except Exception as error:
            self.planned = None
            self.status.setText(str(error)); self.apply_button.setEnabled(False)

    def close(self):
        if self.closed:
            return
        self.closed = True; self.pending.stop(); self.preview.close()
        self.dialog.blockSignals(True); self.dialog.close(); self.dialog.deleteLater()
        try:
            ops.check_subdivision(self.target)
            if App.ActiveDocument == self.doc:
                for obj, names in self.selection:
                    for name in names or ("",): Gui.Selection.addSelection(obj, name)
        except (ValueError, RuntimeError, ReferenceError):
            pass
