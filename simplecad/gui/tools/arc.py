"""Three-click arc interaction; no document changes until the final click."""
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
        return g.V(0,0,1) if self.c.surface_frame is not None else self.c.plane.normal

    def advance(self):
        c = self.c
        if (c.point - c.anchor).Length < g.EPS:
            raise ValueError('Choose a different point to set the radius or second endpoint.')
        self.second = g.V(c.point)
        self.second_local = g.V(c.surface_point) if c.surface_frame is not None else None
        c.snapper.points = [(p, label) for p, label in c.snapper.points
                            if (p - self.second).Length >= g.EPS]
        c.controls.value.clear()
        c.focus_view()
        c.message('Click arc end · Move around the center to choose sweep · Tab for signed degrees · Esc cancels'
                  if c.tool == 'Arc' else 'Click to set bulge · Tab for signed bulge in mm · Esc cancels')
        self.preview()

    def update(self):
        c = self.c
        if self.second is None:
            return
        if c.tool == 'Arc':
            radial, pointer = self.endpoint-self.anchor, self.pointer-self.anchor
            if pointer.Length < g.EPS:
                return
            principal = math.degrees(math.atan2(self.normal.dot(radial.cross(pointer)), radial.dot(pointer)))
            step = (principal - self.previous + 180) % 360 - 180
            self.angle = max(-359.999, min(359.999, self.angle + step))
            self.previous = principal
        else:
            anchor, second, point = self.anchor, self.endpoint, self.pointer
            left = self.normal.cross(g.unit(second-anchor))
            self.bulge = (point-(anchor+second)*.5).dot(left)
        self.build()

    def build(self):
        c = self.c
        self.curve = None
        # A straight/zero preview is expected while choosing the final point.
        if c.tool == 'Arc' and abs(self.angle) > 1e-5:
            self.curve = arcs.centered(self.anchor, self.endpoint, self.normal, self.angle)
        elif c.tool == 'Arc2Point' and abs(self.bulge) >= g.EPS:
            self.curve = arcs.two_point(self.anchor, self.endpoint, self.normal, self.bulge)

    def edge(self):
        if self.curve is None:
            raise ValueError('Choose a nonzero sweep or bulge to finish the arc.')
        edge = self.curve.edge()
        return self.c.surface_frame.edge(edge) if self.c.surface_frame is not None else edge

    def numeric(self, text):
        c = self.c
        if self.second is None:
            length = g.parse_length(text)
            if length < g.EPS:
                raise ValueError('Enter a positive radius or endpoint distance.')
            anchor, point = self.anchor, self.pointer
            direction = point-anchor
            axis = g.V(1,0,0) if c.surface_frame is not None else c.plane.u
            point = anchor+(g.unit(direction) if direction.Length >= g.EPS else axis)*length
            if c.surface_frame is not None:
                c.surface_point = point
            c.point = self.world(point)
            self.advance()
            return False
        if c.tool == 'Arc':
            angle = rotation.parse_angle(text)
            # Validate before replacing the last usable preview.
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
            label = 'Radius' if c.tool == 'Arc' else 'Endpoint distance'
            c.controls.value.setPlaceholderText('%s %.2f mm%s' % (label, (point-anchor).Length,
                                                                 ' on surface' if c.surface_frame else ''))
        else:
            lines = [self.curve.points()] if self.curve else [[anchor, second]]
            if c.tool == 'Arc':
                point = self.curve.point(1) if self.curve else second
                lines += [[second, anchor, point]]
                c.controls.value.setPlaceholderText('Sweep %.2f deg' % self.angle)
            else:
                left = self.normal.cross(g.unit(second-anchor))
                mid = (anchor+second)*.5
                point = mid + left * self.bulge
                lines += [[anchor, second], [mid, point]]
                c.controls.value.setPlaceholderText('Bulge %.2f mm' % self.bulge)
            # The constrained point may differ from the pointer's snap target.
            if snap and (snap.point - self.world(point)).Length > g.EPS:
                snap = None
                c.controls.label.setText('Arc sweep' if c.tool == 'Arc' else 'Arc bulge')
        if c.surface_frame is not None:
            lines = [c.surface_frame.points(line) for line in lines]
            point = self.world(point)
        c.preview.update(lines, point, center=center, center_snapped=c.hint_captured(snap, center),
                         midpoint=midpoint, midpoint_snapped=c.hint_captured(snap, midpoint))
