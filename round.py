"""Shapr3D 风格双向圆角/倒斜角一体化工具：
- 外拉倒圆角 (Fillet)，内推倒斜角 (Chamfer)
- 倒斜角角度支持：默认 45°，预设 30°/45°/60° 与自定义度数输入
- 单击空白处秒退、单击其他边线原地瞬切、按 Esc 单键退出
"""
import math
import FreeCAD as App
import FreeCADGui as Gui
import Part
from pivy import coin

from ...core import geometry as geo
from ...document import operations as ops
from ..previews.shaded import RoundPreview
from ..snapping import screen, pick
from ..previews.overlay import label_font, pixel_ratio
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel

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


def compute_edge_bisector(shape, edge):
    """计算棱边两侧相邻面的外角平分线方向与中点锚点。"""
    try:
        faces = [f for f in shape.Faces if any(e.isSame(edge) for e in f.Edges)]
        mid_param = (edge.FirstParameter + edge.LastParameter) * 0.5
        mid_pt = edge.valueAt(mid_param)
        if len(faces) >= 2:
            normals = []
            for f in faces[:2]:
                uv = f.Surface.parameter(mid_pt)
                n = f.normalAt(uv[0], uv[1])
                normals.append(n.normalize())
            bisector = normals[0] + normals[1]
            if bisector.Length > 1e-4:
                return bisector.normalize(), mid_pt
        elif len(faces) == 1:
            uv = faces[0].Surface.parameter(mid_pt)
            n = faces[0].normalAt(uv[0], uv[1]).normalize()
            return n, mid_pt
    except Exception:
        pass
    mid_param = (edge.FirstParameter + edge.LastParameter) * 0.5
    mid_pt = edge.valueAt(mid_param)
    return V(0, 0, 1), mid_pt


