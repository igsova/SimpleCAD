"""Dense face rows stay synchronized without repeated individual row updates."""
import time
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.gui.controller import instance
from simplecad.gui.tools.selection import DragSelection
from simplecad.gui.qt import QtCore, QtWidgets


def run():
    Gui.activateWorkbench('SimpleCADWorkbench')
    controller = instance(); controller.cancel(quiet=True)
    doc = App.newDocument('DenseSelectionRegression'); doc.UndoMode = 1
    try:
        obj = doc.addObject('Part::Feature','Grid')
        obj.Shape = Part.makeCompound([Part.makePlane(1,1,App.Vector(x*2,y*2,0))
                                       for x in range(50) for y in range(40)])
        doc.recompute()
        before = doc.UndoCount
        faces = ['Face%d' % i for i in range(1,2001)]
        start = time.monotonic()
        DragSelection.apply([(obj,name) for name in faces],QtCore.Qt.NoModifier)
        QtWidgets.QApplication.processEvents();controller.faces.refresh()
        tree = controller.faces.tree
        assert len(tree.selectedItems()) == 2000
        # An idle refresh must not emit another selection replacement.
        changes = []
        def changed(*args): changes.append(1)
        model = tree.selectionModel();model.selectionChanged.connect(changed)
        for _ in range(5):controller.faces.refresh()
        model.selectionChanged.disconnect(changed)
        assert not changes
        middle = faces[500:1500]
        DragSelection.apply([(obj,name) for name in middle],QtCore.Qt.ControlModifier)
        QtWidgets.QApplication.processEvents();controller.faces.refresh()
        selected = {name for item in Gui.Selection.getSelectionEx() if item.Object==obj
                    for name in item.SubElementNames}
        assert selected == set(faces)-set(middle)
        assert len(tree.selectedItems()) == 1000
        Gui.Selection.clearSelection();controller.faces.refresh()
        assert not tree.selectedItems() and doc.UndoCount==before
        return 'PASS: 2,000-face selection, stable idle, bulk toggle and clear, unchanged Undo; %.2f s' % (time.monotonic()-start)
    finally:
        Gui.Selection.clearSelection();App.closeDocument(doc.Name)
