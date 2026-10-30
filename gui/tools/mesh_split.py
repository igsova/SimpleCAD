"""仅限网格的分割预览功能，支持可选的三角形粘接定位缝。"""
import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin
from ...jobs import mesh as mesh_jobs
from ...mesh import slicing as mesh_slicing
from ...mesh.conversion import is_mesh, cached_fingerprints
from ..previews.shaded import NativeMask
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel


class MeshPreview:
    def __init__(self, view):
        self.view, self.mask = view, None
        self.root = coin.SoSeparator()
        pick = coin.SoPickStyle(); pick.style = coin.SoPickStyle.UNPICKABLE; pick.setOverride(True)
        self.root.addChild(pick)
        self.guide = coin.SoSeparator(); self.root.addChild(self.guide)
        self.models = coin.SoSeparator(); self.root.addChild(self.models)
        view.getSceneGraph().addChild(self.root)

    def plane(self, plane, offset):
        self.guide.removeAllChildren()
        points = [tuple(p) for p in plane.corners(offset)]
        light = coin.SoLightModel(); light.model = coin.SoLightModel.BASE_COLOR; self.guide.addChild(light)
        material = coin.SoMaterial(); material.diffuseColor = (.1, .85, .95); material.transparency = .8; self.guide.addChild(material)
        coords = coin.SoCoordinate3(); coords.point.setValues(points); self.guide.addChild(coords)
        face = coin.SoFaceSet(); face.numVertices.setValue(4); self.guide.addChild(face)
        self.view.redraw()

    def clear(self):
        self.models.removeAllChildren()
        if self.mask: self.mask.close(); self.mask = None
        self.view.redraw()

    def show(self, source, meshes, gap, normal):
        self.clear()
        for side, mesh, color in zip((-1, 1), meshes, ((.3, .65, .9), (.95, .65, .25))):
            placement = App.Placement(source.Placement)
            placement.Base += normal * (side * gap / 2)
            model = mesh.copy(); model.Placement = placement
            points, triangles = model.Topology
            root = coin.SoSeparator()
            material = coin.SoMaterial(); material.diffuseColor = color; root.addChild(material)
            hints = coin.SoShapeHints(); hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE; root.addChild(hints)
            coords = coin.SoCoordinate3(); coords.point.setValues([tuple(p) for p in points]); root.addChild(coords)
            faces = coin.SoIndexedFaceSet(); faces.coordIndex.setValues([i for t in triangles for i in (*t, -1)]); root.addChild(faces)
            self.models.addChild(root)
        self.mask = NativeMask(source)
        self.view.redraw()

    def close(self):
        self.clear()
        self.view.getSceneGraph().removeChild(self.root)


