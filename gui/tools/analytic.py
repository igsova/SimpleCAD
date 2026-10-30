"""Dialog for converting selected faceted loops into analytic geometry."""
import FreeCAD as App
import FreeCADGui as Gui

from ...modeling import analytic
from ..qt import QtWidgets
from ..panels import anchor_panel


class AnalyticDialog(QtWidgets.QDialog):
    def __init__(self, target, parent=None):
        super().__init__(parent)
        self.target = target
        self.setWindowTitle('拟合解析几何体 (Fit analytic geometry)')
        self.setObjectName('SimpleCADAnalyticGeometry')
        layout = QtWidgets.QVBoxLayout(self)
        
        # 识别元素类型提示
        label = '圆形闭合环' if target['kind'] == 'circle' else '圆柱面孔壁 / 双孔边环'
        layout.addWidget(QtWidgets.QLabel('%s\n半径: %.6g mm%s' %
                                          (label, target['radius'],
                                           '' if target['kind'] == 'circle' else '\n长度/高度: %.6g mm' % target['height'])))
        
        # 转换拟合模式下拉框
        self.mode = QtWidgets.QComboBox()
        if target.get('can_replace_rim'):
            self.mode.addItem('替换此形状中的圆弧边 (原生解析圆边)', 'replace_rim')
        self.mode.addItem('生成解析圆边 (新建对象)', 'circle')
        if target['kind'] == 'cylinder':
            self.mode.addItem('生成解析圆柱实体 (新建对象)', 'cylinder')
        if target.get('can_cut'):
            self.mode.addItem('替换此形状中的孔 (生成解析圆柱与圆边)', 'hole')
        if target.get('can_cut'):
            self.mode.setCurrentIndex(self.mode.count() - 1)
        elif target.get('can_replace_rim'):
            self.mode.setCurrentIndex(0)
        elif target['kind'] == 'cylinder':
            self.mode.setCurrentIndex(1)
        layout.addWidget(self.mode)
        
        # 替换源对象复选框
        self.replace = QtWidgets.QCheckBox('当选中整个对象时直接替换原对象')
        self.replace.setChecked(bool(target['can_replace']))
        self.replace.setEnabled(bool(target['can_replace']))
        layout.addWidget(self.replace)
        
        # 原位替换关联刷新
        def refresh_replace():
            in_place = self.mode.currentData() in ('hole', 'replace_rim')
            self.replace.setEnabled(bool(target['can_replace']) and not in_place)
        self.mode.currentIndexChanged.connect(refresh_replace)
        refresh_replace()
        
        # 规则说明
        note = QtWidgets.QLabel('选择孔的两端孔口圆环或完整的网格分面孔壁，即可将其整体替换为一个标准的解析圆柱体；'
                                '选择单端孔环会自动与对立端孔环配对。\n'
                                '单独选中一个环将生成标准圆边；选中完整对象将拟合成圆柱体。\n'
                                '有歧义或无法解析的几何体将保持不变。')
        note.setWordWrap(True); layout.addWidget(note)
        self.error = QtWidgets.QLabel(); self.error.setWordWrap(True); layout.addWidget(self.error)
        
        # 确认与取消按钮
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.Apply)
        self.apply_button.setText("应用")
        cancel_btn = buttons.button(QtWidgets.QDialogButtonBox.Cancel)
        cancel_btn.setText("取消")
        self.apply_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setMinimumWidth(420)


def show(controller):
    doc = App.ActiveDocument
    selection = []
    if doc is not None:
        for item in Gui.Selection.getSelectionEx():
            obj = getattr(item, 'Object', None)
            if obj is None or obj.Document != doc:
                continue
            names = tuple(getattr(item, 'SubElementNames', ()) or ())
            existing = next((index for index, (candidate, _) in enumerate(selection)
                             if candidate == obj), None)
            if existing is None:
                selection.append((obj, names))
            elif names:
                selection[existing] = (obj, selection[existing][1] + tuple(name for name in names
                                                                            if name not in selection[existing][1]))
        if not selection:
            for obj in Gui.Selection.getSelection():
                if getattr(obj, 'Document', None) == doc:
                    selection.append((obj, ()))
    try:
        target = analytic.prepare(selection)
    except Exception as error:
        controller.message(str(error))
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), '拟合解析几何体', str(error))
        return False
    saved = selection
    Gui.Selection.clearSelection(); Gui.Selection.clearPreselection()
    dialog = AnalyticDialog(target, Gui.getMainWindow())
    try:
        if anchor_panel(dialog).exec() != QtWidgets.QDialog.Accepted:
            return False
        result = analytic.apply(target, dialog.mode.currentData(), dialog.replace.isChecked())
        Gui.Selection.addSelection(result)
        controller.faces.refresh()
        if dialog.mode.currentData() == 'hole':
            controller.message('孔已替换为标准解析圆柱体 · 撤销可恢复分面网格')
        elif dialog.mode.currentData() == 'replace_rim':
            controller.message('圆弧边已替换为原生标准圆 · 撤销可恢复分面网格')
        else:
            controller.message('已成功创建解析几何体 · 撤销可恢复原对象')
        return True
    except Exception as error:
        dialog.error.setText(str(error))
        raise
    finally:
        dialog.deleteLater()
        if not Gui.Selection.getSelectionEx():
            for obj, names in saved:
                if obj.isValid():
                    for name in names or ('',):
                        Gui.Selection.addSelection(obj, name)