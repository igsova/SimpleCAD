"""Offset faces, shell or thicken, and draft angles on Part shapes.

Pure Part geometry for the isolated shape worker, like ``surface_edit``: no
document selection, view or Undo access. Face numbers are 0-based indices
into ``shape.Faces``.

Offset face moves faces along their own normals and builds straight side
walls where they leave their neighbours, like Push/Pull does on a flat face:
the neighbours do not stretch to follow.
"""
import FreeCAD as App
import Part

from ..core import geometry as geo
from .edit import checked, solid_body, _single

V = App.Vector
TOLERANCE = 1e-6
AXES = {'X': V(1, 0, 0), 'Y': V(0, 1, 0), 'Z': V(0, 0, 1)}


def _mm(value):
    return '%.3g mm' % value


def _indices(shape, indices, what='Select faces of this object.'):
    indices = sorted(set(int(i) for i in indices))
    if not indices or indices[0] < 0 or indices[-1] >= len(shape.Faces):
        raise ValueError(what)
    return indices


def _refined(shape):
    """Merge faces split on one surface, when that keeps the shape valid."""
    try:
        refined = _single(shape.removeSplitter())
        if refined.isValid() and len(refined.Solids) == len(shape.Solids):
            return refined
    except (Part.OCCError, RuntimeError):
        pass
    return shape


def _repaired(result):
    """Boolean results on fitted surfaces can be a hair off; fix and recheck."""
    if result.isValid():
        return result
    fixed = result.copy()
    try:
        fixed.fix(1e-4, 1e-7, 1e-3)
    except (Part.OCCError, RuntimeError):
        return result
    return fixed


def _solid(shape):
    shape = _single(shape)
    if shape.ShapeType == 'Shell' and shape.isClosed():
        shape = Part.Solid(shape)
    return shape


def _connected(faces):
    """Whether the faces form one patch joined along shared edges."""
    reached, frontier = {0}, [0]
    while frontier:
        current = faces[frontier.pop()]
        for i, face in enumerate(faces):
            if i not in reached and any(e.isPartner(f) for e in current.Edges for f in face.Edges):
                reached.add(i)
                frontier.append(i)
    return len(reached) == len(faces)


def slab(faces, distance):
    """Solids swept by faces moved distance along their outward normals.

    Connected faces are offset together so they keep meeting; when the kernel
    cannot do that, each face is offset on its own. Returns a list of solids.
    """
    swept = sum(f.Area for f in faces) * abs(distance)
    if len(faces) > 1 and _connected(faces):
        try:
            joined = _solid(Part.Shell(faces).makeOffsetShape(distance, TOLERANCE, join=2, fill=True))
            if joined.isValid() and joined.Solids and abs(joined.Volume - swept) < .5 * swept:
                return list(joined.Solids)
        except (Part.OCCError, RuntimeError, ValueError):
            pass
    pieces = []
    for face in faces:
        try:
            piece = _solid(face.makeOffsetShape(distance, TOLERANCE, fill=True))
        except (Part.OCCError, RuntimeError) as error:
            raise ValueError('A selected face cannot be offset by %s. Try a smaller distance.'
                             % _mm(abs(distance))) from error
        if not piece.isValid() or not piece.Solids or piece.Volume <= geo.EPS:
            raise ValueError('A selected face cannot be offset by %s: it curves too tightly. Try a smaller distance.'
                             % _mm(abs(distance)))
        pieces.extend(piece.Solids)
    return pieces


