"""曲面建模工具对话框：表面绘制、曲面偏移、抽壳/加厚、拔模斜度、删除并缝合面、消除圆角、修补孔洞、展开曲面与阵列。

所有预览均为临时覆盖层；仅在对话框确认“应用”后才会通过 surface_ops 修改文档几何内容，且支持一步撤销。
"""
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part

from ...core import coincident
from ...modeling import patterns
from ..previews import overlay as preview
from ...surfaces import edit as se, offset as surface_offset, operations as so
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel

V = App.Vector
PREVIEW_EDGES = 400  # 边数超过该阈值的复杂对象预览为其包围盒外框


def selection():
    return [(item.Object, tuple(item.SubElementNames)) for item in Gui.Selection.getSelectionEx()
            if item.Object.Document == App.ActiveDocument]


def one_object(chosen, what):
    owners = list(dict.fromkeys(obj for obj, _ in chosen))
    if len(owners) != 1:
        raise ValueError('请在单个对象上选择%s。' % what)
    obj = owners[0]
    names = [name for o, names in chosen if o == obj for name in names]
    return obj, list(dict.fromkeys(names))


def picked_point(obj, names):
    """当选择记录了点击位置时，获取用户在选定面上点击的具体空间坐标。"""
    if not names:
        return None
    faces = Part.makeCompound([obj.Shape.getElement(name) for name in names])
    for item in Gui.Selection.getSelectionEx():
        if item.Object != obj:
            continue
        for point in getattr(item, 'PickedPoints', ()):
            if faces.distToShape(Part.Vertex(point))[0] < 1e-4:
                return V(point)
    return None


def plural(count, word, many=None):
    return '%d %s' % (count, word if count == 1 else (many or word))


def spin(value, low, high, suffix=' mm', decimals=3, name=None):
    box = QtWidgets.QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setValue(value)
    box.setSuffix(suffix)
    box.setKeyboardTracking(False)
    if name:
        box.setObjectName(name)
    return box


def count_spin(value, low, high, name=None):
    box = QtWidgets.QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    box.setKeyboardTracking(False)
    if name:
        box.setObjectName(name)
    return box


def boundary_normals(shape, indices):
    """沿面边缘采样的点集，每个点附带该处的面法线向量。"""
    lines = []
    for i in indices:
        face = shape.Faces[i]
        for edge in face.Edges:
            if edge.Degenerated:
                continue
            line = []
            for point in edge.discretize(max(4, min(48, int(edge.Length / 2)))):
                try:
                    line.append((point, face.normalAt(*face.Surface.parameter(point))))
                except (Part.OCCError, RuntimeError):
                    continue
            if len(line) >= 2:
                lines.append(line)
    return lines


def moved_lines(samples, distance):
    """沿法线移动的边缘线，每条线起始处带有一条侧壁引线。"""
    lines = []
    for line in samples:
        lines.append([p + n * distance for p, n in line])
        lines.append([line[0][0], line[0][0] + line[0][1] * distance])
    return lines


def face_lines(shape):
    return [line for face in shape.Faces for line in preview.edges(face)]


def box_lines(box):
    corners = [V(x, y, z) for x in (box.XMin, box.XMax) for y in (box.YMin, box.YMax) for z in (box.ZMin, box.ZMax)]
    pairs = ((0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7))
    return [[corners[a], corners[b]] for a, b in pairs]


