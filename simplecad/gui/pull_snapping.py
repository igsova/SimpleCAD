"""Cached height references for Push/Pull; no model booleans on mouse motion."""
from dataclasses import dataclass
import Part
from ..core.geometry import EPS, Plane, seam_indices
from .snapping import pick, screen, ray, camera_state
from ..document import visibility


@dataclass
class Reference:
    distance: float
    point: object
    label: str


class PullReferences:
    def __init__(self, doc, view, anchor, normal, face=None):
        if face is not None:
            # A picked anchor is single precision: on a face 300 mm up it is
            # about 2e-6 mm off the plane, and a level measured from it would
            # leave a step that thin. Measure from the face itself.
            anchor = Plane.from_face(face).project(anchor)
        self.doc, self.view, self.anchor, self.normal = doc, view, anchor, normal
        self.faces, self.edges = {}, []
        self.projection = None
        for obj in doc.Objects:
            if obj.TypeId != 'Part::Feature' or not obj.ViewObject.Visibility:
                continue
            if any(p.hasExtension('App::GeoFeatureGroupExtension') for p in obj.InList):
                continue
            shape = obj.Shape
            hidden = visibility.hidden_faces(obj)
            hidden_edges, _ = visibility.hidden_elements(shape, hidden)
            seams = seam_indices(shape)
            for i, face in enumerate(shape.Faces, 1):
                if i in hidden:
                    continue
                try:
                    plane = Plane.from_face(face)
                except ValueError:
                    continue
                distance = (plane.origin-anchor).dot(normal)
                if abs(plane.normal.dot(normal)) > 1-1e-7 and abs(distance) > EPS:
                    self.faces[(obj.Name, 'Face'+str(i))] = distance
            for i, edge in enumerate(shape.Edges, 1):
                if i in hidden_edges or edge.Degenerated or edge.Length <= EPS:
                    continue
                if i-1 in seams:
                    continue
                points = ([v.Point for v in edge.Vertexes] if isinstance(edge.Curve, Part.Line)
                          else edge.discretize(Number=25))
                if len(points) < 2:
                    continue
                levels = [(point-anchor).dot(normal) for point in points]
                if abs(levels[0]) > EPS and max(levels)-min(levels) < EPS:
                    self.edges.append((levels[0], points))

    def projected(self):
        """Each reference's screen polyline and bounds, kept while the camera is still.

        A drag moves only the pointer: projecting every reference point again
        on each update scales with the model's edges.
        """
        key = (camera_state(self.view), id(self.edges), len(self.edges))
        if self.projection is None or self.projection[0] != key:
            items = []
            for distance, points in self.edges:
                pixels = [screen(self.view, point) for point in points]
                xs, ys = [p[0] for p in pixels], [p[1] for p in pixels]
                items.append((distance, points, pixels, (min(xs), min(ys), max(xs), max(ys))))
            self.projection = (key, items)
        return self.projection[1]

    def snap(self, pos, radius):
        """Nearby constant-height edges take priority over a hovered flat face.

        The reference defines height along the extrusion normal, independent
        of where on the source face the drag began. Leaving a target releases it.
        """
        candidates = []
        origin, direction = ray(self.view, pos)
        direction.normalize()
        for distance, points, projected, (left, top, right, bottom) in self.projected():
            if not (left - radius <= pos[0] <= right + radius and top - radius <= pos[1] <= bottom + radius):
                continue
            for a, b, p, q in zip(projected, projected[1:], points, points[1:]):
                dx, dy = b[0]-a[0], b[1]-a[1]
                size = dx*dx+dy*dy
                t = max(0, min(1, ((pos[0]-a[0])*dx+(pos[1]-a[1])*dy)/size)) if size else 0
                pixels = ((a[0]+t*dx-pos[0])**2+(a[1]+t*dy-pos[1])**2)**.5
                if pixels <= radius:
                    point = p+(q-p)*t
                    depth = (point-origin).dot(direction)
                    candidates.append((pixels, depth, Reference(distance, point, 'Edge level')))
        if candidates:
            nearest = min(item[0] for item in candidates)
            # Prefer the frontmost of almost coincident projected references.
            ordered = sorted(candidates, key=lambda item:(item[0] > nearest+2, item[1], item[0]))
            hits = {}
            for _, _, reference in ordered:
                projected = screen(self.view, reference.point)
                pixel = tuple(int(value) for value in projected)
                if pixel not in hits:
                    hits[pixel] = pick(self.view, self.doc, pixel)
                hit = hits[pixel]
                if hit and abs((hit[2]-self.anchor).dot(self.normal)-reference.distance) > 1e-5:
                    _, sight = ray(self.view, projected)
                    sight.normalize()
                    # Don't attract to an edge behind another visible surface.
                    if (reference.point-hit[2]).dot(sight) > max(1e-5, reference.point.Length*1e-6):
                        continue
                return reference
        hit = pick(self.view, self.doc, pos, face_only=True)
        if hit:
            obj, _, point, name = hit
            distance = self.faces.get((obj.Name, name))
            if distance is not None:
                return Reference(distance, point, 'Face level')
        return None
