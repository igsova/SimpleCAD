"""Curved-surface edits on Part shapes: delete & heal, remove rounds, imprint
or wrap and emboss, fill openings, unwrap and curvature.

Pure Part geometry, with no document selection, view or Undo access, so the
isolated shape worker can run the slow kernel calls (defeaturing, splitting,
filling) and a native crash there cannot take FreeCAD down. Face numbers are
0-based indices into ``shape.Faces``; a BREP round trip keeps their order.
"""
import math

import FreeCAD as App
import Part

from ..core import coincident, geometry as geo

V = App.Vector
CONVEXITY = ('any', 'convex', 'concave')
MODES = ('imprint', 'emboss', 'deboss')


# --- Shared checks ---------------------------------------------------------

def solid_body(shape):
    """The shape as one or more solids, or a clear error for anything else."""
    if shape.isNull() or not shape.Solids:
        raise ValueError('This needs a closed solid. Close its openings with Fill hole first.')
    if sum(len(s.Faces) for s in shape.Solids) != len(shape.Faces):
        raise ValueError('This object mixes solids with loose faces. Separate them first.')
    return shape


def checked(result, source, fewer_faces=False):
    """Reject a result that is invalid, loses a solid, opens a shell or did nothing."""
    if result is None or result.isNull() or not result.isValid():
        raise ValueError('The kernel returned invalid geometry.')
    if len(result.Solids) != len(source.Solids):
        raise ValueError('The result would split or lose a solid.')
    if any(not shell.isClosed() for solid in result.Solids for shell in solid.Shells):
        raise ValueError('The result would leave an opening in the solid.')
    if result.Solids and result.Volume <= geo.EPS:
        raise ValueError('The result has no volume.')
    if fewer_faces and len(result.Faces) >= len(source.Faces):
        raise ValueError('The neighbouring faces could not grow to close the gap.')
    return result


def _single(result):
    """Unwrap a compound holding exactly one solid, as the source objects are."""
    if result.ShapeType == 'Compound' and len(result.Solids) == 1 and len(result.Faces) == len(result.Solids[0].Faces):
        return result.Solids[0]
    return result


# --- Delete & heal ----------------------------------------------------------

def _defeature(shape, faces, keep_others=False):
    try:
        result = checked(_single(shape.defeaturing(faces)), shape, fewer_faces=True)
    except (Part.OCCError, RuntimeError) as error:
        raise ValueError('The neighbouring faces could not grow to close the gap.') from error
    if keep_others and _takes_others(shape, faces, result):
        raise ValueError('Removing these faces would also remove faces next to them.')
    return result


def _samples(face):
    """A few points inside the face, away from its edges."""
    points = [face.valueAt(u, v) for u, v in _domain_points(face, 2)]
    return points or [face.valueAt(u, v) for u, v in _domain_points(face, 5)[:1]]


def _image(face, index, points=None):
    """Where the face of an edited shape that still holds this face's interior
    is in its index, or None.

    A removed face has none: its interior now lies inside or outside the
    solid. A kept face may have grown and still holds its old interior.
    """
    points = _samples(face) if points is None else points
    if not points:
        return None
    reach = max(1e-5, 2 * face.getTolerance(1))
    box = Part.makeCompound([Part.Vertex(point) for point in points]).BoundBox
    for i in index.near(box, reach):
        if all(index.faces[i].distToShape(Part.Vertex(point))[0] <= reach for point in points):
            return i
    return None


def _around(shape, faces):
    """The shape's index and the faces of it whose bounds meet those faces'."""
    index = geo.FaceIndex.build(shape)
    reach = max(1e-5, 2 * shape.getTolerance(1))
    return index, {i for face in faces for i in index.near(face.BoundBox, reach)}


def _takes_others(shape, faces, result):
    """Whether removing faces also took a face beside them that was kept.

    The kernel can fill a whole rounded pocket when only its rounds are
    removed, walls and floor included, and still return a valid solid with
    fewer faces. Only faces whose bounds meet a removed face's are checked.
    """
    source, nearby = _around(shape, faces)
    index = geo.FaceIndex.build(result)
    return any(_image(source.faces[i], index) is None for i in nearby
               if not any(source.faces[i].isSame(face) for face in faces))


def _left(shape, faces, result):
    """The faces of the result that remain of faces removed from the shape.

    Every face of the result near them either holds a kept face's interior or
    is what is left of a removed one: untouched, or rebuilt where an earlier
    removal changed its neighbours, as a corner round is.
    """
    source, nearby = _around(shape, faces)
    index, near = _around(result, faces)
    held = {_image(source.faces[i], index) for i in nearby
            if not any(source.faces[i].isSame(face) for face in faces)}
    return [index.faces[i] for i in sorted(near - held)]


def remove_faces(shape, indices, progress=lambda message: None, keep_others=False):
    """Delete faces and let their neighbours grow until the solid closes again.

    All faces are removed in one kernel call when possible. The kernel may
    return a valid solid with only some of them gone, so what is left of them
    is then tried one face at a time, as all of them are when the single call
    fails; one stubborn round does not block the rest. With keep_others, a
    removal that would also take a face that was not chosen is refused.
    Returns (shape, report) counting the faces actually gone; raises when
    nothing could be removed.
    """
    solid_body(shape)
    indices = sorted(set(int(i) for i in indices))
    if not indices or indices[0] < 0 or indices[-1] >= len(shape.Faces):
        raise ValueError('Select faces of this object to remove.')
    if len(indices) == len(shape.Faces):
        raise ValueError('Keep at least one face; deleting every face removes the object.')
    faces = [shape.Faces[i] for i in indices]
    progress('Removing %d face%s' % (len(faces), '' if len(faces) == 1 else 's'))
    try:
        current = _defeature(shape, faces, keep_others)
    except ValueError:
        if len(faces) == 1:
            raise
        current = shape
    pending = [(face, _samples(face)) for face in _left(shape, faces, current)]
    for n, (face, points) in enumerate(pending, 1):
        # An earlier removal can have rebuilt it again: find where it is now.
        index = geo.FaceIndex.build(current)
        match = _image(face, index, points)
        if match is None:
            continue
        progress('Removing face %d of %d on its own' % (n, len(pending)))
        try:
            current = _defeature(current, [index.faces[match]], keep_others)
        except ValueError:
            pass
    failed = min(len(faces), len(_left(shape, faces, current)))
    if failed == len(faces):
        raise ValueError('None of these faces could be removed: the neighbouring faces cannot grow to close the gap.')
    return current, {'removed': len(faces) - failed, 'failed': failed, 'faces_before': len(shape.Faces),
                     'faces_after': len(current.Faces)}


