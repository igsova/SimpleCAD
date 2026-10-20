"""Two-plane mesh editing with cached indexed preview and isolated Apply."""
import numpy as np
import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin

from ...jobs import mesh as mesh_jobs
from ...mesh import slicing as mesh_slicing, stretch as mesh_stretch
from ...mesh.conversion import cached_fingerprints
from ...mesh.transform import Plan
from ..previews.shaded import RoundPreview, NativeMask
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel


def fill(field, values, dtype=np.float32):
    """Replace a Coin multi-field with exactly these values.

    Passing a NumPy array avoids creating a Python object per coordinate:
    on dense meshes those lists also trigger full garbage collections in the
    FreeCAD process, which cost far more than the copy itself.
    """
    values = np.ascontiguousarray(values, dtype=dtype)
    field.setNum(len(values))
    if not len(values):
        return
    try:
        field.setValues(0, len(values), values)
    except (TypeError, ValueError, NotImplementedError):
        # Pivy built without NumPy typemaps accepts only Python sequences.
        field.setValues(values.tolist())


class StretchPreview(RoundPreview):
    def __init__(self, view, source):
        super().__init__(view)
        self.source, self.key, self.topology = source, None, None
        self.marked, self.painted = (), None
        self.node = coin.SoSeparator()
        hints = coin.SoShapeHints(); hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        self.node.addChild(hints)
        self.material = coin.SoMaterial(); self.node.addChild(self.material)
        binding = coin.SoMaterialBinding(); binding.value = coin.SoMaterialBinding.PER_FACE
        self.node.addChild(binding)
        self.coords = coin.SoCoordinate3(); self.node.addChild(self.coords)
        self.faces = coin.SoIndexedFaceSet(); self.node.addChild(self.faces)
        self.guide = coin.SoSeparator(); self.root.addChild(self.guide)

    def show(self, plan, points):
        self.show_mesh(plan.triangles, plan.weights, points, plan)

    def show_mesh(self, triangles, weights, points, key):
        # Coin setValues only replaces a prefix. Shrink/Clear or changing from
        # Extrude to Move must also discard obsolete walls and cap vertices.
        # Suppress scene notifications while indices and coordinates disagree.
        notify = self.node.enableNotify(False)
        try:
            topology_changed = self.topology is not triangles
            if topology_changed:
                faces = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
                fill(self.faces.coordIndex, np.column_stack((faces, np.full(len(faces), -1))).ravel(), np.int32)
                self.topology = triangles
            if self.key is not key or topology_changed or len(self.marked):
                self.marked = ()
                self.paint(triangles, weights)
                self.key = key
            fill(self.coords.point, points)
        finally:
            self.node.enableNotify(notify)
            if notify: self.node.touch()
        if not self.masks:
            self.masks.append(NativeMask(self.source)); self.models.addChild(self.node)
        self.view.redraw()

    def paint(self, triangles, weights):
        self.painted = (triangles, weights)
        weight = weights[triangles].mean(axis=1)
        colors = np.column_stack((.3+.65*weight, .7-.25*weight, .85-.6*weight))
        if len(self.marked):
            colors[self.marked] = (.9, .08, .08)
        fill(self.material.diffuseColor, colors)

    def mark(self, triangles):
        """Show these preview triangles in red (e.g. predicted collisions)."""
        triangles = np.asarray(triangles, dtype=np.int64)
        if not len(triangles) and not len(self.marked):
            return
        if self.painted is None:
            return
        notify = self.node.enableNotify(False)
        try:
            self.marked = triangles
            self.paint(*self.painted)
        finally:
            self.node.enableNotify(notify)
            if notify: self.node.touch()
        self.view.redraw()

    def clear_model(self):
        # Keep controls visible even when a rotation puts a plane outside the
        # mesh or shortening becomes invalid, so the user can drag it back.
        super().clear()

    def clear(self):
        super().clear()
        self.guide.removeAllChildren()


