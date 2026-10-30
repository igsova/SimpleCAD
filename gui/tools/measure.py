"""测量：拾取一个或两个顶点、边、面或孔，并读取测量结果。

测量过程绝不修改文档内容。结果会显示在小型浮动面板以及 3D 视图的尺寸标注中；
点击“放置标注”可在继续编辑建模时将该尺寸常驻保留在视图中，直到点击“清除已放置标注”。
"""
import FreeCADGui as Gui
import Part
from pivy import coin
from ...core import geometry as geo
from ...inspection import measuring
from ..previews.overlay import label_font, outline
from ..snapping import pick, ray, screen
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel

DIMENSION = (1.0, 0.55, 0.12)
HIGHLIGHT = (0.25, 0.72, 1.0)
VERTEX_REACH = 12  # 像素范围；当光标离顶点在该距离内时优先拾取顶点

_kept = []  # 工具结束后常驻显示在视图中的 (view, Overlay) 列表


class Overlay:
    """在模型上方绘制的不可拾取的目标轮廓线与尺寸标注。

    尺寸线两端带有箭头，当带偏移放置时会引出尺寸界线回连到被测点（类似于 SketchUp）。
    箭头与间隙大小根据屏幕像素计算，随视图缩放保持一致大小。
    """
    def __init__(self, view):
        self.view = view
        self.state = None
        self.sensor = None
        self.root = coin.SoSeparator()
        pick_style = coin.SoPickStyle()
        pick_style.style = coin.SoPickStyle.UNPICKABLE
        depth = coin.SoDepthBuffer()
        depth.function = coin.SoDepthBuffer.ALWAYS
        depth.write = False
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        for node in (pick_style, depth, light):
            self.root.addChild(node)
        self.groups = {}
        for name, rgb, width in (('outline', HIGHLIGHT, 2.5), ('dimension', DIMENSION, 2.0), ('extra', DIMENSION, 1.2)):
            group = coin.SoSeparator()
            color = coin.SoBaseColor()
            color.rgb = rgb
            style = coin.SoDrawStyle()
            style.lineWidth = width
            style.pointSize = 9
            if name == 'extra':
                style.linePattern = 0x0F0F
            coords, lines, dots = coin.SoCoordinate3(), coin.SoLineSet(), coin.SoPointSet()
            for node in (color, style, coords, lines, dots):
                group.addChild(node)
            self.root.addChild(group)
            self.groups[name] = (coords, lines, dots)
        layer = coin.SoSeparator()
        color = coin.SoBaseColor()
        color.rgb = DIMENSION
        self.position = coin.SoTranslation()
        self.text = coin.SoText2()
        self.text.justification = coin.SoText2.CENTER
        for node in (color, self.position, label_font(18), self.text):
            layer.addChild(node)
        self.root.addChild(layer)
        view.getSceneGraph().addChild(self.root)

    def lines(self, name, polylines, dots=0):
        coords, lines, points = self.groups[name]
        values = [tuple(p) for line in polylines for p in line]
        coords.point.setValues(0, len(values), values)
        coords.point.setNum(len(values))
        lines.numVertices.setValues(0, len(polylines), [len(line) for line in polylines])
        lines.numVertices.setNum(len(polylines))
        points.numPoints = dots

    def pixel(self, point):
        """当前摄像机视角下，在指定空间点处一个屏幕像素对应的模型世界长度。"""
        try:
            plane = geo.Plane.from_normal(point, self.view.getViewDirection())
            x, y = screen(self.view, point)
            return max((plane.intersect(*ray(self.view, (x + 1, y))) - plane.intersect(*ray(self.view, (x, y)))).Length,
                       geo.EPS)
        except (AttributeError, ValueError, TypeError, RuntimeError, ZeroDivisionError):
            return .05

    def side(self, point, direction):
        """视图中垂直于线段且在屏幕上朝上的单位方向向量。"""
        try:
            across = self.view.getViewDirection().cross(direction)
            if across.Length < geo.EPS:
                return None
            across = geo.unit(across)
            if screen(self.view, point + across)[1] < screen(self.view, point)[1]:
                across = across * -1
            return across
        except (AttributeError, ValueError, TypeError, RuntimeError):
            return None

    def dimension(self, line, offset):
        """计算尺寸标注折线及标签文字的放置位置。"""
        a, b = line
        A, B = a + offset, b + offset
        middle = (A + B) * .5
        pixel = self.pixel(middle)
        if (B - A).Length <= pixel:
            return [], A
        along = geo.unit(B - A)
        if offset.Length > pixel * 2:
            across = geo.unit(offset)
        else:
            across = self.side(middle, along) or geo.Plane.from_normal(A, along).u
        polylines = [[A, B]]
        if offset.Length > pixel * 2:
            # 尺寸界线从被测点稍远处引出，并略微超出尺寸线
            for point, end in ((a, A), (b, B)):
                polylines.append([point + across * (pixel * 4), end + across * (pixel * 6)])
        size = pixel * 11
        if (B - A).Length > size * 2.5:
            for tip, inward in ((A, along), (B, along * -1)):
                polylines.append([tip + inward * size + across * (size * .35), tip, tip + inward * size - across * (size * .35)])
        return polylines, middle + across * (pixel * 12)

    def show(self, targets, measurement, offset=None):
        self.state = (targets, measurement, offset)
        self.lines('outline', [line for target in targets for line in target.outline])
        line = measurement.line if measurement is not None else None
        polylines, at = self.dimension(line, offset or geo.V()) if line else ([], targets[0].point if targets else None)
        self.lines('dimension', polylines)
        self.lines('extra', [list(pair) for pair in (measurement.extra if measurement else ())])
        if at is not None:
            self.position.translation = tuple(at)
        self.text.string = measurement.label if measurement is not None and polylines else ''
        self.follow_camera()
        self.view.redraw()

    def follow_camera(self):
        """视图缩放或旋转时触发重绘，使标注箭头和间隙保持屏幕像素大小。"""
        if self.sensor is not None:
            return
        try:
            camera = self.view.getCameraNode()
        except AttributeError:
            return
        self.sensor = coin.SoNodeSensor(lambda *unused: self.state and self.show(*self.state), None)
        self.sensor.attach(camera)

    def close(self):
        if self.sensor is not None:
            self.sensor.detach()
            self.sensor = None
        try:
            self.view.getSceneGraph().removeChild(self.root)
            self.view.redraw()
        except (RuntimeError, ReferenceError, AttributeError):
            pass