# --- Rounds -----------------------------------------------------------------

def _domain_points(face, count=3):
    """Interior (u, v) samples that lie on the trimmed face."""
    u0, u1, v0, v1 = face.ParameterRange
    found = []
    for a in [(i + .5) / count for i in range(count)]:
        for b in [(i + .5) / count for i in range(count)]:
            u, v = u0 + (u1 - u0) * a, v0 + (v1 - v0) * b
            try:
                if face.isPartOfDomain(u, v):
                    found.append((u, v))
            except (Part.OCCError, RuntimeError):
                pass
    return found


def is_convex(face, uv=None):
    """Whether the face bulges outward, like a rounded outside edge."""
    u0, u1, v0, v1 = face.ParameterRange
    u, v = uv or ((u0 + u1) / 2, (v0 + v1) / 2)
    p, n = face.valueAt(u, v), face.normalAt(u, v)
    du, dv = (u1 - u0) * .05, (v1 - v0) * .05
    bend = 0.0
    for a, b in ((du, 0.0), (0.0, dv)):
        middle = (face.valueAt(u + a, v + b) + face.valueAt(u - a, v - b)) * .5
        d = (middle - p).dot(n)
        if abs(d) > abs(bend):
            bend = d
    return bend < 0


def round_radius(face):
    """The radius of a face that looks like a round (fillet), else None.

    A partial cylinder, torus or sphere counts; a full-turn cylinder is a hole
    or boss, not a round. A free-form face counts when it is tightly curved
    in one direction with about the same radius everywhere, as fitted rounds
    of converted meshes are.
    """
    surface = face.Surface
    if isinstance(surface, Part.Plane):
        return None
    u0, u1, _, _ = face.ParameterRange
    if isinstance(surface, Part.Cylinder):
        return surface.Radius if u1 - u0 < math.pi - 1e-6 else None
    if isinstance(surface, Part.Toroid):
        return surface.MinorRadius
    if isinstance(surface, Part.Sphere):
        return surface.Radius if face.Area < math.pi * surface.Radius ** 2 else None
    radii = []
    for u, v in _domain_points(face):
        try:
            k1, k2 = face.curvatureAt(u, v)
        except (Part.OCCError, RuntimeError):
            continue
        tight, gentle = max(abs(k1), abs(k2)), min(abs(k1), abs(k2))
        if tight < 1e-9 or gentle > .5 * tight:
            return None  # flat here, or curved alike both ways (a dome, not a round)
        radii.append(1 / tight)
    if len(radii) < 2 or max(radii) > 1.5 * min(radii):
        return None
    return sum(radii) / len(radii)


def find_rounds(shape, max_radius, convexity='any', within=None):
    """Rounds up to max_radius: [{'index', 'radius', 'convex'}], 0-based indices."""
    if convexity not in CONVEXITY:
        raise ValueError('Choose any, convex or concave rounds.')
    if not max_radius > 0:
        raise ValueError('Enter a largest radius above zero.')
    found = []
    for i, face in enumerate(shape.Faces):
        if within is not None and i not in within:
            continue
        try:
            radius = round_radius(face)
        except (Part.OCCError, RuntimeError, ZeroDivisionError):
            continue
        if radius is None or radius > max_radius + 1e-9:
            continue
        convex = is_convex(face)
        if convexity == 'convex' and not convex or convexity == 'concave' and convex:
            continue
        found.append({'index': i, 'radius': radius, 'convex': convex})
    return found


# --- Imprint, emboss and deboss ----------------------------------------------

def frame_at(face, point):
    """Origin, outward normal and an in-surface X direction at a point of a face."""
    u, v = face.Surface.parameter(point)
    origin = face.valueAt(u, v)
    normal = geo.unit(face.normalAt(u, v))
    up = V(0, 0, 1) if abs(normal.z) < .9 else V(1, 0, 0)
    x = geo.unit(up.cross(normal)) if abs(normal.z) < .9 else geo.unit(normal.cross(up).cross(normal))
    return origin, normal, x


def default_font():
    """FreeCAD's bundled single-stroke-friendly font, or '' when it is missing."""
    import os
    path = os.path.join(App.getResourceDir(), 'Mod', 'TechDraw', 'Resources', 'fonts', 'osifont-lgpl3fe.ttf')
    return path if os.path.isfile(path) else ''


def outline(kind, width=10.0, height=10.0, diameter=10.0, sides=6, text='', size=5.0, font=None):
    """A closed outline centred on the XY origin, in mm."""
    if kind == 'rectangle':
        if not (width > geo.EPS and height > geo.EPS):
            raise ValueError('Enter a width and height above zero.')
        w, h = width / 2, height / 2
        return Part.Wire(Part.makePolygon([V(-w, -h, 0), V(w, -h, 0), V(w, h, 0), V(-w, h, 0), V(-w, -h, 0)]))
    if kind == 'circle':
        if not diameter > geo.EPS:
            raise ValueError('Enter a diameter above zero.')
        return Part.Wire(Part.makeCircle(diameter / 2))
    if kind == 'polygon':
        if not (3 <= int(sides) <= 64 and diameter > geo.EPS):
            raise ValueError('Use 3 to 64 sides and a diameter above zero.')
        r, n = diameter / 2, int(sides)
        points = [V(r * math.cos(math.tau * i / n + math.pi / 2), r * math.sin(math.tau * i / n + math.pi / 2), 0)
                  for i in range(n)]
        return Part.Wire(Part.makePolygon(points + points[:1]))
    if kind == 'text':
        if not text.strip():
            raise ValueError('Type the text to draw.')
        if not size > geo.EPS:
            raise ValueError('Enter a text height above zero.')
        if not font:
            raise ValueError('Choose a font file for the text.')
        import os
        folder, name = os.path.split(font)
        letters = Part.makeWireString(text, folder + os.sep, name, size, 0)
        wires = [w for letter in letters for w in letter]
        if not wires:
            raise ValueError('This font has no outlines for that text.')
        compound = Part.makeCompound(wires)
        box = compound.BoundBox
        compound.translate(V(-(box.XMin + box.XMax) / 2, -(box.YMin + box.YMax) / 2, 0))
        return compound
    raise ValueError('Choose a rectangle, circle, polygon or text.')


