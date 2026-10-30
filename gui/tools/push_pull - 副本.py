"""Interactive Push/Pull dialog and input session for exact distance and direction selection."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from ...core import geometry as g
from ...document import operations as ops, locking
from ..snapping import pick, screen, pull_drag, snap_pull
from ..pull_snapping import PullReferences
from ..previews.overlay import outline
from ..qt import QtCore, QtWidgets
V = App.Vector


class PushPullDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.updating = False
        self.setObjectName("SimpleCADPushPull")
        self.setWindowTitle("推拉建模 (Push / Pull)")
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        self.setMinimumWidth(360)
        self.slider_max = max(20.0, round(self.owner.face.BoundBox.DiagonalLength * 1.5))
        self.init_ui()

    def dialog_header_text(self):
        face = self.owner.face
        name = self.owner.name or ""
        surf = type(face.Surface).__name__ if hasattr(face, 'Surface') else "Face"
        surf_map = {"Plane": "平面", "Cylinder": "圆柱面", "BSplineSurface": "B样条曲面", "Face": "表面"}
        surf_cn = surf_map.get(surf, surf)
        return f"{surf_cn} {name} · 面积 {face.Area:.1f} mm²"

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # 顶部提示：表面类型与面积
        self.target_label = QtWidgets.QLabel(self.dialog_header_text())
        self.target_label.setStyleSheet("font-weight: bold; color: #50d6bb;")
        layout.addWidget(self.target_label)

        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        # 距离输入框
        self.dist_edit = QtWidgets.QLineEdit()
        self.dist_edit.setObjectName("SimpleCADPushPullDistance")
        self.dist_edit.setPlaceholderText("例如 5.0 mm")
        mag = abs(self.owner.distance)
        if mag > g.EPS:
            self.dist_edit.setText(f"{mag:.2f} mm")
        form.addRow("推拉距离", self.dist_edit)

        # 快速步进按钮
        dist_buttons_layout = QtWidgets.QHBoxLayout()
        for d_inc in (1, 2, 5, 10):
            btn = QtWidgets.QPushButton(f"+{d_inc} mm")
            btn.setAutoDefault(False)
            btn.clicked.connect(lambda unused=False, inc=d_inc: self.add_distance(inc))
            dist_buttons_layout.addWidget(btn)
        btn_reset_dist = QtWidgets.QPushButton("重置")
        btn_reset_dist.setAutoDefault(False)
        btn_reset_dist.clicked.connect(self.reset_distance)
        dist_buttons_layout.addWidget(btn_reset_dist)
        layout.addLayout(dist_buttons_layout)

        # 挤出方向下拉选择与反向按钮
        dir_layout = QtWidgets.QHBoxLayout()
        self.dir_combo = QtWidgets.QComboBox()
        self.dir_combo.setObjectName("SimpleCADPushPullDirection")
        is_solid = self.owner.is_solid
        if is_solid:
            self.dir_combo.addItem("向外拉伸 (凸台/拉伸)", 1)
            self.dir_combo.addItem("向内切削 (凹槽/切除)", -1)
        else:
            self.dir_combo.addItem("沿法线正向 (+)", 1)
            self.dir_combo.addItem("沿法线反向 (-)", -1)
        if self.owner.direction_sign < 0:
            self.dir_combo.setCurrentIndex(1)
        dir_layout.addWidget(self.dir_combo, 1)

        self.flip_btn = QtWidgets.QPushButton("⇄ 反向")
        self.flip_btn.setAutoDefault(False)
        self.flip_btn.setToolTip("在正向与反向之间反转拉伸方向")
        self.flip_btn.clicked.connect(self.flip_direction)
        dir_layout.addWidget(self.flip_btn)
        form.addRow("挤出方向", dir_layout)

        # 贯通至对立面快捷按钮
        if self.owner.pull_contact is not None:
            opp_dist = self.owner.pull_contact.distance
            self.opp_btn = QtWidgets.QPushButton(f"贯通至对立面 ({abs(opp_dist):.2f} mm)")
            self.opp_btn.setObjectName("SimpleCADPushPullOpposite")
            self.opp_btn.setAutoDefault(False)
            self.opp_btn.setToolTip("设置精确距离以切穿贯通至对立背面")
            self.opp_btn.clicked.connect(self.to_opposite_face)
            layout.addWidget(self.opp_btn)
        else:
            self.opp_btn = None

        # 距离滑块
        self.dist_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.dist_slider.setObjectName("SimpleCADPushPullSlider")
        self.dist_slider.setRange(0, 1000)
        initial_slider_val = min(1000, round((mag / max(self.slider_max, 1e-4)) * 1000))
        self.dist_slider.setValue(initial_slider_val)
        self.dist_slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 4px; background: #555; border-radius: 2px; } "
            "QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #50d6bb; border-radius: 7px; }"
        )
        layout.addWidget(self.dist_slider)

        # 状态描述文本
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(self.status.fontMetrics().lineSpacing() * 2)
        layout.addWidget(self.status)

        # 应用 / 取消按钮
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.Apply)
        self.apply_button.setText("应用")
        self.apply_button.setAutoDefault(False)
        self.apply_button.setEnabled(abs(self.owner.distance) > g.EPS)
        self.apply_button.clicked.connect(self.apply)

        cancel_button = buttons.button(QtWidgets.QDialogButtonBox.Cancel)
        cancel_button.setText("取消")
        buttons.rejected.connect(self.owner.c.cancel)
        self.rejected.connect(self.owner.c.cancel)
        layout.addWidget(buttons)

        # 绑定信号
        self.dist_edit.textEdited.connect(self.on_distance_edited)
        self.dist_edit.returnPressed.connect(self.apply)
        self.dir_combo.currentIndexChanged.connect(self.on_direction_changed)
        self.dist_slider.valueChanged.connect(self.on_slider_changed)

        self.update_status_text()

    def update_status_text(self):
        dist = self.owner.distance
        mag = abs(dist)
        if mag < g.EPS:
            self.status.setStyleSheet("")
            self.status.setText("输入距离数值或在 3D 视图中拖动表面以预览。")
            return

        contact = self.owner.pull_contact
        if contact and abs(dist - contact.distance) <= g.EPS:
            self.status.setStyleSheet("color: #50d6bb;")
            self.status.setText(f"贯通切削至对立面 ({dist:+.2f} mm)")
            return

        if dist > 0:
            action = "向外拉伸" if self.owner.is_solid else "沿法线正向拉伸"
            role = "创建实体凸台" if self.owner.is_solid else "生成实体"
            self.status.setStyleSheet("")
            self.status.setText(f"{action} ({dist:+.2f} mm) · {role}")
        else:
            action = "向内切削" if self.owner.is_solid else "沿法线反向拉伸"
            role = "切削凹槽开槽" if self.owner.is_solid else "生成实体"
            self.status.setStyleSheet("")
            self.status.setText(f"{action} ({dist:+.2f} mm) · {role}")

    def update_status(self, text, is_error=False):
        if is_error:
            self.status.setStyleSheet("color: #e78f70;")
        else:
            self.status.setStyleSheet("")
        self.status.setText(text)

    def on_distance_edited(self, text):
        if self.updating:
            return
        try:
            cleaned = text.strip()
            if not cleaned:
                self.owner.distance = 0.0
                self.owner.refresh()
                self.apply_button.setEnabled(False)
                self.update_status_text()
                return

            if cleaned.startswith('-'):
                self.owner.direction_sign = -1
                self.dir_combo.blockSignals(True)
                self.dir_combo.setCurrentIndex(1)
                self.dir_combo.blockSignals(False)
                mag = abs(g.parse_length(cleaned))
            elif cleaned.startswith('+'):
                self.owner.direction_sign = 1
                self.dir_combo.blockSignals(True)
                self.dir_combo.setCurrentIndex(0)
                self.dir_combo.blockSignals(False)
                mag = abs(g.parse_length(cleaned))
            else:
                mag = abs(g.parse_length(cleaned))

            self.owner.distance = self.owner.direction_sign * mag
            self.dist_slider.blockSignals(True)
            self.dist_slider.setValue(min(1000, round((mag / max(self.slider_max, 1e-4)) * 1000)))
            self.dist_slider.blockSignals(False)
            self.apply_button.setEnabled(abs(self.owner.distance) > g.EPS)
            self.update_status_text()
            self.owner.refresh()
        except Exception:
            pass

    def on_direction_changed(self, idx):
        if self.updating:
            return
        new_sign = self.dir_combo.currentData()
        self.owner.direction_sign = new_sign
        mag = abs(self.owner.distance)
        self.owner.distance = self.owner.direction_sign * mag
        self.update_status_text()
        self.owner.refresh()

    def flip_direction(self):
        self.owner.direction_sign = -self.owner.direction_sign
        self.dir_combo.blockSignals(True)
        idx = self.dir_combo.findData(self.owner.direction_sign)
        if idx >= 0:
            self.dir_combo.setCurrentIndex(idx)
        self.dir_combo.blockSignals(False)
        mag = abs(self.owner.distance)
        self.owner.distance = self.owner.direction_sign * mag
        self.update_status_text()
        self.owner.refresh()

    def add_distance(self, delta):
        mag = abs(self.owner.distance) + delta
        self.owner.distance = self.owner.direction_sign * mag
        self.dist_edit.setText(f"{mag:.2f} mm")
        self.dist_slider.blockSignals(True)
        self.dist_slider.setValue(min(1000, round((mag / max(self.slider_max, 1e-4)) * 1000)))
        self.dist_slider.blockSignals(False)
        self.apply_button.setEnabled(abs(self.owner.distance) > g.EPS)
        self.update_status_text()
        self.owner.refresh()

    def reset_distance(self):
        self.owner.distance = 0.0
        self.dist_edit.clear()
        self.dist_slider.blockSignals(True)
        self.dist_slider.setValue(0)
        self.dist_slider.blockSignals(False)
        self.apply_button.setEnabled(False)
        self.update_status_text()
        self.owner.refresh()

    def to_opposite_face(self):
        if self.owner.pull_contact is None:
            return
        opp_dist = self.owner.pull_contact.distance
        self.owner.direction_sign = -1 if opp_dist < 0 else 1
        self.owner.distance = opp_dist
        self.dir_combo.blockSignals(True)
        idx = self.dir_combo.findData(self.owner.direction_sign)
        if idx >= 0:
            self.dir_combo.setCurrentIndex(idx)
        self.dir_combo.blockSignals(False)
        self.dist_edit.setText(f"{abs(opp_dist):.2f} mm")
        self.dist_slider.blockSignals(True)
        self.dist_slider.setValue(min(1000, round((abs(opp_dist) / max(self.slider_max, 1e-4)) * 1000)))
        self.dist_slider.blockSignals(False)
        self.apply_button.setEnabled(True)
        self.update_status_text()
        self.owner.refresh()

    def on_slider_changed(self, val):
        if self.updating:
            return
        fraction = val / 1000.0
        mag = fraction * self.slider_max
        self.owner.distance = self.owner.direction_sign * mag
        self.dist_edit.blockSignals(True)
        if mag > g.EPS:
            self.dist_edit.setText(f"{mag:.2f} mm")
        else:
            self.dist_edit.clear()
        self.dist_edit.blockSignals(False)
        self.apply_button.setEnabled(abs(self.owner.distance) > g.EPS)
        self.update_status_text()
        self.owner.refresh()

    def sync_from_input(self):
        if self.updating:
            return
        self.updating = True
        try:
            mag = abs(self.owner.distance)
            if not self.dist_edit.hasFocus():
                if mag > g.EPS:
                    self.dist_edit.setText(f"{mag:.2f} mm")
                else:
                    self.dist_edit.clear()

            self.dir_combo.blockSignals(True)
            idx = self.dir_combo.findData(self.owner.direction_sign)
            if idx >= 0:
                self.dir_combo.setCurrentIndex(idx)
            self.dir_combo.blockSignals(False)

            self.dist_slider.blockSignals(True)
            self.dist_slider.setValue(min(1000, round((mag / max(self.slider_max, 1e-4)) * 1000)))
            self.dist_slider.blockSignals(False)

            self.apply_button.setEnabled(mag > g.EPS)
            self.update_status_text()
        finally:
            self.updating = False

    def apply(self):
        if abs(self.owner.distance) < g.EPS:
            self.update_status("请输入非零距离数值。", is_error=True)
            return
        self.owner.c.commit()


class PushPullInput:
    def __init__(self, controller):
        self.c = controller
        self.obj = None
        self.face = None
        self.name = None
        self.normal = None
        self.anchor = None
        self.down_pos = None
        self.distance = 0.0
        self.direction_sign = 1
        self.pull_contact = None
        self.pull_references = None
        self.pull_reference = None
        self.dialog = None
        self.is_solid = True
        self.timer = QtCore.QTimer(controller if isinstance(controller, QtCore.QObject) else None)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)

    def close(self):
        self.timer.stop()
        self.timer.deleteLater()
        if self.dialog is not None:
            dialog = self.dialog
            self.dialog = None
            dialog.blockSignals(True)
            dialog.close()
            dialog.deleteLater()

    def open_dialog(self):
        if not (App.GuiUp and hasattr(Gui, 'getMainWindow')):
            return
        parent = Gui.getMainWindow()
        if parent is None:
            return
        if self.dialog is not None:
            try:
                self.dialog.close()
            except Exception:
                pass
            self.dialog = None
        self.dialog = PushPullDialog(self, parent)
        from ..panels import anchor_panel
        anchor_panel(self.dialog).show()
        self.dialog.dist_edit.setFocus()
        self.dialog.dist_edit.selectAll()

    def choose(self, obj, face_or_name, anchor=None):
        ops.editable(obj)
        if isinstance(face_or_name, str):
            face = obj.Shape.getElement(face_or_name)
            name = face_or_name
        else:
            face = face_or_name
            name = None
            if hasattr(obj, 'Shape'):
                for i, f in enumerate(obj.Shape.Faces, 1):
                    if f.isSame(face):
                        name = f"Face{i}"
                        break

        if not isinstance(face.Surface, Part.Plane):
            raise ValueError("推拉建模需要选择平面。")

        locking.require_face_unlocked(obj, face)

        self.obj = obj
        self.face = face
        self.name = name
        self.is_solid = bool(getattr(obj.Shape, 'Solids', None))
        self.normal = ops.extrusion_normal(self.obj, self.face)
        self.pull_contact = ops.extrusion_contact(self.obj, self.face)
        self.anchor = anchor or face.CenterOfMass
        self.c.anchor = self.anchor
        self.down_pos = screen(self.c.view, self.anchor) if self.c.view else None
        self.distance = 0.0
        self.direction_sign = 1
        self.pull_reference = None

        if self.c.doc and self.c.view:
            self.pull_references = PullReferences(self.c.doc, self.c.view, self.anchor, self.normal, face)
        else:
            self.pull_references = None

        if App.GuiUp and hasattr(Gui, 'Selection'):
            Gui.Selection.clearSelection()
            Gui.Selection.clearPreselection()

        self.show_pull()
        if hasattr(self.c, 'controls') and hasattr(self.c.controls, 'value'):
            self.c.controls.value.setPlaceholderText("推拉距离")
        self.c.message("在面板中输入距离或在视图中拖动表面 · 选择挤出方向 · 点击应用或回车完成 · 按 Esc 取消")
        self.open_dialog()

    def hover(self, pos):
        hit = pick(self.c.view, self.c.doc, pos, face_only=True)
        if hit and isinstance(hit[1].Surface, Part.Plane):
            self.c.preview.update(outline(hit[1]), hit[2])
        else:
            self.c.preview.update()
        return hit

    def click(self, pos):
        if self.face is None:
            hit = pick(self.c.view, self.c.doc, pos, face_only=True)
            if not hit:
                raise ValueError("请在视图中点击一个平面。")
            self.choose(hit[0], hit[1], hit[2])
            return False

        if abs(self.distance) > g.EPS:
            return True
        return False

    def motion(self, pos):
        if self.face is None:
            self.hover(pos)
            return

        step = max(self.face.BoundBox.DiagonalLength, 10.0)
        down_ref = self.down_pos or screen(self.c.view, self.anchor)
        dist, scale = pull_drag(self.c.view, pos, self.anchor, self.normal, down_ref, step)
        self.pull_reference = None
        if self.c.controls.snap.isChecked() and self.c.snapper.settings.pull_faces:
            if self.pull_references:
                self.pull_reference = self.pull_references.snap(pos, self.c.snapper.settings.pull_radius)
            contact_dist = (snap_pull(self.c.view, dist, self.pull_contact.distance,
                                      self.anchor, self.normal, scale, self.c.snapper.settings.pull_radius)
                            if self.pull_contact else None)
            if self.pull_contact and abs(contact_dist - self.pull_contact.distance) <= g.EPS:
                dist = contact_dist
                if self.pull_reference and abs(self.pull_reference.distance - contact_dist) > g.EPS:
                    self.pull_reference = None
            elif self.pull_reference:
                dist = self.pull_reference.distance

        self.distance = dist
        if self.distance > g.EPS:
            self.direction_sign = 1
        elif self.distance < -g.EPS:
            self.direction_sign = -1

        self.show_pull()
        if self.dialog is not None:
            self.dialog.sync_from_input()

    def refresh(self):
        self.show_pull()
        if self.dialog is not None:
            self.dialog.sync_from_input()

    def show_pull(self):
        delta = self.normal * self.distance
        base = outline(self.face)
        polylines = list(base)
        moving = ()
        if abs(self.distance) > g.EPS:
            moving = base
            polylines += [[v.Point, v.Point + delta] for v in self.face.Vertexes]
            target_pt = self.anchor + delta
        else:
            stub = self.normal * (self.direction_sign * 1.5)
            target_pt = self.anchor + stub

        contact = None
        snapped = self.pull_contact is not None and abs(self.distance - self.pull_contact.distance) <= g.EPS
        if self.pull_contact and self.c.controls.snap.isChecked() and self.c.snapper.settings.pull_faces:
            contact = self.face.CenterOfMass + self.normal * self.pull_contact.distance
        label = 'Opposite face'
        reference = self.pull_reference
        if reference and self.c.controls.snap.isChecked() and self.c.snapper.settings.pull_faces:
            contact = reference.point
            label = 'Opposite face' if snapped else reference.label
            snapped = True

        # 3D 视口内悬浮标记与吸附文本汉化
        display_label = '对立面' if label == 'Opposite face' else label

        if self.c.preview is not None:
            self.c.preview.update(polylines, target_pt, contact=contact, contact_snapped=snapped,
                                  contact_label=display_label, moving=moving, offset=delta,
                                  see_through=self.distance < -g.EPS)
        if hasattr(self.c, 'controls') and hasattr(self.c.controls, 'label'):
            self.c.controls.label.setText(
                (("位于对立面" if label == 'Opposite face' else display_label + ' 已吸附')
                 if snapped else "推拉") + (" %.2f mm" % self.distance if abs(self.distance) > g.EPS else "")
            )

    def numeric(self, text):
        cleaned = text.strip()
        if not cleaned:
            return
        if cleaned.startswith('-'):
            self.direction_sign = -1
            mag = abs(g.parse_length(cleaned))
        elif cleaned.startswith('+'):
            self.direction_sign = 1
            mag = abs(g.parse_length(cleaned))
        else:
            mag = abs(g.parse_length(cleaned))
        self.distance = self.direction_sign * mag
        self.refresh()

    def commit(self):
        if abs(self.distance) < g.EPS:
            raise ValueError("请输入非零距离数值。")
        if self.dialog is not None:
            dialog = self.dialog
            self.dialog = None
            dialog.blockSignals(True)
            dialog.close()
            dialog.deleteLater()
        return ops.extrude(self.obj, self.face, self.distance, return_pieces=True)