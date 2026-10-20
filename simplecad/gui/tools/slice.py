"""Choose a cut plane, preview a position and optional gap, then apply once."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from ... import ROOT
from ...core import geometry as geo
from ...document import operations as ops
from ...modeling import slicing
from ..previews.slice import SlicePreview
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel

FACE_ITEM = "Selected face"


class SliceSession:
    def __init__(self, controller, targets, selection):
        self.controller, self.targets, self.selection = controller, targets, selection
        self.doc = targets[0][0].Document
        self.closed = False
        self.cut_key = None
        self.cut_pieces = None
        self.joint_key = None
        self.joint_pieces = None
        self.planned = None
        self.face_normal = None
        self.pick_callback = None
        self.preview = SlicePreview(controller.view)
        self.dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self.dialog.setObjectName("SimpleCADSlice")
        self.dialog.setWindowTitle("Slice / Separate")
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        check_icon = (ROOT / "Resources" / "icons" / "checked.svg").as_posix()
        self.dialog.setStyleSheet('QCheckBox::indicator { width: 16px; height: 16px; } '
                                 'QCheckBox::indicator:checked { image: url("' + check_icon + '"); }')
        layout = QtWidgets.QVBoxLayout(self.dialog)
        self.axis = QtWidgets.QComboBox(self.dialog)
        self.axis.setObjectName("SimpleCADSliceAxis")
        for text, key in (("Object main axis", "Main"), ("X — YZ plane", "X"),
                          ("Y — XZ plane", "Y"), ("Z — XY plane", "Z")):
            self.axis.addItem(text, key)
        layout.addWidget(QtWidgets.QLabel("Cut across"))
        layout.addWidget(self.axis)
        self.pick_button = QtWidgets.QPushButton("Pick face", self.dialog)
        self.pick_button.setObjectName("SimpleCADSlicePickFace")
        self.pick_button.setCheckable(True)
        self.pick_button.setAutoDefault(False)
        self.pick_button.setToolTip("Click a flat face in the 3D view to cut exactly on its plane")
        layout.addWidget(self.pick_button)
        self.offset, self.position_slider = self.length_control(layout, "Cut offset from center", "SimpleCADSliceOffset")
        from .joint import JointControls
        self.joint = JointControls(self.changed, self.make_fit_test, self.dialog)
        layout.addWidget(self.joint)
        self.separation = QtWidgets.QCheckBox("Separate pieces", self.dialog)
        layout.addWidget(self.separation)
        self.gap, self.gap_slider = self.length_control(layout, "Gap between sides", "SimpleCADSliceGap")
        self.gap_note = QtWidgets.QLabel("Both sides move equally · 0 mm keeps them touching")
        self.gap_note.setWordWrap(True)
        layout.addWidget(self.gap_note)
        self.status = QtWidgets.QLabel(self.dialog)
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(self.status.fontMetrics().lineSpacing() * 3)
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
        self.pick_button.toggled.connect(self.toggle_picking)
        self.offset.textChanged.connect(self.changed)
        self.gap.textChanged.connect(self.changed)
        self.offset.returnPressed.connect(self.apply)
        self.gap.returnPressed.connect(self.apply)
        self.position_slider.valueChanged.connect(self.slide_position)
        self.gap_slider.valueChanged.connect(self.slide_gap)
        self.separation.toggled.connect(self.toggle_separation)
        self.joint.enabled.toggled.connect(self.joint_toggled)
        for field in self.joint.fields.values():
            field.returnPressed.connect(self.apply)
        self.dialog.setMinimumWidth(360)

    def length_control(self, layout, title, name):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(title))
        value = QtWidgets.QLineEdit(self.dialog)
        value.setObjectName(name)
        row.addWidget(value)
        layout.addLayout(row)
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self.dialog)
        slider.setRange(0, 1000)
        layout.addWidget(slider)
        return value, slider

    def open(self):
        Gui.Selection.clearSelection()
        Gui.Selection.clearPreselection()
        self.axis_changed()
        self.gap.setText("%.6g mm" % (self.plane.size * .1))
        self.toggle_separation(False)
        # A flat face selected with the object sets the cut on that face.
        for obj, names in self.selection:
            faces = [obj.Shape.getElement(name) for name in names if name.startswith("Face")]
            face = next((face for face in faces if isinstance(face.Surface, Part.Plane)), None)
            if face is not None:
                self.use_face(face)
                break
        anchor_panel(self.dialog).show()
        self.update_preview()
        self.offset.setFocus()
        self.offset.selectAll()

    def axis_changed(self, *unused):
        self.plane = slicing.cut_plane([shape for _, shape in self.targets], self.axis.currentData(), self.face_normal)
        self.offset.setText("0 mm")
        self.changed()

    def use_face(self, face):
        """Cut exactly on a flat face: keep the axis when the face is square to it."""
        normal = slicing.face_normal(face)
        if abs(abs(normal.dot(self.plane.normal)) - 1) > 1e-9:
            self.face_normal = normal
            index = self.axis.findData("Face")
            if index < 0:
                self.axis.addItem(FACE_ITEM, "Face")
                index = self.axis.count() - 1
            self.axis.blockSignals(True)
            self.axis.setCurrentIndex(index)
            self.axis.blockSignals(False)
            self.plane = slicing.cut_plane([shape for _, shape in self.targets], "Face", normal)
        self.offset.setText("%.9g mm" % slicing.face_offset(self.plane, face))
        self.changed()

    def toggle_picking(self, enabled):
        view = self.controller.view
        if enabled and self.pick_callback is None:
            from pivy import coin
            # The preview hides the originals; show them so their faces can be clicked.
            self.pending.stop()
            self.preview.clear()
            self.pick_callback = view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.pick_event)
            self.status.setStyleSheet("")
            self.status.setText("Click a flat face in the 3D view · Click Pick face again to stop")
            self.apply_button.setEnabled(False)
        elif not enabled and self.pick_callback is not None:
            from pivy import coin
            view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.pick_callback)
            self.pick_callback = None
            self.changed()

    def pick_event(self, callback):
        from pivy import coin
        from ..snapping import pick
        event = callback.getEvent()
        if event.getButton() != coin.SoMouseButtonEvent.BUTTON1:
            return
        callback.setHandled()
        if event.getState() != coin.SoButtonEvent.DOWN:
            return
        hit = pick(self.controller.view, self.doc, tuple(event.getPosition().getValue()), face_only=True)
        try:
            if hit is None:
                raise ValueError("No face there. Click a flat face of the model.")
            self.use_face(hit[1])
        except ValueError as error:
            self.status.setStyleSheet("color: #e78f70;")
            self.status.setText(str(error))
            return
        self.pick_button.setChecked(False)

    def toggle_separation(self, enabled):
        self.gap.setEnabled(enabled)
        self.gap_slider.setEnabled(enabled)
        self.changed()

    def joint_toggled(self, enabled):
        self.gap_note.setText("Separation is for layout; the joint fit uses its clearance." if enabled else
                              "Both sides move equally · 0 mm keeps them touching")
        if enabled:
            self.separation.setChecked(True)
            try:
                length = geo.parse_length(self.joint.fields["length"].text())
                gap = geo.parse_length(self.gap.text())
                if gap < length + 2:
                    self.gap.setText("%.6g mm" % (length + 2))
            except Exception:
                pass
        self.dialog.adjustSize()

    def changed(self, *unused):
        self.apply_button.setEnabled(False)
        self.pending.start(180)

    def slide_position(self, value):
        self.offset.setText("%.9g mm" % (self.plane.lower + (self.plane.upper - self.plane.lower) * value / 1000))

    def slide_gap(self, value):
        self.gap.setText("%.6g mm" % (self.plane.size * value / 1000))

    @staticmethod
    def sync_slider(slider, value):
        slider.blockSignals(True)
        slider.setValue(round(value))
        slider.blockSignals(False)

    def update_preview(self):
        self.pending.stop()
        if self.closed:
            return False
        if self.pick_callback is not None:
            return False
        try:
            self.controller.check_context()
            if self.closed:
                return False
            ops.check_slicing(self.targets)
            offset = geo.parse_length(self.offset.text())
            gap = geo.parse_length(self.gap.text()) if self.separation.isChecked() else 0.0
            self.preview.show_plane(self.plane, offset)
            span = self.plane.upper - self.plane.lower
            self.sync_slider(self.position_slider, (offset - self.plane.lower) / span * 1000 if span > geo.EPS else 500)
            self.sync_slider(self.gap_slider, gap / self.plane.size * 1000)
            key = (self.axis.currentData(), offset)
            # A gap adjustment only translates the cached cut pieces. The
            # expensive Boolean runs again only when the cutting plane moves.
            if self.cut_pieces is None or key != self.cut_key:
                self.cut_pieces = ops.preview_slicing(self.targets, self.plane, offset)
                self.cut_key = key
            pieces_to_show = self.cut_pieces
            if self.joint.enabled.isChecked():
                params = self.joint.parameters()
                joint_key = (key, params)
                if self.joint_pieces is None or self.joint_key != joint_key:
                    self.joint_pieces = ops.preview_stud_joints(self.cut_pieces, self.plane, offset, params)
                    self.joint_key = joint_key
                pieces_to_show = self.joint_pieces
            self.planned = [(obj, slicing.separate(pieces, self.plane.normal, gap))
                            for obj, pieces in pieces_to_show]
            self.preview.show([(obj, slicing.compound(pieces)) for obj, pieces in self.planned])
            count = sum(len(pieces) for _, pieces in self.planned)
            self.status.setStyleSheet("")
            self.status.setText("%d pieces · gap %.6g mm\nApply to keep · Esc cancels" % (count, gap))
            self.apply_button.setEnabled(True)
            return True
        except Exception as error:
            self.planned = None
            self.preview.clear()
            self.status.setStyleSheet("color: #e78f70;")
            self.status.setText(str(error))
            self.apply_button.setEnabled(False)
            return False

    def make_fit_test(self):
        try:
            params = self.joint.parameters()
            # Preparing samples can fail; keep the current model/session intact
            # until the separate document has been successfully created.
            doc = ops.create_fit_test(params)
            self.controller.cancel(quiet=True)
            App.setActiveDocument(doc.Name)
            view = Gui.activeDocument().activeView()
            view.viewIsometric(); view.fitAll()
            self.controller.message("Fit test: three clearances · Print the matching stud/socket pairs to choose the fit")
        except Exception as error:
            self.status.setText(str(error))

    def apply(self):
        if not self.update_preview():
            return
        try:
            self.preview.clear()
            objects = ops.commit_slicing(self.targets, self.planned)
            self.controller.cancel(quiet=True)
            Gui.Selection.clearSelection()
            for obj in objects:
                Gui.Selection.addSelection(obj)
            self.controller.focus_view()
            self.controller.message("%d separate pieces · Undo with ⌘Z" % len(objects))
        except Exception as error:
            self.planned = None
            self.status.setText(str(error))
            self.apply_button.setEnabled(False)

    def close(self):
        if self.closed:
            return
        self.pick_button.setChecked(False)
        self.closed = True
        self.pending.stop()
        self.preview.close()
        self.dialog.blockSignals(True)
        self.dialog.close()
        self.dialog.deleteLater()
        try:
            ops.check_slicing(self.targets)
            if App.ActiveDocument == self.doc:
                for obj, names in self.selection:
                    for name in names or ("",):
                        Gui.Selection.addSelection(obj, name)
        except (ValueError, RuntimeError, ReferenceError):
            pass
