"""Fit a few smooth surfaces to a dense triangle mesh (NumPy/SciPy only).

CAD-exported STL files sample smooth design surfaces: every vertex lies on the
designed surface, and the facets between them are chords. Rebuilding each
facet as a CAD face keeps that faceting and produces thousands of faces.
This module instead groups the triangles into patches and fits one surface to
each: a plane when the patch is flat, otherwise a cubic B-spline height field
over the patch's own projection plane. Patches end at sharp edges and are
split further only when one surface cannot follow them within the tolerance.

The FreeCAD side (mesh_surfaces) turns the result into faces and validates
the solid. Nothing here touches FreeCAD, so it is unit-tested directly.
"""
import heapq
import math

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.interpolate import BSpline
from scipy.sparse.csgraph import connected_components

# Facets meeting at more than this angle belong to different faces. Smaller
# creases (such as a shallow countersink) are found when a fit fails.
SHARP_ANGLE = 30.0
# A height field needs every facet to face its projection axis; this keeps
# the projection one-to-one with room for curvature inside a patch.
MAX_TILT = 60.0
DEGREE = 3
MAX_SPANS = 48
# A patch boundary turning more than this at a vertex gets a corner there.
KINK_ANGLE = 35.0
# Each split and refit is bounded; past this the caller keeps the facets.
MAX_PATCHES = 2000
# Facet interiors are bisected at most this often for samples (a facet
# gets at most 2**MAX_BISECTIONS of them).
MAX_BISECTIONS = 16


def _components(count, a, b):
    graph = sp.coo_matrix((np.ones(len(a)), (a, b)), shape=(count, count))
    return connected_components(graph, directed=False)[1]


class Facets:
    """Indexed triangles with the edge adjacency used for segmentation."""

    def __init__(self, points, faces):
        p = self.points = np.asarray(points, dtype=float)
        f = self.faces = np.asarray(faces, dtype=np.int64)
        if p.ndim != 2 or p.shape[1] != 3 or f.ndim != 2 or f.shape[1] != 3 or not len(f):
            raise ValueError('Surface fitting needs an indexed triangle mesh.')
        tri = p[f]
        cross = np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0])
        double = np.linalg.norm(cross, axis=1)
        longest = np.linalg.norm(tri-np.roll(tri, 1, axis=1), axis=2).max(axis=1)
        self.extent = float(np.linalg.norm(np.ptp(p, axis=0))) or 1.0
        # Slivers: their few-micron height makes the facet normal noise.
        self.sliver = double < np.maximum(1e-3*longest, 1e-4*self.extent)*longest
        self.areas = np.where(self.sliver, 0.0, double/2)
        self.normals = cross/np.maximum(double, 1e-300)[:, None]
        half = np.stack((f, np.roll(f, -1, axis=1)), axis=2).reshape(-1, 2)
        owner = np.repeat(np.arange(len(f)), 3)
        keys = half.min(axis=1)*len(p)+half.max(axis=1)
        order = np.argsort(keys, kind='stable')
        sorted_keys = keys[order]
        starts = np.flatnonzero(np.r_[True, sorted_keys[1:] != sorted_keys[:-1]])
        counts = np.diff(np.r_[starts, len(keys)])
        if np.any(counts > 2):
            raise ValueError('Surface fitting needs a manifold mesh.')
        self.half, self.owner = half, owner
        # Twin half-edge of each half-edge, or -1 on an open border.
        self.twin = np.full(len(half), -1, dtype=np.int64)
        pairs = starts[counts == 2]
        self.twin[order[pairs]] = order[pairs+1]
        self.twin[order[pairs+1]] = order[pairs]
        first = order[pairs]
        self.edge_a, self.edge_b = owner[first], owner[self.twin[first]]
        self.edge_vertices = half[first]
        self._borrow_normals()
        cosine = np.einsum('ij,ij->i', self.normals[self.edge_a], self.normals[self.edge_b])
        self.dihedral = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
        # Half-edges on a sharp edge or an open border.
        self.crease = self.twin < 0
        sharp = first[self.dihedral >= SHARP_ANGLE]
        self.crease[sharp] = self.crease[self.twin[sharp]] = True

    def _borrow_normals(self):
        """Give slivers the normal of the neighbor across their longest edge.

        A sliver lies along its longest edge, on the facet across it. Fans
        of slivers share their long edges, so the chain is followed to its
        first real facet; their short edges touch whatever lies at their
        tips, and borrowing from there would put a false sharp edge through
        the middle of a smooth face. Slivers whose chain never reaches a
        real facet (a closed fan or an open border) borrow, best first,
        from the facet they touch whose plane best contains their
        direction, so a needle lying on a flat rim takes the rim's normal
        rather than that of the wall at its tip.
        """
        slivers = np.flatnonzero(self.sliver)
        if not len(slivers):
            return
        corners = self.points[self.faces[slivers]]
        lengths = np.linalg.norm(np.roll(corners, -1, axis=1)-corners, axis=2)
        across = self.twin[3*slivers+np.argmax(lengths, axis=1)]
        pointer = np.arange(len(self.faces))
        pointer[slivers] = np.where(across >= 0, self.owner[np.maximum(across, 0)], slivers)
        for _ in range(64):
            following = pointer[pointer]
            if np.array_equal(following, pointer):
                break
            pointer = following
        found = slivers[~self.sliver[pointer[slivers]]]
        self.normals[found] = self.normals[pointer[found]]
        unknown = self.sliver.copy()
        unknown[found] = False
        if not unknown.any():
            return
        ends = np.take_along_axis(np.roll(corners, -1, axis=1)-corners, np.argmax(lengths, axis=1)[:, None, None], axis=1)[:, 0]
        direction = np.zeros_like(self.normals)
        direction[slivers] = ends/np.maximum(np.linalg.norm(ends, axis=1), 1e-300)[:, None]
        neighbors = np.where(self.twin >= 0, self.owner[np.maximum(self.twin, 0)], -1).reshape(-1, 3).tolist()

        def misfit(sliver, source):
            return abs(float(self.normals[source] @ direction[sliver]))

        queue = [(misfit(sliver, source), sliver, source) for sliver in np.flatnonzero(unknown).tolist()
                 for source in neighbors[sliver] if source >= 0 and not unknown[source]]
        heapq.heapify(queue)
        while queue:
            _, sliver, source = heapq.heappop(queue)
            if not unknown[sliver]:
                continue
            self.normals[sliver] = self.normals[source]
            unknown[sliver] = False
            for other in neighbors[sliver]:
                if other >= 0 and unknown[other]:
                    heapq.heappush(queue, (misfit(other, sliver), other, sliver))


