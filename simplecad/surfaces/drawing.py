"""Local millimetre drawing coordinates and exact curves on a CAD surface.

An affine change of UV coordinates matches an orthonormal tangent frame at
the anchor. It unrolls cylinders exactly; free-form surfaces can stretch the
drawing away from the anchor. Rational planar curves remain rational pcurves,
so committed outlines lie on the native surface without mesh approximations.
"""
import math

import FreeCAD as App
import Part

from ..core import geometry as geo
from .line import on_surface


class SurfaceFrame:
    def __init__(self, face, anchor, x_direction=None):
        if not all(math.isfinite(x) for x in anchor) or not on_surface(face, anchor):
            raise ValueError('Choose a starting point on the surface.')
        self.face = face
        self.origin = tuple(face.Surface.parameter(anchor))
        self.anchor = face.valueAt(*self.origin)
        self.plane = geo.Plane.from_normal(self.anchor, face.normalAt(*self.origin))
        if x_direction is not None:
            self.plane.u = geo.unit(x_direction-self.plane.normal*x_direction.dot(self.plane.normal))
            self.plane.v = self.plane.normal.cross(self.plane.u)
        du, dv = face.derivative1At(*self.origin)
        uu, uv, vv = du.dot(du), du.dot(dv), dv.dot(dv)
        det = uu*vv-uv*uv
        if det <= 1e-14*uu*vv or min(uu, vv) < 1e-20:
            raise ValueError('The surface coordinates meet at this point. Start away from the pole or tip.')

        def coefficients(direction):
            return ((direction.dot(du)*vv-direction.dot(dv)*uv)/det,
                    (direction.dot(dv)*uu-direction.dot(du)*uv)/det)

        self.x, self.y = coefficients(self.plane.u), coefficients(self.plane.v)
        self.det = self.x[0]*self.y[1]-self.x[1]*self.y[0]

    def uv(self, point):
        return tuple(a+point.x*x+point.y*y for a, x, y in zip(self.origin, self.x, self.y))

    def point(self, point):
        return self.face.valueAt(*self.uv(point))

    def local(self, point):
        if not on_surface(self.face, point):
            raise ValueError('Keep drawing on the same curved surface.')
        uv = list(self.face.Surface.parameter(point))
        for i, axis in enumerate(('U', 'V')):
            if getattr(self.face.Surface, 'is'+axis+'Periodic')():
                period = getattr(self.face.Surface, axis+'Period')()
                uv[i] += round((self.origin[i]-uv[i])/period)*period
        u, v = (b-a for a, b in zip(self.origin, uv))
        return geo.V((u*self.y[1]-v*self.y[0])/self.det,
                     (v*self.x[0]-u*self.x[1])/self.det, 0)

    def points(self, points):
        return [self.point(p) for p in points]

    def curves(self, profile):
        """Map an XY wire/edge to exact pcurves; refuse wrapping over itself."""
        curves, planar = [], []
        for edge in profile.Edges:
            spline = edge.toNurbs().Edges[0]
            curve = spline.Curve.copy()
            curve.segment(spline.FirstParameter, spline.LastParameter)
            poles = [App.Base.Vector2d(*self.uv(p)) for p in curve.getPoles()]
            mapped = Part.Geom2d.BSplineCurve2d()
            mapped.buildFromPolesMultsKnots(poles, curve.getMultiplicities(), curve.getKnots(),
                                          curve.isPeriodic(), curve.Degree, curve.getWeights())
            planar.append(mapped.toShape(Part.Plane()))
            result = mapped.toShape(self.face.Surface)
            if edge.Orientation == 'Reversed':
                result.reverse()
            curves.append(result)
        if not curves:
            raise ValueError('The drawing has no edges.')
        box = Part.makeCompound(planar).optimalBoundingBox(False, False)
        bounds = self.face.Surface.bounds()
        for i, axis in enumerate(('U', 'V')):
            low, high = ((box.XMin, box.XMax), (box.YMin, box.YMax))[i]
            if getattr(self.face.Surface, 'is'+axis+'Periodic')():
                if high-low >= getattr(self.face.Surface, axis+'Period')()-1e-7:
                    raise ValueError('The drawing wraps all the way around this surface. Make it smaller.')
            elif low < bounds[2*i]-1e-7 or high > bounds[2*i+1]+1e-7:
                raise ValueError('The drawing leaves the surface. Make it smaller or move its starting point.')
        return curves

    def edge(self, profile):
        return self.curves(profile)[0]

    def wire(self, profile):
        result = Part.Wire(self.curves(profile))
        if not result.isClosed() or not result.isValid():
            raise ValueError('The drawing could not form a closed surface outline. Make it smaller.')
        return result
