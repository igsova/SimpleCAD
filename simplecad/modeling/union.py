"""Fuse complete native volumes into one closed, refined solid."""
import math
import Part
from ..core import geometry as geo


def solids(shape):
    """Keep every component; never silently discard sheets or loose geometry."""
    if shape.isNull():
        raise ValueError('Union needs closed solids. An object has no geometry.')
    if shape.ShapeType in ('Compound', 'CompSolid'):
        children = shape.childShapes()
        if not children:
            raise ValueError('Union needs closed solids. An object has no geometry.')
        return [solid for child in children for solid in solids(child)]
    if shape.ShapeType == 'Shell' and shape.isClosed():
        shape = Part.makeSolid(shape.copy())
    elif shape.ShapeType != 'Solid':
        raise ValueError('Union needs closed solids. Close open surfaces and separate loose lines or points first.')
    result = shape.copy()
    if result.Volume < 0:
        result.reverse()
    if not result.isValid() or not result.isClosed() or not math.isfinite(result.Volume) or result.Volume <= geo.EPS:
        raise ValueError('Union needs valid closed solids. Repair the open or invalid shape first.')
    return [result]


def merge_flat_neighbours(solid, tolerance):
    """Merge adjacent flat faces lying in one plane within ``tolerance``.

    removeSplitter merges only exactly coplanar faces. Parts converted from
    meshes meet a hair apart, such as a rod's end 0.008 mm below the face it
    fills, which would leave a dividing loop no one drew.
    """
    faces = solid.Faces
    parent = list(range(len(faces)))

    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i
    # Only faces sharing an edge can merge. Index the edges once rather than
    # testing every pair of flat faces on a dense part.
    owners = {}
    for i, face in enumerate(faces):
        if isinstance(face.Surface, Part.Plane):
            for edge in face.Edges:
                owners.setdefault(hash(edge), []).append((i, edge))
    pairs = set()
    for bucket in owners.values():
        for a, (i, edge) in enumerate(bucket):
            for j, other in bucket[a + 1:]:
                if i != j and edge.isSame(other):
                    pairs.add((min(i, j), max(i, j)))
    normals = {}

    def normal(i):
        if i not in normals:
            normals[i] = geo.face_normal(faces[i])
        return normals[i]
    for i, j in sorted(pairs):
        if normal(i).dot(normal(j)) >= 1 - 1e-6 and geo.coplanar(faces[i], faces[j], tolerance):
            parent[root(j)] = root(i)
    groups = {}
    for i in range(len(faces)):
        groups.setdefault(root(i), []).append(i)
    merged, redundant = {}, set()
    for members in groups.values():
        if len(members) < 2:
            continue
        keep = max(members, key=lambda i: faces[i].Area)
        try:
            merged[keep] = geo.merge_coplanar_face_group([faces[i] for i in members],
                                                         sum(faces[i].Area for i in members), faces[keep])
        except (ValueError, Part.OCCError):
            continue
        redundant.update(i for i in members if i != keep)
    if not merged:
        return solid
    shell = Part.makeShell([merged.get(i, face) for i, face in enumerate(faces) if i not in redundant])
    shell.sewShape(tolerance)
    result = Part.makeSolid(shell)
    if result.Volume < 0:
        result.reverse()
    return result if result.isValid() and result.isClosed() and len(result.Solids) == 1 else solid


def fused_solid(inputs, fuzzy=None):
    """One refined, valid closed solid of the inputs, or ValueError."""
    fused = inputs[0].multiFuse(inputs[1:], fuzzy) if fuzzy else inputs[0].multiFuse(inputs[1:])
    if len(fused.Solids) != 1:
        raise ValueError('The pieces do not form one connected solid. Move them so they overlap or share a face; touching at an edge or point is not enough.')
    result = fused.removeSplitter()
    if len(result.Solids) != 1 or result.ShapeType not in ('Solid', 'Compound'):
        raise ValueError('Union could not produce one closed solid.')
    solid = result.Solids[0]
    if (len(result.Faces) != len(solid.Faces) or len(result.Edges) != len(solid.Edges)
            or not solid.isClosed() or not solid.isValid()):
        raise ValueError('Union could not create a valid closed solid. Try moving the pieces into a larger overlap.')
    if solid.Volume < 0:
        solid.reverse()
    # Deep native checks also detect self-intersections that basic validity
    # alone can miss. Failure leaves the original objects untouched.
    solid.check(True)
    return solid


def combine(shapes):
    """Compute and validate the full union without document changes."""
    inputs = [solid for shape in shapes for solid in solids(shape)]
    if len(inputs) < 2:
        raise ValueError('Select at least two overlapping solids, then choose Union (J).')
    from ..core.preferences import precision
    # Converted parts report their volume a little off: faces rebuilt from
    # meshes carry mesh-era tolerances. Allow numeric drift of 1% of the
    # modeling precision over their surfaces; real material changes by far
    # more, and the cut checks below find it directly.
    tolerance = max(1e-6, sum(s.Volume for s in inputs) * 1e-8,
                    sum(s.Area for s in inputs) * precision() * .01)
    fuzzy = precision() * .1
    try:
        solid = fused_solid(inputs)
    except ValueError as error:
        if 'connected' not in str(error):
            raise
        # Pieces apart by a hair, such as a pylon ending a micron short of
        # the plate it stands on, touch within the precision. The exact fuse
        # found them disjoint, so their union holds exactly their volumes.
        try:
            joined = merge_flat_neighbours(fused_solid(inputs, fuzzy), fuzzy)
            joined.check(True)
        except (ValueError, Part.OCCError, RuntimeError):
            raise error
        if abs(joined.Volume - sum(s.Volume for s in inputs)) > tolerance:
            raise error
        return geo.validate(joined, solid=True)
    except (Part.OCCError, RuntimeError) as error:
        raise ValueError('FreeCAD could not join these solids cleanly. Try a larger overlap or simpler contact, then Union again.') from error
    try:
        if (not math.isfinite(solid.Volume) or solid.Volume <= geo.EPS
                or solid.Volume > sum(s.Volume for s in inputs) + tolerance):
            raise ValueError('Union failed its volume check. The original pieces were kept.')
        for source in inputs:
            if abs(source.common(solid).Volume - source.Volume) > tolerance:
                raise ValueError('Union would lose part of an object. The original pieces were kept.')
        # Check the final occupied volume directly. The unrefined intermediate
        # can contain redundant curved faces and report an incorrect volume.
        # Every input is cut in one Boolean: one at a time, a block whose
        # sides are tangent to a boss leaves a false remainder.
        remaining = solid.cut(inputs)
        if not remaining.isNull() and abs(remaining.Volume) > tolerance:
            raise ValueError('Union would add unexpected material. The original pieces were kept.')
    except (Part.OCCError, RuntimeError) as error:
        raise ValueError('FreeCAD could not join these solids cleanly. Try a larger overlap or simpler contact, then Union again.') from error
    # Surfaces within a tenth of the modeling precision are one surface: a
    # converted rod in its bore meets the wall a few microns off, and the
    # exact union keeps slivers of both. Booleans cannot verify a fuzzy result
    # against its inputs, so it must match the verified exact union instead,
    # and is used only when it is simpler.
    try:
        clean = merge_flat_neighbours(fused_solid(inputs, fuzzy), fuzzy)
        clean.check(True)
        if len(clean.Faces) < len(solid.Faces) and abs(clean.Volume - solid.Volume) <= tolerance:
            solid = clean
    except (ValueError, Part.OCCError, RuntimeError):
        pass
    return geo.validate(solid, solid=True)