class RoundArrow:
    """Shapr3D 风格的 3D 棱边双向手柄。"""
    def __init__(self, view, anchor, normal):
        self.view = view
        self.anchor = V(anchor)
        self.normal = normal.normalize() if normal.Length > 1e-6 else V(0, 0, 1)
        self.distance = 0.0
        self.mode = "fillet"
        self.angle = 45.0
        self.arrow_len = 45.0
        self.is_hovered = False

        self.root = coin.SoSeparator()
        depth = coin.SoDepthBuffer()
        depth.function = coin.SoDepthBuffer.ALWAYS
        depth.write = False
        self.root.addChild(depth)

        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        self.root.addChild(light)

        # 外拉箭头 (圆角)
        self.pos_sep = coin.SoSeparator()
        self.pos_mat = coin.SoBaseColor()
        self.pos_style = coin.SoDrawStyle()
        self.pos_coords = coin.SoCoordinate3()
        self.pos_lines = coin.SoLineSet()
        self.pos_faces = coin.SoIndexedFaceSet()
        for n in (self.pos_mat, self.pos_style, self.pos_coords, self.pos_lines, self.pos_faces):
            self.pos_sep.addChild(n)
        self.root.addChild(self.pos_sep)

        # 内推箭头 (倒斜角)
        self.neg_sep = coin.SoSeparator()
        self.neg_mat = coin.SoBaseColor()
        self.neg_style = coin.SoDrawStyle()
        self.neg_coords = coin.SoCoordinate3()
        self.neg_lines = coin.SoLineSet()
        self.neg_faces = coin.SoIndexedFaceSet()
        for n in (self.neg_mat, self.neg_style, self.neg_coords, self.neg_lines, self.neg_faces):
            self.neg_sep.addChild(n)
        self.root.addChild(self.neg_sep)

        # 引线与尺寸标签
        self.leader_sep = coin.SoSeparator()
        self.leader_mat = coin.SoBaseColor()
        self.leader_mat.rgb = (0.7, 0.85, 0.95)
        self.leader_style = coin.SoDrawStyle()
        self.leader_coords = coin.SoCoordinate3()
        self.leader_lines = coin.SoLineSet()
        for n in (self.leader_mat, self.leader_style, self.leader_coords, self.leader_lines):
            self.leader_sep.addChild(n)
        self.root.addChild(self.leader_sep)

        self.text_sep = coin.SoSeparator()
        self.text_mat = coin.SoBaseColor()
        self.text_trans = coin.SoTranslation()
        self.text_node = coin.SoText2()
        self.text_node.justification = coin.SoText2.LEFT
        for n in (self.text_mat, self.text_trans, label_font(13), self.text_node):
            self.text_sep.addChild(n)
        self.root.addChild(self.text_sep)

        self.view.getSceneGraph().addChild(self.root)
        self.update(0.0, "fillet", 45.0)

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
                scale = 80.0 / (px_dist / 10.0)
                return max(15.0, min(3000.0, scale))
        except Exception:
            pass
        return 45.0

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

    def update(self, distance, mode, angle=45.0, is_hovered=False, hover_dir=1):
        self.distance = distance
        self.mode = mode
        self.angle = angle
        self.is_hovered = is_hovered
        curr_center = self.anchor
        self.arrow_len = self.compute_arrow_length(curr_center)
        pr = pixel_ratio()

        pos_active = (mode == "fillet" and distance > geo.EPS) or (is_hovered and hover_dir > 0)
        self.pos_mat.rgb = (1.0, 0.75, 0.1) if pos_active else (0.2, 0.85, 0.95)
        self.pos_style.lineWidth = (4.5 if pos_active else 3.0) * pr
        self._build_arrow_geom(curr_center, self.normal, self.arrow_len,
                              self.pos_coords, self.pos_lines, self.pos_faces)

        neg_len = self.arrow_len * 0.75
        neg_active = (mode == "chamfer" and distance > geo.EPS) or (is_hovered and hover_dir < 0)
        self.neg_mat.rgb = (1.0, 0.45, 0.2) if neg_active else (0.85, 0.45, 0.95)
        self.neg_style.lineWidth = (4.5 if neg_active else 2.5) * pr
        self._build_arrow_geom(curr_center, -self.normal, neg_len,
                              self.neg_coords, self.neg_lines, self.neg_faces)

        u, v = self.get_basis()
        active_dir = self.normal if mode == "fillet" else -self.normal
        active_len = self.arrow_len if mode == "fillet" else neg_len
        tip = curr_center + active_dir * active_len
        side_vec = (u + v * 0.7).normalize()
        tag_pos = tip + side_vec * (self.arrow_len * 0.4 + 8.0)

        self.leader_coords.point.setValues(0, 2, [tuple(tip), tuple(tag_pos)])
        self.leader_lines.numVertices.setValue(2)

        self.text_trans.translation = tuple(tag_pos)
        self.text_mat.rgb = (1.0, 1.0, 0.6) if is_hovered or distance > geo.EPS else (0.9, 0.95, 0.95)

        if distance <= geo.EPS:
            self.text_node.string = " 外拉:圆角 / 内推:倒角"
        elif mode == "fillet":
            self.text_node.string = f" 圆角 R {distance:.2f} mm"
        else:
            ang_str = f" ({self.angle:g}°)" if abs(self.angle - 45.0) > 1e-3 else ""
            self.text_node.string = f" 倒斜角 C {distance:.2f} mm{ang_str}"

        self.view.redraw()

    def hit_test(self, pos):
        try:
            curr_center = self.anchor
            s_center = screen(self.view, curr_center)
            pos_tip = curr_center + self.normal * self.arrow_len
            s_pos = screen(self.view, pos_tip)
            neg_tip = curr_center - self.normal * (self.arrow_len * 0.75)
            s_neg = screen(self.view, neg_tip)
            pr = pixel_ratio()
            thresh = 28.0 * pr

            if dist_point_to_segment_2d(pos, s_center, s_pos) <= thresh:
                return 1
            if dist_point_to_segment_2d(pos, s_center, s_neg) <= thresh:
                return -1
            if math.hypot(pos[0] - s_center[0], pos[1] - s_center[1]) <= 22.0 * pr:
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


