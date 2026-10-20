"""Rigid rotations around captured world/object axes; no document writes."""
import math
from dataclasses import dataclass

import FreeCAD as App
import Part
from ..core import geometry as geo
from . import slicing

V = App.Vector
AXES = {"X": V(1, 0, 0), "Y": V(0, 1, 0), "Z": V(0, 0, 1)}


def parse_angle(text):
    """Bare numbers are degrees; explicit angular units use FreeCAD's parser."""
    try:
        if not text.strip():
            raise ValueError()
        quantity = App.Units.Quantity(text.strip())
        if quantity.Unit not in (App.Units.Quantity("1").Unit, App.Units.Quantity("1 deg").Unit):
            raise ValueError()
        value = quantity.Value
        if not math.isfinite(value):
            raise ValueError()
        return value
    except Exception as error:
        raise ValueError("Enter an angle, for example 45°, -90° or 1.57 rad.") from error


def angle_degrees(value):
    if not math.isfinite(value):
        raise ValueError("Enter a finite rotation angle.")
    # Keep trigonometry accurate and whole turns an exact no-op.
    return math.remainder(value, 360.0)


def center(shape):
    return V(shape.CenterOfMass) if hasattr(shape, "CenterOfMass") else shape.optimalBoundingBox(False).Center


def find_curve_center(shape, elements=()):
    """Find analytic center of circular/elliptical edges, adjacent hole, or center of mass."""
    if elements:
        for name in elements:
            try:
                el = shape.getElement(name)
                c = getattr(el, "Curve", None)
                if c and hasattr(c, "Center"):
                    return V(c.Center)
                s = getattr(el, "Surface", None)
                if s and isinstance(s, Part.Cylinder):
                    return V(el.CenterOfMass)
            except Exception:
                pass
        for name in elements:
            try:
                el = shape.getElement(name)
                adjacent = [f for f in shape.ancestorsOfType(el, Part.Face)]
                for f in adjacent:
                    for e in f.Edges:
                        c = getattr(e, "Curve", None)
                        if c and hasattr(c, "Center"):
                            return V(c.Center)
            except Exception:
                pass
    if hasattr(shape, "Curve") and hasattr(shape.Curve, "Center"):
        return V(shape.Curve.Center)
    return center(shape)


def find_element_normal(shape, elements=()):
    """Find face or curve normal for selected elements."""
    if elements:
        for name in elements:
            try:
                el = shape.getElement(name)
                if el.ShapeType == "Face" and isinstance(getattr(el, "Surface", None), Part.Plane):
                    return geo.face_normal(el)
                adjacent = [f for f in shape.ancestorsOfType(el, Part.Face) if isinstance(getattr(f, "Surface", None), Part.Plane)]
                if adjacent:
                    return geo.face_normal(adjacent[0])
                c = getattr(el, "Curve", None)
                if c and hasattr(c, "Axis"):
                    return geo.unit(V(c.Axis))
            except Exception:
                pass
    if shape.Faces:
        planes = [f for f in shape.Faces if isinstance(getattr(f, "Surface", None), Part.Plane)]
        if planes:
            return geo.face_normal(planes[0])
    return V(0, 0, 1)


def direction(shape, axis, target=None):
    if axis in AXES:
        return V(AXES[axis])
    if axis in ("LocalX", "LocalY", "LocalZ"):
        return shape.Placement.Rotation.multVec(AXES[axis[-1]])
    if axis in ("FaceNormal", "Normal"):
        elements = getattr(target, "elements", ()) if target else ()
        return find_element_normal(shape, elements)
    if axis == "Main":
        if hasattr(shape, "PrincipalProperties"):
            return slicing.main_axis(shape)
        # Compounds and isolated vertices have no native principal properties.
        local = shape.copy(); local.Placement = App.Placement()
        box = local.optimalBoundingBox(False)
        index = max(range(3), key=lambda i: (box.XLength, box.YLength, box.ZLength)[i])
        return shape.Placement.Rotation.multVec(tuple(AXES.values())[index])
    raise ValueError("Choose X, Y, Z or an object axis.")


@dataclass
class Frame:
    center: object
    axis: object
    size: float

    def transform(self, angle):
        return App.Placement(V(), App.Rotation(self.axis, angle_degrees(angle)), self.center)


def frames(shapes, axis="Z", pivot="Selection", targets=None):
    if not shapes:
        raise ValueError("Select an object first, then choose Rotate.")
    valid_pivots = ("Selection", "Each", "Origin", "CurveCenter", "Start", "End")
    if pivot not in valid_pivots:
        raise ValueError("Choose a rotation center.")
    for shape in shapes:
        geo.validate(shape)

    first_target = targets[0] if targets else None
    shared_axis = direction(shapes[0], axis, first_target)

    # Determine shared pivot center
    if pivot == "Origin":
        shared = V(0, 0, 0)
    elif pivot == "CurveCenter" and first_target and getattr(first_target, "elements", ()):
        shared = find_curve_center(shapes[0], first_target.elements)
    elif pivot in ("Start", "End") and first_target and getattr(first_target, "elements", ()):
        edge = shapes[0].getElement(first_target.elements[0])
        idx = 0 if pivot == "Start" else -1
        shared = V(edge.Vertexes[idx].Point)
    elif first_target and getattr(first_target, "mode", "object") == "edge" and getattr(first_target, "elements", ()):
        edges = [shapes[0].getElement(n) for n in first_target.elements]
        shared = sum([e.CenterOfMass for e in edges], V()) * (1.0 / len(edges))
    else:
        combined = shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)
        shared = center(combined)

    result = []
    for i, shape in enumerate(shapes):
        t = targets[i] if targets and i < len(targets) else None
        if pivot == "Origin":
            origin = V(0, 0, 0)
        elif pivot == "Each":
            if t and getattr(t, "elements", ()):
                origin = find_curve_center(shape, t.elements)
            else:
                origin = center(shape)
        elif pivot == "CurveCenter" and t and getattr(t, "elements", ()):
            origin = find_curve_center(shape, t.elements)
        elif pivot in ("Start", "End") and t and getattr(t, "elements", ()):
            edge = shape.getElement(t.elements[0])
            idx = 0 if pivot == "Start" else -1
            origin = V(edge.Vertexes[idx].Point)
        else:
            origin = shared

        dir_vec = direction(shape, axis, t) if pivot == "Each" else shared_axis
        size = max(shape.optimalBoundingBox(False).DiagonalLength, 1.0)
        if t and getattr(t, "mode", "object") == "edge" and getattr(t, "elements", ()):
            try:
                bb = shape.getElement(t.elements[0]).BoundBox
                size = max(max(bb.XLength, bb.YLength, bb.ZLength) * 2.5, 10.0)
            except Exception:
                pass
        result.append(Frame(origin, geo.unit(dir_vec), size))
    return result


def rotated(shapes, captured_frames, angle):
    if len(shapes) != len(captured_frames):
        raise ValueError("The rotation preview is no longer current.")
    angle = angle_degrees(angle)
    result = []
    for original, frame in zip(shapes, captured_frames):
        shape = original.copy()
        if angle != 0:
            shape.Placement = frame.transform(angle).multiply(original.Placement)
        result.append(shape)
    return result
