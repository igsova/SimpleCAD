"""Viewport-only rubber band; ordinary clicks still go to FreeCAD."""
import FreeCAD as App
import FreeCADGui as Gui

from pivy import coin

from ...core import preferences
from ...document import visibility
from ...core.geometry import Plane, seam_indices
from ..snapping import ray, pick
from ..box_selection import box_selection
from ..qt import QtCore, QtGui, QtWidgets


def visible_names(obj, names):
    """Names of elements not hidden with the face eyes."""
    hidden = visibility.hidden_faces(obj)
    if not hidden:
        return list(names)
    edges, vertices = visibility.object_hidden_elements(obj, hidden)
    blocked = {'Face%d' % i for i in hidden} | {'Edge%d' % i for i in edges} | {'Vertex%d' % i for i in vertices}
    return [name for name in names if name not in blocked]


class SelectionBox:
    """Unpickable Coin overlay, including on macOS OpenGL/Retina views."""
    def __init__(self, view, widget):
        self.view, self.widget = view, widget
        self.root = coin.SoSeparator()
        pick = coin.SoPickStyle(); pick.style = coin.SoPickStyle.UNPICKABLE
        self.root.addChild(pick)
        depth = coin.SoDepthBuffer(); depth.function = coin.SoDepthBuffer.ALWAYS; depth.write = False
        self.root.addChild(depth)
        light = coin.SoLightModel(); light.model = coin.SoLightModel.BASE_COLOR
        self.root.addChild(light)
        self.coords = coin.SoCoordinate3()
        self.color = coin.SoBaseColor()
        self.styles = []
        self.texts, self.positions = [], []
        for outline in (True, False):
            layer = coin.SoSeparator()
            color = coin.SoBaseColor(); color.rgb = (.03, .05, .06)
            layer.addChild(color if outline else self.color)
            style = coin.SoDrawStyle(); self.styles.append(style)
            layer.addChild(style); layer.addChild(self.coords)
            line = coin.SoLineSet(); line.numVertices = 5; layer.addChild(line)
            self.root.addChild(layer)
            text_layer = coin.SoSeparator()
            text_layer.addChild(color if outline else self.color)
            position = coin.SoTranslation(); self.positions.append(position); text_layer.addChild(position)
            font = coin.SoFont(); font.size = 14 * view.getSize()[0] / widget.width(); text_layer.addChild(font)
            text = coin.SoText2(); self.texts.append(text); text_layer.addChild(text)
            self.root.addChild(text_layer)
        self.crossing = False
        view.getSceneGraph().addChild(self.root)

    def move_box(self, start, end):
        self.crossing = end.x() < start.x()
        width, height = self.view.getSize()
        sx, sy = width / self.widget.width(), height / self.widget.height()
        camera = self.view.getCameraNode()
        center = App.Vector(*camera.position.getValue()) + self.view.getViewDirection() * camera.focalDistance.getValue()
        plane = Plane.from_normal(center, self.view.getViewDirection())
        def world(x, y):
            return tuple(plane.intersect(*ray(self.view, (x*sx, height-y*sy))))
        left, right = sorted((start.x(), end.x()))
        top, bottom = sorted((start.y(), end.y()))
        self.coords.point.setValues([world(left,top),world(right,top),world(right,bottom),world(left,bottom),world(left,top)])
        self.color.rgb = (.16,.81,.57) if self.crossing else (.29,.69,1.0)
        for index, style in enumerate(self.styles):
            style.lineWidth = (4 if index == 0 else 2) * sx
            style.linePattern = 0xF0F0 if self.crossing else 0xFFFF
        label = "Crossing: inside or touching" if self.crossing else "Window: fully inside"
        x, y = min(left, max(2, self.widget.width()-240)), max(18, top-8)
        for index, (position, text) in enumerate(zip(self.positions,self.texts)):
            position.translation = world(x + (1-index), y + (1-index))
            text.string = label
        self.view.redraw()

    def close(self):
        try:
            self.view.getSceneGraph().removeChild(self.root)
            self.view.redraw()
        except (RuntimeError, ReferenceError):
            pass


