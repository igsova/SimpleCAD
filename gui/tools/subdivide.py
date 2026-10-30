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
        self.dialog.setWindowTitle("细分面 (Subdivide face)")
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        icons = ROOT / "Resources" / "icons"
        self.dialog.setStyleSheet('QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("' +
                                  (icons / "spin-up.svg").as_posix() + '"); width: 10px; height: 10px; } '
                                  'QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("' +
                                  (icons / "spin-down.svg").as_posix() + '"); width: 10px; height: 10px; }')
        layout = QtWidgets.QVBoxLayout(self.dialog)
        layout.addWidget(QtWidgets.QLabel("%s · 表面%d" % (target[0].Label, target[2] + 1)))
        form = self.form = QtWidgets.QFormLayout(); layout.addLayout(form)
        self.profile = subdivision.Profile(target[1].Faces[target[2]])
        
        # 划分模式下拉框
        self.pattern = QtWidgets.QComboBox(self.dialog)
        self.pattern.setObjectName("SimpleCADSubdividePattern")
        if len(self.profile.convex_corners()) == 3:
            self.pattern.addItem("三角形划分", "triangles")
        if self.profile.convex_corners() or self.profile.is_disk():
            self.pattern.addItem("中心扇形放射", "fan")
        self.pattern.addItem("均匀等距网格", "spaced")
        self.pattern.addItem("等面积网格", "equal_area")
        self.pattern.setCurrentIndex(self.pattern.findData(self.profile.default_pattern()))
        form.addRow("划分模式", self.pattern)
        
        self.divisions = self.integer(form, "每边细分数", "PerSide", 3)
        self.fan_steps = 8 if self.profile.is_disk() else 1
        self.previous_pattern = "triangles"
        self.triangle_steps = 3
        
        # 网格设定依据
        self.mode = QtWidgets.QComboBox(self.dialog)
        self.mode.addItems(["总细分数", "行数与列数", "仅按行划分", "仅按列划分"])
        self.previous_mode = 0
        self.mode.setObjectName("SimpleCADSubdivideMode")
        form.addRow("设置依据", self.mode)
        
        self.total = self.integer(form, "细分数", "Total", 9)
        self.rows = self.integer(form, "行数", "Rows", 3)
        self.columns = self.integer(form, "列数", "Columns", 3)
        
        # 角度旋转
        self.angle = QtWidgets.QDoubleSpinBox(self.dialog)
        self.angle.setObjectName("SimpleCADSubdivideAngle")
        self.angle.setRange(-180, 180); self.angle.setDecimals(1)
        self.angle.setSingleStep(15); self.angle.setSuffix("°")
        self.angle.setKeyboardTracking(False)
        self.angle.setToolTip("0° 沿表面的最长直边排列。调整此角度可旋转表面上的网格方向。")
        form.addRow("网格角度", self.angle)
        
        # 模式解释说明框
        note = self.note = QtWidgets.QLabel()
        note.setWordWrap(True); note.setMaximumWidth(360)
        layout.addWidget(note)
        
        # 状态描述
        self.status = QtWidgets.QLabel(self.dialog)
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(self.status.fontMetrics().lineSpacing() * 3)
        layout.addWidget(self.status)
        
        # 按钮栏
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.Apply)
        self.apply_button.setText("应用")
        self.apply_button.setAutoDefault(False)
        self.apply_button.clicked.connect(self.apply)
        
        cancel_btn = buttons.button(QtWidgets.QDialogButtonBox.Cancel)
        cancel_btn.setText("取消")
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
        self.form.labelForField(self.angle).setText("起始角度" if pattern == "fan" else "网格角度")
        self.form.labelForField(self.divisions).setText("扇区数" if pattern == "fan" and self.profile.is_disk() else "每边细分数")
        self.mode.setItemText(0, "网格单元总数" if pattern == "spaced" else "总细分数")
        self.form.labelForField(self.total).setText("网格单元数" if pattern == "spaced" else "细分数")
        self.note.setText({
            "triangles": "沿三边以更小的三角形细分。每边 2 等分生成 4 个三角形；每边 3 等分生成 9 个。",
            "fan": ("绕圆心按等角度划分扇区。" if self.profile.is_disk() else
                    "连接中心到每个角点，然后细分各个三角形。这可保留轮廓对称性；不规则多边形各部分面积可能不同。"),
            "spaced": "等间距分隔。选择【仅按行划分】或【仅按列划分】可生成条带。边界轮廓处的面片可能较小或为空；预览显示实际生成的面数。",
            "equal_area": "每个细分面片面积相等。分割间距自适应轮廓外形，各区域宽度和形状可能略有不同。"
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
            layout = ("每边 %d 等分" % divisions if pattern == "triangles" else
                      "%d 个扇区" % divisions if pattern == "fan" and self.profile.is_disk() else
                      "三角形每边 %d 等分" % divisions if pattern == "fan" else
                      "%d 行 × %d 列" % (rows, columns))
            areas = [f.Area for f in self.regions]
            area = ("每面 %.6g mm²" % areas[0] if max(areas) - min(areas) < max(1e-7, max(areas) * 1e-7) else
                    "面积不等 · 等间距划分" if pattern == "spaced" else "自适应轮廓面积划分")
            self.status.setStyleSheet("")
            self.status.setText("单面 · 未生成新细分" if count == 1 else
                                "生成 %d 个表面 · %s\n%s\n点击【应用】保留 · 按 Esc 取消" % (count, layout, area))
            self.apply_button.setEnabled(True)
            return True
        except Exception as error:
            self.planned = None; self.preview.clear()
            self.status.setStyleSheet("color: #e78f70;")
            self.status.setText(str(error)); self.apply_button.setEnabled(False)
            return False

    def apply(self):
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
            self.controller.message("已细分为 %d 个面 · 点击任意区域即可直接推拉 · 按 Ctrl/⌘+Z 撤销" % count
                                    if changed else "保留原表面不变")
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