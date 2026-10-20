"""Pick a face/hole, drag along a direction or use the dialog to elongate into an ellipse or slot."""
import math
import FreeCAD as App
import FreeCADGui as Gui
import Part
from ...core import geometry as g
from ...document import operations as ops, locking
from ...modeling.elongating import ElongateProfile
from ..snapping import pick, ray
from ..previews.overlay import edges, outline
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel
V = App.Vector


def parse_angle_deg(text):
    cleaned = text.strip().removesuffix('deg').removesuffix('°').strip()
    if not cleaned:
        raise ValueError('Enter an angle, e.g. 0° or 45°.')
    val = float(cleaned)
    if not math.isfinite(val):
        raise ValueError('Invalid angle.')
    return val


class ElongateDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.updating = False
        self.setObjectName("SimpleCADElongate")
        self.setWindowTitle("Elongate")
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        self.setMinimumWidth(360)
        self.init_ui()

    def dialog_header_text(self):
        profile = self.owner.profile
        name = self.owner.name or ""
        if profile is None:
            return "Elongate Selection"
        if profile.is_cylinder:
            return f"Cylindrical hole {name} · Radius {profile.radius:.2f} mm"
        elif profile.is_circle:
            return f"Circular rim {name} · Radius {profile.radius:.2f} mm"
        elif profile.is_face:
            return f"Planar face {name} · Area {profile.source.Area:.1f} mm²"
        return f"Element {name}"

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        self.target_label = QtWidgets.QLabel(self.dialog_header_text())
        self.target_label.setStyleSheet("font-weight: bold; color: #50d6bb;")
        layout.addWidget(self.target_label)

        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        # Distance input
        self.dist_edit = QtWidgets.QLineEdit()
        self.dist_edit.setObjectName("SimpleCADElongateDistance")
        self.dist_edit.setPlaceholderText("e.g. 5.0 mm")
        if self.owner.distance > g.EPS:
            self.dist_edit.setText(f"{self.owner.distance:.2f} mm")
        form.addRow("Distance", self.dist_edit)

        # Distance quick preset buttons
        dist_buttons_layout = QtWidgets.QHBoxLayout()
        for d_inc in (1, 2, 5, 10):
            btn = QtWidgets.QPushButton(f"+{d_inc} mm")
            btn.setAutoDefault(False)
            btn.clicked.connect(lambda unused=False, inc=d_inc: self.add_distance(inc))
            dist_buttons_layout.addWidget(btn)
        btn_reset_dist = QtWidgets.QPushButton("Reset")
        btn_reset_dist.setAutoDefault(False)
        btn_reset_dist.clicked.connect(self.reset_distance)
        dist_buttons_layout.addWidget(btn_reset_dist)
        layout.addLayout(dist_buttons_layout)

        # Direction / Angle input
        self.angle_edit = QtWidgets.QLineEdit(f"{self.owner.angle_deg:.1f}°")
        self.angle_edit.setObjectName("SimpleCADElongateAngle")
        self.angle_edit.setPlaceholderText("0° .. 360°")
        form.addRow("Direction", self.angle_edit)

        # Angle slider
        self.angle_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.angle_slider.setObjectName("SimpleCADElongateSlider")
        self.angle_slider.setRange(0, 359)
        self.angle_slider.setTickInterval(45)
        self.angle_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.angle_slider.setValue(round(self.owner.angle_deg) % 360)
        self.angle_slider.setStyleSheet("QSlider::groove:horizontal { height: 4px; background: #555; border-radius: 2px; } "
                                       "QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #50d6bb; border-radius: 7px; }")
        layout.addWidget(self.angle_slider)

        # Direction angle presets
        angle_presets_layout = QtWidgets.QHBoxLayout()
        for deg in (0, 45, 90, 180, 270):
            btn = QtWidgets.QPushButton(f"{deg}°")
            btn.setAutoDefault(False)
            btn.clicked.connect(lambda unused=False, val=deg: self.set_preset_angle(val))
            angle_presets_layout.addWidget(btn)
        flip_btn = QtWidgets.QPushButton("Flip (180°)")
        flip_btn.setAutoDefault(False)
        flip_btn.clicked.connect(self.flip_angle)
        angle_presets_layout.addWidget(flip_btn)
        layout.addLayout(angle_presets_layout)

        # Mode
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.setObjectName("SimpleCADElongateMode")
        self.mode_combo.addItem("Ellipse (smooth)", "ellipse")
        self.mode_combo.addItem("Slot (stadium)", "slot")
        if self.owner.mode == "slot":
            self.mode_combo.setCurrentIndex(1)
        form.addRow("Mode", self.mode_combo)

        # Symmetry
        self.symmetric_check = QtWidgets.QCheckBox("Symmetrical (both sides)")
        self.symmetric_check.setObjectName("SimpleCADElongateSymmetric")
        self.symmetric_check.setChecked(self.owner.symmetric)
        self.symmetric_check.setToolTip("Checked: extends symmetrically both ways. Unchecked: extends only toward the angle direction, keeping the opposite side anchored.")
        layout.addWidget(self.symmetric_check)

        # Cut hole
        self.cut_hole_check = QtWidgets.QCheckBox("Cut hole through solid")
        self.cut_hole_check.setObjectName("SimpleCADElongateCutHole")
        self.cut_hole_check.setChecked(self.owner.cut_hole)
        self.cut_hole_check.setToolTip("Cuts an elongated hole completely through the solid body.")
        is_solid = bool(getattr(self.owner.obj.Shape, 'Solids', None)) if (self.owner.obj and hasattr(self.owner.obj, 'Shape')) else False
        self.cut_hole_check.setVisible(is_solid)
        layout.addWidget(self.cut_hole_check)

        # Status
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(self.status.fontMetrics().lineSpacing() * 2)
        layout.addWidget(self.status)

        # ButtonBox
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.Apply)
        self.apply_button.setAutoDefault(False)
        self.apply_button.setEnabled(self.owner.distance > g.EPS)
        self.apply_button.clicked.connect(self.apply)
        buttons.rejected.connect(self.owner.c.cancel)
        self.rejected.connect(self.owner.c.cancel)
        layout.addWidget(buttons)

        # Connect signals
        self.dist_edit.textEdited.connect(self.on_distance_edited)
        self.dist_edit.returnPressed.connect(self.apply)
        self.angle_edit.textEdited.connect(self.on_angle_edited)
        self.angle_edit.returnPressed.connect(self.apply)
        self.angle_slider.valueChanged.connect(self.on_slider_changed)
        self.symmetric_check.toggled.connect(self.on_symmetric_toggled)
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        self.cut_hole_check.toggled.connect(self.on_cut_hole_toggled)

    def on_distance_edited(self, text):
        if self.updating:
            return
        try:
            cleaned = text.strip().removeprefix('+')
            if not cleaned:
                self.owner.distance = 0.0
            else:
                self.owner.distance = max(0.0, g.parse_length(cleaned))
            self.owner.refresh()
        except Exception:
            pass

    def on_angle_edited(self, text):
        if self.updating:
            return
        try:
            val = parse_angle_deg(text)
            self.owner.set_angle(val)
            self.angle_slider.blockSignals(True)
            self.angle_slider.setValue(round(self.owner.angle_deg) % 360)
            self.angle_slider.blockSignals(False)
            self.owner.refresh()
        except Exception:
            pass

    def on_slider_changed(self, val):
        if self.updating:
            return
        self.owner.set_angle(val)
        self.angle_edit.blockSignals(True)
        self.angle_edit.setText(f"{val}°")
        self.angle_edit.blockSignals(False)
        self.owner.refresh()

    def set_preset_angle(self, deg):
        self.owner.set_angle(deg)
        self.angle_edit.setText(f"{deg % 360}°")
        self.angle_slider.blockSignals(True)
        self.angle_slider.setValue(round(self.owner.angle_deg) % 360)
        self.angle_slider.blockSignals(False)
        self.owner.refresh()

    def flip_angle(self):
        new_angle = (self.owner.angle_deg + 180.0) % 360.0
        self.set_preset_angle(round(new_angle))

    def add_distance(self, delta):
        self.owner.distance = max(0.0, self.owner.distance + delta)
        self.dist_edit.setText(f"{self.owner.distance:.2f} mm")
        self.owner.refresh()

    def reset_distance(self):
        self.owner.distance = 0.0
        self.dist_edit.clear()
        self.owner.refresh()

    def on_symmetric_toggled(self, checked):
        if self.updating:
            return
        self.owner.symmetric = checked
        self.owner.refresh()

    def on_mode_changed(self, idx):
        if self.updating:
            return
        self.owner.mode = self.mode_combo.currentData()
        if hasattr(self.owner.c, 'controls') and hasattr(self.owner.c.controls, 'elongate_mode'):
            bar_combo = self.owner.c.controls.elongate_mode
            bar_combo.blockSignals(True)
            bar_idx = bar_combo.findText(self.owner.mode.capitalize())
            if bar_idx >= 0:
                bar_combo.setCurrentIndex(bar_idx)
            bar_combo.blockSignals(False)
        self.owner.refresh()

    def on_cut_hole_toggled(self, checked):
        if self.updating:
            return
        self.owner.cut_hole = checked
        self.owner.refresh()

    def update_status(self, text, is_error=False):
        if is_error:
            self.status.setStyleSheet("color: #e78f70;")
        else:
            self.status.setStyleSheet("")
        self.status.setText(text)

    def sync_from_input(self):
        if self.updating:
            return
        self.updating = True
        try:
            if not self.dist_edit.hasFocus():
                if self.owner.distance > g.EPS:
                    self.dist_edit.setText(f"{self.owner.distance:.2f} mm")
                else:
                    self.dist_edit.clear()
            if not self.angle_edit.hasFocus():
                self.angle_edit.setText(f"{self.owner.angle_deg:.1f}°")
            self.angle_slider.blockSignals(True)
            self.angle_slider.setValue(round(self.owner.angle_deg) % 360)
            self.angle_slider.blockSignals(False)
            self.symmetric_check.blockSignals(True)
            self.symmetric_check.setChecked(self.owner.symmetric)
            self.symmetric_check.blockSignals(False)
            self.mode_combo.blockSignals(True)
            idx = self.mode_combo.findData(self.owner.mode)
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
            self.mode_combo.blockSignals(False)
            self.cut_hole_check.blockSignals(True)
            self.cut_hole_check.setChecked(self.owner.cut_hole)
            self.cut_hole_check.blockSignals(False)
        finally:
            self.updating = False

    def apply(self):
        if self.owner.distance < g.EPS:
            self.update_status("Enter a distance greater than 0 mm.", is_error=True)
            return
        if not self.owner.refresh(raise_error=False):
            return
        self.owner.c.commit()