class PreviewDialog(QtWidgets.QDialog):
    """在参数编辑时自动重绘临时预览的确认/取消对话框基类。"""
    title = 'SimpleCAD'

    def __init__(self, name, apply_text='应用', parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setWindowTitle(self.title)
        self.setObjectName(name)
        self.preview = preview.Preview(Gui.activeDocument().activeView())
        self.column = QtWidgets.QVBoxLayout(self)
        self.form = QtWidgets.QFormLayout()
        self.column.addLayout(self.form)
        self.info = QtWidgets.QLabel()
        self.info.setObjectName(name + 'Info')
        self.info.setWordWrap(True)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.redraw)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = self.buttons.button(QtWidgets.QDialogButtonBox.Ok)
        self.apply_button.setText(apply_text)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.setMinimumWidth(440)
        anchor_panel(self)

    def finish_layout(self, note=''):
        self.column.addWidget(self.info)
        if note:
            hint = QtWidgets.QLabel(note)
            hint.setWordWrap(True)
            self.column.addWidget(hint)
        self.column.addWidget(self.buttons)
        self.schedule()

    def watch(self, *widgets):
        for widget in widgets:
            for signal in ('valueChanged', 'currentIndexChanged', 'toggled', 'textChanged'):
                if hasattr(widget, signal):
                    getattr(widget, signal).connect(self.schedule)
                    break

    def schedule(self, *_):
        self.timer.start(150)

    def redraw(self):
        try:
            lines, text = self.lines()
            self.apply_button.setEnabled(True)
        except ValueError as error:
            lines, text = [], str(error)
            self.apply_button.setEnabled(False)
        self.info.setText(text)
        self.preview.update(polylines=lines)

    def lines(self):
        return [], ''

    def done(self, result):
        self.timer.stop()
        self.preview.close()
        super().done(result)


# --- 消除圆角 -----------------------------------------------------------------

class RoundsDialog(PreviewDialog):
    title = '消除圆角'

    def __init__(self, obj, names):
        super().__init__('SimpleCADRemoveRounds', '消除')
        self.obj, self.names = obj, names
        self.radius = spin(5.0, .001, 10000, name='SimpleCADRoundRadius')
        self.radius.setToolTip('半径小于或等于此数值的圆角将被移除。')
        self.form.addRow('最大搜索半径', self.radius)
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName('SimpleCADRoundKind')
        for key, text in (('any', '全部圆角 (内凹与外凸)'), ('convex', '仅外凸圆角'),
                          ('concave', '仅内凹圆角')):
            self.kind.addItem(text, key)
        self.form.addRow('圆角类型', self.kind)
        self.watch(self.radius, self.kind)
        self.found = []
        self.finish_layout('高亮显示的面将被移除，其相邻的面将延伸相交以恢复尖锐棱角。%s 支持一步撤销。' % (
            '仅在选中的面中搜索圆角。' if names else '在整个对象中搜索圆角。'))

    def values(self):
        return self.radius.value(), self.kind.currentData()

    def lines(self):
        self.found = so.rounds(self.obj, self.radius.value(), self.kind.currentData(), self.names)
        if not self.found:
            raise ValueError('未找到该半径范围内的圆角。')
        radii = [r['radius'] for r in self.found]
        faces = [self.obj.Shape.Faces[r['index']] for r in self.found]
        return face_lines(Part.makeCompound(faces)), '找到 %s，半径范围 %.3g 至 %.3g mm。' % (
            plural(len(self.found), '处圆角'), min(radii), max(radii))


# --- 表面绘制 / 压印 -------------------------------------------------------------