def _mean_normal(facets, triangles):
    total = (facets.normals[triangles]*(facets.areas[triangles]+1e-12)[:, None]).sum(axis=0)
    length = np.linalg.norm(total)
    return total/length if length > 1e-300 else None


def _normal_clusters(normals, weights, k):
    """Spherical k-means with farthest-point seeding (deterministic)."""
    centers = [normals[int(np.argmax(weights))]]
    for _ in range(1, k):
        nearest = np.max(np.stack([normals @ c for c in centers]), axis=0)
        centers.append(normals[int(np.argmin(nearest))])
    centers = np.asarray(centers)
    labels = np.zeros(len(normals), dtype=np.int64)
    for _ in range(40):
        labels = np.argmax(normals @ centers.T, axis=1)
        moved = np.zeros_like(centers)
        np.add.at(moved, labels, normals*weights[:, None])
        length = np.linalg.norm(moved, axis=1)
        keep = length > 1e-300
        moved[keep] /= length[keep, None]
        moved[~keep] = centers[~keep]
        if np.allclose(moved, centers):
            break
        centers = moved
    return labels, centers


def _connected(facets, triangles, labels):
    """Split each label of the given triangles into connected parts."""
    inside = np.full(len(facets.faces), -1, dtype=np.int64)
    inside[triangles] = labels
    a, b = facets.edge_a, facets.edge_b
    keep = (inside[a] >= 0) & (inside[a] == inside[b])
    parts = _components(len(facets.faces), a[keep], b[keep])[triangles]
    return [triangles[parts == value] for value in np.unique(parts)]