class ElongateInput:
    def __init__(self, controller):
        self.c = controller
        self.obj = None
        self.name = None
        self.original = None
        self.profile = None
        self.distance = 0.0
        self.direction = V(1, 0, 0)
        self.angle_deg = 0.0
        self.mode = 'ellipse'
        self.symmetric = True
        self.cut_hole = False
        self.dialog = None
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
        if hasattr(self.c, 'controls') and self.c.controls and hasattr(self.c.controls, 'elongate_mode'):
            self.c.controls.elongate_mode.hide()

    def check(self):
        if self.obj is None:
            return
        try:
            if not self.obj.Shape.isSame(self.original):
                raise ValueError()
        except Exception as error:
            raise ValueError('The source changed. Start Elongate again.') from error

    def set_angle(self, deg):
        self.angle_deg = float(deg) % 360.0
        ref_u = getattr(self.profile.plane, 'u', V(1, 0, 0))
        ref_v = getattr(self.profile.plane, 'v', self.profile.plane.normal.cross(ref_u).normalize())
        rad = math.radians(self.angle_deg)
        self.direction = g.unit(ref_u * math.cos(rad) + ref_v * math.sin(rad))

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
        self.dialog = ElongateDialog(self, parent)
        anchor_panel(self.dialog).show()
        self.dialog.dist_edit.setFocus()
        self.dialog.dist_edit.selectAll()

    def choose(self, obj, name, point):
        c = self.c
        ops.editable(obj)
        if (obj.Label.startswith('Elongated ') or obj.Name.startswith('SimpleShape')) and not obj.Shape.Solids and not obj.Shape.Faces:
            if ops.heal_dangling_elongations(obj.Document):
                c.message("Integrated elongation into solid")
                return
        source = obj.Shape.getElement(name)
        normal = None
        if source.ShapeType == 'Edge' and isinstance(getattr(source, 'Curve', None), Part.Line):
            raise ValueError('Elongate supports circular edges, cylindrical holes, and planar faces.')

        if source.ShapeType == 'Edge':
            adjacent = [f for f in obj.Shape.ancestorsOfType(source, Part.Face) if isinstance(f.Surface, Part.Plane)]
            if adjacent:
                face = max(adjacent, key=lambda f: abs(g.face_normal(f).dot(c.view.getViewDirection())))
                normal = g.face_normal(face)
        elif source.ShapeType == 'Face' and isinstance(getattr(source, 'Surface', None), Part.Cylinder):
            adjacent = []
            for e in source.Edges:
                for f in obj.Shape.ancestorsOfType(e, Part.Face):
                    if not f.isSame(source) and isinstance(f.Surface, Part.Plane):
                        if not any(f.isSame(existing) for existing in adjacent):
                            adjacent.append(f)
            if adjacent:
                if point is not None:
                    face = min(adjacent, key=lambda f: (f.CenterOfMass - point).Length)
                else:
                    face = max(adjacent, key=lambda f: abs(g.face_normal(f).dot(c.view.getViewDirection())))
                normal = g.face_normal(face)
            else:
                normal = g.unit(source.Surface.Axis)

        profile = ElongateProfile(source, normal, point=point)
        if profile.is_face:
            locking.require_unlocked(obj, [name])

        self.obj, self.name, self.original, self.profile = obj, name, obj.Shape, profile
        self.distance = 0.0
        ref_u = getattr(profile.plane, 'u', V(1, 0, 0))
        self.direction = g.unit(ref_u)
        self.angle_deg = 0.0
        self.symmetric = True
        self.cut_hole = False

        if hasattr(c, 'controls') and hasattr(c.controls, 'elongate_mode'):
            self.mode = c.controls.elongate_mode.currentText().lower()
            c.controls.elongate_mode.show()
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', RuntimeWarning)
                try:
                    c.controls.elongate_mode.currentIndexChanged.disconnect()
                except Exception:
                    pass
            c.controls.elongate_mode.currentIndexChanged.connect(self.mode_changed)

        c.anchor = profile.center
        c.plane = profile.plane
        Gui.Selection.clearSelection()
        Gui.Selection.clearPreselection()
        c.preview.update(edges(source), point=profile.center)
        c.controls.value.setPlaceholderText('Elongation distance (Tab)')
        c.message('Drag in any direction or use the dialog to elongate · Click / Apply to keep · Esc cancels')
        self.open_dialog()

    def mode_changed(self):
        if hasattr(self.c.controls, 'elongate_mode'):
            self.mode = self.c.controls.elongate_mode.currentText().lower()
            if self.dialog:
                self.dialog.mode_combo.blockSignals(True)
                idx = self.dialog.mode_combo.findData(self.mode)
                if idx >= 0:
                    self.dialog.mode_combo.setCurrentIndex(idx)
                self.dialog.mode_combo.blockSignals(False)
            self.refresh()

    def hover(self, pos):
        hit = pick(self.c.view, self.c.doc, pos, prefer_boundary=True)
        if hit and hit[1].ShapeType in ('Face', 'Edge'):
            self.c.preview.update(outline(hit[1]), hit[2])
        else:
            self.c.preview.update()
        return hit

    def click(self, pos):
        if self.obj is None:
            hit = self.hover(pos)
            if not hit or hit[1].ShapeType not in ('Face', 'Edge'):
                raise ValueError('Click a circular hole, hole rim, or planar face.')
            self.choose(hit[0], hit[3], hit[2])
            return False
        self.motion(pos)
        self.refresh(raise_error=True)
        return True

    def motion(self, pos):
        if self.obj is None:
            self.hover(pos)
            return
        self.check()
        point = self.profile.plane.intersect(*ray(self.c.view, pos))
        dir_vec, dist = self.profile.direction_at(point)
        if dist > g.EPS:
            ref_u = getattr(self.profile.plane, 'u', V(1, 0, 0))
            ref_v = getattr(self.profile.plane, 'v', self.profile.plane.normal.cross(ref_u).normalize())
            angle_rad = math.atan2(dir_vec.dot(ref_v), dir_vec.dot(ref_u))
            angle_deg = math.degrees(angle_rad) % 360
            snapped = round(angle_deg / 15.0) * 15.0
            if abs(angle_deg - snapped) < 3.0:
                angle_deg = snapped % 360
                angle_rad = math.radians(angle_deg)
                dir_vec = g.unit(ref_u * math.cos(angle_rad) + ref_v * math.sin(angle_rad))
            self.direction = dir_vec
            self.angle_deg = angle_deg
            self.distance = max(0.0, dist - self.profile.radius)
        if not self.timer.isActive():
            self.timer.start(30)

    def refresh(self, raise_error=False):
        self.timer.stop()
        self.planned = None
        try:
            self.check()
            if abs(self.distance) < g.EPS:
                self.c.preview.update(edges(self.profile.source), point=self.profile.center)
                if self.dialog:
                    self.dialog.sync_from_input()
                    self.dialog.update_status("Move the mouse, type a distance, or click a preset to elongate.", is_error=False)
                    self.dialog.apply_button.setEnabled(False)
                raise ValueError('Move away from the center to set an elongation.')
            self.planned = self.profile.elongate(self.distance, self.direction, mode=self.mode, symmetric=self.symmetric)
            preview_lines = edges(self.planned)
            axis_len = (self.profile.radius + self.distance) * 1.3
            if self.symmetric:
                axis_line = [self.profile.center - self.direction * axis_len,
                             self.profile.center + self.direction * axis_len]
            else:
                axis_line = [self.profile.center - self.direction * self.profile.radius,
                             self.profile.center + self.direction * axis_len]
            self.c.preview.update(preview_lines + [axis_line], point=self.profile.center)
            shape_label = 'Ellipse' if self.mode == 'ellipse' else 'Slot'
            sym_label = '' if self.symmetric else ' · 1-sided'
            self.c.controls.label.setText('%s +%.3g mm (%.1f°%s)' % (shape_label, self.distance, self.angle_deg, sym_label))
            self.c.controls.value.setPlaceholderText('%.3g mm · %.1f°' % (self.distance, self.angle_deg))
            if self.dialog:
                self.dialog.sync_from_input()
                self.dialog.update_status('Preview: %s +%.3g mm at %.1f°%s · Apply to keep · Esc cancels' %
                                          (shape_label, self.distance, self.angle_deg, sym_label), is_error=False)
                self.dialog.apply_button.setEnabled(True)
            return True
        except Exception as error:
            self.c.preview.update(edges(self.profile.source), point=self.profile.center)
            self.c.controls.label.setText('Elongate unavailable')
            if self.dialog:
                self.dialog.update_status(str(error), is_error=True)
                self.dialog.apply_button.setEnabled(False)
            if raise_error:
                raise
            self.c.message(str(error) + ' · Esc to cancel')
            return False

    def numeric(self, text):
        cleaned = text.strip()
        if '@' in cleaned:
            parts = cleaned.split('@')
            dist_str = parts[0].strip()
            ang_str = parts[1].strip().removesuffix('deg').removesuffix('°')
            self.distance = g.parse_length(dist_str)
            self.set_angle(float(ang_str))
        else:
            self.distance = g.parse_length(cleaned.removeprefix('+'))
        if self.dialog:
            self.dialog.sync_from_input()
        self.refresh(raise_error=True)

    def commit(self):
        self.check()
        return ops.elongate(self.obj, self.name, self.distance, self.direction,
                            mode=self.mode, cut_hole=self.cut_hole, symmetric=self.symmetric,
                            point=getattr(self.profile, 'center', None))
