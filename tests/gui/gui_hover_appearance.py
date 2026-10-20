"""Rendered hover alpha, native FaceN picking and idle-update regressions."""
from pathlib import Path
import tempfile
import time
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import appearance as a, operations as ops, visibility
from simplecad.gui import surface_display
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
from simplecad.gui.tools.selection import DragSelection
try:
    from PySide import QtTest
except ImportError:
    from PySide6 import QtTest


def run(screenshots=False):
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument('HoverAppearanceSmoke'); doc.UndoMode = 1
    obj = ops.new_shape(doc, Part.makeCompound([
        Part.makePlane(10, 10, App.Vector(i*10, 0, 10)) for i in range(3)]), 'Three faces')
    backdrop = ops.new_shape(doc, Part.makePlane(90, 10), 'Backdrop')
    a.commit(a.prepare([(backdrop, ())]), color=[0, 1, 0])
    black = ops.new_shape(doc, Part.makePlane(90, 10, App.Vector(0, 0, -1)), 'Black backdrop')
    white = ops.new_shape(doc, Part.makePlane(90, 10, App.Vector(0, 0, -2)), 'White backdrop')
    for target, color in ((black, [0, 0, 0]), (white, [1, 1, 1])):
        a.commit(a.prepare([(target, ())]), color=color)
        target.ViewObject.Visibility = False
    selection_color, hover_color = surface_display.highlight_colors(obj)
    references = []
    for i, (color, opacity) in enumerate(((hover_color, 100), (hover_color, 57), (selection_color, 100))):
        ref = ops.new_shape(doc, Part.makePlane(10, 10, App.Vector(40+i*20, 0, 10)), 'Reference')
        a.commit(a.prepare([(ref, ())]), color=list(color), opacity=opacity)
        references.append(ref)
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(0., 0., 0., 1.)
    view.fitAll()

    def flush():
        for _ in range(3):
            QtWidgets.QApplication.processEvents(); Gui.updateGui()
        c.seams.refresh(); c.faces.refresh()

    def pixels(label):
        flush(); view.redraw()
        width, height = view.getSize()
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder)/'render.png')
            view.saveImage(path, width, height, 'Current')
            image = QtGui.QImage(path)
            values = []
            for face in list(obj.Shape.Faces)+[ref.Shape.Faces[0] for ref in references]:
                x, y = screen(view, face.CenterOfMass)
                values.append(image.pixelColor(round(x), height-1-round(y)).getRgb()[:3])
            x, y = screen(view, App.Vector(35, 5, 0))
            values.append(image.pixelColor(round(x), height-1-round(y)).getRgb()[:3])
            if screenshots:
                image.save(str(ROOT.parent.parent/'work'/('hover-'+label+'.png')))
            return values

    def near(first, second):
        assert all(abs(x-y) <= 3 for x, y in zip(first, second)), (first, second)

    def clear():
        Gui.Selection.clearSelection(); Gui.Selection.clearPreselection(); c.faces.clear_hover()
        flush()

    try:
        clear()
        reference = pixels('references')
        opaque_reference, translucent_reference, selected_reference = reference[3:6]
        clear()
        a.commit(a.prepare([(obj, ('Face1',))]), color=[1, 0, 0], opacity=57)
        baseline = pixels('mixed')
        shape = obj.Shape; materials = a.fingerprint(obj.ViewObject.ShapeAppearance)
        count = doc.UndoCount
        Gui.Selection.setPreselection(obj, 'Face2')
        hovered = pixels('opaque-hover')
        near(hovered[1], opaque_reference)
        near(hovered[0], baseline[0])
        assert hovered[1] != baseline[1], 'Hover must still highlight its target'
        assert a.fingerprint(obj.ViewObject.ShapeAppearance) == materials
        assert doc.UndoCount == count and obj.Shape.isSame(shape)
        # Exercise Qt's real viewport event path, not only Selection calls.
        main = Gui.getMainWindow()
        mdi = main.findChild(QtWidgets.QMdiArea)
        sub = next(s for s in mdi.subWindowList() if s.windowTitle().startswith(doc.Label))
        mdi.setActiveSubWindow(sub); sub.showMaximized(); flush()
        widget = next(w for w in sub.findChildren(QtWidgets.QWidget) if DragSelection.is_viewport(w))
        x, y = screen(view, obj.Shape.Faces[1].CenterOfMass)
        width, height = view.getSize()
        point = QtCore.QPoint(round(x*widget.width()/width), round(widget.height()-y*widget.height()/height))
        QtTest.QTest.mouseClick(widget, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, point)
        flush()
        assert c.faces.selection_keys() == {(doc.Name, obj.Name, 'Face2')}, c.faces.selection_keys()
        clear()
        Gui.Selection.setPreselection(obj, 'Face1')
        translucent = pixels('transparent-hover')[0]
        # Independent, uniformly styled native planes are render references.
        near(translucent, translucent_reference)
        a.commit(a.prepare([(obj, ())]), opacity=57)
        a.commit(a.prepare([(obj, ('Face2', 'Face3'))]), opacity=100)
        clear()
        Gui.Selection.addSelection(obj, 'Face2')
        selected_mixed = pixels('selected-mixed')[1]
        near(selected_reference, selected_mixed)
        clear()
        for i, face in enumerate(obj.Shape.Faces, 1):
            hit = view.getObjectInfo(tuple(round(x) for x in screen(view, face.CenterOfMass)))
            assert hit and hit['Object'] == obj.Name and hit['Component'] == 'Face'+str(i), hit
        visibility.set_hidden(obj, {2}); flush()
        hit = view.getObjectInfo(tuple(round(x) for x in screen(view, obj.Shape.Faces[1].CenterOfMass)))
        assert hit and hit['Object'] == backdrop.Name, hit
        hidden_pixel = pixels('hidden')[1]
        assert hidden_pixel[1] > 2*max(hidden_pixel[0], hidden_pixel[2]), hidden_pixel
        visibility.set_hidden(obj, set()); flush()
        Gui.Selection.addSelection(obj)
        pixels('whole-selection')
        # Whole-object highlight also adds native emission. Measure alpha by
        # changing only the backdrop, independently of that brighter RGB.
        backdrop.ViewObject.Visibility = False; black.ViewObject.Visibility = True
        dark = pixels('whole-black')
        black.ViewObject.Visibility = False; white.ViewObject.Visibility = True
        light = pixels('whole-white')
        near(light[1], dark[1]); near(light[2], dark[2])
        for channel in range(3):
            expected = .43*(light[-1][channel]-dark[-1][channel])
            assert abs(light[0][channel]-dark[0][channel]-expected) <= 3, (light, dark)
        white.ViewObject.Visibility = False; backdrop.ViewObject.Visibility = True
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(obj, 'Face1'); Gui.Selection.addSelection(obj, 'Face2')
        multi = pixels('multi-selection')
        near(selected_reference, multi[1])
        clear()
        # Shape changes replace cached topology; coordinates/picking stay live.
        old_cache = c.seams.topology[(doc.Name, obj.Name)]
        with ops.transaction(doc, 'Replace surface'):
            obj.Shape = Part.makeBox(30, 10, 10)
        flush()
        assert c.seams.topology[(doc.Name, obj.Name)] is not old_cache
        doc.undo(); flush()
        assert len(obj.Shape.Faces) == 3
        # A comparable 72-face model must reuse its seam topology and batch
        # native material reads; record the idle cost rather than timing CI.
        grid = ops.new_shape(doc, Part.makeCompound([
            Part.makePlane(5, 5, App.Vector(x*5, y*5, z))
            for z in (0, 10) for x in range(6) for y in range(6)]), '72 faces')
        a.commit(a.prepare([(grid, ('Face13',))]), color=[1, 0, 0], opacity=57)
        flush()
        item = c.faces.records[grid.Name]['item']; item.setExpanded(True); c.faces.populate(grid.Name)
        cache = c.seams.topology[(doc.Name, grid.Name)]
        begin = time.perf_counter()
        for _ in range(20):
            c.seams.refresh(); c.faces.refresh()
            assert c.seams.topology[(doc.Name, grid.Name)] is cache
        milliseconds = 1000*(time.perf_counter()-begin)/20
        return ('PASS: rendered opaque/transparent hover references; independent neighbor alpha; '
                'face/multi/object selection; FaceN picking; hidden faces; unchanged Undo/materials; '
                'topology invalidation. 72-face idle refresh: %.1f ms (20 warm iterations).' % milliseconds)
    finally:
        App.closeDocument(doc.Name)
