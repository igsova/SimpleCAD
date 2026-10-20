"""Imprint surface crossings, retaining regions for direct face editing."""
import Part
from ..core import coincident, geometry as geo


def split(faces, remaining=(), edges=()):
    faces = coincident.unique(faces)
    if len(faces) < 2:
        raise ValueError('Select at least two intersecting faces, or their whole objects, then Intersect Faces (I).')
    try:
        output, _ = faces[0].generalFuse(faces[1:])
        if len(output.Faces) <= len(faces):
            raise ValueError('No crossing divides these faces. Move them into an overlap or select the crossing faces.')
        # Crossings intentionally have three or four faces at one edge. Keep
        # them as a surface compound until Delete leaves a manifold shell.
        # Sewing now cannot close it and needlessly compares every boundary.
        result = Part.makeCompound(coincident.unique(output.Faces + list(remaining))
                                   + coincident.unique(edges))
        source = coincident.unique(faces + list(remaining))
        area = sum(face.Area for face in source)
        if result is None or abs(result.Area-area) > max(1e-6, area*1e-8):
            raise ValueError('Intersect Faces needs crossing surfaces. Coplanar overlapping regions cannot be retained independently; use Union for overlapping solids.')
        return geo.validate(result)
    except (Part.OCCError, RuntimeError) as error:
        raise ValueError('FreeCAD could not split these intersections cleanly. The original objects were kept.') from error