def place_outline(shape, origin, normal, x, angle=0.0, lift=0.0):
    """Move an XY outline onto the plane through origin with this normal."""
    y = normal.cross(x)
    matrix = App.Matrix(x.x, y.x, normal.x, 0, x.y, y.y, normal.y, 0, x.z, y.z, normal.z, 0, 0, 0, 0, 1)
    placed = shape.copy()
    if angle:
        placed.rotate(V(), V(0, 0, 1), angle)
    placed.transformShape(matrix)
    placed.translate(origin + normal * lift)
    return placed


def _on_profile(profile):
    """A point in the plane of a flat outline (its bounding box centre may not be)."""
    edge = profile.Edges[0]
    return edge.valueAt(edge.FirstParameter)


def _profile_faces(profile):
    wires = [w for w in profile.Wires if w.isClosed()]
    if not wires:
        return None
    try:
        return Part.makeFace(wires, 'Part::FaceMakerBullseye')
    except (Part.OCCError, RuntimeError):
        return None


def _facing(faces, point, direction):
    """Whether the face under point turns its outside toward the drawing."""
    for face in faces:
        if face.distToShape(Part.Vertex(point))[0] > 1e-4:
            continue
        try:
            u, v = face.Surface.parameter(point)
            normal = face.normalAt(u, v)
        except (Part.OCCError, RuntimeError):
            return True
        return normal.dot(direction) < 1e-6
    return True


def project(shape, indices, profile, direction):
    """Edges of the profile projected along direction onto the chosen faces.

    Only the side facing the profile is kept: the back of a cylinder wall
    under the outline is not imprinted.
    """
    targets = [shape.Faces[i] for i in indices]
    d = geo.unit(direction)
    if profile.isNull() or not profile.Edges:
        raise ValueError('The outline has no edges.')
    origin = _on_profile(profile)
    compound = Part.makeCompound(targets)
    # The kernel projects one wire or edge at a time, not a compound.
    pieces = list(profile.Wires)
    pieces += [e for e in profile.Edges if not any(e.isSame(w) for wire in pieces for w in wire.Edges)]
    projected = []
    for piece in pieces:
        try:
            projected.extend(compound.makeParallelProjection(piece, d).Edges)
        except (Part.OCCError, RuntimeError):
            continue  # this part of the outline misses the faces
    front = []
    for edge in projected:
        if edge.Length < geo.EPS:
            continue
        middle = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
        if not _facing(targets, middle, d):
            continue  # the far side of a wall, seen from behind
        depth = (middle - origin).dot(d)
        if depth > 1e-3:
            ray = Part.makeLine(middle - d * depth, middle - d * 1e-3)
            if ray.distToShape(compound)[0] < 1e-4:
                continue  # hidden behind a nearer selected face
        front.append(edge)
    if not front:
        raise ValueError('The outline does not land on the selected faces. Move it over them.')
    return front


