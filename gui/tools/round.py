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
        self.dialog.setWindowTitle("倒圆角 (Round edges)")
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        layout = QtWidgets.QVBoxLayout(self.dialog)
        
        # 选中边数统计提示
        count = sum(len(indices) for _, _, indices in targets)
        layout.addWidget(QtWidgets.QLabel("已选中 %d 条尖锐边" % count))
        
        # 半径输入栏
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("圆角半径"))
        self.radius = QtWidgets.QLineEdit(self.dialog)
        self.radius.setObjectName("SimpleCADRoundRadius")
        self.radius.setPlaceholderText("例如 2 mm 或 0.2 cm")
        row.addWidget(self.radius)
        layout.addLayout(row)
        
        # 半径滑动条
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self.dialog)
        self.slider.setRange(0, 1000)
        layout.addWidget(self.slider)
        
        size = min(d for _, shape, indices in targets
                   for d in [shape.BoundBox.XLength, shape.BoundBox.YLength, shape.BoundBox.ZLength] +
                   [shape.Edges[i].Length for i in indices] if d > geo.EPS)
        self.slider_range = size * .45
        self.default_radius = min(1.0, size * .05)
        
        # 快捷复位按钮
        self.original = QtWidgets.QPushButton("显示原样 (半径为 0)", self.dialog)
        self.original.setAutoDefault(False)
        self.original.clicked.connect(lambda: self.radius.setText("0 mm"))
        layout.addWidget(self.original)
        
        # 动态状态提示文本
        self.status = QtWidgets.QLabel(self.dialog)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        
        # 应用 / 取消按钮
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.Apply)
        self.apply_button.setText("应用")
        self.apply_button.setAutoDefault(False)
        self.apply_button.clicked.connect(self.apply)
        
        cancel_button = buttons.button(QtWidgets.QDialogButtonBox.Cancel)
        cancel_button.setText("取消")
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
            self.status.setText("原始形状 · 不做任何修改" if radius == 0 else
                                "实时预览: %.6g mm · 点击【应用】保留 · 按 Esc 取消" % radius)
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
            self.controller.message("边缘倒角完成 · 按 Ctrl/⌘+Z 撤销" if changed else "已保留原始尖锐边")
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