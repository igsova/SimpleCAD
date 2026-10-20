"""Eye controls, native rendering/picking, saved state and editing lifecycle."""
import tempfile
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
import Part
import MeshPart
from simplecad import ROOT
from simplecad.document import visibility as vis, operations as ops
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, Snapper, pick
from simplecad.gui.box_selection import box_selection
from simplecad.gui.tools.selection import DragSelection
from simplecad.gui.qt import QtCore, QtWidgets
try:
    from PySide import QtTest
except ImportError:
    try: from PySide6 import QtTest
    except ImportError: from PySide2 import QtTest
V = App.Vector


def run(screenshots=False):
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument('VisibilitySmoke'); doc.UndoMode = 1
    obj = ops.new_shape(doc, Part.makeBox(30, 20, 15), 'Block')
    cylinder = ops.new_shape(doc, Part.makeCylinder(4, 15, V(40, 10, 0)), 'Cylinder')
    line = ops.new_shape(doc, Part.makeLine(V(0, 30, 0), V(20, 30, 0)), 'Line')
    view = Gui.activeDocument().activeView(); view.viewTop(); view.fitAll()
    main = Gui.getMainWindow(); main.resize(1400, 950); main.activateWindow()
    mdi = main.findChild(QtWidgets.QMdiArea)
    for window in mdi.subWindowList():
        if window.windowTitle().startswith(doc.Label):
            mdi.setActiveSubWindow(window); window.showMaximized()

    def flush():
        for _ in range(3): QtWidgets.QApplication.processEvents(); Gui.updateGui()
        c.seams.refresh(); c.faces.refresh()

    QtTest.QTest.qWait(500); flush()
    b = c.faces
    dock = b.tabs
    while dock and not isinstance(dock, QtWidgets.QDockWidget): dock = dock.parentWidget()
    dock.show(); dock.raise_(); b.tabs.setCurrentIndex(0); flush()

    def row(target, index=None):
        b.refresh(); item = b.records[target.Name]['item']
        if index is None: return item
        item.setExpanded(True); b.populate(target.Name)
        return item.child(index-1)

    def eye(target, index=None):
        item = row(target, index)
        b.tree.scrollToItem(item); main.activateWindow(); b.tree.setFocus(); flush()
        rect = b.tree.visualItemRect(item)
        pos = QtCore.QPoint(b.tree.columnViewportPosition(1)+17, rect.center().y())
        assert rect.isValid() and not rect.isEmpty()
        QtTest.QTest.mouseClick(b.tree.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, pos)
        flush()

    def hits(point):
        flush()
        pos = tuple(round(x) for x in screen(view, point))
        return [h['Component'] for h in view.getObjectsInfo(pos) or [] if h.get('Object') == obj.Name]

    def viewport_click(point):
        sub = [s for s in mdi.subWindowList() if s.widget().metaObject().className() == 'Gui::View3DInventor'][-1]
        mdi.setActiveSubWindow(sub); sub.showMaximized(); flush()
        widget = next(w for w in sub.findChildren(QtWidgets.QWidget) if DragSelection.is_viewport(w))
        px, py = screen(view, point); width, height = view.getSize()
        pos = QtCore.QPoint(round(px*widget.width()/width), round(widget.height()-py*widget.height()/height))
        QtTest.QTest.mouseClick(widget, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, pos); flush()

    original = obj.Shape; count = doc.UndoCount; object_count = len(doc.Objects)
    assert line.Name in b.records and row(line).childCount() == 0
    Gui.Selection.clearSelection(); Gui.Selection.addSelection(cylinder); flush()
    eye(obj, 6)
    assert vis.hidden_faces(obj) == {6}
    assert Gui.Selection.getSelection() == [cylinder], 'Eye must not select its row'
    assert obj.ViewObject.Visibility and obj.Shape.isSame(original)
    assert len(doc.Objects) == object_count and doc.UndoCount == count+1
    assert 'Face6' not in hits(V(15, 10, 15)) and 'Face5' in hits(V(15, 10, 15))
    viewport_click(V(15, 10, 15))
    assert b.selection_keys() == {(doc.Name, obj.Name, 'Face5')}
    assert row(obj, 6).data(1, QtCore.Qt.AccessibleTextRole) == 'Face hidden'
    doc.undo(); flush(); assert not vis.hidden_faces(obj)
    assert 'Face6' in hits(V(15, 10, 15))
    doc.redo(); flush(); assert vis.hidden_faces(obj) == {6}

    # Object eye restores its own visibility while remembering hidden faces.
    eye(obj); assert not obj.ViewObject.Visibility and vis.hidden_faces(obj) == {6}
    assert not hits(V(15, 10, 15))
    eye(obj); assert obj.ViewObject.Visibility and vis.hidden_faces(obj) == {6}
    eye(obj); eye(obj, 6)
    assert obj.ViewObject.Visibility and not vis.hidden_faces(obj)
    eye(obj, 6)
    snapper = Snapper(doc, view)
    assert not any(label == 'Face center' and (point-V(15, 10, 15)).Length < 1e-6 for point, label in snapper.points)
    assert (obj, 'Face6') not in box_selection(doc, view, (0, 0), view.getSize())
    Gui.Selection.clearSelection(); Gui.Selection.addSelection(obj); flush()
    assert 'Face6' not in hits(V(15, 10, 15)), 'Whole-object highlight must not restore the hidden face'
    Gui.Selection.clearSelection()

    # Native Space toggles the chosen rows, without deleting geometry.
    b.tree.clearSelection(); row(line).setSelected(True); b.tree.setFocus(); flush()
    QtTest.QTest.keyClick(b.tree, QtCore.Qt.Key_Space); flush()
    assert not line.ViewObject.Visibility and line.Shape.Length == 20
    eye(line); assert line.ViewObject.Visibility

    # Display regeneration and workbench switches retain hidden faces.
    for mode in ('Wireframe', 'Flat Lines', 'Flat Lines'):
        obj.ViewObject.DisplayMode = mode
        obj.ViewObject.Deviation = .2 if obj.ViewObject.Deviation != .2 else .3
        flush(); assert vis.hidden_faces(obj) == {6}
    assert 'Face6' not in hits(V(15, 10, 15))
    Gui.activateWorkbench('PartWorkbench'); flush()
    assert 'Face6' not in hits(V(15, 10, 15))
    Gui.activateWorkbench('SimpleCADWorkbench'); flush(); b = c.faces
    assert vis.hidden_faces(obj) == {6}

    # Save/reopen metadata, then Move and rotate without changing face choices.
    with tempfile.TemporaryDirectory() as folder:
        path = str(Path(folder)/'Visibility.FCStd'); name = obj.Name
        doc.saveAs(path); App.closeDocument(doc.Name)
        doc = App.openDocument(path); obj = doc.getObject(name)
        view = Gui.activeDocument().activeView(); view.viewTop(); view.fitAll(); flush()
        assert vis.hidden_faces(obj) == {6}
        assert 'Face6' not in hits(V(15, 10, 15))
        before_volume = obj.Shape.Volume
        ops.transform([obj], V(2, 3, 0)); flush(); assert vis.hidden_faces(obj) == {6}
        obj.Placement.Rotation = App.Rotation(V(0, 0, 1), 25); doc.recompute(); flush()
        assert vis.hidden_faces(obj) == {6}
        assert obj.Shape.Volume == before_volume
        # Hiding is display only: STL still includes the closed complete solid.
        mesh = MeshPart.meshFromShape(Shape=obj.Shape, LinearDeflection=.1, AngularDeflection=.3, Relative=False)
        assert mesh.isSolid() and abs(mesh.Volume-before_volume) < 1e-5
        # New topology never applies an old FaceN mask to the wrong face.
        with ops.transaction(doc, 'Change shape'):
            obj.Shape = Part.makeCylinder(5, 15)
        flush(); assert not vis.hidden_faces(obj)
        doc.undo(); flush(); assert vis.hidden_faces(obj) == {6}

    # A hidden isolated surface has no leftover clickable edges or vertices.
    patches = ops.new_shape(doc, Part.makeCompound([Part.makePlane(10, 10, V(60, 0, 0)), Part.makePlane(10, 10, V(80, 0, 0))]), 'Two surfaces')
    view.viewTop(); view.fitAll(); flush()
    eye(patches, 1)
    assert vis.hidden_faces(patches) == {1}
    for point in (V(65, 5, 0), V(60, 0, 0), V(65, 0, 0)):
        pos = tuple(round(x) for x in screen(view, point))
        hit = pick(view, doc, pos)
        assert hit is None or hit[0] != patches
        viewport_click(point)
        assert patches not in Gui.Selection.getSelection()
    pos = tuple(round(x) for x in screen(view, V(80, 0, 0)))
    assert any(h.get('Object') == patches.Name and h.get('Component', '').startswith('Vertex') for h in view.getObjectsInfo(pos) or [])
    edge = next((i, e) for i, e in enumerate(patches.Shape.Edges, 1) if abs(e.CenterOfMass.x-85) < 1e-6 and abs(e.CenterOfMass.y) < 1e-6)
    pos = tuple(round(x) for x in screen(view, edge[1].CenterOfMass))
    assert any(h.get('Object') == patches.Name and h.get('Component') == 'Edge%d' % edge[0] for h in view.getObjectsInfo(pos) or []), 'Visible EdgeN must not be renumbered'
    viewport_click(edge[1].CenterOfMass)
    assert b.selection_keys() == {(doc.Name, patches.Name, 'Edge%d' % edge[0])}, b.selection_keys()
    patches.ViewObject.DisplayMode = 'Wireframe'; flush()
    eye(patches, 2)
    assert patches.ViewObject.Visibility and vis.hidden_faces(patches) == {1, 2}
    eye(patches, 1); assert vis.hidden_faces(patches) == {2}
    eye(patches, 2); assert not vis.hidden_faces(patches)
    patches.ViewObject.DisplayMode = 'Flat Lines'; flush()
    assert pick(view, doc, tuple(round(x) for x in screen(view, V(65, 5, 0))), face_only=True)[3] == 'Face1'

    # Curved face + seam hiding, complete object hide, selected-face masks.
    cyl = next(o for o in doc.Objects if o.Label == 'Cylinder')
    eye(cyl, 1); assert vis.hidden_faces(cyl) == {1}
    c.seams.configure(True); flush(); assert vis.hidden_faces(cyl) == {1}
    c.seams.configure(False); flush(); eye(cyl, 1)
    for index in range(1, 7):
        if index not in vis.hidden_faces(obj): eye(obj, index)
    assert vis.hidden_faces(obj) == set(range(1, 7))
    eye(obj, 1); assert vis.hidden_faces(obj) == set(range(2, 7))
    for index in range(2, 7): eye(obj, index)
    eye(obj, 6)
    view.viewIsometric(); view.fitAll(); flush()
    if screenshots:
        row(obj).setExpanded(True); b.populate(obj.Name)
        b.tabs.parentWidget().grab().save(str(ROOT.parent.parent/'work/visibility-panel.png'))
        view.saveImage(str(ROOT.parent.parent/'work/visibility-model.png'), 1100, 750, 'Current')
    assert obj.Shape.isValid() and obj.Shape.isClosed()
    App.Console.PrintMessage('PASS: eyes, Space, native face/edge/vertex picking, object/face independence, snap/box filters, Undo/Redo, save/reopen, transformations, topology changes, STL and workbench/display changes\n')
    return doc