class DragSelection(QtCore.QObject):
    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.widget = None
        self.overlay = None
        self.replaying = False
        self.ignore_release = None
        # All, Faces, Edges, Vertices or Objects: what clicks and boxes select.
        self.filter = 'All'
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.check_context)

    def cancel(self):
        self.timer.stop()
        if self.widget is not None:
            self.ignore_release = self.widget
        self.widget = None
        if self.overlay is not None:
            try:
                self.overlay.close()
            except RuntimeError:
                pass
            self.overlay = None

    def check_context(self):
        if self.widget is None:
            return
        try:
            mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
            if (App.ActiveDocument != self.doc or Gui.activeDocument().activeView() != self.view
                    or self.doc.UndoCount != self.undo_count or not self.widget.isVisible()
                    or not mdi.currentSubWindow().isAncestorOf(self.widget)):
                self.cancel()
        except (AttributeError, RuntimeError, ReferenceError):
            self.cancel()

    @staticmethod
    def is_viewport(widget):
        # Restrict interception to the render widget, never trees, text fields,
        # scrollbars, the Start page, or other Qt panels.
        if not isinstance(widget, QtWidgets.QWidget) or not widget.inherits("QOpenGLWidget"):
            return False
        parent = widget.parentWidget()
        while parent:
            if parent.metaObject().className() == "Gui::View3DInventorViewer":
                return True
            parent = parent.parentWidget()
        return False

    def viewport_position(self, widget, event):
        # Coin uses bottom-left physical pixels; Qt uses top-left logical ones.
        width, height = self.view.getSize()
        point = event.localPos()
        return point.x()*width/widget.width(), height-point.y()*height/widget.height()

    def filtered_pick(self, pos):
        """The click's hit under the selection filter, as (object, subelement) pairs."""
        if self.filter == 'Faces':
            hit = pick(self.view, self.doc, pos, face_only=True)
        else:
            hit = pick(self.view, self.doc, pos, prefer_boundary=True)
        if not hit:
            return []
        return self.filtered([(hit[0], hit[3])])

    def filtered(self, hits):
        """Hits of the kinds the filter allows; Objects selects whole objects."""
        if self.filter == 'Objects':
            return list({(obj.Document.Name, obj.Name): (obj, '') for obj, _ in hits}.values())
        prefix = {'Faces': 'Face', 'Edges': 'Edge', 'Vertices': 'Vertex'}.get(self.filter)
        return [(obj, name) for obj, name in hits if prefix is None or name.startswith(prefix)]

    def native_click(self, widget, release):
        if self.filter != 'All' or any(visibility.hidden_faces(obj) for obj in self.doc.Objects if hasattr(obj, 'Shape')):
            # Degenerate Coin edge polylines preserve EdgeN, but their endpoint
            # can still appear in raw ray hits. Skip hidden elements before
            # choosing the frontmost visible hit for an ordinary click. A
            # selection filter also picks here, so a click near an edge in
            # Edges mode takes the edge instead of being refused.
            self.apply(self.filtered_pick(self.viewport_position(widget, release)), release.modifiers())
            return
        self.replay(widget, (self.press, (release.type(), release.localPos(), release.globalPos(),
                                        release.button(), release.buttons(), release.modifiers())))

    def replay(self, widget, events):
        self.replaying = True
        try:
            for kind, position, global_position, button, buttons, modifiers in events:
                event = QtGui.QMouseEvent(kind, QtCore.QPointF(position), QtCore.QPointF(global_position),
                                         button, buttons, modifiers)
                QtWidgets.QApplication.sendEvent(widget, event)
        finally:
            self.replaying = False

    @staticmethod
    def apply(hits, modifiers):
        toggle = bool(modifiers & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier))
        add = bool(modifiers & QtCore.Qt.ShiftModifier)
        key = lambda obj: (obj.Document.Name, obj.Name)
        existing = {(key(item.Object), name) for item in Gui.Selection.getSelectionEx()
                    for name in (item.SubElementNames or ("",))}
        if not toggle and not add:
            Gui.Selection.clearSelection()
        expanded = set()
        additions = {}
        if toggle:
            # A tree selection represents the whole object. Expand it before
            # toggling individual hits, retaining all the untouched geometry.
            show_seams = preferences.load().show_seams
            for obj, _ in hits:
                if (key(obj), "") not in existing or key(obj) in expanded:
                    continue
                expanded.add(key(obj))
                Gui.Selection.removeSelection(obj)
                omitted = {name for other, name in hits if key(other) == key(obj)}
                shape = obj.Shape
                seams = set() if show_seams else seam_indices(shape)
                hidden = visibility.hidden_faces(obj)
                hidden_edges, hidden_vertices = visibility.hidden_elements(shape, hidden)
                names = ["Face" + str(i) for i in range(1, len(shape.Faces) + 1)]
                names += ["Edge" + str(i) for i, edge in enumerate(shape.Edges, 1)
                          if i-1 not in seams]
                if not shape.Edges:
                    names += ["Vertex" + str(i) for i in range(1, len(shape.Vertexes) + 1)]
                blocked = omitted | {'Face%d' % i for i in hidden} | {'Edge%d' % i for i in hidden_edges} | {'Vertex%d' % i for i in hidden_vertices}
                for name in names:
                    if name not in blocked and obj.ViewObject.Visibility:
                        additions.setdefault(obj, []).append(name)
        for obj, name in hits:
            if key(obj) in expanded:
                continue
            if toggle and (key(obj), name) in existing:
                Gui.Selection.removeSelection(obj, name)
            elif not (toggle or add) or (key(obj), "") not in existing:
                additions.setdefault(obj, []).append(name)
        for obj, names in additions.items():
            if '' in names:
                Gui.Selection.addSelection(obj)  # The whole object.
            names = [name for name in names if name]
            if names:
                Gui.Selection.addSelection(obj, names, False)
        Gui.Selection.clearPreselection()

    def double_click(self, widget, event):
        """Grow the double-clicked face or edge: a hole, loop, flat region or smooth surface."""
        from ...inspection import smart_select
        self.cancel()
        self.doc, self.view = App.ActiveDocument, Gui.activeDocument().activeView()
        try:
            pos = self.viewport_position(widget, event)
            hit = pick(self.view, self.doc, pos, face_only=self.filter == 'Faces', prefer_boundary=self.filter != 'Faces')
            if not hit or not hasattr(hit[0], 'Shape') or not hit[3].startswith(('Face', 'Edge')) or self.filter in ('Objects', 'Vertices'):
                return False
            names, kind = smart_select.expand(hit[0].Shape, hit[3], view_direction=self.view.getViewDirection())
            hits = self.filtered([(hit[0], name) for name in visible_names(hit[0], names)])
            self.apply(hits, event.modifiers())
            self.controller.message('Selected %s · %d %s' % (
                {'hole': 'a hole or cylinder wall', 'loop': 'an edge loop', 'flat': 'a flat region',
                 'smooth': 'a smooth surface'}[kind], len(hits), 'element' if len(hits) == 1 else 'elements'))
        except Exception as error:
            self.controller.report(error)
        # The double-click's release belongs to this gesture.
        self.ignore_release = widget
        return True

    def handle_event(self, watched, event):
        if self.replaying:
            return False
        kind = event.type()
        if (self.widget is not None and kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride)
                and event.key() == QtCore.Qt.Key_Escape):
            if kind == QtCore.QEvent.KeyPress:
                self.cancel()
                self.controller.message("Selection cancelled")
            event.accept()
            return True
        if kind == QtCore.QEvent.MouseButtonRelease and watched == self.ignore_release:
            if event.button() == QtCore.Qt.LeftButton:
                self.ignore_release = None
                return True
        if self.widget is not None:
            if kind in (QtCore.QEvent.WindowDeactivate, QtCore.QEvent.Wheel):
                self.cancel()
                return False
            self.check_context()
        if (kind == QtCore.QEvent.MouseButtonDblClick and event.button() == QtCore.Qt.LeftButton
                and not self.controller.tool and self.is_viewport(watched) and App.ActiveDocument is not None):
            return self.double_click(watched, event)
        mouse_types = (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove)
        if kind not in mouse_types or not self.is_viewport(watched):
            return False
        if self.controller.tool:
            return False
        if kind == QtCore.QEvent.MouseButtonPress:
            if event.button() != QtCore.Qt.LeftButton or event.modifiers() & QtCore.Qt.AltModifier:
                if self.widget == watched and event.button() != QtCore.Qt.LeftButton:
                    # A left-then-middle orbit gesture still needs its initial
                    # press. Let the navigation style handle the chord.
                    self.replay(watched, (self.press,))
                self.cancel()
                self.ignore_release = None
                return False
            if event.buttons() != QtCore.Qt.LeftButton:
                return False
            if App.ActiveDocument is None:
                return False
            self.cancel()
            self.ignore_release = None
            self.doc, self.view = App.ActiveDocument, Gui.activeDocument().activeView()
            self.widget = watched
            self.start = event.localPos()
            self.press = (kind, self.start, event.globalPos(), event.button(), event.buttons(), event.modifiers())
            self.undo_count = self.doc.UndoCount
            self.timer.start(100)
            watched.setFocus()
            return True
        if self.widget != watched:
            return False
        end = event.localPos()
        if kind == QtCore.QEvent.MouseMove:
            if not event.buttons() & QtCore.Qt.LeftButton:
                self.cancel()
                return False
            if self.overlay is None and (end - self.start).manhattanLength() < 6:
                return True
            if self.overlay is None:
                self.overlay = SelectionBox(self.view, watched)
            self.overlay.move_box(self.start, end)
            self.controller.message("Crossing: inside or touching" if self.overlay.crossing else "Window: fully inside")
            return True
        if event.button() != QtCore.Qt.LeftButton:
            return False
        try:
            if self.overlay is None:
                self.native_click(watched, event)
            else:
                # Coin uses bottom-left physical pixels; Qt uses top-left
                # logical pixels. Derive both scale factors for Retina too.
                width, height = self.view.getSize()
                def position(p):
                    return (p.x() * width / watched.width(), (watched.height() - p.y()) * height / watched.height())
                hits = self.filtered(box_selection(self.doc, self.view, position(self.start), position(end),
                                                   preferences.load().show_seams, vertices=self.filter == 'Vertices'))
                self.apply(hits, event.modifiers())
                self.controller.message("Selected %d faces/edges · Shift adds · Ctrl/⌘ toggles" % len(hits))
        except Exception as error:
            self.controller.report(error)
        finally:
            self.cancel()
            self.ignore_release = None
        return True
