"""Native Offset interaction, exact distances, open curves, materials and latency."""
import time
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import operations as op, appearance as a
from simplecad.modeling import arcs
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
V=App.Vector


def run(screenshot=None):
    Gui.activateWorkbench('SimpleCADWorkbench'); c=instance();c.cancel(quiet=True)
    doc=App.newDocument('OffsetSmoke');doc.UndoMode=1
    host=op.new_shape(doc,Part.makeBox(30,20,8),'Offset test')
    a.commit(a.prepare([(host,['Face1'])]),color=[1,0,0],opacity=57)
    a.commit(a.prepare([(host,['Face6'])]),color=[0.2,0.8,0.4],opacity=80)
    original=host.Shape;styled=host.Shape.Faces[0].CenterOfMass
    view=Gui.activeDocument().activeView();view.getCameraNode().orientation.setValue((0,0,0,1));view.fitAll()
    for _ in range(5):QtWidgets.QApplication.processEvents();Gui.updateGui()
    Gui.getMainWindow().activateWindow();Gui.getMainWindow().raise_()
    for _ in range(4):QtWidgets.QApplication.processEvents();time.sleep(.05)
    c.controls.plane.setCurrentText('Auto')
    def pos(point):return tuple(round(v) for v in screen(view,point))
    def key(key,text='',field=None):
        if field is None:c.focus_view()
        else:field.setFocus()
        focus=QtWidgets.QApplication.focusWidget();assert focus is not None
        for kind in (QtCore.QEvent.ShortcutOverride,QtCore.QEvent.KeyPress,QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(focus,QtGui.QKeyEvent(kind,key,QtCore.Qt.NoModifier,text))
    def exact(text):
        key(QtCore.Qt.Key_Tab);assert QtWidgets.QApplication.focusWidget()==c.controls.value
        c.controls.value.setText(text);key(QtCore.Qt.Key_Return,field=c.controls.value)
    def select(obj,name):
        Gui.Selection.clearSelection();Gui.Selection.addSelection(obj,name)
        Gui.runCommand('SimpleCAD_Offset',0)
        assert c.tool=='Offset' and c.offset_input.obj==obj
    assert 'SimpleCAD_Offset' in Gui.listCommands()
    assert not QtGui.QIcon(str(ROOT/'Resources/icons/offset.svg')).pixmap(56,56).isNull()
    Gui.Selection.clearSelection();key(QtCore.Qt.Key_E,'e');assert c.tool=='Offset'
    c.click(pos(V(15,5,8)));assert c.offset_input.name=='Face6'
    count=doc.UndoCount;root=c.preview.root
    c.motion(pos(V(15,2,8)));assert c.offset_input.distance<0
    started=time.perf_counter()
    for i in range(50):
        c.motion(pos(V(15,1+i*.05,8)));assert c.offset_input.refresh()
    preview_ms=(time.perf_counter()-started)*1000/50
    assert len(doc.Objects)==1 and doc.UndoCount==count
    assert len(c.preview.lines.numVertices.getValues())==4
    key(QtCore.Qt.Key_Escape)
    assert c.tool is None and view.getSceneGraph().findChild(root)==-1 and doc.UndoCount==count
    # Preselected face, invalid input recovery and unsigned magnitude keeping inward side.
    select(host,'Face6')
    for invalid in ('0','-11 mm','3 deg'):
        exact(invalid);assert c.tool=='Offset' and doc.UndoCount==count
    c.motion(pos(V(15,2,8)))
    exact('2 mm');assert c.tool is None and len(host.Shape.Faces)==7
    small=next(f for f in host.Shape.Faces if abs(f.Area-416)<1e-5)
    for i,f in enumerate(host.Shape.Faces):
        material=a.expanded(host)[i]
        if abs(f.CenterOfMass.z-8)<1e-6:
            assert abs(material.DiffuseColor[1]-.8)<1e-6 and abs(material.Transparency-.2)<1e-6
        if (f.CenterOfMass-styled).Length<1e-6:
            assert material.DiffuseColor[0]==1 and abs(material.Transparency-.43)<1e-6
    for _ in range(6):QtWidgets.QApplication.processEvents();Gui.updateGui();time.sleep(.05)
    hit=pick(view,doc,pos(V(15,10,8)),face_only=True)
    assert hit and abs(hit[1].Area-small.Area)<1e-5
    doc.undo();assert len(host.Shape.Faces)==6
    # Explicit outward dimension makes border surface; source solid stays closed.
    select(host,'Face6');exact('+2 mm')
    assert c.tool is None and len(doc.Objects)==2 and host.Shape.isClosed(), (c.tool,len(doc.Objects),Gui.getMainWindow().statusBar().currentMessage())
    border=next(o for o in doc.Objects if o!=host)
    assert abs(border.Shape.Area-216)<1e-6
    assert abs(a.expanded(border)[0].Transparency-.2)<1e-6
    doc.undo();assert len(doc.Objects)==1
    # Actual line click and mouse finish, with explicit plane controlling side.
    line=op.new_shape(doc,Part.makeLine(V(5,5,8),V(25,5,8)),'Offset line')
    c.controls.plane.setCurrentText('XY')
    Gui.Selection.clearSelection();Gui.runCommand('SimpleCAD_Offset',0)
    c.click(pos(V(15,5,8)));assert c.offset_input.profile.source.ShapeType=='Edge'
    count=doc.UndoCount;c.motion(pos(V(15,8,8)));c.click(pos(V(15,8,8)))
    assert c.tool is None and doc.UndoCount==count+1
    copied=doc.Objects[-1];assert not copied.Shape.Faces and abs(copied.Shape.Length-20)<1e-5
    assert abs(copied.Shape.CenterOfMass.y-8)<.1
    assert len(host.Shape.Faces)==6
    # Arc radius offsets preserve the source arc and do not create a face.
    curve=op.new_shape(doc,arcs.two_point(V(5,5,8),V(25,5,8),V(0,0,1),10).edge(),'Offset arc')
    select(curve,'Edge1');exact('+2 mm')
    copied=doc.Objects[-1];assert not copied.Shape.Faces and not copied.Shape.isClosed()
    assert abs(copied.Shape.Edges[0].Curve.Radius-12)<1e-6
    select(curve,'Edge1');exact('-10 mm');assert c.tool=='Offset'
    key(QtCore.Qt.Key_Escape)
    # A changed document invalidates the source snapshot and removes its pending preview.
    select(curve,'Edge1');c.motion(pos(V(15,17,8)));overlay=c.preview.root
    doc.undo();c.check_context();assert c.tool is None and view.getSceneGraph().findChild(overlay)==-1
    # Keep a clean inward example for the rendering check.
    for obj in list(doc.Objects):
        if obj!=host:doc.removeObject(obj.Name)
    doc.recompute();Gui.Selection.clearSelection();select(host,'Face6');exact('-2 mm')
    if screenshot:
        view.viewIsometric();view.fitAll();Gui.Selection.clearSelection()
        for _ in range(10):QtWidgets.QApplication.processEvents();Gui.updateGui();time.sleep(.1)
        view.saveImage(str(screenshot),1000,750,'Current')
    c.cancel(quiet=True);c.controls.plane.setCurrentText('Auto');App.closeDocument(doc.Name)
    return {'result':'PASS','preview_ms':round(preview_ms,3)}
