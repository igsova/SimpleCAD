"""Fit selected polygonal loops or faceted walls to native analytic geometry."""
import math
import re

import numpy as np
from scipy.optimize import minimize
import FreeCAD as App
import Part

from ..core import geometry as geo
from ..document import locking
from ..mesh.curved import _basis, _fit_circle, fit_circle_loop


FIT_TOLERANCE = .02


def _unique_points(elements):
    points, seen = [], set()
    for element in elements:
        for vertex in element.Vertexes:
            point = vertex.Point
            key = tuple(round(float(value), 9) for value in (point.x, point.y, point.z))
            if key not in seen:
                seen.add(key)
                points.append(point)
    return points


def _sample_points(elements):
    points = _unique_points(elements)
    has_curves = any(hasattr(el, 'Curve') and not isinstance(el.Curve, Part.Line) for el in elements)
    if len(points) >= 8 and not has_curves:
        return points
    sampled = list(points)
    seen = {tuple(round(float(v), 5) for v in (p.x, p.y, p.z)) for p in points}
    for el in elements:
        if hasattr(el, 'discretize'):
            try:
                for pt in el.discretize(12):
                    key = tuple(round(float(v), 5) for v in (pt.x, pt.y, pt.z))
                    if key not in seen:
                        seen.add(key)
                        sampled.append(pt)
            except Exception:
                pass
        elif hasattr(el, 'Edges'):
            for edge in el.Edges:
                try:
                    for pt in edge.discretize(8):
                        key = tuple(round(float(v), 5) for v in (pt.x, pt.y, pt.z))
                        if key not in seen:
                            seen.add(key)
                            sampled.append(pt)
                except Exception:
                    pass
    return sampled if len(sampled) >= len(points) else points


def _refine_axis(xyz, initial_axis):
    u, v = _basis(initial_axis)
    def loss(angles):
        ax = initial_axis + u * angles[0] + v * angles[1]
        norm = np.linalg.norm(ax)
        if norm < 1e-12:
            return 1e6
        ax = ax / norm
        fit = _fit_circle(xyz, ax)
        if fit is None:
            return 1e6
        return fit[2]
    res = minimize(loss, [0.0, 0.0], method='Nelder-Mead', tol=1e-5)
    best_ax = initial_axis + u * res.x[0] + v * res.x[1]
    norm = np.linalg.norm(best_ax)
    return best_ax / (norm if norm > 1e-12 else 1.0)


def _clean_axis(axis):
    ax = np.array([float(axis[0]), float(axis[1]), float(axis[2])], dtype=float)
    for ref in ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]):
        r = np.array(ref, dtype=float)
        if abs(ax @ r) > 0.995:
            ax = r * math.copysign(1.0, ax @ r)
            return App.Vector(float(ax[0]), float(ax[1]), float(ax[2]))
    for i in range(3):
        if abs(ax[i]) < 1e-4:
            ax[i] = 0.0
        elif abs(abs(ax[i]) - 1.0) < 1e-4:
            ax[i] = math.copysign(1.0, ax[i])
    norm = np.linalg.norm(ax)
    if norm > 1e-12:
        ax = ax / norm
    return App.Vector(float(ax[0]), float(ax[1]), float(ax[2]))


def _snap_to_faces(axis, shape):
    ax = np.array([float(axis.x), float(axis.y), float(axis.z)], dtype=float)
    for f in shape.Faces:
        try:
            s = f.Surface
            if isinstance(s, Part.Plane):
                fn = np.array(tuple(f.normalAt(0, 0)), dtype=float)
                dot = ax @ fn
                if abs(abs(dot) - 1.0) < 0.005:
                    return App.Vector(*(fn * math.copysign(1.0, dot)))
        except Exception:
            pass
    return axis


