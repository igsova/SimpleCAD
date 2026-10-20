"""Mouse handles for the two stretch planes, without document geometry/picking."""
import math
import numpy as np
import FreeCAD as App
from pivy import coin
from ...mesh import handles as geometry
from ..previews.overlay import AXIS_COLORS, label_font, pixel_ratio
from ..snapping import camera_state, pull_drag, ray, screen
from ..qt import QtCore


class PlaneHandles:
    def __init__(self, session):
        self.session, self.view = session, session.controller.view
        self.drag = None
        self.hover = self.widget = self.old_cursor = None
        self.projection_key = object()
        self.lines, self.markers = {}, {}

    def render(self):
        s = self.session
        root = s.preview.guide
        root.removeAllChildren()
        depth = coin.SoDepthBuffer(); depth.function = coin.SoDepthBuffer.ALWAYS; depth.write = False
        root.addChild(depth)
        light = coin.SoLightModel(); light.model = coin.SoLightModel.BASE_COLOR; root.addChild(light)
        self.lines, self.markers = {}, {}
        self.projection_key = object()

        def line(points, color, key=None):
            node = coin.SoSeparator()
            material = coin.SoBaseColor(); material.rgb = color; node.addChild(material)
            style = coin.SoDrawStyle(); style.lineWidth = (3.5 if key == self.hover else 1.6)*pixel_ratio()
            node.addChild(style)
            coords = coin.SoCoordinate3(); coords.point.setValues([tuple(p) for p in points]); node.addChild(coords)
            wire = coin.SoLineSet(); wire.numVertices.setValue(len(points)); node.addChild(wire)
            root.addChild(node)
            if key is not None:
                self.lines[key] = points

        def marker(point, color, text, key):
            node = coin.SoSeparator()
            material = coin.SoBaseColor(); material.rgb = color; node.addChild(material)
            style = coin.SoDrawStyle(); style.pointSize = (15 if key == self.hover else 11)*pixel_ratio()
            node.addChild(style)
            coords = coin.SoCoordinate3(); coords.point.setValue(tuple(point)); node.addChild(coords)
            dot = coin.SoPointSet(); dot.numPoints = 1; node.addChild(dot)
            position = coin.SoTranslation(); position.translation = tuple(point); node.addChild(position)
            node.addChild(label_font(12))
            label = coin.SoText2(); label.string = '  '+text; node.addChild(label)
            root.addChild(node)
            self.markers[key] = point

        rotating = s.mouse_mode.currentIndex() == 1
        normal, center = np.asarray(tuple(s.plane.normal)), np.asarray(tuple(s.plane.center))
        u, _ = geometry.basis(normal)
        for i, (level, color) in enumerate(((s.lower.value(), (.1,.7,1)), (s.upper.value(), (1,.65,.2)))):
            corners = s.plane.corners(level)
            key = None if rotating else ('plane', i)
            line(corners + corners[:1], color, key)
            if not rotating:
                point = center + normal*level + u*s.plane.size*.12*(1 if i else -1)
                marker(point, color, 'First plane' if i == 0 else 'Second plane', key)
        if rotating:
            _, axes = geometry.rotations(s.angles())
            for i, axis in enumerate(axes):
                key = ('rotate', i)
                points = geometry.ring(center, axis, s.plane.size*.28)
                color = AXIS_COLORS['XYZ'[i]]
                line(points, color, key)
                marker(points[9+12*i], color, 'Rotate '+'XYZ'[i], key)
        self.view.redraw()

    def projected(self):
        key = camera_state(self.view)
        if self.projection_key != key:
            self.screen_lines = {key: [screen(self.view, App.Vector(*map(float, p))) for p in line]
                                 for key, line in self.lines.items()}
            self.screen_markers = {key: screen(self.view, App.Vector(*map(float, p)))
                                   for key, p in self.markers.items()}
            self.projection_key = key
        return self.screen_lines, self.screen_markers

    def hit(self, pos):
        lines, markers = self.projected()
        candidates = [(np.linalg.norm(np.asarray(pos)-point), key) for key, point in markers.items()]
        candidates += [(geometry.nearest_segment(pos, line)[0], key) for key, line in lines.items()]
        distance, key = min(candidates, default=(math.inf, None))
        return key if distance <= 12*pixel_ratio() else None

    def position(self, widget, event):
        width, height = self.view.getSize(); point = event.localPos()
        return np.asarray((point.x()*width/widget.width(), height-point.y()*height/widget.height()))

    def begin(self, key, pos):
        s = self.session
        s.check()
        self.drag = dict(key=key, down=pos, levels=(s.lower.value(), s.upper.value()),
                         angles=s.angles(), normal=s.plane.normal, center=s.plane.center)
        if key[0] == 'plane':
            anchor = s.plane.center + s.plane.normal*self.drag['levels'][key[1]]
            self.drag.update(anchor=anchor, start=pull_drag(self.view, pos, anchor, s.plane.normal,
                                                          pos, s.plane.size)[0])
        else:
            _, axes = geometry.rotations(s.angles())
            axis = axes[key[1]]
            origin, direction = ray(self.view, pos)
            angle = geometry.plane_angle(tuple(origin), tuple(direction), tuple(s.plane.center), axis)
            _, fraction = geometry.nearest_segment(pos, self.projected()[0][key])
            theta = fraction*2*math.pi/72
            u, v = geometry.basis(axis); center = np.asarray(tuple(s.plane.center))
            def projected(t):
                point = center + s.plane.size*.28*(u*math.cos(t)+v*math.sin(t))
                return np.asarray(screen(self.view, App.Vector(*map(float, point))))
            tangent = (projected(theta+.05)-projected(theta-.05))/.1
            if np.linalg.norm(tangent) < 5:
                tangent = np.asarray((100*pixel_ratio(), 0.))
            self.drag.update(axis=axis, angle=angle, total=0., tangent=tangent)
        s.apply_button.setEnabled(False)

    def move(self, pos, shift=False):
        s, d = self.session, self.drag
        if d['key'][0] == 'plane':
            i = d['key'][1]
            amount = pull_drag(self.view, pos, d['anchor'], d['normal'], d['down'], s.plane.size)[0]-d['start']
            value = geometry.drag_level(d['levels'][i]+amount, s.lower.value(), s.upper.value(), i,
                                        (s.plane.lower, s.plane.upper))
            (s.lower, s.upper)[i].setValue(value)
        else:
            origin, direction = ray(self.view, pos)
            angle = geometry.plane_angle(tuple(origin), tuple(direction), tuple(d['center']), d['axis'])
            if d['angle'] is not None:
                if angle is None:
                    return
                d['total'] += geometry.angle_step(d['angle'], angle)
                d['angle'] = angle
                amount = d['total']
            else:
                amount = geometry.tangent_rotation(d['down'], pos, d['tangent'])
            degrees = math.degrees(amount)
            if shift:
                degrees = round(degrees/15)*15
            i = d['key'][1]
            s.rotation[i].setValue((d['angles'][i]+degrees+180) % 360 - 180)

    def finish(self, restore=False):
        d, self.drag = self.drag, None
        if d is None:
            return
        if self.widget is not None:
            self.widget.releaseMouse()
            self.widget.setCursor(QtCore.Qt.OpenHandCursor)
        if restore:
            for widget, value in zip([self.session.lower, self.session.upper] + self.session.rotation,
                                     list(d['levels']) + d['angles']):
                widget.blockSignals(True); widget.setValue(value); widget.blockSignals(False)
            self.session.orientation_changed()
        if not self.session.closed:
            self.session.update_preview()

    def reset_cursor(self):
        if self.widget is not None:
            try:
                self.widget.setCursor(self.old_cursor)
            except RuntimeError:
                pass
        self.widget = self.old_cursor = None

    def handle_event(self, watched, event):
        kind = event.type()
        if self.drag and kind == QtCore.QEvent.Wheel:
            return watched == self.widget
        if self.drag and kind == QtCore.QEvent.UngrabMouse and watched == self.widget:
            self.finish(restore=True)
            return False
        if kind not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove,
                        QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.Leave):
            return False
        if self.session.closed or not self.session.controller.selection.is_viewport(watched):
            return False
        if kind == QtCore.QEvent.Leave:
            if not self.drag:
                self.reset_cursor()
                self.hover = None; self.render()
            return False
        if not self.drag and event.modifiers() & (QtCore.Qt.AltModifier | QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier):
            return False
        pos = self.position(watched, event)
        if self.drag:
            if kind == QtCore.QEvent.MouseMove:
                self.move(pos, bool(event.modifiers() & QtCore.Qt.ShiftModifier))
            elif kind == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
                self.move(pos, bool(event.modifiers() & QtCore.Qt.ShiftModifier)); self.finish()
            return True
        key = self.hit(pos)
        if key != self.hover:
            self.hover = key; self.render()
        if key is None:
            self.reset_cursor()
            return False
        if self.widget is None:
            self.widget, self.old_cursor = watched, watched.cursor()
        watched.setCursor(QtCore.Qt.OpenHandCursor)
        if kind == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            self.begin(key, pos)
            watched.setFocus(QtCore.Qt.MouseFocusReason); watched.grabMouse()
            watched.setCursor(QtCore.Qt.ClosedHandCursor)
            return True
        return False

    def close(self):
        self.drag = None
        if self.widget is not None:
            try:
                self.widget.releaseMouse()
            except RuntimeError:
                pass
        self.reset_cursor()
