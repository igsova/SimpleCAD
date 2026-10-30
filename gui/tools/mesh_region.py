"""拾取相连的网格面片，实时预览移动、旋转或挤出效果。"""
import numpy as np
import FreeCAD as App
import FreeCADGui as Gui
from concurrent.futures import ThreadPoolExecutor
from ...mesh import collisions as mesh_collisions, region_edit as mesh_region_edit
from ...jobs import mesh as mesh_jobs
from ...mesh.region import RegionPlan
from ...mesh.stretch import check_source
from .mesh_stretch import StretchPreview
from ...mesh.conversion import cached_fingerprints
from ..snapping import ray
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel

# 使用单个后台线程通过 NumPy 评估预览碰撞，保证在密集网格上输入数值或拾取面片时界面依然流畅。
_collisions = ThreadPoolExecutor(max_workers=1, thread_name_prefix='SimpleCADMeshCollisions')


class MeshRegionSession:
    def __init__(self, controller, source):
        check_source(source)
        self.controller, self.source = controller, source
        self.original, self.topology = mesh_region_edit.snapshot(source)
        self.placement = App.Placement(source.Placement)
        self.selected = set(); self.plan = self.plan_key = self.job = self.press = None
        self.closed = False
        self.validation_error = ''
        self.color_keys = {}
        self.preview = StretchPreview(controller.view, source)
        self.shown_points, self.shown_faces = self.topology.points, self.topology.triangles
        self.origins = np.arange(len(self.shown_faces))
        self.dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self.dialog.setObjectName('SimpleCADMeshRegion')
        self.dialog.setWindowTitle('网格局部编辑 · 移动 / 旋转 / 挤出')
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        layout = QtWidgets.QVBoxLayout(self.dialog)
        layout.addWidget(QtWidgets.QLabel('%s · %s 个三角面片' % (source.Label, format(len(self.topology.triangles), ','))))
        self.form = QtWidgets.QFormLayout(); layout.addLayout(self.form)
        self.selection = self.combo('选择面片类型', [('平整面片', 'Flat'), ('光滑曲面片', 'Smooth'), ('单个三角形', 'Triangle')])
        self.crease = self.spin('光滑折痕阈值角', 15, 0, 90, '°')
        self.action = self.combo('拾取动作', [('替换选择', 'Replace'), ('添加到选择', 'Add'), ('从选择中移除', 'Remove')])
        self.selection_count = QtWidgets.QLabel()
        self.selection_count.setObjectName('SimpleCADMeshRegionSelectionCount')
        layout.addWidget(self.selection_count)
        self.selection_buttons = []
        buttons = QtWidgets.QHBoxLayout(); layout.addLayout(buttons)
        for title, action in [('扩大选择', lambda: self.grow(1)), ('收缩选择', lambda: self.grow(-1)), ('清空选择', self.clear)]:
            button = QtWidgets.QPushButton(title); button.clicked.connect(action); buttons.addWidget(button)
            self.selection_buttons.append(button)
        self.mode = self.combo('操作模式', [('平移', 'Move'), ('旋转', 'Rotate'), ('挤出', 'Extrude')])
        self.rings = QtWidgets.QSpinBox(); self.rings.setRange(1, 30); self.rings.setValue(1)
        self.rings.setToolTip('平移/旋转影响逐渐衰减到零的相连顶点环数。选中的面片将作为整体刚性移动。')
        self.form.addRow('过渡渐变环数', self.rings); self.rings.valueChanged.connect(self.changed)
        self.delta = [self.spin('平移 ' + axis + ' 轴', 0) for axis in 'XYZ']
        self.direction = self.combo('方向 / 旋转轴', [('区域平均法线', 'Region normal'), ('世界 X 轴', 'World X'), ('世界 Y 轴', 'World Y'), ('世界 Z 轴', 'World Z')])
        self.angle = self.spin('旋转角度', 0, -180, 180, '°')
        self.distance = self.spin('挤出距离', 0)
        self.custom_pivot = QtWidgets.QCheckBox('使用自定义旋转中心'); self.form.addRow(self.custom_pivot)
        self.pivot = [self.spin('旋转中心 ' + axis, 0) for axis in 'XYZ']
        note = QtWidgets.QLabel('在视图中点击表面即可选择其相连面片。使用“添加到选择/移除”或按住 Shift 点击可组合多个面片。'
                                '“扩大/收缩选择”可微调边界。橙色为选中区域；蓝色保持固定；中间渐变色表示平滑过渡带。\n'
                                '平移和旋转将带动相邻过渡环平滑形变。挤出将生成封闭侧壁（包括孔洞边缘）。\n'
                                '点击“应用”将在后台自动检测自相交，并将原始网格作为隐藏备份保留。')
        note.setWordWrap(True); layout.addWidget(note)
        self.status = QtWidgets.QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.progress = QtWidgets.QProgressBar(); self.progress.setRange(0, 0); self.progress.hide(); layout.addWidget(self.progress)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = box.button(QtWidgets.QDialogButtonBox.Apply); self.apply_button.setAutoDefault(False)
        self.apply_button.clicked.connect(self.apply); box.rejected.connect(controller.cancel)
        self.dialog.rejected.connect(controller.cancel); layout.addWidget(box)
        self.pending = QtCore.QTimer(self.dialog); self.pending.setSingleShot(True); self.pending.timeout.connect(self.update_preview)
        self.collision = None
        self.collision_timer = QtCore.QTimer(self.dialog); self.collision_timer.setSingleShot(True)
        self.collision_timer.timeout.connect(self.check_collisions)
        self.collision_poller = QtCore.QTimer(self.dialog); self.collision_poller.setInterval(40)
        self.collision_poller.timeout.connect(self.collisions_ready)
        self.poller = QtCore.QTimer(self.dialog); self.poller.setInterval(150); self.poller.timeout.connect(self.poll)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.custom_pivot.toggled.connect(self.mode_changed)
        self.dialog.setMinimumWidth(430)

    def combo(self, label, items):
        widget = QtWidgets.QComboBox()
        for item in items:
            if isinstance(item, tuple):
                title, key = item
            else:
                title, key = item, item
            widget.addItem(title, key)
        self.form.addRow(label, widget)
        widget.currentIndexChanged.connect(self.changed)
        return widget

    def spin(self, label, value, low=-1e6, high=1e6, suffix=' mm'):
        widget = QtWidgets.QDoubleSpinBox(); widget.setRange(low, high); widget.setDecimals(4)
        widget.setValue(value); widget.setSuffix(suffix); widget.setKeyboardTracking(False)
        self.form.addRow(label, widget); widget.valueChanged.connect(self.changed)
        return widget

    def open(self):
        Gui.Selection.clearSelection(); Gui.Selection.clearPreselection()
        self.mode_changed(); anchor_panel(self.dialog).show(); self.update_preview()

    def check(self):
        check_source(self.source)
        if cached_fingerprints.get(self.source) != self.original or not self.source.Placement.isSame(self.placement):
            raise ValueError('原始网格已改变，请重新启动【网格局部编辑】。')

    def mode_changed(self, *unused):
        mode = self.mode.currentData()
        fields = [(w, mode == 'Move') for w in self.delta]
        fields += [(self.direction, mode != 'Move'), (self.angle, mode == 'Rotate'),
                   (self.distance, mode == 'Extrude'), (self.rings, mode != 'Extrude')]
        fields += [(w, mode == 'Rotate' and self.custom_pivot.isChecked()) for w in self.pivot]
        for widget, show in fields:
            widget.setVisible(show); self.form.labelForField(widget).setVisible(show)
        self.custom_pivot.setVisible(mode == 'Rotate')
        self.changed()

    def values(self):
        index = self.direction.currentIndex()
        return dict(mode=self.mode.currentData(), rings=self.rings.value(), delta=[w.value() for w in self.delta],
                    axis=None if index == 0 else np.eye(3)[index - 1].tolist(), angle=self.angle.value(),
                    distance=self.distance.value(), pivot=[w.value() for w in self.pivot] if self.custom_pivot.isChecked() else None)

    def changed(self, *unused):
        if not hasattr(self, 'pending') or self.closed: return
        self.validation_error = ''
        self.update_selection_feedback()
        self.apply_button.setEnabled(False)
        if self.job: self.job.cancel(); self.job = None
        self.poller.stop(); self.progress.hide()
        self.stop_collision_check()
        if not self.pending.isActive(): self.pending.start(35)

    def update_selection_feedback(self):
        count = len(self.selected)
        self.selection_count.setText('已选择 %s 个三角面片' % format(count, ','))
        for button in self.selection_buttons:
            button.setEnabled(bool(count))
        self.crease.setEnabled(self.selection.currentData() == 'Smooth')

    def pick_hint(self):
        if self.action.currentData() == 'Remove':
            return '当前未选中任何面片。请切换为“替换选择”或“添加到选择”，然后在视图中点击网格表面。'
        patch = {'Flat': '平整面片', 'Smooth': '光滑曲面片', 'Triangle': '单个三角形'}[self.selection.currentData()]
        return '点击网格表面以选择 %s。所选区域将高亮显示为橙色。' % patch

    def pick_feedback(self, message):
        # 未点中或重新选择时保留之前拒绝的参数原因，直到用户实际修改编辑参数
        self.status.setText(self.validation_error or message)

    def reject(self, message):
        self.validation_error = message
        self.status.setText(message)
        self.apply_button.setEnabled(False)

    def grow(self, amount):
        self.selected = self.topology.grow(self.selected, amount); self.changed()

    def clear(self):
        self.selected.clear(); self.changed()

    def update_preview(self):
        self.pending.stop()
        if self.closed: return False
        self.update_selection_feedback()
        try:
            self.check()
            if not self.selected:
                self.shown_points, self.shown_faces = self.topology.points, self.topology.triangles
                self.origins = np.arange(len(self.shown_faces))
                self.preview.show_mesh(self.shown_faces, np.zeros(len(self.shown_points)), self.shown_points, self.topology)
                self.status.setText(self.pick_hint()); self.apply_button.setEnabled(False)
                return False
            key = (frozenset(self.selected), self.rings.value())
            if self.plan_key != key:
                self.plan = RegionPlan(self.topology, self.selected, self.rings.value()); self.plan_key = key
                self.color_keys = {name: object() for name in ('Move', 'Rotate', 'Extrude', 'invalid')}
            values = self.values(); values.pop('rings')
            try:
                points, faces = self.plan.transform(**values)
                self.plan.validate(points, faces, values['mode'])
            except ValueError:
                # 即使输入参数暂不可用（如挤出距离为0），也显示当前选择区域，避免残留旧的高亮面片
                self.stop_collision_check()
                self.shown_points, self.shown_faces = self.topology.points, self.topology.triangles
                self.origins = np.arange(len(self.shown_faces))
                self.preview.show_mesh(self.shown_faces, self.plan.weights, self.shown_points, self.color_keys['invalid'])
                raise
            weights = self.plan.weights
            self.origins = np.arange(len(faces))
            if values['mode'] == 'Extrude':
                weights = np.r_[np.zeros(len(self.topology.points)), np.ones(len(self.plan.vertices))]
                keep = np.ones(len(self.topology.triangles), dtype=bool); keep[self.plan.selected] = False
                self.origins = np.r_[np.flatnonzero(keep), self.plan.selected, np.full(2 * len(self.plan.boundary), -1)]
            self.shown_points, self.shown_faces = points, faces
            self.preview.show_mesh(faces, weights, points, self.color_keys[values['mode']])
            changed = values['mode'] == 'Extrude' or np.max(np.linalg.norm(points - self.topology.points, axis=1)) > 1e-9
            self.apply_button.setEnabled(bool(changed))
            self.summary_text = '已选 %s 个三角形 · %s 个过渡渐变顶点' % (
                format(len(self.selected), ','), format(self.plan.summary()['transition_vertices'] if values['mode'] != 'Extrude' else 0, ','))
            if not changed:
                self.status.setText(self.summary_text + ' · 请输入位移、旋转角度或挤出距离。')
            else:
                self.status.setText(self.summary_text + ' · 正在检查预览网格是否存在相交碰撞…')
                self.stop_collision_check(); self.collision_timer.start(120)
            return bool(changed)
        except (ValueError, RuntimeError, ReferenceError) as error:
            self.reject(str(error)); return False

    def stop_collision_check(self):
        self.collision_timer.stop(); self.collision_poller.stop()
        if self.collision is not None and self.collision[2] is not None:
            # 队列中被替换的预览检查将被取消
            self.collision[2].cancel()
        self.collision = None

    def check_collisions(self):
        """对当前预览启动碰撞预估计算。"""
        if self.closed: return
        points, faces = self.shown_points, self.shown_faces
        candidates = mesh_collisions.changed_triangles(self.topology.points, points, self.topology.triangles, faces)
        if len(candidates) > mesh_collisions.PREVIEW_LIMIT:
            self.collision = (points, faces, None, None); self.show_collisions(); return
        future = _collisions.submit(mesh_collisions.find, points, faces, candidates)
        self.collision = (points, faces, future, None); self.collision_poller.start()

    def collisions_ready(self):
        if self.collision is None or self.closed:
            self.collision_poller.stop(); return
        points, faces, future, found = self.collision
        if not future.done(): return
        self.collision_poller.stop()
        try:
            found = future.result()
        except Exception as error:  # 仅作参考；点击“应用”时会执行原生底层校验
            App.Console.PrintWarning('SimpleCAD 网格预览碰撞检查: %s\n' % error)
            found = None
        if points is not self.shown_points or faces is not self.shown_faces:
            return  # 此时已有更新的预览替代了该计算
        self.collision = (points, faces, future, found); self.show_collisions()

    def show_collisions(self):
        found = self.collision[3] if self.collision else None
        future = self.collision[2] if self.collision else None
        if future is None and self.collision is not None:
            note = '修改范围较大：点击“应用”时将执行完整碰撞检查。'
        elif found is None:
            note = '点击“应用”时将执行碰撞检查。'
        elif len(found):
            note = ('红色区域：有 %s 个三角形与网格其他部分发生相交碰撞。点击“应用”时的完整检查预计将拒绝此操作。'
                    '请减小位移/挤出量、修改选择面片或调整过渡环数。' % format(len(found), ','))
        else:
            note = '预览中未检测到自交碰撞；点击“应用”将执行完整校验。'
        self.preview.mark(found if found is not None and len(found) else ())
        if self.job is None:
            self.status.setText(getattr(self, 'summary_text', '') + ' · ' + note)

    def show_failed_triangles(self, triangles):
        """标记后台校验拒绝的三角形面片。"""
        triangles = np.asarray(triangles, dtype=np.int64)
        if len(triangles) and triangles.max() < len(self.shown_faces):
            self.preview.mark(triangles)

    def handle_event(self, widget, event):
        if self.closed or self.controller.selection.replaying: return False
        kind = event.type()
        if kind not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease):
            return False
        if not isinstance(widget, QtWidgets.QWidget):
            return False
        if not self.controller.selection.is_viewport(widget):
            self.press = None
            return False
        navigation = (event.modifiers() & (QtCore.Qt.AltModifier | QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier)
                      or event.buttons() & (QtCore.Qt.MiddleButton | QtCore.Qt.RightButton))
        if navigation:
            if self.press is not None and self.press[0] is widget:
                self.controller.selection.replay(widget, (self.press[3],))
            self.press = None
            return False
        width, height = self.controller.view.getSize(); p = event.localPos()
        logical = np.asarray((p.x(), p.y()))
        pos = np.asarray((p.x() * width / widget.width(), height - p.y() * height / widget.height()))
        if kind == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            original = (kind, p, event.globalPos(), event.button(), event.buttons(), event.modifiers())
            self.press = (widget, logical, False, original)
            widget.setFocus(QtCore.Qt.MouseFocusReason)
            return True
        if self.press is None: return False
        owner, down, dragged, original = self.press
        if owner is not widget: self.press = None; return False
        if kind == QtCore.QEvent.MouseMove:
            dragged = dragged or np.linalg.norm(logical - down) >= QtWidgets.QApplication.startDragDistance()
            self.press = (owner, down, dragged, original); return True
        if kind == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            self.press = None
            if not dragged:
                self.check(); origin, direction = ray(self.controller.view, pos)
                hit = self.topology.pick(tuple(origin), tuple(direction), self.shown_points, self.shown_faces)
                if hit is None:
                    self.pick_feedback('该位置未拾取到网格面片。请点击可见的网格表面。')
                elif self.origins[hit] < 0:
                    self.pick_feedback('请点击原始表面或橙色端面以修改选择。')
                else:
                    region = self.topology.region(int(self.origins[hit]) + 1, self.selection.currentData(), self.crease.value())
                    action = 'Add' if event.modifiers() & QtCore.Qt.ShiftModifier else self.action.currentData()
                    selected = (self.selected | region if action == 'Add' else self.selected - region if action == 'Remove' else region)
                    if selected == self.selected:
                        message = ('该面片未被选中。请切换为“替换选择”或“添加到选择”以选中它。' if action == 'Remove'
                                   else '该面片已在选择中。请输入位移、旋转角度或挤出距离。')
                        self.pick_feedback(message)
                    else:
                        self.selected = selected
                        self.changed()
            return True
        return False

    def apply(self):
        if not self.update_preview(): return
        try:
            self.job = mesh_jobs.start_region(self.source, triangles=[int(i) + 1 for i in sorted(self.selected)], **self.values())
            self.apply_button.setEnabled(False); self.progress.show(); self.poller.start()
            self.status.setText('正在后台校验修改后的网格…')
        except (ValueError, RuntimeError) as error: self.reject(str(error))

    def poll(self):
        if self.closed or self.job is None: return
        state = self.job.status(); self.status.setText(state['error'] or state['stage'])
        if state['status'] == 'running': return
        self.poller.stop(); self.progress.hide()
        if state['status'] != 'ready':
            self.reject(state['error'] or state['stage'])
            self.show_failed_triangles(getattr(self.job, 'failed_triangles', ()))
            return
        try:
            self.check(); self.preview.clear(); self.job.apply()
            warnings = self.job.report.get('warnings', [])
            for warning in warnings:
                App.Console.PrintWarning('SimpleCAD 网格局部编辑: ' + warning + '\n')
            self.controller.cancel(quiet=True); self.controller.faces.refresh()
            self.controller.message('网格局部编辑已应用 · 原始网格已隐藏备份 · 撤销可恢复'
                                    + (' · ' + warnings[0] if warnings else ''))
        except (ValueError, RuntimeError) as error:
            self.job.cancel(); self.reject(str(error))

    def close(self):
        if self.closed: return
        self.closed = True; self.pending.stop(); self.poller.stop(); self.press = None
        self.stop_collision_check()
        if self.job: self.job.cancel()
        self.preview.close(); self.dialog.hide(); self.dialog.deleteLater()