"""Interactive Push/Pull dialog and input session for exact distance and direction selection."""
import math
import FreeCAD as App
import FreeCADGui as Gui
import Part
from pivy import coin
from ...core import geometry as g
from ...document import operations as ops, locking
from ..snapping import pick, screen, pull_drag, snap_pull
from ..pull_snapping import PullReferences
from ..previews.overlay import outline, label_font, pixel_ratio
from ..qt import QtCore, QtWidgets
V = App.Vector


def dist_point_to_segment_2d(p, a, b):
    px, py = p[0], p[1]
    ax, ay = a[0], a[1]
    bx, by = b[0], b[1]
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-6:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class PushPullArrow:
    """Shapr3D 风格的大号 3D 视口法线推拉箭头与独立引线文字。"""
    def __init__(self, view, anchor, normal):
        self.view = view
        self.anchor = V(anchor)
        self.normal = g.unit(normal) if normal.Length > 1e-9 else V(0, 0, 1)
        self.distance = 0.0
        self.is_hovered = False
        self.hover_side = 1
        self.arrow_len = 50.0

        self.root = coin.SoSeparator()

        depth = coin.SoDepthBuffer()
        depth.function = coin.SoDepthBuffer.ALWAYS
        depth.write = False
        self.root.addChild(depth)

        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        self.root.addChild(light)

        # 1. 主拉伸箭头
        self.pos_sep = coin.SoSeparator()
        self.pos_mat = coin.SoBaseColor()
        self.pos_style = coin.SoDrawStyle()
        self.pos_coords = coin.SoCoordinate3()
        self.pos_lines = coin.SoLineSet()
        self.pos_faces = coin.SoIndexedFaceSet()
        for node in (self.pos_mat, self.pos_style, self.pos_coords, self.pos_lines, self.pos_faces):
            self.pos_sep.addChild(node)
        self.root.addChild(self.pos_sep)

        # 2. 反向切削辅助箭头
        self.neg_sep = coin.SoSeparator()
        self.neg_mat = coin.SoBaseColor()
        self.neg_style = coin.SoDrawStyle()
        self.neg_style.linePattern = 0xF0F0
        self.neg_coords = coin.SoCoordinate3()
        self.neg_lines = coin.SoLineSet()
        self.neg_faces = coin.SoIndexedFaceSet()
        for node in (self.neg_mat, self.neg_style, self.neg_coords, self.neg_lines, self.neg_faces):
            self.neg_sep.addChild(node)
        self.root.addChild(self.neg_sep)

        # 3. 表面基准圆环
        self.ring_sep = coin.SoSeparator()
        self.ring_mat = coin.SoBaseColor()
        self.ring_mat.rgb = (0.2, 0.85, 0.95)
        self.ring_style = coin.SoDrawStyle()
        self.ring_coords = coin.SoCoordinate3()
        self.ring_lines = coin.SoLineSet()
        for node in (self.ring_mat, self.ring_style, self.ring_coords, self.ring_lines):
            self.ring_sep.addChild(node)
        self.root.addChild(self.ring_sep)

        # 4. 指示引线
        self.leader_sep = coin.SoSeparator()
        self.leader_mat = coin.SoBaseColor()
        self.leader_mat.rgb = (0.7, 0.85, 0.95)
        self.leader_style = coin.SoDrawStyle()
        self.leader_style.lineWidth = 1.5
        self.leader_coords = coin.SoCoordinate3()
        self.leader_lines = coin.SoLineSet()
        for node in (self.leader_mat, self.leader_style, self.leader_coords, self.leader_lines):
            self.leader_sep.addChild(node)
        self.root.addChild(self.leader_sep)

        # 5. 动态尺寸标签文字
        self.text_sep = coin.SoSeparator()
        self.text_mat = coin.SoBaseColor()
        self.text_trans = coin.SoTranslation()
        self.text_node = coin.SoText2()
        self.text_node.justification = coin.SoText2.LEFT
        for node in (self.text_mat, self.text_trans, label_font(13), self.text_node):
            self.text_sep.addChild(node)
        self.root.addChild(self.text_sep)

        self.view.getSceneGraph().addChild(self.root)
        self.update(self.distance)

    def get_basis(self):
        norm = self.normal
        ref = V(0, 0, 1) if abs(norm.z) < 0.85 else V(1, 0, 0)
        u = norm.cross(ref).normalize()
        v = norm.cross(u).normalize()
        return u, v

    def compute_arrow_length(self, center):
        try:
            p0 = screen(self.view, center)
            p1 = screen(self.view, center + self.normal * 10.0)
            px_dist = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if px_dist > 1e-3:
                scale = 90.0 / (px_dist / 10.0)
                return max(20.0, min(5000.0, scale))
        except Exception:
            pass
        return 50.0

    def _build_arrow_geom(self, base_pt, dir_vec, length, coords_node, lines_node, faces_node):
        u, v = self.get_basis()
        cone_len = length * 0.28
        cone_rad = length * 0.09
        shaft_end = base_pt + dir_vec * (length - cone_len)
        tip = base_pt + dir_vec * length

        n_seg = 8
        angles = [i * 2 * math.pi / n_seg for i in range(n_seg)]
        ring_pts = [shaft_end + (u * math.cos(a) + v * math.sin(a)) * cone_rad for a in angles]

        pts = [base_pt, shaft_end, tip] + ring_pts
        coords_node.point.setValues(0, len(pts), [tuple(p) for p in pts])
        lines_node.numVertices.setValue(2)

        indices = []
        for i in range(n_seg):
            next_i = (i + 1) % n_seg
            indices.extend([2, 3 + i, 3 + next_i, -1])
            indices.extend([1, 3 + next_i, 3 + i, -1])
        faces_node.coordIndex.setValues(0, len(indices), indices)

    def update(self, distance=0.0, is_hovered=False, hover_side=1, label_text=""):
        self.distance = distance
        self.is_hovered = is_hovered
        self.hover_side = hover_side

        curr_center = self.anchor + self.normal * self.distance
        self.arrow_len = self.compute_arrow_length(curr_center)
        pr = pixel_ratio()

        pos_active = (is_hovered and hover_side > 0) or (distance > g.EPS)
        if pos_active:
            self.pos_mat.rgb = (1.0, 0.72, 0.1)
            self.pos_style.lineWidth = 5.0 * pr
        else:
            self.pos_mat.rgb = (0.2, 0.85, 0.95)
            self.pos_style.lineWidth = 3.5 * pr
        self._build_arrow_geom(curr_center, self.normal, self.arrow_len,
                              self.pos_coords, self.pos_lines, self.pos_faces)

        neg_len = self.arrow_len * 0.45
        neg_active = (is_hovered and hover_side < 0) or (distance < -g.EPS)
        if neg_active:
            self.neg_mat.rgb = (1.0, 0.45, 0.2)
            self.neg_style.lineWidth = 3.8 * pr
        else:
            self.neg_mat.rgb = (0.7, 0.45, 0.3)
            self.neg_style.lineWidth = 2.0 * pr
        self._build_arrow_geom(curr_center, -self.normal, neg_len,
                              self.neg_coords, self.neg_lines, self.neg_faces)

        u, v = self.get_basis()
        r_rad = self.arrow_len * 0.1
        n_ring = 16
        ring_pts = [self.anchor + (u * math.cos(i * 2 * math.pi / n_ring) + v * math.sin(i * 2 * math.pi / n_ring)) * r_rad
                    for i in range(n_ring + 1)]
        self.ring_coords.point.setValues(0, len(ring_pts), [tuple(p) for p in ring_pts])
        self.ring_lines.numVertices.setValue(len(ring_pts))
        self.ring_style.lineWidth = 2.0 * pr

        tip = curr_center + self.normal * self.arrow_len
        side_vec = (u + v * 0.7).normalize()
        tag_pos = tip + side_vec * (self.arrow_len * 0.45 + 10.0) + self.normal * 5.0

        self.leader_coords.point.setValues(0, 2, [tuple(tip), tuple(tag_pos)])
        self.leader_lines.numVertices.setValue(2)

        self.text_trans.translation = tuple(tag_pos)
        self.text_mat.rgb = (1.0, 1.0, 0.7) if (is_hovered or abs(distance) > g.EPS) else (0.9, 0.95, 0.95)
        self.text_node.string = " " + (label_text or (f"{self.distance:+.2f} mm" if abs(self.distance) > g.EPS else "推拉"))

        self.view.redraw()

    def hit_test(self, pos):
        try:
            curr_center = self.anchor + self.normal * self.distance
            s_center = screen(self.view, curr_center)
            pos_tip = curr_center + self.normal * self.arrow_len
            s_pos = screen(self.view, pos_tip)
            neg_tip = curr_center - self.normal * (self.arrow_len * 0.45)
            s_neg = screen(self.view, neg_tip)
            pr = pixel_ratio()
            thresh = 22.0 * pr

            if dist_point_to_segment_2d(pos, s_center, s_pos) <= thresh:
                return 1
            if dist_point_to_segment_2d(pos, s_center, s_neg) <= thresh:
                return -1
            if math.hypot(pos[0] - s_center[0], pos[1] - s_center[1]) <= 20.0 * pr:
                return 1
        except Exception:
            pass
        return 0

    def close(self):
        try:
            self.view.getSceneGraph().removeChild(self.root)
            self.view.redraw()
        except Exception:
            pass


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

        self.target_label = QtWidgets.QLabel(self.dialog_header_text())
        self.target_label.setStyleSheet("font-weight: bold; color: #50d6bb;")
        layout.addWidget(self.target_label)

        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.dist_edit = QtWidgets.QLineEdit()
        self.dist_edit.setObjectName("SimpleCADPushPullDistance")
        self.dist_edit.setPlaceholderText("例如 5.0 mm")
        mag = abs(self.owner.distance)
        if mag > g.EPS:
            self.dist_edit.setText(f"{mag:.2f} mm")
        form.addRow("推拉距离", self.dist_edit)

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
        self.flip_btn.setToolTip("反转推拉方向")
        self.flip_btn.clicked.connect(self.flip_direction)
        dir_layout.addWidget(self.flip_btn)
        form.addRow("挤出方向", dir_layout)

        self.opp_btn = QtWidgets.QPushButton("贯通至对立面")
        self.opp_btn.setObjectName("SimpleCADPushPullOpposite")
        self.opp_btn.setAutoDefault(False)
        self.opp_btn.setToolTip("设置精确距离以切穿贯通至对立背面")
        self.opp_btn.clicked.connect(self.to_opposite_face)
        layout.addWidget(self.opp_btn)
        if self.owner.pull_contact is not None:
            opp_dist = self.owner.pull_contact.distance
            self.opp_btn.setText(f"贯通至对立面 ({abs(opp_dist):.2f} mm)")
            self.opp_btn.setVisible(True)
        else:
            self.opp_btn.setVisible(False)

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

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(self.status.fontMetrics().lineSpacing() * 2)
        layout.addWidget(self.status)

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

        self.dist_edit.textEdited.connect(self.on_distance_edited)
        self.dist_edit.returnPressed.connect(self.apply)
        self.dir_combo.currentIndexChanged.connect(self.on_direction_changed)
        self.dist_slider.valueChanged.connect(self.on_slider_changed)

        self.update_status_text()

    def refresh_target(self):
        """原地刷新当前面板内容为新选中的面，完全不重复开窗、不叠罗汉！"""
        self.updating = True
        try:
            self.target_label.setText(self.dialog_header_text())
            self.slider_max = max(20.0, round(self.owner.face.BoundBox.DiagonalLength * 1.5))
            self.dist_edit.clear()
            self.dist_slider.blockSignals(True)
            self.dist_slider.setValue(0)
            self.dist_slider.blockSignals(False)

            is_solid = self.owner.is_solid
            self.dir_combo.blockSignals(True)
            self.dir_combo.clear()
            if is_solid:
                self.dir_combo.addItem("向外拉伸 (凸台/拉伸)", 1)
                self.dir_combo.addItem("向内切削 (凹槽/切除)", -1)
            else:
                self.dir_combo.addItem("沿法线正向 (+)", 1)
                self.dir_combo.addItem("沿法线反向 (-)", -1)
            self.dir_combo.setCurrentIndex(0)
            self.dir_combo.blockSignals(False)

            if self.owner.pull_contact is not None:
                opp_dist = self.owner.pull_contact.distance
                self.opp_btn.setText(f"贯通至对立面 ({abs(opp_dist):.2f} mm)")
                self.opp_btn.setVisible(True)
            else:
                self.opp_btn.setVisible(False)

            self.apply_button.setEnabled(False)
            self.update_status_text()
        finally:
            self.updating = False

    def update_status_text(self):
        dist = self.owner.distance
        mag = abs(dist)
        if mag < g.EPS:
            self.status.setStyleSheet("")
            self.status.setText("请点击并拖拽 3D 箭头，或在下方输入精确数值。")
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
        self.drag_start_pos = None
        self.distance = 0.0
        self.direction_sign = 1
        self.pull_contact = None
        self.pull_references = None
        self.pull_reference = None
        self.dialog = None
        self.arrow = None
        self.is_solid = True
        self.dragging = False  # 待命状态：只有与箭头互动才激活推拉
        self.timer = QtCore.QTimer(controller if isinstance(controller, QtCore.QObject) else None)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)

    def close(self):
        self.timer.stop()
        self.timer.deleteLater()
        if self.arrow is not None:
            self.arrow.close()
            self.arrow = None
        if self.dialog is not None:
            dialog = self.dialog
            self.dialog = None
            try:
                dialog.blockSignals(True)
                dialog.close()
                dialog.deleteLater()
            except Exception:
                pass
        # 兜底清理主窗口中任何可能残留的同名对话框
        if App.GuiUp and hasattr(Gui, 'getMainWindow'):
            main_win = Gui.getMainWindow()
            if main_win:
                for old in main_win.findChildren(QtWidgets.QDialog, "SimpleCADPushPull"):
                    try:
                        old.blockSignals(True)
                        old.close()
                        old.deleteLater()
                    except Exception:
                        pass

    def open_dialog(self):
        if not (App.GuiUp and hasattr(Gui, 'getMainWindow')):
            return
        parent = Gui.getMainWindow()
        if parent is None:
            return

        # 若已有面板打开：绝不重复开窗，直接刷新内容！
        if self.dialog is not None:
            try:
                self.dialog.refresh_target()
                return
            except Exception:
                self.dialog = None

        # 彻底清理任何遗留的旧窗口（坚决防止叠罗汉）
        for old in parent.findChildren(QtWidgets.QDialog, "SimpleCADPushPull"):
            try:
                old.blockSignals(True)
                old.close()
                old.deleteLater()
            except Exception:
                pass

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
        self.drag_start_pos = None
        self.distance = 0.0
        self.direction_sign = 1
        self.pull_reference = None
        self.dragging = False

        if self.c.doc and self.c.view:
            self.pull_references = PullReferences(self.c.doc, self.c.view, self.anchor, self.normal, face)
        else:
            self.pull_references = None

        if App.GuiUp and hasattr(Gui, 'Selection'):
            Gui.Selection.clearSelection()
            Gui.Selection.clearPreselection()

        # 箭头转移到当前面
        if self.c.view:
            if self.arrow is not None:
                self.arrow.close()
            self.arrow = PushPullArrow(self.c.view, self.anchor, self.normal)

        self.show_pull()
        if hasattr(self.c, 'controls') and hasattr(self.c.controls, 'value'):
            self.c.controls.value.setPlaceholderText("推拉距离")
        self.c.message("表面已就绪：请点击并拖拽 3D 箭头调整厚度 · 点击其他面切换 · 按 Esc 取消")

        # 刷新或打开唯一窗口
        if self.dialog is not None:
            self.dialog.refresh_target()
        else:
            self.open_dialog()

    def hover(self, pos):
        if self.face is None:
            hit = pick(self.c.view, self.c.doc, pos, face_only=True)
            if hit and isinstance(hit[1].Surface, Part.Plane):
                self.c.preview.update(outline(hit[1]), hit[2])
            else:
                self.c.preview.update()
            return hit

        if self.arrow is not None:
            hit_code = self.arrow.hit_test(pos)
            if hit_code != 0:
                self.arrow.update(distance=self.distance, is_hovered=True, hover_side=hit_code)
                if hit_code < 0:
                    self.c.message("拖拽反向箭头进行向内切削 · 点击应用或按 Enter 确定")
                else:
                    self.c.message("拖拽正向箭头进行拉伸成型 · 点击应用或按 Enter 确定")
            else:
                self.arrow.update(distance=self.distance, is_hovered=False, hover_side=self.direction_sign)
        return None

    def click(self, pos):
        if self.face is None:
            hit = pick(self.c.view, self.c.doc, pos, face_only=True)
            if not hit:
                raise ValueError("请在视图中点击一个平面。")
            self.choose(hit[0], hit[1], hit[2])
            return False

        # 待命状态：检测点击了什么
        if not self.dragging:
            hit_code = self.arrow.hit_test(pos) if self.arrow else 0
            if hit_code != 0:
                self.dragging = True
                self.drag_start_pos = pos
                self.down_pos = pos
                if hit_code < 0:
                    self.direction_sign = -1
                    if self.dialog is not None:
                        self.dialog.flip_direction()
                self.arrow.update(distance=self.distance, is_hovered=True, hover_side=self.direction_sign)
                self.c.message("已抓住箭头：移动鼠标调整推拉距离 · 再次点击确定 · 按 Tab 输入数值")
                return False
            else:
                # 点击其他面：无缝原地切换目标面！
                hit = pick(self.c.view, self.c.doc, pos, face_only=True)
                if hit and hasattr(hit[1], 'Surface') and isinstance(hit[1].Surface, Part.Plane):
                    self.choose(hit[0], hit[1], hit[2])
                    return False
                else:
                    # 点击空白区域：退出推拉，窗口关闭！
                    self.c.cancel()
                    return False

        # 拖拽拉伸状态中再次点击：完成提交！
        if abs(self.distance) > g.EPS:
            return True
        else:
            self.dragging = False
            self.show_pull()
            return False

    def motion(self, pos):
        if self.face is None:
            self.hover(pos)
            return

        left_down = bool(QtWidgets.QApplication.mouseButtons() & QtCore.Qt.LeftButton)

        if not self.dragging:
            hit_code = self.arrow.hit_test(pos) if self.arrow else 0
            if left_down and hit_code != 0:
                self.dragging = True
                self.drag_start_pos = pos
                self.down_pos = pos
                if hit_code < 0:
                    self.direction_sign = -1
                    if self.dialog is not None:
                        self.dialog.flip_direction()
            else:
                self.hover(pos)
                return

        step = max(self.face.BoundBox.DiagonalLength, 10.0)
        down_ref = self.drag_start_pos or self.down_pos or screen(self.c.view, self.anchor)
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

        display_label = '对立面' if label == 'Opposite face' else label

        if self.c.preview is not None:
            self.c.preview.update(polylines, target_pt, contact=contact, contact_snapped=snapped,
                                  contact_label=display_label, moving=moving, offset=delta,
                                  see_through=self.distance < -g.EPS)

        if self.arrow is not None:
            tag_text = display_label if snapped else (f"{self.distance:+.2f} mm" if abs(self.distance) > g.EPS else "推拉")
            self.arrow.update(distance=self.distance,
                              is_hovered=self.arrow.is_hovered,
                              hover_side=self.direction_sign,
                              label_text=tag_text)

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
        if self.arrow is not None:
            self.arrow.close()
            self.arrow = None
        if self.dialog is not None:
            dialog = self.dialog
            self.dialog = None
            try:
                dialog.blockSignals(True)
                dialog.close()
                dialog.deleteLater()
            except Exception:
                pass
        return ops.extrude(self.obj, self.face, self.distance, return_pieces=True)