"""Real FreeCAD rendering/picking, persistent dialog, Undo, and reopened models."""
from pathlib import Path
import tempfile

import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.core import preferences as prefs, geometry as g
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.display import edge_nodes
from simplecad.gui.snapping import screen
from simplecad.gui.settings_dialog import SettingsDialog
from simplecad.gui.qt import QtCore, QtWidgets

V = App.Vector


def run(screenshot=None):
    previous = prefs.load()
    prefs.save(prefs.Settings())
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.seams.configure(False)
    doc = App.newDocument("SimpleCADSettingsSmoke")
    doc.UndoMode = 1
    try:
        obj = op.new_shape(doc, Part.makeCylinder(8, 25), "Cylinder")
        view = Gui.activeDocument().activeView()
        view.getCameraNode().orientation.setValue(
            App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), "ZXY").Q)
        view.fitAll()
        Gui.updateGui()

        def flush():
            # Run queued document observers and Coin field sensors as the GUI does.
            for _ in range(3):
                QtWidgets.QApplication.processEvents()
                Gui.updateGui()

        def sections(node):
            parts = []; section = []
            for value in node.coordIndex.getValues():
                if value < 0:
                    parts.append(section); section = []
                else:
                    section.append(value)
            assert not section
            return parts

        def assert_hidden(target):
            flush()
            seams = {i for i, edge in enumerate(target.Shape.Edges) if g.is_seam_edge(target.Shape, edge)}
            assert seams
            for node in edge_nodes(target.ViewObject.RootNode):
                parts = sections(node)
                assert len(parts) == len(target.Shape.Edges)
                for i, part in enumerate(parts):
                    if i in seams:
                        assert len(set(part)) == 1, (i, part)
                    else:
                        assert len(set(part)) > 1, (i, part)

        def seam_hit(expected):
            seam = next("Edge" + str(i + 1) for i, edge in enumerate(obj.Shape.Edges)
                        if g.is_seam_edge(obj.Shape, edge))
            midpoint = obj.Shape.getElement(seam).CenterOfMass
            pos = tuple(round(value) for value in screen(view, midpoint))
            hits = view.getObjectsInfo(pos) or []
            assert any(h.get("Object") == obj.Name and h.get("Component") == seam for h in hits) == expected, hits
            return seam

        assert_hidden(obj)
        seam = seam_hit(False)
        for i, edge in enumerate(obj.Shape.Edges):
            if g.is_seam_edge(obj.Shape, edge):
                continue
            p = edge.valueAt(edge.getParameterByLength(edge.Length / 2))
            hits = view.getObjectsInfo(tuple(round(value) for value in screen(view, p))) or []
            assert any(h.get("Object") == obj.Name and h.get("Component") == "Edge" + str(i + 1) for h in hits), hits
        count, volume = doc.UndoCount, obj.Shape.Volume
        if screenshot:
            view.saveImage(str(screenshot), 1000, 750, "Current")
        App.Console.PrintMessage("PASS: seam hidden by default, no native seam hover/pick, circular rim EdgeN picks preserved\n")

        errors = []
        def dialog_edit(action, custom=None, take_picture=False):
            def edit():
                try:
                    dialog = QtWidgets.QApplication.activeModalWidget()
                    assert isinstance(dialog, SettingsDialog), dialog
                    if take_picture:
                        dialog.grab().save(str(ROOT.parent.parent / "work" / "simplecad-settings.png"))
                    if custom is not None:
                        dialog.set_values(custom)
                        button = dialog.findChild(QtWidgets.QPushButton, "SimpleCADFaceColor")
                        assert button.text() == custom.face_color and button.isEnabled(), button.text()
                    if action == "defaults":
                        buttons = dialog.findChild(QtWidgets.QDialogButtonBox)
                        buttons.button(QtWidgets.QDialogButtonBox.RestoreDefaults).click()
                        assert dialog.values() == prefs.Settings()
                        dialog.accept()
                    elif action == "cancel":
                        dialog.reject()
                    else:
                        dialog.accept()
                except BaseException as error:
                    errors.append(error)
                    widget = QtWidgets.QApplication.activeModalWidget()
                    if widget:
                        widget.reject()
            QtCore.QTimer.singleShot(80, edit)
            Gui.runCommand("SimpleCAD_Settings", 0)
            assert not errors, errors
            flush()

        custom = prefs.Settings(show_seams=True, face_color="#FFD27F", endpoints=False, centers=False, axes=False,
                                midpoint_radius=50)
        dialog_edit("cancel", custom, take_picture=True)
        assert prefs.load() == prefs.Settings()
        seam_hit(False)
        dialog_edit("ok", custom)
        assert prefs.load() == custom
        seam_hit(True)
        Gui.Selection.addSelection(obj, seam)
        c.start("Delete")
        assert obj.Shape.Volume == volume and doc.UndoCount == count
        c.start("Line")
        assert c.snapper.settings == custom
        assert {label for _, label in c.snapper.points} == {"Midpoint"}
        c.cancel(quiet=True)
        # Hiding also removes a previously selected seam's cached overlay.
        Gui.Selection.addSelection(obj, seam)
        dialog_edit("defaults")
        assert prefs.load() == prefs.Settings()
        assert_hidden(obj)
        seam_hit(False)
        assert doc.UndoCount == count and obj.Shape.Volume == volume
        App.Console.PrintMessage("PASS: settings menu, Cancel, saved options, larger midpoint radius, next Line session, Restore defaults, visible seam deletion protection; no Undo edits\n")

        # Native renderer regeneration (including changed tessellation).
        obj.ViewObject.Deviation = 0.12
        obj.ViewObject.DisplayMode = "Wireframe"
        assert_hidden(obj)
        seam_hit(False)
        obj.ViewObject.DisplayMode = "Flat Lines"
        with op.transaction(doc, "Resize cylinder"):
            obj.Shape = Part.makeCylinder(9, 30)
        assert_hidden(obj)
        doc.undo(); assert_hidden(obj)
        doc.redo(); assert_hidden(obj)
        with op.transaction(doc, "Replace by box"):
            obj.Shape = Part.makeBox(10, 12, 15)
        flush()
        assert all(len(set(part)) > 1 for node in edge_nodes(obj.ViewObject.RootNode) for part in sections(node))
        doc.undo(); assert_hidden(obj)
        for shape in (Part.makeCone(10, 4, 25), Part.makeSphere(8), Part.makeTorus(12, 3)):
            target = op.new_shape(doc, shape, "Curved test")
            assert_hidden(target)
            doc.removeObject(target.Name)
        # Exercise the user's actual circle-on-face then Push/Pull path too.
        block = op.new_shape(doc, Part.makeBox(40, 40, 20, V(50, 0, 0)), "Circle host")
        top = block.Shape.Faces[-1]
        disk = g.circle(g.Plane.from_face(top), top.CenterOfMass, 5)
        op.draw_circle(doc, disk, block)
        region = next(face for face in block.Shape.Faces if abs(face.Area - disk.Area) < 1e-6)
        op.extrude(block, region, 10)
        assert_hidden(block)
        doc.undo()
        region = next(face for face in block.Shape.Faces if abs(face.Area - disk.Area) < 1e-6)
        op.extrude(block, region, -10)
        assert_hidden(block)
        doc.removeObject(block.Name)
        flush()
        App.Console.PrintMessage("PASS: regenerated tessellation, Wireframe/Flat Lines, shape edits, Undo/Redo, cylinder/cone/sphere/torus, circle-on-face boss/pocket, deleted object cleanup\n")

        # A different workbench gets exactly the native lines back.
        Gui.activateWorkbench("NoneWorkbench")
        assert not c.seams.records
        seam_hit(True)
        Gui.Selection.addSelection(obj, seam)
        Gui.activateWorkbench("SimpleCADWorkbench")
        assert_hidden(obj)
        assert not Gui.Selection.getSelection(), "Previously selected seam must not retain a visible overlay"
        name = obj.Name
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "native-seams.FCStd")
            doc.saveAs(path)
            App.closeDocument(doc.Name)
            doc = App.openDocument(path)
            obj = doc.getObject(name)
            view = Gui.activeDocument().activeView()
            assert obj.TypeId == "Part::Feature"
            assert obj.Shape.isValid() and len(obj.Shape.Solids) == 1
            assert_hidden(obj)
            # Replacing only display arrays must not mark a saved document dirty.
            assert not Gui.activeDocument().Modified
        App.Console.PrintMessage("PASS: native lines restored outside SimpleCAD, hidden on return/save/reopen; native Part object, no saved geometry or document modification\n")
        return doc
    finally:
        c.cancel(quiet=True)
        prefs.save(previous)
        c.seams.configure(previous.show_seams)
