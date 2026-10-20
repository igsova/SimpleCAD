"""Native radius preview, Apply/Cancel, restored rendering and document state."""
import tempfile
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import operations as op
from simplecad.core import geometry as g
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
V=App.Vector

def run(screenshots=False):
    Gui.activateWorkbench('SimpleCADWorkbench')
    c=instance();c.cancel(quiet=True)
    doc=App.newDocument('SimpleCADRoundSmoke');doc.UndoMode=1
    obj=op.new_shape(doc,Part.makeBox(40,30,20),'Round test')
    view=Gui.activeDocument().activeView();view.viewIsometric();view.fitAll();Gui.updateGui()
    def flush():
        for _ in range(3):QtWidgets.QApplication.processEvents();Gui.updateGui()
    def start(names=()):
        Gui.Selection.clearSelection()
        for name in names or ('',):Gui.Selection.addSelection(obj,name)
        Gui.runCommand('SimpleCAD_Round')
        flush()
        assert c.tool=='Round' and c.round_session is not None
        return c.round_session
    def value(session,text):
        session.radius.setText(text)
        result=session.update_preview();flush()
        return result
    def save(name):
        if screenshots:view.saveImage(str(ROOT.parent.parent/'work'/name),1000,750,'Current')
    original=obj.Shape
    native_children=obj.ViewObject.RootNode.getNumChildren()
    count=doc.UndoCount
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'Before.FCStd';name=obj.Name
        doc.saveAs(str(path));App.closeDocument(doc.Name)
        doc=App.openDocument(str(path));doc.UndoMode=1;obj=doc.getObject(name)
        view=Gui.activeDocument().activeView();view.viewIsometric();view.fitAll();flush()
        original=obj.Shape;native_children=obj.ViewObject.RootNode.getNumChildren();count=doc.UndoCount
        assert not Gui.activeDocument().Modified
        save('round-before.png')
        session=start()
        assert session.planned is not None,session.status.text()
        assert len(session.planned[0][1].Faces)==26
        assert value(session,'3 mm'),session.status.text()
        assert session.preview.masks and session.apply_button.isEnabled()
        assert obj.Shape.isSame(original) and obj.ViewObject.Visibility
        assert doc.UndoCount==count and len(doc.Objects)==1 and not Gui.activeDocument().Modified
        if screenshots:session.dialog.grab().save(str(ROOT.parent.parent/'work'/'round-panel.png'))
        save('round-preview.png')
        # A too-large/invalid radius shows the original rather than a stale result.
        for bad in ('100 mm','-1 mm','banana','nan'):
            assert not value(session,bad)
            assert not session.apply_button.isEnabled() and not session.preview.masks
            assert obj.ViewObject.RootNode.getNumChildren()==native_children
            assert obj.Shape.isSame(original) and doc.UndoCount==count
        session.slider.setValue(250)
        assert session.update_preview(),session.status.text()
        assert 0<session.preview_radius<session.slider_range
        # Return to the original shape is also a no-op when applied.
        session.original.click();assert session.update_preview()
        assert session.preview_radius==0
        session.apply_button.click();flush()
        assert c.round_session is None and c.tool is None
        assert obj.Shape.isSame(original) and doc.UndoCount==count
        assert not Gui.activeDocument().Modified
        assert obj.ViewObject.RootNode.getNumChildren()==native_children
        App.Console.PrintMessage('PASS: shaded radius preview, units, slider, invalid-radius recovery, zero original, no geometry/view-property/dirty/Undo changes\n')
        # Esc in the panel restores the original native pick paths and selection.
        session=start(('Edge1',));assert value(session,'2 mm')
        QtWidgets.QApplication.sendEvent(session.radius,QtGui.QKeyEvent(QtCore.QEvent.KeyPress,QtCore.Qt.Key_Escape,QtCore.Qt.NoModifier))
        flush()
        assert c.round_session is None
        assert any('Edge1' in item.SubElementNames for item in Gui.Selection.getSelectionEx())
        assert obj.ViewObject.RootNode.getNumChildren()==native_children and obj.Shape.isSame(original)
        Gui.Selection.clearSelection()
        hit=view.getObjectsInfo(tuple(round(v) for v in screen(view,V(20,0,10)))) or []
        assert any(item.get('Object')==obj.Name for item in hit),hit
        # Enter commits precisely the previewed value once.
        session=start();assert value(session,'0.2 cm')
        planned=session.planned[0][1]
        for kind in (QtCore.QEvent.ShortcutOverride,QtCore.QEvent.KeyPress,QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(session.radius,QtGui.QKeyEvent(kind,QtCore.Qt.Key_Return,QtCore.Qt.NoModifier))
        flush()
        assert c.tool is None and c.round_session is None
        assert obj.Shape.isValid() and len(obj.Shape.Faces)==26
        assert abs(obj.Shape.Volume-planned.Volume)<1e-6
        assert doc.UndoCount==count+1 and len(doc.Objects)==1 and obj.ViewObject.Visibility
        Gui.Selection.clearSelection();save('round-applied.png')
        doc.undo();flush();assert len(obj.Shape.Faces)==6
        doc.redo();flush();assert len(obj.Shape.Faces)==26
        App.Console.PrintMessage('PASS: Esc, original native picking and selection restored, Enter Apply, ordinary solid, one-step Undo/Redo\n')
        doc.undo();flush();original=obj.Shape
        # A radius session cannot survive edits or context changes.
        session=start(('Face6',));assert len(session.targets[0][2])==4
        c.start('Select');assert session.closed and c.round_session is None
        session=start();Gui.activateWorkbench('PartWorkbench')
        assert session.closed and not c.active
        Gui.activateWorkbench('SimpleCADWorkbench')
        session=start();other=App.newDocument('RoundOther');c.check_context()
        assert session.closed
        App.closeDocument(other.Name);App.setActiveDocument(doc.Name)
        op.transform([obj],V(1,0,0))
        session=start();doc.undo();c.check_context();assert session.closed
        doc.redo();obj=doc.getObject('SimpleShape');assert obj is not None
        assert obj.ViewObject.RootNode.getNumChildren()==native_children
        # Direct shape changes (not just Undo) also invalidate the snapshot.
        session=start();op.transform([obj],V(5,0,0));c.check_context();assert session.closed
        doc.undo();flush()
        # Closing the previewed document must release even its retained Coin nodes.
        closing=App.newDocument('RoundCloseTest')
        target=op.new_shape(closing,Part.makeCylinder(8,20),'Cylinder')
        Gui.Selection.clearSelection();Gui.Selection.addSelection(target)
        c.start('Round');closing_session=c.round_session
        assert closing_session and closing_session.planned, closing_session.status.text() if closing_session else 'not started'
        App.closeDocument(closing.Name);c.check_context()
        assert closing_session.closed and c.round_session is None
        App.setActiveDocument(doc.Name)
        App.Console.PrintMessage('PASS: face boundary selection, tool/workbench/document changes, Undo and moved-shape invalidation restore native drawing\n')
    c.cancel(quiet=True)
    return doc