class MeshSplitSession:
    def __init__(self, controller, source):
        if not is_mesh(source): raise ValueError('请选择一个要分割的 STL 网格对象。')
        self.controller, self.source = controller, source
        self.original = cached_fingerprints.refresh(source)
        self.closed, self.job = False, None
        self.planes = {}
        self.preview = MeshPreview(controller.view)
        self.dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self.dialog.setObjectName('SimpleCADMeshSplit')
        self.dialog.setWindowTitle('分割网格')
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        layout = QtWidgets.QVBoxLayout(self.dialog)
        layout.addWidget(QtWidgets.QLabel(source.Label + '\n%s 个三角面片 · 网格格式输出' % format(source.Mesh.CountFacets, ',')))
        self.axis = QtWidgets.QComboBox()
        for text, key in [
            ('对象主轴', 'Main'),
            ('X 轴 — YZ 切割面', 'X'),
            ('Y 轴 — XZ 切割面', 'Y'),
            ('Z 轴 — XY 切割面', 'Z'),
            ('对象局部 X 轴', 'LocalX'),
            ('对象局部 Y 轴', 'LocalY'),
            ('对象局部 Z 轴', 'LocalZ')
        ]:
            self.axis.addItem(text, key)
        form = QtWidgets.QFormLayout(); form.addRow('切割截面', self.axis)
        self.offset = QtWidgets.QDoubleSpinBox(); self.offset.setDecimals(4); self.offset.setSuffix(' mm'); self.offset.setKeyboardTracking(False)
        form.addRow('自中心偏移', self.offset)
        layout.addLayout(form)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.slider.setRange(0, 1000); layout.addWidget(self.slider)
        self.cap = QtWidgets.QCheckBox('封闭切割截面 (封口)'); self.cap.setChecked(source.Mesh.isSolid()); layout.addWidget(self.cap)
        self.glue = QtWidgets.QCheckBox('三角形粘接定位缝'); layout.addWidget(self.glue)
        self.glue_controls = QtWidgets.QWidget(); glue_form = QtWidgets.QFormLayout(self.glue_controls); glue_form.setContentsMargins(0, 0, 0, 0)
        self.glue_depth = QtWidgets.QDoubleSpinBox(); self.glue_depth.setRange(.05, 20); self.glue_depth.setDecimals(2); self.glue_depth.setValue(2); self.glue_depth.setSuffix(' mm'); self.glue_depth.setKeyboardTracking(False)
        self.glue_depth.setToolTip('45° 斜坡沿切割轮廓延伸。薄壁限制凸棱高度；较宽的切割区域在该最大深度处削平封顶。')
        glue_form.addRow('最大缝深', self.glue_depth)
        self.glue_clearance = QtWidgets.QDoubleSpinBox(); self.glue_clearance.setRange(0, 10); self.glue_clearance.setDecimals(2); self.glue_clearance.setSingleStep(.05); self.glue_clearance.setValue(.15); self.glue_clearance.setSuffix(' mm'); self.glue_clearance.setKeyboardTracking(False)
        self.glue_clearance.setToolTip('沿分割轴向降低凸棱高度以留出装配与胶水容纳间隙。设为 0 表示几何完全贴合。')
        glue_form.addRow('胶水配合间隙', self.glue_clearance)
        self.glue_flip = QtWidgets.QCheckBox('调换凸棱与凹槽位置'); glue_form.addRow(self.glue_flip)
        note_glue = QtWidgets.QLabel('通过匹配的凸棱与凹槽对齐两侧零件。薄壁会自动限制棱高。'); note_glue.setWordWrap(True); glue_form.addRow(note_glue)
        layout.addWidget(self.glue_controls); self.glue_controls.hide()
        self.gap = QtWidgets.QDoubleSpinBox(); self.gap.setDecimals(3); self.gap.setRange(0, 100000); self.gap.setSuffix(' mm'); self.gap.setKeyboardTracking(False)
        form = QtWidgets.QFormLayout(); form.addRow('两侧零件间距', self.gap); layout.addLayout(form)
        self.gap.setToolTip('设为 0 mm 保持两部分接触贴合。正间距会使两侧等距散开。')
        note = QtWidgets.QLabel('未切削的三角面片将完整保留细节。原始网格将作为隐藏备份保留。'); note.setWordWrap(True); layout.addWidget(note)
        self.status = QtWidgets.QLabel('请调整切割截面位置，然后点击“预览分割”。'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.progress = QtWidgets.QProgressBar(); self.progress.setRange(0, 0); self.progress.hide(); layout.addWidget(self.progress)
        buttons = QtWidgets.QDialogButtonBox()
        self.preview_button = buttons.addButton('预览分割', QtWidgets.QDialogButtonBox.ActionRole)
        self.apply_button = buttons.addButton(QtWidgets.QDialogButtonBox.Apply); self.apply_button.setEnabled(False)
        buttons.addButton(QtWidgets.QDialogButtonBox.Cancel)
        self.preview_button.clicked.connect(self.begin); self.apply_button.clicked.connect(self.apply)
        buttons.rejected.connect(controller.cancel); self.dialog.rejected.connect(controller.cancel)
        layout.addWidget(buttons)
        self.poller = QtCore.QTimer(self.dialog); self.poller.setInterval(150); self.poller.timeout.connect(self.poll)
        self.axis.currentIndexChanged.connect(self.axis_changed)
        self.offset.valueChanged.connect(self.changed); self.cap.toggled.connect(self.changed); self.gap.valueChanged.connect(self.changed)
        self.slider.valueChanged.connect(self.slide)
        self.glue.toggled.connect(self.glue_changed)
        self.glue_depth.valueChanged.connect(self.changed); self.glue_clearance.valueChanged.connect(self.changed); self.glue_flip.toggled.connect(self.changed)
        self.dialog.setMinimumWidth(390)

    def open(self):
        Gui.Selection.clearSelection(); Gui.Selection.clearPreselection()
        self.axis_changed(); anchor_panel(self.dialog).show()

    def check(self):
        if self.closed: return
        if not self.source.isValid():
            raise ValueError('原始网格已改变，请重新启动【分割网格】。')
        if cached_fingerprints.get(self.source) != self.original:
            raise ValueError('原始网格已改变，请重新启动【分割网格】。')

    def axis_changed(self, *unused):
        key = self.axis.currentData()
        if key not in self.planes: self.planes[key] = mesh_slicing.plane(self.source.Mesh, key)
        self.plane = self.planes[key]
        self.offset.blockSignals(True); self.offset.setRange(self.plane.lower, self.plane.upper); self.offset.setValue(0); self.offset.blockSignals(False)
        self.changed()

    def slide(self, value):
        self.offset.setValue(self.plane.lower + (self.plane.upper - self.plane.lower) * value / 1000)

    def glue_changed(self, enabled):
        self.glue_controls.setVisible(enabled)
        if enabled: self.cap.setChecked(True)
        self.cap.setEnabled(not enabled)
        self.changed(); self.dialog.adjustSize()

    def glue_options(self):
        return {'depth': self.glue_depth.value(), 'clearance': self.glue_clearance.value(), 'flip': self.glue_flip.isChecked()} if self.glue.isChecked() else None

    def changed(self, *unused):
        if self.job: self.job.cancel(); self.job = None
        self.poller.stop(); self.progress.hide(); self.preview.clear()
        self.apply_button.setEnabled(False); self.preview_button.setEnabled(True)
        self.slider.blockSignals(True)
        span = self.plane.upper - self.plane.lower
        self.slider.setValue(round((self.offset.value() - self.plane.lower) / span * 1000) if span else 500)
        self.slider.blockSignals(False)
        self.preview.plane(self.plane, self.offset.value())
        self.status.setText('请调整切割截面位置，然后点击“预览分割”。')

    def begin(self):
        try:
            self.check()
            if self.job: self.job.cancel()
            self.job = mesh_jobs.start_split(self.source, self.axis.currentData(), self.offset.value(), self.gap.value(), self.cap.isChecked(), glue=self.glue_options())
            self.apply_button.setEnabled(False); self.preview_button.setEnabled(False)
            self.progress.show(); self.poller.start()
        except Exception as error: self.status.setText(str(error))

    def poll(self):
        if self.closed or not self.job: return
        state = self.job.status(); self.status.setText(state['stage'])
        if state['status'] == 'running': return
        self.poller.stop(); self.progress.hide(); self.preview_button.setEnabled(True)
        if state['status'] != 'ready':
            self.status.setText(state['error'] or state['stage']); return
        try:
            self.check()
            self.preview.show(self.source, self.job.split_meshes(), self.gap.value(), self.plane.normal)
            details = ['%s 个三角面片 · %s' % (format(p['triangles'], ','), '闭合' if p['closed'] else '开敞') for p in state['report']['pieces']]
            self.status.setText(' / '.join(details) + '\n点击“应用”以保留分割后的两个网格零件。\n' + '\n'.join(state['report']['warnings']))
            self.apply_button.setEnabled(True)
            self.dialog.adjustSize()
        except Exception as error:
            self.job.cancel(); self.preview.clear(); self.status.setText(str(error))

    def apply(self):
        try:
            self.check()
            if not self.job or self.job.state != 'ready': return
            self.preview.clear()
            self.job.apply()
            self.controller.cancel(quiet=True)
            self.controller.faces.refresh()
            self.controller.message('网格已分割为两个部分 · 原始网格已隐藏备份 · 撤销可恢复')
        except Exception as error: self.status.setText(str(error))

    def close(self):
        if self.closed: return
        self.closed = True
        self.poller.stop()
        if self.job: self.job.cancel()
        self.preview.close(); self.dialog.hide(); self.dialog.deleteLater()