def _axis_candidates(points, faces=None):
    xyz = np.asarray([tuple(point) for point in points], dtype=float)
    centered = xyz - xyz.mean(axis=0)
    if len(xyz) < 3:
        return xyz, []
    try:
        _, s, vectors = np.linalg.svd(centered.T @ centered)
        min_spread = float((centered @ vectors[-1]).max() - (centered @ vectors[-1]).min())
        if min_spread < 0.05:
            norm_v = vectors[-1] / np.linalg.norm(vectors[-1])
            norm_app = _clean_axis(norm_v)
            return xyz, [np.array([norm_app.x, norm_app.y, norm_app.z], dtype=float)]
    except Exception:
        pass

    candidates = []
    if faces:
        normals = np.asarray([tuple(f.normalAt(0, 0)) for f in faces], dtype=float)
        try:
            _, _, v = np.linalg.svd(normals.T @ normals)
            candidates.append(v[-1] / np.linalg.norm(v[-1]))
        except Exception:
            pass
    try:
        _, _, vectors = np.linalg.svd(centered.T @ centered)
        candidates.extend([row / np.linalg.norm(row) for row in vectors])
    except np.linalg.LinAlgError:
        pass

    for ax in (np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, 1.0])):
        candidates.append(ax)

    scored = []
    for axis in candidates:
        fit = _fit_circle(xyz, axis)
        res = fit[2] if fit is not None else 1e6
        scored.append((res, axis))
    scored.sort(key=lambda item: item[0])

    refined = []
    seen = []
    for res, axis in scored[:2]:
        if res < 1.0:
            axis = _refine_axis(xyz, axis)
        key = tuple(np.round(np.abs(axis), 4))
        if key not in seen:
            seen.append(key)
            refined.append(axis)

    return xyz, refined or [row / np.linalg.norm(row) for row in vectors]


def _clean_point(point):
    pt = [float(point[0]), float(point[1]), float(point[2])]
    for i in range(3):
        if abs(pt[i] - round(pt[i])) < 1e-5:
            pt[i] = float(round(pt[i]))
    return App.Vector(pt[0], pt[1], pt[2])


def _fit_cloud(points, tolerance=FIT_TOLERANCE, faces=None):
    xyz, candidates = _axis_candidates(points, faces)
    best = None
    for axis in candidates:
        fits = []
        fit = _fit_circle(xyz, axis)
        if fit is not None:
            fits.append(fit)
            center, radius = fit[0], fit[1]
            radial = np.linalg.norm((xyz - center) - axis * ((xyz - center) @ axis)[:, None], axis=1)
            if float(radial.max() - radial.min()) > max(0.5, radius * 0.1):
                middle = float(np.median(radial))
                for mask in (radial <= middle, radial >= middle):
                    if int(mask.sum()) >= 8:
                        clustered = _fit_circle(xyz[mask], axis)
                        if clustered is not None:
                            fits.append(clustered)
        for fit in fits:
            center, radius, residual, largest_gap, _, _ = fit
            if largest_gap > math.radians(280) or residual > max(tolerance, radius * .004):
                continue
            score = (residual, largest_gap, -radius)
            if best is None or score < best[0]:
                best = (score, center, axis, radius, residual, largest_gap)
    if best is None:
        raise ValueError('The selected geometry does not form a complete circular loop or cylindrical wall.')
    _, center, axis, radius, residual, largest_gap = best
    axial = (xyz - center) @ axis
    amin, amax = float(axial.min()), float(axial.max())
    height = amax - amin
    if height <= max(geo.EPS, radius * .01, 0.05):
        height = 0.0
    center_v = _clean_point(App.Vector(*center))
    axis_v = _clean_axis(App.Vector(*axis))
    base_v = _clean_point(App.Vector(*(center + axis * amin)))
    return {'center': center_v, 'axis': axis_v,
            'base': base_v,
            'rim_center': center_v,
            'radius': float(radius), 'height': height,
            'residual': float(residual), 'largest_gap': float(largest_gap)}


def _wall_deviation(radius, largest_gap):
    """Inward chord deviation of the faceted wall from its fitted circle."""
    return radius * (1 - math.cos(min(largest_gap, math.pi) / 2))