class FlatMap:
    """A face flattened into the plane, mapping points both ways.

    A fine triangulation of the face is unwrapped by FreeCAD's flatmesh, which
    keeps lengths nearly unchanged on curved faces and exactly on developable
    ones such as cylinders. Points map through the triangle that holds them.

    A closed face such as a full cylinder wall is cut open along its seam to
    flatten. When the two sides of the cut match, the flat face is repeated
    once beyond each side, so a drawing can run across the seam.
    """

    def __init__(self, face):
        import flatmesh
        import numpy as np
        self.np = np
        work = face.copy()
        work.tessellate(max(.005, min(.05, math.sqrt(face.Area) / 1000)))
        try:
            unwrapper = flatmesh.FaceUnwrapper(work)
            unwrapper.findFlatNodes(5, .95)
            # flatmesh reads the triangulation without the face's own placement.
            matrix = face.Placement.toMatrix()
            rotation = np.array([[matrix.A11, matrix.A12, matrix.A13], [matrix.A21, matrix.A22, matrix.A23],
                                 [matrix.A31, matrix.A32, matrix.A33]])
            self.nodes = np.array(unwrapper.nodes, dtype=float) @ rotation.T + np.array([matrix.A14, matrix.A24,
                                                                                          matrix.A34])
            self.flat = np.array(unwrapper.ze_nodes, dtype=float)[:, :2]
            self.tris = np.array(unwrapper.tris, dtype=int)
        except Exception as error:
            raise ValueError('This face could not be flattened to wrap the drawing.') from error
        if not len(self.tris):
            raise ValueError('This face could not be flattened to wrap the drawing.')
        self.centres = self.nodes[self.tris].mean(axis=1)  # the face itself; copies follow in tris
        self.seam = self._seam(face)
        if self.seam is not None:
            r, t = self.seam
            count = len(self.nodes)
            self.flat = np.vstack([self.flat, self.flat @ r.T + t, (self.flat - t) @ r])
            self.tris = np.vstack([self.tris, self.tris + count, self.tris + 2 * count])
            self.nodes = np.vstack([self.nodes] * 3)

    def _seam(self, face):
        """The rigid flat move (r, t) carrying one side of the seam onto the other, or None.

        Nodes on the seam edge appear twice in the cut-open triangulation, at
        the same 3D point and two flat points.
        """
        np = self.np
        seams = [edge for edge in face.Edges if edge.isSeam(face)]
        if not seams:
            return None
        seams = Part.makeCompound(seams)
        keys = np.round(self.nodes / 1e-6).astype(np.int64)
        _, group, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
        group = group.ravel()
        twice = np.nonzero(counts[group] == 2)[0]
        pairs = twice[np.argsort(group[twice], kind='stable')].reshape(-1, 2)
        pairs = np.array([pair for pair in pairs
                          if seams.distToShape(Part.Vertex(V(*self.nodes[pair[0]])))[0] < 1e-4], dtype=int)
        if len(pairs) < 2:
            return None
        a, b = self.flat[pairs[:, 0]], self.flat[pairs[:, 1]]
        if np.linalg.norm(a - b, axis=1).min() < 1e-3:
            return None
        # The node nearer the first one is on the same side of the cut.
        swap = (np.linalg.norm(b - a[0], axis=1) < np.linalg.norm(a - a[0], axis=1))[:, None]
        a, b = np.where(swap, b, a), np.where(swap, a, b)
        ca, cb = a.mean(axis=0), b.mean(axis=0)
        u, _, vt = np.linalg.svd((a - ca).T @ (b - cb))
        if np.linalg.det(vt.T @ u.T) < 0:
            vt[-1] *= -1
        r = vt.T @ u.T
        t = cb - r @ ca
        span = np.linalg.norm(self.flat.max(axis=0) - self.flat.min(axis=0))
        if np.linalg.norm(a @ r.T + t - b, axis=1).max() > max(.01, span * 1e-3):
            return None  # the sides do not match, as on a sphere or a torus
        return r, t

    def images(self, q):
        """The flat point and its copies across the seam."""
        if self.seam is None:
            return [q]
        r, t = self.seam
        return [q, r @ q + t, r.T @ (q - t)]

    def to_flat(self, point):
        """Flat coordinates of a point on the face, and the 2x3 map of its tangent plane."""
        np = self.np
        p = np.array([point.x, point.y, point.z])
        k = int(np.argmin(((self.centres - p) ** 2).sum(axis=1)))
        a, b, c = self.nodes[self.tris[k]]
        fa, fb, fc = self.flat[self.tris[k]]
        edges = np.array([b - a, c - a])
        jacobian = np.linalg.lstsq(edges, np.array([fb - fa, fc - fa]), rcond=None)[0].T
        return fa + jacobian @ (p - a), jacobian

    def to_surface(self, flat_points):
        """3D points for flat points, or None for any that fall off the face."""
        np = self.np
        q = np.asarray(flat_points, dtype=float)
        a, b, c = (self.flat[self.tris[:, i]] for i in range(3))
        v0, v1 = b - a, c - a
        d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
        det = d00 * d11 - d01 * d01
        det[np.abs(det) < 1e-30] = 1e-30
        result = []
        step = max(1, 2000000 // len(self.tris))  # bounds the temporary arrays to a few MB
        for start in range(0, len(q), step):
            chunk = q[start:start + step]
            v2 = chunk[:, None, :] - a[None, :, :]
            d20, d21 = (v2 * v0).sum(2), (v2 * v1).sum(2)
            l1 = (d11 * d20 - d01 * d21) / det
            l2 = (d00 * d21 - d01 * d20) / det
            l0 = 1 - l1 - l2
            inside = (l0 > -1e-9) & (l1 > -1e-9) & (l2 > -1e-9)
            for row in range(len(chunk)):
                hits = np.nonzero(inside[row])[0]
                if not len(hits):
                    return None
                k = hits[0]
                corners = self.nodes[self.tris[k]]
                point = l0[row, k] * corners[0] + l1[row, k] * corners[1] + l2[row, k] * corners[2]
                result.append(V(*point))
        return result


def wrap_frame(flat_map, anchor, normal, x):
    """Flat origin and unit axes for an outline whose X follows x at anchor."""
    np = flat_map.np
    origin, jacobian = flat_map.to_flat(anchor)
    y = normal.cross(x)
    ex = jacobian @ np.array([x.x, x.y, x.z])
    ey = jacobian @ np.array([y.x, y.y, y.z])
    ex = ex / np.linalg.norm(ex)
    ey = ey - ex * ex.dot(ey)
    ey = ey / np.linalg.norm(ey)
    return origin, ex, ey


def _overlaps_itself(flat_map, profile, origin, ex, ey):
    """Whether the outline, wrapped around a closed face, would run into itself."""
    if flat_map.seam is None:
        return False
    np = flat_map.np
    r, t = flat_map.seam
    m = np.array([ex, ey]).T  # outline XY to flat
    turn = m.T @ r @ m
    move = m.T @ (r @ origin + t - origin)
    other = profile.copy()
    other.rotate(V(), V(0, 0, 1), math.degrees(math.atan2(turn[1, 0], turn[0, 0])))
    other.translate(V(float(move[0]), float(move[1]), 0))
    if profile.distToShape(other)[0] < 1e-3:
        return True
    area = _profile_faces(profile)
    if area is None:
        return False
    try:
        return area.common(_profile_faces(other)).Area > 1e-6
    except (Part.OCCError, RuntimeError, AttributeError):
        return True


def _check_fits(flat_map, profile, frame):
    if _overlaps_itself(flat_map, profile, *frame):
        raise ValueError('The wrapped drawing is longer than the way around this face. Make it smaller.')


def wrap_lines(flat_map, profile, anchor, normal, x):
    """Polylines of an XY outline wrapped onto the mapped face, for previews."""
    origin, ex, ey = wrap_frame(flat_map, anchor, normal, x)
    _check_fits(flat_map, profile, (origin, ex, ey))
    lines = []
    for edge in profile.Edges:
        points = edge.discretize(max(8, min(200, int(edge.Length / .5))))
        mapped = flat_map.to_surface([origin + p.x * ex + p.y * ey for p in points])
        if mapped is None:
            raise ValueError('The wrapped drawing runs off this face. Make it smaller or move it.')
        lines.append(mapped)
    return lines


def wrap(face, profile, anchor, normal, x):
    """Edges of an XY outline wrapped onto a face, keeping its lengths.

    The outline's origin lands on anchor with its X along x. Raises when any
    part of it would run off the face.
    """
    if profile.isNull() or not profile.Edges:
        raise ValueError('The outline has no edges.')
    flat_map = FlatMap(face)
    origin, ex, ey = wrap_frame(flat_map, anchor, normal, x)
    _check_fits(flat_map, profile, (origin, ex, ey))
    edges = []
    for edge in profile.Edges:
        count = max(12, min(400, int(edge.Length / .25)))
        points = edge.discretize(count)
        flat = [origin + p.x * ex + p.y * ey for p in points]
        mapped = flat_map.to_surface(flat)
        if mapped is None:
            raise ValueError('The wrapped drawing runs off this face. Make it smaller or move it.')
        curve = Part.BSplineCurve()
        closed = edge.isClosed() and len(mapped) > 3
        try:
            if closed:
                curve.interpolate(mapped[:-1], PeriodicFlag=True)
            else:
                curve.interpolate(mapped)
        except (Part.OCCError, RuntimeError) as error:
            raise ValueError('Part of the drawing is too small to wrap. Make it larger.') from error
        edges.append(curve.toShape())
    # Lay the edges exactly on the face; neighbouring ends project to the same point.
    try:
        projected = face.project(edges)
    except (Part.OCCError, RuntimeError) as error:
        raise ValueError('The wrapped drawing could not be laid on the face.') from error
    result = [e for e in projected.Edges if e.Length > geo.EPS]
    if not result:
        raise ValueError('The wrapped drawing could not be laid on the face.')
    return result, flat_map, (origin, ex, ey)


def imprint(shape, indices, profile, direction, mode='imprint', depth=0.0, progress=lambda message: None,
            wrapping=None):
    """Split faces along a projected outline; optionally raise or recess it.

    With wrapping = (anchor, normal, x), profile is an XY outline wrapped onto
    the selected face nearest anchor instead, keeping its lengths, and raised
    or recessed along the face normals.

    Returns (shape, report). report['regions'] lists the 0-based indices of
    the faces inside a closed outline when only imprinting.
    """
    if mode not in MODES:
        raise ValueError('Choose imprint, emboss or deboss.')
    indices = sorted(set(int(i) for i in indices))
    if not indices or indices[0] < 0 or indices[-1] >= len(shape.Faces):
        raise ValueError('Select the faces to draw on.')
    if mode != 'imprint':
        solid_body(shape)
        if not depth > geo.EPS:
            raise ValueError('Enter a depth above zero.')
    d = geo.unit(direction)
    if wrapping:
        anchor, normal, x = (V(*v) for v in wrapping)
        indices = [min(indices, key=lambda i: shape.Faces[i].distToShape(Part.Vertex(anchor))[0])]
        progress('Wrapping the outline onto the face')
        edges, flat_map, (flat_origin, ex, ey) = wrap(shape.Faces[indices[0]], profile, anchor, normal, x)
    else:
        progress('Projecting the outline')
        edges = project(shape, indices, profile, d)
    progress('Splitting the faces')
    try:
        result, _, pieces, _, _ = geo.split_faces_locally(shape, [shape.Faces[i] for i in indices], edges)
    except (Part.OCCError, RuntimeError) as error:
        raise ValueError('The outline could not split these faces.') from error
    if not result.isValid():
        # Edges projected onto free-form faces can leave the split a hair off;
        # shape fixing may repair it, and the repaired shape is checked again.
        result = result.copy()
        result.fix(1e-4, 1e-7, 1e-3)
        if not result.isValid() or result.Solids and len(result.Solids) != len(shape.Solids) or any(
                not s.isClosed() for solid in result.Solids for s in solid.Shells):
            raise ValueError('The outline could not split these faces cleanly.')
    area = _profile_faces(profile)
    origin = _on_profile(profile)
    regions = []
    if area is not None:
        for face in (piece for parts in pieces for piece in parts):
            points, triangles = face.tessellate(max(.01, min(.5, math.sqrt(face.Area) / 20)))
            if not triangles:
                continue
            a, b, c = (points[i] for i in triangles[0])
            inside = (a + b + c) * (1 / 3)
            if wrapping:
                # The drawing may run across the seam onto a copy of the flat face.
                backs = [V(float((q - flat_origin).dot(ex)), float((q - flat_origin).dot(ey)), 0)
                         for q in flat_map.images(flat_map.to_flat(inside)[0])]
            else:
                backs = [inside - d * (inside - origin).dot(d)]
            if any(area.isInside(back, 1e-5, True) for back in backs):
                regions.append(face)
    report = {'edges': len(edges), 'regions': [], 'mode': mode, 'wrapped': bool(wrapping)}
    if mode == 'imprint':
        report['regions'] = [i for i, f in enumerate(result.Faces) if any(f.isSame(r) for r in regions)]
        return result, report
    if not regions:
        raise ValueError('Raise and recess need a closed outline over the faces.')
    progress('Raising the outline' if mode == 'emboss' else 'Recessing the outline')
    try:
        if wrapping:
            # Along the face normals, so the raised drawing follows the curve.
            from .offset import slab
            tools = slab(regions, depth if mode == 'emboss' else -depth)
        elif mode == 'emboss':
            tools = [face.extrude(d * -depth) for face in regions]
        else:
            tools = [face.extrude(d * depth) for face in regions]
        changed = result.fuse(tools) if mode == 'emboss' else result.cut(tools)
        changed = _single(changed)
        try:
            refined = _single(changed.removeSplitter())
            if refined.isValid() and len(refined.Solids) == len(changed.Solids):
                changed = refined
        except (Part.OCCError, RuntimeError):
            pass
    except (Part.OCCError, RuntimeError) as error:
        raise ValueError('The raised or recessed shape could not be joined to the solid.') from error
    checked(changed, shape)
    report['volume_change'] = changed.Volume - shape.Volume
    return changed, report


# --- Fill openings ------------------------------------------------------------

def open_loops(shape):
    """Closed wires of free (single-face) edges: the rims of openings."""
    shells = list(shape.Shells)
    if not shells and shape.Faces:
        sewn = Part.makeCompound(shape.Faces).copy()
        sewn.sewShape()
        shells = list(sewn.Shells)
    edges = [e for shell in shells for e in shell.getFreeEdges().Edges]
    if not edges:
        return []
    loops = []
    for group in Part.sortEdges(edges):
        wire = Part.Wire(group)
        if wire.isClosed():
            loops.append(wire)
    return loops


def _planar(wire):
    try:
        return isinstance(Part.Face(wire).Surface, Part.Plane)
    except (Part.OCCError, RuntimeError, ValueError):
        return False


def _smooth_patch(shell, wire):
    """A patch that meets the neighbouring faces tangentially (G1), or None."""
    edges = list(wire.Edges)
    reference = shell
    if len(edges) < 3:
        # The filling kernel needs at least three boundary curves.
        replacements = []
        split = []
        for edge in edges:
            a, b = edge.FirstParameter, edge.LastParameter
            parts = edge.split([a + (b - a) / 3, a + 2 * (b - a) / 3])
            replacements.append((edge, parts))
            split.extend(parts.Edges)
        reference = shell.replaceShape(replacements)
        edges = [e for e in reference.Edges if any(e.isSame(s) for s in split)] or split
    doc = App.newDocument('SimpleCADFill', hidden=True)
    try:
        source = doc.addObject('Part::Feature', 'Source')
        source.Shape = reference
        names, owners = [], []
        for edge in edges:
            index = next((i for i, e in enumerate(reference.Edges, 1) if e.isSame(edge)), None)
            owner = next((i for i, f in enumerate(reference.Faces, 1) if any(e.isSame(edge) for e in f.Edges)), None)
            if index is None or owner is None:
                return None
            names.append((source, 'Edge%d' % index))
            owners.append('Face%d' % owner)
        filling = doc.addObject('Surface::Filling', 'Fill')
        filling.BoundaryEdges = names
        filling.BoundaryFaces = owners
        filling.BoundaryOrder = [1] * len(names)
        doc.recompute()
        patch = filling.Shape
        if patch.isNull() or not patch.Faces or not patch.isValid():
            return None
        return patch.Faces[0]
    except Exception:
        return None
    finally:
        App.closeDocument(doc.Name)


def _coplanar(wires):
    """Whether every wire is flat and in one plane."""
    if not all(_planar(w) for w in wires):
        return False
    plane = Part.Face(wires[0]).Surface
    normal, origin = geo.unit(plane.Axis), plane.Position
    return all(abs((v.Point - origin).dot(normal)) < 1e-6 for w in wires[1:] for v in w.Vertexes)


def _islands(loops):
    """[(outer, [inner, ...])]: each opening with the openings lying inside it.

    Containment is judged across the opening, ignoring its thinnest extent,
    so a rim on a gently curved surface still holds the islands within it.
    """
    def inside(small, big):
        if small is big:
            return False
        a, b = small.BoundBox, big.BoundBox
        spans = [(b.XLength, 'X'), (b.YLength, 'Y'), (b.ZLength, 'Z')]
        thin = min(spans)[1]
        return a.DiagonalLength < b.DiagonalLength - 1e-6 and all(
            getattr(b, axis + 'Min') - 1e-6 <= getattr(a, axis + 'Min') and
            getattr(a, axis + 'Max') <= getattr(b, axis + 'Max') + 1e-6 for axis in 'XYZ' if axis != thin)
    outers = [w for w in loops if not any(inside(w, other) for other in loops)]
    return [(w, [other for other in loops if inside(other, w)]) for w in outers]


def _crosses(patch, faces, rim, tolerance=1e-3):
    """Whether a patch touches or cuts a face that does not meet its rim."""
    box = patch.BoundBox
    box.enlarge(tolerance)
    for face in faces:
        if not box.intersect(face.BoundBox):
            continue
        if any(rim.distToShape(vertex)[0] < tolerance for vertex in face.Vertexes):
            continue  # a neighbour along the rim, or touching one of its corners
        try:
            if patch.distToShape(face)[0] < tolerance:
                return True
        except (Part.OCCError, RuntimeError):
            return True
    return False


def fill(shape, edge_indices=None, smooth=True, progress=lambda message: None):
    """Close openings with patches; a fully closed shell becomes a solid.

    edge_indices (0-based) pick the openings whose rim contains one of those
    edges; None fills every opening. Flat rims get a plane, with flat islands
    inside them left open as holes. Curved rims get a patch tangent to the
    neighbours when smooth, else one only through the rim. A patch that would
    cut through the part is refused. Returns (shape, report).
    """
    loops = open_loops(shape)
    if not loops:
        raise ValueError('This object has no openings to fill.')
    if edge_indices is not None:
        chosen = [shape.Edges[i] for i in edge_indices]
        loops = [w for w in loops if any(e.isSame(c) or coincident.same(e, c) for e in w.Edges for c in chosen)]
        if not loops:
            raise ValueError('The selected edges are not on the rim of an opening.')
    shells = list(shape.Shells) or [Part.Shell(shape.Faces)]
    patches, tangent = [], 0
    groups = _islands(loops)
    for n, (wire, islands) in enumerate(groups, 1):
        progress('Filling opening %d of %d' % (n, len(groups)))
        if islands:
            if not _coplanar([wire] + islands):
                raise ValueError('An opening has another opening inside it. Fill hole cannot make a curved '
                                 'patch with a hole yet; delete the faces around the inner opening first.')
            patches.append(Part.makeFace([wire] + islands, 'Part::FaceMakerBullseye').Faces[0])
            continue
        if _planar(wire):
            patches.append(Part.Face(wire))
            continue
        patch = None
        if smooth:
            owner = next((s for s in shells if any(e.isSame(w) for e in s.Edges for w in wire.Edges)), shells[0])
            patch = _smooth_patch(owner, wire)
            tangent += patch is not None
        if patch is None:
            try:
                patch = Part.makeFilledFace(wire.Edges)
            except (Part.OCCError, RuntimeError) as error:
                raise ValueError('An opening could not be filled; its rim may cross itself.') from error
        patches.append(patch)
    progress('Checking the patches')
    for patch, (wire, islands) in zip(patches, groups):
        if _crosses(patch, shape.Faces, Part.makeCompound([wire] + islands)):
            raise ValueError('A patch would cut through the part. Fill this opening in smaller steps.')
    progress('Joining the patches')
    sewn = Part.makeCompound(list(shape.Faces) + patches)
    sewn.sewShape()
    parts = []
    for shell in sewn.Shells:
        if shell.isClosed():
            solid = Part.Solid(shell)
            if solid.Volume < 0:
                solid.reverse()
            parts.append(solid)
        else:
            parts.append(shell)
    result = parts[0] if len(parts) == 1 else Part.makeCompound(parts)
    if result.isNull() or not result.isValid():
        raise ValueError('The patches could not be joined to the surface.')
    if len(result.Faces) != len(shape.Faces) + len(patches):
        raise ValueError('The patches could not be joined to the surface.')
    return result, {'filled': len(groups), 'tangent': tangent, 'closed': bool(result.Solids) and not
                    any(not s.isClosed() for s in result.Shells), 'solids': len(result.Solids)}


# --- Unwrap ---------------------------------------------------------------------

def _align(face):
    """Lay a flat face on XY: main direction along X, corner at the origin."""
    points = [v.Point for v in face.Vertexes] or [face.CenterOfMass]
    normal = geo.unit(face.normalAt(*face.Surface.parameter(face.CenterOfMass))) if not isinstance(
        face.Surface, Part.Plane) else geo.face_normal(face)
    flat = face.copy()
    rotation = App.Rotation(normal, V(0, 0, 1))
    flat.rotate(V(), rotation.Axis, math.degrees(rotation.Angle))
    points = [v.Point for v in flat.Vertexes]
    if len(points) >= 2:
        cx = sum(p.x for p in points) / len(points)
        cy = sum(p.y for p in points) / len(points)
        sxx = sum((p.x - cx) ** 2 for p in points)
        syy = sum((p.y - cy) ** 2 for p in points)
        sxy = sum((p.x - cx) * (p.y - cy) for p in points)
        angle = .5 * math.atan2(2 * sxy, sxx - syy)
        flat.rotate(V(), V(0, 0, 1), -math.degrees(angle))
    box = flat.BoundBox
    flat.translate(V(-box.XMin, -box.YMin, -box.ZMin))
    return flat


def unwrap(face):
    """Flatten a face to an outline of the same area on XY. Returns (face, report).

    Curved faces are flattened by least-squares conformal mapping of a fine
    triangulation (FreeCAD's flatmesh), so the outline is a fine polygon and
    doubly curved faces stretch slightly; the report gives the area change.
    """
    if face.ShapeType != 'Face':
        raise ValueError('Select one face to unwrap.')
    if isinstance(face.Surface, Part.Plane):
        flat = _align(face)
    else:
        import flatmesh
        work = face.copy()
        work.tessellate(max(.01, min(.5, math.sqrt(face.Area) / 500)))
        try:
            unwrapper = flatmesh.FaceUnwrapper(work)
            unwrapper.findFlatNodes(5, .95)
            loops = unwrapper.getFlatBoundaryNodes()
        except Exception as error:
            raise ValueError('This face could not be unwrapped.') from error
        wires = []
        for loop in loops:
            points = [V(*p) for p in list(loop)]
            if len(points) >= 3:
                wires.append(Part.makePolygon(points + points[:1]))
        if not wires:
            raise ValueError('This face could not be unwrapped.')
        try:
            flat = _align(Part.makeFace(wires, 'Part::FaceMakerBullseye'))
        except (Part.OCCError, RuntimeError) as error:
            raise ValueError('The unwrapped outline crosses itself; split the face first.') from error
    if not flat.isValid() or flat.Area <= geo.EPS:
        raise ValueError('This face could not be unwrapped.')
    box = flat.BoundBox
    return flat, {'area': flat.Area, 'source_area': face.Area,
                  'area_change': flat.Area / face.Area - 1, 'width': box.XLength, 'height': box.YLength}


# --- Curvature --------------------------------------------------------------

def curvature(face, point=None):
    """Principal curvatures at a point, signed: negative bulges outward.

    Returns {'tight', 'gentle'} radii in mm (inf when flat that way) and the
    shape: 'flat', 'convex', 'concave' or 'saddle'.
    """
    if isinstance(face.Surface, Part.Plane):
        return {'tight': math.inf, 'gentle': math.inf, 'kind': 'flat', 'k': (0.0, 0.0)}
    point = face.CenterOfMass if point is None else point
    u, v = face.Surface.parameter(point)
    u0, u1, v0, v1 = face.ParameterRange
    for step in (0.0, 1e-4, 1e-3, 1e-2):
        # Poles and seams have no defined curvature; read it just beside them.
        try:
            k1, k2 = face.curvatureAt(min(max(u + (u1 - u0) * step, u0), u1),
                                      min(max(v - (v1 - v0) * step, v0), v1))
            break
        except (Part.OCCError, RuntimeError):
            continue
    else:
        raise ValueError('The curvature is not defined at this point.')
    if face.Orientation == 'Reversed':
        k1, k2 = -k1, -k2
    if abs(k1) < abs(k2):
        k1, k2 = k2, k1
    eps = 1e-9
    radius = lambda k: math.inf if abs(k) < eps else 1 / abs(k)
    if abs(k1) < eps:
        kind = 'flat'
    elif abs(k2) < eps or k1 * k2 > 0:
        kind = 'convex' if k1 < 0 else 'concave'
    else:
        kind = 'saddle'
    return {'tight': radius(k1), 'gentle': radius(k2), 'kind': kind, 'k': (k1, k2)}


def _radii_near(face, points, grid=16):
    """Tightest bend radius at each point, read from the nearest of a grid of
    surface samples.

    Projecting each point back onto a free-form surface takes about a
    millisecond; evaluating the surface on a grid and taking the nearest
    sample is a hundred times quicker, and plenty for a colour map.
    """
    import numpy as np
    surface = face.Surface
    u0, u1, v0, v1 = face.ParameterRange
    samples, radii = [], []
    for i in range(grid + 1):
        for j in range(grid + 1):
            u, v = u0 + (u1 - u0) * i / grid, v0 + (v1 - v0) * j / grid
            try:
                point = surface.value(u, v)
                tight = max(abs(surface.curvature(u, v, 'Max')), abs(surface.curvature(u, v, 'Min')))
            except (Part.OCCError, RuntimeError):
                continue
            samples.append((point.x, point.y, point.z))
            radii.append(1 / tight if tight > 1e-9 else math.inf)
    if not samples:
        return [math.inf] * len(points)
    grid_points = np.array(samples)
    norms = (grid_points ** 2).sum(1)
    targets = np.array([(p[0], p[1], p[2]) for p in points], dtype=float).reshape(-1, 3)
    nearest = []
    for chunk in range(0, len(targets), 4096):
        # |p - g|^2 = |g|^2 - 2 p.g + |p|^2, and |p|^2 does not change which g is nearest.
        nearest.extend((norms[None, :] - 2 * targets[chunk:chunk + 4096] @ grid_points.T).argmin(1).tolist())
    return [radii[k] for k in nearest]


def _split(nodes, triangles, n):
    """(points, triangles) of a face's triangles, each split evenly into n * n.

    New points lie in the plane of the triangle they split, so the pieces cover
    exactly the same surface as the triangles they came from. Neighbouring
    triangles share the points along their common edge.
    """
    points, corners, edges, pieces = [], {}, {}, []

    def add(*weights):
        points.append(tuple(sum(nodes[i][axis] * w for i, w in weights) / n for axis in range(3)))
        return len(points) - 1

    def corner(i):
        if i not in corners:
            corners[i] = add((i, n))
        return corners[i]

    def edge(p, q):
        """The points strictly between nodes p and q, from p towards q."""
        a, b = min(p, q), max(p, q)
        if (a, b) not in edges:
            edges[a, b] = [add((a, n - s), (b, s)) for s in range(1, n)]
        return edges[a, b] if p == a else edges[a, b][::-1]

    for a, b, c in triangles:
        # grid[i, j] has weight i on b, j on c and the rest on a.
        ab, ac, bc = edge(a, b), edge(a, c), edge(b, c)
        grid = {(0, 0): corner(a), (n, 0): corner(b), (0, n): corner(c)}
        for s in range(1, n):
            grid[s, 0], grid[0, s], grid[n - s, s] = ab[s - 1], ac[s - 1], bc[s - 1]
        for i in range(1, n):
            for j in range(1, n - i):
                grid[i, j] = add((a, n - i - j), (b, i), (c, j))
        for i in range(n):
            for j in range(n - i):
                pieces.append((grid[i, j], grid[i + 1, j], grid[i, j + 1]))
                if i + j < n - 1:
                    pieces.append((grid[i + 1, j], grid[i + 1, j + 1], grid[i, j + 1]))
    return points, pieces


def curvature_mesh(shape, limit=20000, drawn=None):
    """Triangles of the curved faces with the tightest bend radius at each point.

    Returns (points, triangles, radii); flat faces are left out, and radii are
    inf where a point is flat.

    ``drawn`` is the triangulation the 3D view shows for the shape: its points,
    and the triangles of each face in ``shape.Faces`` order. A map of its own
    triangulation sinks behind the shaded faces wherever theirs is coarser and
    a face is hollow, in patches that change as you zoom. On the drawn
    triangles it lies exactly on the shaded faces; they are split evenly for
    colour detail, up to about ``limit`` points. Without ``drawn`` the faces
    are triangulated afresh, coarser until there are at most ``limit`` points.
    """
    curved = [i for i, f in enumerate(shape.Faces) if not isinstance(f.Surface, Part.Plane)]
    if not curved:
        return [], [], []
    if drawn is None:
        deflection = max(.01, shape.BoundBox.DiagonalLength / 400)
        while True:
            # Fresh copies: the kernel keeps a finer triangulation it already has.
            meshes = [shape.Faces[i].copy().tessellate(deflection) for i in curved]
            if sum(len(p) for p, _ in meshes) <= limit or deflection > shape.BoundBox.DiagonalLength:
                break
            deflection *= 2
    else:
        nodes, faces = drawn
        count = sum(len(faces[i]) for i in curved)
        # A triangle split n ways has n * n pieces, about n * n / 2 new points.
        splits = max(1, min(4, int(math.sqrt(2 * limit / max(count, 1)))))
        meshes = [_split(nodes, faces[i], splits) for i in curved]
    points, triangles, radii = [], [], []
    for i, (face_points, face_triangles) in zip(curved, meshes):
        start = len(points)
        points.extend(face_points)
        radii.extend(_radii_near(shape.Faces[i], face_points))
        triangles.extend((a + start, b + start, c + start) for a, b, c in face_triangles)
    return points, triangles, radii


def curvature_range(size):
    """Radii shown red (tight) and blue (gentle) for a model this big (diagonal, mm)."""
    size = max(size, 1e-3)
    return max(.05, size / 200), size / 2


def curvature_color(radius, tight, gentle):
    """Red for tight bends through yellow and green to blue for gentle ones."""
    if radius <= tight:
        t = 0.0
    elif radius >= gentle or math.isinf(radius):
        t = 1.0
    else:
        t = math.log(radius / tight) / math.log(gentle / tight)
    stops = ((0.0, (.9, .15, .1)), (1 / 3, (.95, .85, .1)), (2 / 3, (.2, .8, .3)), (1.0, (.15, .4, .95)))
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            return tuple(a + (b - a) * f for a, b in zip(c0, c1))
    return stops[-1][1]
