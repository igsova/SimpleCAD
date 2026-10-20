"""Push/Pull pocket, exact hole, past-face cap, and returning a cap to a hole."""
from types import SimpleNamespace

import FreeCAD as App
import FreeCADGui as Gui
import Part
from pivy import coin
from simplecad import ROOT
from simplecad.core import geometry as g, coincident as coinc, preferences as prefs
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import pick, screen
from simplecad.gui.qt import QtCore, QtGui, QtWidgets

V = App.Vector


def run(screenshots=False):
    previous = prefs.load()
    prefs.save(prefs.Settings())
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADPullContactSmoke")
    doc.UndoMode = 1
    try:
        box = Part.makeBox(40, 40, 20)
        obj = op.new_shape(doc, box, "Push/Pull test")
        profile = g.circle(g.Plane.named("XY", V(20, 20, 20)), V(20, 20, 20), 5)
        op.draw_circle(doc, profile, obj)
        view = Gui.activeDocument().activeView()
        c.controls.snap.setChecked(True)

        def camera(below=False):
            view.getCameraNode().orientation.setValue(
                App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, -1 if below else 1), "ZXY").Q)
            view.fitAll(); Gui.updateGui()

        def pos(point):
            return tuple(round(value) for value in screen(view, point))

        def mouse(state, position):
            event = coin.SoMouseButtonEvent()
            event.setButton(coin.SoMouseButtonEvent.BUTTON1)
            event.setState(state)
            event.setPosition(coin.SbVec2s(*position))
            c.coin_event(SimpleNamespace(getEvent=lambda: event, setHandled=lambda: None))

        def save(label):
            if screenshots:
                camera(below=True)
                Gui.Selection.clearSelection(); Gui.updateGui()
                view.saveImage(str(ROOT.parent.parent / "work" / ("pull-" + label + ".png")), 1000, 750, "Current")

        def start():
            camera()
            center = V(20, 20, 20)
            hit = pick(view, doc, pos(center), face_only=True)
            assert hit and coinc.same(hit[1], profile), hit
            c.start("PushPull")
            mouse(coin.SoButtonEvent.DOWN, pos(center))
            assert abs(c.pull_contact.distance + 20) < 1e-6

        for depth, label in ((-10, "pocket"), (-19.7, "hole"), (-30, "beyond")):
            start()
            count = doc.UndoCount
            destination = pos(c.anchor + c.normal * depth)
            c.motion(destination)
            assert doc.UndoCount == count and len(obj.Shape.Solids) == 1
            if label == "hole":
                assert c.distance == c.pull_contact.distance
                assert c.controls.label.text().startswith("On opposite face")
                assert c.preview.pull_guide.texts[-1].string[0] == "Opposite face snapped"
            else:
                assert abs(c.distance - depth) < .2
                assert c.preview.pull_guide.texts[-1].string[0] == "Opposite face"
            committed_distance = c.distance
            mouse(coin.SoButtonEvent.UP, destination)
            assert c.tool is None and doc.UndoCount == count + 1
            assert obj.Shape.isValid() and len(doc.Objects) == 1
            if label == "beyond":
                assert not obj.Shape.Solids
                assert any(coinc.same(face, box.Faces[4]) for face in obj.Shape.Faces)
                assert abs(obj.Shape.BoundBox.ZMin - (20 + committed_distance)) < 1e-6
                cap = profile.copy(); cap.translate(V(0, 0, committed_distance))
                assert any(coinc.same(face, cap) for face in obj.Shape.Faces)
            else:
                assert len(obj.Shape.Solids) == 1
                assert abs(obj.Shape.Volume - (32000 + profile.Area * committed_distance)) < 1e-5
            save(label)
            doc.undo()
            assert len(obj.Shape.Solids) == 1 and abs(obj.Shape.Volume - 32000) < 1e-5
        App.Console.PrintMessage("PASS: native mouse drag/release: pocket, exact face snap creates hole, farther drag creates cap and preserves opposite face; no preview writes; atomic Undo\n")

        # Typed dimensions must not be silently attracted by the mouse radius.
        start()
        c.controls.value.setText("-20.2 mm")
        c.controls.value.setFocus()
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(c.controls.value, QtGui.QKeyEvent(kind, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier))
        assert c.tool is None and not obj.Shape.Solids
        assert abs(obj.Shape.BoundBox.ZMin + .2) < 1e-6
        doc.undo()

        # Snap off allows a pointer release just beyond the face as well.
        start(); c.controls.snap.setChecked(False)
        destination = pos(c.anchor + c.normal * -20.8)
        c.motion(destination)
        assert c.distance < -20.1
        assert c.preview.pull_guide.switch.whichChild.getValue() == coin.SO_SWITCH_NONE
        mouse(coin.SoButtonEvent.UP, destination)
        assert not obj.Shape.Solids
        doc.undo(); c.controls.snap.setChecked(True)
        App.Console.PrintMessage("PASS: exact typed distances bypass mouse magnet; Snap off hides target and allows a small overshoot\n")

        # Return an actual rendered cap to the intact back face.
        start(); c.controls.value.setText("-30"); c.numeric()
        camera(below=True)
        cap_center = V(20, 20, -10)
        hit = pick(view, doc, pos(cap_center), face_only=True)
        assert hit and abs(hit[1].CenterOfMass.z + 10) < 1e-6, hit
        count = doc.UndoCount
        c.start("PushPull"); c.click(pos(cap_center))
        assert abs(c.pull_contact.distance - 10) < 1e-5
        destination = pos(c.anchor + c.normal * 9.7)
        c.motion(destination)
        assert abs(c.distance - 10) < 1e-5
        c.click(destination)
        assert c.tool is None and doc.UndoCount == count + 1
        assert len(obj.Shape.Solids) == 1
        assert abs(obj.Shape.Volume - (32000 - profile.Area * 20)) < 1e-5
        doc.undo(); assert not obj.Shape.Solids
        doc.redo(); assert len(obj.Shape.Solids) == 1
        App.Console.PrintMessage("PASS: native cap pick, click-move-click retraction snaps onto the opposite face and makes a solid with a through-hole; Undo/Redo\n")

        # Perspective drag still captures and releases the plane at its true position.
        doc.undo(); doc.undo()
        view.setCameraType("Perspective")
        start()
        destination = pos(c.anchor + c.normal * -19.7)
        c.motion(destination)
        assert abs(c.distance + 20) < 1e-5
        c.motion(pos(c.anchor + c.normal * -30))
        assert c.distance < -25
        c.cancel(quiet=True)
        App.Console.PrintMessage("PASS: perspective face contact and release beyond; cancellation preserves the model\n")
        start()
        doc.undo()
        c.check_context()
        assert c.tool is None, "Undo must discard the cached opposite face"
        doc.redo()
        return doc
    finally:
        c.cancel(quiet=True)
        prefs.save(previous)