class MeshStretchSession:
    def __init__(self, controller, source):
        mesh_stretch.check_source(source)
        self.controller, self.source = controller, source
        self.original = cached_fingerprints.refresh(source)
        self.placement = App.Placement(source.Placement)
        self.closed, self.job, self.plan, self.plan_key = False, None, None, None
        self.planes = {}
        self.points, self.triangles = source.Mesh.Topology
        self.points = np.asarray([tuple(p) for p in self.points])
        self.triangles = np.asarray(self.triangles, dtype=np.int64)
        self.preview = StretchPreview(controller.view, source)
        self.dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self.dialog.setObjectName('SimpleCADMeshStretch')
        self.dialog.setWindowTitle('Stretch mesh / Move region')
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        layout = QtWidgets.QVBoxLayout(self.dialog)
        layout.addWidget(QtWidgets.QLabel('%s · %s triangles' % (source.Label, format(len(self.triangles), ','))))
        self.form = QtWidgets.QFormLayout(); layout.addLayout(self.form)
        self.mode = QtWidgets.QComboBox(); self.mode.addItems(['Stretch along axis', 'Move end region (XYZ)'])
        self.form.addRow('Operation', self.mode)
        self.axis = QtWidgets.QComboBox()
        for label, key in [('Object main axis','Main'), ('World X','X'), ('World Y','Y'), ('World Z','Z'),
                           ('Object local X','LocalX'), ('Object local Y','LocalY'), ('Object local Z','LocalZ')]:
            self.axis.addItem(label, key)
        self.form.addRow('Axis', self.axis)
        row = QtWidgets.QWidget(); angles_layout = QtWidgets.QHBoxLayout(row); angles_layout.setContentsMargins(0,0,0,0)
        self.rotation = []
        for label in 'XYZ':
            widget = QtWidgets.QDoubleSpinBox(); widget.setDecimals(2); widget.setRange(-180,180)
            widget.setSuffix('°'); widget.setPrefix(label+' '); widget.setKeyboardTracking(False)
            widget.setToolTip('Rotate both planes about their common origin, world X then Y then Z. Plane spacing is preserved.')
            widget.setAccessibleName('Plane rotation '+label)
            widget.valueChanged.connect(self.orientation_changed)
            angles_layout.addWidget(widget); self.rotation.append(widget)
        self.form.addRow('Plane rotation', row)
        self.mouse_mode = QtWidgets.QComboBox(); self.mouse_mode.addItems(['Move planes', 'Rotate both planes'])
        self.form.addRow('Drag in view', self.mouse_mode)
        self.mouse_mode.currentIndexChanged.connect(self.changed)
        self.lower = self.spin('First plane', 0)
        self.upper = self.spin('Second plane', 1)
        self.reverse = QtWidgets.QCheckBox('Move negative side instead'); self.form.addRow(self.reverse)
        self.distance = self.spin('Length change', 0)
        self.delta = [self.spin('Move ' + name, 0) for name in 'XYZ']
        self.note = QtWidgets.QLabel('Drag a plane frame or its labeled handle to position it. Choose Rotate both planes '
            'to drag X/Y/Z rings; Shift snaps rotation to 15°. Numeric fields stay synchronized.\n'
            'Positions are measured from the common origin along the rotated axis.\n'
            'Blue stays fixed; orange moves together. Only the section between the planes stretches.\n'
            'Keep holes and mounts outside that section to preserve their dimensions.')
        self.note.setWordWrap(True); layout.addWidget(self.note)
        self.status = QtWidgets.QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.progress = QtWidgets.QProgressBar(); self.progress.setRange(0,0); self.progress.hide(); layout.addWidget(self.progress)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.Apply)
        self.apply_button.setAutoDefault(False); self.apply_button.clicked.connect(self.apply)
        buttons.rejected.connect(controller.cancel); self.dialog.rejected.connect(controller.cancel); layout.addWidget(buttons)
        self.pending = QtCore.QTimer(self.dialog); self.pending.setSingleShot(True); self.pending.timeout.connect(self.update_preview)
        self.poller = QtCore.QTimer(self.dialog); self.poller.setInterval(150); self.poller.timeout.connect(self.poll)
        self.axis.currentIndexChanged.connect(self.axis_changed)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.reverse.toggled.connect(self.changed)
        from .mesh_handles import PlaneHandles
        self.handles = PlaneHandles(self)
        self.dialog.setMinimumWidth(430)

    def spin(self, label, value):
        widget = QtWidgets.QDoubleSpinBox(); widget.setDecimals(4); widget.setRange(-1e6, 1e6)
        widget.setSuffix(' mm'); widget.setValue(value); widget.setKeyboardTracking(False)
        widget.valueChanged.connect(self.changed); self.form.addRow(label, widget)
        return widget

    def open(self):
        Gui.Selection.clearSelection(); Gui.Selection.clearPreselection()
        self.axis_changed(); self.mode_changed(); anchor_panel(self.dialog).show(); self.update_preview()

    def check(self):
        mesh_stretch.check_source(self.source)
        if (cached_fingerprints.get(self.source) != self.original
                or not self.source.Placement.isSame(self.placement)):
            raise ValueError('The source mesh changed. Start Stretch mesh again.')

    def axis_changed(self, *unused):
        key = self.axis.currentData()
        if key not in self.planes:
            self.planes[key] = mesh_slicing.plane(self.source.Mesh, key)
        self.base_plane = self.plane = self.planes[key]
        for widget in self.rotation:
            widget.blockSignals(True); widget.setValue(0); widget.blockSignals(False)
        span = self.plane.upper - self.plane.lower
        for widget, level in ((self.lower, self.plane.lower+span/3), (self.upper, self.plane.upper-span/3)):
            widget.blockSignals(True); widget.setValue(level); widget.blockSignals(False)
        self.changed()

    def angles(self):
        return [widget.value() for widget in self.rotation]

    def orientation_changed(self, *unused):
        if not hasattr(self, 'base_plane'):
            return
        self.plane = mesh_stretch.orient_plane(self.base_plane, self.points, self.angles())
        self.changed()

    def mode_changed(self, *unused):
        for widget in [self.distance] + self.delta:
            visible = (self.mode.currentIndex() == 0) == (widget is self.distance)
            widget.setVisible(visible); self.form.labelForField(widget).setVisible(visible)
        self.changed()

    def movement(self):
        if self.mode.currentIndex() == 0:
            return np.asarray(tuple(self.plane.normal)) * self.distance.value() * (-1 if self.reverse.isChecked() else 1)
        return np.asarray([w.value() for w in self.delta])

    def values(self):
        values = dict(axis=self.axis.currentData(), rotation=self.angles(), lower=self.lower.value(),
                      upper=self.upper.value(), reverse=self.reverse.isChecked())
        if self.mode.currentIndex() == 0:
            values['distance'] = self.distance.value()
        else:
            values['delta'] = [w.value() for w in self.delta]
        return values

    def changed(self, *unused):
        if not hasattr(self, 'pending') or self.closed:
            return
        self.apply_button.setEnabled(False)
        if self.job:
            self.job.cancel(); self.job = None
        self.poller.stop(); self.progress.hide()
        if hasattr(self, 'plane') and self.handles.drag is None:
            self.handles.render()
        # Continuous motion should render at a bounded rate, not postpone the
        # preview indefinitely by restarting a debounce timer on every event.
        if not self.pending.isActive():
            self.pending.start(35)

    def update_preview(self):
        self.pending.stop()
        if self.closed:
            return False
        try:
            self.check()
            self.handles.render()
            lower, upper = self.lower.value(), self.upper.value()
            delta = self.movement()
            if self.handles.drag is not None:
                if upper-lower < 1e-5:
                    raise ValueError('The second plane must be above the first.')
                if 1+(-1 if self.reverse.isChecked() else 1)*float(delta @ tuple(self.plane.normal))/(upper-lower) < 1e-4:
                    raise ValueError('This movement would collapse the middle section. Reduce the shortening.')
                weights = np.clip(((self.points-tuple(self.plane.center)) @ tuple(self.plane.normal)-lower)/(upper-lower), 0, 1)
                if self.reverse.isChecked(): weights = 1-weights
                self.preview.show_mesh(self.triangles, weights, self.points+weights[:,None]*delta, object())
                self.status.setText('Release to refine the preview · Both planes stay parallel.')
                self.apply_button.setEnabled(False)
                return True
            key = (self.axis.currentData(), tuple(self.angles()), lower, upper, self.reverse.isChecked())
            if key != self.plan_key:
                self.plan = Plan(self.points, self.triangles, tuple(self.plane.center), tuple(self.plane.normal),
                                 lower, upper, self.reverse.isChecked())
                self.plan_key = key
            points = self.plan.transform(delta)
            self.preview.show(self.plan, points)
            status = '%s triangles in preview · Original kept as a hidden backup on Apply.' % format(len(self.plan.triangles), ',')
            if self.plan.degenerate_before:
                status += '\n%d pre-existing degenerate triangles will be retained.' % self.plan.degenerate_before
            self.status.setText(status)
            self.apply_button.setEnabled(float(np.linalg.norm(delta)) >= 1e-9)
            return True
        except (ValueError, RuntimeError, ReferenceError) as error:
            self.preview.clear_model(); self.status.setText(str(error)); self.apply_button.setEnabled(False)
            return False

    def apply(self):
        if not self.update_preview() or not self.apply_button.isEnabled():
            return
        try:
            self.job = mesh_jobs.start_stretch(self.source, **self.values())
            self.apply_button.setEnabled(False); self.progress.show(); self.poller.start()
            self.status.setText('Checking the result in the background…')
        except (ValueError, RuntimeError) as error:
            self.status.setText(str(error))

    def poll(self):
        if self.closed or not self.job:
            return
        state = self.job.status(); self.status.setText(state['error'] or state['stage'])
        if state['status'] == 'running':
            return
        self.poller.stop(); self.progress.hide()
        if state['status'] != 'ready':
            return
        try:
            self.check(); self.preview.clear(); self.job.apply()
            self.controller.cancel(quiet=True); self.controller.faces.refresh()
            self.controller.message('Mesh stretched · Original kept hidden · Undo restores it')
        except (ValueError, RuntimeError) as error:
            self.job.cancel(); self.status.setText(str(error))

    def close(self):
        if self.closed:
            return
        self.closed = True; self.pending.stop(); self.poller.stop()
        self.handles.close()
        if self.job:
            self.job.cancel()
        self.preview.close(); self.dialog.hide(); self.dialog.deleteLater()
