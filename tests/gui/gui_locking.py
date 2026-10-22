"""Click native padlocks without changing selection; exercise shared edit guard."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.document import operations as ops, locking, appearance, visibility
from simplecad.gui.controller import instance
from simplecad.gui.qt import QtCore, QtWidgets
try:
    from PySide import QtTest
except ImportError:
    from PySide6 import QtTest


def run():
    Gui.activateWorkbench('SimpleCADWorkbench')
    c=instance(); c.cancel(quiet=True)
    doc=App.newDocument('LockUI'); doc.UndoMode=1
    obj=ops.new_shape(doc,Part.makeBox(20,20,20),'Lock test')
    view=Gui.activeDocument().activeView(); view.viewIsometric(); view.fitAll()
    main=Gui.getMainWindow(); main.resize(1400,900)
    def flush():
        for _ in range(3): QtWidgets.QApplication.processEvents(); Gui.updateGui()
        c.faces.refresh()
    QtTest.QTest.qWait(600); flush()
    b=c.faces; b.tabs.setCurrentIndex(0)
    dock=b.tabs
    while dock and not isinstance(dock,QtWidgets.QDockWidget): dock=dock.parentWidget()
    dock.show(); dock.raise_(); main.activateWindow(); flush()
    def row(face=None):
        b.refresh(); parent=b.records[obj.Name]['item']; parent.setExpanded(True); b.populate(obj.Name)
        return parent if face is None else parent.child(face-1)
    def click_lock(item):
        b.tree.scrollToItem(item); flush()
        rect=b.tree.visualItemRect(item)
        point=QtCore.QPoint(b.tree.columnViewportPosition(3)+b.tree.columnWidth(3)//2,rect.center().y())
        assert b.tree.columnAt(point.x())==3
        QtTest.QTest.mouseClick(b.tree.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,point)
        flush()
    Gui.Selection.addSelection(obj,'Face2'); flush()
    selected=b.selection_keys()
    click_lock(row(1))
    assert locking.state(obj)==({1},False) and b.selection_keys()==selected, (locking.state(obj),b.selection_keys(),selected)
    assert row(1).toolTip(3)=='Unlock geometry'
    # A locked face remains selectable from the tree.
    b.tree.clearSelection(); row(1).setSelected(True); b.select(); flush()
    assert (doc.Name,obj.Name,'Face1') in b.selection_keys()
    click_lock(row())
    assert locking.whole(obj) and 'Unlock the object first' in row(1).toolTip(3)
    targets=appearance.prepare([(obj,['Face1'])])
    appearance.commit(targets,[1,0,0],57)
    b.toggle_eyes([(doc.Name,obj.Name,'Face1')]); assert visibility.hidden_faces(obj)=={1}
    b.toggle_eyes([(doc.Name,obj.Name,'Face1')]); assert not visibility.hidden_faces(obj)
    try: ops.transform([obj],App.Vector(10,0,0))
    except ValueError as error: assert 'locked' in str(error)
    else: raise AssertionError('Locked object moved')
    click_lock(row()); assert not locking.whole(obj) and locking.state(obj)[0]=={1}
    click_lock(row(1)); assert not locking.state(obj)[0]
    ops.transform([obj],App.Vector(10,0,0)); assert obj.Shape.BoundBox.XMin==10
    Gui.Selection.clearSelection(); App.closeDocument(doc.Name)
    return 'PASS: face/object padlock clicks, selection, inheritance, appearance, visibility and edit protection'
