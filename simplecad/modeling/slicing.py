"""Plane slicing and symmetric separation of native solids and open surfaces."""
import math
from dataclasses import dataclass

import FreeCAD as App
import Part
from BOPTools import SplitAPI
from ..core import geometry as geo, coincident as coinc

V = App.Vector
AXES = {"X": V(1, 0, 0), "Y": V(0, 1, 0), "Z": V(0, 0, 1)}


def compound(shapes):
    return shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)


def main_axis(shape):
    """The least moment of inertia is the long mass axis, in world coordinates."""
    properties = shape.PrincipalProperties
    moments = tuple(abs(value) for value in properties["Moments"])
    names = ("FirstAxisOfInertia", "SecondAxisOfInertia", "ThirdAxisOfInertia")
    order = sorted(range(3), key=lambda i: moments[i])
    if abs(moments[order[1]] - moments[order[0]]) <= max(geo.EPS, abs(moments[order[2]]) * 1e-8):
        # Cubes/spheres have no unique long axis. Choose the longest local
        # bounding dimension deterministically instead of an unstable eigenvector.
        local = shape.copy()
        rotation = shape.Placement.Rotation
        local.Placement = App.Placement()
        box = local.BoundBox
        axis = rotation.multVec(tuple(AXES.values())[max(range(3), key=lambda i:
                                      (box.XLength, box.YLength, box.ZLength)[i])])
    else:
        axis = properties[names[order[0]]]
    axis = geo.unit(axis)
    largest = max(range(3), key=lambda i: abs(tuple(axis)[i]))
    return axis if tuple(axis)[largest] >= 0 else -axis


def bounds(shape, rotation):
    local = shape.copy()
    local.Placement = App.Placement(V(), rotation.inverted()).multiply(local.Placement)
    # BoundBox can include a whole curved support surface beyond its trim
    # (notably rotated fillets), falsely making a cut piece straddle the plane.
    return local.optimalBoundingBox(False)


@dataclass
class CutPlane:
    normal: object
    rotation: object
    center: object
    lower: float
    upper: float
    size: float

    def face(self, offset):
        plane = geo.Plane.from_normal(self.center + self.normal * offset, self.normal)
        extent = self.size * .6
        points = [plane.origin + plane.u * u * extent + plane.v * v * extent
                  for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1), (-1, -1))]
        return Part.Face(Part.makePolygon(points))


def face_normal(face):
    """The cut direction of a flat face, signed like the axis choices."""
    if not isinstance(face.Surface, Part.Plane):
        raise ValueError("Pick a flat face to cut along.")
    normal = geo.unit(geo.face_normal(face))
    largest = max(range(3), key=lambda i: abs(tuple(normal)[i]))
    return normal if tuple(normal)[largest] >= 0 else -normal


def cut_plane(shapes, axis="Main", normal=None):
    """The cut plane across ``shapes``; axis "Face" uses the given ``normal``."""
    shape = compound(shapes)
    geo.validate(shape)
    if axis == "Face":
        normal = geo.unit(normal) if normal is not None else None
    else:
        normal = main_axis(shape) if axis == "Main" else AXES.get(axis)
    if normal is None:
        raise ValueError("Choose X, Y, Z, Object main axis, or pick a flat face.")
    rotation = App.Rotation(V(0, 0, 1), normal)
    box = bounds(shape, rotation)
    center = rotation.multVec(box.Center)
    return CutPlane(normal, rotation, center, -box.ZLength / 2, box.ZLength / 2,
                    max(box.DiagonalLength, geo.EPS * 100))


def face_offset(plane, face):
    """The cut offset putting the plane exactly on a flat face parallel to it."""
    if abs(abs(face_normal(face).dot(plane.normal)) - 1) > 1e-9:
        raise ValueError("That face is not parallel to the cut plane.")
    return (face.Vertexes[0].Point - plane.center).dot(plane.normal)


def leaves(shape):
    if shape.ShapeType in ("Compound", "CompSolid"):
        for child in shape.childShapes():
            yield from leaves(child)
    else:
        yield shape


def side_parts(parts):
    """Keep solids independent; sew open faces on one side without capping them."""
    solids = [part for part in parts if part.ShapeType == "Solid"]
    surfaces = [part for part in parts if part.ShapeType != "Solid"]
    if surfaces:
        joined = coinc.assemble([face for part in surfaces for face in part.Faces],
                                [edge for part in surfaces for edge in coinc.loose_edges(part)])
        if joined is not None:
            solids.append(joined)
        solids.extend(part for part in surfaces if part.ShapeType == "Vertex")
    return solids


def split(shape, plane, offset):
    """Return (side, shape) pairs. Cutting tools never enter the result."""
    geo.validate(shape)
    if shape.ShapeType == "Shell" and shape.isClosed():
        shape = geo.validate(Part.makeSolid(shape), solid=True)
    if shape.ShapeType == "Solid" and shape.Volume < 0:
        shape = shape.copy()
        shape.reverse()
    if not math.isfinite(offset):
        raise ValueError("Enter a finite cut offset, for example 5 mm.")
    origin = plane.center + plane.normal * offset
    cut = origin.dot(plane.normal)
    tolerance = max(geo.EPS * 10, plane.size * 1e-9)
    source = bounds(shape, plane.rotation)
    if source.ZMax <= cut + tolerance:
        return [(-1, shape.copy())]
    if source.ZMin >= cut - tolerance:
        return [(1, shape.copy())]
    try:
        result = SplitAPI.slice(shape.copy(), [plane.face(offset)], "Split")
        negative, positive = [], []
        for part in leaves(result):
            box = bounds(part, plane.rotation)
            if box.ZMax <= cut + tolerance:
                negative.append(part)
            elif box.ZMin >= cut - tolerance:
                positive.append(part)
            else:
                raise ValueError("The plane could not fully separate this shape. Try a different position.")
        pieces = [(side, geo.validate(part)) for side, parts in ((-1, negative), (1, positive))
                  for part in side_parts(parts)]
        if not pieces:
            raise ValueError("The cut produced no usable pieces.")
        # Validate by dimension: open surfaces have no meaningful solid volume.
        volume = sum(abs(solid.Volume) for solid in shape.Solids)
        new_volume = sum(abs(solid.Volume) for _, part in pieces for solid in part.Solids)
        # A plane cut only adds faces. On converted solids carrying mesh-era
        # tolerances the volume evaluation still drifts by about 1e-7; losing
        # or duplicating a piece changes far more.
        if abs(new_volume - volume) > max(1e-6, volume * 1e-6):
            raise ValueError("The cut did not preserve the solid volume.")
        if not shape.Solids and abs(sum(part.Area for _, part in pieces) - shape.Area) > max(1e-6, shape.Area * 1e-7):
            raise ValueError("The cut did not preserve the surface area.")
        return pieces
    except Part.OCCError as error:
        raise ValueError("This shape could not be sliced here. Try a different plane position.") from error


def separate(pieces, normal, gap):
    if not math.isfinite(gap) or gap < 0:
        raise ValueError("Enter a gap of zero or greater, for example 10 mm.")
    result = []
    for side, original in pieces:
        shape = original.copy()
        shape.translate(normal * (side * gap / 2))
        result.append(shape)
    return result
