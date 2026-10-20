"""Dialog for mirroring whole objects along X, Y or Z."""
import FreeCAD as App
import FreeCADGui as Gui
from ...document import operations as ops
from ..qt import QtWidgets
from ..panels import anchor_panel

PLANES = (('Center', 'Selection center (flip in place)'),
          ('Max', 'Selection side, + direction (copy lands beside it)'),
          ('Min', 'Selection side, − direction (copy lands beside it)'),
          ('Origin', 'World origin'))


class MirrorDialog(QtWidgets.QDialog):
    def __init__(self, objects, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Mirror')
        self.setObjectName('SimpleCADMirror')
        layout = QtWidgets.QVBoxLayout(self)
        count = len(objects)
        layout.addWidget(QtWidgets.QLabel(objects[0].Label if count == 1 else '%d objects, mirrored together' % count))
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)
        self.axis = QtWidgets.QComboBox()
        self.axis.setObjectName('SimpleCADMirrorAxis')
        for axis, plane in (('X', 'YZ'), ('Y', 'XZ'), ('Z', 'XY')):
            self.axis.addItem('%s  ·  flip across the %s plane' % (axis, plane), axis)
        form.addRow('Mirror along', self.axis)
        self.plane = QtWidgets.QComboBox()
        self.plane.setObjectName('SimpleCADMirrorPlane')
        for key, text in PLANES:
            self.plane.addItem(text, key)
        form.addRow('Plane through', self.plane)
        self.original = QtWidgets.QCheckBox('Mirror the original instead of making a copy')
        self.original.setObjectName('SimpleCADMirrorOriginal')
        layout.addWidget(self.original)
        hint = QtWidgets.QLabel('A mirrored copy is created by default and the original stays as it is. '
                                'Face colors and hidden faces are kept. One Undo step.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Mirror')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setMinimumWidth(420)

    def values(self):
        return self.axis.currentData(), self.plane.currentData(), not self.original.isChecked()


def show(controller):
    objects = controller.selected()
    if App.ActiveDocument is None or not objects:
        raise ValueError('Select the objects to mirror, then choose Mirror.')
    for obj in objects:
        ops.editable(obj)
    dialog = MirrorDialog(objects, Gui.getMainWindow())
    try:
        if anchor_panel(dialog).exec() != QtWidgets.QDialog.Accepted:
            controller.message('Mirror canceled')
            return
        axis, through, copy = dialog.values()
    finally:
        dialog.deleteLater()
    results = ops.mirror(objects, axis, copy=copy, through=through)
    Gui.Selection.clearSelection()
    for obj in results:
        Gui.Selection.addSelection(obj)
    controller.faces.refresh()
    controller.message(('%d mirrored cop%s created' % (len(results), 'y' if len(results) == 1 else 'ies') if copy
                        else 'Mirrored along %s' % axis) + ' · Undo with ⌘Z')
