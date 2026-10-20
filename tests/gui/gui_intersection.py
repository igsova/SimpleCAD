"""Native 72-face sphere/bowl edit, selection, materials, timing and Undo."""
import math
import runpy
import time
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import appearance as a, operations as op
from simplecad.core import geometry as g
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
V=App.Vector


def run(screenshots=False):
    Gui.activateWorkbench('SimpleCADWorkbench'); c=instance(); c.cancel(quiet=True)
    doc=App.newDocument('IntersectionSmoke'); doc.UndoMode=1
    block=op.new_shape(doc,runpy.run_path(str(ROOT/'tests/gui/gui_material_mapping.py'))['rubik'](),'Rubik reference')
    center=V(10,0,10)
    sphere=op.new_shape(doc,g.sphere(center,4),'Sphere'); sphere_name=sphere.Name
    find=lambda obj,fn: next('Face'+str(i) for i,f in enumerate(obj.Shape.Faces,1) if fn(f))
    target=find(block,lambda f:(f.CenterOfMass-center).Length<1e-6)
    red=find(block,lambda f:(f.CenterOfMass-V(10,0,30)).Length<1e-6)
    a.commit(a.prepare([(block,(target,))]),color=[0,1,0],opacity=100)
    a.commit(a.prepare([(block,(red,))]),color=[1,0,0],opacity=57)
    a.commit(a.prepare([(sphere,())]),color=[0,0,1],opacity=75)
    original=a.fingerprint(block.ViewObject.ShapeAppearance,precision=6)
    count=doc.UndoCount
    view=Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(*App.Rotation(V(0,0,1),V(0,-1,0)).Q)
    view.fitAll(); Gui.updateGui()
    def flush():
        for _ in range(3): QtWidgets.QApplication.processEvents(); Gui.updateGui()
        c.seams.refresh(); c.faces.refresh()
    def pos(point): return tuple(round(n) for n in screen(view,point))
    def select(obj, names):
        Gui.Selection.clearSelection()
        for name in names: Gui.Selection.addSelection(obj,name)
    assert 'SimpleCAD_Intersect' in Gui.listCommands()
    assert not QtGui.QIcon(str(ROOT/'Resources/icons/intersect.svg')).pixmap(56,56).isNull()
    select(block,[target]); Gui.Selection.addSelection(sphere,'Face1')
    c.focus_view(); focus=QtWidgets.QApplication.focusWidget()
    start=time.perf_counter()
    for kind in (QtCore.QEvent.ShortcutOverride,QtCore.QEvent.KeyPress,QtCore.QEvent.KeyRelease):
        QtWidgets.QApplication.sendEvent(focus,QtGui.QKeyEvent(kind,QtCore.Qt.Key_I,QtCore.Qt.NoModifier,'i'))
    elapsed=(time.perf_counter()-start)*1000
    assert doc.UndoCount==count+1 and doc.getObject(sphere_name) is None
    assert len(block.Shape.Faces)==75, len(block.Shape.Faces)
    flush()
    def check_materials():
        for i,face in enumerate(block.Shape.Faces,1):
            style=a.describe(block,i)
            if isinstance(face.Surface,Part.Sphere): assert style=={'color':[0.,0.,1.],'opacity':75},style
            elif (face.CenterOfMass-V(10,0,30)).Length<1e-6: assert style=={'color':[1.,0.,0.],'opacity':57},style
            elif abs(face.CenterOfMass.y)<1e-6 and (face.CenterOfMass-center).Length<1e-6:
                assert style=={'color':[0.,1.,0.],'opacity':100},style
    check_materials()
    upper=find(block,lambda f:isinstance(f.Surface,Part.Sphere) and f.CenterOfMass.y<0)
    hit=pick(view,doc,pos(center),face_only=True)
    assert hit and isinstance(hit[1].Surface,Part.Sphere) and hit[1].CenterOfMass.y<0
    select(block,[upper]); Gui.runCommand('SimpleCAD_Delete',0)
    assert len(block.Shape.Faces)==74; flush(); check_materials()
    disk=find(block,lambda f:isinstance(f.Surface,Part.Plane) and abs(f.Area-math.pi*16)<1e-5)
    hit=pick(view,doc,pos(center),face_only=True)
    assert hit and abs(hit[1].Area-math.pi*16)<1e-5
    select(block,[disk]); Gui.runCommand('SimpleCAD_Delete',0)
    assert len(block.Shape.Solids)==1 and block.Shape.isValid() and block.Shape.isClosed()
    assert abs(block.Shape.Volume-(160000-2*math.pi*64/3))<1e-5
    flush(); check_materials()
    hit=pick(view,doc,pos(center),face_only=True)
    assert hit and isinstance(hit[1].Surface,Part.Sphere) and hit[1].CenterOfMass.y>0
    if screenshots:
        view.getCameraNode().orientation.setValue(*App.Rotation(V(0,0,1),V(0,-1,.6)).Q)
        view.fitAll(); flush()
        view.saveImage(str(ROOT.parent.parent/'work/intersection-bowl.png'),1100,850,'Current')
    for _ in range(3): doc.undo()
    assert doc.getObject(sphere_name) is not None and len(block.Shape.Faces)==72
    assert a.fingerprint(block.ViewObject.ShapeAppearance,precision=6)==original
    for _ in range(3): doc.redo()
    assert block.Shape.ShapeType=='Solid'; check_materials()
    result={'intersection_ms':round(elapsed,1),'faces':len(block.Shape.Faces),'volume':block.Shape.Volume,
            'result':'PASS: I command, native picks of hemisphere/disk/bowl, source materials, deletion, Undo/Redo'}
    App.Console.PrintMessage(str(result)+'\n')
    return result
