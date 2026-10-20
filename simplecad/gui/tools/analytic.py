"""Dialog for converting selected faceted loops into analytic geometry."""
import FreeCAD as App
import FreeCADGui as Gui

from ...modeling import analytic
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel


class AnalyticDialog(QtWidgets.QDialog):
    def __init__(self, target, parent=None):
        super().__init__(parent)
        self.target = target
        self.setWindowTitle('Fit analytic geometry')
        self.setObjectName('SimpleCADAnalyticGeometry')
        layout = QtWidgets.QVBoxLayout(self)
        label = 'Circle loop' if target['kind'] == 'circle' else 'Cylindrical wall / two rims'
        layout.addWidget(QtWidgets.QLabel('%s\nRadius: %.6g mm%s' %
                                          (label, target['radius'],
                                           '' if target['kind'] == 'circle' else '\nLength: %.6g mm' % target['height'])))
        self.mode = QtWidgets.QComboBox()
        if target.get('can_replace_rim'):
            self.mode.addItem('Replace circular edge in this shape (native circle edge)', 'replace_rim')
        self.mode.addItem('Analytic circle edge (new object)', 'circle')
        if target['kind'] == 'cylinder':
            self.mode.addItem('Analytic cylinder solid', 'cylinder')
        if target.get('can_cut'):
            self.mode.addItem('Replace the hole in this shape (analytic cylinder & circular rims)', 'hole')
        if target.get('can_cut'):
            self.mode.setCurrentIndex(self.mode.count() - 1)
        elif target.get('can_replace_rim'):
            self.mode.setCurrentIndex(0)
        elif target['kind'] == 'cylinder':
            self.mode.setCurrentIndex(1)
        layout.addWidget(self.mode)
        self.replace = QtWidgets.QCheckBox('Replace the source when the whole object is selected')
        self.replace.setChecked(bool(target['can_replace']))
        self.replace.setEnabled(bool(target['can_replace']))
        layout.addWidget(self.replace)
        # The in-place hole and rim replacements always keep the source object.
        def refresh_replace():
            in_place = self.mode.currentData() in ('hole', 'replace_rim')
            self.replace.setEnabled(bool(target['can_replace']) and not in_place)
        self.mode.currentIndexChanged.connect(refresh_replace)
        refresh_replace()
        note = QtWidgets.QLabel('Select both circular rims or the complete faceted wall of a hole to replace it with one '
                                'analytic cylinder; a single rim is paired with its opposite rim automatically. '
                                'One loop alone creates a circle edge, and a whole selected object becomes a cylinder. '
                                'Ambiguous geometry is left unchanged.')
        note.setWordWrap(True); layout.addWidget(note)
        self.error = QtWidgets.QLabel(); self.error.setWordWrap(True); layout.addWidget(self.error)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.Apply)
        self.apply_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setMinimumWidth(420)


def show(controller):
    doc = App.ActiveDocument
    selection = []
    if doc is not None:
        # SelectionEx is the right source for faces/edges, but a tree click can
        # expose only the object selection.  Keep one normalized entry per
        # object so analytic.prepare can fit a standalone whole cylinder too.
        for item in Gui.Selection.getSelectionEx():
            obj = getattr(item, 'Object', None)
            if obj is None or obj.Document != doc:
                continue
            names = tuple(getattr(item, 'SubElementNames', ()) or ())
            existing = next((index for index, (candidate, _) in enumerate(selection)
                             if candidate == obj), None)
            if existing is None:
                selection.append((obj, names))
            elif names:
                selection[existing] = (obj, selection[existing][1] + tuple(name for name in names
                                                                            if name not in selection[existing][1]))
        if not selection:
            for obj in Gui.Selection.getSelection():
                if getattr(obj, 'Document', None) == doc:
                    selection.append((obj, ()))
    try:
        target = analytic.prepare(selection)
    except Exception as error:
        controller.message(str(error))
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), 'Fit analytic geometry', str(error))
        return False
    saved = selection
    Gui.Selection.clearSelection(); Gui.Selection.clearPreselection()
    dialog = AnalyticDialog(target, Gui.getMainWindow())
    try:
        if anchor_panel(dialog).exec() != QtWidgets.QDialog.Accepted:
            return False
        result = analytic.apply(target, dialog.mode.currentData(), dialog.replace.isChecked())
        Gui.Selection.addSelection(result)
        controller.faces.refresh()
        if dialog.mode.currentData() == 'hole':
            controller.message('Hole replaced with an analytic cylinder · Undo restores the facets')
        elif dialog.mode.currentData() == 'replace_rim':
            controller.message('Circular edge replaced with native circle · Undo restores the facets')
        else:
            controller.message('Analytic geometry created · Undo restores the source')
        return True
    except Exception as error:
        dialog.error.setText(str(error))
        raise
    finally:
        dialog.deleteLater()
        if not Gui.Selection.getSelectionEx():
            for obj, names in saved:
                if obj.isValid():
                    for name in names or ('',):
                        Gui.Selection.addSelection(obj, name)
