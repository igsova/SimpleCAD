"""Curved-surface tools from the toolbar: dialogs, previews, Undo and Cancel."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from simplecad.gui import command_state
from simplecad.gui.tools import curvature as curvature_ui
from simplecad.jobs import shape as shape_jobs
from simplecad.surfaces import operations as so
from simplecad.gui.controller import instance

V = App.Vector


def active(key):
    command_state.current(fresh=True)
    return Gui.Command.get('SimpleCAD_' + key).isActive()


def pick(obj, *names):
    Gui.Selection.clearSelection()
    if names:
        Gui.Selection.addSelection(obj, list(names))
    else:
        Gui.Selection.addSelection(obj)


def when_open(name, action):
    """Run action(dialog) once a dialog with this object name is open."""
    def poll():
        widget = QtWidgets.QApplication.activeModalWidget()
        if widget is not None and widget.objectName() == name:
            QtWidgets.QApplication.processEvents()
            action(widget)
        else:
            QtCore.QTimer.singleShot(50, poll)
    QtCore.QTimer.singleShot(50, poll)


def settle(dialog):
    dialog.timer.stop()
    dialog.redraw()


def apply(dialog):
    settle(dialog)
    assert dialog.apply_button.isEnabled(), dialog.info.text()
    dialog.accept()


def faces(obj, kind):
    return ['Face%d' % i for i, f in enumerate(obj.Shape.Faces, 1) if isinstance(f.Surface, kind)]


def run():
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance(); c.cancel(quiet=True)
    window = Gui.getMainWindow()
    bars = {bar.windowTitle(): bar for bar in window.findChildren(QtWidgets.QToolBar)}
    surface = [a.text().replace('&&', '&') for a in bars['SimpleCAD Surface'].actions() if a.text()]
    assert surface == ['Draw on surface…', 'Offset face…', 'Shell / Thicken…', 'Draft faces…', 'Delete & heal faces',
                       'Remove rounds…', 'Fill hole…', 'Unwrap face'], surface
    assert 'Pattern…' in [a.text() for a in bars['SimpleCAD Modify'].actions()]
    assert 'Curvature map' in [a.text() for a in bars['SimpleCAD Inspect'].actions()]
    doc = App.newDocument('SurfaceToolsTest')
    try:
        box = Part.makeBox(20, 20, 10)
        part = doc.addObject('Part::Feature', 'Rounded')
        part.Shape = box.makeFillet(2, box.Edges[:4])
        part.Placement = App.Placement(V(5, 0, 0), App.Rotation(V(0, 0, 1), 20))
        doc.recompute()
        placement = App.Placement(part.Placement)
        rounds = faces(part, Part.Cylinder)
        assert len(rounds) == 4

        # Availability on a curved face.
        pick(part, rounds[0])
        for key in ('Imprint', 'OffsetFace', 'Shell', 'Draft', 'HealFaces', 'RemoveRounds', 'Unwrap', 'Curvature',
                    'Pattern'):
            assert active(key) == (key != 'Pattern'), key
        assert not active('PushPull') and not active('FillHole')

        # Delete & heal one round: one Undo step, Placement kept.
        undo = doc.UndoCount
        c.start('HealFaces')
        assert len(part.Shape.Faces) == 9 and doc.UndoCount == undo + 1, (len(part.Shape.Faces), doc.UndoCount)
        assert part.Placement.isSame(placement, 1e-9)
        doc.undo()
        assert len(part.Shape.Faces) == 10

        # Remove rounds: the dialog previews what it finds; Cancel changes nothing.
        pick(part)
        when_open('SimpleCADRemoveRounds', lambda d: (settle(d), d.reject()))
        c.start('RemoveRounds')
        assert len(part.Shape.Faces) == 10 and doc.UndoCount == undo

        def remove(dialog):
            settle(dialog)
            assert dialog.info.text().startswith('4 rounds found'), dialog.info.text()
            assert dialog.preview.lines.numVertices.getNum() > 0
            dialog.radius.setValue(1)
            settle(dialog)
            assert not dialog.apply_button.isEnabled()
            dialog.radius.setValue(3)
            apply(dialog)
        pick(part)
        when_open('SimpleCADRemoveRounds', remove)
        c.start('RemoveRounds')
        assert len(part.Shape.Faces) == 6 and abs(part.Shape.Volume - 4000) < 1e-3, len(part.Shape.Faces)
        assert part.Placement.isSame(placement, 1e-9)
        doc.undo()

        # Cancelling the worker leaves the model unchanged.
        def cancel_job():
            job = window.findChild(QtWidgets.QProgressDialog, 'SimpleCADShapeJob')
            if job is None:
                QtCore.QTimer.singleShot(20, cancel_job)
            else:
                job.cancel()
        QtCore.QTimer.singleShot(20, cancel_job)
        try:
            so.heal_faces(part, rounds[:1])
            raise AssertionError('The cancelled job applied a result')
        except shape_jobs.Cancelled:
            pass
        assert len(part.Shape.Faces) == 10 and doc.UndoCount == undo

        # Draw on surface: a circle on the top face becomes a selected region.
        top = next('Face%d' % i for i, f in enumerate(part.Shape.Faces, 1)
                   if isinstance(f.Surface, Part.Plane) and f.CenterOfMass.z > 9.9)
        pick(part, top)

        def circle(dialog):
            dialog.shape.setCurrentIndex(1)
            dialog.diameter.setValue(6)
            settle(dialog)
            assert 'lands on the faces' in dialog.info.text(), dialog.info.text()
            apply(dialog)
        when_open('SimpleCADImprint', circle)
        c.start('Imprint')
        chosen = Gui.Selection.getSelectionEx()
        assert chosen and len(chosen[0].SubElementNames) == 1, chosen
        assert len(part.Shape.Faces) == 11 and doc.UndoCount == undo + 1
        doc.undo()

        # Offset face: the top moves up 2 mm in one Undo step; Cancel changes nothing.
        pick(part, top)
        when_open('SimpleCADOffsetFace', lambda d: (settle(d), d.reject()))
        c.start('OffsetFace')
        assert doc.UndoCount == undo

        def offset(dialog):
            settle(dialog)
            assert dialog.preview.lines.numVertices.getNum() > 0
            dialog.distance.setValue(0)
            settle(dialog)
            assert not dialog.apply_button.isEnabled()
            dialog.distance.setValue(2)
            apply(dialog)
        before = part.Shape.Volume
        when_open('SimpleCADOffsetFace', offset)
        c.start('OffsetFace')
        assert part.Shape.BoundBox.ZMax > 11.9 and part.Shape.Volume > before + 600, part.Shape.BoundBox
        assert part.Placement.isSame(placement, 1e-9) and doc.UndoCount == undo + 1
        doc.undo()

        # Shell: hollow a block with its top open.
        block = doc.addObject('Part::Feature', 'Block')
        block.Shape = Part.makeBox(20, 20, 10, V(0, -40, 0))
        doc.recompute()
        lid = next(n for n in faces(block, Part.Plane) if block.Shape.getElement(n).CenterOfMass.z > 9.9)
        pick(block, lid)
        when_open('SimpleCADShell', lambda d: (settle(d), d.thickness.setValue(1), apply(d)))
        c.start('Shell')
        assert abs(block.Shape.Volume - (4000 - 18 * 18 * 9)) < 1e-3, block.Shape.Volume
        doc.undo()

        # Draft the four sides about the bottom.
        sides = [n for n in faces(block, Part.Plane) if abs(block.Shape.getElement(n).Surface.Axis.z) < 1e-6]
        pick(block, *sides)
        assert active('Draft')

        def tilt(dialog):
            settle(dialog)
            assert 'narrows toward the top' in dialog.info.text(), dialog.info.text()
            apply(dialog)
        when_open('SimpleCADDraft', tilt)
        c.start('Draft')
        roof = next(f for f in block.Shape.Faces if f.CenterOfMass.z > 9.99)
        floor = next(f for f in block.Shape.Faces if f.CenterOfMass.z < 1e-6)
        assert roof.Area < floor.Area, (roof.Area, floor.Area)
        doc.undo()

        # Emboss text on a curved round; the outline is centred on the face.
        wall = Part.makeCylinder(15, 30)
        drum = doc.addObject('Part::Feature', 'Drum')
        drum.Shape = wall
        doc.recompute()
        side = faces(drum, Part.Cylinder)[0]
        pick(drum, side)

        def raised(dialog):
            assert dialog.wrap.isChecked()  # one curved face: wrapped like a label by default
            dialog.shape.setCurrentIndex(3)
            dialog.text.setText('SC')
            dialog.size.setValue(6)
            dialog.mode.setCurrentIndex(1)
            dialog.depth.setValue(.8)
            if not dialog.font:
                dialog.shape.setCurrentIndex(0)  # no bundled font in this FreeCAD build
            apply(dialog)
        before = drum.Shape.Volume
        when_open('SimpleCADImprint', raised)
        c.start('Imprint')
        assert drum.Shape.Volume > before + 1, (before, drum.Shape.Volume)
        assert len(drum.Shape.Solids) == 1 and drum.Shape.isValid()

        # A wrapped rectangle keeps its size around the drum.
        side = max(faces(drum, Part.Cylinder), key=lambda name: drum.Shape.getElement(name).Area)
        pick(drum, side)

        def label(dialog):
            dialog.shape.setCurrentIndex(0)
            dialog.width.setValue(40)
            dialog.height.setValue(6)
            dialog.mode.setCurrentIndex(0)
            settle(dialog)
            assert 'keeping its size' in dialog.info.text(), dialog.info.text()
            apply(dialog)
        when_open('SimpleCADImprint', label)
        c.start('Imprint')
        chosen = Gui.Selection.getSelectionEx()[0].SubElementNames  # two faces if it crosses the seam
        assert abs(sum(drum.Shape.getElement(name).Area for name in chosen) - 240) < 1, chosen

        # Fill hole closes an open box into a solid.
        shell = doc.addObject('Part::Feature', 'OpenBox')
        shell.Shape = Part.Shell(Part.makeBox(10, 10, 10, V(0, 40, 0)).Faces[:5])
        doc.recompute()
        pick(shell)
        assert active('FillHole') and not active('HealFaces')
        when_open('SimpleCADFillHole', apply)
        c.start('FillHole')
        assert len(shell.Shape.Solids) == 1 and abs(shell.Shape.Volume - 1000) < 1e-4

        # Unwrap a curved face into a new flat object.
        count = len(doc.Objects)
        pick(drum, side)
        c.start('Unwrap')
        assert len(doc.Objects) == count + 1
        flat = doc.Objects[-1]
        assert flat.Shape.BoundBox.ZLength < 1e-6 and flat.Shape.Area > 2000, flat.Shape.Area

        # Pattern around Z: three copies in one Undo step.
        undo = doc.UndoCount
        pick(part)

        def around(dialog):
            dialog.kind.setCurrentIndex(1)
            dialog.count.setValue(4)
            settle(dialog)
            assert dialog.info.text() == '3 copies will be made.', dialog.info.text()
            apply(dialog)
        when_open('SimpleCADPattern', around)
        c.start('Pattern')
        assert len(doc.Objects) == count + 4 and doc.UndoCount == undo + 1
        doc.undo()
        assert len(doc.Objects) == count + 1

        # Curvature map: shown on the selection, hidden again by the same command.
        pick(drum)
        c.start('Curvature')
        assert curvature_ui.shown(doc)
        assert active('Curvature')
        # The map is laid on the triangles the view shades, read from its scene graph.
        drawn = curvature_ui.drawn_mesh(drum)
        assert drawn is not None and len(drawn[1]) == len(drum.Shape.Faces)
        box = drum.Shape.BoundBox
        box.enlarge(1e-3)
        assert all(box.isInside(App.Vector(*p)) for p in drawn[0]) and any(drawn[1])
        Gui.Selection.clearSelection()
        assert active('Curvature')  # hiding needs no selection
        c.start('Curvature')
        assert not curvature_ui.shown(doc)
        print('surface tools: toolbar, dialogs, previews, worker cancel, undo and curvature map passed')
    finally:
        Gui.Selection.clearSelection()
        curvature_ui.hide(doc)
        App.closeDocument(doc.Name)
