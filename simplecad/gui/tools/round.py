"""Small radius panel with a preview, explicit Apply, and reversible cancel."""
import FreeCAD as App
import FreeCADGui as Gui

from ...core import geometry as geo
from ...document import operations as ops
from ..previews.shaded import RoundPreview
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel


class RoundSession:
    def __init__(self, controller, targets, selection):
        self.controller, self.targets, self.selection = controller, targets, selection
        self.doc = targets[0][0].Document
        self.closed = False
        self.planned = None
        self.preview_radius = None
        self.preview = RoundPreview(controller.view)
        self.dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self.dialog.setObjectName("SimpleCADRoundEdges")
        self.dialog.setWindowTitle("Round edges")
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        layout = QtWidgets.QVBoxLayout(self.dialog)
        count = sum(len(indices) for _, _, indices in targets)
        layout.addWidget(QtWidgets.QLabel("%d sharp edge%s selected" % (count, "" if count == 1 else "s")))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Radius"))
        self.radius = QtWidgets.QLineEdit(self.dialog)
        self.radius.setObjectName("SimpleCADRoundRadius")
        self.radius.setPlaceholderText("For example 2 mm or 0.2 cm")
        row.addWidget(self.radius)
        layout.addLayout(row)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self.dialog)
        self.slider.setRange(0, 1000)
        layout.addWidget(self.slider)
        size = min(d for _, shape, indices in targets
                   for d in [shape.BoundBox.XLength, shape.BoundBox.YLength, shape.BoundBox.ZLength] +
                   [shape.Edges[i].Length for i in indices] if d > geo.EPS)
        self.slider_range = size * .45
        self.default_radius = min(1.0, size * .05)
        self.original = QtWidgets.QPushButton("Show original (radius 0)", self.dialog)
        self.original.setAutoDefault(False)
        self.original.clicked.connect(lambda: self.radius.setText("0 mm"))
        layout.addWidget(self.original)
        self.status = QtWidgets.QLabel(self.dialog)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.Apply)
        self.apply_button.setAutoDefault(False)
        self.apply_button.clicked.connect(self.apply)
        buttons.rejected.connect(controller.cancel)
        layout.addWidget(buttons)
        self.dialog.rejected.connect(controller.cancel)
        self.pending = QtCore.QTimer(self.dialog)
        self.pending.setSingleShot(True)
        self.pending.timeout.connect(self.update_preview)
        self.radius.textChanged.connect(self.changed)
        self.radius.returnPressed.connect(self.apply)
        self.slider.valueChanged.connect(self.slide)
        self.dialog.setMinimumWidth(340)

    def open(self):
        Gui.Selection.clearSelection()
        Gui.Selection.clearPreselection()
        self.radius.setText("%.6g mm" % self.default_radius)
        anchor_panel(self.dialog).show()
        self.update_preview()
        self.radius.setFocus()
        self.radius.selectAll()

    def changed(self, *unused):
        self.apply_button.setEnabled(False)
        self.pending.start(180)

    def slide(self, value):
        self.radius.setText("%.6g mm" % (self.slider_range * value / 1000))

    def update_preview(self):
        self.pending.stop()
        if self.closed:
            return False
        try:
            self.controller.check_context()
            if self.closed:
                return False
            ops.check_rounding(self.targets)
            radius = geo.parse_length(self.radius.text())
            if self.planned is None or radius != self.preview_radius:
                planned = ops.preview_rounding(self.targets, radius)
                self.preview.show(planned)
                self.planned, self.preview_radius = planned, radius
            self.slider.blockSignals(True)
            self.slider.setValue(round(radius / self.slider_range * 1000))
            self.slider.blockSignals(False)
            self.status.setStyleSheet("")
            self.status.setText("Original shape · nothing will change" if radius == 0 else
                                "Preview: %.6g mm · Apply to keep it · Esc cancels" % radius)
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
            changed = ops.commit_rounding(self.targets, self.planned, self.preview_radius)
            objects = [obj for obj, _ in self.planned]
            self.controller.cancel(quiet=True)
            if changed:
                Gui.Selection.clearSelection()
                for obj in objects:
                    Gui.Selection.addSelection(obj)
            self.controller.focus_view()
            self.controller.message("Edges rounded · Undo with ⌘Z" if changed else "Original sharp edges kept")
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
            ops.check_rounding(self.targets)
            if App.ActiveDocument == self.doc:
                for obj, names in self.selection:
                    for name in names or ("",):
                        Gui.Selection.addSelection(obj, name)
        except (ValueError, RuntimeError, ReferenceError):
            pass
