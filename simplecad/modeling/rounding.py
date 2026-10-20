"""Native constant-radius fillets for selected sharp solid edges."""
import math
import re

from ..core import geometry as geo
import Part


def solid_source(shape):
    geo.validate(shape)
    if shape.ShapeType == "Shell" and shape.isClosed():
        shape = Part.makeSolid(shape)
    if (len(shape.Solids) != 1 or len(shape.Faces) != len(shape.Solids[0].Faces)
            or len(shape.Edges) != len(shape.Solids[0].Edges)):
        raise ValueError("Round Edges needs a closed solid. Close the open surfaces first.")
    solid = shape.Solids[0]
    if solid.Volume < 0:
        solid.reverse()
    return geo.validate(solid, solid=True)


def sharp(shape, edge):
    if geo.is_seam_edge(shape, edge):
        return False
    faces = [face for face in shape.Faces if any(edge.isSame(e) for e in face.Edges)]
    if len(faces) != 2:
        return False
    # Test several points, including curved edges. A smooth tangent boundary
    # and a coplanar drawn divider must not become attempted fillets.
    for fraction in (.2, .5, .8):
        point = edge.valueAt(edge.getParameterByLength(edge.Length * fraction))
        normals = [geo.unit(face.normalAt(*face.Surface.parameter(point))) for face in faces]
        if normals[0].dot(normals[1]) < 1 - 1e-6:
            return True
    return False


def selected_edges(shape, names=()):
    """Resolve EdgeN/FaceN from the original shape; no names means all edges."""
    solid_source(shape)
    candidates = set()
    if not names:
        candidates.update(range(len(shape.Edges)))
    for name in names:
        match = re.fullmatch(r"(Edge|Face)([1-9][0-9]*)", name)
        if not match:
            raise ValueError("Select an edge, a face, or a whole solid to round.")
        kind, number = match.groups()
        number = int(number) - 1
        parts = shape.Edges if kind == "Edge" else shape.Faces
        if number >= len(parts):
            raise ValueError("The selection has changed. Select the edges again.")
        if kind == "Edge":
            candidates.add(number)
        else:
            candidates.update(i for i, edge in enumerate(shape.Edges)
                              if any(edge.isSame(e) for e in parts[number].Edges))
    result = tuple(i for i in sorted(candidates) if sharp(shape, shape.Edges[i]))
    if not result:
        raise ValueError("No sharp edges selected. Seams, flat dividers and smooth boundaries are skipped.")
    return result


def round_edges(shape, indices, radius):
    if not math.isfinite(radius) or radius < 0:
        raise ValueError("Enter a radius of zero or greater, for example 2 mm.")
    source = shape.copy()
    solid = solid_source(source)
    if not indices or any(i < 0 or i >= len(source.Edges) for i in indices):
        raise ValueError("Select at least one sharp edge to round.")
    if radius == 0:
        return shape.copy()
    if radius < geo.EPS * 10:
        raise ValueError("That radius is too small. Use zero for the original sharp shape.")
    edges = [source.Edges[i] for i in sorted(set(indices))]
    if not all(sharp(source, edge) for edge in edges):
        raise ValueError("Choose sharp edges, not flat dividers, seams or smooth boundaries.")
    try:
        result = solid.makeFillet(radius, edges)
        result = solid_source(result)
    except (Part.OCCError, ValueError) as error:
        raise ValueError("That radius does not fit these edges. Try a smaller radius or fewer edges.") from error
    return result
