"""Connected native skins for drawing across face boundaries.

The picked face chooses a component, not a permanent trim boundary. Only faces
that share native edges belong to the same drawing support.
"""
import Part

from ..inspection.smart_select import adjacency, grow


def has_faces(doc):
    """Whether a shown object of the document has a CAD face to draw on."""
    for obj in doc.Objects:
        view = getattr(obj, 'ViewObject', None)
        if view is not None and not view.Visibility:
            continue
        shape = getattr(obj, 'Shape', None)
        if isinstance(shape, Part.Shape) and not shape.isNull() and shape.countElement('Face'):
            return True
    return False


class Skin:
    def __init__(self, shape, face):
        adj = adjacency(shape)
        seed = adj.index_of(face)
        if seed is None:
            raise ValueError('The surface changed. Pick the starting face again.')
        self.shape = shape
        self.indices = frozenset(grow(adj, seed, lambda i, j, edge: True))
        self.adj = adj
        self.faces = [adj.faces[i] for i in sorted(self.indices)]
        self.surface = Part.makeCompound(self.faces)

    def contains(self, face):
        return self.adj.index_of(face) in self.indices
