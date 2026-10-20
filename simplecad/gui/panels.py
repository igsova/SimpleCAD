"""Tool panels open in the bottom-right corner of the 3D view, clear of the model."""
from .qt import QtCore, QtGui, QtWidgets


PANEL_MARGIN = 12  # px between a tool panel and the corner of the 3D view


def panel_position(view, frame, screen=None, margin=PANEL_MARGIN):
    """Top-left (x, y) of a panel frame (width, height) in the bottom-right corner of the
    view (x, y, width, height). A panel bigger than the view starts at the view's top-left;
    the screen (x, y, width, height) keeps it reachable."""
    x, y = (max(view[i] + view[i + 2] - frame[i] - margin, view[i]) for i in (0, 1))
    if screen:
        x, y = (max(min(value, screen[i] + screen[i + 2] - frame[i]), screen[i]) for i, value in enumerate((x, y)))
    return x, y


def view_widget(dialog=None):
    """The current 3D view's widget, else the main window (None without one)."""
    try:
        import FreeCADGui as Gui
        main = Gui.getMainWindow()
    except (ImportError, AttributeError):
        main = None
    if main is None and dialog is not None and dialog.parentWidget() is not None:
        main = dialog.parentWidget().window()
    if main is None:
        return None
    mdi = main.findChild(QtWidgets.QMdiArea)
    sub = mdi.currentSubWindow() if mdi else None
    widget = sub.widget() if sub else None
    return widget if widget is not None and widget.inherits('Gui::View3DInventor') and widget.isVisible() else main


class PanelAnchor(QtCore.QObject):
    """Places its dialog when shown and keeps it in the corner as its rows grow,
    until the user drags it somewhere else."""
    def __init__(self, dialog, margin=PANEL_MARGIN):
        super().__init__(dialog)
        self.margin, self.spot, self.shown = margin, None, False
        dialog.installEventFilter(self)

    def place(self, force=False):
        try:  # Placement is cosmetic; it never stops a tool from opening.
            dialog = self.parent()
            if not force and dialog.pos() != self.spot:
                return
            widget = view_widget(dialog)
            if widget is None:
                return
            corner = widget.mapToGlobal(QtCore.QPoint(0, 0))
            screen = (QtGui.QGuiApplication.screenAt(widget.mapToGlobal(widget.rect().center()))
                      or QtGui.QGuiApplication.primaryScreen())
            area = screen.availableGeometry().getRect() if screen else None
            frame = dialog.frameGeometry()
            x, y = panel_position((corner.x(), corner.y(), widget.width(), widget.height()),
                                  (frame.width(), frame.height()), area, self.margin)
            if dialog.pos() != QtCore.QPoint(x, y):
                dialog.move(x, y)
            self.spot = dialog.pos()
        except (RuntimeError, AttributeError):
            pass

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QtCore.QEvent.Show:
            # Shown: final size, and the native frame is known before the window maps.
            self.place(not self.shown); self.shown = True
            QtCore.QTimer.singleShot(0, self.place)
        elif kind == QtCore.QEvent.LayoutRequest and watched.isVisible():
            QtCore.QTimer.singleShot(0, self.place)  # rows shown or hidden: keep the corner
        return False


def anchor_panel(dialog, margin=PANEL_MARGIN):
    """Open a tool panel in the bottom-right corner of the active 3D view, clear of the model
    being edited. Call before show() or exec(); returns the dialog."""
    if getattr(dialog, 'simplecad_anchor', None) is None:
        dialog.simplecad_anchor = PanelAnchor(dialog, margin)
        dialog.simplecad_anchor.place(True)
    return dialog
