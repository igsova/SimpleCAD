"""Pick connected mesh patches, then move, rotate, or extrude with live preview."""
import numpy as np
import FreeCAD as App
import FreeCADGui as Gui
from concurrent.futures import ThreadPoolExecutor
from ...mesh import collisions as mesh_collisions, region_edit as mesh_region_edit
from ...jobs import mesh as mesh_jobs
from ...mesh.region import RegionPlan
from ...mesh.stretch import check_source
from .mesh_stretch import StretchPreview
from ...mesh.conversion import cached_fingerprints
from ..snapping import ray
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel

# One background thread estimates preview collisions with NumPy, so typing a
# value or picking stays responsive on dense meshes. Stale results are ignored.
_collisions = ThreadPoolExecutor(max_workers=1, thread_name_prefix='SimpleCADMeshCollisions')


class MeshRegionSession:
    def __init__(self, controller, source):
        check_source(source)
        self.controller,self.source = controller,source
        self.original,self.topology = mesh_region_edit.snapshot(source)
        self.placement = App.Placement(source.Placement)
        self.selected = set(); self.plan = self.plan_key = self.job = self.press = None
        self.closed = False
        self.validation_error = ''
        self.color_keys = {}
        self.preview = StretchPreview(controller.view,source)
        self.shown_points,self.shown_faces = self.topology.points,self.topology.triangles
        self.origins = np.arange(len(self.shown_faces))
        self.dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self.dialog.setObjectName('SimpleCADMeshRegion')
        self.dialog.setWindowTitle('Mesh region · Move / Rotate / Extrude')
        self.dialog.setWindowFlags(QtCore.Qt.Tool|QtCore.Qt.WindowTitleHint|QtCore.Qt.WindowCloseButtonHint)
        layout = QtWidgets.QVBoxLayout(self.dialog)
        layout.addWidget(QtWidgets.QLabel('%s · %s triangles' % (source.Label,format(len(self.topology.triangles),','))))
        self.form = QtWidgets.QFormLayout(); layout.addLayout(self.form)
        self.selection = self.combo('Select patch',['Flat','Smooth','Triangle'])
        self.crease = self.spin('Smooth crease angle',15,0,90,'°')
        self.action = self.combo('Pick action',['Replace','Add','Remove'])
        self.selection_count = QtWidgets.QLabel()
        self.selection_count.setObjectName('SimpleCADMeshRegionSelectionCount')
        layout.addWidget(self.selection_count)
        self.selection_buttons = []
        buttons = QtWidgets.QHBoxLayout(); layout.addLayout(buttons)
        for title, action in [('Grow',lambda: self.grow(1)),('Shrink',lambda: self.grow(-1)),('Clear',self.clear)]:
            button=QtWidgets.QPushButton(title); button.clicked.connect(action); buttons.addWidget(button)
            self.selection_buttons.append(button)
        self.mode = self.combo('Operation',['Move','Rotate','Extrude'])
        self.rings = QtWidgets.QSpinBox(); self.rings.setRange(1,30); self.rings.setValue(1)
        self.rings.setToolTip('Number of connected vertex rings over which movement reaches zero. The selected patch moves rigidly.')
        self.form.addRow('Transition rings',self.rings); self.rings.valueChanged.connect(self.changed)
        self.delta = [self.spin('Move '+axis,0) for axis in 'XYZ']
        self.direction = self.combo('Direction / rotation axis',['Region normal','World X','World Y','World Z'])
        self.angle = self.spin('Rotation',0,-180,180,'°')
        self.distance = self.spin('Extrusion distance',0)
        self.custom_pivot = QtWidgets.QCheckBox('Use custom rotation pivot'); self.form.addRow(self.custom_pivot)
        self.pivot = [self.spin('Pivot '+axis,0) for axis in 'XYZ']
        note=QtWidgets.QLabel('Click a wall to select its connected patch. Use Add/Remove or Shift-click to combine patches. '
            'Grow/Shrink adjusts the boundary. Orange is selected; blue stays fixed; intermediate colors show the transition.\n'
            'Move and Rotate deform neighboring rings. Extrude creates side walls, including around holes. '
            'Apply checks for self-intersections in the background and keeps the original as a hidden backup.')
        note.setWordWrap(True); layout.addWidget(note)
        self.status = QtWidgets.QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.progress = QtWidgets.QProgressBar(); self.progress.setRange(0,0); self.progress.hide(); layout.addWidget(self.progress)
        box=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply|QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button=box.button(QtWidgets.QDialogButtonBox.Apply); self.apply_button.setAutoDefault(False)
        self.apply_button.clicked.connect(self.apply); box.rejected.connect(controller.cancel)
        self.dialog.rejected.connect(controller.cancel); layout.addWidget(box)
        self.pending=QtCore.QTimer(self.dialog); self.pending.setSingleShot(True); self.pending.timeout.connect(self.update_preview)
        self.collision=None
        self.collision_timer=QtCore.QTimer(self.dialog); self.collision_timer.setSingleShot(True)
        self.collision_timer.timeout.connect(self.check_collisions)
        self.collision_poller=QtCore.QTimer(self.dialog); self.collision_poller.setInterval(40)
        self.collision_poller.timeout.connect(self.collisions_ready)
        self.poller=QtCore.QTimer(self.dialog); self.poller.setInterval(150); self.poller.timeout.connect(self.poll)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.custom_pivot.toggled.connect(self.mode_changed)
        self.dialog.setMinimumWidth(430)

    def combo(self,label,items):
        widget=QtWidgets.QComboBox(); widget.addItems(items); self.form.addRow(label,widget)
        widget.currentIndexChanged.connect(self.changed)
        return widget

    def spin(self,label,value,low=-1e6,high=1e6,suffix=' mm'):
        widget=QtWidgets.QDoubleSpinBox(); widget.setRange(low,high); widget.setDecimals(4)
        widget.setValue(value); widget.setSuffix(suffix); widget.setKeyboardTracking(False)
        self.form.addRow(label,widget); widget.valueChanged.connect(self.changed)
        return widget

    def open(self):
        Gui.Selection.clearSelection(); Gui.Selection.clearPreselection()
        self.mode_changed(); anchor_panel(self.dialog).show(); self.update_preview()

    def check(self):
        check_source(self.source)
        if cached_fingerprints.get(self.source)!=self.original or not self.source.Placement.isSame(self.placement):
            raise ValueError('The source mesh changed. Start Mesh region again.')

    def mode_changed(self,*unused):
        mode=self.mode.currentText()
        fields = [(w,mode=='Move') for w in self.delta]
        fields += [(self.direction,mode!='Move'), (self.angle,mode=='Rotate'),
                   (self.distance,mode=='Extrude'), (self.rings,mode!='Extrude')]
        fields += [(w,mode=='Rotate' and self.custom_pivot.isChecked()) for w in self.pivot]
        for widget,show in fields:
            widget.setVisible(show); self.form.labelForField(widget).setVisible(show)
        self.custom_pivot.setVisible(mode=='Rotate')
        self.changed()

    def values(self):
        index=self.direction.currentIndex()
        return dict(mode=self.mode.currentText(),rings=self.rings.value(),delta=[w.value() for w in self.delta],
                    axis=None if index==0 else np.eye(3)[index-1].tolist(),angle=self.angle.value(),
                    distance=self.distance.value(),pivot=[w.value() for w in self.pivot] if self.custom_pivot.isChecked() else None)

    def changed(self,*unused):
        if not hasattr(self,'pending') or self.closed: return
        self.validation_error = ''
        self.update_selection_feedback()
        self.apply_button.setEnabled(False)
        if self.job: self.job.cancel(); self.job=None
        self.poller.stop(); self.progress.hide()
        self.stop_collision_check()
        if not self.pending.isActive(): self.pending.start(35)

    def update_selection_feedback(self):
        count = len(self.selected)
        self.selection_count.setText('%s triangle%s selected' % (format(count,','), '' if count==1 else 's'))
        for button in self.selection_buttons:
            button.setEnabled(bool(count))
        self.crease.setEnabled(self.selection.currentText()=='Smooth')

    def pick_hint(self):
        if self.action.currentText()=='Remove':
            return 'Nothing is selected. Choose Replace or Add, then click a mesh surface.'
        patch = {'Flat':'a flat patch','Smooth':'a smooth patch','Triangle':'a triangle'}[self.selection.currentText()]
        return 'Click a mesh surface to select %s. The selection turns orange.' % patch

    def pick_feedback(self,message):
        # A miss or reselect leaves the rejected parameters unchanged. Keep the
        # reason Apply is disabled until the user actually changes the edit.
        self.status.setText(self.validation_error or message)

    def reject(self,message):
        self.validation_error = message
        self.status.setText(message)
        self.apply_button.setEnabled(False)

    def grow(self,amount):
        self.selected=self.topology.grow(self.selected,amount); self.changed()

    def clear(self):
        self.selected.clear(); self.changed()

    def update_preview(self):
        self.pending.stop()
        if self.closed: return False
        self.update_selection_feedback()
        try:
            self.check()
            if not self.selected:
                self.shown_points,self.shown_faces=self.topology.points,self.topology.triangles
                self.origins=np.arange(len(self.shown_faces))
                self.preview.show_mesh(self.shown_faces,np.zeros(len(self.shown_points)),self.shown_points,self.topology)
                self.status.setText(self.pick_hint()); self.apply_button.setEnabled(False)
                return False
            key=(frozenset(self.selected),self.rings.value())
            if self.plan_key!=key:
                self.plan=RegionPlan(self.topology,self.selected,self.rings.value()); self.plan_key=key
                self.color_keys = {name:object() for name in ('Move','Rotate','Extrude','invalid')}
            values=self.values(); values.pop('rings')
            try:
                points,faces=self.plan.transform(**values)
                self.plan.validate(points,faces,values['mode'])
            except ValueError:
                # Show the current selection even when an input (e.g. zero
                # extrusion) is invalid; never leave an old patch highlighted.
                self.stop_collision_check()
                self.shown_points,self.shown_faces=self.topology.points,self.topology.triangles
                self.origins=np.arange(len(self.shown_faces))
                self.preview.show_mesh(self.shown_faces,self.plan.weights,self.shown_points,self.color_keys['invalid'])
                raise
            weights=self.plan.weights
            self.origins=np.arange(len(faces))
            if values['mode']=='Extrude':
                weights=np.r_[np.zeros(len(self.topology.points)),np.ones(len(self.plan.vertices))]
                keep=np.ones(len(self.topology.triangles),dtype=bool); keep[self.plan.selected]=False
                self.origins=np.r_[np.flatnonzero(keep),self.plan.selected,np.full(2*len(self.plan.boundary),-1)]
            self.shown_points,self.shown_faces=points,faces
            self.preview.show_mesh(faces,weights,points,self.color_keys[values['mode']])
            changed=values['mode']=='Extrude' or np.max(np.linalg.norm(points-self.topology.points,axis=1))>1e-9
            self.apply_button.setEnabled(bool(changed))
            self.summary_text='%s selected triangles · %s transition vertices' % (
                format(len(self.selected),','),format(self.plan.summary()['transition_vertices'] if values['mode']!='Extrude' else 0,','))
            if not changed:
                self.status.setText(self.summary_text+' · Enter a movement, rotation or extrusion distance.')
            else:
                self.status.setText(self.summary_text+' · Checking the preview for collisions…')
                self.stop_collision_check(); self.collision_timer.start(120)
            return bool(changed)
        except (ValueError,RuntimeError,ReferenceError) as error:
            self.reject(str(error)); return False

    def stop_collision_check(self):
        self.collision_timer.stop(); self.collision_poller.stop()
        if self.collision is not None and self.collision[2] is not None:
            # The single worker would run a queued check for a replaced
            # preview before the current one. A running check finishes.
            self.collision[2].cancel()
        self.collision=None

    def check_collisions(self):
        """Start the advisory collision estimate for the current preview."""
        if self.closed: return
        points,faces=self.shown_points,self.shown_faces
        candidates=mesh_collisions.changed_triangles(self.topology.points,points,self.topology.triangles,faces)
        if len(candidates)>mesh_collisions.PREVIEW_LIMIT:
            self.collision=(points,faces,None,None); self.show_collisions(); return
        future=_collisions.submit(mesh_collisions.find,points,faces,candidates)
        self.collision=(points,faces,future,None); self.collision_poller.start()

    def collisions_ready(self):
        if self.collision is None or self.closed:
            self.collision_poller.stop(); return
        points,faces,future,found=self.collision
        if not future.done(): return
        self.collision_poller.stop()
        try:
            found=future.result()
        except Exception as error:  # Advisory only; Apply runs the native check.
            App.Console.PrintWarning('SimpleCAD preview collision check: %s\n' % error)
            found=None
        if points is not self.shown_points or faces is not self.shown_faces:
            return  # A newer preview replaced this one.
        self.collision=(points,faces,future,found); self.show_collisions()

    def show_collisions(self):
        found=self.collision[3] if self.collision else None
        future=self.collision[2] if self.collision else None
        if future is None and self.collision is not None:
            note='Large edit: Apply checks it for collisions.'
        elif found is None:
            note='Apply checks it for collisions.'
        elif len(found):
            note=('Red: %s triangles would intersect other parts of the mesh. Apply\'s full check is expected '
                  'to reject this. Reduce the movement or change the selection or transition rings.' % format(len(found),','))
        else:
            note='No collisions found in the preview; Apply runs the full check.'
        self.preview.mark(found if found is not None and len(found) else ())
        if self.job is None:  # Apply's progress and result own the status line.
            self.status.setText(getattr(self,'summary_text','')+' · '+note)

    def show_failed_triangles(self,triangles):
        """Mark the triangles the background check rejected, when they map."""
        triangles=np.asarray(triangles,dtype=np.int64)
        if len(triangles) and triangles.max()<len(self.shown_faces):
            self.preview.mark(triangles)

    def handle_event(self,widget,event):
        if self.closed or self.controller.selection.replaying: return False
        kind=event.type()
        if kind not in (QtCore.QEvent.MouseButtonPress,QtCore.QEvent.MouseMove,QtCore.QEvent.MouseButtonRelease):
            return False
        # A physical mouse event visits QWidgetWindow before Qt forwards it to
        # the render QWidget. That intermediate release/move is not a click
        # outside the viewport and must not erase the pending press. Synthetic
        # sendEvent(viewport, ...) tests bypass this native-window delivery.
        if not isinstance(widget,QtWidgets.QWidget):
            return False
        if not self.controller.selection.is_viewport(widget):
            self.press=None
            return False
        navigation = (event.modifiers() & (QtCore.Qt.AltModifier|QtCore.Qt.ControlModifier|QtCore.Qt.MetaModifier)
                      or event.buttons() & (QtCore.Qt.MiddleButton|QtCore.Qt.RightButton))
        if navigation:
            if self.press is not None and self.press[0] is widget:
                # Preserve CAD navigation's left-then-middle/right chords.
                # replay() sets its guard so this event is not captured again.
                self.controller.selection.replay(widget,(self.press[3],))
            self.press=None
            return False
        width,height=self.controller.view.getSize(); p=event.localPos()
        logical=np.asarray((p.x(),p.y()))
        pos=np.asarray((p.x()*width/widget.width(),height-p.y()*height/widget.height()))
        if kind==QtCore.QEvent.MouseButtonPress and event.button()==QtCore.Qt.LeftButton:
            original=(kind,p,event.globalPos(),event.button(),event.buttons(),event.modifiers())
            self.press=(widget,logical,False,original)
            widget.setFocus(QtCore.Qt.MouseFocusReason)
            return True
        if self.press is None: return False
        owner,down,dragged,original=self.press
        if owner is not widget: self.press=None; return False
        if kind==QtCore.QEvent.MouseMove:
            # Qt's threshold is in logical pixels, including on Retina screens.
            dragged = dragged or np.linalg.norm(logical-down)>=QtWidgets.QApplication.startDragDistance()
            self.press=(owner,down,dragged,original); return True
        if kind==QtCore.QEvent.MouseButtonRelease and event.button()==QtCore.Qt.LeftButton:
            self.press=None
            if not dragged:
                self.check(); origin,direction=ray(self.controller.view,pos)
                hit=self.topology.pick(tuple(origin),tuple(direction),self.shown_points,self.shown_faces)
                if hit is None:
                    self.pick_feedback('No mesh patch at that point. Click a visible mesh surface.')
                elif self.origins[hit]<0:
                    self.pick_feedback('Click an original surface or the orange end face to change the selection.')
                else:
                    region=self.topology.region(int(self.origins[hit])+1,self.selection.currentText(),self.crease.value())
                    action='Add' if event.modifiers() & QtCore.Qt.ShiftModifier else self.action.currentText()
                    selected=(self.selected|region if action=='Add' else self.selected-region if action=='Remove' else region)
                    if selected==self.selected:
                        message=('That patch is not selected. Choose Replace or Add to select it.' if action=='Remove'
                                 else 'That patch is already selected. Enter a movement, rotation or extrusion distance.')
                        self.pick_feedback(message)
                    else:
                        self.selected=selected
                        self.changed()
            return True
        return False

    def apply(self):
        if not self.update_preview(): return
        try:
            self.job=mesh_jobs.start_region(self.source,triangles=[int(i)+1 for i in sorted(self.selected)],**self.values())
            self.apply_button.setEnabled(False); self.progress.show(); self.poller.start()
            self.status.setText('Checking the edited mesh in the background…')
        except (ValueError,RuntimeError) as error: self.reject(str(error))

    def poll(self):
        if self.closed or self.job is None: return
        state=self.job.status(); self.status.setText(state['error'] or state['stage'])
        if state['status']=='running': return
        self.poller.stop(); self.progress.hide()
        if state['status']!='ready':
            self.reject(state['error'] or state['stage'])
            self.show_failed_triangles(getattr(self.job,'failed_triangles',()))
            return
        try:
            self.check(); self.preview.clear(); self.job.apply()
            warnings = self.job.report.get('warnings',[])
            for warning in warnings:
                App.Console.PrintWarning('SimpleCAD mesh region: '+warning+'\n')
            self.controller.cancel(quiet=True); self.controller.faces.refresh()
            self.controller.message('Mesh region edited · Original kept hidden · Undo restores it'
                                    + (' · '+warnings[0] if warnings else ''))
        except (ValueError,RuntimeError) as error:
            self.job.cancel(); self.reject(str(error))

    def close(self):
        if self.closed: return
        self.closed=True; self.pending.stop(); self.poller.stop(); self.press=None
        self.stop_collision_check()
        if self.job: self.job.cancel()
        self.preview.close(); self.dialog.hide(); self.dialog.deleteLater()
