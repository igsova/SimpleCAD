"""Tool panels open in the bottom-right corner of the 3D view, leaving the model visible.

Covers panels shown with show() (Push/Pull, Measure, Rotate, Slice) and with exec()
(Mirror, Offset face), a panel growing while it stays in the corner, and a panel the
user moved staying where it was put. SC_PANEL_SCREENSHOT saves the Push/Pull screen.
"""
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.document import operations as op
from simplecad.core import preferences as prefs
from simplecad.gui.controller import instance
from simplecad.gui.panels import PANEL_MARGIN
from simplecad.gui.qt import QtCore, QtGui, QtWidgets


def run(screenshots=False):
    previous = prefs.load()
    prefs.save(prefs.Settings())
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance(); c.cancel(quiet=True)
    main = Gui.getMainWindow()
    geometry, maximized = main.geometry(), main.isMaximized()
    doc = App.newDocument('SimpleCADPanelPlacement'); doc.UndoMode = 1

    def flush():
        for _ in range(4):
            QtWidgets.QApplication.processEvents(); Gui.updateGui()

    def select(*names):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj, *([list(names)] if names else []))

    def view_rect():
        widget = mdi.currentSubWindow().widget()
        assert widget.inherits('Gui::View3DInventor'), widget.metaObject().className()
        return QtCore.QRect(widget.mapToGlobal(QtCore.QPoint(0, 0)), widget.size())

    def check(dialog, name):
        flush()
        view, frame = view_rect(), dialog.frameGeometry()
        assert dialog.isVisible(), name
        assert view.contains(frame), (name, frame, view)
        gaps = view.right() - frame.right(), view.bottom() - frame.bottom()
        assert all(0 <= gap <= PANEL_MARGIN + 2 for gap in gaps), (name, gaps, frame, view)
        assert not frame.contains(view.center()), (name, frame, view)
        return frame

    def modal(name, start):
        """Start a tool whose panel runs exec(); check it from inside the dialog's loop."""
        seen, tries = [], [0]

        def poll():
            widget = QtWidgets.QApplication.activeModalWidget()
            if widget is not None and widget.objectName() == name:
                try:
                    seen.append(check(widget, name))
                except AssertionError as error:
                    seen.append(error)
                widget.reject()
            elif tries[0] < 100:
                tries[0] += 1; QtCore.QTimer.singleShot(50, poll)
            elif widget is not None:
                widget.reject()  # never leave the suite blocked in exec()
        QtCore.QTimer.singleShot(50, poll)
        start(); flush()
        assert len(seen) == 1 and isinstance(seen[0], QtCore.QRect), (name, seen)

    try:
        main.showNormal(); main.setGeometry(QtGui.QGuiApplication.primaryScreen().availableGeometry()); flush()
        obj = op.new_shape(doc, Part.makeBox(40, 30, 20), 'Panel placement box'); count = doc.UndoCount
        mdi = main.findChild(QtWidgets.QMdiArea)
        sub = [s for s in mdi.subWindowList() if s.widget().inherits('Gui::View3DInventor')][-1]
        mdi.setActiveSubWindow(sub); sub.showMaximized()
        view = Gui.activeDocument().activeView(); view.viewIsometric(); view.fitAll(); flush()
        assert view_rect().width() > 800 and view_rect().height() > 500, view_rect()

        select('Face6')
        c.start('PushPull'); flush()
        assert c.tool == 'PushPull' and c.push_pull_input.dialog is not None
        check(c.push_pull_input.dialog, 'Push/Pull')
        if os.environ.get('SC_PANEL_SCREENSHOT'):
            view.fitAll(); flush()
            QtGui.QGuiApplication.primaryScreen().grabWindow(0).save(os.environ['SC_PANEL_SCREENSHOT'])
        c.cancel(); flush()

        c.start('Measure'); flush()
        check(c.measure_session.dialog, 'Measure')
        c.cancel(); flush()

        select()
        c.start('Rotate'); flush()
        assert c.tool == 'Rotate'
        check(c.rotate_session.dialog, 'Rotate')
        c.cancel(); flush()

        select()
        c.start('Slice'); flush()
        session = c.slice_session; dialog = session.dialog
        before = check(dialog, 'Slice')
        session.joint.enabled.setChecked(True); flush()
        grown = check(dialog, 'Slice with joint rows')  # grew, and the corner stayed put
        assert grown.height() > before.height(), (before, grown)
        moved = view_rect().topLeft() + QtCore.QPoint(40, 40)
        dialog.move(moved); flush(); height = dialog.height()
        session.joint.more.setChecked(True); flush()
        assert dialog.height() > height and dialog.pos() == moved, (dialog.pos(), moved)  # the user's spot wins
        c.cancel(); flush()

        select()
        modal('SimpleCADMirror', lambda: c.start('Mirror'))
        select('Face6')
        modal('SimpleCADOffsetFace', lambda: c.start('OffsetFace'))
        assert doc.UndoCount == count and len(doc.Objects) == 1, (doc.UndoCount, len(doc.Objects))  # nothing applied
        print('panel placement: Push/Pull, Measure, Rotate, Slice, Mirror and Offset face open bottom-right')
    finally:
        c.cancel(quiet=True)
        App.closeDocument(doc.Name)
        main.setGeometry(geometry)
        if maximized:
            main.showMaximized()
        prefs.save(previous)
