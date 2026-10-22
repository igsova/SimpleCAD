"""Live native material preview, applied in one Undo step or restored on cancel."""
import FreeCAD  # noqa: F401  Load the application before its native modules.
import FreeCADGui as Gui
from ...document import appearance
from ..qt import QtCore, QtGui, QtWidgets
from ..panels import anchor_panel


class AppearanceDialog(QtWidgets.QDialog):
    def __init__(self, targets, refresh, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Color & opacity')
        self.setObjectName('SimpleCADAppearance')
        self.targets, self.refresh = targets, refresh
        self.material_preview = appearance.Preview()
        self.color_value = self.opacity_value = None
        self.failed = False
        values = [m for obj, _, indices, original in targets
                  for i, m in enumerate(appearance.expanded(obj, original)) if indices is None or i in indices]
        colors = [tuple(m.DiffuseColor[:3]) for m in values]
        opacities = [round(100*(1-m.Transparency)) for m in values]
        self.initial_color = QtGui.QColor.fromRgbF(*colors[0])
        self.mixed_color = any(c != colors[0] for c in colors)
        self.mixed_opacity = any(o != opacities[0] for o in opacities)
        layout = QtWidgets.QVBoxLayout(self)
        whole = sum(indices is None for _, _, indices, _ in targets)
        face_count = sum(len(indices) for _, _, indices, _ in targets if indices is not None)
        parts = ([f'{whole} whole object'+('s' if whole != 1 else '')] if whole else [])
        if face_count: parts.append(f'{face_count} face'+('s' if face_count != 1 else ''))
        layout.addWidget(QtWidgets.QLabel(' · '.join(parts)))
        form = QtWidgets.QFormLayout(); layout.addLayout(form)
        self.color_button = QtWidgets.QPushButton()
        self.color_button.setAutoDefault(False)
        self.color_button.setObjectName('SimpleCADAppearanceColor')
        self.color_button.clicked.connect(self.choose_color)
        form.addRow('Surface color', self.color_button)
        self.update_color_button()
        row = QtWidgets.QHBoxLayout()
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.slider.setRange(0, 100)
        self.slider.setStyleSheet('QSlider::groove:horizontal { height: 5px; background: #59666c; border-radius: 2px; } '
                                 'QSlider::handle:horizontal { width: 16px; margin: -6px 0; background: #00d6c0; border-radius: 8px; }')
        self.opacity = QtWidgets.QSpinBox(); self.opacity.setRange(0, 100); self.opacity.setSuffix(' %')
        self.opacity.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.opacity.setObjectName('SimpleCADAppearanceOpacity')
        self.opacity.setValue(opacities[0]); self.slider.setValue(opacities[0])
        self.slider.valueChanged.connect(self.opacity.setValue)
        self.opacity.valueChanged.connect(self.set_opacity)
        row.addWidget(self.slider, 1); row.addWidget(self.opacity)
        form.addRow('Opacity', row)
        self.note = QtWidgets.QLabel('Mixed opacity — move the slider to set all selected surfaces.' if self.mixed_opacity
                                    else '0% transparent · 100% opaque')
        self.note.setWordWrap(True); layout.addWidget(self.note)
        hint = QtWidgets.QLabel('Preview updates immediately. Only the controls you change are applied.\nEdges stay visible; the eye hides a face or object completely.')
        hint.setWordWrap(True); layout.addWidget(hint)
        self.error = QtWidgets.QLabel(); self.error.setWordWrap(True); layout.addWidget(self.error)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply = buttons.button(QtWidgets.QDialogButtonBox.Apply); self.apply.setEnabled(False); self.apply.setDefault(True)
        self.apply.clicked.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setMinimumWidth(460)

    def update_color_button(self):
        color = QtGui.QColor.fromRgbF(*self.color_value) if self.color_value is not None else self.initial_color
        self.color_button.setText('Mixed colors — choose…' if self.mixed_color and self.color_value is None else color.name().upper()+'  ·  Choose…')
        if not self.mixed_color or self.color_value is not None:
            brightness = .2126*color.redF() + .7152*color.greenF() + .0722*color.blueF()
            foreground = '#101820' if brightness > .5 else '#ffffff'
            self.color_button.setStyleSheet('QPushButton { background-color: '+color.name()+'; color: '+foreground+'; padding: 8px; }')

    def choose_color(self):
        start = QtGui.QColor.fromRgbF(*self.color_value) if self.color_value is not None else self.initial_color
        color = QtWidgets.QColorDialog.getColor(start, self, 'Choose surface color')
        if color.isValid():
            self.set_color(color)

    def set_color(self, color):
        self.color_value = (color.redF(), color.greenF(), color.blueF())
        self.update_color_button(); self.preview()

    def set_opacity(self, value):
        self.slider.setValue(value)
        self.opacity_value = value
        self.note.setText('0% transparent · 100% opaque')
        self.preview()

    def preview(self):
        try:
            self.material_preview.apply(appearance.plan(self.targets, self.color_value, self.opacity_value))
            self.refresh()
            self.apply.setEnabled(True); self.error.clear(); self.failed = False
        except Exception as error:
            self.failed = True; self.apply.setEnabled(False); self.error.setText(str(error))


def show(controller):
    targets = appearance.prepare([(s.Object, tuple(s.SubElementNames)) for s in Gui.Selection.getSelectionEx()])
    doc = targets[0][0].Document
    if not doc.UndoMode:
        raise ValueError('Enable Undo for this document before changing appearance.')
    selection = [(s.Object, tuple(s.SubElementNames)) for s in Gui.Selection.getSelectionEx()]
    Gui.Selection.clearSelection(); Gui.Selection.clearPreselection()
    dialog = AppearanceDialog(targets, controller.seams.refresh, Gui.getMainWindow())
    accepted = False
    try:
        accepted = anchor_panel(dialog).exec() == QtWidgets.QDialog.Accepted and not dialog.failed
        dialog.material_preview.close()
        if accepted and (dialog.color_value is not None or dialog.opacity_value is not None):
            appearance.commit(targets,dialog.color_value,dialog.opacity_value)
    finally:
        dialog.material_preview.close()
        controller.seams.refresh(); controller.faces.refresh()
        if not accepted:
            for obj, names in selection:
                if obj.isValid():
                    for name in names or ('',): Gui.Selection.addSelection(obj, name)
        dialog.deleteLater()
    controller.message('Appearance applied · Undo restores it' if accepted else 'Appearance canceled')
