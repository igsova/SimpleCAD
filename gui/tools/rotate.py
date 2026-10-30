"""用于可撤销刚性旋转的轴线、基准点与旋转角度控制面板。"""
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
        self.dialog.setWindowTitle("旋转")
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        layout = QtWidgets.QVBoxLayout(self.dialog)
        is_edge_mode = any(getattr(t, "mode", "object") in ("edge", "face") for t in targets)
        self.is_edge_mode = is_edge_mode
        if is_edge_mode:
            count = sum(len(getattr(t, "elements", ())) for t in targets)
            layout.addWidget(QtWidgets.QLabel("%d 条线段 / 圆弧边已选中" % count))
        else:
            layout.addWidget(QtWidgets.QLabel("%d 个完整对象已选中" % len(targets)))
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)
        self.axis = QtWidgets.QComboBox(self.dialog)
        self.axis.setObjectName("SimpleCADRotateAxis")
        if is_edge_mode:
            self.axis.addItem("面 / 平面法线", "FaceNormal")
        for title, key in (("世界 X 轴", "X"), ("世界 Y 轴", "Y"), ("世界 Z 轴", "Z"),
                           ("对象主轴", "Main"), ("对象局部 X 轴", "LocalX"),
                           ("对象局部 Y 轴", "LocalY"), ("对象局部 Z 轴", "LocalZ")):
            self.axis.addItem(title, key)
        self.axis.setCurrentIndex(0 if is_edge_mode else 2)
        form.addRow("旋转轴", self.axis)
        self.pivot = QtWidgets.QComboBox(self.dialog)
        self.pivot.setObjectName("SimpleCADRotatePivot")
        self.pivot.setToolTip("“整体旋转”与“世界原点”使用单一共用旋转轴。对于对象轴，使用首个选中对象的轴线。")
        if is_edge_mode:
            self.pivot.addItem("曲线 / 孔中心", "CurveCenter")
            self.pivot.addItem("起点", "Start")
            self.pivot.addItem("终点", "End")
            self.pivot.addItem("所选内容中心", "Selection")
            self.pivot.addItem("世界原点 (0, 0, 0)", "Origin")
        else:
            for title, key in (("所选内容中心 — 整体旋转", "Selection"),
                               ("各自对象中心 — 分别旋转", "Each"), ("世界原点 (0, 0, 0)", "Origin")):
                self.pivot.addItem(title, key)
        form.addRow("旋转基准中心", self.pivot)
        self.angle = QtWidgets.QLineEdit("0°", self.dialog)
        self.angle.setObjectName("SimpleCADRotateAngle")
        self.angle.setPlaceholderText("例如 45° 或 -90°")
        form.addRow("旋转角度", self.angle)
        self.copy_check = QtWidgets.QCheckBox("保留原始对象 (创建旋转副本)", self.dialog)
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
            button = QtWidgets.QPushButton("%+d°" % degrees if degrees else "重置", self.dialog)
            button.setAutoDefault(False)
            button.clicked.connect(lambda unused=False, value=degrees: self.angle.setText("%d°" % value))
            presets.addWidget(button)
            self.presets[degrees] = button
        layout.addLayout(presets)
        self.note = QtWidgets.QLabel("世界坐标轴保持固定。对象局部轴随对象转动。\n输入负角度可向反方向旋转。")
        self.note.setWordWrap(True)
        self.note.setMaximumWidth(360)
        self.angle.setToolTip("默认单位为度 (°)；亦支持输入 rad 等角度单位。从旋转轴箭头末端朝中心看去，正角度为逆时针旋转。")
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
        # 旋转自身的轴向时，默认围绕各对象自身中心旋转
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
            self.status.setText("保持原始方向 · 几何未发生变化" if rotation.angle_degrees(angle) == 0 else
                                "预览：%.6g° · 点击“应用”保留 · 按 Esc 取消" % angle)
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
            msg = ("已旋转线条/圆弧 · 可按 Ctrl+Z / ⌘Z 撤销" if self.is_edge_mode else "已旋转对象 · 可按 Ctrl+Z / ⌘Z 撤销") if changed else "已保留原始方向"
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