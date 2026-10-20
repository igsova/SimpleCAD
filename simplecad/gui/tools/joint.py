"""Optional print-joint controls inside the Slice / Separate panel."""
from ...core import geometry as geo
from ...modeling import joints
from ..qt import QtCore, QtWidgets

# Rows follow the cut face's long direction; grids add a second row across it.
PATTERNS = (("One stud", 1, False), ("Two in a row", 2, False), ("Three in a row", 3, False),
            ("Four in a row", 4, False), ("Five in a row", 5, False), ("Six in a row", 6, False),
            ("Four (2 × 2 grid)", 4, True), ("Six (2 × 3 grid)", 6, True))


class JointControls(QtWidgets.QWidget):
    def __init__(self, changed, make_test, parent=None):
        super().__init__(parent)
        self.setObjectName("SimpleCADJointControls")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.enabled = QtWidgets.QCheckBox("Add studs and sockets", self)
        layout.addWidget(self.enabled)
        self.body = QtWidgets.QWidget(self)
        body = QtWidgets.QVBoxLayout(self.body)
        body.setContentsMargins(8, 0, 0, 0)
        form = QtWidgets.QFormLayout()
        self.pattern = QtWidgets.QComboBox(self)
        for label, count, grid in PATTERNS:
            self.pattern.addItem(label, (count, grid))
        self.pattern.setCurrentIndex(1)
        form.addRow("Pattern", self.pattern)
        self.fields = {}
        for key, label, value in (("diameter", "Stud diameter", "6 mm"),
                                  ("length", "Stud length", "4 mm"),
                                  ("clearance", "Fit clearance per side", "0.10 mm")):
            self.add_length(form, key, label, value)
        body.addLayout(form)
        note = QtWidgets.QLabel("Positive clearance = looser · negative = tighter\nPLA / PETG: print a fit test before the full model.", self)
        note.setWordWrap(True)
        body.addWidget(note)
        self.flip = QtWidgets.QCheckBox("Put studs on the other side", self)
        body.addWidget(self.flip)
        self.more = QtWidgets.QToolButton(self)
        self.more.setText("Layout and wall")
        self.more.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.more.setArrowType(QtCore.Qt.RightArrow)
        self.more.setCheckable(True)
        body.addWidget(self.more)
        self.details = QtWidgets.QWidget(self)
        detail_form = QtWidgets.QFormLayout(self.details)
        detail_form.setContentsMargins(0, 0, 0, 0)
        for key, label, value in (("spacing", "Stud spacing (centers)", "Auto"),
                                  ("across", "Move along the row", "0 mm"),
                                  ("up", "Move across the row", "0 mm"),
                                  ("wall", "Minimum surrounding wall", "1.2 mm")):
            self.add_length(detail_form, key, label, value)
        body.addWidget(self.details)
        self.details.hide()
        self.test_button = QtWidgets.QPushButton("Make a fit test", self)
        self.test_button.setAutoDefault(False)
        self.test_button.setToolTip("Open a separate document with three small stud/socket pairs, 0.10 mm tighter and looser than this fit.")
        self.test_button.clicked.connect(make_test)
        body.addWidget(self.test_button)
        layout.addWidget(self.body)
        self.body.hide()
        self.enabled.toggled.connect(self.body.setVisible)
        self.enabled.toggled.connect(changed)
        self.pattern.currentIndexChanged.connect(changed)
        self.flip.toggled.connect(changed)
        for field in self.fields.values():
            field.textChanged.connect(changed)
        self.more.toggled.connect(self.expand)

    def add_length(self, form, key, label, value):
        field = QtWidgets.QLineEdit(value, self)
        field.setObjectName("SimpleCADJoint_" + key)
        self.fields[key] = field
        form.addRow(label, field)

    def expand(self, expanded):
        self.more.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)
        self.details.setVisible(expanded)

    def parameters(self):
        values = {}
        for key, field in self.fields.items():
            text = field.text().strip()
            # Auto (or empty) spreads the studs evenly over the cut face.
            values[key] = 0.0 if key == "spacing" and text.lower() in ("", "auto") else geo.parse_length(text)
        count, grid = self.pattern.currentData()
        return joints.StudJoint(**values, count=count, grid=grid, flip=self.flip.isChecked()).validate()
