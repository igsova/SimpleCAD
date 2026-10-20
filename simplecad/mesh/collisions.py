"""Fast, local triangle-collision estimate for mesh previews (NumPy only).

Previews used to look plausible and then fail the native self-intersection
check on Apply. This finds the same kind of defect early, for the triangles an
edit changed, so the preview can show them. It is advisory: the background
worker's native FreeCAD check stays authoritative and is never relaxed.

Pairs that share a vertex are skipped, as are triangles that only touch. Folded
and collapsed neighbors are reported separately by RegionPlan.validate().
"""
import numpy as np

# Above this many changed triangles the estimate takes too long to be useful
# while editing; Apply's native check still runs on every edit.
PREVIEW_LIMIT = 6000


def changed_triangles(before_points, after_points, before_faces, after_faces):
    """Indices into after_faces whose geometry differs from the source.

    New vertices (extrusion caps) count as moved. Rows are compared only when
    the triangle count is unchanged (Move/Rotate may flip diagonals); an
    extrusion keeps the untouched source triangles' vertex numbers.
    """
    moved = np.ones(len(after_points), dtype=bool)
    common = min(len(before_points), len(after_points))
    moved[:common] = np.any(before_points[:common] != after_points[:common], axis=1)
    changed = moved[after_faces].any(axis=1)
    if after_faces is not before_faces and len(after_faces) == len(before_faces):
        changed |= np.any(before_faces != after_faces, axis=1)
    return np.flatnonzero(changed)


def candidate_pairs(tri, candidates, tolerance, budget=4_000_000):
    """Pairs (candidate, other) whose bounding boxes overlap.

    Sweep along the longest axis of the edited neighborhood. Triangles are
    grouped by their extent on that axis, so a few long slivers or large flat
    triangles do not widen the search window for all the others. Each
    unordered pair is returned once, even when both triangles changed.
    """
    candidates = np.unique(np.asarray(candidates, dtype=np.int64))
    empty = np.zeros(0, dtype=np.int64)
    if not len(candidates):
        return empty, empty
    low, high = tri.min(axis=1)-tolerance, tri.max(axis=1)+tolerance
    # Only triangles near the edited region can collide with it.
    near = np.flatnonzero(np.all(low <= high[candidates].max(axis=0), axis=1)
                          & np.all(high >= low[candidates].min(axis=0), axis=1))
    is_candidate = np.zeros(len(tri), dtype=bool); is_candidate[candidates] = True
    axis = int(np.argmax(high[near].max(axis=0)-low[near].min(axis=0)))
    extent = high[near, axis]-low[near, axis]
    scale = max(float(np.median(extent)), 1e-12)
    groups = np.clip(np.floor(np.log2(np.maximum(extent/scale, 1e-12))), -4, 24).astype(int)
    first, second = [], []
    for group in np.unique(groups):
        members = near[groups == group]
        members = members[np.argsort(low[members, axis], kind='stable')]
        starts_at = low[members, axis]
        width = float((high[members, axis]-starts_at).max())
        start = np.searchsorted(starts_at, low[candidates, axis]-width, 'left')
        stop = np.searchsorted(starts_at, high[candidates, axis], 'right')
        count = stop-start
        # Bound memory: process candidates in slices of about `budget` pairs.
        ends = np.cumsum(count)
        bounds = np.searchsorted(ends, np.arange(budget, ends[-1], budget), 'right') if ends[-1] else []
        for begin, finish in zip(np.r_[0, bounds], np.r_[bounds, len(candidates)]):
            rows = slice(int(begin), int(finish))
            n = count[rows]
            if not n.sum():
                continue
            a = np.repeat(candidates[rows], n)
            b = members[np.repeat(start[rows], n)+np.arange(n.sum())-np.repeat(np.cumsum(n)-n, n)]
            keep = (a != b) & ~(is_candidate[b] & (b < a))
            keep &= np.all(low[a] <= high[b], axis=1) & np.all(high[a] >= low[b], axis=1)
            first.append(a[keep]); second.append(b[keep])
    if not first:
        return empty, empty
    return np.concatenate(first), np.concatenate(second)


def _intervals(points, distances, direction):
    """Where each triangle crosses the other plane, projected on the line."""
    starts = points; ends = np.roll(points, -1, axis=1)
    d0 = distances; d1 = np.roll(distances, -1, axis=1)
    crossing = (d0*d1 <= 0) & (d0 != d1)
    with np.errstate(divide='ignore', invalid='ignore'):
        fraction = np.where(crossing, d0/(d0-d1), 0)
    position = np.einsum('ijk,ik->ij', starts+(ends-starts)*fraction[..., None], direction)
    on_plane = d0 == 0
    vertex = np.einsum('ijk,ik->ij', points, direction)
    valid = crossing | on_plane
    position = np.where(crossing, position, vertex)
    low = np.where(valid, position, np.inf).min(axis=1)
    high = np.where(valid, position, -np.inf).max(axis=1)
    return low, high


