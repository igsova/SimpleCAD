"""Real viewport Qt events: directional boxes, native clicks and cleanup."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.tools.selection import DragSelection
from simplecad.gui.snapping import screen
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
V=App.Vector

def run(screenshots=False):
    Gui.activateWorkbench('SimpleCADWorkbench')
    c=instance();c.start('Select')
    doc=App.newDocument('SimpleCADBoxSelectionSmoke');doc.UndoMode=1
    obj=op.new_shape(doc,Part.makeCompound([Part.makePlane(10,10),Part.makePlane(20,10,V(10,0,0))]),'Joined faces')
    view=Gui.activeDocument().activeView();view.viewTop();view.fitAll()
    mdi=Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    sub=[s for s in mdi.subWindowList() if s.widget().metaObject().className()=='Gui::View3DInventor'][-1]
    mdi.setActiveSubWindow(sub);sub.showMaximized()
    Gui.updateGui()
    widget=[w for w in sub.findChildren(QtWidgets.QWidget) if DragSelection.is_viewport(w)][0]
    widget.setFocus()
    def process():
        QtWidgets.QApplication.processEvents();Gui.updateGui()
    process();view.fitAll();process()
    def point(x,y,z=0):
        px,py=screen(view,V(x,y,z));width,height=view.getSize()
        return QtCore.QPointF(px*widget.width()/width,widget.height()-py*widget.height()/height)
    def send(kind,p,button=QtCore.Qt.NoButton,buttons=QtCore.Qt.NoButton,mods=QtCore.Qt.NoModifier):
        event=QtGui.QMouseEvent(kind,p,QtCore.QPointF(widget.mapToGlobal(p.toPoint())),button,buttons,mods)
        QtWidgets.QApplication.sendEvent(widget,event)
        process()
    def press(p,mods=QtCore.Qt.NoModifier):send(QtCore.QEvent.MouseButtonPress,p,QtCore.Qt.LeftButton,QtCore.Qt.LeftButton,mods)
    def move(p,mods=QtCore.Qt.NoModifier):send(QtCore.QEvent.MouseMove,p,buttons=QtCore.Qt.LeftButton,mods=mods)
    def release(p,mods=QtCore.Qt.NoModifier):send(QtCore.QEvent.MouseButtonRelease,p,QtCore.Qt.LeftButton,mods=mods)
    def names():return {name for item in Gui.Selection.getSelectionEx() if item.Object==obj for name in item.SubElementNames}
    def drag(a,b,mods=QtCore.Qt.NoModifier):
        press(a,mods);move(b,mods)
        assert c.selection.overlay is not None
        release(b,mods)
        assert c.selection.widget is None and c.selection.overlay is None
    count=doc.UndoCount
    a,b=point(-1,11),point(11,-1)
    press(a);move(b)
    assert not c.selection.overlay.crossing
    assert not Gui.Selection.getSelection()
    if screenshots:view.saveImage(str(ROOT.parent.parent/'work'/'selection-window.png'),*view.getSize(),'Current')
    release(b)
    assert 'Face1' in names() and 'Face2' not in names(),names()
    if screenshots:view.saveImage(str(ROOT.parent.parent/'work'/'selection-window-result.png'),*view.getSize(),'Current')
    first=names()
    Gui.Selection.clearSelection()
    press(b);move(a)
    assert c.selection.overlay.crossing
    if screenshots:view.saveImage(str(ROOT.parent.parent/'work'/'selection-crossing.png'),*view.getSize(),'Current')
    release(a)
    assert {'Face1','Face2'} <= names() and first <= names(),names()
    if screenshots:view.saveImage(str(ROOT.parent.parent/'work'/'selection-crossing-result.png'),*view.getSize(),'Current')
    assert doc.UndoCount==count
    App.Console.PrintMessage('PASS: Qt drag/release window vs crossing, Retina scaling, native subelement highlights, overlay styles, no document edits\n')
    # Small clicks replay the complete native press/release pair.
    Gui.Selection.clearSelection()
    press(point(5,5));release(point(5,5))
    assert names()=={'Face1'},names()
    press(point(25,5),QtCore.Qt.ControlModifier);release(point(25,5),QtCore.Qt.ControlModifier)
    assert {'Face1','Face2'} <= names(),names()
    press(point(-1,-1));release(point(-1,-1));assert not names()
    drag(a,b)
    before=names()
    press(b);move(a)
    QtWidgets.QApplication.sendEvent(widget,QtGui.QKeyEvent(QtCore.QEvent.KeyPress,QtCore.Qt.Key_Escape,QtCore.Qt.NoModifier))
    release(a)
    assert names()==before and c.selection.overlay is None
    drag(point(9,11),point(31,-1),QtCore.Qt.ShiftModifier)
    assert {'Face1','Face2'} <= names()
    drag(a,b,QtCore.Qt.ControlModifier)
    assert 'Face1' not in names() and 'Face2' in names(),names()
    Gui.Selection.clearSelection();Gui.Selection.addSelection(obj)
    drag(a,b,QtCore.Qt.ControlModifier)
    assert 'Face1' not in names() and 'Face2' in names(),names()
    press(point(5,5));move(point(31,-1))
    assert not c.selection.overlay.crossing
    move(point(-1,11));assert c.selection.overlay.crossing
    release(point(-1,11))
    assert 'Face1' in names() and 'Face2' not in names(),names()
    App.Console.PrintMessage('PASS: ordinary clicks, Ctrl multi-select, empty click, Esc preserves selection, Shift adds, Ctrl toggles\n')
    # Selecting faces/edges feeds the existing Delete transaction.
    Gui.Selection.clearSelection();drag(point(-1,11),point(31,-1))
    obj_name=obj.Name
    c.start('Delete');assert not doc.getObject(obj_name)
    assert doc.UndoCount==count+1
    doc.undo();obj=doc.getObject(obj_name)
    Gui.Selection.clearSelection()
    # Escape/tool change/workbench switch cannot leave a rubber band behind.
    press(a);move(b);c.start('Line')
    assert c.selection.overlay is None and c.tool=='Line'
    release(b);c.cancel(quiet=True)
    press(a);move(b);Gui.activateWorkbench('PartWorkbench')
    assert c.selection.overlay is None and not c.active
    release(b);Gui.activateWorkbench('SimpleCADWorkbench')
    assert c.active
    press(a);move(b)
    other=App.newDocument('SelectionOther');c.selection.check_context()
    assert c.selection.overlay is None
    App.closeDocument(other.Name);App.setActiveDocument(doc.Name)
    Gui.Selection.clearSelection()
    mdi.setActiveSubWindow(sub)
    press(a);move(b)
    doc.undo();c.selection.check_context()
    assert c.selection.overlay is None
    doc.redo();obj=doc.getObject(obj_name)
    release(b)
    # Both native orbit button orders yield to the navigation style.
    for left_first in (False, True):
        p=point(5,5)
        if left_first:
            press(p)
            send(QtCore.QEvent.MouseButtonPress,p,QtCore.Qt.MiddleButton,QtCore.Qt.LeftButton|QtCore.Qt.MiddleButton)
        else:
            send(QtCore.QEvent.MouseButtonPress,p,QtCore.Qt.MiddleButton,QtCore.Qt.MiddleButton)
            send(QtCore.QEvent.MouseButtonPress,p,QtCore.Qt.LeftButton,QtCore.Qt.LeftButton|QtCore.Qt.MiddleButton)
        assert c.selection.widget is None and c.selection.overlay is None
        send(QtCore.QEvent.MouseButtonRelease,p,QtCore.Qt.LeftButton,QtCore.Qt.MiddleButton)
        send(QtCore.QEvent.MouseButtonRelease,p,QtCore.Qt.MiddleButton)
    App.Console.PrintMessage('PASS: selection Delete and Undo, tool/workbench/document changes clean up the drag\n')
    view.setCameraType('Perspective');view.viewIsometric();view.fitAll();process()
    width,height=view.getSize()
    drag(QtCore.QPointF(1,1),QtCore.QPointF(widget.width()-1,widget.height()-1))
    assert {'Face1','Face2'} <= names(),names()
    assert doc.UndoCount==count
    App.Console.PrintMessage('PASS: perspective box selection and unchanged Undo history\n')
    c.cancel(quiet=True)
    return doc
