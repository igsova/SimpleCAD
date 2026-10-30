"""导入网格转换为可编辑 CAD 对象的面板；转换成功前不会对原模型进行任何修改。"""
import FreeCAD as App
import FreeCADGui as Gui
from ...jobs import mesh as mesh_jobs
from ...core import preferences
from ...mesh.conversion import is_mesh
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel


class MeshDialog(QtWidgets.QDialog):
    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source, self.job = source, None
        self.setWindowTitle('转为可编辑网格')
        self.setObjectName('SimpleCADMeshConversion')
        self.setMinimumWidth(440)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel('%s\n%s 个三角面片' % (source.Label, format(source.Mesh.CountFacets, ','))))
        text = QtWidgets.QLabel('将三角网格重建为可编辑的 CAD 面。完整的闭合圆柱面将自动转为原生解析几何体。\n'
                                '启用拟合光滑曲面后，平面与曲面区域将在公差范围内拟合成最少的完整面片；'
                                '若未启用，则仅重建平整区域与孔壁，其他曲面区域保留分面面片。\n'
                                '原始网格将作为隐藏备份保留；开敞非闭合网格将转换为曲面。')
        text.setWordWrap(True)
        layout.addWidget(text)
        form = QtWidgets.QFormLayout()
        self.tolerance = QtWidgets.QDoubleSpinBox()
        self.tolerance.setDecimals(5); self.tolerance.setRange(.00001, 1); self.tolerance.setValue(preferences.precision()); self.tolerance.setSuffix(' mm')
        self.tolerance.setToolTip('与拟合曲面的最大允许偏差，以及边界缝合修复的极限距离。此值为单位 mm 的距离数值，而非目标面片数。')
        form.addRow('曲面拟合 / 修复公差', self.tolerance)
        self.surfaces = QtWidgets.QCheckBox('拟合平滑曲面 (生成最少的面片)')
        self.surfaces.setChecked(preferences.smooth_surfaces())
        self.surfaces.setToolTip('在公差范围内将平面与曲面区域重建为拟合平面、圆柱面及光滑 B 样条曲面。'
                                 '圆孔与凸台将转换为原生解析圆柱体。若某部分无法拟合，'
                                 '将自动回退为平面面片与分面三角形，并附带警告提示。')
        form.addRow(self.surfaces)
        self.optimize = QtWidgets.QCheckBox('缩减三角形数量以加快编辑性能')
        self.optimize.setToolTip('对剩余未拟合的三角形面片进行减面优化。已拟合的光滑曲面绝不会被减面。')
        form.addRow(self.optimize)
        self.error = QtWidgets.QDoubleSpinBox()
        self.error.setDecimals(3); self.error.setRange(.001, 1); self.error.setValue(.01); self.error.setSuffix(' mm')
        self.error.setEnabled(False)
        self.optimize.toggled.connect(self.error.setEnabled)
        form.addRow('网格简化允许误差', self.error)
        layout.addLayout(form)
        self.status = QtWidgets.QLabel('每个生成的面均保持在网格的曲面公差范围内。额外的三角网格减面为可选操作。')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.progress = QtWidgets.QProgressBar(); self.progress.setRange(0, 0); self.progress.hide(); layout.addWidget(self.progress)
        buttons = QtWidgets.QDialogButtonBox()
        self.convert = buttons.addButton('转换', QtWidgets.QDialogButtonBox.AcceptRole)
        self.cancel_button = buttons.addButton(QtWidgets.QDialogButtonBox.Cancel)
        self.convert.clicked.connect(self.begin)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)
        self.timer = QtCore.QTimer(self); self.timer.setInterval(200); self.timer.timeout.connect(self.poll)

    def begin(self):
        try:
            surfaces = self.surfaces.isChecked()
            self.job = mesh_jobs.start(self.source, self.tolerance.value(), self.error.value() if self.optimize.isChecked() else 0,
                                       surfaces)
            App.ParamGet(preferences.PARAMETER_PATH).SetBool('smooth_surfaces', surfaces)
            for widget in (self.convert, self.tolerance, self.surfaces, self.optimize, self.error): widget.setEnabled(False)
            self.progress.show(); self.timer.start()
        except Exception as error:
            self.status.setText(str(error))

    def poll(self):
        state = self.job.status()
        self.status.setText(state['stage'])
        if state['status'] == 'running':
            return
        self.timer.stop(); self.progress.hide()
        try:
            if state['status'] != 'ready':
                raise ValueError(state['error'] or state['stage'])
            self.job.apply()
            report = self.job.report
            analytic = report.get('cylinders', 0) + report.get('analytic_holes', 0)
            recognized = ('\n已识别出 %s 个原生解析圆柱体特征。' % format(analytic, ',')) if analytic else ''
            smooth, flat = report.get('fitted_smooth', 0), report.get('fitted_planes', 0)
            cylinders = report.get('fitted_cylinders', 0)
            if smooth or flat:
                cyl_text = ('（其中 %s 个圆柱面）' % format(cylinders, ',')) if cylinders else ''
                recognized += '\n已拟合 %s 个平滑面%s及 %s 个平面，与网格最大偏差 %.3f mm。' % (
                    format(smooth, ','), cyl_text, format(flat, ','), report.get('max_fit_deviation', 0))
            self.status.setText('%s 个可编辑面 · %s 个实体%s\n%s' % (
                format(report['faces'], ','), report['solids'], recognized, '\n'.join(report['warnings'])))
            self.convert.hide()
            self.cancel_button.setText('关闭')
        except Exception as error:
            self.job.cancel()
            self.status.setText(str(error))
            for widget in (self.convert, self.tolerance, self.surfaces, self.optimize): widget.setEnabled(True)
            self.error.setEnabled(self.optimize.isChecked())

    def reject(self):
        self.timer.stop()
        if self.job: self.job.cancel()
        super().reject()


def show(controller):
    selected = controller.selected()
    if not selected and App.ActiveDocument:
        selected = [obj for obj in App.ActiveDocument.Objects if is_mesh(obj) and obj.ViewObject.Visibility]
    if len(selected) != 1 or not is_mesh(selected[0]):
        raise ValueError('请先选择一个导入的网格对象，然后再选择【转为可编辑网格…】。')
    dialog = MeshDialog(selected[0], Gui.getMainWindow())
    anchor_panel(dialog).exec()
    dialog.deleteLater()
    controller.faces.refresh()