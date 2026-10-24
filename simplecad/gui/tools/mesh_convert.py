"""Import-to-edit conversion panel; the model remains untouched until success."""
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
        self.setWindowTitle('Make mesh editable')
        self.setObjectName('SimpleCADMeshConversion')
        self.setMinimumWidth(440)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel('%s\n%s triangles' % (source.Label, format(source.Mesh.CountFacets, ','))))
        text = QtWidgets.QLabel('Rebuild the mesh as editable faces. Complete closed cylinders become analytic.\nWith smooth surfaces, flat and curved regions each become one fitted face, for the fewest faces within the tolerance; otherwise flat regions and holes are rebuilt and other curved areas stay faceted.\nThe original mesh is kept as a hidden backup; open meshes become surfaces.')
        text.setWordWrap(True)
        layout.addWidget(text)
        form = QtWidgets.QFormLayout()
        self.tolerance = QtWidgets.QDoubleSpinBox()
        self.tolerance.setDecimals(5); self.tolerance.setRange(.00001, 1); self.tolerance.setValue(preferences.precision()); self.tolerance.setSuffix(' mm')
        self.tolerance.setToolTip('Maximum deviation from a fitted surface, and the limit for boundary repair. This is a distance in mm, not a target face count.')
        form.addRow('Surface / repair tolerance', self.tolerance)
        self.surfaces = QtWidgets.QCheckBox('Fit smooth surfaces (fewest faces)')
        self.surfaces.setChecked(preferences.smooth_surfaces())
        self.surfaces.setToolTip('Rebuild flat and curved regions as fitted planes, cylinders and smooth B-spline faces within the tolerance. '
                                 'Round holes and bosses become analytic cylinders. If a part cannot be fitted, '
                                 'it falls back to flat faces and triangles, with a warning.')
        form.addRow(self.surfaces)
        self.optimize = QtWidgets.QCheckBox('Reduce triangles for faster editing')
        self.optimize.setToolTip('Decimate the remaining triangles. Fitted smooth surfaces are never decimated.')
        form.addRow(self.optimize)
        self.error = QtWidgets.QDoubleSpinBox()
        self.error.setDecimals(3); self.error.setRange(.001, 1); self.error.setValue(.01); self.error.setSuffix(' mm')
        self.error.setEnabled(False)
        self.optimize.toggled.connect(self.error.setEnabled)
        form.addRow('Simplification tolerance', self.error)
        layout.addLayout(form)
        self.status = QtWidgets.QLabel('Every face stays within the surface tolerance of the mesh. Extra triangle reduction is optional.')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.progress = QtWidgets.QProgressBar(); self.progress.setRange(0, 0); self.progress.hide(); layout.addWidget(self.progress)
        buttons = QtWidgets.QDialogButtonBox()
        self.convert = buttons.addButton('Convert', QtWidgets.QDialogButtonBox.AcceptRole)
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
            recognized = ('\nRecognized %s analytic cylindrical feature%s.' % (analytic, '' if analytic == 1 else 's')) if analytic else ''
            smooth, flat = report.get('fitted_smooth', 0), report.get('fitted_planes', 0)
            cylinders = report.get('fitted_cylinders', 0)
            if smooth or flat:
                recognized += '\nFitted %s smooth%s and %s flat face%s, within %.3f mm of the mesh.' % (
                    format(smooth, ','), ' (%s cylindrical)' % format(cylinders, ',') if cylinders else '', format(flat, ','),
                    '' if smooth+flat == 1 else 's', report.get('max_fit_deviation', 0))
            self.status.setText('%s editable faces · %s solids%s\n%s' % (format(report['faces'], ','), report['solids'], recognized, '\n'.join(report['warnings'])))
            self.convert.hide()
            self.cancel_button.setText('Close')
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
        raise ValueError('Select one imported mesh, then choose Make mesh editable…')
    dialog = MeshDialog(selected[0], Gui.getMainWindow())
    anchor_panel(dialog).exec()
    dialog.deleteLater()
    controller.faces.refresh()
