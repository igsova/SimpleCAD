"""Exact face-following Line segments, with cheap parametric previews.

A straight segment in the face's parameter space becomes an exact curve on
its surface (an arc/helix on a cylinder). Periodic coordinates take the short
route across seams. This is a surface path, not a shortest-path solver.
"""
import math
from contextlib import contextmanager
from contextvars import ContextVar

import FreeCAD as App
import Part

from ..core import geometry as geo

TOLERANCE = 1e-5
_comparison_cache = ContextVar('surface_comparison_cache',default=None)


@contextmanager
def comparison_cache():
    """Share expensive native skin differences only during one atomic edit."""
    token = _comparison_cache.set({})
    try:
        yield
    finally:
        _comparison_cache.reset(token)


def skin_differences(removed,added):
    cache = _comparison_cache.get()
    cache_key = tuple(tuple(sorted((hash(f),f.Orientation) for f in group)) for group in (removed,added))
    if cache is not None:
        for before,after,differences in cache.get(cache_key,()):
            if all(all(any(f.isSame(g) and f.Orientation==g.Orientation for g in known) for f in current)
                   for current,known in ((removed,before),(added,after))):
                return differences
    # Re-intersecting different fitted patches together can misclassify an
    # entire split face at an old, tolerant seam. Compare trims on identical
    # B-spline supports separately. Exact coefficients (including weights and
    # parameterization) are required; the approximate UI support matcher is
    # deliberately unsuitable for this geometry check.
    groups = {}
    for side,faces in enumerate((removed,added)):
        for face in faces:
            groups.setdefault(_spline_support(face),[[],[]])[side].append(face)
    # Rebuilt neighbours can carry a different parameterization. They still
    # require the original native geometric comparison, not a coefficient test.
    unmatched = [[],[]]
    for key,(before,after) in list(groups.items()):
        if key is None or not before or not after:
            unmatched[0].extend(before)
            unmatched[1].extend(after)
            del groups[key]
    if any(unmatched):
        groups[None] = unmatched
    missing,extra = [],[]
    for before,after in groups.values():
        if not before or not after:
            missing.extend(before)
            extra.extend(after)
            continue
        before,after = Part.makeCompound(before),Part.makeCompound(after)
        missing.extend(before.cut(after).Faces)
        extra.extend(after.cut(before).Faces)
    differences = Part.makeCompound(missing),Part.makeCompound(extra)
    if cache is not None:
        cache.setdefault(cache_key,[]).append((list(removed),list(added),differences))
    return differences


def _spline_support(face):
    """Exact, world-space B-spline parameterization; other surfaces stay grouped."""
    surface = face.Surface
    if not isinstance(surface,Part.BSplineSurface):
        return None
    return (surface.UDegree,surface.VDegree,
            surface.isUPeriodic(),surface.isVPeriodic(),
            tuple(surface.getUKnots()),tuple(surface.getVKnots()),
            tuple(surface.getUMultiplicities()),tuple(surface.getVMultiplicities()),
            tuple(tuple(tuple(p) for p in row) for row in surface.getPoles()),
            tuple(tuple(row) for row in surface.getWeights()))


def project(face, point):
    u, v = face.Surface.parameter(point)
    return face.valueAt(u, v)


def on_surface(face, point):
    """Underlying surface membership; a path can cross existing face divisions."""
    return (project(face, point) - point).Length <= TOLERANCE


def same_surface(first, second):
    """Match drawing supports, including split faces, rather than shared corners.

    Native Geometry.isSame can miss identical cylinders or throw on fitted
    B-splines in FreeCAD 1.1. Check points of both bounded faces as a fallback.
    This chooses a UI support only; final curves still undergo exact coverage
    and the existing strict split/area/volume/orientation checks.
    """
    if first.isSame(second):
        return True
    a,b = first.Surface,second.Surface
    if type(a) != type(b):
        return False
    try:
        if a.isSame(b,1e-7,1e-10):
            return True
    except (RuntimeError,Part.OCCError):
        # A native comparison failure is inconclusive. In particular it must
        # not interrupt Line's support refresh after an already committed split.
        pass
    for face,other in ((first,second),(second,first)):
        u0,u1,v0,v1 = face.ParameterRange
        for u,v in ((.2,.2),(.5,.5),(.8,.2),(.2,.8),(.8,.8)):
            if not on_surface(other,face.valueAt(u0+u*(u1-u0),v0+v*(v1-v0))):
                return False
    return True


