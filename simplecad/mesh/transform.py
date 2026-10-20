"""Indexed, piecewise-affine mesh deformation; no CAD or GUI dependencies.

Triangles crossing either control plane are split once. A cached plan then
updates only coordinates while the user changes displacement. Positive
axial Jacobian makes the mapping globally one-to-one: it cannot fold a
valid input onto itself, including when the moving end is shifted sideways.
"""
import math
import numpy as np

MAX_TRIANGLES = 500000
MIN_DOUBLE_AREA = 1e-14


def double_areas(points, triangles):
    sample = points[triangles]
    return np.linalg.norm(np.cross(sample[:, 1] - sample[:, 0], sample[:, 2] - sample[:, 0]), axis=1)


def scalar(value, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or abs(value) > 1e7:
        raise ValueError(label + ' must be a finite number between -10000000 and 10000000.')
    return float(value)


def vector(value, label):
    try:
        if len(value) != 3:
            raise ValueError()
        return np.asarray([scalar(v, label) for v in value], dtype=float)
    except (TypeError, ValueError):
        raise ValueError(label + ' needs three finite coordinates.')


class Plan:
    def __init__(self, points, triangles, origin, normal, lower, upper, reverse=False):
        self.origin = vector(origin, 'Plane center')
        self.normal = vector(normal, 'Axis')
        length = float(np.linalg.norm(self.normal))
        if length < 1e-10:
            raise ValueError('Choose a nonzero axis.')
        self.normal /= length
        self.lower, self.upper = scalar(lower, 'First plane'), scalar(upper, 'Second plane')
        if self.upper - self.lower < 1e-5:
            raise ValueError('The second plane must be at least 0.00001 mm above the first.')
        if not isinstance(reverse, bool):
            raise ValueError('Moving negative side must be true or false.')
        self.reverse = reverse
        xyz = np.asarray(points, dtype=float)
        raw = np.asarray(triangles)
        if (xyz.ndim != 2 or xyz.shape[1] != 3 or not len(xyz) or not np.isfinite(xyz).all()
                or np.max(np.abs(xyz)) > 1e7 or raw.ndim != 2 or raw.shape[1] != 3
                or raw.dtype.kind not in 'iu' or not 0 < len(raw) <= MAX_TRIANGLES
                or raw.min() < 0 or raw.max() >= len(xyz)):
            raise ValueError('Choose a finite indexed mesh with 1 to 500000 triangles.')
        levels = (xyz - self.origin) @ self.normal
        epsilon = max(1e-9, float(np.ptp(levels)) * 1e-10)
        if self.lower < float(levels.min()) - epsilon or self.upper > float(levels.max()) + epsilon:
            raise ValueError('Place both control planes within the mesh extent.')
        points = xyz.tolist()
        levels = levels.tolist()
        faces = raw.astype(np.int64, copy=True)
        # Keep provenance through both cuts. Some otherwise closed STL meshes
        # contain collinear facets; deleting them would tear their connectivity.
        # Only their descendants may remain degenerate after deformation.
        degenerate = double_areas(xyz, faces) <= MIN_DOUBLE_AREA
        self.degenerate_before = int(np.count_nonzero(degenerate))
        for plane in (self.lower, self.upper):
            # Most triangles do not cross a plane: keep them in one array.
            heights = np.asarray(levels)[faces]
            crossing = (heights.min(axis=1) < plane) & (heights.max(axis=1) > plane)
            additions, inherited, intersections = [], [], {}

            def cut(a, b):
                if levels[a] == plane:
                    return a
                if levels[b] == plane:
                    return b
                key = (min(a, b), max(a, b))
                if key not in intersections:
                    t = (plane - levels[a]) / (levels[b] - levels[a])
                    p = np.asarray(points[a]) + (np.asarray(points[b]) - points[a]) * t
                    intersections[key] = len(points)
                    points.append(p.tolist()); levels.append(plane)
                return intersections[key]

            for tri, was_degenerate in zip(faces[crossing].tolist(), degenerate[crossing]):
                for sign in (-1, 1):
                    polygon = []
                    for a, b in zip(tri, tri[1:] + tri[:1]):
                        inside_a = sign * (levels[a] - plane) >= 0
                        inside_b = sign * (levels[b] - plane) >= 0
                        if inside_a:
                            polygon.append(a)
                        if inside_a != inside_b:
                            polygon.append(cut(a, b))
                    polygon = list(dict.fromkeys(polygon))
                    additions.extend((polygon[0], polygon[i], polygon[i+1]) for i in range(1, len(polygon)-1))
                    inherited.extend([was_degenerate] * max(0, len(polygon)-2))
            if additions:
                faces = np.concatenate((faces[~crossing], np.asarray(additions, dtype=np.int64)))
                degenerate = np.concatenate((degenerate[~crossing], np.asarray(inherited, dtype=bool)))
            if len(faces) > MAX_TRIANGLES:
                raise ValueError('Splitting at the control planes exceeds 500000 triangles.')
        self.points = np.asarray(points, dtype=float)
        self.triangles = faces
        self.inherited_degenerate = degenerate
        self.weights = np.clip((np.asarray(levels) - self.lower) / (self.upper - self.lower), 0, 1)
        if reverse:
            self.weights = 1 - self.weights
        self.original_count = len(raw)

    def validate_areas(self, moved):
        """Permit existing degenerate facets, never a newly collapsed facet."""
        areas = double_areas(moved, self.triangles)
        collapsed = areas <= MIN_DOUBLE_AREA
        if not np.isfinite(areas).all() or np.any(collapsed & ~self.inherited_degenerate):
            raise ValueError('The stretch created a collapsed triangle. Move the control planes slightly or reduce the movement.')
        return int(np.count_nonzero(collapsed))

    def transform(self, delta):
        delta = vector(delta, 'Displacement')
        jacobian = 1 + (-1 if self.reverse else 1) * float(delta @ self.normal) / (self.upper - self.lower)
        if jacobian < 1e-4:
            raise ValueError('This movement would collapse or reverse the middle section. Reduce the shortening.')
        result = self.points + self.weights[:, None] * delta
        if not np.isfinite(result).all() or np.max(np.abs(result)) > 1e7:
            raise ValueError('The result exceeds the supported coordinate range.')
        return result
