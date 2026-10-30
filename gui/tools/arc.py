"""三击圆弧交互逻辑；在完成最终点击前不会修改文档。"""
import math
from ...modeling import arcs, rotation
from ...core import geometry as g


class ArcInput:
    def __init__(self, controller):
        self.c = controller
        self.second = None
        self.second_local = None
        self.angle = 0.0
        self.previous = 0.0
        self.bulge = 0.0
        self.curve = None

    @property
    def anchor(self):
        return g.V() if self.c.surface_frame is not None else self.c.anchor

    @property
    def pointer(self):
        return self.c.surface_point if self.c.surface_frame is not None else self.c.point

    @property
    def endpoint(self):
        return self.second_local if self.c.surface_frame is not None else self.second

    def world(self, point):
        frame = self.c.surface_frame
        return frame.point(point) if frame is not None else point

    @property
    def normal(self):
        return g.V(0, 0, 1) if self.c.surface_frame is not None else self.c.plane.normal

    def advance(self):
        c = self.c
        if (c.point - c.anchor).Length < g.EPS:
            raise ValueError('请选择不同的点以设置半径或第二端点。')
        self.second = g.V(c.point)
        self.second_local = g.V(c.surface_point) if c.surface_frame is not None else None
        c.snapper.points = [(p, label) for p, label in c.snapper.points
                            if (p - self.second).Length >= g.EPS]
        c.controls.value.clear()
        c.focus_view()
        c.message('点击确定圆弧终点 · 绕中心移动调整扫掠角度 · 按 Tab 键输入精确角度 · 按 Esc 取消'
                  if c.tool == 'Arc' else '点击确定拱高 · 按 Tab 键输入精确拱高 (mm) · 按 Esc 取消')
        self.preview()

    def update(self):
        c = self.c
        if self.second is None:
            return
        if c.tool == 'Arc':
            radial, pointer = self.endpoint - self.anchor, self.pointer - self.anchor
            if pointer.Length < g.EPS:
                return
            principal = math.degrees(math.atan2(self.normal.dot(radial.cross(pointer)), radial.dot(pointer)))
            step = (principal - self.previous + 180) % 360 - 180
            self.angle = max(-359.999, min(359.999, self.angle + step))
            self.previous = principal
        else:
            anchor, second, point = self.anchor, self.endpoint, self.pointer
            left = self.normal.cross(g.unit(second - anchor))
            self.bulge = (point - (anchor + second) * .5).dot(left)
        self.build()

    def build(self):
        c = self.c
        self.curve = None
        # 选择最终点时，直线或零值预览属于正常情况
        if c.tool == 'Arc' and abs(self.angle) > 1e-5:
            self.curve = arcs.centered(self.anchor, self.endpoint, self.normal, self.angle)
        elif c.tool == 'Arc2Point' and abs(self.bulge) >= g.EPS:
            self.curve = arcs.two_point(self.anchor, self.endpoint, self.normal, self.bulge)

    def edge(self):
        if self.curve is None:
            raise ValueError('请选择非零的扫掠角度或拱高以完成圆弧绘制。')
        edge = self.curve.edge()
        return self.c.surface_frame.edge(edge) if self.c.surface_frame is not None else edge

    def numeric(self, text):
        c = self.c
        if self.second is None:
            length = g.parse_length(text)
            if length < g.EPS:
                raise ValueError('请输入大于零的半径或端点距离。')
            anchor, point = self.anchor, self.pointer
            direction = point - anchor
            axis = g.V(1, 0, 0) if c.surface_frame is not None else c.plane.u
            point = anchor + (g.unit(direction) if direction.Length >= g.EPS else axis) * length
            if c.surface_frame is not None:
                c.surface_point = point
            c.point = self.world(point)
            self.advance()
            return False
        if c.tool == 'Arc':
            angle = rotation.parse_angle(text)
            # 在替换最后一个可用预览之前先进行校验
            arcs.centered(self.anchor, self.endpoint, self.normal, angle)
            self.angle = angle
        else:
            bulge = g.parse_length(text)
            arcs.two_point(self.anchor, self.endpoint, self.normal, bulge)
            self.bulge = bulge
        self.build()
        return True

    def preview(self, snap=None, center=None, midpoint=None):
        c = self.c
        anchor, point, second = self.anchor, self.pointer, self.endpoint
        if self.second is None:
            lines = [[anchor, point]]
            label = '半径' if c.tool == 'Arc' else '端点距离'
            c.controls.value.setPlaceholderText('%s %.2f mm%s' % (label, (point - anchor).Length,
                                                                 ' (曲面上)' if c.surface_frame else ''))
        else:
            lines = [self.curve.points()] if self.curve else [[anchor, second]]
            if c.tool == 'Arc':
                point = self.curve.point(1) if self.curve else second
                lines += [[second, anchor, point]]
                c.controls.value.setPlaceholderText('扫掠角 %.2f°' % self.angle)
            else:
                left = self.normal.cross(g.unit(second - anchor))
                mid = (anchor + second) * .5
                point = mid + left * self.bulge
                lines += [[anchor, second], [mid, point]]
                c.controls.value.setPlaceholderText('拱高 %.2f mm' % self.bulge)
            # 约束点可能与光标捕捉的目标点不一致
            if snap and (snap.point - self.world(point)).Length > g.EPS:
                snap = None
                c.controls.label.setText('圆弧扫掠角' if c.tool == 'Arc' else '圆弧拱高')
        if c.surface_frame is not None:
            lines = [c.surface_frame.points(line) for line in lines]
            point = self.world(point)
        c.preview.update(lines, point, center=center, center_snapped=c.hint_captured(snap, center),
                         midpoint=midpoint, midpoint_snapped=c.hint_captured(snap, midpoint))