class ImprintDialog(PreviewDialog):
    title = '表面绘制 / 压印'
    SHAPES = (('rectangle', '矩形'), ('circle', '圆'), ('polygon', '正多边形'), ('text', '文字'))
    MODES = (('imprint', '分割为可独立选中的区域'), ('emboss', '凸起成型 (浮雕/凸印)'),
             ('deboss', '凹进切削 (挖槽/凹印)'))

    def __init__(self, obj, names, point):
        super().__init__('SimpleCADImprint', '绘制')
        self.obj, self.names, self.point = obj, names, point
        self.shape = QtWidgets.QComboBox()
        self.shape.setObjectName('SimpleCADImprintShape')
        for key, text in self.SHAPES:
            self.shape.addItem(text, key)
        self.form.addRow('绘制形状', self.shape)
        self.width = spin(10, .01, 10000, name='SimpleCADImprintWidth')
        self.height = spin(10, .01, 10000, name='SimpleCADImprintHeight')
        self.diameter = spin(10, .01, 10000, name='SimpleCADImprintDiameter')
        self.sides = count_spin(6, 3, 64, 'SimpleCADImprintSides')
        self.text = QtWidgets.QLineEdit('ABC')
        self.text.setObjectName('SimpleCADImprintText')
        self.size = spin(5, .1, 1000, name='SimpleCADImprintTextSize')
        self.font = se.default_font()
        self.font_button = QtWidgets.QPushButton(os.path.basename(self.font) or '选择字体…')
        self.font_button.clicked.connect(self.choose_font)
        self.rows = {}
        for key, label, widget in (('width', '宽度', self.width), ('height', '高度', self.height),
                                   ('diameter', '直径', self.diameter), ('sides', '边数', self.sides),
                                   ('text', '文字内容', self.text), ('size', '字号高度', self.size),
                                   ('font', '字体', self.font_button)):
            self.form.addRow(label, widget)
            self.rows[key] = widget
        self.angle = spin(0, -360, 360, '°', 2, 'SimpleCADImprintAngle')
        self.shift_x = spin(0, -10000, 10000, name='SimpleCADImprintShiftX')
        self.shift_y = spin(0, -10000, 10000, name='SimpleCADImprintShiftY')
        self.form.addRow('旋转角度', self.angle)
        self.form.addRow('横向偏移', self.shift_x)
        self.form.addRow('纵向偏移', self.shift_y)
        self.mode = QtWidgets.QComboBox()
        self.mode.setObjectName('SimpleCADImprintMode')
        for key, text in self.MODES:
            self.mode.addItem(text, key)
        self.form.addRow('成型效果', self.mode)
        self.depth = spin(1, .001, 1000, name='SimpleCADImprintDepth')
        self.form.addRow('凸起 / 凹进深度', self.depth)
        self.wrap = QtWidgets.QCheckBox('贴合曲面包裹 (保持图形原始尺寸)')
        self.wrap.setObjectName('SimpleCADImprintWrap')
        self.wrap.setToolTip('贴合包裹会像标签贴纸一样贴紧单个曲面，沿面法线方向凸起/凹进并保持尺寸长度；未勾选时图形将以平行投影投射到所选各面上。')
        self.wrap.setChecked(len(names) == 1 and not isinstance(obj.Shape.getElement(names[0]).Surface, Part.Plane))
        self.form.addRow('', self.wrap)
        self.flat_maps = {}
        self.shape.currentIndexChanged.connect(self.show_fields)
        self.mode.currentIndexChanged.connect(self.show_fields)
        self.watch(self.shape, self.width, self.height, self.diameter, self.sides, self.text, self.size,
                   self.angle, self.shift_x, self.shift_y, self.mode, self.depth, self.wrap)
        self.show_fields()
        self.finish_layout('图形以在面上点击的位置为中心，贴合包裹到该曲面或平行投影到所选面上。'
                           '分割后的独立区域可单独着色、推拉或删除。支持一步撤销。')

    def choose_font(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '选择文字字体', os.path.dirname(self.font),
                                                        '字体文件 (*.ttf *.otf *.ttc)')
        if path:
            self.font = path
            self.font_button.setText(os.path.basename(path))
            self.schedule()

    def show_fields(self, *_):
        kind = self.shape.currentData()
        shown = {'rectangle': ('width', 'height'), 'circle': ('diameter',), 'polygon': ('diameter', 'sides'),
                 'text': ('text', 'size', 'font')}[kind]
        for key, widget in self.rows.items():
            widget.setVisible(key in shown)
            self.form.labelForField(widget).setVisible(key in shown)
        raised = self.mode.currentData() != 'imprint'
        self.depth.setVisible(raised)
        self.form.labelForField(self.depth).setVisible(raised)

    def outline(self):
        return se.outline(self.shape.currentData(), width=self.width.value(), height=self.height.value(),
                          diameter=self.diameter.value(), sides=self.sides.value(), text=self.text.text(),
                          size=self.size.value(), font=self.font)

    def values(self):
        return dict(outline=self.outline(), point=self.point, angle=self.angle.value(),
                    shift=(self.shift_x.value(), self.shift_y.value()), mode=self.mode.currentData(),
                    depth=self.depth.value(), wrap=self.wrap.isChecked())

    def wrapped_lines(self):
        profile, (origin, normal, x) = so.wrapping(self.obj, self.names, self.outline(), self.point,
                                                   self.angle.value(), (self.shift_x.value(), self.shift_y.value()))
        shape = so.local(self.obj)
        index = min(so.indices(self.obj, self.names), key=lambda i: shape.Faces[i].distToShape(Part.Vertex(origin))[0])
        if index not in self.flat_maps:
            self.flat_maps[index] = se.FlatMap(shape.Faces[index])
        lines = se.wrap_lines(self.flat_maps[index], profile, origin, normal, x)
        placement = self.obj.Placement
        return ([[placement.multVec(p) for p in line] for line in lines],
                '图形以原始尺寸贴合包裹至 Face%d。' % (index + 1))

    def lines(self):
        if self.wrap.isChecked():
            return self.wrapped_lines()
        profile, direction = so.drawing(self.obj, self.names, self.outline(), self.point, self.angle.value(),
                                        (self.shift_x.value(), self.shift_y.value()))
        lines = preview.edges(so.world(profile, self.obj))
        try:
            projected = se.project(so.local(self.obj), so.indices(self.obj, self.names), profile, direction)
        except ValueError as error:
            raise ValueError(str(error)) from error
        lines += preview.edges(so.world(Part.makeCompound(projected), self.obj))
        text = '图形轮廓投影在面上，共分割为 %s。' % plural(len(projected), '段')
        try:
            loose = any(not Part.Wire(group).isClosed() for group in Part.sortEdges(projected))
        except (Part.OCCError, RuntimeError):
            loose = True
        if loose:
            text += ' 部分轮廓超出了所选面的范围；只有闭合部分才能成为独立区域。'
        return lines, text