def _wall_present(shape, fit):
    """True when the fitted cylinder's side surface lies on the shape boundary."""
    if fit['height'] <= geo.EPS:
        return False
    axis = np.asarray(tuple(fit['axis']), dtype=float)
    base = np.asarray(tuple(fit['base']), dtype=float)
    radius = fit['radius']
    reach = _wall_deviation(radius, fit['largest_gap']) + max(.05, radius * .01)
    u, v = _basis(axis)
    mid = base + axis * (fit['height'] * 0.5)
    is_hole = not shape.isInside(App.Vector(*mid), 1e-4, False)
    if is_hole:
        for level in (.2, .5, .8):
            middle = base + axis * (fit['height'] * level)
            for step in range(6):
                angle = (step + .5) * math.pi / 3
                probe = middle + (u * math.cos(angle) + v * math.sin(angle)) * (radius + reach)
                if shape.isInside(App.Vector(*probe), reach * 2, True):
                    return True
        return False
    else:
        for level in (.2, .5, .8):
            middle = base + axis * (fit['height'] * level)
            for step in range(6):
                angle = (step + .5) * math.pi / 3
                probe = middle + (u * math.cos(angle) + v * math.sin(angle)) * radius
                if shape.isInside(App.Vector(*probe), reach, True):
                    return True
        return False


def _rim_pair(shape, fit, tolerance):
    """Pair one selected rim with the opposite rim of the same hole, or None."""
    axis, center, radius = fit['axis'], fit['center'], fit['radius']
    best = None
    for face in shape.Faces:
        try:
            surface = face.Surface
        except Exception:
            continue
        if not isinstance(surface, Part.Plane) or abs(abs(surface.Axis.dot(axis)) - 1) > .01:
            continue
        if abs((face.CenterOfMass - center).dot(axis)) <= max(radius * .02, tolerance * 2):
            continue  # the face carrying the selected rim itself
        for wire in face.Wires:
            other = fit_circle_loop(_sample_points(wire.Edges), max(tolerance * 2, radius * 0.01))
            if other is None or abs(other['radius'] - radius) > max(tolerance * 4, radius * .02):
                continue
            offset = other['center'] - center
            axial = offset.dot(axis)
            if abs(axial) <= max(radius * .02, tolerance * 2):
                continue
            if (offset - axis * axial).Length > max(tolerance * 4, radius * .02):
                continue
            candidate = dict(fit)
            dist = offset.Length
            norm_axis = _clean_axis(offset * (1.0 / dist))
            if norm_axis.dot(axis) >= 0:
                candidate['axis'] = norm_axis
                candidate['base'] = center
            else:
                candidate['axis'] = norm_axis * -1.0
                candidate['base'] = other['center']
            candidate['height'] = float(dist)
            candidate['rim_center'] = fit['center']
            if not _wall_present(shape, candidate):
                continue
            if best is None or candidate['height'] < best['height']:
                best = candidate
    return best


