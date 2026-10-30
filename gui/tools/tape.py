"""测量卷尺：从指定点开始测量并放置辅助线/参考点（类似于 SketchUp 的卷尺工具）。

从一条边或参考线引出时，卷尺向垂直方向测量并生成与其平行的参考辅助线；
从其他任意点引出时，卷尺测量到光标位置并生成参考点，同时留有虚线引线供绘图吸附。
输入精确距离可精准定位辅助线；输入 0 将在起点处生成一个无引线的参考点。
辅助线属于构造参考元素而非模型几何体：绘图可自动吸附到辅助线上，且模型本身绝不会被修改。
"""
from ...core import geometry as geo
from ...document import guides
from ..guide_view import GuideNodes


class TapeInput:
    def __init__(self, controller):
        self.c = controller
        self.along = None  # 测量的基准边或参考线的单位方向向量；从点测量时为 None
        self.end = None  # 放置辅助线/参考点的目标位置
        self.nodes = GuideNodes(pickable=False)
        controller.view.getSceneGraph().addChild(self.nodes.root)

    def begin(self, snap):
        """第一次点击：若从边或参考线引出，辅助线将与其保持平行。"""
        is_edge = snap.label in ('On edge', '在边上', '边上')
        is_guide = snap.label in ('On guide', '在参考线上', '参考线上')
        self.along = snap.direction if (is_edge or is_guide) else None
        source_name = '边' if is_edge else '参考线'
        self.c.message('从' + source_name + '向外移动 · 点击以放置平行辅助线 · 按 Tab 键输入精确距离 · 按 Esc 退出'
                       if self.along is not None else
                       '点击以测量并放置参考点 · 按 Tab 键输入精确距离 · 按 X/Y/Z 锁定坐标轴 · 按 Esc 退出')

    def offset(self, point):
        """从起点到光标的偏移；若从边引出，则仅保留与其垂直的分量。"""
        delta = point - self.c.anchor
        return delta if self.along is None else delta - self.along * delta.dot(self.along)

    def preview(self, snap):
        c = self.c
        self.end = c.anchor + self.offset(c.point)
        distance = (self.end - c.anchor).Length
        # 卷尺引线本身及其将生成的参考辅助线
        self.nodes.set([[c.anchor, self.end]] if distance > geo.EPS else [],
                       [(self.end, self.along)] if self.along is not None else [],
                       [self.end] if self.along is None else [])
        text = '%.2f mm' % distance
        c.preview.update([], c.point, axis=snap.axis if snap else '',
                         lengths=[([c.anchor, self.end], text)] if distance > geo.EPS else [])
        c.controls.value.setPlaceholderText(text)
        if snap is not None:
            c.controls.label.setText(snap.label + ' · ' + text)

    def numeric(self, text):
        """通过键盘输入的精确距离，沿光标方向或垂直于边引出。"""
        c = self.c
        distance = geo.parse_length(text)
        direction = self.offset(c.point)
        if direction.Length < geo.EPS:
            if self.along is not None:
                raise ValueError('请先将光标移至放置辅助线的一侧，然后再输入距离。')
            direction = c.axis if c.axis is not None else c.plane.u
        self.end = c.anchor + geo.unit(direction) * distance

    def commit(self):
        c = self.c
        guides.add(c.doc, self.end, self.along, c.anchor)
        distance = (self.end - c.anchor).Length
        # 准备下一次测量（下一次测量可以直接吸附到刚刚创建的辅助线上）
        from ..snapping import Snapper
        c.snapper = Snapper(c.doc, c.view)
        c.line_undo_count = c.doc.UndoCount
        c.anchor = c.point = c.axis = None
        self.along = self.end = None
        self.nodes.set()
        c.preview.update()
        c.controls.value.clear()
        c.controls.value.setPlaceholderText('距离')
        c.focus_view()
        c.message('已在 %.2f mm 处放置辅助线 · 点击可再次测量 · 按 Esc 退出 · 可按 Ctrl+Z / ⌘Z 撤销' % distance)

    def close(self):
        try:
            self.c.view.getSceneGraph().removeChild(self.nodes.root)
        except (AttributeError, RuntimeError, ReferenceError):
            pass