# --- 曲面偏移 -------------------------------------------------------------------------

class OffsetDialog(PreviewDialog):
    title = '曲面偏移'

    def __init__(self, obj, names):
        super().__init__('SimpleCADOffsetFace', '偏移')
        self.obj, self.names = obj, names
        self.distance = spin(1, -10000, 10000, name='SimpleCADOffsetDistance')
        self.distance.setToolTip('正值沿法线向外移动面以增加材料；负值向内移动面以挖槽切削。')
        self.form.addRow('偏移距离', self.distance)
        self.watch(self.distance)
        self.samples = boundary_normals(obj.Shape, so.indices(obj, names))
        self.finish_layout('每个面沿自身的法线方向移动，类似于在曲面上执行推拉 (Push/Pull)。'
                           '侧壁沿法线垂直拉伸；相邻面不发生变形。支持一步撤销。')

    def lines(self):
        distance = self.distance.value()
        if abs(distance) < 1e-6:
            raise ValueError('请输入非零的偏移距离。')
        return moved_lines(self.samples, distance), '%s将%s移动 %.3g mm。' % (
            plural(len(self.names), '个面'),
            '向外（增加材料）' if distance > 0 else '向内（挖槽切削）', abs(distance))


# --- 抽壳与加厚 -------------------------------------------------------------------

class ShellDialog(PreviewDialog):
    SIDES = (('front', '正面 (沿面法线方向)'), ('back', '背面 (法线反方向)'),
             ('both', '向两侧对称延伸 (各占一半)'))

    def __init__(self, obj, names):
        self.surface = so.is_surface(obj)
        self.title = '加厚曲面' if self.surface else '实体抽壳'
        super().__init__('SimpleCADShell', '加厚' if self.surface else '抽壳')
        self.obj, self.names = obj, names
        self.thickness = spin(1, .001, 1000, name='SimpleCADShellThickness')
        self.form.addRow('厚度' if self.surface else '壁厚', self.thickness)
        self.side = QtWidgets.QComboBox()
        self.side.setObjectName('SimpleCADShellSide')
        for key, text in self.SIDES:
            self.side.addItem(text, key)
        if self.surface:
            self.form.addRow('加厚方向', self.side)
            self.samples = boundary_normals(obj.Shape, range(len(obj.Shape.Faces)))
        self.watch(self.thickness, self.side)
        self.finish_layout('将开敞曲面加厚为具有该壁厚的实体。支持一步撤销。' if self.surface else
                           '将实体向内掏空为指定壁厚的壳体。所选面将保留为开口；若未选择任何面则掏空为完全封闭的内部空腔。支持一步撤销。')

    def lines(self):
        thickness = self.thickness.value()
        if self.surface:
            side = self.side.currentData()
            distances = {'front': [thickness], 'back': [-thickness], 'both': [thickness / 2, -thickness / 2]}[side]
            lines = [line for d in distances for line in moved_lines(self.samples, d)]
            return lines, '曲面将加厚为 %.3g mm 壁厚的实体。' % thickness
        if not self.names:
            return [], '生成内部封闭空腔，壁厚 %.3g mm。' % thickness
        faces = Part.makeCompound([self.obj.Shape.getElement(name) for name in self.names])
        return face_lines(faces), '%s保留为开口，壁厚 %.3g mm。' % (plural(len(self.names), '个面'), thickness)