def _expand_edge_loop(shape, edges):
    if not edges:
        return edges

    try:
        w = Part.Wire(Part.__sortEdges__(edges))
        if w.isClosed() and w.Length > 1e-4:
            return edges
    except Exception:
        pass

    # 1. Fast-path: Check if selected edge(s) belong to a closed circular wire in any face
    for edge in edges:
        for f in shape.Faces:
            for w in f.Wires:
                if w.isClosed():
                    if any(we.isSame(edge) for we in w.Edges):
                        fit = fit_circle_loop(_sample_points(w.Edges), 0.05)
                        if fit is not None:
                            return list(w.Edges)

    # 2. Directed graph search with tangent continuation & coplanarity constraint
    v_map = {}
    for edge in shape.Edges:
        for v in edge.Vertexes:
            pt = (round(v.Point.x, 5), round(v.Point.y, 5), round(v.Point.z, 5))
            v_map.setdefault(pt, []).append(edge)

    def edge_vec(edge, from_pt):
        pts = [(round(v.Point.x, 5), round(v.Point.y, 5), round(v.Point.z, 5)) for v in edge.Vertexes]
        to_pt = pts[1] if pts[0] == from_pt else pts[0]
        v = App.Vector(to_pt[0] - from_pt[0], to_pt[1] - from_pt[1], to_pt[2] - from_pt[2])
        norm = v.Length
        return (v * (1.0 / norm) if norm > 1e-9 else App.Vector(0, 0, 0)), to_pt

    expanded = list(edges)
    visited = {e.hashCode() for e in edges}
    plane_normal = None

    for edge in list(edges):
        c_edge = getattr(edge, 'Curve', None)
        v_pts = [(round(v.Point.x, 5), round(v.Point.y, 5), round(v.Point.z, 5)) for v in edge.Vertexes]
        if len(v_pts) < 2:
            continue
        for start_idx in (0, 1):
            curr_pt = v_pts[start_idx]
            prev_pt = v_pts[1 - start_idx]
            d = App.Vector(curr_pt[0] - prev_pt[0], curr_pt[1] - prev_pt[1], curr_pt[2] - prev_pt[2])
            if d.Length < 1e-9:
                continue
            in_vec = d.normalize()

            while True:
                neighbors = [e for e in v_map.get(curr_pt, []) if e.hashCode() not in visited]
                if not neighbors:
                    break
                if isinstance(c_edge, Part.Circle):
                    same_circle = [n for n in neighbors if isinstance(getattr(n, 'Curve', None), Part.Circle)
                                   and abs(n.Curve.Radius - c_edge.Radius) < 1e-3
                                   and (n.Curve.Center - c_edge.Center).Length < 1e-3]
                    if same_circle:
                        neighbors = same_circle
                best_n, best_dot, best_to = None, 0.35, None
                for n in neighbors:
                    out_vec, to_pt = edge_vec(n, curr_pt)
                    dot = in_vec.dot(out_vec)
                    if plane_normal is not None and abs(out_vec.dot(plane_normal)) > 0.15:
                        continue
                    if dot > best_dot or isinstance(getattr(n, 'Curve', None), Part.Circle):
                        best_dot = dot
                        best_n = n
                        best_to = to_pt
                if best_n is None:
                    break
                if plane_normal is None:
                    cross = in_vec.cross(edge_vec(best_n, curr_pt)[0])
                    if cross.Length > 1e-4:
                        plane_normal = cross.normalize()
                visited.add(best_n.hashCode())
                expanded.append(best_n)
                in_vec, _ = edge_vec(best_n, curr_pt)
                curr_pt = best_to
                try:
                    w = Part.Wire(Part.__sortEdges__(expanded))
                    if w.isClosed() and w.Length > 1e-4:
                        return expanded
                except Exception:
                    pass

    return expanded


def _expand_wall_faces(shape, faces):
    if not faces:
        return faces
    e_map = {}
    for f in shape.Faces:
        for e in f.Edges:
            e_map.setdefault(e.hashCode(), []).append(f)

    # Estimate cylinder axis from the selected face(s) and their immediate strip neighbors
    axis = None
    for f in faces:
        try:
            n = f.normalAt(0, 0)
        except Exception:
            continue
        for e in f.Edges:
            for nb in e_map.get(e.hashCode(), []):
                if nb.hashCode() != f.hashCode():
                    try:
                        nb_n = nb.normalAt(0, 0)
                        dot = n.dot(nb_n)
                        if 0.85 < dot < 0.9999:
                            cross = n.cross(nb_n)
                            if cross.Length > 1e-4:
                                axis = cross.normalize()
                                break
                    except Exception:
                        pass
            if axis is not None:
                break
        if axis is not None:
            break

    expanded = list(faces)
    visited = {f.hashCode() for f in faces}
    queue = list(faces)
    while queue:
        curr = queue.pop(0)
        try:
            curr_norm = curr.normalAt(0, 0)
        except Exception:
            continue
        for e in curr.Edges:
            for neighbor in e_map.get(e.hashCode(), []):
                if neighbor.hashCode() not in visited:
                    try:
                        nb_norm = neighbor.normalAt(0, 0)
                    except Exception:
                        continue
                    dot = curr_norm.dot(nb_norm)
                    if dot > 0.85:
                        if axis is not None:
                            if abs(nb_norm.dot(axis)) > 0.08:
                                continue
                            cross = curr_norm.cross(nb_norm)
                            if cross.Length > 1e-4 and abs(abs(cross.normalize().dot(axis)) - 1) > 0.15:
                                continue
                        visited.add(neighbor.hashCode())
                        expanded.append(neighbor)
                        queue.append(neighbor)
    return expanded


