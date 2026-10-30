"""沿 X、Y 或 Z 轴镜像完整对象的对话框。"""
import FreeCAD as App
import FreeCADGui as Gui
from ...document import operations as ops
from ..qt import QtWidgets
from ..panels import anchor_panel

PLANES = (('Center', '所选内容中心 (原地翻转)'),
          ('Max', '所选边界侧面，正向 (+ 侧相邻生成副本)'),
          ('Min', '所选边界侧面，负向 (− 侧相邻生成副本)'),
          ('Origin', '世界坐标原点 (0, 0, 0)'))


class MirrorDialog(QtWidgets.QDialog):
    def __init__(self, objects, parent=None):
        super().__init__(parent)
        self.setWindowTitle('镜像')
        self.setObjectName('SimpleCADMirror')
        layout = QtWidgets.QVBoxLayout(self)
        count = len(objects)
        layout.addWidget(QtWidgets.QLabel(objects[0].Label if count == 1 else '共 %d 个对象，作为一个整体镜像' % count))
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)
        self.axis = QtWidgets.QComboBox()
        self.axis.setObjectName('SimpleCADMirrorAxis')
        for axis, plane in (('X', 'YZ'), ('Y', 'XZ'), ('Z', 'XY')):
            self.axis.addItem('%s 轴  ·  跨越 %s 平面翻转' % (axis, plane), axis)
        form.addRow('镜像基准轴', self.axis)
        self.plane = QtWidgets.QComboBox()
        self.plane.setObjectName('SimpleCADMirrorPlane')
        for key, text in PLANES:
            self.plane.addItem(text, key)
        form.addRow('对称平面位置', self.plane)
        self.original = QtWidgets.QCheckBox('直接镜像原对象（不创建副本）')
        self.original.setObjectName('SimpleCADMirrorOriginal')
        layout.addWidget(self.original)
        hint = QtWidgets.QLabel('默认创建镜像副本并保留原始对象。'
                                '表面颜色和隐藏面属性将完整保留。支持一步撤销。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('镜像')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setMinimumWidth(420)

    def values(self):
        return self.axis.currentData(), self.plane.currentData(), not self.original.isChecked()


def show(controller):
    objects = controller.selected()
    if App.ActiveDocument is None or not objects:
        raise ValueError('请先选择要镜像的对象，然后再选择【镜像】。')
    for obj in objects:
        ops.editable(obj)
    dialog = MirrorDialog(objects, Gui.getMainWindow())
    try:
        if anchor_panel(dialog).exec() != QtWidgets.QDialog.Accepted:
            controller.message('已取消镜像')
            return
        axis, through, copy = dialog.values()
    finally:
        dialog.deleteLater()
    results = ops.mirror(objects, axis, copy=copy, through=through)
    Gui.Selection.clearSelection()
    for obj in results:
        Gui.Selection.addSelection(obj)
    controller.faces.refresh()
    msg = ('已创建 %d 个镜像副本' % len(results)) if copy else ('已沿 %s 轴镜像原对象' % axis)
    controller.message(msg + ' · 可按 Ctrl+Z / ⌘Z 撤销')