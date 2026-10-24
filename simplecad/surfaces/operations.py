"""Document edits of the curved-surface tools, each in one Undo step.

Kernel work runs in the isolated shape worker on a copy of the shape in the
object's own coordinates. The result gets the object's Placement back, so
nothing moves, and it replaces the shape inside one transaction, which also
keeps face colours on the faces they belonged to. A failure or cancel leaves
the document unchanged. Names are FreeCAD's 1-based FaceN/EdgeN.
"""
import math
import re

import FreeCAD as App
import Part

from ..core import geometry as geo
from ..document import locking, operations as ops
from ..modeling import patterns
from ..jobs import shape as shape_jobs
from . import edit as se

V = App.Vector


def indices(obj, names, kind='Face'):
    """0-based indices of FaceN (or EdgeN) names on obj."""
    count = obj.Shape.countElement(kind)
    result = set()
    for name in names:
        match = re.fullmatch(kind + r'([1-9][0-9]*)', name)
        if not match or int(match.group(1)) > count:
            raise ValueError('%s is not a %s of %s. Select again.' % (name, kind.lower(), obj.Label))
        result.add(int(match.group(1)) - 1)
    return sorted(result)


def local(obj):
    """The object's shape in its own coordinates, with the same face order."""
    shape = obj.Shape.copy()
    shape.Placement = App.Placement()
    return shape


def placed(shape, obj):
    shape = shape.copy()
    shape.Placement = obj.Placement.multiply(shape.Placement)
    return shape


def _target(obj):
    ops.editable(obj)
    locking.require_unlocked(obj)
    return obj


def _commit(obj, shape, title):
    geo.validate(shape)
    with ops.transaction(obj.Document, title):
        obj.Shape = placed(shape, obj)
    return obj


def heal_faces(obj, names, dialog=None):
    """Delete faces of a solid and grow the neighbours to close the gap."""
    _target(obj)
    faces = indices(obj, names)
    if not faces:
        raise ValueError('Select the faces to remove.')
    shape = se.solid_body(local(obj))
    result, report = shape_jobs.run('remove_faces', shape, {'faces': faces},
                                    label='Deleting and healing faces', dialog=dialog)
    _commit(obj, result, 'Delete & heal faces')
    return report


def rounds(obj, max_radius, convexity='any', names=()):
    """The rounds a Remove rounds would take away: [{'index', 'radius', 'convex'}]."""
    ops.editable(obj)
    within = set(indices(obj, names)) if names else None
    return se.find_rounds(local(obj), max_radius, convexity, within)


def remove_rounds(obj, max_radius, convexity='any', names=(), dialog=None):
    _target(obj)
    shape = se.solid_body(local(obj))
    found = rounds(obj, max_radius, convexity, names)
    if not found:
        raise ValueError('No %srounds up to %s found.' % ('' if convexity == 'any' else convexity + ' ',
                                                         geo_length(max_radius)))
    # Rounds only: a pocket whose rounds are removed keeps its walls and floor.
    result, report = shape_jobs.run('remove_faces', shape, {'faces': [r['index'] for r in found], 'keep_others': True},
                                    label='Removing %d round%s' % (len(found), '' if len(found) == 1 else 's'),
                                    dialog=dialog)
    report['found'] = len(found)
    _commit(obj, result, 'Remove rounds')
    return report


def geo_length(value):
    return '%.3g mm' % value


# --- Draw on surface -------------------------------------------------------------

def drawing_frame(obj, names, point=None):
    """Local origin, outward normal and in-surface X where the drawing sits."""
    faces = indices(obj, names)
    if not faces:
        raise ValueError('Select the faces to draw on.')
    shape = local(obj)
    if point is not None:
        point = obj.Placement.inverse().multVec(point)
        face = min((shape.Faces[i] for i in faces), key=lambda f: f.distToShape(Part.Vertex(point))[0])
    else:
        face = shape.Faces[faces[0]]
        point = middle(face)
    return se.frame_at(face, point)