def snap_point(face, point, label):
    """A native boundary snap in this face's own trim coordinates.

    Fitted faces can carry 3D boundary vertices/curves off their surface within
    their original BREP tolerances. Orthogonal projection of those points can
    land inside the face, leaving a supposedly snapped line disconnected.
    Its pcurve defines the actual boundary on this surface; use that instead.
    This changes the picked point, never the face or any validation tolerance.
    """
    if label in ('Endpoint','Midpoint','On edge'):
        for edge in face.Edges:
            if edge.Degenerated:
                continue
            if label == 'Endpoint' and not any((vertex.Point-point).Length <= geo.EPS for vertex in edge.Vertexes):
                continue
            data = face.curveOnSurface(edge)
            if data is None:
                continue
            curve,first,last = data
            if label == 'Endpoint':
                parameter = min((first,last),key=lambda t:(edge.valueAt(t)-point).Length)
            else:
                parameter = edge.Curve.parameter(point)
                if (parameter < first-geo.EPS or parameter > last+geo.EPS
                        or (edge.valueAt(parameter)-point).Length > geo.EPS):
                    continue
            uv = curve.value(parameter)
            return face.valueAt(uv.x,uv.y)
    return project(face,point) if on_surface(face,point) and geo.point_on_face(face,point) else None


class SurfacePath:
    def __init__(self, face, first, second):
        if not all(math.isfinite(x) for p in (first, second) for x in p):
            raise ValueError('Line needs finite endpoints.')
        if not all(on_surface(face, p) for p in (first, second)):
            raise ValueError('Keep both endpoints on the same curved surface.')
        self.face = face
        self.start = tuple(face.Surface.parameter(first))
        end = list(face.Surface.parameter(second))
        for i, axis in enumerate(('U', 'V')):
            if getattr(face.Surface, 'is' + axis + 'Periodic')():
                period = getattr(face.Surface, axis + 'Period')()
                end[i] += round((self.start[i] - end[i]) / period) * period
        self.delta = tuple(b - a for a, b in zip(self.start, end))

    def point(self, t):
        return self.face.valueAt(*(a + t * d for a, d in zip(self.start, self.delta)))

    def preview(self):
        return [self.point(i / 64) for i in range(65)]

    def edge(self, scale=1.0):
        end = [a + scale * d for a, d in zip(self.start, self.delta)]
        if (self.point(scale) - self.point(0)).Length < geo.EPS:
            raise ValueError('Choose a different endpoint on the surface.')
        try:
            curve = Part.Geom2d.Line2dSegment(App.Base.Vector2d(*self.start), App.Base.Vector2d(*end))
            return curve.toShape(self.face.Surface)
        except (Part.OCCError, RuntimeError) as error:
            raise ValueError('The line could not be laid on this surface. Try a shorter segment.') from error

    def at_length(self, length):
        """Continue this parametric direction to an exact on-surface length."""
        if not math.isfinite(length) or abs(length) < geo.EPS:
            raise ValueError('Enter a nonzero surface length.')
        sign = 1 if length > 0 else -1
        desired = abs(length)
        lo, hi = 0.0, 1.0
        for _ in range(20):
            if self.edge(sign * hi).Length >= desired:
                break
            hi *= 2
        else:
            raise ValueError('That surface length is too large. Choose a nearer endpoint.')
        for _ in range(40):
            middle = (lo + hi) / 2
            actual = self.edge(sign * middle).Length
            if actual < desired:
                lo = middle
            else:
                hi = middle
        point = self.point(sign * (lo + hi) / 2)
        if abs(SurfacePath(self.face, self.point(0), point).edge().Length-desired) > max(1e-6, desired*1e-8):
            raise ValueError('That length wraps too far around the surface. Draw shorter segments.')
        return point


def covered(shape, edge):
    """Exact coverage rejects paths across a hole or beyond trimmed boundaries."""
    if shape.Solids:
        # Every segment of a Line asks this of the same part.
        index = geo.face_index(shape, build=False)
        shape = index.compound if index is not None else Part.makeCompound(shape.Faces)
    return abs(shape.common(edge).Length - edge.Length) <= max(geo.EPS, edge.Length * 1e-8)


