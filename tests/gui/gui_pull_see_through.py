"""Push/Pull into a solid shows its walls and cap through the faces; the outward look is unchanged."""
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace

import FreeCAD as App
import FreeCADGui as Gui
import Part
from pivy import coin
from simplecad.core import geometry as g, preferences as prefs
from simplecad.document import operations as op
from simplecad.gui.previews import overlay as preview
from simplecad.gui.controller import instance
from simplecad.gui.snapping import pick, screen
from simplecad.gui.qt import QtGui, QtWidgets
try:
    from PySide import QtTest
except ImportError:
    try: from PySide6 import QtTest
    except ImportError: from PySide2 import QtTest
V = App.Vector
ISOMETRIC = App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), "ZXY").Q
SOLID = tuple(round(255 * value) for value in preview.LINE_COLOR)


def teal(rgb):
    """A preview line pixel, solid or see-through; not a grey face, the background, a guide or a profile."""
    r, gr, b = rgb
    return r < 80 and gr > 90 and gr - r > 70 and b > r


def solid(rgb):
    return all(abs(x - y) <= 12 for x, y in zip(rgb, SOLID))


def run():
    previous = prefs.load(); prefs.save(prefs.Settings())
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance(); c.cancel(quiet=True)
    style = c.viewport_style
    doc = App.newDocument("PullSeeThroughSmoke"); doc.UndoMode = 1
    try:
        box = op.new_shape(doc, Part.makeBox(40, 40, 20, V(20, 20, 0)), "Box")
        center = V(40, 40, 20)
        op.draw_circle(doc, g.circle(g.Plane.named("XY", center), center, 8), box)
        support = op.new_shape(doc, Part.makeBox(40, 40, 20, V(80, 20, 0)), "Support")
        rectangle = op.new_shape(doc, g.rectangle(g.Plane.named("XY", V(0, 0, 20)), V(90, 30, 20), V(110, 50, 20)),
                                 "Rectangle", support)
        original = box.Shape
        main = Gui.getMainWindow(); main.resize(1400, 950)
        view = Gui.activeDocument().activeView()
        root = view.getSceneGraph()
        c.controls.snap.setChecked(True)

        def flush():
            # The style restores its background when the view repaints.
            for _ in range(3):
                QtWidgets.QApplication.processEvents(); Gui.updateGui()
            QtTest.QTest.qWait(50)
            for _ in range(2):
                QtWidgets.QApplication.processEvents(); Gui.updateGui()

        def camera():
            view.getCameraNode().orientation.setValue(*ISOMETRIC); view.fitAll(); flush()

        def pos(point):
            return tuple(round(value) for value in screen(view, point))

        def send(event, point):
            event.setPosition(coin.SbVec2s(*pos(point)))
            c.coin_event(SimpleNamespace(getEvent=lambda: event, setHandled=lambda: None))

        def press(point):
            event = coin.SoMouseButtonEvent()
            event.setButton(coin.SoMouseButtonEvent.BUTTON1); event.setState(coin.SoButtonEvent.DOWN)
            send(event, point)

        def move(point):
            send(coin.SoLocation2Event(), point)

        def render():
            flush()
            width, height = view.getSize()
            with tempfile.TemporaryDirectory() as folder:
                path = str(Path(folder) / "view.png")
                view.saveImage(path, width, height, "Current")
                return QtGui.QImage(path)

        def near(image, point, spread=3):
            x, y = screen(view, point)
            x, y = round(x), image.height() - 1 - round(y)
            return [image.pixelColor(x + dx, y + dy).getRgb()[:3]
                    for dx in range(-spread, spread + 1) for dy in range(-spread, spread + 1)]

        def samples(polylines):
            return [a + (b - a) * t for line in polylines for a, b in zip(line, line[1:]) for t in (0, .5)]

        def behind(inp):
            """Wall and cap points of the current pull hidden by the solid, clear of the face's own outline."""
            delta = inp.normal * inp.distance
            mouth = samples(preview.outline(inp.face))
            cap = [p + delta for p in mouth]
            walls = [v.Point + delta * t for v in inp.face.Vertexes for t in (0.4, 0.6, 0.8)]
            rim = [screen(view, p) for p in mouth]
            points = [p for p in cap + walls if min(math.dist(screen(view, p), q) for q in rim) > 8]
            for p in points:
                # Behind a face of the solid, where main drew no preview pixel.
                hit = pick(view, doc, pos(p), face_only=True)
                assert hit and hit[0] in (inp.obj, getattr(inp.obj, "SC_Support", None)), (p, hit)
                assert (p - hit[2]).dot(view.getViewDirection()) > 1, (p, hit[2])
            assert len(points) >= 10, len(points)
            return points, mouth

        def shown(image, points):
            return sum(any(teal(rgb) for rgb in near(image, p)) for p in points) / len(points)

        def check_inward(inp, label):
            points, mouth = behind(inp)
            image = render()
            fraction = shown(image, points)
            assert fraction >= 0.85, (label, fraction, inp.distance)
            # The visible part of the face's outline is drawn over, as before.
            assert any(solid(rgb) for p in mouth for rgb in near(image, p, 1)), label
            assert preview_switch() == 0, label
            return image

        def preview_switch():
            return c.preview.see_through.whichChild.getValue()

        def see_through_nodes():
            search = coin.SoSearchAction()
            search.setName(coin.SbName(preview.SEE_THROUGH))
            search.setInterest(coin.SoSearchAction.ALL); search.setSearchingAll(True)
            search.apply(root)
            return search.getPaths().getLength()

        camera()
        c.start("PushPull")
        press(center)
        inp = c.push_pull_input
        assert inp.face is not None and abs(inp.pull_contact.distance + 20) < 1e-6
        count = doc.UndoCount
        move(inp.anchor + inp.normal * -8)
        assert -8.5 < inp.distance < -7.5 and inp.direction_sign == -1, inp.distance
        check_inward(inp, "drag inward")
        App.Console.PrintMessage("PASS: an inward drag draws the pocket's walls and cap through the solid's faces\n")

        # Dragging only translates the cap: its points are not sent again.
        writes = []
        sensor = coin.SoFieldSensor(lambda *unused: writes.append(1), None)
        sensor.setPriority(0); sensor.attach(c.preview.moving_coords.point)
        try:
            for depth in (-5, -9, -12, -6):
                move(inp.anchor + inp.normal * depth)
        finally:
            sensor.detach()
        assert not writes and preview_switch() == 0, writes
        assert see_through_nodes() == 1

        move(inp.anchor + inp.normal * -19.6)
        assert inp.distance == inp.pull_contact.distance and c.controls.label.text().startswith("On opposite face")
        check_inward(inp, "opposite face snap")
        z = c.preview.offset.translation.getValue()[2]
        assert abs(z + 20) < 1e-5 and abs(c.preview.marker_coords.point[0][2]) < 1e-5, z

        # Typed outward: no see-through pass, the frame is the one drawn without its node.
        dialog = inp.dialog
        dialog.dir_combo.setCurrentIndex(0)
        assert inp.distance == 20 and preview_switch() == coin.SO_SWITCH_NONE, inp.distance
        dialog.dist_edit.setText("6 mm"); dialog.on_distance_edited("6 mm")
        assert inp.distance == 6 and preview_switch() == coin.SO_SWITCH_NONE, (inp.distance, preview_switch())
        image = render()
        cap = [p + inp.normal * 6 for p in samples(preview.outline(inp.face))]
        assert sum(any(solid(rgb) for rgb in near(image, p, 1)) for p in cap) / len(cap) >= 0.9
        node = c.preview.see_through
        node.ref()
        index = c.preview.root.findChild(node)
        c.preview.root.removeChild(index)
        try:
            without = render()
        finally:
            c.preview.root.insertChild(node, index); node.unref()
        assert image == without, "an outward preview must look as before"
        App.Console.PrintMessage("PASS: outward previews draw no see-through pass and render as without it\n")

        dialog.flip_direction()
        assert inp.distance == -6
        check_inward(inp, "Flip")
        dialog.to_opposite_face()
        assert inp.distance == -20
        check_inward(inp, "opposite face button")
        dialog.reset_distance()
        assert preview_switch() == coin.SO_SWITCH_NONE

        # FreeCAD's own look: the same pass, without the style's depth guard.
        dialog.on_distance_edited("-10")
        style.configure(False); camera()
        check_inward(inp, "style off")
        style.configure(True); camera()
        check_inward(inp, "style on again")
        App.Console.PrintMessage("PASS: typed, Flip, Opposite face button and snap; with the viewport style on and off\n")

        c.cancel(quiet=True)
        assert c.tool is None and see_through_nodes() == 0
        assert doc.UndoCount == count, (doc.UndoCount, count)
        assert box.Shape.isSame(original) and abs(box.Shape.Volume - 32000) < 1e-6
        flush()

        # A supported rectangle profile pulls into its solid the same way; Apply commits once.
        c.start("PushPull")
        press(V(100, 40, 20))
        inp = c.push_pull_input
        assert inp.obj == rectangle, inp.obj
        move(inp.anchor + inp.normal * -8)
        check_inward(inp, "rectangle")
        distance = inp.distance
        c.click(pos(inp.anchor + inp.normal * -8))
        assert c.tool is None and doc.UndoCount == count + 1 and see_through_nodes() == 0
        assert abs(support.Shape.Volume - (32000 + 400 * distance)) < 1e-4, support.Shape.Volume
        doc.undo()
        assert abs(support.Shape.Volume - 32000) < 1e-6
        App.Console.PrintMessage("PASS: supported rectangle pocket shows through; Cancel and Apply remove the pass; Cancel keeps the model\n")

        # Other tools and Push/Pull's face hover never draw it.
        c.start("PushPull")
        move(center)
        assert c.push_pull_input.face is None and preview_switch() == coin.SO_SWITCH_NONE
        c.cancel(quiet=True)
        c.start("Rectangle")
        move(V(30, 30, 20))
        assert preview_switch() == coin.SO_SWITCH_NONE
        c.cancel(quiet=True)
        assert see_through_nodes() == 0
        App.Console.PrintMessage("PASS: the see-through pass is opt-in for Push/Pull\n")
        return doc
    finally:
        c.cancel(quiet=True)
        prefs.save(previous)
        style.configure(previous.viewport_style, prefs.color(previous.face_color))
