"""Cache source meshes and transform them while the angle slider moves."""
import math
from pivy import coin
from ...core import geometry as geo
from .shaded import RoundPreview, NativeMask, representation


def discretize_edge(edge, num_points=36):
    try:
        curve = getattr(edge, "Curve", None)
        if type(curve).__name__ in ("Line", "LineSegment", "GeomLine", "GeomLineSegment"):
            if hasattr(edge, "Vertexes") and len(edge.Vertexes) >= 2:
                return [v.Point for v in edge.Vertexes]
        if hasattr(edge, "discretize"):
            points = edge.discretize(Number=num_points)
            if len(points) >= 2:
                return points
    except Exception:
        pass
    try:
        if hasattr(edge, "discretize"):
            points = edge.discretize(Deflection=0.1)
            if len(points) >= 2:
                return points
    except Exception:
        pass
    if hasattr(edge, "Vertexes") and len(edge.Vertexes) >= 2:
        return [edge.Vertexes[0].Point, edge.Vertexes[-1].Point]
    return []


class RotatePreview(RoundPreview):
    def __init__(self, view, targets):
        super().__init__(view)
        self.targets = targets
        self.cached = []
        self.models_added = False
        self.guide = coin.SoSeparator()
        self.root.addChild(self.guide)
        try:
            for target in targets:
                obj, original = target[0], target[1]
                mode = getattr(target, "mode", "object")
                elements = getattr(target, "elements", ())
                root = coin.SoSeparator()
                transform = coin.SoTransform()
                root.addChild(transform)
                if mode in ("edge", "face") and elements:
                    edge_list = []
                    for name in elements:
                        try:
                            el = original.getElement(name)
                            if el.ShapeType == "Edge":
                                edge_list.append(el)
                            elif el.ShapeType == "Face":
                                edge_list.extend(el.Edges)
                        except Exception:
                            pass
                    if edge_list:
                        discretized = [discretize_edge(e) for e in edge_list]
                        discretized = [poly for poly in discretized if len(poly) >= 2]
                        if discretized:
                            coords = coin.SoCoordinate3()
                            pts = [pt for poly in discretized for pt in poly]
                            coords.point.setValues([tuple(p) for p in pts])
                            root.addChild(coords)
                            style = coin.SoDrawStyle()
                            style.lineWidth = 3.5
                            root.addChild(style)
                            color = coin.SoBaseColor()
                            color.rgb = (0.31, 0.84, 0.73)
                            root.addChild(color)
                            lines = coin.SoLineSet()
                            lines.numVertices.setValues([len(poly) for poly in discretized])
                            root.addChild(lines)
                else:
                    root.addChild(representation(obj, original))
                    if original.Vertexes and not original.Edges:
                        coords = coin.SoCoordinate3()
                        coords.point.setValues([tuple(vertex.Point) for vertex in original.Vertexes])
                        root.addChild(coords)
                        style = coin.SoDrawStyle(); style.pointSize = 6
                        root.addChild(style)
                        root.addChild(coin.SoPointSet())
                self.cached.append((root, transform))
        except Exception:
            self.close()
            raise

    def clear(self):
        super().clear()
        self.models_added = False
        self.guide.removeAllChildren()

    def show_rotation(self, frames, angle, axis_name):
        if not self.models_added:
            self.models_added = True
            for target, (root, _) in zip(self.targets, self.cached):
                mode = getattr(target, "mode", "object")
                if mode == "object":
                    self.masks.append(NativeMask(target[0]))
                self.models.addChild(root)
        for frame, (_, transform) in zip(frames, self.cached):
            placement = frame.transform(angle)
            transform.translation = tuple(placement.Base)
            transform.rotation = coin.SbRotation(*placement.Rotation.Q)
        self.guide.removeAllChildren()
        light = coin.SoLightModel(); light.model = coin.SoLightModel.BASE_COLOR
        self.guide.addChild(light)
        color = coin.SoBaseColor()
        color.rgb = {"X": (1, .3, .3), "Y": (.25, .9, .4), "Z": (.3, .6, 1)}.get(axis_name[-1], (1, .75, .2))
        self.guide.addChild(color)
        style = coin.SoDrawStyle(); style.lineWidth = 2.5
        self.guide.addChild(style)
        seen = set()
        for frame in frames:
            key = tuple(frame.center) + tuple(frame.axis)
            if key in seen:
                continue
            seen.add(key)
            plane = geo.Plane.from_normal(frame.center, frame.axis)
            radius = frame.size * .38
            circle = [frame.center + radius * (plane.u * math.cos(t * math.pi / 64) + plane.v * math.sin(t * math.pi / 64)) for t in range(129)]
            tip = frame.center + frame.axis * frame.size * .5
            # An arrow marks the positive axis; a moving spoke shows the angle.
            head = tip - frame.axis * frame.size * .08
            rotated_u = frame.transform(angle).Rotation.multVec(plane.u)
            points = (circle + [frame.center - frame.axis * frame.size * .5, tip,
                                head + plane.u * frame.size * .035, tip, head - plane.u * frame.size * .035,
                                frame.center, frame.center + rotated_u * radius])
            coords = coin.SoCoordinate3(); coords.point.setValues([tuple(p) for p in points])
            self.guide.addChild(coords)
            lines = coin.SoLineSet(); lines.numVertices.setValues([129, 2, 3, 2])
            self.guide.addChild(lines)
        self.view.redraw()
