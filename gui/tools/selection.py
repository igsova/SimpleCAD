"""仅限视口的橡皮筋框选；普通单击操作仍转发至 FreeCAD 原生处理。"""
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
    """获取未被隐藏（未通过面可见性小眼睛隐藏）的元素名称。"""
    hidden = visibility.hidden_faces(obj)
    if not hidden:
        return list(names)
    edges, vertices = visibility.object_hidden_elements(obj, hidden)
    blocked = {'Face%d' % i for i in hidden} | {'Edge%d' % i for i in edges} | {'Vertex%d' % i for i in vertices}
    return [name for name in names if name not in blocked]


class SelectionBox:
    """不可点选的 Coin 视口覆盖层，兼容 macOS OpenGL/Retina 高分屏。"""
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
            return tuple(plane.intersect(*ray(self.view, (x * sx, height - y * sy))))

        left, right = sorted((start.x(), end.x()))
        top, bottom = sorted((start.y(), end.y()))
        self.coords.point.setValues([world(left, top), world(right, top), world(right, bottom), world(left, bottom), world(left, top)])
        self.color.rgb = (.16, .81, .57) if self.crossing else (.29, .69, 1.0)
        for index, style in enumerate(self.styles):
            style.lineWidth = (4 if index == 0 else 2) * sx
            style.linePattern = 0xF0F0 if self.crossing else 0xFFFF
        label = "交叉选择：相交或包含" if self.crossing else "窗口选择：完全包含"
        x, y = min(left, max(2, self.widget.width() - 240)), max(18, top - 8)
        for index, (position, text) in enumerate(zip(self.positions, self.texts)):
            position.translation = world(x + (1 - index), y + (1 - index))
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
        # All, Faces, Edges, Vertices 或 Objects：点击和拉框所选的目标类型
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
        # 仅拦截 3D 渲染窗口事件，绝不干扰模型树、文本框、滚动条、起始页等其他 Qt 面板
        if not isinstance(widget, QtWidgets.QWidget) or not widget.inherits("QOpenGLWidget"):
            return False
        parent = widget.parentWidget()
        while parent:
            if parent.metaObject().className() == "Gui::View3DInventorViewer":
                return True
            parent = parent.parentWidget()
        return False

    def viewport_position(self, widget, event):
        # Coin 使用左下角物理像素；Qt 使用左上角逻辑像素
        width, height = self.view.getSize()
        point = event.localPos()
        return point.x() * width / widget.width(), height - point.y() * height / widget.height()

    def filtered_pick(self, pos):
        """当前选择过滤器下的单击拾取结果，返回 (object, subelement) 对列表。"""
        if self.filter == 'Faces':
            hit = pick(self.view, self.doc, pos, face_only=True)
        else:
            hit = pick(self.view, self.doc, pos, prefer_boundary=True)
        if not hit:
            return []
        return self.filtered([(hit[0], hit[3])])

    def filtered(self, hits):
        """过滤器允许的拾取目标；Objects 模式选择完整对象。"""
        if self.filter == 'Objects':
            return list({(obj.Document.Name, obj.Name): (obj, '') for obj, _ in hits}.values())
        prefix = {'Faces': 'Face', 'Edges': 'Edge', 'Vertices': 'Vertex'}.get(self.filter)
        return [(obj, name) for obj, name in hits if prefix is None or name.startswith(prefix)]

    def native_click(self, widget, release):
        if self.filter != 'All' or any(visibility.hidden_faces(obj) for obj in self.doc.Objects if hasattr(obj, 'Shape')):
            # 退化的 Coin 边折线保留 EdgeN，但其端点仍可能出现在原始光线碰撞中。
            # 在为常规点击选择最前端可见碰撞前先跳过隐藏元素。
            # 选择过滤器也会在此处拾取，因此在 Edges 模式下点击边附近会选中该边，而不是被拒绝。
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
            # 树选择项代表整个对象。在切换单个选中项之前先将其展开，保留所有未触及的几何元素。
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
                          if i - 1 not in seams]
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
                Gui.Selection.addSelection(obj)  # 整个对象
            names = [name for name in names if name]
            if names:
                Gui.Selection.addSelection(obj, names, False)
        Gui.Selection.clearPreselection()

    def double_click(self, widget, event):
        """扩展双击的面或边：整孔、边缘环、共面平整区或相切光滑面。"""
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
            kind_text = {'hole': '整孔 / 圆柱面', 'loop': '边缘环', 'flat': '共面平整区', 'smooth': '相切光滑面'}[kind]
            self.controller.message('已选中 %s · 共 %d 个元素' % (kind_text, len(hits)))
        except Exception as error:
            self.controller.report(error)
        # 双击后的释放事件属于当前手势
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
                self.controller.message("已取消框选")
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
                    # 先左键再中键的视角旋转手势仍需要初始的按下事件。由导航模式处理复合操作。
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
            self.controller.message("交叉选择：相交或包含" if self.overlay.crossing else "窗口选择：完全包含")
            return True
        if event.button() != QtCore.Qt.LeftButton:
            return False
        try:
            if self.overlay is None:
                self.native_click(watched, event)
            else:
                # Coin 使用左下角物理像素；Qt 使用左上角逻辑像素。同时适配 Retina 缩放。
                width, height = self.view.getSize()

                def position(p):
                    return (p.x() * width / watched.width(), (watched.height() - p.y()) * height / watched.height())

                hits = self.filtered(box_selection(self.doc, self.view, position(self.start), position(end),
                                                   preferences.load().show_seams, vertices=self.filter == 'Vertices'))
                self.apply(hits, event.modifiers())
                self.controller.message("已选中 %d 个面/边 · Shift 增加选择 · Ctrl/⌘ 切换选择" % len(hits))
        except Exception as error:
            self.controller.report(error)
        finally:
            self.cancel()
            self.ignore_release = None
        return True