def _rim_wall(shape, fit, tolerance):
    """Pair a single selected rim with its adjacent faceted cylindrical wall."""
    if fit.get('largest_gap', 0) > math.radians(70):
        return None
    axis, center, radius = fit['axis'], fit['center'], fit['radius']
    rim_edges = []
    for edge in shape.Edges:
        pts = [v.Point for v in edge.Vertexes]
        if len(pts) == 2:
            off0 = pts[0] - center
            off1 = pts[1] - center
            if abs(off0.dot(axis)) <= max(tolerance * 2, 0.05) and abs(off1.dot(axis)) <= max(tolerance * 2, 0.05):
                if abs((off0 - axis * off0.dot(axis)).Length - radius) <= max(tolerance * 2, radius * 0.02):
                    rim_edges.append(edge)
    if len(rim_edges) < 8:
        return None
    e_map = {}
    for f in shape.Faces:
        for e in f.Edges:
            e_map.setdefault(e.hashCode(), []).append(f)
    wall_faces = []
    for e in rim_edges:
        for f in e_map.get(e.hashCode(), []):
            try:
                fn = f.normalAt(0, 0)
                if abs(fn.dot(axis)) < 0.08:
                    wall_faces.append(f)
            except Exception:
                pass
    if len(wall_faces) < 8:
        return None
    expanded = _expand_wall_faces(shape, wall_faces)
    if len(expanded) < 8:
        return None
    wall_fit = _fit_cloud(_unique_points(expanded), tolerance, faces=expanded)
    if wall_fit['height'] > geo.EPS and abs(wall_fit['radius'] - radius) <= max(tolerance * 4, radius * 0.05):
        candidate = dict(wall_fit)
        candidate['rim_center'] = fit['center']
        if _wall_present(shape, candidate):
            return candidate
    return None


def _selected_elements(shape, names):
    edges, faces = [], []
    for name in names:
        match = re.fullmatch(r'(Edge|Face)([1-9][0-9]*)', name)
        if not match:
            raise ValueError('Select circular edges or faceted cylindrical faces.')
        kind, number = match.groups()
        index = int(number) - 1
        elements = shape.Edges if kind == 'Edge' else shape.Faces
        if index >= len(elements):
            raise ValueError('The selection changed. Select the circular geometry again.')
        (edges if kind == 'Edge' else faces).append(elements[index])
    return edges, faces