def offset_faces(shape, indices, distance, progress=lambda message: None):
    """Move faces of a solid outward (distance > 0) or inward along their normals.

    Returns (shape, report). Every face of the solid offsets the whole part.
    """
    solid_body(shape)
    indices = _indices(shape, indices, 'Select faces of this object to offset.')
    if abs(distance) <= geo.EPS:
        raise ValueError('Enter a distance other than zero.')
    faces = [shape.Faces[i] for i in indices]
    if len(indices) == len(shape.Faces):
        progress('Offsetting the whole part')
        try:
            result = _solid(shape.makeOffsetShape(distance, TOLERANCE, join=2))
        except (Part.OCCError, RuntimeError) as error:
            raise ValueError('The kernel could not offset the whole part by %s.'
                             % _mm(abs(distance))) from error
    else:
        progress('Offsetting %d face%s' % (len(faces), '' if len(faces) == 1 else 's'))
        tools = slab(faces, distance)
        progress('Joining the offset to the solid' if distance > 0 else 'Cutting the offset into the solid')
        try:
            result = shape.fuse(tools) if distance > 0 else shape.cut(tools)
        except (Part.OCCError, RuntimeError) as error:
            raise ValueError('The offset faces could not be joined to the solid.') from error
        result = _repaired(_refined(_single(result)))
        if not result.isValid():
            raise ValueError('The offset could not be joined cleanly to the neighbouring faces here. '
                             'Try a smaller distance, or offset fewer faces at once.')
    checked(result, shape)
    if abs(result.Volume - shape.Volume) <= geo.EPS:
        raise ValueError('The offset did not change the solid.')
    return result, {'faces': len(faces), 'distance': distance, 'volume_change': result.Volume - shape.Volume}


# --- Shell and thicken ----------------------------------------------------------

SHELL_FAILED = ('The kernel could not hollow this part with a %s wall. Shell works on parts made of flat faces, '
                'cylinders and simple curves; surfaces fitted to a mesh often fail. Try a thinner wall, or '
                'remove small rounds first.')


def shell(shape, indices, thickness, progress=lambda message: None):
    """Hollow a solid to a wall thickness, leaving the chosen faces open.

    With no faces chosen the part becomes a closed hollow solid.
    """
    solid_body(shape)
    if len(shape.Solids) != 1:
        raise ValueError('Shell one solid at a time.')
    if not thickness > geo.EPS:
        raise ValueError('Enter a wall thickness above zero.')
    indices = sorted(set(int(i) for i in indices))
    if indices and (indices[0] < 0 or indices[-1] >= len(shape.Faces)):
        raise ValueError('Select faces of this object to leave open.')
    if len(indices) == len(shape.Faces):
        raise ValueError('Leave at least one face closed.')
    faces = [shape.Faces[i] for i in indices]
    progress('Hollowing the part')
    for join in (2, 0):  # sharp inner corners first, then rounded ones
        try:
            if faces:
                result = _solid(shape.makeThickness(faces, -thickness, 1e-3, False, False, 0, join))
            else:
                inner = _solid(shape.makeOffsetShape(-thickness, 1e-3, False, False, 0, join))
                if not inner.isValid() or not inner.Solids:
                    continue
                result = _single(shape.cut(inner))
            result = _repaired(result)
            checked(result, shape)
        except (Part.OCCError, RuntimeError, ValueError):
            continue
        if result.Volume < shape.Volume - geo.EPS:
            return result, {'open_faces': len(faces), 'thickness': thickness,
                            'volume_change': result.Volume - shape.Volume}
    raise ValueError(SHELL_FAILED % _mm(thickness))


def thicken(shape, thickness, side='front', progress=lambda message: None):
    """Turn a face or open surface into a solid wall.

    side: 'front' grows along the face normals, 'back' against them, and
    'both' half each way.
    """
    if shape.isNull() or not shape.Faces:
        raise ValueError('Select a surface object to thicken.')
    if shape.Solids:
        raise ValueError('This is already a solid. Use Shell to hollow it.')
    if not thickness > geo.EPS:
        raise ValueError('Enter a thickness above zero.')
    if side not in ('front', 'back', 'both'):
        raise ValueError('Choose front, back or both sides.')
    progress('Thickening the surface')
    faces = shape.Faces
    distances = {'front': [thickness], 'back': [-thickness], 'both': [thickness / 2, -thickness / 2]}[side]
    tools = [piece for d in distances for piece in slab(faces, d)]
    try:
        result = tools[0] if len(tools) == 1 else _single(tools[0].fuse(tools[1:]))
    except (Part.OCCError, RuntimeError) as error:
        raise ValueError('The thickened pieces could not be joined.') from error
    result = _repaired(_refined(_single(result)))
    if not result.isValid() or len(result.Solids) != 1 or result.Volume <= geo.EPS:
        raise ValueError('This surface could not be thickened by %s. Try a smaller thickness.'
                         % _mm(thickness))
    return result, {'thickness': thickness, 'side': side, 'volume': result.Volume}


