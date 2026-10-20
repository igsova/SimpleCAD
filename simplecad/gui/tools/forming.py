"""Preview-only controls for scaling, ordered lofts and path sweeps."""
import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin
from ... import ROOT
from ...document import operations as ops
from ...modeling import forming
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel
from ..previews.rotate import RotatePreview
from ..previews.shaded import RoundPreview, NativeMask, representation


class ScalePreview(RotatePreview):
    def show_scale(self,frames,values):
        if not self.masks:
            for (obj,_),(root,_) in zip(self.targets,self.cached):
                self.masks.append(NativeMask(obj));self.models.addChild(root)
        for (center,rotation),(_,transform) in zip(frames,self.cached):
            transform.center=tuple(center)
            transform.scaleOrientation=coin.SbRotation(*rotation.Q)
            transform.scaleFactor=values
        self.view.redraw()


class FormingSession:
    def __init__(self,controller,mode,selection):
        self.controller,self.mode,self.selection=controller,mode,selection
        self.targets=ops.prepare_scaling(selection) if mode=='Scale' else ops.prepare_profiles(selection,mode)
        self.doc=self.targets[0][0].Document
        self.closed=False;self.result=None;self.key=None;self.syncing=False
        self.preview=ScalePreview(controller.view,self.targets) if mode=='Scale' else RoundPreview(controller.view)
        self.dialog=QtWidgets.QDialog(Gui.getMainWindow())
        self.dialog.setObjectName('SimpleCAD'+mode)
        self.dialog.setWindowTitle('Scale / Stretch' if mode=='Scale' else mode)
        self.dialog.setWindowFlags(QtCore.Qt.Tool|QtCore.Qt.WindowTitleHint|QtCore.Qt.WindowCloseButtonHint)
        check_icon=(ROOT/'Resources/icons/checked.svg').as_posix()
        self.dialog.setStyleSheet('QCheckBox::indicator { width: 16px; height: 16px; } '
                                 'QCheckBox::indicator:checked { image: url("'+check_icon+'"); }')
        layout=QtWidgets.QVBoxLayout(self.dialog)
        self.form=QtWidgets.QFormLayout();layout.addLayout(self.form)
        if mode=='Scale':self.scale_controls()
        else:self.profile_controls()
        self.status=QtWidgets.QLabel();self.status.setWordWrap(True);self.status.setMinimumHeight(50)
        self.status.setMaximumWidth(460);layout.addWidget(self.status)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply|QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button=buttons.button(QtWidgets.QDialogButtonBox.Apply)
        self.apply_button.setAutoDefault(False);self.apply_button.clicked.connect(self.apply)
        buttons.rejected.connect(controller.cancel);self.dialog.rejected.connect(controller.cancel)
        layout.addWidget(buttons)
        self.pending=QtCore.QTimer(self.dialog);self.pending.setSingleShot(True)
        self.pending.timeout.connect(self.update_preview)
        self.dialog.setMinimumWidth(420)

    def combo(self,label,entries):
        widget=QtWidgets.QComboBox()
        for title,value in entries:widget.addItem(title,value)
        widget.currentIndexChanged.connect(self.changed);self.form.addRow(label,widget)
        return widget

    def checkbox(self,label,checked):
        widget=QtWidgets.QCheckBox(label);widget.setChecked(checked)
        widget.toggled.connect(self.changed);self.form.addRow(widget)
        return widget

    def scale_controls(self):
        self.form.addRow(QtWidgets.QLabel('%d whole object(s) selected'%len(self.targets)))
        self.linked=self.checkbox('Uniform scale — link X, Y and Z',True)
        self.values=[]
        for axis in 'XYZ':
            spin=QtWidgets.QDoubleSpinBox();spin.setDecimals(4);spin.setRange(.0001,10000)
            spin.setValue(1);spin.setSingleStep(.1);spin.setSuffix(' ×')
            spin.setObjectName('SimpleCADScale'+axis)
            self.values.append(spin);self.form.addRow(axis+' factor',spin)
            spin.valueChanged.connect(lambda value,source=spin:self.factor_changed(source,value))
        self.axes=self.combo('Axes',[('World X / Y / Z','World'),('Object local X / Y / Z','Local')])
        self.pivot=self.combo('Scale around',[('Selection center — together','Selection'),("Each object's center",'Each'),('World origin','Origin')])
        note=QtWidgets.QLabel('1 keeps the size; 2 doubles it; 0.5 halves it.\nUnlink the factors to stretch one dimension.');note.setWordWrap(True)
        self.form.addRow(note)
        self.linked.toggled.connect(lambda checked:self.factor_changed(self.values[0],self.values[0].value()) if checked else None)

    def factor_changed(self,source,value):
        if self.syncing:return
        if self.linked.isChecked():
            self.syncing=True
            for spin in self.values:
                if spin is not source:spin.setValue(value)
            self.syncing=False
        self.changed()

    def profile_controls(self):
        self.order=QtWidgets.QListWidget();self.order.setMinimumHeight(90);self.order.setMaximumHeight(150)
        for obj,_,names,_ in self.targets:self.order.addItem(obj.Label+' · '+(', '.join(names) if names else 'outline'))
        self.order.setCurrentRow(0);self.form.addRow('Profiles in order' if self.mode=='Loft' else 'Profile first · path second',self.order)
        row=QtWidgets.QWidget();buttons=QtWidgets.QHBoxLayout(row);buttons.setContentsMargins(0,0,0,0)
        for title,step in [('Move up',-1),('Move down',1)]:
            b=QtWidgets.QPushButton(title);b.setAutoDefault(False)
            b.clicked.connect(lambda unused=False,d=step:self.reorder(d));buttons.addWidget(b)
        self.form.addRow(row)
        self.solid=self.checkbox('Create a closed solid',True)
        if self.mode=='Loft':
            self.ruled=self.checkbox('Straight transitions between profiles (ruled)',False)
        else:
            self.align=self.checkbox('Align profile center to start of path',True)
            self.frenet=self.checkbox('Follow path curvature (Frenet)',False)
            self.transition=self.combo('Path corners',[('Transformed',0),('Right corners',1),('Rounded corners',2)])
        self.hide=self.checkbox('Hide source outline objects after Apply',True)
        self.hide.setToolTip('Selected faces/edges of larger objects stay visible. Source geometry is kept.')

    def reorder(self,step):
        i=self.order.currentRow();j=i+step
        if not 0<=j<len(self.targets):return
        self.targets[i],self.targets[j]=self.targets[j],self.targets[i]
        item=self.order.takeItem(i);self.order.insertItem(j,item);self.order.setCurrentRow(j);self.changed()

    def options(self):
        if self.mode=='Loft':return dict(solid=self.solid.isChecked(),ruled=self.ruled.isChecked())
        return dict(solid=self.solid.isChecked(),align=self.align.isChecked(),frenet=self.frenet.isChecked(),transition=self.transition.currentData())

    def open(self):
        Gui.Selection.clearSelection();Gui.Selection.clearPreselection()
        anchor_panel(self.dialog).show();self.update_preview()

    def changed(self,*unused):
        if not hasattr(self,'pending'):return
        self.apply_button.setEnabled(False);self.pending.start(25 if self.mode=='Scale' else 150)

    def check(self):
        if self.mode=='Scale':ops.check_scaling(self.targets)
        else:ops.check_profiles(self.targets)

    def update_preview(self):
        self.pending.stop()
        if self.closed:return False
        try:
            self.controller.check_context()
            if self.closed:return False
            self.check()
            if self.mode=='Scale':
                self.factors=forming.factors(tuple(w.value() for w in self.values))
                frames=forming.scale_frames([s for _,s in self.targets],self.axes.currentData(),self.pivot.currentData())
                self.preview.show_scale(frames,self.factors)
                message='Preview: X %.4g × · Y %.4g × · Z %.4g ×'%self.factors
            else:
                options=self.options();key=(tuple((o.Name,names) for o,_,names,_ in self.targets),tuple(options.items()))
                if self.key!=key or self.result is None:
                    result=ops.form_preview(self.targets,self.mode,**options)
                    node=representation(self.targets[0][0],result)
                    self.preview.clear();self.preview.models.addChild(node)
                    self.result,self.key=result,key
                    self.controller.view.redraw()
                message='%d faces · %s'%(len(self.result.Faces),'Closed solid' if self.solid.isChecked() else 'Surface')
            self.status.setStyleSheet('');self.status.setText(message+'\nApply to keep · Esc cancels')
            self.apply_button.setEnabled(True);return True
        except Exception as error:
            self.result=None;self.key=None;self.preview.clear()
            self.status.setStyleSheet('color: #e78f70;');self.status.setText(str(error))
            self.apply_button.setEnabled(False);return False

    def apply(self):
        if not self.update_preview():return
        try:
            self.preview.clear()
            if self.mode=='Scale':
                ops.scale_objects(self.targets,self.factors,self.axes.currentData(),self.pivot.currentData())
                result=[obj for obj,_ in self.targets]
            else:result=[ops.commit_form(self.targets,self.mode,self.result,self.hide.isChecked())]
            title=self.dialog.windowTitle()
            self.controller.cancel(quiet=True)
            Gui.Selection.clearSelection()
            for obj in result:Gui.Selection.addSelection(obj)
            self.controller.focus_view();self.controller.message(title+' applied · Undo with ⌘Z')
        except Exception as error:
            self.status.setStyleSheet('color: #e78f70;');self.status.setText(str(error));self.apply_button.setEnabled(False)

    def close(self):
        if self.closed:return
        self.closed=True;self.pending.stop();self.preview.close()
        self.dialog.blockSignals(True);self.dialog.close();self.dialog.deleteLater()
        try:
            if App.ActiveDocument==self.doc:
                self.check()
                for obj,names in self.selection:
                    for name in names or ('',):Gui.Selection.addSelection(obj,name)
        except (ValueError,RuntimeError,ReferenceError):pass
