"""Viewport style in real views: grid, axes, lights, face and edge colours, FreeCAD's own look."""
from pathlib import Path
import tempfile

import FreeCAD as App
import FreeCADGui as Gui
import Mesh
import Part
from pivy import coin
from simplecad.document import appearance as a, operations as ops, visibility
from simplecad.core import preferences as prefs
from simplecad.gui import surface_display, viewport_style as vs
from simplecad.gui.controller import instance
from simplecad.gui.previews.shaded import representation
from simplecad.gui.box_selection import box_selection
from simplecad.gui.snapping import pick, screen
from simplecad.gui.qt import QtGui, QtWidgets
try:
    from PySide import QtTest
except ImportError:
    try: from PySide6 import QtTest
    except ImportError: from PySide2 import QtTest
V = App.Vector
ISOMETRIC = App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), "ZXY").Q


def near(first, second, limit=0.01):
    assert all(abs(x - y) <= limit for x, y in zip(first, second)), (first, second)


def run():
    previous = prefs.load()
    prefs.save(prefs.Settings())
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance(); c.cancel(quiet=True)
    style = c.viewport_style
    doc = App.newDocument("ViewportStyleSmoke"); doc.UndoMode = 1
    others = []
    try:
        box = ops.new_shape(doc, Part.makeBox(10, 10, 10, V(-5, -5, 0)), "Box")
        line = ops.new_shape(doc, Part.makeLine(V(20, 20, 0), V(40, 20, 0)), "Line")
        red = ops.new_shape(doc, Part.makeBox(4, 4, 4, V(30, -20, 0)), "Red edges")
        red.ViewObject.LineColor = (1., 0., 0.)
        # A raw mesh in FreeCAD's default colour, away from the other checks.
        mesh = doc.addObject("Mesh::Feature", "Mesh"); mesh.Mesh = Mesh.createBox(4, 4, 4)
        mesh.Placement.Base = V(12, 8, 0); doc.recompute()
        view = Gui.activeDocument().activeView()
        main = Gui.getMainWindow(); main.resize(1400, 950)
        mdi = main.findChild(QtWidgets.QMdiArea)
        root = view.getSceneGraph()
        manager = view.getViewer().getSoRenderManager()

        def flush():
            for _ in range(3):
                QtWidgets.QApplication.processEvents(); Gui.updateGui()
            QtTest.QTest.qWait(50)
            for _ in range(2):
                QtWidgets.QApplication.processEvents(); Gui.updateGui()

        def camera():
            view.getCameraNode().orientation.setValue(*ISOMETRIC)
            view.fitAll()
            view.getCameraNode().height = 60.
            flush()

        def named(name, node=root):
            return [node.getChild(i) for i in range(node.getNumChildren())
                    if str(node.getChild(i).getName()) == vs.NAME + name]

        def lights():
            own = named("Lights")
            return [bool(light.on.getValue()) for light in vs.native_lights(manager, root, own[0] if own else None)]

        def environment():
            node = next(root.getChild(i) for i in range(root.getNumChildren())
                        if root.getChild(i).isOfType(coin.SoEnvironment.getClassTypeId()))
            return node.ambientIntensity.getValue(), tuple(node.ambientColor.getValue().getValue())

        def line_colours():
            return [tuple(vs.materials(obj.ViewObject.RootNode)["LineMaterial"][0].diffuseColor[0].getValue())
                    for obj in (box, line, red)]

        def face_colours():
            return [tuple(tuple(c.getValue()) for c in vs.materials(obj.ViewObject.RootNode)["ShapeMaterial"][0]
                          .diffuseColor.getValues()) for obj in (box, red, mesh)]

        def faces_are(colour):
            for colours in face_colours():
                assert len(colours) == 1, colours
                near(colours[0], colour, 1e-6)

        def state():
            return (tuple(manager.getBackgroundColor().getValue()), lights(), environment(), line_colours(),
                    root.getNumChildren(), face_colours())

        def same_state(first, second):
            near(first[0], second[0], 1e-6)
            assert first[1] == second[1] and first[4] == second[4], (first, second)
            near(first[2][1] + (first[2][0],), second[2][1] + (second[2][0],), 1e-6)
            for one, other in zip(first[3], second[3]):
                near(one, other, 1e-6)
            assert [len(one) for one in first[5]] == [len(one) for one in second[5]], (first[5], second[5])
            for one, other in zip(first[5], second[5]):
                for a_, b_ in zip(one, other):
                    near(a_, b_, 1e-6)

        def bounds():
            action = coin.SoGetBoundingBoxAction(manager.getViewportRegion())
            action.apply(root)
            found = action.getBoundingBox()
            return tuple(found.getMin().getValue()) + tuple(found.getMax().getValue())

        def fitted():
            view.fitAll(); flush()
            node = view.getCameraNode()
            return tuple(node.position.getValue().getValue()) + (node.height.getValue(),)

        def render():
            width, height = view.getSize()
            with tempfile.TemporaryDirectory() as folder:
                path = str(Path(folder) / "view.png")
                view.saveImage(path, width, height, "Current")
                image = QtGui.QImage(path)
            def pixel(point, spread=0):
                x, y = screen(view, point)
                found = [image.pixelColor(round(x) + dx, height - 1 - round(y) + dy).getRgb()[:3]
                         for dx in range(-spread, spread + 1) for dy in range(-spread, spread + 1)]
                # The reddest pixel of the patch finds a one-pixel X axis line.
                return max(found, key=lambda rgb: rgb[0] - rgb[1]) if spread else found[0]
            return pixel

        free = V(-30, 0, 0)  # on the X axis, away from every object
        empty = V(-23, 27, 0)  # between grid lines and axes

        # FreeCAD's look first, as a reference for the restore checks.
        style.configure(False); camera()
        native = state()
        assert not named("Lights") and not named("Grid") and not named("Axes")
        for colour, expected in zip(native[3], (vs.SIMPLECAD_EDGE, vs.SIMPLECAD_EDGE, (1., 0., 0.))):
            near(colour, expected, 1e-6)
        for colours, expected in zip(native[5], (vs.SIMPLECAD_FACE, vs.SIMPLECAD_FACE, vs.unpack(vs.FREECAD_FACE))):
            assert len(colours) == 1, colours
            near(colours[0], expected, 1e-6)
        assert style.shown_face(box.ViewObject.ShapeColor) == tuple(box.ViewObject.ShapeColor)[:3]
        assert style.shown_edge(box.ViewObject.LineColor) == tuple(box.ViewObject.LineColor)[:3]
        native_bounds, native_fit = bounds(), fitted()
        camera()
        native_empty = render()(empty)
        pos = tuple(round(v) for v in screen(view, free))
        native_hits = view.getObjectsInfo(pos)
        top = next(i + 1 for i, f in enumerate(box.Shape.Faces) if (f.CenterOfMass - V(0, 0, 10)).Length < 1e-6)
        face_hit = view.getObjectInfo(tuple(round(v) for v in screen(view, V(0, 0, 10))))
        assert face_hit and face_hit["Object"] == box.Name and face_hit["Component"] == "Face%d" % top, face_hit
        count, objects = doc.UndoCount, len(doc.Objects)
        materials = [a.fingerprint(obj.ViewObject.ShapeAppearance) for obj in (box, line, red)]
        mesh_colour = tuple(mesh.ViewObject.ShapeColor)[:3]
        properties = [(tuple(o.ViewObject.LineColor), o.ViewObject.LineWidth) for o in (box, line, red)]

        style.configure(True); camera()
        assert len(named("Lights")) == len(named("Grid")) == len(named("Axes")) == 1
        near(manager.getBackgroundColor().getValue(), vs.BACKGROUND)
        assert lights() and not any(lights()), lights()
        record = next(r for r in style.views if r.root == root)
        assert record.rotation.rotation.getValue().equals(view.getCameraNode().orientation.getValue(), 1e-6)
        colours = line_colours()
        near(colours[0], vs.EDGE); near(colours[1], vs.LOOSE); near(colours[2], (1., 0., 0.))
        faces_are(vs.FACE)
        assert style.shown_face(box.ViewObject.ShapeColor) == vs.FACE
        assert style.shown_face((0.2, 0.4, 0.6)) == (0.2, 0.4, 0.6)
        assert style.shown_edge(box.ViewObject.LineColor) == vs.EDGE
        # Shape previews draw the object as the style shows it.
        shown = representation(box, box.Shape)
        for kind, field, expected in ((coin.SoMaterial, "diffuseColor", vs.FACE), (coin.SoBaseColor, "rgb", vs.EDGE)):
            search = coin.SoSearchAction(); search.setType(kind.getClassTypeId()); search.apply(shown)
            near(search.getPath().getTail().getField(field).getValues()[0].getValue(), expected, 1e-6)
        App.Console.PrintMessage("PASS: new document view gets background, grid, axes, camera lights; default faces white (mesh and shape previews too), default edges black, loose lines light, custom edges kept\n")

        # Display only: no bounding box, fit, picking, snapping or selection change.
        near(bounds(), native_bounds, 1e-6)
        near(fitted(), native_fit, 1e-6)
        camera()
        pixel = render()
        axis = pixel(free, 1)
        assert axis[0] > axis[1] + 20 and axis[0] > axis[2] + 20, axis  # the X axis is drawn there
        assert view.getObjectsInfo(pos) == native_hits and view.getObjectInfo(pos) is None
        assert pick(view, doc, pos) is None
        ray = coin.SoRayPickAction(manager.getViewportRegion())
        ray.setPoint(coin.SbVec2s(*pos)); ray.setRadius(4); ray.apply(manager.getSceneGraph())
        assert ray.getPickedPoint() is None
        hit = view.getObjectInfo(tuple(round(v) for v in screen(view, V(0, 0, 10))))
        assert hit == face_hit, (hit, face_hit)
        x, y = pos
        assert box_selection(doc, view, (x - 40, y - 40), (x + 40, y + 40)) == []
        assert box_selection(doc, view, (x + 40, y - 40), (x - 40, y + 40)) == []
        points = []
        for enabled in (True, False, True):
            style.configure(enabled); camera()
            c.start("Line"); c.motion(pos)
            points.append(V(c.drawing_start(pos)[0].point)); c.cancel(quiet=True)
            # Let the view repaint, so the style restores its background
            # before the off-screen pixel checks below.
            flush()
        assert (points[0] - points[1]).Length < 1e-9 and (points[0] - points[2]).Length < 1e-9, points
        assert abs(points[0].y) < 0.5 and abs(points[0].z) < 1e-9 and points[0].x < -20, points
        # Tools toggle a FreeCAD View preference, after which FreeCAD resets its
        # background; no frame may be drawn with it.
        drawn = []
        def traced(unused, action):
            if action.isOfType(coin.SoGLRenderAction.getClassTypeId()):
                drawn.append(tuple(manager.getBackgroundColor().getValue())[:3])
        probe = coin.SoCallback(); probe.setCallback(traced); root.addChild(probe)
        try:
            for _ in range(2):
                c.start("Line"); flush(); c.cancel(quiet=True); flush()
        finally:
            root.removeChild(probe)
        assert drawn and all(vs.close(colour, vs.BACKGROUND) for colour in drawn), drawn
        App.Console.PrintMessage("PASS: grid and axes unpickable, outside bounding box and fitAll; picks, Line points and box selection unchanged; tools never show FreeCAD's background\n")

        # Three greys by face direction on white; a coloured face keeps its colour.
        style.configure(True, (1., 1., 1.)); flush()
        pixel = render()
        near([v / 255 for v in pixel(V(2.5, 2.5, 10))], (0.94,) * 3, 0.03)
        near([v / 255 for v in pixel(V(0, -5, 5))], (0.78,) * 3, 0.03)
        near([v / 255 for v in pixel(V(5, 0, 5))], (0.56,) * 3, 0.03)
        near([v / 255 for v in pixel(empty)], vs.BACKGROUND, 0.02)
        near([v / 255 for v in pixel(V(12, 8, 2))], (0.94,) * 3, 0.03)  # the mesh's top (createBox is centred)
        # The default face colour is a light blue-grey.
        style.configure(True, vs.FACE); flush()
        near([v / 255 for v in render()(V(2.5, 2.5, 10))], [0.873 * c + 0.067 for c in vs.FACE], 0.03)
        # Any face colour; only faces without a colour of their own take it.
        blue = (0.2, 0.5, 0.9)
        style.configure(True, blue); flush()
        faces_are(blue)
        near([v / 255 for v in render()(V(2.5, 2.5, 10))], [0.873 * c + 0.067 for c in blue], 0.03)
        style.configure(True, vs.FACE); flush()
        faces_are(vs.FACE)
        # A colour preview of one face leaves the others in the face colour.
        preview = a.Preview()
        preview.apply(a.plan(a.prepare([(box, ["Face%d" % top])]), color=[1, 0, 0])); flush()
        shown = face_colours()[0]
        assert len(shown) == 6 and shown[top - 1] == (1., 0., 0.), shown
        assert all(vs.close(colour, vs.FACE) for i, colour in enumerate(shown) if i != top - 1), shown
        preview.close(); flush()
        assert all(vs.close(colour, vs.FACE) for colour in face_colours()[0]), face_colours()
        a.commit(a.prepare([(box, ["Face%d" % top])]), color=[1, 0, 0])
        flush()
        pixel = render()
        styled = pixel(V(2.5, 2.5, 10))
        assert styled[0] > 1.5 * max(styled[1:]) and styled[0] > 120, styled
        near([v / 255 for v in pixel(V(0, -5, 5))], [0.713 * c + 0.067 for c in vs.FACE], 0.03)
        style.configure(False); camera()
        plain = render()(V(2.5, 2.5, 10))
        assert plain[0] > 1.5 * max(plain[1:]), plain
        assert not any(vs.close(colour, vs.FACE) for colour in face_colours()[0]), face_colours()
        style.configure(True); camera()
        doc.undo(); flush()
        faces_are(vs.FACE)
        App.Console.PrintMessage("PASS: white faces read light, mid and dark grey by direction; light blue-grey by default, any face colour; previews and a red face keep their colour with and without the style\n")

        # FreeCAD lights a hovered or selected face up by adding its highlight
        # colour, which a white face cannot show. The style draws such faces
        # again in a tint, hover over selection, and keeps OpenGL's depth test
        # as FreeCAD's own highlight needs it.
        record = next(r for r in style.views if r.root == root)
        guards = [node for node in (record.lights.getChild(i) for i in range(record.lights.getNumChildren()))
                  if node.isOfType(coin.SoDepthBuffer.getClassTypeId())]
        assert len(guards) == 1 and guards[0].getField("function").getValue() == coin.SoDepthBuffer.LESS
        selection, hover = surface_display.highlight_colors(box)
        right, left = (next(i + 1 for i, f in enumerate(box.Shape.Faces) if (f.CenterOfMass - centre).Length < 1e-6)
                       for centre in (V(5, 0, 5), V(0, -5, 5)))

        def lit(colour, grey):
            return [grey * value + 0.067 for value in colour]

        def shows(point, colour, grey):
            near([v / 255 for v in render()(point)], lit(colour, grey), 0.03)

        def clear():
            Gui.Selection.clearSelection(); Gui.Selection.clearPreselection(); flush()

        clear(); camera()
        # FreeCAD's own highlight, here on a light blue face without the tint.
        style.configure(True, vs.SIMPLECAD_FACE); flush()
        plain = vs.FaceHighlight.plain
        vs.FaceHighlight.plain = lambda self: False
        try:
            before = render()(V(2.5, 2.5, 10))
            Gui.Selection.setPreselection(box, "Face%d" % top); flush()
            after = render()(V(2.5, 2.5, 10))
            assert after[1] > before[1] + 30 and abs(after[0] - before[0]) < 5, (before, after)
        finally:
            vs.FaceHighlight.plain = plain
        clear(); style.configure(True, vs.FACE); flush()
        Gui.Selection.addSelection(box, "Face%d" % right)
        Gui.Selection.setPreselection(box, "Face%d" % top); flush()
        shows(V(2.5, 2.5, 10), vs.tint(hover), 0.873)
        shows(V(5, 0, 5), vs.tint(selection), 0.493)
        shows(V(0, -5, 5), vs.FACE, 0.713)
        Gui.Selection.setPreselection(box, "Face%d" % right); flush()
        shows(V(5, 0, 5), vs.tint(hover), 0.493)
        Gui.Selection.setPreselection(box, "Edge1"); flush()
        shows(V(2.5, 2.5, 10), vs.FACE, 0.873)
        shows(V(5, 0, 5), vs.tint(selection), 0.493)
        # Hiding a face rewrites FreeCAD's triangles; the tint follows them.
        highlights = style.styled[(doc.Name, box.Name)][4]
        visibility.set_hidden(box, {top}); flush()
        shows(V(5, 0, 5), vs.tint(selection), 0.493)
        clear(); Gui.Selection.addSelection(box); flush()
        for highlight in highlights:
            assert tuple(highlight.parts[0][1].coordIndex.getValues()) == tuple(highlight.native.coordIndex.getValues())
        assert sum(highlight.parts[0][1].coordIndex.getNum() for highlight in highlights) > 0
        visibility.set_hidden(box, set()); clear()
        shows(V(5, 0, 5), vs.FACE, 0.493)
        assert all(not highlight.parts[0][1].coordIndex.getNum() for highlight in highlights)
        # A transparent face keeps FreeCAD's highlight, which shows there.
        red.ViewObject.Transparency = 50
        Gui.Selection.addSelection(red, "Face1"); flush()
        assert all(not any(h.shown[:2]) for h in style.styled[(doc.Name, red.Name)][4])
        red.ViewObject.Transparency = 0; clear()
        # A raw mesh is selected whole: its face colour is tinted, and FreeCAD
        # adds its highlight colour to that.
        Gui.Selection.addSelection(mesh); flush()
        near(face_colours()[2][0], vs.mesh_tint(selection), 1e-6)
        Gui.Selection.setPreselection(mesh, ""); flush()
        near(face_colours()[2][0], vs.mesh_tint(hover), 1e-6)
        clear()
        faces_are(vs.FACE)
        parents = [highlight.parent for highlight in highlights]
        assert parents and all(named("Highlight", parent) for parent in parents)
        style.configure(False); flush()
        Gui.Selection.addSelection(box, "Face%d" % right); flush()
        assert not any(named("Highlight", parent) for parent in parents) and not named("Lights")
        clear(); style.configure(True); camera()
        App.Console.PrintMessage("PASS: hovered and selected faces tinted on white, hover over selection, edges, hidden and transparent faces left to FreeCAD; mesh tinted whole; depth test kept for FreeCAD's highlight\n")

        # Camera changes; turning off or leaving the workbench restores FreeCAD's look.
        record = next(r for r in style.views if r.root == root)  # turning off dropped the old one
        # A camera moved just before FreeCAD deletes it on a perspective switch:
        # Coin still runs its sensor, which must not read the deleted camera.
        grids = []
        record.update_grid = lambda: grids.append(1)
        view.getCameraNode().height = 70.
        view.setCameraType("Perspective")
        assert not record.following()
        coin.SoDB.getSensorManager().processDelayQueue(False)
        del record.update_grid
        assert not grids
        flush(); style.refresh()
        assert record.following()
        assert record.camera.isOfType(coin.SoPerspectiveCamera.getClassTypeId())
        assert record.master == view.getCameraNode()
        view.setCameraType("Orthographic"); flush(); style.refresh()
        view.getCameraNode().height = 6000.; flush()
        assert record.plan[0] >= 100, record.plan
        camera()
        assert record.plan[0] == 10, record.plan
        style.configure(False); camera()
        same_state(state(), native)
        assert not named("Lights") and not named("Grid") and not named("Axes")
        near(render()(empty), native_empty, 2)
        style.configure(True); camera()
        Gui.activateWorkbench("NoneWorkbench"); flush()
        assert not c.active and not named("Grid")
        same_state(state(), native)
        Gui.activateWorkbench("SimpleCADWorkbench"); camera()
        assert named("Grid") and not any(lights())
        App.Console.PrintMessage("PASS: perspective switch ignores the deleted camera, adaptive spacing; off and leaving the workbench restore FreeCAD's background, lights, ambient, faces and edges\n")

        # Later documents and extra views are styled; closing them is harmless.
        other = App.newDocument("ViewportStyleLater"); others.append(other)
        flush(); QtTest.QTest.qWait(100); flush()
        assert named("Grid", Gui.getDocument(other.Name).activeView().getSceneGraph())
        App.closeDocument(other.Name); others.clear(); flush(); style.refresh()
        assert all(r.doc != "ViewportStyleLater" for r in style.views)
        window = next(w for w in mdi.subWindowList() if w.windowTitle().startswith(doc.Label))
        mdi.setActiveSubWindow(window); flush()
        Gui.runCommand("Std_ViewCreate", 0); flush(); style.refresh()
        assert sum(r.doc == doc.Name for r in style.views) == 2, [r.doc for r in style.views]
        mdi.activeSubWindow().close(); flush(); style.refresh()
        assert sum(r.doc == doc.Name for r in style.views) == 1
        assert doc.UndoCount == count and doc.RedoCount == 1 and len(doc.Objects) == objects
        assert [a.fingerprint(obj.ViewObject.ShapeAppearance) for obj in (box, line, red)] == materials
        assert tuple(mesh.ViewObject.ShapeColor)[:3] == mesh_colour
        assert [(tuple(o.ViewObject.LineColor), o.ViewObject.LineWidth) for o in (box, line, red)] == properties
        App.Console.PrintMessage("PASS: later documents and extra views styled, closed views dropped; only the colour test's own Undo step, no saved colour changed\n")
    finally:
        c.cancel(quiet=True)
        prefs.save(previous)
        style.configure(previous.viewport_style, prefs.color(previous.face_color))
        for other in others:
            App.closeDocument(other.Name)
        App.closeDocument(doc.Name)