def middle(face):
    """A point on the face as far from its edges as possible.

    The centre of mass can lie off a curved face, or in the hole of a ring.
    """
    points, triangles = face.copy().tessellate(max(.01, math.sqrt(face.Area) / 20))
    centre = face.CenterOfMass
    candidates = [centre] if face.isInside(centre, 1e-4, True) else []
    step = max(1, len(triangles) // 150)
    candidates += [(points[a] + points[b] + points[c]) * (1 / 3) for a, b, c in triangles[::step]]
    if not candidates:
        return centre
    rim = Part.makeCompound(face.Edges)
    return max(candidates, key=lambda p: rim.distToShape(Part.Vertex(p))[0])


def drawing(obj, names, outline, point=None, angle=0.0, shift=(0.0, 0.0)):
    """The outline placed on the faces, in local coordinates, and its direction."""
    origin, normal, x = drawing_frame(obj, names, point)
    y = normal.cross(x)
    origin = origin + x * shift[0] + y * shift[1]
    return se.place_outline(outline, origin, normal, x, angle), -normal


def world(shape, obj):
    """A local-coordinate shape of obj, placed in the world for previews."""
    return placed(shape, obj)


def wrapping(obj, names, outline, point=None, angle=0.0, shift=(0.0, 0.0)):
    """The outline turned and moved in its own XY plane, and the local frame it wraps from."""
    origin, normal, x = drawing_frame(obj, names, point)
    profile = outline.copy()
    if angle:
        profile.rotate(V(), V(0, 0, 1), angle)
    profile.translate(V(shift[0], shift[1], 0))
    return profile, (origin, normal, x)


def imprint(obj, names, outline, point=None, angle=0.0, shift=(0.0, 0.0), mode='imprint', depth=0.0,
            dialog=None, wrap=False):
    """Split faces along a projected outline, or raise/recess it by depth.

    With wrap, the outline is wrapped onto the face under point keeping its
    lengths, instead of projected straight. Returns the report; after
    imprinting, report['regions'] holds the FaceN names of the new regions
    inside the outline.
    """
    _target(obj)
    faces = indices(obj, names)
    options = {'faces': faces, 'mode': mode, 'depth': depth}
    if wrap:
        profile, frame = wrapping(obj, names, outline, point, angle, shift)
        options.update(direction=list(-frame[1]), wrapping=[list(v) for v in frame])
    else:
        profile, direction = drawing(obj, names, outline, point, angle, shift)
        options['direction'] = list(direction)
    words = {'imprint': 'Drawing on the surface', 'emboss': 'Raising the drawing', 'deboss': 'Recessing the drawing'}
    result, report = shape_jobs.run('imprint', local(obj), options, profile=profile,
                                    label=words.get(mode, 'Drawing'), dialog=dialog)
    _commit(obj, result, {'imprint': 'Draw on surface', 'emboss': 'Raise drawing',
                          'deboss': 'Recess drawing'}.get(mode, 'Draw on surface'))
    report['regions'] = ['Face%d' % (i + 1) for i in report.get('regions', ())]
    return report


# --- Offset, shell, thicken and draft ----------------------------------------------

def offset_faces(obj, names, distance, dialog=None):
    """Move faces along their normals by distance (outward when positive)."""
    _target(obj)
    faces = indices(obj, names)
    if not faces:
        raise ValueError('Select the faces to offset.')
    result, report = shape_jobs.run('offset_faces', local(obj), {'faces': faces, 'distance': float(distance)},
                                    label='Offsetting %d face%s' % (len(faces), '' if len(faces) == 1 else 's'),
                                    dialog=dialog)
    _commit(obj, result, 'Offset face')
    return report


def shell(obj, names, thickness, dialog=None):
    """Hollow a solid, leaving the named faces open."""
    _target(obj)
    result, report = shape_jobs.run('shell', local(obj), {'faces': indices(obj, names), 'thickness': float(thickness)},
                                    label='Hollowing the part', dialog=dialog)
    _commit(obj, result, 'Shell')
    return report


def thicken(obj, thickness, side='front', dialog=None):
    """Turn a surface object into a solid wall."""
    _target(obj)
    result, report = shape_jobs.run('thicken', local(obj), {'thickness': float(thickness), 'side': side},
                                    label='Thickening the surface', dialog=dialog)
    _commit(obj, result, 'Thicken')
    return report


def is_surface(obj):
    """Whether the object is faces with no solid, so Shell thickens it instead."""
    shape = obj.Shape
    return bool(shape.Faces) and not shape.Solids


def draft_axis(obj, axis):
    """A world axis name (X, Y, Z, optionally -X…) in the object's own coordinates."""
    sign = -1 if axis.startswith('-') else 1
    world = V(*{'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}[axis.lstrip('+-')]) * sign
    return obj.Placement.Rotation.inverted().multVec(world)


def draft(obj, names, angle, axis='Z', hinge='bottom', narrower='top', dialog=None):
    """Tilt flat or round faces by angle about a hinge plane across the world axis."""
    _target(obj)
    faces = indices(obj, names)
    if not faces:
        raise ValueError('Select the faces to draft.')
    result, report = shape_jobs.run('draft', local(obj), {'faces': faces, 'angle': float(angle),
                                                          'axis': list(draft_axis(obj, axis)),
                                                          'hinge': hinge, 'narrower': narrower},
                                    label='Drafting %d face%s' % (len(faces), '' if len(faces) == 1 else 's'),
                                    dialog=dialog)
    _commit(obj, result, 'Draft')
    return report


# --- Fill hole -------------------------------------------------------------------

def openings(obj):
    """Rim wires of the object's openings, in world coordinates."""
    ops.editable(obj)
    return se.open_loops(obj.Shape)


def fill_holes(obj, edge_names=(), smooth=True, dialog=None):
    _target(obj)
    edges = indices(obj, edge_names, 'Edge') if edge_names else None
    result, report = shape_jobs.run('fill', local(obj), {'edges': edges, 'smooth': bool(smooth)},
                                    label='Filling openings', dialog=dialog)
    _commit(obj, result, 'Fill hole')
    return report


# --- Unwrap ------------------------------------------------------------------------

def unwrap(obj, name, dialog=None):
    """A new flat face object with the face's unwrapped outline, beside obj."""
    ops.editable(obj)
    face = indices(obj, [name])[0]
    flat, report = shape_jobs.run('unwrap', local(obj), {'face': face}, label='Unwrapping the face', dialog=dialog)
    box = obj.Shape.BoundBox
    gap = max(5.0, .1 * box.DiagonalLength)
    flat = flat.copy()
    flat.translate(V(box.XMax + gap, box.YMin, box.ZMin))
    result = ops.new_shape(obj.Document, flat, '%s %s unwrapped' % (obj.Label, name))
    return result, report


# --- Patterns ------------------------------------------------------------------------

def pattern(objects, placements):
    """Independent copies of whole objects at each placement, one Undo step."""
    objects = list(dict.fromkeys(objects))
    if not objects:
        raise ValueError('Select the objects to repeat.')
    if not placements:
        raise ValueError('The pattern has no copies.')
    doc = objects[0].Document
    for obj in objects:
        ops.editable(obj)
        if obj.Document != doc:
            raise ValueError('Select objects from one document.')
    if len(objects) * len(placements) > patterns.LIMIT:
        raise ValueError('A pattern can make at most %d copies.' % patterns.LIMIT)
    from ..document import visibility
    results = []
    with ops.transaction(doc, 'Pattern'):
        for obj in objects:
            hidden = visibility.hidden_faces(obj)
            for n, placement in enumerate(placements, 2):
                copy = doc.addObject('Part::Feature', 'SimplePattern')
                copy.Label = '%s %d' % (obj.Label, n)
                copy.Shape = obj.Shape.copy()
                copy.Placement = placement.multiply(obj.Placement)
                if App.GuiUp:
                    copy.ViewObject.ShapeAppearance = obj.ViewObject.ShapeAppearance
                    copy.ViewObject.LineColor = obj.ViewObject.LineColor
                    if hidden:
                        visibility.set_hidden(copy, sorted(hidden))
                results.append(copy)
    return results


def selection_center(objects):
    box = App.BoundBox()
    for obj in objects:
        box.add(obj.Shape.BoundBox)
    return box.Center


def path_shape(targets):
    """The edges picked as a pattern path, joined into one wire."""
    edges = [obj.Shape.getElement(name) for obj, names in targets for name in names if name.startswith('Edge')]
    if not edges:
        raise ValueError('Also select an edge, on another object, for the copies to follow.')
    return patterns._wire(Part.makeCompound(edges))


def placements(kind, objects, path=None, count=3, spacing=(10.0, 0.0, 0.0), counts=None, axis=(0, 0, 1),
               center=None, angle=360.0, align=True):
    if kind == 'grid':
        if counts is None:
            counts = (count, 1, 1)
        return patterns.grid(counts, spacing)
    if kind == 'radial':
        return patterns.radial(count, V(*axis), selection_center(objects) if center is None else V(*center), angle)
    if kind == 'path':
        if path is None:
            raise ValueError('Select an edge for the copies to follow.')
        return patterns.along(path, count, align)
    raise ValueError('Choose a grid, radial or path pattern.')


def curvature_at(obj, name, point=None):
    """Curvature of a face of obj at a world point (default: its middle)."""
    face = obj.Shape.getElement(name)
    if face.ShapeType != 'Face':
        raise ValueError('Pick a face to read its curvature.')
    result = se.curvature(face, point)
    result['tight'] = None if math.isinf(result['tight']) else result['tight']
    result['gentle'] = None if math.isinf(result['gentle']) else result['gentle']
    return result
