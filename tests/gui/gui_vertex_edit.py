"""Native vertex pick, drag/release, axis keys, typed vector and material lineage."""
from types import SimpleNamespace
import time
import FreeCAD as App
import FreeCADGui as Gui
import Part
from pivy import coin
from simplecad.core import geometry as g
from simplecad.document import operations as op, appearance
from simplecad.modeling import vertex_edit as ve
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
V=App.Vector


def run(screenshot=None):
    Gui.activateWorkbench('SimpleCADWorkbench');c=instance();c.cancel(quiet=True)
    doc=App.newDocument('VertexSmoke');doc.UndoMode=1
    obj=op.new_shape(doc,Part.makeBox(20,20,20),'Vertex demo')
    corner=V(20,20,20)
    name=next('Vertex'+str(i) for i,v in enumerate(obj.Shape.Vertexes,1) if ve.same(v.Point,corner))
    n=op.prepare_vertex(obj,name)
    styled=next(iter(n.faces))
    appearance.commit(appearance.prepare([(obj,['Face'+str(styled+1)])]),color=[.9,.12,.1],opacity=57)
    original=obj.Shape;materials=tuple(obj.ViewObject.ShapeAppearance)
    view=Gui.activeDocument().activeView();view.getCameraNode().orientation.setValue(*App.Rotation(V(0,0,1),V(1,1,1)).Q);view.fitAll();Gui.updateGui()
    assert 'SimpleCAD_VertexMove' in Gui.listCommands()
    def pos(point):return tuple(round(x) for x in screen(view,point))
    def mouse(state,position):
        e=coin.SoMouseButtonEvent();e.setButton(coin.SoMouseButtonEvent.BUTTON1);e.setState(state);e.setPosition(coin.SbVec2s(*position))
        c.coin_event(SimpleNamespace(getEvent=lambda:e,setHandled=lambda:None))
    def key(char):
        c.focus_view();focus=QtWidgets.QApplication.focusWidget()
        for kind in (QtCore.QEvent.ShortcutOverride,QtCore.QEvent.KeyPress,QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(focus,QtGui.QKeyEvent(kind,ord(char),QtCore.Qt.NoModifier,char.lower()))
    def enter(text):
        c.controls.value.setText(text);c.controls.value.setFocus()
        for kind in (QtCore.QEvent.ShortcutOverride,QtCore.QEvent.KeyPress,QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(c.controls.value,QtGui.QKeyEvent(kind,QtCore.Qt.Key_Return,QtCore.Qt.NoModifier))
    Gui.Selection.clearSelection();c.start('VertexMove');hit=pick(view,doc,pos(corner),prefer_boundary=True)
    assert hit and hit[3]==name,hit
    before=doc.UndoCount;mouse(coin.SoButtonEvent.DOWN,pos(corner));assert ve.same(c.anchor,corner)
    key('Z');assert c.axis==V(0,0,1)
    c.controls.snap.setChecked(False)
    destination=pos(corner+V(0,0,5))
    start=time.perf_counter()
    for _ in range(100):c.motion(destination)
    preview_ms=(time.perf_counter()-start)*10
    assert obj.Shape.isSame(original) and doc.UndoCount==before
    delta=c.point-c.anchor
    mouse(coin.SoButtonEvent.UP,destination)
    assert c.tool is None and doc.UndoCount==before+1
    assert any(ve.same(v.Point,corner+delta) for v in obj.Shape.Vertexes)
    assert obj.Shape.isClosed() and obj.Shape.isValid()
    doc.undo();assert obj.Shape.isSame(original) or abs(obj.Shape.Volume-original.Volume)<1e-7
    # Preselected vertex + exact XYZ displacements; bent faces retain styles.
    Gui.Selection.clearSelection();Gui.Selection.addSelection(obj,name);c.start('VertexMove')
    assert ve.same(c.anchor,corner)
    captured=c.vertex_neighborhood
    expected,origins=captured.build(V(3,2,4))
    expected_materials=[materials[i] if len(materials)==6 else materials[0] for i in origins]
    start=time.perf_counter();enter('3 mm, 2 mm, 4 mm');commit_ms=(time.perf_counter()-start)*1000
    assert c.tool is None and obj.Shape.isClosed()
    assert any(ve.same(v.Point,corner+V(3,2,4)) for v in obj.Shape.Vertexes)
    assert appearance.fingerprint(obj.ViewObject.ShapeAppearance,6)==appearance.fingerprint(expected_materials,6)
    doc.undo();assert appearance.fingerprint(obj.ViewObject.ShapeAppearance,6)==appearance.fingerprint(materials,6)
    doc.redo();assert obj.Shape.isClosed()
    if screenshot:
        Gui.Selection.clearSelection();Gui.updateGui();view.fitAll();view.saveImage(str(screenshot),1100,800,'Current')
    # Cancel and external edits invalidate the captured vertex without writing.
    Gui.Selection.clearSelection();c.start('VertexMove');c.choose_vertex(obj,'Vertex1');before=doc.UndoCount;c.cancel()
    assert doc.UndoCount==before
    c.start('VertexMove');c.choose_vertex(obj,'Vertex1');doc.undo();c.check_context();assert c.tool is None
    # A single signed numeric distance on X works without mouse displacement.
    Gui.Selection.clearSelection();Gui.Selection.addSelection(obj,name);c.start('VertexMove');key('X');enter('2')
    assert c.tool is None and any(ve.same(v.Point,corner+V(2,0,0)) for v in obj.Shape.Vertexes)
    # A circle drawn on the top does not block its corner; the circle stays exact.
    obj.Shape=g.divide_face_with_profile(Part.makeBox(20,20,20),g.circle(g.Plane.named('XY',V(0,0,20)),V(10,10,20),4))
    view.fitAll();Gui.updateGui()
    name=next('Vertex'+str(i) for i,v in enumerate(obj.Shape.Vertexes,1) if ve.same(v.Point,corner))
    hit=pick(view,doc,pos(corner),prefer_boundary=True);assert hit and hit[3]==name,hit
    before=doc.UndoCount
    Gui.Selection.clearSelection();Gui.Selection.addSelection(obj,name);c.start('VertexMove');key('Z');enter('-4')
    assert c.tool is None and doc.UndoCount==before+1
    assert any(ve.same(v.Point,corner+V(0,0,-4)) for v in obj.Shape.Vertexes)
    assert obj.Shape.isValid() and obj.Shape.isClosed()
    assert any(isinstance(e.Curve,Part.Circle) and abs(e.Curve.Radius-4)<1e-9 for e in obj.Shape.Edges)
    return {'result':'PASS','preview_ms':round(preview_ms,2),'commit_ms':round(commit_ms,1)}
