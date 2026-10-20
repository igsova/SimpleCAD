"""Native Union command, Qt selection/key focus, face browser, Undo and editing."""
import math
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import operations as ops
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
try:
    from PySide import QtTest
except ImportError:
    try:
        from PySide6 import QtTest
    except ImportError:
        from PySide2 import QtTest
V = App.Vector


def run(screenshots=False):
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument('UnionSmoke'); doc.UndoMode = 1
    a = ops.new_shape(doc, Part.makeBox(20, 20, 10), 'Rectangle')
    b = ops.new_shape(doc, Part.makeBox(20, 20, 10, V(10, 0, 0)), 'Polygon')
    a.ViewObject.ShapeColor = (.7, .8, .85)
    color = a.ViewObject.ShapeColor
    view = Gui.activeDocument().activeView(); view.viewTop(); view.fitAll()
    main = Gui.getMainWindow(); main.resize(1400, 900); main.activateWindow()
    mdi = main.findChild(QtWidgets.QMdiArea)
    for window in mdi.subWindowList():
        if window.windowTitle().startswith(doc.Label):
            mdi.setActiveSubWindow(window); window.showMaximized()

    def flush():
        for _ in range(3): QtWidgets.QApplication.processEvents(); Gui.updateGui()
        c.faces.refresh()

    def key(field=None):
        main.activateWindow()
        if field is None: c.focus_view()
        else: field.setFocus()
        flush()
        focus = QtWidgets.QApplication.focusWidget(); assert focus is not None
        QtTest.QTest.keyClick(focus, QtCore.Qt.Key_J); flush()

    def select_faces():
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(a, 'Face6'); Gui.Selection.addSelection(b, 'Face6'); flush()

    QtTest.QTest.qWait(500); flush()
    assert 'SimpleCAD_Union' in Gui.listCommands()
    assert not QtGui.QIcon(str(ROOT/'Resources/icons/union.svg')).pixmap(56, 56).isNull()
    browser = c.faces
    select_faces(); count = doc.UndoCount; second_name = b.Name
    key()
    assert len(doc.Objects) == 1 and a.Label == 'Union' and doc.UndoCount == count+1
    assert abs(a.Shape.Volume-6000) < 1e-6 and len(a.Shape.Faces) == 6
    assert a.ViewObject.ShapeColor == color
    assert Gui.Selection.getSelection() == [a]
    assert len(browser.records) == 1 and second_name not in browser.records
    item = browser.records[a.Name]['item']; item.setExpanded(True); browser.populate(a.Name)
    assert item.childCount() == 6
    doc.undo(); flush(); b = doc.getObject(second_name)
    assert len(doc.Objects) == 2 and a.Label == 'Rectangle' and b.Label == 'Polygon'
    assert len(browser.records) == 2
    doc.redo(); flush(); assert len(doc.Objects) == 1 and len(browser.records) == 1
    doc.undo(); flush(); b = doc.getObject(second_name)

    # Multiple face rows identify whole owners, just like viewport selections.
    browser.tabs.setCurrentIndex(0); select_faces(); key(browser.tree)
    assert len(doc.Objects) == 1 and abs(a.Shape.Volume-6000) < 1e-6
    doc.undo(); flush(); b = doc.getObject(second_name)

    # Typing J in an editor must not merge selected shapes.
    select_faces(); edit = QtWidgets.QLineEdit(main); edit.show(); key(edit)
    assert edit.text() == 'j' and len(doc.Objects) == 2
    edit.close(); edit.deleteLater(); flush()

    # Failure leaves geometry, selection and history untouched; retry succeeds.
    original_placement = App.Placement(b.Placement)
    b.Placement.Base = V(35, 0, 0); doc.recompute(); flush(); select_faces()
    before_keys = browser.selection_keys(); count = doc.UndoCount
    Gui.runCommand('SimpleCAD_Union'); flush()
    assert len(doc.Objects) == 2 and doc.UndoCount == count
    assert browser.selection_keys() == before_keys
    assert 'connected' in main.statusBar().currentMessage()
    b.Placement = original_placement; doc.recompute(); flush(); select_faces()
    Gui.runCommand('SimpleCAD_Union'); flush()
    assert len(doc.Objects) == 1 and len(a.Shape.Faces) == 6

    # The union's top is one pickable face and can be pulled immediately.
    Gui.Selection.clearSelection(); view.viewTop(); view.fitAll(); flush()
    pos = tuple(round(x) for x in screen(view, V(15, 10, 10)))
    hit = pick(view, doc, pos, face_only=True)
    assert hit and hit[0] == a and abs(hit[1].Area-600) < 1e-6
    c.start('PushPull'); c.click(pos); c.controls.value.setText('2'); c.numeric(); flush()
    assert a.Shape.isValid() and abs(a.Shape.Volume-7200) < 1e-6
    doc.undo(); flush()

    # Switching from an unfinished line clears its preview before the command.
    b = ops.new_shape(doc, Part.makeBox(10, 20, 10, V(25, 0, 0)), 'Extension')
    c.start('Line'); c.click(pos)
    Gui.Selection.clearSelection(); Gui.Selection.addSelection(a); Gui.Selection.addSelection(b)
    c.start('Union'); flush()
    assert c.tool is None and len(doc.Objects) == 1 and abs(a.Shape.Volume-7000) < 1e-6

    # Screenshot-like polygon, stem and intersecting box; retain real silhouette edges.
    points = [V(10*math.cos(i*math.pi/3), 10*math.sin(i*math.pi/3), 0) for i in range(6)]
    prism = Part.Face(Part.makePolygon(points+points[:1])).extrude(V(0, 0, 15))
    a.Shape = prism.fuse(Part.makeBox(4, 4, 30, V(-2, -2, -25))).removeSplitter()
    a.Label = 'Polygon with stem'
    b = ops.new_shape(doc, Part.makeBox(20, 15, 8, V(-10, -7.5, 10)), 'Rectangle')
    view.viewIsometric(); view.fitAll(); flush()
    if screenshots:
        Gui.Selection.clearSelection()
        view.saveImage(str(ROOT.parent.parent/'work/union-before.png'), 1100, 750, 'Current')
    Gui.Selection.addSelection(a); Gui.Selection.addSelection(b)
    Gui.runCommand('SimpleCAD_Union'); flush()
    assert len(doc.Objects) == 1 and a.Shape.isValid() and a.Shape.isClosed()
    assert len(a.Shape.Solids) == 1
    browser.records[a.Name]['item'].setExpanded(True); browser.populate(a.Name)
    Gui.Selection.clearSelection(); Gui.Selection.clearPreselection(); flush()
    if screenshots:
        view.fitAll(); flush()
        view.saveImage(str(ROOT.parent.parent/'work/union-after.png'), 1100, 750, 'Current')
        browser.tabs.parentWidget().grab().save(str(ROOT.parent.parent/'work/union-panel.png'))
    App.Console.PrintMessage('PASS: Union J/toolbar, owner selections, tree refresh, Undo/Redo, editor focus, rejected disjoint inputs, native picking and Push/Pull\n')
    return doc
