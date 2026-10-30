"""拾取面或边，向任一侧移动，然后点击确定或输入精确偏移距离。"""
import FreeCAD  # noqa: F401  在加载原生模块前先加载应用程序
import FreeCADGui as Gui
import Part
from ...core import geometry as g
from ...document import operations as ops, locking
from ...modeling.offsetting import Profile
from ..snapping import pick, ray
from ..previews.overlay import edges, outline
from ..qt import QtCore


class OffsetInput:
    def __init__(self, controller):
        self.c = controller; self.obj = None; self.planned = None; self.distance = 0.; self.side = -1
        self.timer = QtCore.QTimer(controller); self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)

    def close(self):
        self.timer.stop(); self.timer.deleteLater()

    def check(self):
        if self.obj is None: return
        try:
            if not self.obj.Shape.isSame(self.original): raise ValueError()
        except Exception as error:
            raise ValueError('原始对象已改变，请重新启动【偏移】。') from error

    def choose(self, obj, name, point):
        c = self.c; ops.editable(obj)
        source = obj.Shape.getElement(name)
        normal = None
        if source.ShapeType == 'Edge' and isinstance(source.Curve, Part.Line):
            mode = c.controls.plane.currentText()
            if mode not in ('Auto', '自动'): normal = g.Plane.named(mode).normal
            else:
                # 存在支撑平面时优先使用最直接面向视角的平面；独立直线则使用视角投影面
                adjacent = [f for f in obj.Shape.ancestorsOfType(source, Part.Face) if isinstance(f.Surface, Part.Plane)]
                if not adjacent: adjacent = [f for f in obj.Shape.Faces if isinstance(f.Surface, Part.Plane) and any(e.isSame(source) for e in f.Edges)]
                if adjacent:
                    face = max(adjacent, key=lambda f: abs(g.face_normal(f).dot(c.view.getViewDirection())))
                    normal = g.face_normal(face)
                else:
                    tangent = g.unit(source.valueAt(source.LastParameter) - source.valueAt(source.FirstParameter))
                    view = c.view.getViewDirection()
                    normal = view - tangent * view.dot(tangent)
                    if normal.Length < g.EPS: raise ValueError('请旋转视图视角，或在控制栏选择 XY/XZ/YZ 基准面以偏移此直线。')
        profile = Profile(source, normal)
        if profile.face: locking.require_unlocked(obj, [name])
        self.obj, self.name, self.original, self.profile = obj, name, obj.Shape, profile
        self.distance = 0.; self.planned = None; self.side = -1 if profile.face else 1
        c.anchor = point; c.plane = profile.plane
        Gui.Selection.clearSelection(); Gui.Selection.clearPreselection()
        c.preview.update(edges(source))
        c.controls.value.setPlaceholderText('偏移距离')
        c.message('向内 / 向外移动 · 点击以保留 · 按 Tab 键输入精确距离 (− 向内，+ 向外) · 按 Esc 取消'
                  if profile.face or isinstance(source.Curve, Part.Circle) else
                  '向任一侧移动 · 点击以保留 · 按 Tab 键输入精确距离 · 按 Esc 取消')

    def hover(self, pos):
        hit = pick(self.c.view, self.c.doc, pos, prefer_boundary=True)
        if hit and hit[1].ShapeType in ('Face', 'Edge'):
            self.c.preview.update(outline(hit[1]), hit[2])
        else: self.c.preview.update()
        return hit

    def click(self, pos):
        if self.obj is None:
            hit = self.hover(pos)
            if not hit or hit[1].ShapeType not in ('Face', 'Edge'): raise ValueError('请点击面或边（避开顶点）。')
            self.choose(hit[0], hit[3], hit[2]); return False
        self.motion(pos); self.refresh(raise_error=True)
        return True

    def motion(self, pos):
        if self.obj is None: self.hover(pos); return
        self.check()
        point = self.profile.plane.intersect(*ray(self.c.view, pos))
        self.distance = self.profile.distance_at(point)
        if abs(self.distance) > g.EPS: self.side = 1 if self.distance > 0 else -1
        if not self.timer.isActive(): self.timer.start(30)

    def refresh(self, raise_error=False):
        self.timer.stop(); self.planned = None
        try:
            self.check()
            if abs(self.distance) < g.EPS:
                self.c.preview.update(edges(self.profile.source))
                raise ValueError('请移离原始边界以设定偏移量。')
            self.planned = self.profile.offset(self.distance)
            self.c.preview.update(edges(self.planned))
            circular = isinstance(getattr(self.profile.source, 'Curve', None), Part.Circle)
            side = ('向外' if self.distance > 0 else '向内') if self.profile.face or circular else ('左侧' if self.distance > 0 else '右侧')
            self.c.controls.label.setText('%s偏移 %.3g mm' % (side, abs(self.distance)))
            self.c.controls.value.setPlaceholderText('%.3g mm · %s' % (abs(self.distance), side))
            return True
        except Exception as error:
            self.c.preview.update(edges(self.profile.source))
            self.c.controls.label.setText('偏移不可用')
            if raise_error: raise
            self.c.message(str(error) + ' · 减小偏移距离或按 Esc 取消')
            return False

    def numeric(self, text):
        distance = g.parse_length(text.strip().removeprefix('+'))
        # 无符号距离保持鼠标当前所在侧；带有显式符号时按符号确定侧向
        self.distance = distance if text.strip().startswith(('+', '-')) else abs(distance) * self.side
        self.refresh(raise_error=True)

    def commit(self):
        self.check()
        return ops.offset(self.obj, self.name, self.distance, self.profile.plane.normal)