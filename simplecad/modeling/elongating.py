"""Planar elongation: stretch circular holes into ellipses or slots along any chosen direction."""
import math
import FreeCAD as App
import Part
from ..core import geometry as g
from ..core.geometry import V, Plane, EPS


def stretch_matrix(center, normal, direction, scale):
    """Affine matrix stretching points along direction centered at center."""
    u = g.unit(direction)
    n = g.unit(normal)
    v = n.cross(u).normalize()
    mat = App.Matrix()
    cols = []
    for basis in (V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)):
        cols.append(scale * basis.dot(u) * u + basis.dot(v) * v + basis.dot(n) * n)
    mat.A11, mat.A21, mat.A31 = cols[0].x, cols[0].y, cols[0].z
    mat.A12, mat.A22, mat.A32 = cols[1].x, cols[1].y, cols[1].z
    mat.A13, mat.A23, mat.A33 = cols[2].x, cols[2].y, cols[2].z
    offset = center - mat.multVec(center)
    mat.A14, mat.A24, mat.A34 = offset.x, offset.y, offset.z
    return mat


class ElongateProfile:
    def __init__(self, element, normal=None, point=None):
        self.source = element
        self.is_face = element.ShapeType == 'Face'
        self.is_circle = False
        self.is_cylinder = False
        self.cylinder_axis = None
        self.cylinder_height = None

        if self.is_face and isinstance(getattr(element, 'Surface', None), Part.Cylinder):
            cyl = element.Surface
            self.is_cylinder = True
            self.cylinder_axis = g.unit(cyl.Axis)
            self.radius = cyl.Radius
            self.center = element.CenterOfMass

            # Align to circular rim if present
            circular_ends = [e for e in element.Edges if isinstance(getattr(e, 'Curve', None), Part.Circle)]
            if circular_ends:
                if point is not None:
                    chosen_end = min(circular_ends, key=lambda e: (e.Curve.Center - point).Length)
                    self.center = chosen_end.Curve.Center
                elif normal is not None:
                    chosen_end = max(circular_ends, key=lambda e: (e.Curve.Center - element.CenterOfMass).dot(normal))
                    self.center = chosen_end.Curve.Center
                else:
                    self.center = circular_ends[0].Curve.Center

            ref_normal = normal if normal is not None else self.cylinder_axis
            self.plane = Plane.from_normal(self.center, ref_normal)
            bb = element.BoundBox
            self.cylinder_height = max(bb.XLength, bb.YLength, bb.ZLength)
            self.is_circle = True
        elif self.is_face and isinstance(getattr(element, 'Surface', None), Part.Plane):
            self.plane = Plane.from_face(element)
            self.center = element.CenterOfMass
            if len(element.Edges) == 1 and isinstance(getattr(element.Edges[0], 'Curve', None), Part.Circle):
                self.is_circle = True
                c = element.Edges[0].Curve
                self.center = c.Center
                self.radius = c.Radius
            else:
                self.radius = math.sqrt(max(element.Area, EPS) / math.pi)
        elif element.ShapeType == 'Edge' and isinstance(getattr(element, 'Curve', None), Part.Circle):
            self.is_circle = True
            c = element.Curve
            self.center = c.Center
            self.radius = c.Radius
            plane_normal = normal if normal is not None else c.Axis
            self.plane = Plane.from_normal(self.center, plane_normal)
        else:
            raise ValueError('Elongate supports circular edges, cylindrical holes, and planar faces.')

    def direction_at(self, point):
        """Returns unit direction vector and distance from center on the plane."""
        proj = self.plane.project(point)
        delta = proj - self.center
        dist = delta.Length
        if dist < EPS:
            u = getattr(self.plane, 'u', V(1, 0, 0))
            return g.unit(u), 0.0
        return g.unit(delta), dist

    def elongate(self, distance, direction, mode='ellipse', symmetric=True):
        """Builds the elongated edge / wire / face.

        distance: extension beyond radius (so major_radius = radius + distance).
        direction: direction unit vector in the plane.
        mode: 'ellipse' or 'slot'.
        symmetric: if True (default), extends symmetrically in both directions (+u and -u).
                   if False, extends only along +u, keeping the opposite side (-u) anchored.
        """
        if isinstance(distance, bool) or not math.isfinite(distance) or distance < -self.radius + EPS:
            raise ValueError('Enter an elongation distance greater than -radius.')
        u = g.unit(direction)
        u = g.unit(u - self.plane.normal * u.dot(self.plane.normal))
        v = self.plane.normal.cross(u).normalize()

        if self.is_circle:
            if abs(distance) < EPS:
                # Zero elongation returns circular edge
                result = Part.Circle(self.center, self.plane.normal, self.radius).toShape()
                g.validate(result)
                return result

            if symmetric:
                major_r = self.radius + distance
                minor_r = self.radius

                if major_r < minor_r:
                    if major_r < EPS:
                        raise ValueError('Elongation collapses the circle.')
                    e = Part.Ellipse()
                    e.Center = self.center
                    e.MajorRadius = minor_r
                    e.MinorRadius = major_r
                    e.Axis = self.plane.normal
                    e.XAxis = v
                    edge = e.toShape()
                    g.validate(edge)
                    return edge

                if mode == 'slot' and distance > EPS:
                    c1 = self.center - u * distance
                    c2 = self.center + u * distance
                    p1 = c1 + v * minor_r
                    p2 = c2 + v * minor_r
                    p3 = c2 - v * minor_r
                    p4 = c1 - v * minor_r
                    line1 = Part.makeLine(p1, p2)
                    line2 = Part.makeLine(p3, p4)
                    mid1 = c2 + u * minor_r
                    mid2 = c1 - u * minor_r
                    arc1 = Part.Arc(p2, mid1, p3).toShape()
                    arc2 = Part.Arc(p4, mid2, p1).toShape()
                    wire = Part.Wire([line1, arc1, line2, arc2])
                    g.validate(wire)
                    return wire

                e = Part.Ellipse()
                e.Center = self.center
                e.MajorRadius = major_r
                e.MinorRadius = minor_r
                e.Axis = self.plane.normal
                e.XAxis = u
                edge = e.toShape()
                g.validate(edge)
                return edge

            else:
                # One-sided elongation: anchored at self.center - u * self.radius
                if mode == 'slot' and distance > EPS:
                    c1 = self.center
                    c2 = self.center + u * distance
                    p1 = c1 + v * self.radius
                    p2 = c2 + v * self.radius
                    p3 = c2 - v * self.radius
                    p4 = c1 - v * self.radius
                    line1 = Part.makeLine(p1, p2)
                    line2 = Part.makeLine(p3, p4)
                    mid1 = c2 + u * self.radius
                    mid2 = c1 - u * self.radius
                    arc1 = Part.Arc(p2, mid1, p3).toShape()
                    arc2 = Part.Arc(p4, mid2, p1).toShape()
                    wire = Part.Wire([line1, arc1, line2, arc2])
                    g.validate(wire)
                    return wire

                new_center = self.center + u * (distance / 2.0)
                r_u = self.radius + distance / 2.0
                r_v = self.radius
                if r_u < EPS:
                    raise ValueError('Elongation collapses the circle.')

                e = Part.Ellipse()
                e.Center = new_center
                e.Axis = self.plane.normal
                if r_u >= r_v:
                    e.MajorRadius = r_u
                    e.MinorRadius = r_v
                    e.XAxis = u
                else:
                    e.MajorRadius = r_v
                    e.MinorRadius = r_u
                    e.XAxis = v
                edge = e.toShape()
                g.validate(edge)
                return edge

        # For general planar face:
        if symmetric:
            scale = 1.0 + distance / max(self.radius, 1.0)
            if scale <= EPS:
                raise ValueError('Elongation collapses the face.')
            mat = stretch_matrix(self.center, self.plane.normal, u, scale)
        else:
            scale = 1.0 + distance / max(2.0 * self.radius, 1.0)
            if scale <= EPS:
                raise ValueError('Elongation collapses the face.')
            anchor = self.center - u * self.radius
            mat = stretch_matrix(anchor, self.plane.normal, u, scale)

        result = self.source.transformGeometry(mat)
        g.validate(result)
        return result