def changed_measure(removed, added, name):
    """The change of a shape's Area or Volume, integrated over changed faces.

    OCC sums both over faces, and an unchanged native face contributes the
    same area to both shapes. Its volume term depends on a reference point,
    which drops out only of a closed shell: use 'Volume' only when the
    source and the result are both closed. Integrating a whole fitted part
    twice per edit took most of a second.
    """
    if name == 'Area':
        def total(faces):
            return Part.makeCompound(faces).Area if faces else 0.0
        return abs(total(added) - total(removed))
    # One compound gives both sets the same reference point; a reversed face
    # counts negatively.
    faces = list(added) + [face.reversed() for face in removed]
    return abs(Part.makeCompound(faces).Volume) if faces else 0.0


def preserves_area(source, result):
    """Check actual lost/added skin when B-spline area quadrature disagrees.

    Changing trims can change OCC's numerical area integral. The geometric
    differences must still satisfy exactly the existing area tolerance.
    """
    removed, added = changed_faces(source, result)
    change = changed_measure(removed, added, 'Area')
    if change <= 1e-6:
        return True
    # The removed faces are part of the source, so their area bounds the
    # source's from below, and so does the tolerance. When that already
    # decides, skip integrating every face of a fitted part (0.15-0.3 s).
    if removed and change <= Part.makeCompound(removed).Area * 1e-8:
        return True
    tolerance = max(1e-6, source.Area * 1e-8)
    if change <= tolerance:
        return True
    if not removed or not added:
        return sum(f.Area for f in removed+added) <= tolerance
    missing,extra = skin_differences(removed,added)
    return missing.Area <= tolerance and extra.Area <= tolerance


def changed_faces(source, result):
    """Cancel shared, equally oriented faces before geometric comparisons.

    Local splitting retains the native identity of unrelated faces. Including
    those in a Boolean can fail on a fitted part's old tolerance overlaps.
    Every unmatched face still participates, including rebuilt neighbours.
    """
    index = {}
    for face in result.Faces:
        index.setdefault(hash(face), []).append(face)
    removed = []
    for face in source.Faces:
        bucket = index.get(hash(face), [])
        match = next((i for i, other in enumerate(bucket)
                      if face.isSame(other) and face.Orientation == other.Orientation), None)
        if match is None:
            removed.append(face)
        else:
            bucket.pop(match)
    return removed, [face for bucket in index.values() for face in bucket]


def same_boundary(source, result):
    """An unchanged oriented skin proves zero added/removed solid material.

    Require empty face differences, rather than accepting a scalar area error.
    This also avoids whole-solid Booleans over unrelated fitted faces when
    trimming only changes the kernel's numerical volume integration.
    """
    removed, added = changed_faces(source, result)
    if not removed or not added:
        return not removed and not added
    missing,extra = skin_differences(removed,added)
    if missing.Faces or extra.Faces:
        return False
    for part in added:
        u0,u1,v0,v1 = part.ParameterRange
        u,v = (u0+u1)/2,(v0+v1)/2
        point,normal = part.valueAt(u,v),part.normalAt(u,v)
        if not any(face.common(part).Area > geo.EPS and
                   face.normalAt(*face.Surface.parameter(point)).dot(normal) > 0 for face in removed):
            return False
    return True


def preserves_volume(source, result, relative=1e-8, valid=False):
    """Measure actual changed volume when trimmed-surface integration drifts.

    Splitting a fitted solid changes its integration domains. A changed scalar
    Volume alone does not establish a cut or added material. Keep the caller's
    existing tolerance for both directions of the actual solid difference.
    valid: the caller has just found result.isValid() and nothing has run on
    the result since; checking it again cost 0.1 s on a fitted part.
    """
    closed = source.isClosed() and result.isClosed()
    change = (changed_measure(*changed_faces(source, result), 'Volume') if closed
              else abs(geo.volume(result)-geo.volume(source)))
    if change <= 1e-6:
        return True
    # The source is usually the previous divide's result, already measured.
    tolerance = max(1e-6, abs(geo.volume(source)) * relative)
    if change <= tolerance:
        return True
    # Closed valid solids with the same outward boundary enclose exactly the
    # same material. Do not ask a full Boolean to re-intersect untouched faces.
    if (source.Solids and result.Solids and source.isClosed() and result.isClosed()
            and source.isValid() and (valid or result.isValid()) and same_boundary(source, result)):
        return True
    for before, after in ((source,result),(result,source)):
        difference = before.cut(after)
        if difference.isNull():
            continue
        solids = difference.Solids
        if (not difference.isValid()
                or sum(len(s.Faces) for s in solids) != len(difference.Faces)
                or not solids and difference.childShapes()
                or sum(abs(s.Volume) for s in solids) > tolerance):
            return False
    return True
