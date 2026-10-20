"""Native viewport arc interaction, snapping, numeric input, cancel and materials."""
import math
import time
from unittest.mock import patch
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.modeling import arcs
from simplecad.document import operations as op, appearance
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
V = App.Vector


def run(screenshot=None):
    Gui.activateWorkbench('SimpleCADWorkbench')
    c=instance(); c.cancel(quiet=True)
    doc=App.newDocument('ArcSmoke'); doc.UndoMode=1
    host=op.new_shape(doc,Part.makeBox(40,30,12),'Arc reference')
    view=Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue((0,0,0,1)); view.fitAll()
    for _ in range(4): QtWidgets.QApplication.processEvents(); Gui.updateGui()
    c.controls.plane.setCurrentText('Auto'); c.controls.snap.setChecked(True)
    def pos(p): return tuple(int(round(v)) for v in screen(view,p))
    def key(key,text='',field=None):
        if field is None: c.focus_view()
        else: field.setFocus()
        focus=QtWidgets.QApplication.focusWidget(); assert focus is not None
        for kind in (QtCore.QEvent.ShortcutOverride,QtCore.QEvent.KeyPress,QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(focus,QtGui.QKeyEvent(kind,key,QtCore.Qt.NoModifier,text))
    def exact(text):
        key(QtCore.Qt.Key_Tab); assert QtWidgets.QApplication.focusWidget()==c.controls.value
        c.controls.value.setText(text); key(QtCore.Qt.Key_Return,field=c.controls.value)
    def begin(tool,point):
        Gui.runCommand('SimpleCAD_'+tool,0); assert c.tool==tool
        c.click(pos(point))
    for tool in ('Arc','Arc2Point'):
        assert 'SimpleCAD_'+tool in Gui.listCommands()
        assert not QtGui.QIcon(str(ROOT/'Resources/icons'/(tool.lower()+'.svg'))).pixmap(56,56).isNull()
    # Center magnet, exact radius then signed degrees; no objects during preview.
    key(QtCore.Qt.Key_A,'a'); assert c.tool=='Arc'
    x,y=pos(V(20,15,12)); c.motion((x+15,y))
    assert c.controls.label.text()=='Face center'
    c.click((x+15,y)); assert (c.anchor-V(20,15,12)).Length<1e-6
    count=doc.UndoCount
    for invalid in ('0','-2','45 deg'):
        exact(invalid); assert c.arc_input.second is None and doc.UndoCount==count
    c.motion(pos(V(30,15,12))); exact('1 cm')
    assert c.arc_input.second is not None and doc.UndoCount==count and len(doc.Objects)==1
    for invalid in ('0','360','-360','2 mm'):
        exact(invalid); assert c.tool=='Arc' and doc.UndoCount==count
    with patch.object(Part,'Arc',side_effect=AssertionError('kernel in preview')):
        started=time.perf_counter()
        for i in range(100):
            theta=math.radians(i*2.7)
            c.motion(pos(V(20+10*math.cos(theta),15+10*math.sin(theta),12)))
        preview_ms=(time.perf_counter()-started)*10
    assert c.arc_input.angle>240, c.arc_input.angle
    exact('-270 deg'); assert c.tool is None and doc.UndoCount==count+1
    curve=next(o for o in doc.Objects if o!=host)
    assert isinstance(curve.Shape.Edges[0].Curve,Part.Circle)
    assert abs(curve.Shape.Length-15*math.pi)<1e-6
    doc.undo(); assert len(doc.Objects)==1
    # Cancel at each stage, both toolbar tools and keyboard H.
    for tool in ('Arc','Arc2Point'):
        for stage in (1,2):
            begin(tool,V(0,0,12)); overlay=c.preview.root
            if stage==2: c.click(pos(V(40,0,12)))
            count=doc.UndoCount; key(QtCore.Qt.Key_Escape)
            assert c.tool is None and doc.UndoCount==count and view.getSceneGraph().findChild(overlay)==-1
    # Actual endpoint clicks and bulge click partition the host, preserving another face's material.
    materials=list(host.ViewObject.ShapeAppearance)
    material=appearance.clone(materials[0]); material.DiffuseColor=(1.,0.,0.); material.Transparency=.43
    if len(materials)==1: materials=materials*6
    materials[0]=material; host.ViewObject.ShapeAppearance=materials
    styled=host.Shape.Faces[0].CenterOfMass
    key(QtCore.Qt.Key_H,'h'); assert c.tool=='Arc2Point'
    c.click(pos(V(0,0,12))); c.motion(pos(V(40,0,12)))
    assert c.controls.label.text()=='Endpoint'
    c.click(pos(V(40,0,12))); c.motion(pos(V(20,10,12)))
    assert c.arc_input.bulge>0 and doc.UndoCount==count
    c.click(pos(V(20,10,12)))
    assert c.tool is None and len(doc.Objects)==1 and len(host.Shape.Faces)==7
    assert host.Shape.isValid() and host.Shape.isClosed() and abs(host.Shape.Volume-14400)<1e-6
    index=next(i for i,f in enumerate(host.Shape.Faces) if (f.CenterOfMass-styled).Length<1e-6)
    actual=host.ViewObject.ShapeAppearance[index]
    assert tuple(actual.DiffuseColor)[:3]==(1.,0.,0.) and abs(actual.Transparency-.43)<1e-6
    doc.undo(); assert len(host.Shape.Faces)==6
    # Exact chord distance and negative bulge; typed length maintains direction.
    begin('Arc2Point',V(0,0,12)); c.motion(pos(V(40,0,12))); exact('4 cm')
    assert abs((c.arc_input.second-c.anchor).Length-40)<1e-6
    for invalid in ('0','30 deg'):
        exact(invalid); assert c.tool=='Arc2Point' and len(doc.Objects)==1
    exact('-1 cm'); assert c.tool is None and len(doc.Objects)==2
    # Positive center arc with mouse clicks; midpoint snapping, then document Undo cancels session.
    begin('Arc',V(0,0,12)); c.motion(pos(V(20,0,12)))
    assert c.controls.label.text()=='Midpoint'
    c.click(pos(V(20,0,12))); c.click(pos(V(0,20,12)))
    assert c.tool is None
    begin('Arc',V(0,0,12)); c.click(pos(V(20,0,12)))
    doc.undo(); c.check_context(); assert c.tool is None
    if screenshot:
        Gui.Selection.clearSelection(); host.ViewObject.Visibility=True
        view.viewIsometric(); view.fitAll()
        for _ in range(10): QtWidgets.QApplication.processEvents(); Gui.updateGui(); time.sleep(.1)
        view.saveImage(str(screenshot),1000,750,'Current')
    c.cancel(quiet=True); App.closeDocument(doc.Name)
    # Fixed YZ drawing plane with a face-on camera and no host geometry.
    doc=App.newDocument('ArcYZSmoke'); doc.UndoMode=1
    view=Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(*App.Rotation(V(0,0,1),V(1,0,0)).Q)
    view.getCameraNode().height=80
    for _ in range(4): QtWidgets.QApplication.processEvents(); Gui.updateGui()
    c.controls.plane.setCurrentText('YZ'); c.controls.snap.setChecked(False)
    begin('Arc2Point',V(0,-10,0)); c.click(pos(V(0,10,0))); c.click(pos(V(0,0,8)))
    assert c.tool is None and len(doc.Objects)==1
    edge=doc.Objects[0].Shape.Edges[0]
    assert isinstance(edge.Curve,Part.Circle) and edge.BoundBox.XLength<1e-6
    assert abs(abs(edge.Curve.Axis.x)-1)<1e-6
    c.controls.plane.setCurrentText('Auto'); c.controls.snap.setChecked(True)
    App.closeDocument(doc.Name)
    return {'result':'PASS','preview_ms':round(preview_ms,3),'tools':['Arc','Arc2Point']}
