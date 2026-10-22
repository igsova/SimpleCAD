"""Native Qt face-tree selection, existing tools, synchronization and lifecycle."""
import tempfile
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import operations as ops
from simplecad.gui.controller import instance
from simplecad.gui.face_browser import ROLE, alive
from simplecad.gui.qt import QtCore, QtWidgets
try:
    from PySide import QtTest
except ImportError:
    try:
        from PySide6 import QtTest
    except ImportError:
        from PySide2 import QtTest


def run(screenshots=False):
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument('FaceBrowserSmoke'); doc.UndoMode = 1
    host = ops.new_shape(doc, Part.makeBox(40, 30, 20), 'Triangle')
    cylinder = ops.new_shape(doc, Part.makeCylinder(5, 20, App.Vector(55, 0, 0)), 'Cylinder')
    line = ops.new_shape(doc, Part.makeLine(App.Vector(0, 50, 0), App.Vector(20, 50, 0)), 'Line')
    view = Gui.activeDocument().activeView(); view.viewIsometric(); view.fitAll()
    main = Gui.getMainWindow(); main.resize(1400, 900); main.activateWindow()

    def flush():
        for _ in range(3): QtWidgets.QApplication.processEvents(); Gui.updateGui()
        c.faces.refresh()

    QtTest.QTest.qWait(600); flush()
    b = c.faces
    if not alive(b.tree) or b.tabs is None:
        widgets=[(w.metaObject().className(), w.objectName(), w.parentWidget().metaObject().className() if w.parentWidget() else '') for w in main.findChildren(QtWidgets.QWidget) if isinstance(w, (QtWidgets.QTreeWidget,QtWidgets.QTabWidget)) or 'TreePanel' in w.metaObject().className()]
        raise AssertionError(str((b.running, b.tree,b.tabs,b.native,widgets)))
    dock = b.tabs
    while dock and not isinstance(dock, QtWidgets.QDockWidget): dock = dock.parentWidget()
    assert dock is not None
    dock.show(); dock.raise_(); b.tabs.setCurrentIndex(0); flush()

    def row(obj, face=None):
        b.refresh()
        parent = b.records[obj.Name]['item']
        if face is None: return parent
        parent.setExpanded(True); b.populate(obj.Name)
        return parent.child(face - 1)

    def click(item, modifiers=QtCore.Qt.NoModifier):
        b.tree.scrollToItem(item); main.activateWindow(); b.tree.setFocus(); flush()
        rect = b.tree.visualItemRect(item)
        assert rect.isValid() and not rect.isEmpty()
        QtTest.QTest.mouseClick(b.tree.viewport(), QtCore.Qt.LeftButton, modifiers, rect.center())
        flush()

    def key(code, modifiers=QtCore.Qt.NoModifier):
        main.activateWindow(); b.tree.setFocus(); flush()
        QtTest.QTest.keyClick(b.tree, code, modifiers); flush()

    def keys(): return b.selection_keys()
    def expected(obj, *names): return {(doc.Name, obj.Name, name) for name in names}

    # Browsing doesn't create objects, touch saved geometry or add Undo history.
    with tempfile.TemporaryDirectory() as folder:
        path = str(Path(folder) / 'Browser.FCStd')
        host_name, cylinder_name, line_name = host.Name, cylinder.Name, line.Name
        doc.saveAs(path); App.closeDocument(doc.Name)
        doc = App.openDocument(path); doc.UndoMode = 1
        host, cylinder, line = (doc.getObject(name) for name in (host_name, cylinder_name, line_name))
        view = Gui.activeDocument().activeView(); view.viewIsometric(); view.fitAll(); flush()
        assert not Gui.activeDocument().Modified, 'Baseline reopened model already modified'
        original = host.Shape; count = doc.UndoCount; objects = len(doc.Objects)
        assert b.root.childCount() == 3 and line.Name in b.records
        assert row(line).childCount() == 0  # Edge-only objects now have an eye too.
        assert row(host).childCount() == 0
        row(host).setExpanded(True); assert row(host).childCount() == 6
        click(row(host, 2)); assert keys() == expected(host, 'Face2')
        assert b.selected_face()[0] == host
        click(row(host, 4), QtCore.Qt.ControlModifier)
        assert keys() == expected(host, 'Face2', 'Face4')
        assert b.selected_face() is None
        click(row(host, 1)); click(row(host, 3), QtCore.Qt.ShiftModifier)
        assert keys() == expected(host, 'Face1', 'Face2', 'Face3')
        click(row(host)); assert keys() == expected(host, '')
        assert all(not row(host, i).isSelected() for i in range(1, 7))
        click(row(cylinder, 1)); assert keys() == expected(cylinder, 'Face1')
        b.hover(row(cylinder, 1))  # Geometry details are populated on demand.
        assert 'Cylinder' in row(cylinder, 1).toolTip(0)
        assert 'Area:' in row(cylinder, 1).toolTip(0)
        b.hover(row(host, 5)); pre = Gui.Selection.getPreselection()
        assert pre.ObjectName == host.Name and pre.SubElementNames == ('Face5',)
        b.clear_hover(); assert not Gui.Selection.getPreselection().ObjectName
        assert host.Shape.isSame(original) and doc.UndoCount == count and len(doc.Objects) == objects
        assert not Gui.activeDocument().Modified

        # 3D/native selection updates face rows; normal Objects tree remains intact.
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(host, 'Face6'); flush()
        assert row(host, 6).isSelected() and not row(host).isSelected()
        assert b.selected_face() is None  # Doesn't alter viewport-only Push/Pull.
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(host); flush()
        assert row(host).isSelected()
        b.tabs.setCurrentIndex(1); flush()
        assert b.native.isVisible() and b.native.metaObject().className() == 'Gui::TreeWidget'
        b.tabs.setCurrentIndex(0); flush()
        assert doc.UndoCount == count and not Gui.activeDocument().Modified

        # Pull a face from the list, including a face on the back of the block.
        click(row(host, 1)); key(QtCore.Qt.Key_P)
        assert c.tool == 'PushPull' and c.anchor is not None and c.obj == host, str((c.tool,c.anchor,b.chosen,keys(),main.statusBar().currentMessage(),QtWidgets.QApplication.focusWidget()))
        assert (c.face.CenterOfMass - original.Faces[0].CenterOfMass).Length < 1e-7
        c.controls.value.setText('2'); c.numeric(); flush()
        assert abs(host.Shape.Volume - (original.Volume + original.Faces[0].Area * 2)) < 1e-5
        doc.undo(); flush(); assert abs(host.Shape.Volume - original.Volume) < 1e-6
        click(row(host, 2)); Gui.runCommand('SimpleCAD_PushPull'); assert c.anchor is not None
        c.cancel(quiet=True)

        # Delete is face-only when the tree has focus, and one Undo restores it.
        click(row(host, 3)); key(QtCore.Qt.Key_Backspace)
        assert len(doc.Objects) == objects and len(host.Shape.Faces) == 5 and not host.Shape.Solids
        assert row(host).childCount() == 5
        doc.undo(); flush()
        assert len(host.Shape.Faces) == 6 and row(host).childCount() == 6, str((len(host.Shape.Faces),row(host).childCount(),doc.UndoCount,doc.RedoCount,c.tool,main.statusBar().currentMessage()))
        doc.redo(); flush(); assert row(host).childCount() == 5
        doc.undo(); flush()

        click(row(host, 6)); key(QtCore.Qt.Key_D)
        assert c.subdivide_session is not None
        c.cancel(quiet=True); flush()
        # Use native operation to exercise row refresh after a face-count change.
        target = ops.prepare_subdivision([(host, ('Face6',))])
        # The same validated partition path used by the dialog.
        planned, regions = ops.preview_subdivision(target, 2, 2, pattern='spaced')
        ops.commit_subdivision(target, planned, 2, 2, len(regions))
        flush(); assert row(host).childCount() == len(host.Shape.Faces)
        assert len(host.Shape.Faces) > 6 and not any(k[2].startswith('Face') for k in keys()), str((len(host.Shape.Faces), keys()))
        doc.undo(); flush(); assert row(host).childCount() == 6

        # A queued stale row cannot select a renumbered face after an edit.
        stale = tuple(row(host, 2).data(0, ROLE))
        host.Shape = Part.makeBox(20, 20, 20)
        assert b.resolve(stale) is None
        flush(); assert row(host).childCount() == 6
        host.Shape = original; doc.recompute(); flush()
        host.Label = 'Expanded structure'; flush(); assert row(host).text(0) == host.Label
        host.ViewObject.Visibility = False; flush()
        assert 'hidden' in row(host).toolTip(0)
        b.hover(row(host, 1)); assert b.hovered is None
        host.ViewObject.Visibility = True

        # Selection of a face cancels a stale drawing anchor safely.
        c.start('Line'); click(row(host, 4)); assert c.tool is None
        click(row(host, 4)); click(row(cylinder, 2), QtCore.Qt.ControlModifier)
        assert keys() == expected(host, 'Face4') | expected(cylinder, 'Face2')
        Gui.Selection.clearSelection(); flush(); assert not b.tree.selectedItems()

        # Object creation/deletion and document changes rebuild without stale refs.
        extra = ops.new_shape(doc, Part.makePlane(5, 5), 'Extra'); flush()
        assert extra.Name in b.records
        extra_name = extra.Name
        click(row(extra)); key(QtCore.Qt.Key_Delete); assert doc.getObject(extra_name) is None
        flush(); assert extra_name not in b.records
        doc.undo(); flush(); assert extra_name in b.records
        other = App.newDocument('FaceBrowserOther'); flush()
        assert b.doc_name == other.Name and b.root.childCount() == 0
        App.closeDocument(other.Name); App.setActiveDocument(doc.Name); flush()
        assert b.doc_name == doc.Name and host.Name in b.records
        click(row(host, 6))
        if screenshots:
            b.tabs.parentWidget().grab().save(str(ROOT.parent.parent / 'work/face-browser-panel.png'))
            view.saveImage(str(ROOT.parent.parent / 'work/face-browser-model.png'), 1100, 750, 'Current')

        # Repeated activation restores the same native widget, without row objects.
        native = b.native; parent = b.tabs.parentWidget()
        before = [(obj.Name, obj.TypeId) for obj in doc.Objects]
        for _ in range(3):
            Gui.activateWorkbench('PartWorkbench')
            assert not b.running and b.tree is None and alive(native)
            assert native.parentWidget() == parent
            Gui.activateWorkbench('SimpleCADWorkbench'); flush()
            assert b.running and b.native == native and b.tabs.count() == 2
            assert [(obj.Name, obj.TypeId) for obj in doc.Objects] == before
        doc.save(); restored_path = doc.FileName; App.closeDocument(doc.Name); flush()
        assert b.doc_name != 'FaceBrowserSmoke'
        doc = App.openDocument(restored_path); flush()
        assert b.doc_name == doc.Name and 'Expanded structure' in [r['item'].text(0) for r in b.records.values()]
        assert all(obj.TypeId == 'Part::Feature' and not hasattr(obj, 'Proxy') for obj in doc.Objects)
    App.Console.PrintMessage('PASS: face browser, native selection, tools, Undo, synchronization, save/reopen and lifecycle\n')
    return doc