def _cross2(a, b):
    return a[..., 0]*b[..., 1]-a[..., 1]*b[..., 0]


def _coplanar_overlap(a, b, normal, tolerance):
    """Strict overlap of coplanar triangles, after projecting to 2D."""
    axis = np.argmax(abs(normal), axis=1)
    keep = np.asarray([[1, 2], [0, 2], [0, 1]])[axis]
    pa = np.take_along_axis(a, keep[:, None, :], axis=2)
    pb = np.take_along_axis(b, keep[:, None, :], axis=2)
    hit = np.zeros(len(a), dtype=bool)
    for i in range(3):
        p, r = pa[:, i], pa[:, (i+1) % 3]-pa[:, i]
        for j in range(3):
            q, s = pb[:, j], pb[:, (j+1) % 3]-pb[:, j]
            # Proper crossing of the two open segments.
            o1 = _cross2(r, q-p); o2 = _cross2(r, q+s-p)
            o3 = _cross2(s, p-q); o4 = _cross2(s, p+r-q)
            scale = np.linalg.norm(r, axis=1)*np.linalg.norm(s, axis=1)*tolerance
            hit |= (o1*o2 < -scale**2) & (o3*o4 < -scale**2)

    def inside(points, triangle):
        centroid = points.mean(axis=1)
        signs = np.stack([_cross2(triangle[:, (k+1) % 3]-triangle[:, k], centroid-triangle[:, k])
                          for k in range(3)], axis=1)
        area = _cross2(triangle[:, 1]-triangle[:, 0], triangle[:, 2]-triangle[:, 0])
        margin = abs(area)[:, None]*tolerance
        return np.all(signs > margin, axis=1) | np.all(signs < -margin, axis=1)
    # One triangle entirely within the other has no crossing edges.
    return hit | inside(pa, pb) | inside(pb, pa)


def intersecting_pairs(tri, a, b, tolerance=1e-6):
    """Boolean mask of pairs (a[i], b[i]) whose triangles truly intersect."""
    if not len(a):
        return np.zeros(0, dtype=bool)
    ta, tb = tri[a], tri[b]
    na = np.cross(ta[:, 1]-ta[:, 0], ta[:, 2]-ta[:, 0])
    nb = np.cross(tb[:, 1]-tb[:, 0], tb[:, 2]-tb[:, 0])
    la, lb = np.linalg.norm(na, axis=1), np.linalg.norm(nb, axis=1)
    usable = (la > 1e-18) & (lb > 1e-18)
    na = na/np.maximum(la, 1e-300)[:, None]; nb = nb/np.maximum(lb, 1e-300)[:, None]
    da = np.einsum('ijk,ik->ij', ta-tb[:, :1], nb)
    db = np.einsum('ijk,ik->ij', tb-ta[:, :1], na)
    da[abs(da) <= tolerance] = 0; db[abs(db) <= tolerance] = 0
    separated = np.all(da > 0, axis=1) | np.all(da < 0, axis=1) | np.all(db > 0, axis=1) | np.all(db < 0, axis=1)
    coplanar = np.all(da == 0, axis=1) & np.all(db == 0, axis=1)
    result = np.zeros(len(a), dtype=bool)
    general = usable & ~separated & ~coplanar
    if general.any():
        direction = np.cross(na[general], nb[general])
        length = np.linalg.norm(direction, axis=1)
        ok = length > 1e-12
        direction = direction/np.maximum(length, 1e-300)[:, None]
        low_a, high_a = _intervals(ta[general], da[general], direction)
        low_b, high_b = _intervals(tb[general], db[general], direction)
        overlap = np.minimum(high_a, high_b)-np.maximum(low_a, low_b) > tolerance
        result[np.flatnonzero(general)] = ok & overlap
    flat = usable & coplanar
    if flat.any():
        result[np.flatnonzero(flat)] = _coplanar_overlap(ta[flat], tb[flat], na[flat], tolerance)
    return result


def find(points, faces, candidates, tolerance=1e-6, limit=PREVIEW_LIMIT):
    """Triangles (indices into faces) in intersections involving candidates.

    Returns None when more than `limit` candidates would make the preview
    estimate too slow for the GUI thread; Apply still checks every triangle.
    """
    candidates = np.asarray(candidates, dtype=np.int64)
    if len(candidates) > limit:
        return None
    points = np.asarray(points, dtype=float); faces = np.asarray(faces, dtype=np.int64)
    tri = points[faces]
    a, b = candidate_pairs(tri, candidates, tolerance)
    shared = np.any(faces[a][:, :, None] == faces[b][:, None, :], axis=(1, 2))
    a, b = a[~shared], b[~shared]
    hit = intersecting_pairs(tri, a, b, tolerance)
    return np.unique(np.r_[a[hit], b[hit]])
