"""Cached surface preview and numeric controls for local movement and bending."""
import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin
from ...document import operations as ops
from ...modeling import deformation as d, rotation
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel
from ..previews.shaded import RoundPreview, NativeMask
V=App.Vector


class DeformPreview(RoundPreview):
    def __init__(self,view,obj,region):
        super().__init__(view);self.obj=obj;self.region=region
        self.node=coin.SoSeparator()
        self.coords=coin.SoCoordinate3();self.node.addChild(self.coords)
        self.material=coin.SoMaterial();self.node.addChild(self.material)
        binding=coin.SoMaterialBinding();binding.value=coin.SoMaterialBinding.PER_FACE;self.node.addChild(binding)
        faces=coin.SoIndexedFaceSet();faces.coordIndex.setValues([i for tri in region.triangles for i in (*tri,-1)])
        self.node.addChild(faces)
    def show_points(self,points,weights):
        self.coords.point.setValues([tuple(p) for p in points])
        values=[sum(weights[i] for i in t)/3 for t in self.region.triangles]
        self.material.diffuseColor.setValues([(.3+.65*w,.7-.25*w,.85-.6*w) for w in values])
        if not self.masks:
            self.masks.append(NativeMask(self.obj));self.models.addChild(self.node)
        self.view.redraw()


