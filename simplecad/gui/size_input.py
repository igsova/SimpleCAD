"""Boxes in the 3D view for typing a size while drawing.

The status-bar field stays the value every tool reads; these boxes only edit
it where the eye already is. A Rectangle gets one box on each side's size
label and Tab moves between them. Line, Circle, Sphere and Polygon get one on
their size label, and the other tools one beside the pointer.
"""
from .qt import QtGui, QtWidgets

STYLE = ("QLineEdit { background: #121619; color: #f4f7f6; border: 1px solid #1ad9a6;"
         " border-radius: 3px; padding: 1px 4px; font-weight: bold; }"
         " QLineEdit:focus { border: 2px solid #1ad9a6; }")


def widget_point(view, widget, spot):
    """Qt position in ``widget`` of a Coin screen position: bottom-left, physical pixels."""
    width, height = view.getSize()
    return spot[0] * widget.width() / width, widget.height() - spot[1] * widget.height() / height


class SizeInput:
    def __init__(self, controller):
        self.controller = controller
        self.boxes = []
        self.widget = None

    def owns(self, widget):
        return widget is not None and any(widget is box for box in self.boxes)

    def open(self, text=""):
        """Show the boxes with ``text`` typed into the first; False where there is no 3D view to show them in."""
        c = self.controller
        self.close()
        try:
            self.widget = c.view.graphicsView().viewport()
        except (AttributeError, RuntimeError, ReferenceError):
            return False
        for index in range(2 if c.tool == "Rectangle" else 1):
            box = QtWidgets.QLineEdit(self.widget)
            box.setObjectName("SimpleCADSizeBox")
            box.setStyleSheet(STYLE)
            # Left-aligned, as Qt hides a centred placeholder while the box has
            # focus. Its final size is set before placing, or the centring is off.
            box.ensurePolished()
            box.setFixedSize(QtGui.QFontMetrics(box.font()).horizontalAdvance("00000.00 mm") + 16,
                             box.sizeHint().height())
            box.textEdited.connect(self.edited)
            box.returnPressed.connect(c.numeric)
            self.boxes.append(box)
        if c.preview is not None:
            c.preview.labelled = self.place
        self.place()
        for box in self.boxes:
            box.show()
            box.raise_()
        self.boxes[0].setFocus()
        self.boxes[0].setText(text)
        self.edited()
        return True

    def edited(self, *unused):
        """Write the boxes into the status-bar field; a comma moves on to the next box."""
        if len(self.boxes) > 1 and "," in self.boxes[0].text():
            first, rest = self.boxes[0].text().split(",", 1)
            self.boxes[0].setText(first.strip())
            self.boxes[1].setText(rest.strip() or self.boxes[1].text())
            self.boxes[1].setFocus()
        for box in self.boxes:
            if box.text()[:1].isspace():
                box.setText(box.text().lstrip())  # the space typed after "40,"
        texts = [box.text().strip() for box in self.boxes]
        # A missing height leaves one value, which the tool names as missing.
        self.controller.controls.value.setText(", ".join(text for text in texts if text))

    def step(self, direction=1):
        """Tab: focus the next box (Shift+Tab the previous one)."""
        focus = QtWidgets.QApplication.focusWidget()
        index = next((i for i, box in enumerate(self.boxes) if box is focus), 0)
        box = self.boxes[(index + direction) % len(self.boxes)]
        box.setFocus()
        box.selectAll()

    def place(self):
        """Put each box on its size label, or beside the pointer when the shape has none."""
        c = self.controller
        if not self.boxes or c.view is None:
            return
        spots = c.preview.label_spots() if c.preview is not None else []
        sizes = c.preview.label_texts() if c.preview is not None else []
        try:
            for index, box in enumerate(self.boxes):
                # Empty, a box shows the size it covers, as the label did.
                box.setPlaceholderText(sizes[index] if index < len(sizes)
                                       else c.controls.value.placeholderText() or "Size")
                spot = spots[index] if index < len(spots) else None
                if spot is not None:
                    x, y = widget_point(c.view, self.widget, spot)
                    x, y = x - box.width() / 2, y - box.height() / 2
                elif c.last_pos is not None:
                    x, y = widget_point(c.view, self.widget, c.last_pos)
                    x, y = x + 18, y + 18 + index * (box.height() + 4)
                else:
                    x, y = 12, 12 + index * (box.height() + 4)
                x = min(max(0, x), self.widget.width() - box.width())
                y = min(max(0, y), self.widget.height() - box.height())
                box.move(int(round(x)), int(round(y)))
        except (RuntimeError, ReferenceError, ZeroDivisionError):
            pass

    def close(self):
        boxes, self.boxes = self.boxes, []
        for box in boxes:
            try:
                box.hide()
                box.deleteLater()
            except RuntimeError:
                pass
        preview = self.controller.preview
        if boxes and preview is not None and preview.labelled == self.place:
            preview.labelled = None
        self.widget = None