class RoundSession:
    def __init__(self, controller, targets, selection):
        self.controller, self.targets, self.selection = controller, targets, selection
        self.doc = targets[0][0].Document
        self.closed = False
        self.planned = None
        self.preview_radius = None
        self.mode = "fillet"
        self.current_distance = 0.0
        self.chamfer_angle = 45.0  # 默认 45°
        self.dragging = False
        self.drag_start = None
        self.initial_drag_val = 0.0

        # 防叠罗汉：清理旧对话框
        main_win = Gui.getMainWindow()
        if main_win:
            for old in main_win.findChildren(QtWidgets.QDialog, "SimpleCADRoundEdges"):
                try:
                    old.blockSignals(True)
                    old.close()
                    old.deleteLater()
                except Exception:
                    pass

        self.preview = RoundPreview(controller.view)

        # 3D 箭头
        first_obj, first_shape, first_indices = targets[0]
        first_edge = first_shape.Edges[first_indices[0]]
        self.normal, self.anchor = compute_edge_bisector(first_shape, first_edge)
        self.arrow = RoundArrow(controller.view, self.anchor, self.normal)

        # 计算尺寸
        size = min(d for _, shape, indices in targets
                   for d in [shape.BoundBox.XLength, shape.BoundBox.YLength, shape.BoundBox.ZLength] +
                   [shape.Edges[i].Length for i in indices] if d > geo.EPS)
        self.slider_range = max(1.0, size * 0.45)
        self.default_radius = 0.0
        self.current_distance = 0.0

        # 安装 Coin3D 原生事件回调
        self._cb = None
        if hasattr(self.controller.view, 'addEventCallbackPivy'):
            self._cb = self.controller.view.addEventCallbackPivy(
                coin.SoEvent.getClassTypeId(), self._on_coin_event
            )

        # 构建对话框面板
        self.dialog = QtWidgets.QDialog(main_win)
        self.dialog.setObjectName("SimpleCADRoundEdges")
        self.dialog.setWindowTitle("倒圆角 / 倒斜角 (Round & Chamfer)")
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        self.dialog.setMinimumWidth(360)
        self.init_ui(targets)

    def _on_coin_event(self, event_callback):
        if self.closed or not self.arrow:
            return
        so_event = event_callback.getEvent()

        # 键盘 Esc 键秒退
        if so_event.isOfType(coin.SoKeyboardEvent.getClassTypeId()):
            if so_event.getKey() == coin.SoKeyboardEvent.ESCAPE and so_event.getState() == coin.SoButtonEvent.DOWN:
                event_callback.setHandled()
                self.controller.cancel()
                return

        pos_vec = so_event.getPosition()
        pos = (pos_vec[0], pos_vec[1])

        # 鼠标移动事件
        if so_event.isOfType(coin.SoLocation2Event.getClassTypeId()):
            if self.dragging:
                self.on_drag(pos, self.drag_start)
                event_callback.setHandled()
            else:
                hit = self.arrow.hit_test(pos)
                self.arrow.update(self.current_distance, self.mode, self.chamfer_angle,
                                  is_hovered=(hit != 0), hover_dir=hit)

        # 鼠标按键事件
        elif so_event.isOfType(coin.SoMouseButtonEvent.getClassTypeId()):
            btn = so_event.getButton()
            state = so_event.getState()
            if btn == coin.SoMouseButtonEvent.BUTTON1:
                if state == coin.SoButtonEvent.DOWN:
                    hit = self.arrow.hit_test(pos)
                    if hit != 0:
                        self.dragging = True
                        self.drag_start = pos
                        self.initial_drag_val = self.current_distance if self.mode == "fillet" else -self.current_distance
                        if hit < 0:
                            self.set_mode("chamfer")
                        else:
                            self.set_mode("fillet")
                        event_callback.setHandled()
                    else:
                        picked = pick(self.controller.view, self.controller.doc, pos)
                        if picked and hasattr(picked[1], 'ShapeType') and picked[1].ShapeType == 'Edge':
                            # 点击另一条边：应用并切换
                            event_callback.setHandled()
                            if self.current_distance > geo.EPS and self.planned:
                                self.apply(quiet=True)
                            else:
                                self.controller.cancel(quiet=True)
                            Gui.Selection.clearSelection()
                            Gui.Selection.addSelection(picked[0], picked[2])
                        elif not picked:
                            # 点击空白区域：退出
                            event_callback.setHandled()
                            if self.current_distance > geo.EPS and self.planned:
                                self.apply()
                            else:
                                self.controller.cancel()

                elif state == coin.SoButtonEvent.UP:
                    if self.dragging:
                        self.dragging = False
                        self.update_preview()
                        event_callback.setHandled()

    def init_ui(self, targets):
        layout = QtWidgets.QVBoxLayout(self.dialog)

        count = sum(len(indices) for _, _, indices in targets)
        self.info_label = QtWidgets.QLabel(f"已选中 {count} 条棱边 · 拖动箭头或切换模式")
        self.info_label.setStyleSheet("font-weight: bold; color: #50d6bb;")
        layout.addWidget(self.info_label)

        # 模式切换单选栏
        mode_box = QtWidgets.QHBoxLayout()
        self.btn_fillet = QtWidgets.QPushButton("○ 倒圆角 (外拉)")
        self.btn_fillet.setCheckable(True)
        self.btn_fillet.setChecked(True)
        self.btn_fillet.setAutoDefault(False)
        self.btn_fillet.clicked.connect(lambda: self.set_mode("fillet"))

        self.btn_chamfer = QtWidgets.QPushButton("◇ 倒斜角 (内推)")
        self.btn_chamfer.setCheckable(True)
        self.btn_chamfer.setChecked(False)
        self.btn_chamfer.setAutoDefault(False)
        self.btn_chamfer.clicked.connect(lambda: self.set_mode("chamfer"))

        self.flip_btn = QtWidgets.QPushButton("⇄ 切换")
        self.flip_btn.setAutoDefault(False)
        self.flip_btn.setToolTip("在倒圆角与倒斜角之间快速切换")
        self.flip_btn.clicked.connect(self.toggle_mode)

        mode_box.addWidget(self.btn_fillet, 1)
        mode_box.addWidget(self.btn_chamfer, 1)
        mode_box.addWidget(self.flip_btn)
        layout.addLayout(mode_box)

        # 倒斜角角度控制行 (默认 45°，预设 30°/45°/60° 与自定义)
        self.angle_container = QtWidgets.QWidget(self.dialog)
        angle_layout = QtWidgets.QHBoxLayout(self.angle_container)
        angle_layout.setContentsMargins(0, 4, 0, 4)

        angle_layout.addWidget(QtWidgets.QLabel("倒角角度:"))
        self.btn_ang30 = QtWidgets.QPushButton("30°")
        self.btn_ang30.setAutoDefault(False)
        self.btn_ang45 = QtWidgets.QPushButton("45°")
        self.btn_ang45.setAutoDefault(False)
        self.btn_ang60 = QtWidgets.QPushButton("60°")
        self.btn_ang60.setAutoDefault(False)

        for b in (self.btn_ang30, self.btn_ang45, self.btn_ang60):
            b.setCheckable(True)
        self.btn_ang45.setChecked(True)

        self.btn_ang30.clicked.connect(lambda: self.set_angle(30.0))
        self.btn_ang45.clicked.connect(lambda: self.set_angle(45.0))
        self.btn_ang60.clicked.connect(lambda: self.set_angle(60.0))

        angle_layout.addWidget(self.btn_ang30)
        angle_layout.addWidget(self.btn_ang45)
        angle_layout.addWidget(self.btn_ang60)

        self.angle_edit = QtWidgets.QLineEdit(self.angle_container)
        self.angle_edit.setFixedWidth(55)
        self.angle_edit.setText("45°")
        self.angle_edit.setPlaceholderText("度数")
        self.angle_edit.textEdited.connect(self.on_angle_edited)
        angle_layout.addWidget(self.angle_edit)

        layout.addWidget(self.angle_container)
        self.angle_container.setVisible(False)  # 初始圆角模式下隐藏

        # 数值输入行
        row = QtWidgets.QHBoxLayout()
        self.label_dim = QtWidgets.QLabel("圆角半径:")
        self.radius = QtWidgets.QLineEdit(self.dialog)
        self.radius.setObjectName("SimpleCADRoundRadius")
        self.radius.setPlaceholderText("例如 2.0 mm")
        row.addWidget(self.label_dim)
        row.addWidget(self.radius)
        layout.addLayout(row)

        # 增量步进调节
        inc_layout = QtWidgets.QHBoxLayout()
        for inc in (0.5, 1.0, 2.0, 5.0):
            b = QtWidgets.QPushButton(f"+{inc:g}")
            b.setAutoDefault(False)
            b.clicked.connect(lambda unused=False, v=inc: self.add_distance(v))
            inc_layout.addWidget(b)
        btn_reset = QtWidgets.QPushButton("重置 (0)")
        btn_reset.setAutoDefault(False)
        btn_reset.clicked.connect(lambda: self.set_distance(0.0))
        inc_layout.addWidget(btn_reset)
        layout.addLayout(inc_layout)

        # 滑块
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self.dialog)
        self.slider.setRange(0, 1000)
        layout.addWidget(self.slider)

        # 动态状态信息
        self.status = QtWidgets.QLabel(self.dialog)
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(self.status.fontMetrics().lineSpacing() * 2)
        layout.addWidget(self.status)

        # 操作按钮
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.Apply)
        self.apply_button.setText("应用")
        self.apply_button.setAutoDefault(False)
        self.apply_button.clicked.connect(self.apply)

        cancel_button = buttons.button(QtWidgets.QDialogButtonBox.Cancel)
        cancel_button.setText("取消 (Esc)")
        buttons.rejected.connect(self.controller.cancel)
        layout.addWidget(buttons)
        self.dialog.rejected.connect(self.controller.cancel)

        # 信号连接
        self.pending = QtCore.QTimer(self.dialog)
        self.pending.setSingleShot(True)
        self.pending.timeout.connect(self.update_preview)
        self.radius.textChanged.connect(self.on_text_edited)
        self.radius.returnPressed.connect(self.apply)
        self.slider.valueChanged.connect(self.on_slide)

    def set_mode(self, mode):
        if self.mode == mode:
            return
        self.mode = mode
        self.btn_fillet.blockSignals(True)
        self.btn_chamfer.blockSignals(True)
        self.btn_fillet.setChecked(mode == "fillet")
        self.btn_chamfer.setChecked(mode == "chamfer")
        self.btn_fillet.blockSignals(False)
        self.btn_chamfer.blockSignals(False)

        # 倒斜角显示角度栏，圆角隐藏
        self.angle_container.setVisible(mode == "chamfer")

        self.label_dim.setText("圆角半径:" if mode == "fillet" else "倒角距离:")
        self.planned = None
        self.arrow.update(self.current_distance, self.mode, self.chamfer_angle)
        self.update_preview()

    def toggle_mode(self):
        self.set_mode("chamfer" if self.mode == "fillet" else "fillet")

    def set_angle(self, angle):
        """设置预设或自定义倒斜角角度"""
        self.chamfer_angle = max(1.0, min(89.0, float(angle)))
        self.btn_ang30.blockSignals(True)
        self.btn_ang45.blockSignals(True)
        self.btn_ang60.blockSignals(True)
        self.btn_ang30.setChecked(abs(self.chamfer_angle - 30.0) < 1e-2)
        self.btn_ang45.setChecked(abs(self.chamfer_angle - 45.0) < 1e-2)
        self.btn_ang60.setChecked(abs(self.chamfer_angle - 60.0) < 1e-2)
        self.btn_ang30.blockSignals(False)
        self.btn_ang45.blockSignals(False)
        self.btn_ang60.blockSignals(False)

        self.angle_edit.blockSignals(True)
        self.angle_edit.setText(f"{self.chamfer_angle:g}°")
        self.angle_edit.blockSignals(False)

        self.planned = None
        self.arrow.update(self.current_distance, self.mode, self.chamfer_angle)
        self.update_preview()

    def on_angle_edited(self, text):
        cleaned = text.replace("°", "").replace("deg", "").strip()
        try:
            val = float(cleaned)
            if 1.0 <= val <= 89.0:
                self.chamfer_angle = val
                self.btn_ang30.blockSignals(True)
                self.btn_ang45.blockSignals(True)
                self.btn_ang60.blockSignals(True)
                self.btn_ang30.setChecked(abs(val - 30.0) < 1e-2)
                self.btn_ang45.setChecked(abs(val - 45.0) < 1e-2)
                self.btn_ang60.setChecked(abs(val - 60.0) < 1e-2)
                self.btn_ang30.blockSignals(False)
                self.btn_ang45.blockSignals(False)
                self.btn_ang60.blockSignals(False)

                self.planned = None
                self.arrow.update(self.current_distance, self.mode, self.chamfer_angle)
                self.pending.start(180)
        except Exception:
            pass

    def set_distance(self, dist):
        self.current_distance = max(0.0, dist)
        self.radius.blockSignals(True)
        self.radius.setText(f"{self.current_distance:.2f} mm" if self.current_distance > geo.EPS else "0 mm")
        self.radius.blockSignals(False)
        self.slider.blockSignals(True)
        self.slider.setValue(min(1000, round((self.current_distance / self.slider_range) * 1000)))
        self.slider.blockSignals(False)
        self.arrow.update(self.current_distance, self.mode, self.chamfer_angle)
        self.update_preview()

    def add_distance(self, delta):
        self.set_distance(self.current_distance + delta)

    def open(self):
        Gui.Selection.clearSelection()
        Gui.Selection.clearPreselection()
        self.set_distance(0.0)
        anchor_panel(self.dialog).show()
        self.radius.setFocus()
        self.radius.selectAll()

    def on_text_edited(self, text):
        cleaned = text.strip()
        if not cleaned:
            return
        try:
            if cleaned.startswith("-"):
                val = abs(geo.parse_length(cleaned))
                self.set_mode("chamfer")
            elif cleaned.startswith("+"):
                val = abs(geo.parse_length(cleaned))
                self.set_mode("fillet")
            else:
                val = abs(geo.parse_length(cleaned))

            self.current_distance = val
            self.slider.blockSignals(True)
            self.slider.setValue(min(1000, round((self.current_distance / self.slider_range) * 1000)))
            self.slider.blockSignals(False)
            self.arrow.update(self.current_distance, self.mode, self.chamfer_angle)
            self.apply_button.setEnabled(False)
            self.pending.start(180)
        except Exception:
            pass

    def on_slide(self, value):
        val = (self.slider_range * value) / 1000.0
        self.current_distance = val
        self.radius.blockSignals(True)
        self.radius.setText(f"{val:.2f} mm" if val > geo.EPS else "0 mm")
        self.radius.blockSignals(False)
        self.arrow.update(self.current_distance, self.mode, self.chamfer_angle)
        self.apply_button.setEnabled(False)
        self.pending.start(120)

    def on_drag(self, pos, start_pos):
        try:
            s_anchor = screen(self.controller.view, self.anchor)
            s_normal = screen(self.controller.view, self.anchor + self.normal * 10.0)
            dx = s_normal[0] - s_anchor[0]
            dy = s_normal[1] - s_anchor[1]
            seg_len = math.hypot(dx, dy)
            if seg_len < 1e-3:
                return

            ux = dx / seg_len
            uy = dy / seg_len
            m_dx = pos[0] - start_pos[0]
            m_dy = pos[1] - start_pos[1]
            proj = m_dx * ux + m_dy * uy

            step = (proj / 80.0) * (self.slider_range * 0.4)
            val = self.initial_drag_val + step

            if val < -geo.EPS:
                self.set_mode("chamfer")
                self.current_distance = abs(val)
            else:
                self.set_mode("fillet")
                self.current_distance = max(0.0, val)

            self.radius.blockSignals(True)
            self.radius.setText(f"{self.current_distance:.2f} mm")
            self.radius.blockSignals(False)
            self.slider.blockSignals(True)
            self.slider.setValue(min(1000, round((self.current_distance / self.slider_range) * 1000)))
            self.slider.blockSignals(False)
            self.arrow.update(self.current_distance, self.mode, self.chamfer_angle, is_hovered=True)
            self.pending.start(80)
        except Exception:
            pass

    def compute_chamfer(self, distance):
        """支持 45° 等距及 30°/60°/任意角度的倒斜角计算"""
        planned = []
        d1 = distance
        # 根据角度计算次边距离 d2 = d1 * tan(angle)
        ang_rad = math.radians(self.chamfer_angle)
        d2 = d1 * math.tan(ang_rad)

        for obj, shape, indices in self.targets:
            edges = [shape.Edges[i] for i in indices]
            if abs(self.chamfer_angle - 45.0) < 1e-3:
                new_shape = shape.makeChamfer(d1, edges)
            else:
                try:
                    new_shape = shape.makeChamfer(d1, d2, edges)
                except Exception:
                    new_shape = shape.makeChamfer(d1, edges)
            planned.append((obj, new_shape))
        return planned

    def update_preview(self):
        self.pending.stop()
        if self.closed:
            return False
        try:
            self.controller.check_context()
            if self.closed:
                return False
            ops.check_rounding(self.targets)
            radius = self.current_distance

            if radius <= geo.EPS:
                self.planned = None
                self.preview.clear()
                self.status.setStyleSheet("")
                self.status.setText("原始形状 · 不做任何修改")
                self.apply_button.setEnabled(True)
                return True

            if self.mode == "fillet":
                planned = ops.preview_rounding(self.targets, radius)
                self.status.setText(f"实时预览: 倒圆角 R {radius:.2f} mm · 点击空白处应用")
            else:
                planned = self.compute_chamfer(radius)
                ang_info = f" ({self.chamfer_angle:g}°)" if abs(self.chamfer_angle - 45.0) > 1e-3 else " (45°)"
                self.status.setText(f"实时预览: 倒斜角 C {radius:.2f} mm{ang_info} · 点击空白处应用")

            self.preview.show(planned)
            self.planned = planned
            self.preview_radius = radius
            self.status.setStyleSheet("color: #50d6bb;")
            self.apply_button.setEnabled(True)
            return True

        except Exception as error:
            self.planned = None
            self.preview.clear()
            self.status.setStyleSheet("color: #e78f70;")
            self.status.setText(f"计算失败: {error}")
            self.apply_button.setEnabled(False)
            return False

    def apply(self, quiet=False):
        if not self.update_preview() and self.current_distance > geo.EPS:
            return
        try:
            self.preview.clear()
            changed = False
            if self.current_distance > geo.EPS and self.planned:
                if self.mode == "fillet":
                    changed = ops.commit_rounding(self.targets, self.planned, self.preview_radius)
                else:
                    self.doc.openTransaction("倒斜角 (Chamfer)")
                    for obj, new_shape in self.planned:
                        obj.Shape = new_shape
                    self.doc.commitTransaction()
                    self.doc.recompute()
                    changed = True

            objects = [obj for obj, _ in (self.planned or self.targets)]
            self.controller.cancel(quiet=True)
            if changed and not quiet:
                Gui.Selection.clearSelection()
                for obj in objects:
                    Gui.Selection.addSelection(obj)
            self.controller.focus_view()
            if not quiet:
                mode_desc = "倒圆角" if self.mode == "fillet" else f"倒斜角 ({self.chamfer_angle:g}°)"
                self.controller.message(f"{mode_desc} 完成 · 按 Ctrl/⌘+Z 撤销并重新微调")
        except Exception as error:
            self.planned = None
            self.status.setText(str(error))
            self.apply_button.setEnabled(False)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.pending.stop()
        if self._cb and hasattr(self.controller.view, 'removeEventCallbackPivy'):
            try:
                self.controller.view.removeEventCallbackPivy(coin.SoEvent.getClassTypeId(), self._cb)
            except Exception:
                pass
            self._cb = None
        if self.arrow:
            self.arrow.close()
            self.arrow = None
        self.preview.close()
        self.dialog.blockSignals(True)
        self.dialog.close()
        self.dialog.deleteLater()