class DeformSession:
    def __init__(self,controller,selection,seed=None):
        self.controller=controller;self.selection=selection;self.closed=False;self.building=False
        self.target=ops.prepare_deformation(selection)
        obj,region,names=self.target
        self.doc=obj.Document;self.points=None
        self.preview=DeformPreview(controller.view,obj,region)
        self.dialog=QtWidgets.QDialog(Gui.getMainWindow());self.dialog.setObjectName('SimpleCADDeform')
        self.dialog.setWindowTitle('Bend / Soft Deform')
        self.dialog.setWindowFlags(QtCore.Qt.Tool|QtCore.Qt.WindowTitleHint|QtCore.Qt.WindowCloseButtonHint)
        layout=QtWidgets.QVBoxLayout(self.dialog);self.form=QtWidgets.QFormLayout();layout.addLayout(self.form)
        self.form.addRow(QtWidgets.QLabel(obj.Label+' · '+(', '.join(names) if names else 'whole object')))
        self.mode=self.combo('Operation',[('Soft Move','Move'),('Bend','Bend')])
        center=V(seed) if seed is not None else d.default_center(region.shape,names)
        self.center=self.triplet('Influence center',center)
        self.radius=self.spin('Influence radius',region.size*.55,.001,1e6,' mm')
        self.delta=self.triplet('Displacement X / Y / Z',V())
        self.axis=self.combo('Bend along',[(n,n) for n in ('Main','X','Y','Z','LocalX','LocalY','LocalZ')])
        origin,axis,toward,length=d.bend_frame(region.shape)
        self.origin=self.triplet('Bend origin',origin)
        self.length=self.spin('Bend length',length,.001,1e6,' mm')
        self.direction=self.spin('Bend direction',0,-180,180,'°')
        self.angle=self.spin('Bend angle',0,-170,170,'°')
        self.slider=QtWidgets.QSlider(QtCore.Qt.Horizontal);self.slider.setRange(-170,170)
        self.slider.setStyleSheet('QSlider::groove:horizontal { height: 4px; background: #555; } '
                                 'QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #50d6bb; border-radius: 7px; }')
        self.form.addRow('Angle',self.slider)
        self.detail=QtWidgets.QSpinBox();self.detail.setRange(3,16);self.detail.setValue(6)
        self.form.addRow('Surface detail',self.detail)
        note=QtWidgets.QLabel('Blue stays nearly fixed; orange moves most.\nResult uses small planar faces with shaded display.\nHigher detail makes a finer surface and costs more to apply.')
        note.setWordWrap(True);layout.addWidget(note)
        self.status=QtWidgets.QLabel();self.status.setWordWrap(True);self.status.setMaximumWidth(480);layout.addWidget(self.status)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply|QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button=buttons.button(QtWidgets.QDialogButtonBox.Apply);self.apply_button.setAutoDefault(False)
        self.apply_button.clicked.connect(self.apply);buttons.rejected.connect(controller.cancel);self.dialog.rejected.connect(controller.cancel)
        layout.addWidget(buttons)
        self.pending=QtCore.QTimer(self.dialog);self.pending.setSingleShot(True);self.pending.timeout.connect(self.update_preview)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.axis.currentIndexChanged.connect(self.axis_changed)
        self.detail.valueChanged.connect(self.changed)
        self.slider.valueChanged.connect(self.angle.setValue)
        self.angle.valueChanged.connect(self.sync_slider)
        self.dialog.setMinimumWidth(490);self.mode_changed()

    def spin(self,label,value,low=-1e6,high=1e6,suffix=' mm'):
        w=QtWidgets.QDoubleSpinBox();w.setDecimals(3);w.setRange(low,high);w.setValue(value);w.setSuffix(suffix)
        w.valueChanged.connect(self.changed);self.form.addRow(label,w);return w
    def triplet(self,label,value):
        row=QtWidgets.QWidget();layout=QtWidgets.QHBoxLayout(row);layout.setContentsMargins(0,0,0,0);widgets=[]
        for axis,v in zip('XYZ',value):
            w=QtWidgets.QDoubleSpinBox();w.setRange(-1e6,1e6);w.setDecimals(3);w.setValue(v);w.setPrefix(axis+' ')
            w.valueChanged.connect(self.changed);layout.addWidget(w);widgets.append(w)
        self.form.addRow(label,row);return widgets
    def combo(self,label,items):
        w=QtWidgets.QComboBox()
        for title,key in items:w.addItem(title,key)
        w.currentIndexChanged.connect(self.changed);self.form.addRow(label,w);return w
    def sync_slider(self,value):
        self.slider.blockSignals(True);self.slider.setValue(round(value));self.slider.blockSignals(False)
    def mode_changed(self,*unused):
        bend=self.mode.currentData()=='Bend'
        for w in [self.center[0].parentWidget(),self.delta[0].parentWidget(),self.radius]:
            w.setVisible(not bend)
            label=self.form.labelForField(w)
            if label:label.setVisible(not bend)
        for w in [self.origin[0].parentWidget(),self.axis,self.length,self.direction,self.angle,self.slider]:
            w.setVisible(bend)
            label=self.form.labelForField(w)
            if label:label.setVisible(bend)
        self.changed()
    def axis_changed(self,*unused):
        origin,_,_,length=d.bend_frame(self.target[1].shape,self.axis.currentData())
        for w,value in zip(self.origin,origin):w.blockSignals(True);w.setValue(value);w.blockSignals(False)
        self.length.setValue(length);self.changed()
    def values(self,widgets):return V(*(w.value() for w in widgets))
    def changed(self,*unused):
        if hasattr(self,'pending'):
            self.apply_button.setEnabled(False);self.pending.start(60)
    def check(self):ops.check_deformation(self.target)
    def open(self):
        Gui.Selection.clearSelection();Gui.Selection.clearPreselection();anchor_panel(self.dialog).show();self.update_preview()
    def update_preview(self):
        self.pending.stop()
        if self.closed or self.building:return False
        try:
            self.controller.check_context()
            if self.closed:return False
            self.check();obj,region,names=self.target
            if self.detail.value()!=region.detail:
                replacement=d.Region(region.shape,self.detail.value())
                self.preview.close();self.target=(obj,replacement,names);region=replacement
                self.preview=DeformPreview(self.controller.view,obj,region)
            if self.mode.currentData()=='Move':points,weights=region.move(self.values(self.center),self.radius.value(),self.values(self.delta))
            else:
                axis=rotation.direction(region.shape,self.axis.currentData())
                toward=App.Rotation(axis,self.direction.value()).multVec(d.g.Plane.from_normal(V(),axis).u)
                points,weights=region.bend(self.values(self.origin),axis,toward,self.length.value(),self.angle.value())
            self.preview.show_points(points,weights);self.points=points
            self.status.setStyleSheet('');self.status.setText('%d surface faces · Apply to keep · Esc cancels'%len(region.triangles))
            self.apply_button.setEnabled(True);return True
        except Exception as error:
            self.points=None;self.preview.clear();self.status.setStyleSheet('color: #e78f70;');self.status.setText(str(error));self.apply_button.setEnabled(False);return False
    def apply(self):
        if not self.update_preview():return
        try:
            self.building=True;self.pending.stop();self.apply_button.setEnabled(False)
            self.status.setText('Building and checking the deformed surface…');Gui.updateGui()
            if self.closed:return
            self.check()
            self.preview.clear();changed=ops.commit_deformation(self.target,self.points)
            obj=self.target[0];self.controller.cancel(quiet=True);Gui.Selection.clearSelection();Gui.Selection.addSelection(obj)
            self.controller.focus_view();self.controller.message('Deformation applied · Undo with ⌘Z' if changed else 'Original shape kept')
        except Exception as error:
            self.status.setStyleSheet('color: #e78f70;');self.status.setText(str(error))
        finally:self.building=False
    def close(self):
        if self.closed:return
        self.closed=True;self.pending.stop();self.preview.close();self.dialog.blockSignals(True);self.dialog.close();self.dialog.deleteLater()
        try:
            self.check()
            if App.ActiveDocument==self.doc:
                for obj,names in self.selection:
                    for name in names or ('',):Gui.Selection.addSelection(obj,name)
        except (ValueError,RuntimeError,ReferenceError):pass