# --- 拔模斜度 -------------------------------------------------------------------------------

class DraftDialog(PreviewDialog):
    title = '拔模斜度'
    AXES = (('Z', '世界坐标系 Z 轴 (向上)'), ('X', '世界坐标系 X 轴'), ('Y', '世界坐标系 Y 轴'))

    def __init__(self, obj, names):
        super().__init__('SimpleCADDraft', '拔模')
        self.obj, self.names = obj, names
        self.angle = spin(3, .01, 89.9, '°', 2, 'SimpleCADDraftAngle')
        self.form.addRow('拔模角度', self.angle)
        self.axis = QtWidgets.QComboBox()
        self.axis.setObjectName('SimpleCADDraftAxis')
        for key, text in self.AXES:
            self.axis.addItem(text, key)
        self.form.addRow('脱模拔模方向', self.axis)
        self.hinge = QtWidgets.QComboBox()
        self.hinge.setObjectName('SimpleCADDraftHinge')
        self.hinge.addItem('在所选面的底部', 'bottom')
        self.hinge.addItem('在所选面的顶部', 'top')
        self.form.addRow('铰链基准面', self.hinge)
        self.narrower = QtWidgets.QComboBox()
        self.narrower.setObjectName('SimpleCADDraftNarrower')
        self.narrower.addItem('朝顶部逐渐收窄', 'top')
        self.narrower.addItem('朝底部逐渐收窄', 'bottom')
        self.form.addRow('收窄锥度', self.narrower)
        self.watch(self.angle, self.axis, self.hinge, self.narrower)
        self.finish_layout('侧壁面围绕与脱模方向垂直的铰链基准面倾斜，交叉处尺寸保持不变。“顶部”即为脱模方向。'
                           '仅支持平面与圆柱面。支持一步撤销。')

    def values(self):
        return dict(angle=self.angle.value(), axis=self.axis.currentData(), hinge=self.hinge.currentData(),
                    narrower=self.narrower.currentData())

    def lines(self):
        shape = self.obj.Shape
        chosen = so.indices(self.obj, self.names)
        axis = V(*{'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}[self.axis.currentData()])
        for i in chosen:
            face = shape.Faces[i]
            if not isinstance(face.Surface, (Part.Plane, Part.Cylinder, Part.Cone)):
                raise ValueError('拔模仅支持平面、圆柱面与圆锥面，不支持自由曲面。')
            if isinstance(face.Surface, Part.Plane) and abs(face.normalAt(0, 0).dot(axis)) > 1 - 1e-6:
                raise ValueError('垂直于脱模方向的顶面/底面无法拔模，请选择侧壁面。')
        height = surface_offset.hinge_height(shape, chosen, axis, self.hinge.currentData())
        box = Part.makeCompound([shape.Faces[i] for i in chosen]).BoundBox
        u = V(1, 0, 0) if abs(axis.x) < .9 else V(0, 1, 0)
        w = axis.cross(u)
        corners = [V(x, y, z) for x in (box.XMin, box.XMax) for y in (box.YMin, box.YMax) for z in (box.ZMin, box.ZMax)]
        us, ws = [c.dot(u) for c in corners], [c.dot(w) for c in corners]
        margin = .1 * max(box.DiagonalLength, 1)
        rim = [axis * height + u * a + w * b for a, b in ((min(us) - margin, min(ws) - margin),
                                                          (max(us) + margin, min(ws) - margin),
                                                          (max(us) + margin, max(ws) + margin),
                                                          (min(us) - margin, max(ws) + margin))]
        centre = axis * height + u * ((min(us) + max(us)) / 2) + w * ((min(ws) + max(ws)) / 2)
        arrow = [centre, centre + axis * (box.DiagonalLength / 3 or 5)]
        return [rim + rim[:1], arrow], '%s绕铰链面倾斜 %.3g°；零件朝%s逐渐收窄。' % (
            plural(len(chosen), '个面'), self.angle.value(),
            '顶部' if self.narrower.currentData() == 'top' else '底部')


# --- 修补孔洞 ------------------------------------------------------------------------

class FillDialog(PreviewDialog):
    title = '修补孔洞'

    def __init__(self, obj, edges):
        super().__init__('SimpleCADFillHole', '修补')
        self.obj, self.edges = obj, edges
        self.smooth = QtWidgets.QCheckBox('与相邻曲面平滑过渡缝合 (相切连续)')
        self.smooth.setObjectName('SimpleCADFillSmooth')
        self.smooth.setChecked(True)
        self.smooth.setToolTip('弯曲开口将使用与周边曲面相切的面片封闭；平整开口始终使用平面封闭。')
        self.column.addWidget(self.smooth)
        self.finish_layout('高亮显示的开口边缘将被曲面面片封闭。完全闭合且无开口的曲面将自动转化为实体。支持一步撤销。')

    def lines(self):
        loops = so.openings(self.obj)
        if self.edges:
            chosen = [self.obj.Shape.getElement(name) for name in self.edges]
            loops = [w for w in loops if any(e.isSame(c) or coincident.same(e, c) for e in w.Edges for c in chosen)]
        if not loops:
            raise ValueError('选中的边不在任何开敞孔洞的边缘上。' if self.edges
                             else '该对象没有需要修补的开敞孔洞。')
        return [line for wire in loops for line in preview.edges(wire)], '待修补 %s。' % plural(len(loops), '处开口')


# --- 阵列 ------------------------------------------------------------------------------

class PatternDialog(PreviewDialog):
    title = '阵列'

    def __init__(self, objects, path):
        super().__init__('SimpleCADPattern', '创建副本')
        self.objects, self.path = objects, path
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName('SimpleCADPatternKind')
        self.kind.addItem('沿 X、Y 和 Z 轴网格阵列', 'grid')
        self.kind.addItem('围绕轴线环形阵列', 'radial')
        if path is not None:
            self.kind.addItem('沿选定边缘路径阵列', 'path')
            self.kind.setCurrentIndex(2)
        self.form.addRow('阵列模式', self.kind)
        size = App.BoundBox()
        for obj in objects:
            size.add(obj.Shape.BoundBox)
        step = round(max(size.XLength, size.YLength, size.ZLength, 1) * 1.5, 1)
        self.counts = [count_spin(n, 1, 500, 'SimpleCADPatternCount' + a) for n, a in ((3, 'X'), (1, 'Y'), (1, 'Z'))]
        self.spacing = [spin(step, -100000, 100000, name='SimpleCADPatternSpacing' + a) for a in 'XYZ']
        self.grid_rows = []
        for axis, count, spacing in zip('XYZ', self.counts, self.spacing):
            row = QtWidgets.QWidget()
            line = QtWidgets.QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.addWidget(count)
            line.addWidget(QtWidgets.QLabel('间距'))
            line.addWidget(spacing)
            self.form.addRow('沿 %s 轴' % axis, row)
            self.grid_rows.append(row)
        self.count = count_spin(6, 2, 500, 'SimpleCADPatternCount')
        self.form.addRow('阵列数量', self.count)
        self.angle = spin(360, -360, 360, '°', 2, 'SimpleCADPatternAngle')
        self.form.addRow('总旋转角度', self.angle)
        self.axis = QtWidgets.QComboBox()
        self.axis.setObjectName('SimpleCADPatternAxis')
        for axis in 'XYZ':
            self.axis.addItem('世界 ' + axis + ' 轴', axis)
        self.axis.setCurrentIndex(2)
        self.form.addRow('旋转轴', self.axis)
        self.center = QtWidgets.QComboBox()
        self.center.setObjectName('SimpleCADPatternCenter')
        self.center.addItem('世界原点 (0, 0, 0)', 'origin')
        self.center.addItem('所选内容中心', 'selection')
        self.form.addRow('旋转中心点', self.center)
        self.align = QtWidgets.QCheckBox('使副本沿路径切线随动旋转')
        self.align.setObjectName('SimpleCADPatternAlign')
        self.align.setChecked(True)
        self.form.addRow('', self.align)
        self.kind.currentIndexChanged.connect(self.show_fields)
        self.watch(self.kind, *self.counts, *self.spacing, self.count, self.angle, self.axis, self.center, self.align)
        self.show_fields()
        self.outlines = []
        for obj in objects:
            shape = obj.Shape
            self.outlines += box_lines(shape.BoundBox) if len(shape.Edges) > PREVIEW_EDGES else preview.edges(shape)
        self.finish_layout('保留原始对象；每个生成的副本均为独立对象并继承原对象颜色。'
                           '数量包含原始对象在内。支持一步撤销。')

    def show_fields(self, *_):
        kind = self.kind.currentData()
        for widget in self.grid_rows:
            widget.setVisible(kind == 'grid')
            self.form.labelForField(widget).setVisible(kind == 'grid')
        for widget, kinds in ((self.count, ('radial', 'path')), (self.angle, ('radial',)), (self.axis, ('radial',)),
                              (self.center, ('radial',)), (self.align, ('path',))):
            widget.setVisible(kind in kinds)
            label = self.form.labelForField(widget)
            if label is not None:
                label.setVisible(kind in kinds)

    def placements(self):
        kind = self.kind.currentData()
        axis = {'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}[self.axis.currentData()]
        center = (0, 0, 0) if self.center.currentData() == 'origin' else None
        return so.placements(kind, self.objects, path=self.path, count=self.count.value(),
                             counts=[c.value() for c in self.counts], spacing=[s.value() for s in self.spacing],
                             axis=axis, center=center, angle=self.angle.value(), align=self.align.isChecked())

    def lines(self):
        placements = self.placements()
        if len(placements) * len(self.objects) > patterns.LIMIT:
            raise ValueError('阵列单次最多可生成 %d 个副本。' % patterns.LIMIT)
        lines = [[p.multVec(point) for point in line] for p in placements for line in self.outlines]
        return lines, '将生成 %s。' % plural(len(placements) * len(self.objects), '个副本')


# --- 工具调用入口 ---------------------------------------------------------------------------

def run(controller, tool):
    chosen = selection()
    if tool == 'HealFaces':
        obj, names = one_object(chosen, '要移除的面')
        report = so.heal_faces(obj, names)
        Gui.Selection.clearSelection()
        controller.message('已移除并缝合 %s%s · 面数 %d → %d · 可按 Ctrl+Z / ⌘Z 撤销' % (
            plural(report['removed'], '个面'),
            ' · %d 个面缝合失败已保留' % report['failed'] if report['failed'] else '',
            report['faces_before'], report['faces_after']))
    elif tool == 'RemoveRounds':
        obj, names = one_object(chosen, '实体或其部分面')
        dialog = RoundsDialog(obj, [n for n in names if n.startswith('Face')])
        if not dialog.exec():
            controller.message('已取消消除圆角')
            return
        radius, kind = dialog.values()
        report = so.remove_rounds(obj, radius, kind, dialog.names)
        Gui.Selection.clearSelection()
        controller.message('已消除 %s%s · 可按 Ctrl+Z / ⌘Z 撤销' % (
            plural(report['removed'], '处圆角'),
            ' · %d 处圆角无法消除已保留' % report['failed'] if report['failed'] else ''))
    elif tool == 'Imprint':
        obj, names = one_object(chosen, '要绘制的目标面')
        faces = [n for n in names if n.startswith('Face')]
        dialog = ImprintDialog(obj, faces, picked_point(obj, faces))
        if not dialog.exec():
            controller.message('已取消表面绘制')
            return
        values = dialog.values()
        report = so.imprint(obj, dialog.names, **values)
        Gui.Selection.clearSelection()
        if report['regions']:
            Gui.Selection.addSelection(obj, report['regions'])
        controller.message({'imprint': '已绘制在表面上 · 已选中 %s 便于着色、推拉或删除'
                            % plural(len(report['regions']), '个区域'),
                            'emboss': '表面图形已凸起 %.3g mm' % values['depth'],
                            'deboss': '表面图形已凹进 %.3g mm' % values['depth']}[values['mode']]
                           + ' · 可按 Ctrl+Z / ⌘Z 撤销')
    elif tool == 'OffsetFace':
        obj, names = one_object(chosen, '要偏移的面')
        dialog = OffsetDialog(obj, [n for n in names if n.startswith('Face')])
        if not dialog.exec():
            controller.message('已取消曲面偏移')
            return
        distance = dialog.distance.value()
        report = so.offset_faces(obj, dialog.names, distance)
        Gui.Selection.clearSelection()
        controller.message('%s已向%s移动 %.3g mm · 可按 Ctrl+Z / ⌘Z 撤销' % (
            plural(report['faces'], '个面'), '外' if distance > 0 else '内', abs(distance)))
    elif tool == 'Shell':
        obj, names = one_object(chosen, '零件实体或要留空的开口面')
        dialog = ShellDialog(obj, [n for n in names if n.startswith('Face')])
        if not dialog.exec():
            controller.message('已取消%s' % dialog.title)
            return
        thickness = dialog.thickness.value()
        if dialog.surface:
            so.thicken(obj, thickness, dialog.side.currentData())
            message = '已加厚为 %.3g mm 壁厚的实体' % thickness
        else:
            report = so.shell(obj, dialog.names, thickness)
            message = '已掏空为 %.3g mm 壁厚的壳体%s' % (
                thickness, ' · %s留空' % plural(report['open_faces'], '个面') if report['open_faces'] else '')
        Gui.Selection.clearSelection()
        controller.message(message + ' · 可按 Ctrl+Z / ⌘Z 撤销')
    elif tool == 'Draft':
        obj, names = one_object(chosen, '要拔模的面')
        dialog = DraftDialog(obj, [n for n in names if n.startswith('Face')])
        if not dialog.exec():
            controller.message('已取消拔模')
            return
        values = dialog.values()
        report = so.draft(obj, dialog.names, **values)
        Gui.Selection.clearSelection()
        controller.message('%s已完成拔模倾斜 %.3g° · 可按 Ctrl+Z / ⌘Z 撤销' % (plural(report['faces'], '个面'), values['angle']))
    elif tool == 'FillHole':
        obj, names = one_object(chosen, '开敞曲面或开口边缘')
        dialog = FillDialog(obj, [n for n in names if n.startswith('Edge')])
        if not dialog.exec():
            controller.message('已取消修补孔洞')
            return
        report = so.fill_holes(obj, dialog.edges, dialog.smooth.isChecked())
        Gui.Selection.clearSelection()
        controller.message('已修补 %s%s%s · 可按 Ctrl+Z / ⌘Z 撤销' % (
            plural(report['filled'], '处开口'),
            '，其中 %d 处平滑过渡' % report['tangent'] if report['tangent'] else '',
            ' · 现已闭合成实体' if report['closed'] else ''))
    elif tool == 'Unwrap':
        obj, names = one_object(chosen, '单个面')
        faces = [n for n in names if n.startswith('Face')]
        if len(faces) != 1:
            raise ValueError('请选择单个要展开的曲面。')
        flat, report = so.unwrap(obj, faces[0])
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(flat)
        change = report['area_change'] * 100
        controller.message('已展平为 %.2f × %.2f mm 轮廓放置在零件旁%s · 可按 Ctrl+Z / ⌘Z 撤销' % (
            report['width'], report['height'],
            ' · 面积变化 %+.2f%%（双曲率曲面展平时会发生拉伸变形）' % change if abs(change) >= .05 else ''))
    elif tool == 'Pattern':
        objects = [obj for obj, names in chosen if not names]
        paths = [(obj, names) for obj, names in chosen if names]
        if not objects:
            raise ValueError('请选择要重复阵列的完整对象；可在另一个对象上加选一条边作为路径。')
        path = so.path_shape(paths) if paths else None
        dialog = PatternDialog(objects, path)
        if not dialog.exec():
            controller.message('已取消阵列')
            return
        copies = so.pattern(objects, dialog.placements())
        Gui.Selection.clearSelection()
        for copy in copies:
            Gui.Selection.addSelection(copy)
        controller.message('已生成 %s · 可按 Ctrl+Z / ⌘Z 撤销' % plural(len(copies), '个副本'))
    else:
        raise ValueError('未知的曲面工具。')
    controller.faces.refresh()