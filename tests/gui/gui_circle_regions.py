"""Reproduce overlapping circles; verify native regions, Push/Pull and Delete."""
import math

import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.core import geometry as g
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick
from simplecad.gui.qt import QtCore, QtGui, QtWidgets

V = App.Vector


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADCircleRegionSmoke")
    doc.UndoMode = 1
    view = Gui.activeDocument().activeView()
    c.controls.plane.setCurrentText("Auto")
    c.controls.snap.setChecked(True)

    def polygon(points):
        return Part.Face(Part.makePolygon(points + [points[0]]))

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def delete_key(key):
        c.focus_view()
        focus = QtWidgets.QApplication.focusWidget()
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(focus, QtGui.QKeyEvent(kind, key, QtCore.Qt.NoModifier))

    notched = polygon([V(), V(60, 0, 0), V(40, 15, 0), V(60, 30, 0), V(0, 30, 0)])
    triangle = polygon([V(), V(60, 0, 0), V(0, 40, 0)])
    box = Part.makeBox(60, 40, 20)
    shell = Part.makeShell(box.Faces[1:])
    placement = App.Placement(V(10, 20, 30), App.Rotation(V(1, 2, 0), 24))
    for title, source in (("Notched sheet", notched), ("Triangle", triangle),
                          ("Open shell", shell), ("Solid", box)):
        source = source.copy()
        source.Placement = placement
        obj = op.new_shape(doc, source, title)
        face = source.Faces[-1]  # Original top face stays visible after tilting.
        center = face.CenterOfMass
        profile = g.circle(g.Plane.from_face(face), center, 4)
        # Reproduce both old standalone overlays and old supported profiles.
        legacy = op.new_shape(doc, profile, "Old Circle", obj if source.Solids else None)
        legacy_name = legacy.Name
        view.getCameraNode().orientation.setValue(
            App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), "ZXY").Q)
        view.fitAll()
        Gui.updateGui()
        visible = pick(view, doc, pos(center), face_only=True)
        assert visible and g.coplanar(visible[1], face), (title, visible)
        count = doc.UndoCount
        c.start("Circle")
        c.click(pos(center))
        assert (c.anchor - center).Length < 1e-6
        # Reuse the old circumference endpoint; no remembered radius needed.
        rim = profile.Vertexes[0].Point
        c.motion(pos(rim))
        assert (c.point - rim).Length < 1e-6, (title, c.point, rim)
        assert doc.UndoCount == count
        c.click(pos(rim))
        assert c.tool is None
        assert doc.getObject(legacy_name) is None
        assert len(doc.Objects) == 1
        assert len(obj.Shape.Faces) == len(source.Faces) + 1
        assert abs(obj.Shape.Area - source.Area) < 1e-5
        assert doc.UndoCount == count + 1
        Gui.updateGui()
        hit = pick(view, doc, pos(center), face_only=True)
        assert hit and hit[0] == obj and abs(hit[1].Area - math.pi * 16) < 1e-5, (title, hit)
        outside = center + g.Plane.from_face(face).u * 8
        outer = pick(view, doc, pos(outside), face_only=True)
        assert outer and outer[0] == obj and outer[3] != hit[3], (title, outer)

        for distance in (-3, 3):
            c.start("PushPull")
            c.click(pos(center))
            assert abs(c.face.Area - profile.Area) < 1e-5
            c.controls.value.setText(str(distance))
            c.numeric()
            assert c.tool is None
            assert len(obj.Shape.Solids) == 1 and obj.Shape.isValid()
            expected = source.Volume + profile.Area * distance if source.Solids else profile.Area * abs(distance)
            assert abs(obj.Shape.Volume - expected) < 1e-5
            if not source.Solids:
                rest = next(other for other in doc.Objects if other != obj)
                assert abs(rest.Shape.Area - (source.Area - profile.Area)) < 1e-5
            doc.undo()
            Gui.updateGui()
            assert len(doc.Objects) == 1 and len(obj.Shape.Faces) == len(source.Faces) + 1

        # Select through native picking and exercise both physical key mappings.
        for key in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            hit = pick(view, doc, pos(center), face_only=True)
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(obj, hit[3])
            delete_key(key)
            assert len(doc.Objects) == 1 and obj.Shape.isValid()
            assert not obj.Shape.Solids
            assert abs(obj.Shape.Area - (source.Area - profile.Area)) < 1e-5
            Gui.updateGui()
            through = pick(view, doc, pos(center), face_only=True)
            assert not through or not g.coplanar(through[1], face), (title, through)
            if screenshot and title == "Notched sheet":
                view.saveImage(str(screenshot), 1100, 750, "Current")
            doc.undo()
            Gui.updateGui()
            assert abs(obj.Shape.Area - source.Area) < 1e-5
            assert len(obj.Shape.Faces) == len(source.Faces) + 1
        doc.undo()
        Gui.updateGui()
        assert doc.getObject(legacy_name) is not None
        assert len(obj.Shape.Faces) == len(source.Faces)
        App.Console.PrintMessage("PASS: " + title + " legacy-circle repair, native disk/rim selection, +/- Push/Pull, Delete/Backspace hole, atomic Undo\n")
        for other in list(doc.Objects):
            doc.removeObject(other.Name)
        Gui.updateGui()
    return doc