def _absorb(facets, parts, limit):
    """Join the small fragments a clustering leaves to neighboring parts.

    Clusters by normal direction are not connected: a few triangles whose
    normals fall between clusters, near a pole or a seam, end up as islands
    of their own. Each fragment joins the neighbor it shares most edges
    with, when the joined part still faces its mean normal within limit.
    """
    if len(parts) < 2:
        return parts
    parts = list(parts)
    label = np.full(len(facets.faces), -1, dtype=np.int64)
    for index, part in enumerate(parts):
        label[part] = index
    total = sum(len(part) for part in parts)
    cosine = math.cos(math.radians(limit))
    a, b = facets.edge_a, facets.edge_b
    for index in sorted(range(len(parts)), key=lambda i: len(parts[i])):
        part = parts[index]
        if len(part) > max(8, total//50):
            break
        touching = np.r_[label[b[label[a] == index]], label[a[label[b] == index]]]
        touching = touching[(touching >= 0) & (touching != index)]
        if not len(touching):
            continue
        neighbors, shared = np.unique(touching, return_counts=True)
        for neighbor in neighbors[np.argsort(-shared, kind='stable')].tolist():
            joined = np.r_[parts[neighbor], part]
            normals, weights = facets.normals[joined], facets.areas[joined]+1e-12
            mean = (normals*weights[:, None]).sum(axis=0)
            mean /= max(np.linalg.norm(mean), 1e-300)
            if np.min(normals @ mean) >= cosine:
                parts[neighbor], parts[index] = joined, part[:0]
                label[part] = neighbor
                break
    return [part for part in parts if len(part)]


def _tilted(facets, triangles, limit):
    """Split triangles until every part faces its mean normal within limit."""
    normals, weights = facets.normals[triangles], facets.areas[triangles]+1e-12
    cosine = math.cos(math.radians(limit))
    labels = np.zeros(len(triangles), dtype=np.int64)
    for k in range(1, 33):
        if k > 1:
            labels, _ = _normal_clusters(normals, weights, k)
        worst = 1.0
        for value in np.unique(labels):
            chosen = labels == value
            mean = (normals[chosen]*weights[chosen, None]).sum(axis=0)
            mean /= max(np.linalg.norm(mean), 1e-300)
            worst = min(worst, float(np.min(normals[chosen] @ mean)))
        if worst >= cosine:
            break
    return _absorb(facets, _connected(facets, triangles, labels), limit)


def regions(facets, sharp=SHARP_ANGLE):
    """Smooth regions: the triangles between sharp edges."""
    smooth = facets.dihedral < sharp
    found = _components(len(facets.faces), facets.edge_a[smooth], facets.edge_b[smooth])
    order = np.argsort(found, kind='stable')
    bounds = np.flatnonzero(np.r_[True, np.diff(found[order]) != 0, True])
    return [order[start:stop] for start, stop in zip(bounds[:-1], bounds[1:])]


def segment(facets, sharp=SHARP_ANGLE, tilt=MAX_TILT):
    """Initial patches: smooth regions bounded by sharp edges, split until
    each can be a height field."""
    return [part for region in regions(facets, sharp) for part in _tilted(facets, region, tilt)]


def split(facets, triangles):
    """Two or more connected parts of a patch that failed to fit, or []."""
    if len(triangles) < 2:
        return []
    inside = np.zeros(len(facets.faces), dtype=bool)
    inside[triangles] = True
    internal = inside[facets.edge_a] & inside[facets.edge_b]
    angles = facets.dihedral[internal]
    if len(angles) and angles.max() >= 8:
        # Cut the strongest creases first, e.g. a countersink below the
        # sharp-edge angle; a fillet's gentler facet turns stay together.
        cut = angles >= max(8.0, .7*float(angles.max()))
        a, b = facets.edge_a[internal][~cut], facets.edge_b[internal][~cut]
        labels = _components(len(facets.faces), a, b)[triangles]
        parts = [triangles[labels == value] for value in np.unique(labels)]
        if len(parts) > 1:
            return parts
    weights = facets.areas[triangles]+1e-12
    labels, _ = _normal_clusters(facets.normals[triangles], weights, 2)
    parts = _connected(facets, triangles, labels)
    if len(parts) > 1:
        return parts
    # Uniformly curved: halve across the longest direction.
    centers = facets.points[facets.faces[triangles]].mean(axis=1)
    centered = centers-np.average(centers, axis=0, weights=weights)
    axis = np.linalg.svd(centered, full_matrices=False)[2][0]
    parts = _connected(facets, triangles, (centered @ axis > 0).astype(np.int64))
    return parts if len(parts) > 1 else []


class PlaneFit:
    kind = 'plane'

    def __init__(self, origin, normal, error):
        self.origin, self.normal, self.error = origin, normal, error
        self.sample_error = error
        helper = np.eye(3)[int(np.argmin(np.abs(normal)))]
        first = np.cross(normal, helper)
        first /= np.linalg.norm(first)
        self.axes = np.stack((first, np.cross(normal, first)))

    def parameters(self, points):
        return (points-self.origin) @ self.axes.T

    def at(self, parameters):
        return self.origin+parameters @ self.axes

    def project(self, points):
        return points-np.outer((points-self.origin) @ self.normal, self.normal)

    def distance(self, points):
        return np.abs((points-self.origin) @ self.normal)


class CylinderFit:
    """A circular cylinder around the line through origin along axis.

    Parameters are (radius*angle, height): arc length around the axis from
    the x direction toward y = axis x x, and height along the axis. That
    frame is right-handed about the outward normal; `outward` says whether
    the patch's triangles face away from the axis (a boss) or toward it
    (a hole).
    """
    kind = 'cylinder'

    def __init__(self, origin, axis, radius, outward, error, sample_error):
        self.origin, self.axis, self.radius, self.outward = origin, axis, radius, outward
        self.error, self.sample_error = error, sample_error
        self.period = 2*math.pi*radius
        helper = np.eye(3)[int(np.argmin(np.abs(axis)))]
        self.x = np.cross(axis, helper)
        self.x /= np.linalg.norm(self.x)
        self.y = np.cross(axis, self.x)

    def _split(self, points):
        relative = points-self.origin
        height = relative @ self.axis
        return height, relative-np.outer(height, self.axis)

    def parameters(self, points):
        relative = points-self.origin
        return np.c_[self.radius*np.arctan2(relative @ self.y, relative @ self.x), relative @ self.axis]

    def at(self, parameters):
        angle = parameters[:, 0]/self.radius
        return (self.origin+self.radius*(np.outer(np.cos(angle), self.x)+np.outer(np.sin(angle), self.y))
                + np.outer(parameters[:, 1], self.axis))

    def project(self, points):
        height, radial = self._split(points)
        length = np.linalg.norm(radial, axis=1)
        direction = np.where(length[:, None] > 1e-300, radial/np.maximum(length, 1e-300)[:, None], self.x)
        return self.origin+np.outer(height, self.axis)+self.radius*direction

    def distance(self, points):
        return np.abs(np.linalg.norm(self._split(points)[1], axis=1)-self.radius)


def _circle_2d(points):
    """Center and radius of the least-squares circle through 2D points."""
    matrix = np.c_[2*points, np.ones(len(points))]
    solution = np.linalg.lstsq(matrix, (points*points).sum(axis=1), rcond=None)[0]
    center = solution[:2]
    return center, math.sqrt(max(solution[2]+center @ center, 0.0))


def _cylinder_along(facets, solid, points, axis, origin, tolerance):
    """The cylinder with this axis direction that fits the facets, or None.

    Without an origin, the axis passes through the center of the points'
    circle across it.
    """
    helper = np.eye(3)[int(np.argmin(np.abs(axis)))]
    e1 = np.cross(axis, helper)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    if origin is None:
        center, _ = _circle_2d(np.c_[points @ e1, points @ e2])
        origin = center[0]*e1+center[1]*e2
    fitted = CylinderFit(origin, axis, 1.0, True, 0.0, 0.0)
    reach = np.linalg.norm(fitted._split(points)[1], axis=1)
    radius = float(reach.mean())
    # Facet samples only widen the vertices' spread around the axis.
    if not tolerance < radius <= facets.extent or float(reach.max()-reach.min()) > 1.5*tolerance:
        return None
    # Every facet faces the same way across the wall: a genuine cylinder
    # sheet, not a fold or a region that only passes near one.
    centers = facets.points[facets.faces[solid]].mean(axis=1)
    radial = fitted._split(centers)[1]
    facing = np.einsum('ij,ij->i', facets.normals[solid],
                       radial/np.maximum(np.linalg.norm(radial, axis=1), 1e-300)[:, None])
    fitted.outward = bool(facing.mean() > 0)
    if np.min(facing if fitted.outward else -facing) < math.cos(math.radians(MAX_TILT)):
        return None
    # Exporters facet a cylinder as an inscribed polygon: corners on the
    # circle, chords and the vertices along them sagging inside it, often
    # by about the tolerance itself. The radius sits midway between the
    # farthest and nearest points, sampled at the spacing where a chord
    # sags by an eighth of the tolerance, and everything must lie within
    # three quarters of the tolerance. The last quarter is the neighboring
    # surface's, whose boundary fit() holds that close, so their seam
    # stays within the tolerance.
    spacing = max(math.sqrt(radius*tolerance), tolerance)
    samples, _ = _samples(facets, solid, spacing, np.zeros(len(facets.points), dtype=bool),
                          np.full(len(solid), spacing))
    reach = np.linalg.norm(fitted._split(np.vstack((points, samples)))[1], axis=1)
    fitted.radius = float(reach.max()+reach.min())/2
    fitted.period = 2*math.pi*fitted.radius
    distance, sample_distance = fitted.distance(points), fitted.distance(samples)
    if max(distance.max(), sample_distance.max(initial=0)) > .75*tolerance:
        return None
    fitted.error, fitted.sample_error = float(distance.max()), float(sample_distance.max(initial=0))
    return fitted


def fit_cylinder(facets, triangles, tolerance):
    """A CylinderFit within the tolerance of the triangles, or None.

    Holes, bosses and other turned faces come out of CAD exporters as one
    smooth region between sharp edges. A height field cannot wrap around
    them, so fit() would cut them into several faces; one cylinder follows
    the whole region, and its rims stay single circles. The axis is the
    direction the facet normals avoid: every facet of a faceted cylinder
    runs along it, even where its vertices sit on chords, so it stays
    square to the faces the cylinder meets. Only when that cylinder misses
    are the axis and its position refined to the vertices. Flat regions are
    left to fit()'s plane.
    """
    from scipy.optimize import least_squares
    triangles = np.asarray(triangles, dtype=np.int64)
    solid = triangles[~facets.sliver[triangles]]
    if len(solid) < 4:
        return None
    vertices = np.unique(facets.faces[solid])
    points = facets.points[vertices]
    if _plane(points)[2] <= tolerance/4:
        return None
    normals, weights = facets.normals[solid], facets.areas[solid]
    axis = np.linalg.eigh((normals*weights[:, None]).T @ normals)[1][:, 0]
    fitted = _cylinder_along(facets, solid, points, axis, None, tolerance)
    if fitted is not None:
        return fitted
    helper = np.eye(3)[int(np.argmin(np.abs(axis)))]
    e1 = np.cross(axis, helper)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    center, radius = _circle_2d(np.c_[points @ e1, points @ e2])
    if not 0 < radius <= facets.extent:
        return None
    # Refining only helps a nearly fitting cylinder; anything else, such as
    # a whole filleted box, is left to the height fields.
    reach = np.linalg.norm(np.c_[points @ e1, points @ e2]-center, axis=1)
    if float(reach.max()-reach.min()) > .1*radius:
        return None
    origin = center[0]*e1+center[1]*e2

    def frame(x):
        direction = axis+x[0]*e1+x[1]*e2
        direction /= np.linalg.norm(direction)
        return origin+x[2]*e1+x[3]*e2, direction

    def residual(x):
        base, direction = frame(x)
        relative = points-base
        return np.linalg.norm(relative-np.outer(relative @ direction, direction), axis=1)-x[4]
    solution = least_squares(residual, np.r_[0, 0, 0, 0, radius], x_scale=np.r_[1, 1, radius, radius, radius])
    base, direction = frame(solution.x)
    return _cylinder_along(facets, solid, points, direction, base, tolerance)


def _clamped(breaks):
    return np.r_[[breaks[0]]*DEGREE, breaks, [breaks[-1]]*DEGREE]


def _design(values, knots):
    lo, hi = knots[DEGREE], knots[-DEGREE-1]
    return BSpline.design_matrix(np.clip(values, lo, hi), knots, DEGREE).tocsr()


def _tensor(bu, bv):
    """Row-wise Kronecker product of two B-spline design matrices."""
    rows, size = bu.shape[0], DEGREE+1
    iu, vu = bu.indices.reshape(rows, size), bu.data.reshape(rows, size)
    iv, vv = bv.indices.reshape(rows, size), bv.data.reshape(rows, size)
    columns = (iu[:, :, None]*bv.shape[1]+iv[:, None, :]).reshape(rows, -1)
    values = (vu[:, :, None]*vv[:, None, :]).reshape(rows, -1)
    return sp.csr_matrix((values.ravel(), (np.repeat(np.arange(rows), size*size), columns.ravel())),
                         shape=(rows, bu.shape[1]*bv.shape[1]))


def _roughness(nu, nv):
    def second(n):
        return sp.diags([np.ones(n-2), -2*np.ones(n-2), np.ones(n-2)], [0, 1, 2], shape=(max(n-2, 0), n))

    def first(n):
        return sp.diags([-np.ones(n-1), np.ones(n-1)], [0, 1], shape=(n-1, n))
    iu, iv = sp.identity(nu), sp.identity(nv)
    return sp.vstack([sp.kron(second(nu), iv), sp.kron(iu, second(nv)),
                      math.sqrt(2)*sp.kron(first(nu), first(nv))]).tocsr()


class HeightField:
    """A cubic B-spline height over the patch's projection plane.

    The surface is origin + s*e1 + t*e2 + h(s, t)*e3. Its poles sit on the
    Greville grid, which makes it an ordinary B-spline surface for OCC.
    """
    kind = 'bspline'

    def __init__(self, origin, axes, ubreaks, vbreaks, heights):
        self.origin = origin
        self.e1, self.e2, self.e3 = axes
        self.ubreaks, self.vbreaks = ubreaks, vbreaks
        self.uknots = None if ubreaks is None else _clamped(ubreaks)
        self.vknots = None if vbreaks is None else _clamped(vbreaks)
        self.heights = heights
        self.error = self.sample_error = 0.0

    def local(self, points):
        relative = points-self.origin
        return np.c_[relative @ self.e1, relative @ self.e2], relative @ self.e3

    def height(self, st):
        matrix = _tensor(_design(st[:, 0], self.uknots), _design(st[:, 1], self.vknots))
        return matrix @ self.heights.ravel()

    def inside(self, st):
        return ((st[:, 0] >= self.ubreaks[0]) & (st[:, 0] <= self.ubreaks[-1])
                & (st[:, 1] >= self.vbreaks[0]) & (st[:, 1] <= self.vbreaks[-1]))

    def parameters(self, points):
        return self.local(points)[0]

    def at(self, st):
        return self.origin+np.outer(st[:, 0], self.e1)+np.outer(st[:, 1], self.e2)+np.outer(self.height(st), self.e3)

    def project(self, points):
        """Move points along e3 onto the surface."""
        st, h = self.local(points)
        return points+np.outer(self.height(st)-h, self.e3)

    def distance(self, points):
        """Vertical distance, an upper bound on the true distance."""
        st, h = self.local(points)
        return np.abs(self.height(st)-h)

    def poles(self):
        def greville(knots, count):
            return np.asarray([knots[i+1:i+DEGREE+1].mean() for i in range(count)])
        gu = greville(self.uknots, self.heights.shape[0])
        gv = greville(self.vknots, self.heights.shape[1])
        return (self.origin+gu[:, None, None]*self.e1+gv[None, :, None]*self.e2
                + self.heights[:, :, None]*self.e3)


def _plane(points):
    center = points.mean(axis=0)
    normal = np.linalg.svd(points-center, full_matrices=False)[2][2]
    return center, normal, float(np.max(np.abs((points-center) @ normal)))


def _interior(corners, spacing):
    """Centroids of the facets bisected until no edge exceeds its spacing.

    Halving the longest edge keeps needles narrow, so a long, thin facet
    gets a row of samples along its length rather than a full grid.
    """
    found = []
    for _ in range(MAX_BISECTIONS):
        edges = np.linalg.norm(np.roll(corners, -1, axis=1)-corners, axis=2)
        longest = np.argmax(edges, axis=1)
        split = edges[np.arange(len(corners)), longest] > spacing
        found.append(corners[~split].mean(axis=1))
        corners, spacing, longest = corners[split], spacing[split], longest[split]
        if not len(corners):
            break
        # Rotate each facet so its longest edge runs from corner 0 to 1.
        corners = np.take_along_axis(corners, ((longest[:, None]+np.arange(3)) % 3)[:, :, None], axis=1)
        middle = (corners[:, 0]+corners[:, 1])/2
        corners = np.concatenate((np.stack((corners[:, 0], middle, corners[:, 2]), axis=1),
                                  np.stack((middle, corners[:, 1], corners[:, 2]), axis=1)))
        spacing = np.r_[spacing, spacing]
    else:
        found.append(corners.mean(axis=1))
    return np.vstack(found)


def _samples(facets, triangles, spacing, boundary, interior_spacing):
    """Points on the patch's facets, and whether each is on its boundary.

    Every edge is sampled along its length and every facet across its
    interior, at about the spacing of the knots there. The samples lie on
    the flat facets. A CAD exporter keeps those chords within its own
    deviation of the designed surface, so they bound the fit between sparse
    vertices; estimating a curve from vertex normals instead bulges wrongly
    along long, twisted fan triangles. The interior samples keep the
    surface from rippling inside large or long facets, which edge samples
    alone leave free. An edge is on the boundary when both its vertices are.
    """
    f = facets.faces[triangles]
    edges = np.unique(np.sort(np.stack((f, np.roll(f, -1, axis=1)), axis=2).reshape(-1, 2), axis=1), axis=0)
    p0, p1 = facets.points[edges[:, 0]], facets.points[edges[:, 1]]
    on_boundary = boundary[edges[:, 0]] & boundary[edges[:, 1]]
    # Boundaries are sampled twice as densely: the seam curve is built there.
    step = np.where(on_boundary, spacing/2, spacing)
    count = np.clip(np.ceil(np.linalg.norm(p1-p0, axis=1)/step), 1, 512).astype(np.int64)
    index = np.repeat(np.arange(len(edges)), count)
    t = ((np.arange(count.sum())-np.repeat(np.cumsum(count)-count, count)+.5)/np.repeat(count, count))[:, None]
    inner = _interior(facets.points[f], interior_spacing)
    return (np.vstack((p0[index]*(1-t)+p1[index]*t, inner)),
            np.r_[on_boundary[index], np.zeros(len(inner), dtype=bool)])


def _span_width(breaks, values):
    span = np.clip(np.searchsorted(breaks, values, 'right')-1, 0, len(breaks)-2)
    return np.diff(breaks)[span]


def _refined(breaks, values, limit, smallest):
    """Breaks with every span holding a value halved, or None at the limit.

    Spans narrower than twice `smallest` stay whole: the samples are
    spaced by span width, and ever-narrower spans would let the surface
    ripple between them where conflicting data asked for a crease.
    """
    if not len(values) or len(breaks)-1 >= limit:
        return None
    span = np.clip(np.searchsorted(breaks, values, 'right')-1, 0, len(breaks)-2)
    span = span[breaks[span+1]-breaks[span] >= 2*smallest]
    if not len(span):
        return None
    marked, counts = np.unique(span, return_counts=True)
    room = limit-(len(breaks)-1)
    if len(marked) > room:
        marked = marked[np.argsort(-counts, kind='stable')[:room]]
    return np.sort(np.r_[breaks, (breaks[marked]+breaks[marked+1])/2])


def margin(facets, triangles):
    """Triangles one step across the patch's smooth boundary edges."""
    inside = np.zeros(len(facets.faces), dtype=bool)
    inside[triangles] = True
    halves = (3*np.asarray(triangles)[:, None]+np.arange(3)).ravel()
    twins = facets.twin[halves]
    across = facets.owner[twins[(twins >= 0) & ~facets.crease[halves]]]
    return np.unique(across[~inside[across] & ~facets.sliver[across]])


def fit(facets, triangles, tolerance, plane_tolerance=None, around=None):
    """A PlaneFit or HeightField within tolerance of the patch, or None.

    Every vertex must lie within half the tolerance and the facets (edges
    and interiors) within the tolerance. On the patch boundary, which the
    neighbor fits as well, both limits are halved, so two neighbors stay
    within the tolerance of each other there. A flat patch becomes a plane
    when its vertices are within plane_tolerance (a quarter of the
    tolerance). Slivers are left out when the patch has other triangles:
    they have no area to fit, and the long edge of a T-junction fan can lie
    over a different part of the patch in projection.

    Once a smooth surface fits, it is solved once more on the same knots
    while also following the `around` triangles, lightly and without
    limits, and kept that way if the patch still fits. It then continues
    into its smooth neighbors as they do, so their shared curve can smooth
    the mesh's steps between triangles and stay on both surfaces.
    """
    triangles = np.asarray(triangles, dtype=np.int64)
    solid = triangles[~facets.sliver[triangles]]
    if len(solid):
        triangles = solid
    vertices = np.unique(facets.faces[triangles])
    points = facets.points[vertices]
    if len(vertices) < 3:
        return None
    center, normal, deviation = _plane(points)
    limit = tolerance/4 if plane_tolerance is None else plane_tolerance
    axis = _mean_normal(facets, triangles)
    if axis is None:
        return None
    if deviation <= limit:
        return PlaneFit(center, normal if normal @ axis >= 0 else -normal, deviation)
    if len(triangles) < 2 or np.min(facets.normals[triangles] @ axis) < math.cos(math.radians(MAX_TILT+15)):
        return None
    reference = np.linalg.svd((points-center)-np.outer((points-center) @ axis, axis), full_matrices=False)[2][0]
    e1 = reference-axis*(reference @ axis)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    field = HeightField(center, (e1, e2, axis), None, None, None)
    st, h = field.local(points)
    # The projection must keep every facet's orientation, or two parts of
    # the patch would share one (s, t) and no height field could fit.
    corners, _ = field.local(facets.points[facets.faces[triangles]].reshape(-1, 3))
    corners = corners.reshape(-1, 3, 2)
    signed = ((corners[:, 1, 0]-corners[:, 0, 0])*(corners[:, 2, 1]-corners[:, 0, 1])
              - (corners[:, 1, 1]-corners[:, 0, 1])*(corners[:, 2, 0]-corners[:, 0, 0]))
    if np.any(signed[~facets.sliver[triangles]] <= 0):
        return None
    around = np.zeros(0, dtype=np.int64) if around is None else np.asarray(around, dtype=np.int64)
    if len(around):
        outside, _ = field.local(facets.points[facets.faces[around]].reshape(-1, 3))
        outside = outside.reshape(-1, 3, 2)
        facing = ((outside[:, 1, 0]-outside[:, 0, 0])*(outside[:, 2, 1]-outside[:, 0, 1])
                  - (outside[:, 1, 1]-outside[:, 0, 1])*(outside[:, 2, 0]-outside[:, 0, 0])) > 0
        around, outside = around[facing], outside[facing]
    extra = np.setdiff1d(np.unique(facets.faces[around]), vertices)
    extra_st, extra_h = field.local(facets.points[extra])
    low, high = st.min(axis=0), st.max(axis=0)
    size = high-low
    if len(extra):
        low, high = np.minimum(low, extra_st.min(axis=0)), np.maximum(high, extra_st.max(axis=0))
    pad = .03*size.max()+tolerance
    low, high = low-pad, high+pad
    spans = np.maximum(1, np.round(4*size/size.max())).astype(np.int64)
    smallest = (high-low).max()/(4*MAX_SPANS)
    ubreaks = np.linspace(low[0], high[0], spans[0]+1)
    vbreaks = np.linspace(low[1], high[1], spans[1]+1)
    inside = np.zeros(len(facets.faces), dtype=bool)
    inside[triangles] = True
    halves = (3*triangles[:, None]+np.arange(3)).ravel()
    twins = facets.twin[halves]
    open_halves = halves[(twins < 0) | ~inside[facets.owner[np.maximum(twins, 0)]]]
    boundary = np.zeros(len(facets.points), dtype=bool)
    boundary[facets.half[open_halves].ravel()] = True
    on_boundary = boundary[vertices]
    vertex_weight = np.where(on_boundary, 4.0, 1.0)
    vertex_limit = np.where(on_boundary, tolerance/4, tolerance/2)
    for _ in range(16):
        spacing = min(np.diff(ubreaks).min(), np.diff(vbreaks).min())/2
        local = np.minimum(_span_width(ubreaks, corners[..., 0]), _span_width(vbreaks, corners[..., 1])).min(axis=1)
        samples, sample_boundary = _samples(facets, triangles, spacing, boundary, local)
        sample_st, sample_h = field.local(samples)
        data_st, data_h = np.vstack((st, sample_st)), np.r_[h, sample_h]
        weights = np.r_[vertex_weight, np.where(sample_boundary, 1.0, .25)]
        limits = np.r_[vertex_limit, np.where(sample_boundary, tolerance/2, tolerance)]
        uknots, vknots = _clamped(ubreaks), _clamped(vbreaks)
        matrix = _tensor(_design(data_st[:, 0], uknots), _design(data_st[:, 1], vknots))
        nu, nv = len(ubreaks)-1+DEGREE, len(vbreaks)-1+DEGREE
        rough = _roughness(nu, nv)

        def solve(matrix, weights, values):
            normal_matrix = (matrix.T @ sp.diags(weights) @ matrix).tocsc()
            smoothing = 1e-3*normal_matrix.diagonal().mean()
            return spla.spsolve((normal_matrix+smoothing*(rough.T @ rough)).tocsc(), matrix.T @ (weights*values))
        heights = solve(matrix, weights, data_h)
        if not np.all(np.isfinite(heights)):
            return None
        residual = np.abs(matrix @ heights-data_h)
        bad = residual > limits
        if not bad.any():
            if len(around):
                local = np.minimum(_span_width(ubreaks, outside[..., 0]), _span_width(vbreaks, outside[..., 1])).min(axis=1)
                guide = np.vstack((facets.points[extra], _samples(facets, around, spacing, boundary, local)[0]))
                guide_st, guide_h = field.local(guide)
                guided = solve(sp.vstack((matrix, _tensor(_design(guide_st[:, 0], uknots), _design(guide_st[:, 1], vknots)))).tocsr(),
                               np.r_[weights, np.full(len(guide), .1)], np.r_[data_h, guide_h])
                guided_residual = np.abs(matrix @ guided-data_h)
                if np.all(np.isfinite(guided)) and np.all(guided_residual <= limits):
                    heights, residual = guided, guided_residual
            field.ubreaks, field.vbreaks = ubreaks, vbreaks
            field.uknots, field.vknots = uknots, vknots
            field.heights = heights.reshape(nu, nv)
            field.error = float(residual[:len(st)].max())
            field.sample_error = float(residual[len(st):].max(initial=0))
            return field
        refined_u = _refined(ubreaks, data_st[bad, 0], MAX_SPANS, smallest)
        refined_v = _refined(vbreaks, data_st[bad, 1], MAX_SPANS, smallest)
        if refined_u is None and refined_v is None:
            return None
        ubreaks = ubreaks if refined_u is None else refined_u
        vbreaks = vbreaks if refined_v is None else refined_v
    return None


class Patch:
    def __init__(self, triangles, surface):
        self.triangles, self.surface = triangles, surface


def fit_patches(facets, tolerance, progress=lambda message: None, cylinders=True):
    """Patches with fitted surfaces covering every triangle exactly once.

    A smooth region that one cylinder follows becomes one patch (unless
    `cylinders` is false). Other regions are split until each faces one
    direction, and a patch that no surface follows is split along its
    strongest creases, then by facet direction. A single triangle is always
    its own plane. Finally stray triangles join the patch around them when
    its surface fits, and every sliver joins the patch across its longest
    edge.
    """
    pending, patches = [], []
    for region in regions(facets):
        cylinder = fit_cylinder(facets, region, tolerance) if cylinders else None
        if cylinder is None:
            pending.extend(_tilted(facets, region, MAX_TILT))
        else:
            patches.append(Patch(region, cylinder))
    while pending:
        if len(patches)+len(pending) > MAX_PATCHES:
            raise ValueError('The mesh needs too many separate surfaces to fit.')
        triangles = pending.pop()
        surface = fit(facets, triangles, tolerance, around=margin(facets, triangles))
        if surface is not None:
            patches.append(Patch(triangles, surface))
            continue
        parts = split(facets, triangles)
        if parts:
            pending.extend(parts)
            continue
        for triangle in triangles.tolist():
            single = np.asarray([triangle])
            surface = fit(facets, single, tolerance, plane_tolerance=math.inf)
            if surface is None:
                raise ValueError('A degenerate triangle could not form a face.')
            patches.append(Patch(single, surface))
        if len(patches) % 50 == 0:
            progress('Fitting smooth surfaces (%d)' % len(patches))
    labels = np.empty(len(facets.faces), dtype=np.int64)
    for index, patch in enumerate(patches):
        labels[patch.triangles] = index
    labels = settle_slivers(facets, tidy(facets, labels, [patch.surface for patch in patches], tolerance))
    order = np.argsort(labels, kind='stable')
    groups = np.split(order, np.flatnonzero(np.diff(labels[order]))+1)
    return [Patch(group, patches[labels[group[0]]].surface) for group in groups]


def _accepts(facets, surface, triangle, tolerance):
    """Whether the surface fits a triangle as if it were on its boundary."""
    corners = facets.points[facets.faces[triangle]]
    if surface.kind == 'bspline':
        st, _ = surface.local(corners)
        signed = ((st[1, 0]-st[0, 0])*(st[2, 1]-st[0, 1])-(st[1, 1]-st[0, 1])*(st[2, 0]-st[0, 0]))
        if signed <= 0 or not surface.inside(st).all():
            return False
    middles = np.vstack((corners.mean(axis=0), (corners+np.roll(corners, 1, axis=0))/2))
    return bool(surface.distance(corners).max() <= tolerance/4 and surface.distance(middles).max() <= tolerance/2)


def tidy(facets, labels, surfaces, tolerance):
    """Labels with stray triangles joined to the patch around them.

    Splits assign whole triangles, so a boundary between two smooth patches
    steps from triangle to triangle, and a lone triangle can end up inside
    another patch. A triangle sharing two or three edges with one other
    patch joins it when that patch's surface fits it within its boundary
    limits; the boundary then runs straighter and the island disappears.
    """
    labels = np.asarray(labels).copy()
    twin = facets.twin
    neighbors = np.where(twin >= 0, facets.owner[np.maximum(twin, 0)], -1).reshape(-1, 3)
    for _ in range(16):
        around = np.where(neighbors >= 0, labels[np.maximum(neighbors, 0)], -1)
        a, b, c = around.T
        target = np.where((a == b) | (a == c), a, np.where(b == c, b, -1))
        moved = 0
        for triangle in np.flatnonzero((target >= 0) & (target != labels) & ~facets.sliver).tolist():
            near = [int(labels[n]) for n in neighbors[triangle] if n >= 0]
            best = max(set(near), key=near.count)
            if best == labels[triangle] or near.count(best) < 2:
                continue
            if _accepts(facets, surfaces[best], triangle, tolerance):
                labels[triangle] = best
                moved += 1
        if not moved:
            break
    return labels


def settle_slivers(facets, labels):
    """Labels with every sliver joined to the patch across its longest edge.

    A sliver has no area, so either side of its long edge is geometrically
    right. Exporters close T-junctions with fans of them; left on their short
    side, they give the patch outline a zero-width spike that no trimmed face
    can follow. Across the long edge, the outline runs along the short edges
    on the same line instead. A chain of slivers follows to its end.
    """
    labels = np.asarray(labels).copy()
    slivers = np.flatnonzero(facets.sliver)
    if not len(slivers):
        return labels
    corners = facets.points[facets.faces[slivers]]
    lengths = np.linalg.norm(np.roll(corners, -1, axis=1)-corners, axis=2)
    across = facets.twin[3*slivers+np.argmax(lengths, axis=1)]
    pointer = np.arange(len(facets.faces))
    pointer[slivers] = np.where(across >= 0, facets.owner[np.maximum(across, 0)], slivers)
    for _ in range(64):
        following = pointer[pointer]
        if np.array_equal(following, pointer):
            break
        pointer = following
    return labels[pointer]


class Chain:
    """A boundary between two patches (right is -1 on an open border).

    It is smooth when it crosses no sharp edge: the two surfaces continue
    into each other there, and the mesh edges only step between triangles.
    `halves` are its mesh half-edges, on the left patch's side. A `loose`
    chain is a whole loop with no corner, closed at an arbitrary vertex
    that no other chain touches.
    """

    def __init__(self, vertices, left, right, smooth=False, halves=(), loose=False):
        self.vertices, self.left, self.right, self.smooth = vertices, left, right, smooth
        self.halves = list(halves)
        self.loose = loose


def boundaries(facets, labels):
    """Shared boundary chains and, per patch, its loops of (chain, forward).

    Loops follow the triangles' orientation, so the outer loop runs
    counterclockwise around the patch normal and holes run clockwise.
    Chains end where three patches meet or the neighbor changes. A loop
    with no such vertex is one closed chain, which starts and ends at the
    same vertex.
    """
    half, owner, twin = facets.half, facets.owner, facets.twin
    label = labels[owner]
    other = np.where(twin >= 0, labels[owner[np.maximum(twin, 0)]], -1)
    border = np.flatnonzero(label != other)
    following = {}
    for h in border.tolist():
        # Turn around the end vertex through the patch's own triangles
        # until a border half-edge leaves it; this also handles patches
        # that touch themselves at a single vertex.
        step = 3*(h//3)+(h % 3+1) % 3
        while other[step] == label[step]:
            step = int(twin[step])
            step = 3*(step//3)+(step % 3+1) % 3
        following[h] = step
    around = {}
    for h in border.tolist():
        for vertex in half[h].tolist():
            around.setdefault(vertex, set()).update((int(label[h]), int(other[h])))
    corners = {vertex for vertex, seen in around.items() if len(seen) >= 3}
    loops, seen = [], set()
    for start in border.tolist():
        if start in seen:
            continue
        loop, h = [], start
        while h not in seen:
            seen.add(h)
            loop.append(h)
            h = following[h]
        loops.append(loop)

    # A sharp edge that turns sharply has a real corner there; one smooth
    # curve across it would round it off and could cross its neighbors.
    # Between smooth patches the mesh edges step from triangle to triangle,
    # and the curve rightly smooths those steps instead.
    points = facets.points
    for loop in loops:
        loop = np.asarray(loop)
        start = points[half[loop, 0]]
        incoming = start-np.roll(start, 1, axis=0)
        outgoing = np.roll(start, -1, axis=0)-start
        cosine = np.einsum('ij,ij->i', incoming, outgoing)/np.maximum(
            np.linalg.norm(incoming, axis=1)*np.linalg.norm(outgoing, axis=1), 1e-300)
        kink = (cosine < math.cos(math.radians(KINK_ANGLE))) & facets.crease[loop] & facets.crease[np.roll(loop, 1)]
        corners.update(half[loop[kink], 0].tolist())

    chains, canonical, result = [], {}, {}
    for loop in loops:
        patch = int(label[loop[0]])
        found = [i for i, h in enumerate(loop) if half[h, 0] in corners or other[h] != other[loop[i-1]]]
        loose = not found
        # A loop along one neighbor with no corner, such as a hole's rim,
        # is one closed chain. Both sides start it at its lowest vertex.
        found = found or [int(np.argmin(half[loop, 0]))]
        runs = []
        for j, begin in enumerate(found):
            count = (found[(j+1) % len(found)]-begin) % len(loop) or len(loop)
            edges = [loop[(begin+i) % len(loop)] for i in range(count)]
            vertices = [int(half[e, 0]) for e in edges]+[int(half[edges[-1], 1])]
            neighbor = int(other[edges[0]])
            forward = neighbor < 0 or patch < neighbor
            key = tuple(vertices) if forward else tuple(vertices[::-1])
            index = canonical.get(key)
            if index is None:
                index = canonical[key] = len(chains)
                chains.append(Chain(list(key), patch if forward else neighbor, neighbor if forward else patch,
                                    neighbor >= 0 and not facets.crease[edges].any(),
                                    edges if forward else [int(twin[e]) for e in edges[::-1]], loose))
            runs.append((index, forward))
        result.setdefault(patch, []).append(runs)
    return chains, result


def _polyline_at(points, cumulative, t):
    """Points at chord-length parameters t along the polyline."""
    segment = np.clip(np.searchsorted(cumulative, t, 'right')-1, 0, len(points)-2)
    span = np.maximum(cumulative[segment+1]-cumulative[segment], 1e-300)
    fraction = np.clip((t-cumulative[segment])/span, 0, 1)[:, None]
    return points[segment]*(1-fraction)+points[segment+1]*fraction


def curve_points(fitted, count):
    """Points at evenly spaced parameters of a fit_curve result."""
    knots, poles = fitted
    return _design(np.linspace(0, 1, count), knots) @ poles


def fit_curve(points, tolerance):
    """A clamped cubic B-spline through both end points, within tolerance.

    Works for 2D and 3D points. Returns (knots, poles) with full end
    multiplicities, or None when the straight line between the ends already
    follows the points. Parameters follow chord length; spans double until
    the curve is close enough to the whole polyline, not only to its
    vertices. Every span is fitted to several polyline samples, so no pole
    is left unconstrained to swing away between sparse points.
    """
    points = np.asarray(points, dtype=float)
    start, end = points[0], points[-1]
    direction = end-start
    length = float(np.linalg.norm(direction))
    if length > 1e-12:
        along = (points-start) @ (direction/length)
        off = np.linalg.norm(points-start-np.outer(along, direction/length), axis=1)
        if off.max() <= tolerance and np.all(along >= -tolerance) and np.all(along <= length+tolerance):
            return None
    steps = np.linalg.norm(np.diff(points, axis=0), axis=1)
    keep = np.r_[True, steps > 1e-9]
    keep[-1] = True
    points = points[keep]
    steps = np.linalg.norm(np.diff(points, axis=0), axis=1)
    if len(points) < 3 or steps.sum() <= 1e-12:
        return None
    cumulative = np.r_[0, np.cumsum(steps)]/steps.sum()
    best = None
    for spans in (1, 2, 4, 8, 16, 32, 64, 128, 256):
        t = np.unique(np.r_[cumulative, np.linspace(0, 1, 8*spans+1)])
        target = _polyline_at(points, cumulative, t)
        knots = _clamped(np.linspace(0, 1, spans+1))
        matrix = _design(t, knots).toarray()
        # Fix both end poles at the end points; fit the inner ones.
        rhs = target-np.outer(matrix[:, 0], start)-np.outer(matrix[:, -1], end)
        inner = np.linalg.lstsq(matrix[:, 1:-1], rhs, rcond=None)[0]
        poles = np.vstack((start, inner, end))
        error = float(np.max(np.linalg.norm(matrix @ poles-target, axis=1)))
        best = (knots, poles)
        if error <= tolerance:
            break
    return best
