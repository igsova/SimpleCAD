"""切片 / 分离面板中可选的 3D 打印连接定位销/孔控制组件。"""
from ...core import geometry as geo
from ...modeling import joints
from ..qt import QtCore, QtWidgets

# 单行沿切割截面的长轴方向排列；网格模式则沿横向增加第二行。
PATTERNS = (("单销", 1, False), ("单行 2 个", 2, False), ("单行 3 个", 3, False),
            ("单行 4 个", 4, False), ("单行 5 个", 5, False), ("单行 6 个", 6, False),
            ("4 个 (2 × 2 网格)", 4, True), ("6 个 (2 × 3 网格)", 6, True))


class JointControls(QtWidgets.QWidget):
    def __init__(self, changed, make_test, parent=None):
        super().__init__(parent)
        self.setObjectName("SimpleCADJointControls")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.enabled = QtWidgets.QCheckBox("添加定位销与安装孔 (用于 3D 打印拼接)", self)
        layout.addWidget(self.enabled)
        self.body = QtWidgets.QWidget(self)
        body = QtWidgets.QVBoxLayout(self.body)
        body.setContentsMargins(8, 0, 0, 0)
        form = QtWidgets.QFormLayout()
        self.pattern = QtWidgets.QComboBox(self)
        for label, count, grid in PATTERNS:
            self.pattern.addItem(label, (count, grid))
        self.pattern.setCurrentIndex(1)
        form.addRow("排列模式", self.pattern)
        self.fields = {}
        for key, label, value in (("diameter", "定位销直径", "6 mm"),
                                  ("length", "定位销长度", "4 mm"),
                                  ("clearance", "单侧配合间隙", "0.10 mm")):
            self.add_length(form, key, label, value)
        body.addLayout(form)
        note = QtWidgets.QLabel("正间隙 = 配合更松 · 负间隙 = 配合更紧\nPLA / PETG：建议在打印完整大件前先打印测试样件验证公差。", self)
        note.setWordWrap(True)
        body.addWidget(note)
        self.flip = QtWidgets.QCheckBox("将定位销调换至对侧零件", self)
        body.addWidget(self.flip)
        self.more = QtWidgets.QToolButton(self)
        self.more.setText("间距布局与壁厚")
        self.more.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.more.setArrowType(QtCore.Qt.RightArrow)
        self.more.setCheckable(True)
        body.addWidget(self.more)
        self.details = QtWidgets.QWidget(self)
        detail_form = QtWidgets.QFormLayout(self.details)
        detail_form.setContentsMargins(0, 0, 0, 0)
        for key, label, value in (("spacing", "定位销中心间距", "自动"),
                                  ("across", "沿排布方向偏移", "0 mm"),
                                  ("up", "垂直排布方向偏移", "0 mm"),
                                  ("wall", "最小外围壁厚", "1.2 mm")):
            self.add_length(detail_form, key, label, value)
        body.addWidget(self.details)
        self.details.hide()
        self.test_button = QtWidgets.QPushButton("生成配合测试样件", self)
        self.test_button.setAutoDefault(False)
        self.test_button.setToolTip("在新文档中创建三组小型定位销/孔对（分别比当前间隙紧 0.10 mm、相同、松 0.10 mm），用于快速测试打印公差。")
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
            # 输入“自动”、“auto”（或留空）会将定位销沿切割面均匀分布。
            values[key] = 0.0 if key == "spacing" and text.lower() in ("", "auto", "自动") else geo.parse_length(text)
        count, grid = self.pattern.currentData()
        return joints.StudJoint(**values, count=count, grid=grid, flip=self.flip.isChecked()).validate()