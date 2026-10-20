"""Pick a face/edge, move to either side, then click or enter an exact offset."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from ...core import geometry as g
from ...document import operations as ops, locking
from ...modeling.offsetting import Profile
from ..snapping import pick, ray
from ..previews.overlay import edges, outline
from ..qt import QtCore


class OffsetInput:
    def __init__(self, controller):
        self.c=controller; self.obj=None; self.planned=None; self.distance=0.; self.side=-1
        self.timer=QtCore.QTimer(controller); self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)

    def close(self):
        self.timer.stop(); self.timer.deleteLater()

    def check(self):
        if self.obj is None: return
        try:
            if not self.obj.Shape.isSame(self.original): raise ValueError()
        except Exception as error:
            raise ValueError('The source changed. Start Offset again.') from error

    def choose(self,obj,name,point):
        c=self.c; ops.editable(obj)
        source=obj.Shape.getElement(name)
        normal=None
        if source.ShapeType=='Edge' and isinstance(source.Curve,Part.Line):
            mode=c.controls.plane.currentText()
            if mode!='Auto': normal=g.Plane.named(mode).normal
            else:
                # Use a supporting flat face when present, preferring the face
                # most directly facing the view. Loose lines use a view plane.
                adjacent=[f for f in obj.Shape.ancestorsOfType(source,Part.Face) if isinstance(f.Surface,Part.Plane)]
                if not adjacent: adjacent=[f for f in obj.Shape.Faces if isinstance(f.Surface,Part.Plane) and any(e.isSame(source) for e in f.Edges)]
                if adjacent:
                    face=max(adjacent,key=lambda f:abs(g.face_normal(f).dot(c.view.getViewDirection())))
                    normal=g.face_normal(face)
                else:
                    tangent=g.unit(source.valueAt(source.LastParameter)-source.valueAt(source.FirstParameter))
                    view=c.view.getViewDirection()
                    normal=view-tangent*view.dot(tangent)
                    if normal.Length<g.EPS: raise ValueError('Orbit the view or choose XY/XZ/YZ for this line offset.')
        profile=Profile(source,normal)
        if profile.face: locking.require_unlocked(obj,[name])
        self.obj,self.name,self.original,self.profile=obj,name,obj.Shape,profile
        self.distance=0.;self.planned=None;self.side=-1 if profile.face else 1
        c.anchor=point; c.plane=profile.plane
        Gui.Selection.clearSelection(); Gui.Selection.clearPreselection()
        c.preview.update(edges(source))
        c.controls.value.setPlaceholderText('Offset distance')
        c.message('Move inward/outward · Click to keep · Tab for distance (− inward, + outward) · Esc cancels'
                  if profile.face or isinstance(source.Curve,Part.Circle) else
                  'Move to either side · Click to keep · Tab for distance · Esc cancels')

    def hover(self,pos):
        hit=pick(self.c.view,self.c.doc,pos,prefer_boundary=True)
        if hit and hit[1].ShapeType in ('Face','Edge'):
            self.c.preview.update(outline(hit[1]),hit[2])
        else: self.c.preview.update()
        return hit

    def click(self,pos):
        if self.obj is None:
            hit=self.hover(pos)
            if not hit or hit[1].ShapeType not in ('Face','Edge'): raise ValueError('Click a face or edge, away from its vertices.')
            self.choose(hit[0],hit[3],hit[2]); return False
        self.motion(pos); self.refresh(raise_error=True)
        return True

    def motion(self,pos):
        if self.obj is None: self.hover(pos); return
        self.check()
        point=self.profile.plane.intersect(*ray(self.c.view,pos))
        self.distance=self.profile.distance_at(point)
        if abs(self.distance)>g.EPS: self.side=1 if self.distance>0 else -1
        if not self.timer.isActive(): self.timer.start(30)

    def refresh(self,raise_error=False):
        self.timer.stop(); self.planned=None
        try:
            self.check()
            if abs(self.distance)<g.EPS:
                self.c.preview.update(edges(self.profile.source))
                raise ValueError('Move away from the original boundary to set an offset.')
            self.planned=self.profile.offset(self.distance)
            self.c.preview.update(edges(self.planned))
            circular=isinstance(getattr(self.profile.source,'Curve',None),Part.Circle)
            side=('Outward' if self.distance>0 else 'Inward') if self.profile.face or circular else ('Left' if self.distance>0 else 'Right')
            self.c.controls.label.setText('%s offset %.3g mm' % (side,abs(self.distance)))
            self.c.controls.value.setPlaceholderText('%.3g mm · %s' % (abs(self.distance),side.lower()))
            return True
        except Exception as error:
            self.c.preview.update(edges(self.profile.source))
            self.c.controls.label.setText('Offset unavailable')
            if raise_error: raise
            self.c.message(str(error)+' · Reduce distance or Esc to cancel')
            return False

    def numeric(self,text):
        distance=g.parse_length(text.strip().removeprefix('+'))
        # Unsigned dimensions keep the mouse-chosen side; explicit signs choose it.
        self.distance=distance if text.strip().startswith(('+','-')) else abs(distance)*self.side
        self.refresh(raise_error=True)

    def commit(self):
        self.check()
        return ops.offset(self.obj,self.name,self.distance,self.profile.plane.normal)