def prepare(selection, tolerance=FIT_TOLERANCE):
    if len(selection) != 1:
        raise ValueError('Select one circular edge loop or one faceted cylindrical wall.')
    obj, names = selection[0]
    if obj.Document is None:
        raise ValueError('The selected object is no longer in the document.')
    if obj.TypeId != 'Part::Feature':
        raise ValueError('Use a plain editable Part object. Convert the STL first.')
    if obj.InList or 'SC_Support' in obj.PropertiesList or obj.ExpressionEngine:
        raise ValueError('Make a Part simple copy before fitting analytic geometry.')
    if not obj.Shape or not obj.Shape.Faces:
        raise ValueError('The selected shape is invalid.')
    # FreeCAD can report a viewport/object selection without subelement names
    # (for example after selecting a whole converted STL in the tree).  Treat
    # that as the complete shape so a standalone cylindrical component still
    # opens the fitting dialog instead of silently doing nothing.  For a mixed
    # object this will fail with the normal, actionable fit error below.
    if names:
        locking.require_unlocked(obj, names)
        edges, faces = _selected_elements(obj.Shape, names)
    else:
        edges, faces = list(obj.Shape.Edges), list(obj.Shape.Faces)
        if not edges and not faces:
            raise ValueError('Select a circular edge loop or cylindrical faces first.')
    if edges and len(edges) < 8 and not faces:
        is_closed = False
        try:
            w = Part.Wire(Part.__sortEdges__(edges))
            is_closed = w.isClosed() and w.Length > 1e-4
        except Exception:
            pass
        if not is_closed:
            edges = _expand_edge_loop(obj.Shape, edges)
    if faces and len(faces) < 8:
        faces = _expand_wall_faces(obj.Shape, faces)
    elements = faces or edges
    points = _sample_points(elements)
    if len(points) < 8:
        raise ValueError('Select the complete circular loop or enough cylindrical facets.')
    fit = _fit_cloud(points, tolerance, faces=faces)
    if fit['height'] <= geo.EPS:
        # One selected rim can still belong to a complete hole: pair it with
        # the matching opposite rim or adjacent cylinder wall before deciding what may be replaced.
        fit = _rim_pair(obj.Shape, fit, tolerance) or _rim_wall(obj.Shape, fit, tolerance) or fit
    fit['axis'] = _snap_to_faces(fit['axis'], obj.Shape)
    if fit['height'] == 0:
        fit['kind'] = 'circle'
    else:
        fit['kind'] = 'cylinder'
    fit['obj'], fit['names'], fit['original'] = obj, tuple(names), obj.Shape
    fit['can_replace'] = (len(faces) == len(obj.Shape.Faces)
                          or (not faces and len(edges) == len(obj.Shape.Edges)))

    # Check if selected edges belong to a circular wire on a planar face of the object
    carrying_face, target_wire = None, None
    if edges and not faces:
        edge_hashes = {e.hashCode() for e in edges}
        for f in obj.Shape.Faces:
            try:
                if isinstance(f.Surface, Part.Plane):
                    for w in f.Wires:
                        w_hashes = {we.hashCode() for we in w.Edges}
                        if w_hashes and edge_hashes == w_hashes:
                            carrying_face, target_wire = f, w
                            break
                    if carrying_face is not None:
                        break
            except Exception:
                pass

    fit['carrying_face'] = carrying_face
    fit['target_wire'] = target_wire
    fit['can_replace_rim'] = (carrying_face is not None and target_wire is not None
                              and not locking.whole(obj))

    # A hole inside a larger solid or shell can be rebuilt in place: both faceted rims
    # become circle edges and the faceted wall becomes one cylindrical face.
    # Locked faces block whole-topology edits.
    indices, stale = locking.state(obj)
    max_gap = math.radians(180) if faces else math.radians(70)
    fit['can_cut'] = (fit['kind'] == 'cylinder'
                      and (bool(obj.Shape.Solids) or bool(obj.Shape.Shells))
                      and not fit['can_replace']
                      and fit['largest_gap'] <= max_gap
                      and not locking.whole(obj) and not indices and not stale
                      and _wall_present(obj.Shape, fit))
    return fit


def check(target):
    obj = target['obj']
    if (obj.Document is None or not obj.isValid() or not obj.Shape.isSame(target['original'])
            or obj.InList or 'SC_Support' in obj.PropertiesList):
        raise ValueError('The shape changed. Select the circular geometry again.')
    locking.require_unlocked(obj, target['names'])


def shape_for(target, mode=None):
    mode = mode or target['kind']
    if mode == 'circle':
        center = target.get('rim_center', target['center'])
        edge = Part.makeCircle(target['radius'], center, target['axis'])
        return Part.Wire([edge])
    if mode != 'cylinder' or target['height'] <= geo.EPS:
        raise ValueError('Select two circular rims or cylindrical facets for a cylinder.')
    return Part.makeCylinder(target['radius'], target['height'], target['base'], target['axis'])


def replace_hole(target):
    """Replace the selected faceted hole inside its solid with one cylinder.

    Both faceted rims become analytic circle edges on the surrounding faces
    and the faceted wall becomes a single cylindrical face.  The faceted hole
    is inscribed in its fitted circle, so only the thin slivers between the
    polygon and the true cylinder may change; anything more is rejected.
    """
    from ..mesh.curved import replace_hole as rebuild
    shape = target['original']
    try:
        candidate = rebuild(shape, target['base'], target['axis'], target['radius'],
                            target['height'], tolerance=max(FIT_TOLERANCE, target['residual'] * 4))
    except (RuntimeError, Part.OCCError) as error:
        raise ValueError(str(error) or 'The fitted cylinder could not replace the selected hole.')
    if shape.Solids and len(candidate.Solids) != len(shape.Solids):
        raise ValueError('Replacing the selected hole would break the solid apart.')
    was_valid = shape.isValid()
    if was_valid:
        return geo.validate(candidate)
    return candidate