def clear_kept():
    while _kept:
        _kept.pop()[1].close()


class MeasureSession:
    def __init__(self, controller):
        self.c = controller
        self.targets, self.measurement = [], None
        self.placing = False
        self.overlay = Overlay(controller.view)
        self.dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self.dialog.setObjectName('SimpleCADMeasure')
        self.dialog.setWindowTitle('测量')
        self.dialog.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        layout = QtWidgets.QVBoxLayout(self.dialog)
        hint = QtWidgets.QLabel('点击顶点、边、面或孔。点击第二个元素测量二者之间的距离或夹角；'
                                '第三次点击将重新开始测量。点击“放置标注”可将尺寸线引出并保留在视图中。'
                                '模型中的几何内容绝不会被修改。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.picked = QtWidgets.QLabel()
        self.picked.setWordWrap(True)
        layout.addWidget(self.picked)
        self.table = QtWidgets.QTreeWidget()
        self.table.setObjectName('SimpleCADMeasureResults')
        self.table.setColumnCount(2)
        self.table.setHeaderLabels(['测量项', '数值'])
        self.table.setRootIsDecorated(False)
        self.table.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        layout.addWidget(self.table)
        buttons = QtWidgets.QHBoxLayout()
        self.place_button = QtWidgets.QPushButton('放置标注')
        self.place_button.setToolTip('移动光标引出尺寸线，然后点击以将其固定保留在视图中')
        self.clear_button = QtWidgets.QPushButton('清除已放置标注')
        copy = QtWidgets.QPushButton('复制结果')
        copy.setToolTip('将当前测量结果以文本形式复制到剪贴板')
        close = QtWidgets.QPushButton('关闭')
        for button in (self.place_button, self.clear_button, copy, close):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.place_button.clicked.connect(self.place)
        self.clear_button.clicked.connect(self.clear)
        copy.clicked.connect(self.copy)
        close.clicked.connect(controller.cancel)
        self.dialog.rejected.connect(controller.cancel)
        self.dialog.setMinimumWidth(380)
        self.refresh()
        anchor_panel(self.dialog).show()

    def target_at(self, pos):
        """获取光标下的几何元素；若附近有顶点则优先拾取（与绘图吸附一致）。"""
        snapper = self.c.snapper
        if snapper is not None:
            near = [(distance, point) for distance, point, label in snapper.screen_points(pos, VERTEX_REACH)
                    if label == 'Endpoint']
            if near:
                point = min(near, key=lambda item: item[0])[1]
                return measuring.Target('Vertex', 'Vertex', Part.Vertex(point), point, outline=[[point, point]])
        hit = pick(self.c.view, self.c.doc, pos, prefer_boundary=True)
        if not hit or not hasattr(hit[0], 'Shape'):
            return None
        return measuring.resolve(hit[0].Shape, hit[3], hit[2])

    def offset_at(self, pos):
        """计算光标将尺寸线从被测点引出的偏移距离。

        尺寸线在通过被测线段且面向视角的平面内移动，并与线段垂直。
        """
        a, b = self.measurement.line
        if (b - a).Length <= geo.EPS:
            return geo.V()
        along = geo.unit(b - a)
        view = self.c.view.getViewDirection()
        facing = view - along * view.dot(along)
        if facing.Length <= 1e-6:
            return geo.V()
        try:
            point = geo.Plane.from_normal(a, facing).intersect(*ray(self.c.view, pos))
        except ValueError:
            return geo.V()
        offset = point - a
        return offset - along * offset.dot(along)

    def hover(self, pos):
        if self.placing:
            self.c.preview.show_endpoint(None)
            self.c.preview.update()
            self.overlay.show(self.targets, self.measurement, self.offset_at(pos))
            return
        # 仅显示轮廓高亮：拟合分面孔等操作在点击后执行
        snapper = self.c.snapper
        vertex = None
        if snapper is not None:
            near = [(distance, point) for distance, point, label in snapper.screen_points(pos, VERTEX_REACH)
                    if label == 'Endpoint']
            vertex = min(near, key=lambda item: item[0])[1] if near else None
        self.c.preview.show_endpoint(vertex, vertex is not None)
        if vertex is not None:
            self.c.preview.update()
            return
        hit = pick(self.c.view, self.c.doc, pos, prefer_boundary=True)
        if hit and hit[1].ShapeType in ('Edge', 'Face'):
            self.c.preview.update(outline(hit[1]))
        else:
            self.c.preview.update()

    def click(self, pos):
        if self.placing:
            self.keep(self.offset_at(pos))
            return
        target = self.target_at(pos)
        if target is None:
            raise ValueError('请点击 CAD 对象的顶点、边、面或孔。')
        self.targets = [target] if len(self.targets) != 1 else self.targets + [target]
        self.measurement = (measuring.describe(self.targets[0]) if len(self.targets) == 1
                            else measuring.between(*self.targets))
        self.refresh()
        self.c.message(' · '.join(row.name + ' ' + row.text() for row in self.measurement.rows[:2]) +
                       (' · 点击第二个元素以测量两者之间的关系' if len(self.targets) == 1 else ''))

    def refresh(self):
        self.picked.setText('<b>1</b>: %s<br><b>2</b>: %s' % tuple(
            self.targets[i].label if i < len(self.targets) else '—' for i in range(2)))
        self.table.clear()
        for row in self.measurement.rows if self.measurement else ():
            QtWidgets.QTreeWidgetItem(self.table, [row.name, row.text()])
        self.place_button.setEnabled(self.measurement is not None and self.measurement.line is not None
                                     and not self.placing)
        self.clear_button.setEnabled(bool(_kept))
        self.overlay.show(self.targets, self.measurement)

    def place(self):
        if self.measurement is None or self.measurement.line is None:
            return
        self.placing = True
        self.refresh()
        self.c.focus_view()
        self.c.message('移动光标引出尺寸标注 · 点击以放置在视图中 · 按 Esc 退出放置')

    def keep(self, offset=None):
        """将尺寸标注保留在视图中；使用新的覆盖图层接管后续测量。"""
        if self.measurement is None:
            return
        self.overlay.show([], self.measurement, offset)
        _kept.append((self.c.view, self.overlay))
        self.overlay = Overlay(self.c.view)
        self.targets, self.measurement, self.placing = [], None, False
        self.refresh()
        self.c.message('标注已放置 · 编辑时将常驻保留在视图中 · 点击“清除已放置标注”可移除')

    def clear(self):
        clear_kept()
        self.refresh()

    def copy(self):
        if self.measurement is not None:
            QtWidgets.QApplication.clipboard().setText(measuring.summary(self.measurement, self.targets))
            self.c.message('测量结果已复制到剪贴板')

    def close(self):
        self.overlay.close()
        self.dialog.blockSignals(True)
        self.dialog.hide()
        self.dialog.deleteLater()