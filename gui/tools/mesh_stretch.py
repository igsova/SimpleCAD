"""基于双截面的网格拉伸与形变编辑，具备索引缓存预览与独立的应用生成机制。"""
import numpy as np
import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin

from ...jobs import mesh as mesh_jobs
from ...mesh import slicing as mesh_slicing, stretch as mesh_stretch
from ...mesh.conversion import cached_fingerprints
from ...mesh.transform import Plan
from ..previews.shaded import RoundPreview, NativeMask
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel


def fill(field, values, dtype=np.float32):
    """使用指定值替换 Coin 多值字段。

    传入 NumPy 数组可避免为每个坐标创建 Python 对象：
    在密集网格上，这些列表还会触发 FreeCAD 进程的全量垃圾回收，其开销远高于数据复制本身。
    """
    values = np.ascontiguousarray(values, dtype=dtype)
    field.setNum(len(values))
    if not len(values):
        return
    try:
        field.setValues(0, len(values), values)
    except (TypeError, ValueError, NotImplementedError):
        # 未配置 NumPy 类型映射的 Pivy 仅接受 Python 序列
        field.setValues(values.tolist())


class StretchPreview(RoundPreview):
    def __init__(self, view, source):
        super().__init__(view)
        self.source, self.key, self.topology = source, None, None
        self.marked, self.painted = (), None
        self.node = coin.SoSeparator()
        hints = coin.SoShapeHints(); hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        self.node.addChild(hints)
        self.material = coin.SoMaterial(); self.node.addChild(self.material)
        binding = coin.SoMaterialBinding(); binding.value = coin.SoMaterialBinding.PER_FACE
        self.node.addChild(binding)
        self.coords = coin.SoCoordinate3(); self.node.addChild(self.coords)
        self.faces = coin.SoIndexedFaceSet(); self.node.addChild(self.faces)
        self.guide = coin.SoSeparator(); self.root.addChild(self.guide)

    def show(self, plan, points):
        self.show_mesh(plan.triangles, plan.weights, points, plan)

    def show_mesh(self, triangles, weights, points, key):
        # Coin 的 setValues 仅替换前缀内容。收缩/清除或从“挤出”切换到“移动”时还必须丢弃废弃的侧壁与封顶顶点。
        # 当索引和坐标尚未同步完成时，暂时禁用场景图通知。
        notify = self.node.enableNotify(False)
        try:
            topology_changed = self.topology is not triangles
            if topology_changed:
                faces = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
                fill(self.faces.coordIndex, np.column_stack((faces, np.full(len(faces), -1))).ravel(), np.int32)
                self.topology = triangles
            if self.key is not key or topology_changed or len(self.marked):
                self.marked = ()
                self.paint(triangles, weights)
                self.key = key
            fill(self.coords.point, points)
        finally:
            self.node.enableNotify(notify)
            if notify: self.node.touch()
        if not self.masks:
            self.masks.append(NativeMask(self.source)); self.models.addChild(self.node)
        self.view.redraw()

    def paint(self, triangles, weights):
        self.painted = (triangles, weights)
        weight = weights[triangles].mean(axis=1)
        colors = np.column_stack((.3 + .65 * weight, .7 - .25 * weight, .85 - .6 * weight))
        if len(self.marked):
            colors[self.marked] = (.9, .08, .08)
        fill(self.material.diffuseColor, colors)

    def mark(self, triangles):
        """在预览中将这些三角形高亮为红色（例如预测发生碰撞/自交的区域）。"""
        triangles = np.asarray(triangles, dtype=np.int64)
        if not len(triangles) and not len(self.marked):
            return
        if self.painted is None:
            return
        notify = self.node.enableNotify(False)
        try:
            self.marked = triangles
            self.paint(*self.painted)
        finally:
            self.node.enableNotify(notify)
            if notify: self.node.touch()
        self.view.redraw()

    def clear_model(self):
        # 即使旋转使截面超出网格或缩短形变无效，也保留控制手柄显示，以便用户拖回有效位置
        super().clear()

    def clear(self):
        super().clear()
        self.guide.removeAllChildren()