def replace_rim(target):
    """Replace the selected circular loop on a planar face with an analytic circle edge."""
    shape = target['original']
    if shape.Solids and target.get('can_cut'):
        return replace_hole(target)

    face = target['carrying_face']
    wire = target['target_wire']
    center = target.get('rim_center', target['center'])
    radius = target['radius']
    axis = target['axis']

    u, v = (App.Vector(*w) for w in _basis(np.asarray(tuple(axis), dtype=float)))
    offsets = [v.Point - center for v in wire.Vertexes]
    if len(offsets) < 3:
        offsets = [p - center for p in wire.discretize(12)]
    xy = [(o.dot(u), o.dot(v)) for o in offsets]
    signed = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1])) / 2
    direction = axis if signed > 0 else axis * -1

    c_edge = Part.makeCircle(radius, center, direction)
    c_wire = Part.Wire([c_edge])

    rebuilt = None
    wires = [c_wire if w.isSame(wire) else w for w in face.Wires]
    try:
        rebuilt = Part.makeFace(wires, "Part::FaceMakerBullseye")
    except Exception:
        pass
    if rebuilt is None or not rebuilt.isValid() or len(rebuilt.Wires) != len(wires):
        try:
            rebuilt = Part.Face(face.Surface, wires)
        except Exception:
            pass
    if rebuilt is None or not rebuilt.isValid() or len(rebuilt.Wires) != len(wires):
        circle_rev = c_wire.reversed()
        wires_rev = [circle_rev if w.isSame(wire) else w for w in face.Wires]
        try:
            rebuilt = Part.makeFace(wires_rev, "Part::FaceMakerBullseye")
        except Exception:
            try:
                rebuilt = Part.Face(face.Surface, wires_rev)
            except Exception:
                pass
    if rebuilt is None or not rebuilt.isValid() or len(rebuilt.Wires) != len(wires):
        raise ValueError('The circular face could not be rebuilt with an analytic circle.')
    if rebuilt.normalAt(0, 0).dot(face.normalAt(0, 0)) < 0:
        rebuilt.reverse()

    new_faces = [rebuilt if f.isSame(face) else f for f in shape.Faces]
    try:
        shell = Part.makeShell(new_faces)
        shell.fix(1e-7, 1e-7, max(1e-5, target.get('residual', 0.02) * 4))
        if shape.Solids:
            solid = Part.makeSolid(shell)
            if solid.Volume < 0:
                solid.reverse()
            candidate = solid
        else:
            candidate = shell
    except Exception as e:
        raise ValueError(f'Rebuilding the shape with the analytic circle failed: {e}')

    was_valid = shape.isValid()
    if was_valid and not candidate.isValid():
        raise ValueError('The rebuilt shape is invalid.')
    return candidate


def apply(target, mode=None, replace=False):
    from ..document.operations import transaction
    check(target)
    mode = mode or target['kind']
    obj, doc = target['obj'], target['obj'].Document
    if mode == 'hole':
        if not target.get('can_cut'):
            raise ValueError('Select one complete hole inside an unlocked solid first.')
        # Replacing a hole rebuilds the whole boundary, so no face locks may exist.
        locking.require_unlocked(obj)
        shape = replace_hole(target)
        with transaction(doc, 'Fit analytic hole'):
            obj.Shape = shape
        return obj
    if mode == 'replace_rim':
        if not target.get('can_replace_rim'):
            raise ValueError('Select a complete circular loop on a flat face first.')
        locking.require_unlocked(obj)
        shape = replace_rim(target)
        with transaction(doc, 'Fit analytic circle'):
            obj.Shape = shape
        return obj
    shape = geo.validate(shape_for(target, mode), solid=mode == 'cylinder')
    replace = bool(replace and target['can_replace'])
    with transaction(doc, 'Fit analytic geometry'):
        if replace:
            obj.Shape = shape
        else:
            result = doc.addObject('Part::Feature', 'SimpleAnalytic')
            result.Label = 'Analytic ' + ('Circle' if mode == 'circle' else 'Cylinder')
            result.Shape = shape
            if App.GuiUp:
                result.ViewObject.ShapeColor = obj.ViewObject.ShapeColor
                result.ViewObject.LineColor = obj.ViewObject.LineColor
                result.ViewObject.LineWidth = 2.0
    return obj if replace else result