# --- Draft --------------------------------------------------------------------

def hinge_height(shape, indices, axis, where):
    """Height along axis of the bottom or top of the chosen faces."""
    axis = geo.unit(V(*axis))
    heights = []
    for i in indices:
        face = shape.Faces[i]
        for edge in face.Edges:
            heights.extend(p.dot(axis) for p in edge.discretize(16))
    if not heights:
        raise ValueError('Select faces with edges to draft.')
    return min(heights) if where == 'bottom' else max(heights)


def draft(shape, indices, angle, axis, hinge='bottom', narrower='top', progress=lambda message: None):
    """Tilt faces by angle degrees about a hinge plane normal to axis.

    The faces keep their place where they cross the hinge plane at the bottom
    or top of the selection and lean so the part gets narrower toward the
    top (+axis) or bottom. Uses PartDesign's Draft on a private document, so
    run it in the shape worker.
    """
    solid_body(shape)
    indices = _indices(shape, indices, 'Select the faces to draft.')
    if not 0 < angle < 89.9:
        raise ValueError('Enter an angle between 0 and 89.9 degrees.')
    if hinge not in ('bottom', 'top') or narrower not in ('top', 'bottom'):
        raise ValueError('Choose the hinge and which way the part narrows.')
    axis = geo.unit(V(*axis))
    for i in indices:
        face = shape.Faces[i]
        if not isinstance(face.Surface, (Part.Plane, Part.Cylinder, Part.Cone)):
            raise ValueError('Draft works on flat, cylindrical and conical faces, not on free-form curved ones.')
        if isinstance(face.Surface, Part.Plane) and abs(geo.face_normal(face).dot(axis)) > 1 - 1e-6:
            raise ValueError('A face square to the pull direction cannot be drafted. Select the side walls.')
    origin = axis * hinge_height(shape, indices, axis, hinge)
    progress('Tilting %d face%s' % (len(indices), '' if len(indices) == 1 else 's'))
    import PartDesign  # noqa: F401  (registers the Draft feature)
    doc = App.newDocument('SimpleCADDraft', hidden=True, temp=True)
    try:
        base = doc.addObject('Part::Feature', 'Base')
        base.Shape = shape
        body = doc.addObject('PartDesign::Body', 'Body')
        body.BaseFeature = base
        plane = doc.addObject('PartDesign::Plane', 'Hinge')
        body.addObject(plane)
        plane.MapMode = 'Deactivated'
        plane.Placement = App.Placement(origin, App.Rotation(V(0, 0, 1), axis))
        feature = doc.addObject('PartDesign::Draft', 'Draft')
        body.addObject(feature)
        feature.Base = (base, ['Face%d' % (i + 1) for i in indices])
        feature.Angle = angle
        feature.NeutralPlane = (plane, [''])
        feature.Reversed = narrower == 'bottom'
        doc.recompute()
        if 'Invalid' in feature.State or feature.Shape.isNull():
            raise ValueError('These faces could not be drafted about that hinge. They must cross or touch the '
                             'hinge plane, and rounds that blend into them must be drafted with them or removed '
                             'first (Remove rounds). Try the other hinge or a smaller angle.')
        result = _single(feature.Shape.copy())
    finally:
        App.closeDocument(doc.Name)
    checked(result, shape)
    if abs(result.Volume - shape.Volume) <= geo.EPS:
        raise ValueError('The draft did not change the solid.')
    return result, {'faces': len(indices), 'angle': angle, 'volume_change': result.Volume - shape.Volume}
