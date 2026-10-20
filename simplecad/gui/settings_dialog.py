"""Small persistent settings dialog, available even without an open model."""
from .. import ROOT
from ..core import preferences
from .qt import QtGui, QtWidgets


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SimpleCAD settings")
        self.setObjectName("SimpleCADSettings")
        # FreeCAD's stylesheet can lose its checkmark resource in an embedded
        # Qt runtime. Bundle this small indicator so on/off is always evident.
        check_icon = (ROOT / "Resources" / "icons" / "checked.svg").as_posix()
        self.setStyleSheet('QCheckBox::indicator { width: 16px; height: 16px; } '
                           'QCheckBox::indicator:checked { image: url("' + check_icon + '"); }')
        layout = QtWidgets.QVBoxLayout(self)
        display = QtWidgets.QGroupBox("Display", self)
        display_layout = QtWidgets.QVBoxLayout(display)
        self.show_seams = QtWidgets.QCheckBox("Show seams on curved surfaces", display)
        display_layout.addWidget(self.show_seams)
        note = QtWidgets.QLabel("Seams stay protected from deletion, even when visible.", display)
        note.setWordWrap(True)
        display_layout.addWidget(note)
        self.viewport_style = QtWidgets.QCheckBox("Dark viewport with ground grid and axes", display)
        self.viewport_style.setToolTip("Changes only how views look while SimpleCAD is active. Models and saved "
                                       "colors are unchanged; FreeCAD's own look returns when this is off.")
        display_layout.addWidget(self.viewport_style)
        face_row = QtWidgets.QHBoxLayout()
        face_row.setContentsMargins(24, 0, 0, 0)
        self.face_label = QtWidgets.QLabel("Face color", display)
        face_row.addWidget(self.face_label)
        self.face_button = QtWidgets.QPushButton(display)
        self.face_button.setObjectName("SimpleCADFaceColor")
        self.face_button.setToolTip("Faces without a color of their own are drawn in this color in the dark "
                                    "viewport. Colors you set on faces are kept, and nothing is saved in models.")
        self.face_button.clicked.connect(self.choose_face_color)
        face_row.addWidget(self.face_button)
        face_row.addStretch(1)
        display_layout.addLayout(face_row)
        self.viewport_style.toggled.connect(self.face_label.setEnabled)
        self.viewport_style.toggled.connect(self.face_button.setEnabled)
        self.face_color = preferences.Settings.face_color
        layout.addWidget(display)
        modeling = QtWidgets.QGroupBox("Modeling", self)
        modeling_layout = QtWidgets.QFormLayout(modeling)
        self.precision = QtWidgets.QDoubleSpinBox(modeling)
        self.precision.setRange(*preferences.RANGES["precision"])
        self.precision.setDecimals(3)
        self.precision.setSingleStep(0.01)
        self.precision.setSuffix(" mm")
        self.precision.setToolTip("Details smaller than this are treated as noise: mesh conversion flattens and "
                                  "aligns surfaces within it, and edits ignore slivers below it.")
        modeling_layout.addRow("Precision", self.precision)
        precision_note = QtWidgets.QLabel(
            "Used for new mesh conversions and Push/Pull. Already converted models keep their geometry.", modeling)
        precision_note.setWordWrap(True)
        modeling_layout.addRow(precision_note)
        layout.addWidget(modeling)
        snapping = QtWidgets.QGroupBox("Snapping", self)
        grid = QtWidgets.QGridLayout(snapping)
        grid.addWidget(QtWidgets.QLabel("Snap to"), 0, 0)
        grid.addWidget(QtWidgets.QLabel("Capture distance"), 0, 1)
        self.checks = {}
        self.radii = {}
        for row, (name, label, radius) in enumerate((
            ("endpoints", "Endpoints (vertices)", "endpoint_radius"),
            ("midpoints", "Edge midpoints", "midpoint_radius"),
            ("edges", "Points on edges and axis crossings", "edge_radius"),
            ("centers", "Face and circle centers", "center_radius"),
            ("axes", "Automatic axis alignment", "axis_radius"),
            ("pull_faces", "Push/Pull to faces and edge levels", "pull_radius"),
        ), 1):
            check = QtWidgets.QCheckBox(label, snapping)
            spin = QtWidgets.QSpinBox(snapping)
            spin.setRange(*preferences.RANGES[radius])
            spin.setSuffix(" px")
            spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
            spin.setToolTip("How close the pointer must be to capture this target.")
            check.toggled.connect(spin.setEnabled)
            grid.addWidget(check, row, 0)
            grid.addWidget(spin, row, 1)
            self.checks[name], self.radii[radius] = check, spin
        layout.addWidget(snapping)
        help_text = QtWidgets.QLabel(
            "Larger distances make snapping easier. Center and midpoint guides follow their snap switches. "
            "X/Y/Z key locks still work when automatic alignment is off.", self)
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel |
            QtWidgets.QDialogButtonBox.RestoreDefaults, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QtWidgets.QDialogButtonBox.RestoreDefaults).clicked.connect(
            lambda: self.set_values(preferences.Settings()))
        layout.addWidget(buttons)
        self.set_values(preferences.load())
        self.setMinimumWidth(420)

    def set_face_color(self, text):
        self.face_color = preferences.color_text(text)
        self.face_button.setText(self.face_color)
        # Dark text on light swatches, light text on dark ones.
        red, green, blue = preferences.color(self.face_color)
        ink = "#000000" if 0.299*red + 0.587*green + 0.114*blue > 0.55 else "#FFFFFF"
        self.face_button.setStyleSheet("QPushButton#SimpleCADFaceColor { background-color: %s; color: %s; "
                                       "border: 1px solid #808080; border-radius: 4px; padding: 3px 14px; }"
                                       % (self.face_color, ink))

    def choose_face_color(self):
        chosen = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.face_color), self, "Face color")
        if chosen.isValid():
            self.set_face_color(chosen.name())

    def set_values(self, settings):
        self.show_seams.setChecked(settings.show_seams)
        self.viewport_style.setChecked(settings.viewport_style)
        self.set_face_color(settings.face_color)
        self.face_label.setEnabled(settings.viewport_style)
        self.face_button.setEnabled(settings.viewport_style)
        self.precision.setValue(settings.precision)
        for name, widget in self.checks.items():
            widget.setChecked(getattr(settings, name))
        for name, widget in self.radii.items():
            widget.setValue(getattr(settings, name))
        for name, radius in (("endpoints", "endpoint_radius"), ("midpoints", "midpoint_radius"), ("edges", "edge_radius"),
                             ("centers", "center_radius"), ("axes", "axis_radius"),
                             ("pull_faces", "pull_radius")):
            self.radii[radius].setEnabled(self.checks[name].isChecked())

    def values(self):
        return preferences.Settings(show_seams=self.show_seams.isChecked(), viewport_style=self.viewport_style.isChecked(),
                                    face_color=self.face_color, precision=self.precision.value(),
                                    **{key: widget.isChecked() for key, widget in self.checks.items()},
                                    **{key: widget.value() for key, widget in self.radii.items()})