class MeshStretchSession:
    def __init__(self, controller, source):
        mesh_stretch.check_source(source)
        self.controller, self.source = controller, source
        self.original = cached_fingerprints.refresh(source)
        self.placement = App.Placement(source.Placement)
        self.closed, self.job, self.plan, self.plan_key = False, None, None, None
        self.planes = {}
        self.points, self.triangles = source.Mesh.Topology
        self.points = np.asarray([tuple(p) for p in self.points])
        self.triangles = np.asarray(self.triangles, dtype=np.int64)
        self.preview = StretchPreview(controller.view, source)
        self.dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self.dialog.setObjectName('SimpleCADMeshStretch')
        self.dialog.setWindowTitle('拉伸网格 / 移动区域')
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        layout = QtWidgets.QVBoxLayout(self.dialog)
        layout.addWidget(QtWidgets.QLabel('%s · %s 个三角面片' % (source.Label, format(len(self.triangles), ','))))
        self.form = QtWidgets.QFormLayout(); layout.addLayout(self.form)
        self.mode = QtWidgets.QComboBox(); self.mode.addItems(['沿轴向拉伸', '平移末端区域 (XYZ)'])
        self.form.addRow('操作模式', self.mode)
        self.axis = QtWidgets.QComboBox()
        for label, key in [('对象主轴', 'Main'), ('世界 X 轴', 'X'), ('世界 Y 轴', 'Y'), ('世界 Z 轴', 'Z'),
                           ('对象局部 X 轴', 'LocalX'), ('对象局部 Y 轴', 'LocalY'), ('对象局部 Z 轴', 'LocalZ')]:
            self.axis.addItem(label, key)
        self.form.addRow('基准轴', self.axis)
        row = QtWidgets.QWidget(); angles_layout = QtWidgets.QHBoxLayout(row); angles_layout.setContentsMargins(0, 0, 0, 0)
        self.rotation = []
        for label in 'XYZ':
            widget = QtWidgets.QDoubleSpinBox(); widget.setDecimals(2); widget.setRange(-180, 180)
            widget.setSuffix('°'); widget.setPrefix(label + ' '); widget.setKeyboardTracking(False)
            widget.setToolTip('围绕公共原点旋转两个截面（依次绕世界坐标系 X、Y、Z 轴旋转）。双截面间距保持不变。')
            widget.setAccessibleName('截面旋转 ' + label)
            widget.valueChanged.connect(self.orientation_changed)
            angles_layout.addWidget(widget); self.rotation.append(widget)
        self.form.addRow('截面旋转角度', row)
        self.mouse_mode = QtWidgets.QComboBox(); self.mouse_mode.addItems(['移动截面', '旋转双截面'])
        self.form.addRow('视图拖动模式', self.mouse_mode)
        self.mouse_mode.currentIndexChanged.connect(self.changed)
        self.lower = self.spin('第一平面', 0)
        self.upper = self.spin('第二平面', 1)
        self.reverse = QtWidgets.QCheckBox('改动负方向一侧 (反转移动端)'); self.form.addRow(self.reverse)
        self.distance = self.spin('长度变化量', 0)
        self.delta = [self.spin('平移 ' + name + ' 轴', 0) for name in 'XYZ']
        self.note = QtWidgets.QLabel('在视图中拖动截面框线或文字手柄即可定位截面。切换到“旋转双截面”可拖动 X/Y/Z 圆环手柄；按住 Shift 键吸附到 15° 步长。数值输入框将保持同步。\n'
                                     '截面位置是沿旋转后的基准轴自公共原点测量的。\n'
                                     '蓝色区域保持固定；橙色区域整体移动。仅两个截面之间的区域会被拉伸形变。\n'
                                     '请将开孔、安装位等结构保持在双截面之外，以防止其发生尺寸拉伸形变。')
        self.note.setWordWrap(True); layout.addWidget(self.note)
        self.status = QtWidgets.QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.progress = QtWidgets.QProgressBar(); self.progress.setRange(0, 0); self.progress.hide(); layout.addWidget(self.progress)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.Apply)
        self.apply_button.setAutoDefault(False); self.apply_button.clicked.connect(self.apply)
        buttons.rejected.connect(controller.cancel); self.dialog.rejected.connect(controller.cancel); layout.addWidget(buttons)
        self.pending = QtCore.QTimer(self.dialog); self.pending.setSingleShot(True); self.pending.timeout.connect(self.update_preview)
        self.poller = QtCore.QTimer(self.dialog); self.poller.setInterval(150); self.poller.timeout.connect(self.poll)
        self.axis.currentIndexChanged.connect(self.axis_changed)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.reverse.toggled.connect(self.changed)
        from .mesh_handles import PlaneHandles
        self.handles = PlaneHandles(self)
        self.dialog.setMinimumWidth(430)

    def spin(self, label, value):
        widget = QtWidgets.QDoubleSpinBox(); widget.setDecimals(4); widget.setRange(-1e6, 1e6)
        widget.setSuffix(' mm'); widget.setValue(value); widget.setKeyboardTracking(False)
        widget.valueChanged.connect(self.changed); self.form.addRow(label, widget)
        return widget

    def open(self):
        Gui.Selection.clearSelection(); Gui.Selection.clearPreselection()
        self.axis_changed(); self.mode_changed(); anchor_panel(self.dialog).show(); self.update_preview()

    def check(self):
        mesh_stretch.check_source(self.source)
        if (cached_fingerprints.get(self.source) != self.original
                or not self.source.Placement.isSame(self.placement)):
            raise ValueError('原始网格已改变，请重新启动【拉伸网格】。')

    def axis_changed(self, *unused):
        key = self.axis.currentData()
        if key not in self.planes:
            self.planes[key] = mesh_slicing.plane(self.source.Mesh, key)
        self.base_plane = self.plane = self.planes[key]
        for widget in self.rotation:
            widget.blockSignals(True); widget.setValue(0); widget.blockSignals(False)
        span = self.plane.upper - self.plane.lower
        for widget, level in ((self.lower, self.plane.lower + span / 3), (self.upper, self.plane.upper - span / 3)):
            widget.blockSignals(True); widget.setValue(level); widget.blockSignals(False)
        self.changed()

    def angles(self):
        return [widget.value() for widget in self.rotation]

    def orientation_changed(self, *unused):
        if not hasattr(self, 'base_plane'):
            return
        self.plane = mesh_stretch.orient_plane(self.base_plane, self.points, self.angles())
        self.changed()

    def mode_changed(self, *unused):
        for widget in [self.distance] + self.delta:
            visible = (self.mode.currentIndex() == 0) == (widget is self.distance)
            widget.setVisible(visible); self.form.labelForField(widget).setVisible(visible)
        self.changed()

    def movement(self):
        if self.mode.currentIndex() == 0:
            return np.asarray(tuple(self.plane.normal)) * self.distance.value() * (-1 if self.reverse.isChecked() else 1)
        return np.asarray([w.value() for w in self.delta])

    def values(self):
        values = dict(axis=self.axis.currentData(), rotation=self.angles(), lower=self.lower.value(),
                      upper=self.upper.value(), reverse=self.reverse.isChecked())
        if self.mode.currentIndex() == 0:
            values['distance'] = self.distance.value()
        else:
            values['delta'] = [w.value() for w in self.delta]
        return values

    def changed(self, *unused):
        if not hasattr(self, 'pending') or self.closed:
            return
        self.apply_button.setEnabled(False)
        if self.job:
            self.job.cancel(); self.job = None
        self.poller.stop(); self.progress.hide()
        if hasattr(self, 'plane') and self.handles.drag is None:
            self.handles.render()
        # 持续交互操作应以有限频率渲染，避免每个事件都重启防抖定时器导致预览无限期推迟
        if not self.pending.isActive():
            self.pending.start(35)

    def update_preview(self):
        self.pending.stop()
        if self.closed:
            return False
        try:
            self.check()
            self.handles.render()
            lower, upper = self.lower.value(), self.upper.value()
            delta = self.movement()
            if self.handles.drag is not None:
                if upper - lower < 1e-5:
                    raise ValueError('第二平面的位置必须高于第一平面。')
                if 1 + (-1 if self.reverse.isChecked() else 1) * float(delta @ tuple(self.plane.normal)) / (upper - lower) < 1e-4:
                    raise ValueError('该移动量会导致中间截面坍缩重叠。请减小压缩/缩短量。')
                weights = np.clip(((self.points - tuple(self.plane.center)) @ tuple(self.plane.normal) - lower) / (upper - lower), 0, 1)
                if self.reverse.isChecked(): weights = 1 - weights
                self.preview.show_mesh(self.triangles, weights, self.points + weights[:, None] * delta, object())
                self.status.setText('松开鼠标以生成精细预览 · 两个截面将保持相互平行。')
                self.apply_button.setEnabled(False)
                return True
            key = (self.axis.currentData(), tuple(self.angles()), lower, upper, self.reverse.isChecked())
            if key != self.plan_key:
                self.plan = Plan(self.points, self.triangles, tuple(self.plane.center), tuple(self.plane.normal),
                                 lower, upper, self.reverse.isChecked())
                self.plan_key = key
            points = self.plan.transform(delta)
            self.preview.show(self.plan, points)
            status = '预览中包含 %s 个三角面片 · 应用后原始网格将作为隐藏备份保留。' % format(len(self.plan.triangles), ',')
            if self.plan.degenerate_before:
                status += '\n将保留原始网格中预存的 %d 个退化三角形。' % self.plan.degenerate_before
            self.status.setText(status)
            self.apply_button.setEnabled(float(np.linalg.norm(delta)) >= 1e-9)
            return True
        except (ValueError, RuntimeError, ReferenceError) as error:
            self.preview.clear_model(); self.status.setText(str(error)); self.apply_button.setEnabled(False)
            return False

    def apply(self):
        if not self.update_preview() or not self.apply_button.isEnabled():
            return
        try:
            self.job = mesh_jobs.start_stretch(self.source, **self.values())
            self.apply_button.setEnabled(False); self.progress.show(); self.poller.start()
            self.status.setText('正在后台校验拉伸结果…')
        except (ValueError, RuntimeError) as error:
            self.status.setText(str(error))

    def poll(self):
        if self.closed or not self.job:
            return
        state = self.job.status(); self.status.setText(state['error'] or state['stage'])
        if state['status'] == 'running':
            return
        self.poller.stop(); self.progress.hide()
        if state['status'] != 'ready':
            return
        try:
            self.check(); self.preview.clear(); self.job.apply()
            self.controller.cancel(quiet=True); self.controller.faces.refresh()
            self.controller.message('网格拉伸已应用 · 原始网格已隐藏备份 · 撤销可恢复')
        except (ValueError, RuntimeError) as error:
            self.job.cancel(); self.status.setText(str(error))

    def close(self):
        if self.closed:
            return
        self.closed = True; self.pending.stop(); self.poller.stop()
        self.handles.close()
        if self.job:
            self.job.cancel()
        self.preview.close(); self.dialog.hide(); self.dialog.deleteLater()