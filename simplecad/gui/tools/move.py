"""Move and Copy panel: the move as X, Y and Z distances, typed or followed live."""
import FreeCAD as App
import FreeCADGui as Gui
from ...core import geometry as geo
from ..qt import QtCore, QtWidgets


def faces_to_move(selection, doc):
    """(object, face names) when faces of one solid are selected, else None.

    Edges and vertices of those faces may be selected with them, as clicking
    around a boss easily picks its rims too; they move with the faces. A
    whole object, or an edge or vertex off the selected faces, keeps Move on
    whole objects as before.
    """
    items = [item for item in selection if item.Object.Document == doc]
    if not items or any(not item.SubElementNames for item in items):
        return None
    names = [name for item in items for name in item.SubElementNames]
    faces = list(dict.fromkeys(name for name in names if name.startswith('Face')))
    if not faces:
        return None
    owners = {item.Object for item in items}
    if len(owners) > 1:
        raise ValueError('Select faces of one object to move them, or select whole objects.')
    obj = items[0].Object
    shape = getattr(obj, 'Shape', None)
    others = [name for name in names if not name.startswith('Face')]
    if others:
        chosen = [shape.getElement(name) for name in faces]
        for name in others:
            element = shape.getElement(name)
            parts = (lambda face: face.Edges) if name.startswith('Edge') else (lambda face: face.Vertexes)
            if not any(element.isSame(part) for face in chosen for part in parts(face)):
                return None
    if not getattr(shape, 'Solids', None):
        raise ValueError('Moving faces needs a closed solid. Select the whole object to move it.')
    return obj, faces


class MovePanel:
    """X, Y, Z fields that show the move while you drag and set it when typed."""

    def __init__(self, controller, title):
        self.c = controller
        self.typed = False
        self.updating = False
        self.dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self.dialog.setObjectName("SimpleCADMove")
        self.dialog.setWindowTitle(controller.tool)
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        layout = QtWidgets.QVBoxLayout(self.dialog)
        self.title = QtWidgets.QLabel(title, self.dialog)
        self.title.setStyleSheet("font-weight: bold; color: #50d6bb;")
        layout.addWidget(self.title)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)
        self.fields = []
        for axis in "XYZ":
            # Empty, so a click puts the cursor in a blank field: "0 mm" is only the placeholder.
            field = QtWidgets.QLineEdit(self.dialog)
            field.setObjectName("SimpleCADMove" + axis)
            field.setPlaceholderText("0 mm")
            field.textEdited.connect(self.edited)
            field.returnPressed.connect(self.apply)
            form.addRow(axis, field)
            self.fields.append(field)
        self.status = QtWidgets.QLabel(self.dialog)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.Apply)
        self.apply_button.setAutoDefault(False)
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply)
        # Enter in a field applies; it must not also press Cancel.
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setAutoDefault(False)
        buttons.rejected.connect(controller.cancel)
        self.dialog.rejected.connect(controller.cancel)
        layout.addWidget(buttons)
        self.hint("Type X, Y and Z, or click a base point and a destination in the view.")
        # The view keeps the keyboard for X/Y/Z locks and Tab.
        self.dialog.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        from ..panels import anchor_panel
        anchor_panel(self.dialog).show()

    def owns(self, widget):
        """Whether ``widget`` is one of this panel's own, such as an X, Y or Z field."""
        try:
            return (self.dialog is not None and isinstance(widget, QtWidgets.QWidget)
                    and (widget is self.dialog or self.dialog.isAncestorOf(widget)))
        except (RuntimeError, ReferenceError):
            return False

    def hint(self, text, error=False):
        self.status.setStyleSheet("color: #ff7b72;" if error else "")
        self.status.setText(text)

    def values(self):
        return geo.V(*[geo.parse_length(field.text()) if field.text().strip() else 0.0 for field in self.fields])

    def show(self, delta):
        """Follow the pointer: the fields show the move so far."""
        if self.typed or self.updating:
            return
        for field, value in zip(self.fields, (delta.x, delta.y, delta.z)):
            if not field.hasFocus():
                field.setText("%.2f mm" % value)
        self.apply_button.setEnabled(delta.Length >= geo.EPS)

    def edited(self, *unused):
        """A typed value takes over from the pointer until Apply or Esc."""
        try:
            delta = self.values()
        except Exception:
            self.apply_button.setEnabled(False)
            self.hint("Enter distances such as 5, -2.5 mm or 1 cm.", error=True)
            return
        self.typed = True
        self.updating = True
        try:
            self.c.typed_move(delta)
        finally:
            self.updating = False
        self.apply_button.setEnabled(delta.Length >= geo.EPS)
        self.hint("Enter or Apply moves by these distances · Esc cancels")

    def apply(self):
        try:
            delta = self.values()
        except Exception:
            self.hint("Enter distances such as 5, -2.5 mm or 1 cm.", error=True)
            return
        if delta.Length < geo.EPS:
            self.hint("Enter a distance on at least one axis.", error=True)
            return
        try:
            if self.typed or self.c.anchor is None:
                self.c.typed_move(delta)
            self.c.commit()
        except Exception as error:
            self.c.report(error)
            if self.dialog is not None:
                self.hint(str(error), error=True)

    def close(self):
        dialog, self.dialog = self.dialog, None
        if dialog is not None:
            try:
                dialog.blockSignals(True)
                dialog.close()
                dialog.deleteLater()
            except (RuntimeError, ReferenceError):
                pass
