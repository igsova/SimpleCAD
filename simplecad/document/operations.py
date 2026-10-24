"""Atomic, undoable document writes; previews never reach this layer."""
from contextlib import contextmanager
import math
import re

import FreeCAD as App
import Part
from ..core import geometry as geo, coincident as coinc
from ..modeling import drawing, arcs
from ..modeling import rounding
from . import locking


@contextmanager
def transaction(doc, title, material_groups=(), face_materials=()):
    from . import materials as material_mapping
    materials = material_mapping.capture(doc, material_groups)
    overrides = {obj.Name for obj, _ in face_materials}
    materials = [entry for entry in materials if entry[0] not in overrides]
    protected = locking.capture(doc)
    if protected and not doc.UndoMode:
        raise ValueError('Enable document Undo before editing a model with locked geometry.')
    # An edit made of smaller ones joins the transaction already open, so it
    # stays one Undo step; FreeCAD would commit the open one instead.
    outer = doc.Name not in _open
    if outer:
        doc.openTransaction("SimpleCAD: " + title)
        _open.add(doc.Name)
    try:
        yield
        settle(doc)
        locking.validate(doc, protected)
        material_mapping.restore(doc, materials)
        for obj, values in face_materials:
            obj.ViewObject.ShapeAppearance = values
    except Exception:
        if outer:
            doc.abortTransaction()
        raise
    else:
        if outer:
            doc.commitTransaction()
    finally:
        if outer:
            _open.discard(doc.Name)


_open = set()  # names of documents with a SimpleCAD transaction open


def settle(doc):
    """Recompute, leaving plain shapes that need nothing from it as assigned.

    Recomputing a touched plain Part feature only stamps its Placement onto
    its shape again. That gives every face and edge a new native identity,
    so caches keyed by identity (snaps, material mapping, unchanged faces of
    a local split) start over, and the whole object is redrawn a second time.
    Objects that others depend on, or that carry expressions, are still
    recomputed.
    """
    for obj in doc.Objects:
        if (obj.TypeId == "Part::Feature" and "Touched" in obj.State and not obj.InList
                and not obj.ExpressionEngine and obj.Shape.Placement.isSame(obj.Placement, 1e-12)):
            obj.purgeTouched()
    doc.recompute()


def editable(obj):
    if obj is not None and getattr(obj, "TypeId", "").startswith("Mesh::"):
        raise ValueError("This is a mesh. Select it and choose SimpleCAD → Mesh → Make mesh editable… first.")
    if obj is None or obj.TypeId != "Part::Feature":
        raise ValueError("Use a plain Part shape. For parametric features, make a Part simple copy first.")
    if any(parent.hasExtension("App::GeoFeatureGroupExtension") for parent in obj.InList):
        raise ValueError("Move this shape out of its Part container first.")
    if obj.Shape.isNull():
        raise ValueError("This object has no shape.")
    return obj


def visible_shapes(doc):
    """Only geometry editable in this workbench participates across objects."""
    result = []
    for obj in doc.Objects:
        if App.GuiUp and (not obj.ViewObject or not obj.ViewObject.Visibility):
            continue
        try:
            editable(obj)
        except ValueError:
            continue
        result.append(obj)
    return result


def new_shape(doc, shape, label, support=None):
    geo.validate(shape)
    if support is not None:
        editable(support)
        geo.matching_support_face(support.Shape, shape)
    if shape.ShapeType in ("Face", "Edge"):
        for existing in visible_shapes(doc):
            if (getattr(existing, "SC_Support", None) == support
                    and coinc.same(existing.Shape, shape)):
                return existing
    with transaction(doc, label):
        obj = doc.addObject("Part::Feature", "SimpleShape")
        obj.Label = label
        obj.Shape = shape
        if support is not None:
            obj.addProperty("App::PropertyLink", "SC_Support", "SimpleCAD", "Solid used by Push/Pull")
            obj.SC_Support = support
            obj.setEditorMode("SC_Support", 1)
        if App.GuiUp:
            obj.ViewObject.ShapeColor = (0.76, 0.84, 0.88)
            obj.ViewObject.LineColor = (0.15, 0.23, 0.29)
            obj.ViewObject.LineWidth = 2.0
            if support:
                obj.ViewObject.ShapeColor = (0.34, 0.78, 0.71)
    return obj


def prepare_rounding(selection):
    """Capture the original topology once for every radius in this session."""
    grouped = {}
    doc = None
    for obj, names in selection:
        editable(obj)
        if doc is not None and obj.Document != doc:
            raise ValueError("Select solids from one document.")
        doc = obj.Document
        previous = grouped.get(obj, set())
        grouped[obj] = None if not names or previous is None else previous.union(names)
    if not grouped:
        raise ValueError("Select edges, a face, or a solid first, then choose Round Edges.")
    return [(obj, obj.Shape, rounding.selected_edges(obj.Shape, names or ()))
            for obj, names in grouped.items()]


def check_rounding(targets):
    for obj, original, _ in targets:
        if not obj.isValid() or not editable(obj).Shape.isSame(original):
            raise ValueError("The shape changed. Select its edges and start Round Edges again.")


def preview_rounding(targets, radius):
    check_rounding(targets)
    return [(obj, rounding.round_edges(original, indices, radius))
            for obj, original, indices in targets]


def commit_rounding(targets, planned, radius):
    check_rounding(targets)
    if radius == 0:
        return False
    if [obj for obj, _, _ in targets] != [obj for obj, _ in planned]:
        raise ValueError("The rounding preview is no longer current.")
    for _, shape in planned:
        geo.validate(shape, solid=True)
    apply_plan(targets[0][0].Document, planned, "Round Edges")
    return True


def prepare_subdivision(selection):
    faces = {}
    for obj, names in selection:
        editable(obj)
        if obj.InList or "SC_Support" in obj.PropertiesList or obj.ExpressionEngine:
            raise ValueError("This shape has links or expressions. Make a Part simple copy before subdividing.")
        geo.validate(obj.Shape)
        if not names and len(obj.Shape.Faces) == 1:
            names = ("Face1",)
        if not names:
            raise ValueError("Click one face of the object, then choose Subdivide Face.")
        for name in names:
            match = re.fullmatch(r"Face([1-9][0-9]*)", name)
            if not match or int(match[1]) > len(obj.Shape.Faces):
                raise ValueError("Select one flat face, not edges or a whole solid.")
            locking.require_unlocked(obj, [name])
            faces[(obj, int(match[1]) - 1)] = obj.Shape
    if len(faces) != 1:
        raise ValueError("Select one flat face first, then choose Subdivide Face.")
    (obj, index), shape = next(iter(faces.items()))
    geo.face_normal(shape.Faces[index])
    return obj, shape, index


def check_subdivision(target):
    obj, shape, _ = target
    try:
        check_rotation([(obj, shape)])
    except ValueError as error:
        raise ValueError("The face changed. Select it and start Subdivide Face again.") from error


def preview_subdivision(target, rows, columns, angle=0, pattern="equal_area", divisions=3):
    from ..modeling import subdivision
    check_subdivision(target)
    obj, original, index = target
    shape, regions = subdivision.divide(original, index, rows, columns, angle, pattern, divisions)
    return [(obj, shape)], regions


def commit_subdivision(target, planned, rows, columns, region_count=None):
    check_subdivision(target)
    count = rows * columns if region_count is None else region_count
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100:
        raise ValueError("The subdivision preview is no longer current.")
    if count == 1:
        return False
    obj, original, _ = target
    if len(planned) != 1 or planned[0][0] != obj:
        raise ValueError("The subdivision preview is no longer current.")
    result = geo.validate(planned[0][1], solid=bool(original.Solids))
    if len(result.Faces) != len(original.Faces) + count - 1:
        raise ValueError("The subdivision preview is no longer current.")
    apply_plan(obj.Document, planned, "Subdivide Face")
    return True


class RotationTarget(tuple):
    def __new__(cls, obj, shape, elements=(), mode="object"):
        inst = super().__new__(cls, (obj, shape))
        inst.obj = obj
        inst.shape = shape
        inst.elements = tuple(elements)
        inst.mode = mode
        return inst


def prepare_rotation(selection):
    if not selection:
        raise ValueError("Select an object first, then choose Rotate.")
    grouped = {}
    doc = None
    for obj, names in selection:
        editable(obj)
        locking.require_unlocked(obj)
        if doc is not None and obj.Document != doc:
            raise ValueError("Select objects from one document.")
        doc = obj.Document
        if obj.InList or "SC_Support" in obj.PropertiesList or obj.ExpressionEngine:
            raise ValueError("This shape has links or expressions. Make a Part simple copy before rotating.")
        geo.validate(obj.Shape)
        previous = grouped.get(obj, set())
        grouped[obj] = previous.union(names) if names else previous

    all_names = [n for names in grouped.values() for n in names]
    has_edges = bool(all_names and all(n.startswith("Edge") for n in all_names))
    has_faces = bool(all_names and all(n.startswith("Face") for n in all_names))

    targets = []
    for obj, names in grouped.items():
        if has_edges and names:
            targets.append(RotationTarget(obj, obj.Shape, sorted(names), mode="edge"))
        elif has_faces and names and len(obj.Shape.Faces) > len(names):
            targets.append(RotationTarget(obj, obj.Shape, sorted(names), mode="face"))
        else:
            targets.append(RotationTarget(obj, obj.Shape, (), mode="object"))

    if not targets:
        raise ValueError("Select an object first, then choose Rotate.")
    return targets


def check_rotation(targets):
    for target in targets:
        obj, original = target[0], target[1]
        if (not obj.isValid() or not obj.Name or obj.Document is None or obj.Document.getObject(obj.Name) != obj
                or not editable(obj).Shape.isSame(original)
                or obj.InList or "SC_Support" in obj.PropertiesList or obj.ExpressionEngine):
            raise ValueError("The shape changed. Select it and start Rotate again.")


def preview_rotation(targets, frames, angle):
    from ..modeling import rotation
    check_rotation(targets)
    shapes = []
    for target, frame in zip(targets, frames):
        mode = getattr(target, "mode", "object")
        if mode == "edge" and getattr(target, "elements", ()):
            rot_placement = frame.transform(angle)
            rot_edges = []
            for name in target.elements:
                edge = target.shape.getElement(name).copy()
                edge.Placement = rot_placement.multiply(edge.Placement)
                rot_edges.append(edge)
            preview_shape = Part.makeCompound(rot_edges) if len(rot_edges) > 1 else rot_edges[0]
            shapes.append(preview_shape)
        elif mode == "face" and getattr(target, "elements", ()):
            rot_placement = frame.transform(angle)
            rot_faces = []
            for name in target.elements:
                face = target.shape.getElement(name).copy()
                face.Placement = rot_placement.multiply(face.Placement)
                rot_faces.append(face)
            preview_shape = Part.makeCompound(rot_faces) if len(rot_faces) > 1 else rot_faces[0]
            shapes.append(preview_shape)
        else:
            shape = target.shape.copy()
            if rotation.angle_degrees(angle) != 0:
                shape.Placement = frame.transform(angle).multiply(target.shape.Placement)
            shapes.append(shape)
    return [(target.obj, shape) for target, shape in zip(targets, shapes)]


def commit_rotation(targets, frames, angle, copy=False):
    from ..modeling import rotation
    from ..modeling.offsetting import partition
    if rotation.angle_degrees(angle) == 0:
        return False
    check_rotation(targets)
    with transaction(targets[0][0].Document, "Rotate"):
        for target, frame in zip(targets, frames):
            obj = target.obj
            doc = obj.Document
            mode = getattr(target, "mode", "object")
            rot_placement = frame.transform(angle)
            if mode == "object":
                shape = target.shape.copy()
                shape.Placement = rot_placement.multiply(target.shape.Placement)
                obj.Placement = shape.Placement
            elif mode in ("edge", "face"):
                rot_edges = []
                for name in target.elements:
                    el = target.shape.getElement(name)
                    if el.ShapeType == "Edge":
                        e = el.copy()
                        e.Placement = rot_placement.multiply(e.Placement)
                        rot_edges.append(e)
                    elif el.ShapeType == "Face":
                        for fe in el.Edges:
                            e = fe.copy()
                            e.Placement = rot_placement.multiply(e.Placement)
                            rot_edges.append(e)
                if obj.Shape.Faces:
                    face_plane = None
                    for name in target.elements:
                        try:
                            el = target.shape.getElement(name)
                            adjacent = [f for f in obj.Shape.ancestorsOfType(el, Part.Face) if isinstance(getattr(f, "Surface", None), Part.Plane)]
                            if adjacent:
                                face_plane = geo.Plane.from_face(adjacent[0])
                                break
                        except Exception:
                            pass
                    if face_plane is None:
                        face_plane = geo.Plane.from_normal(frame.center, frame.axis)
                    base_shape = obj.Shape
                    if not copy:
                        try:
                            erased = geo.erase_elements(obj.Shape, target.elements)
                            if erased is not None and erased.isValid():
                                base_shape = erased
                        except Exception:
                            pass
                    wire = Part.Wire(rot_edges) if len(rot_edges) > 1 else rot_edges[0]
                    repartitioned, extra = partition(base_shape, wire, face_plane)
                    if repartitioned.isValid() and (not obj.Shape.Solids or repartitioned.Solids):
                        obj.Shape = repartitioned
                    else:
                        new_shape(doc, wire, "Rotated Line/Arc")
                else:
                    if len(target.elements) == len(obj.Shape.Edges):
                        obj.Placement = rot_placement.multiply(obj.Placement)
                    else:
                        remaining = [e.copy() for i, e in enumerate(obj.Shape.Edges, 1) if f"Edge{i}" not in target.elements]
                        new_edges = remaining + rot_edges
                        try:
                            obj.Shape = Part.Wire(new_edges)
                        except Exception:
                            obj.Shape = Part.makeCompound(new_edges)
    return True


def prepare_slicing(selection):
    targets = []
    for obj, _ in selection:
        editable(obj)
        if any(obj == previous for previous, _ in targets):
            continue
        if targets and obj.Document != targets[0][0].Document:
            raise ValueError("Select shapes from one document.")
        if obj.InList or "SC_Support" in obj.PropertiesList:
            raise ValueError("This shape has links to other objects. Make a Part simple copy before slicing.")
        geo.validate(obj.Shape)
        if not obj.Shape.Faces:
            raise ValueError("Select a solid or surface to slice.")
        targets.append((obj, obj.Shape))
    if not targets:
        raise ValueError("Select an object first, then choose Slice / Separate.")
    return targets


def check_slicing(targets):
    for obj, original in targets:
        if (not obj.isValid() or not editable(obj).Shape.isSame(original)
                or obj.InList or "SC_Support" in obj.PropertiesList):
            raise ValueError("The shape changed. Select it and start Slice / Separate again.")


def preview_slicing(targets, plane, offset):
    from ..modeling import slicing
    check_slicing(targets)
    planned = [(obj, slicing.split(original, plane, offset)) for obj, original in targets]
    if {side for _, pieces in planned for side, _ in pieces} != {-1, 1}:
        raise ValueError("The plane needs geometry on both sides. Move it farther inside the object.")
    return planned


def preview_stud_joints(cut_plan, plane, offset, params):
    from ..modeling import joints
    if len(cut_plan) != 1:
        raise ValueError("For a stud joint, select one object and cut it into two solid pieces.")
    obj, pieces = cut_plan[0]
    return [(obj, joints.add_studs(pieces, plane, offset, params))]


def create_fit_test(params):
    """Create a separate native document only after every sample validates."""
    from ..modeling import joints
    samples = joints.fit_samples(params)
    doc = App.newDocument("SimpleCADFitTest")
    try:
        doc.UndoMode = 1
        with transaction(doc, "Stud fit test"):
            for label, shape, clearance in samples:
                obj = doc.addObject("Part::Feature", "FitSample")
                obj.Label = label
                obj.Shape = shape
                obj.addProperty("App::PropertyString", "FitInformation", "Print test")
                obj.FitInformation = "Clearance per side: %+.6g mm. Print a pair to check the fit." % clearance
                obj.setEditorMode("FitInformation", 1)
                if App.GuiUp:
                    obj.ViewObject.ShapeColor = (.76, .84, .88)
                    obj.ViewObject.LineColor = (.15, .23, .29)
        return doc
    except Exception:
        App.closeDocument(doc.Name)
        raise


def commit_slicing(targets, planned):
    """One native object per piece, all created/replaced in a single Undo step."""
    check_slicing(targets)
    if [obj for obj, _ in targets] != [obj for obj, _ in planned]:
        raise ValueError("The slicing preview is no longer current.")
    for _, pieces in planned:
        if not pieces:
            raise ValueError("The cut produced no usable pieces.")
        for shape in pieces:
            geo.validate(shape)
    results = []
    with transaction(targets[0][0].Document, "Slice / Separate"):
        for obj, pieces in planned:
            label = obj.Label
            for index, shape in enumerate(pieces):
                result = obj if index == 0 else obj.Document.addObject("Part::Feature", "SimpleSlice")
                result.Shape = shape
                result.Label = label + " · %d" % (index + 1) if len(pieces) > 1 else label
                if result != obj and App.GuiUp:
                    for key in ("ShapeColor", "LineColor", "LineWidth", "PointColor", "PointSize", "Transparency", "DisplayMode"):
                        setattr(result.ViewObject, key, getattr(obj.ViewObject, key))
                results.append(result)
    return results


def extrusion_normal(obj, face):
    """Use the same resolved normal for the preview and the committed pull."""
    editable(obj)
    locking.require_face_unlocked(obj, face)
    support = getattr(obj, "SC_Support", None)
    if support:
        return geo.face_normal(geo.matching_support_face(editable(support).Shape, face))
    _, selected, _ = geo.pull_source(obj.Shape, face, include_remainder=False)
    return geo.face_normal(selected)


def extrusion_contact(obj, face):
    """Exact stop in the currently picked cap's distance coordinates."""
    editable(obj)
    locking.require_face_unlocked(obj, face)
    support = getattr(obj, "SC_Support", None)
    if support:
        base, selected, offset = editable(support).Shape, face, 0.0
        normal = geo.face_normal(geo.matching_support_face(base, selected))
    else:
        base, selected, _, offset = geo.pull_setup(obj.Shape, face, include_remainder=False)
        normal = geo.face_normal(selected)
    stop = geo.opposite_face(base, selected, normal)
    if stop is not None:
        return geo.OppositeFace(stop.distance - offset, stop.faces)
    return None


def extrude(obj, face, distance, return_pieces=False):
    editable(obj)
    locking.require_face_unlocked(obj, face)
    support = getattr(obj, "SC_Support", None)
    if "SC_Support" in obj.PropertiesList and support is None:
        raise ValueError("This profile has lost its support. Draw a new profile.")
    target = editable(support) if support else obj
    if support:
        result = geo.push_pull(target.Shape.copy(), face.copy(), distance, supported=True)
        remainder = None
    else:
        # Resolve the picked native face before making geometry copies inside
        # pull_source. Independent copies lose shared topology; boolean-based
        # equality is unreliable on repaired STL surface boundaries.
        result, remainder = geo.plan_push_pull(target.Shape, face, distance)
        # A pulled solid and an imported remainder surface can be microscopically
        # apart even when they are intended to meet. Project and imprint those
        # near-coincident straight edges before creating the remainder object so
        # the target face remains split/selectable at the contact.
        if remainder is not None:
            remainder = geo.imprint_pull_edges(remainder, result)
    pieces = sorted(result.Solids, key=lambda s: s.Volume, reverse=True) if len(result.Solids) > 1 else []
    original = target.Shape
    materials = tuple(target.ViewObject.ShapeAppearance) if App.GuiUp else ()
    results = [target]
    with transaction(obj.Document, "Push/Pull"):
        if remainder is not None:
            rest = obj.Document.addObject("Part::Feature", "SimpleSurface")
            rest.Label = target.Label + " surfaces"
            rest.Shape = remainder
            results.append(rest)
            if App.GuiUp:
                for key in ("ShapeColor", "LineColor", "LineWidth", "PointColor", "PointSize", "Transparency"):
                    setattr(rest.ViewObject, key, getattr(target.ViewObject, key))
        # Keep the picked object's identity for the extrusion. Other surfaces
        # stay native and editable in their own object, never a mixed solid/sheet.
        target.Shape = pieces[0] if pieces else result
        for index, piece in enumerate(pieces[1:], 2):
            part = obj.Document.addObject('Part::Feature', 'SimpleShape')
            part.Label = target.Label + ' · piece ' + str(index)
            part.Shape = piece
            if App.GuiUp:
                from . import materials as material_mapping
                for key in ('LineColor', 'LineWidth', 'PointColor', 'PointSize'):
                    setattr(part.ViewObject, key, getattr(target.ViewObject, key))
                part.ViewObject.ShapeAppearance = material_mapping.mapped(original, piece, materials)
            results.append(part)
        if support:
            obj.Document.removeObject(obj.Name)
    return results if return_pieces else target


def draw_circle(doc, profile, preferred=None):
    return draw_profile(doc, profile, preferred, "Circle")


def draw_polygon(doc, profile, preferred=None):
    return draw_profile(doc, profile, preferred, "Polygon")


def draw_profile(doc, profile, preferred, title):
    """Partition the underlying face, or create a standalone planar profile.

    Retracing an overlay consumes matching independent profiles/edges in the
    same Undo step. Prefer a larger host over the old profile being picked.
    """
    usable = visible_shapes(doc)
    if preferred is not None:
        editable(preferred)
        if preferred.Document != doc:
            raise ValueError("Choose a face in the current document.")
        usable = [preferred] + [obj for obj in usable if obj != preferred]
    duplicates = [obj for obj in usable if coinc.same(obj.Shape, profile)
                  or (obj.Shape.ShapeType == "Edge"
                      and any(coinc.same(obj.Shape, edge) for edge in profile.Edges))]
    for obj in usable:
        if obj in duplicates or not obj.Shape.Faces:
            continue
        try:
            geo.profile_support_faces(obj.Shape, profile)
        except ValueError:
            continue
        result = geo.divide_face_with_profile(obj.Shape, profile)
        planned = [(obj, result)] if result is not None else []
        planned.extend((other, None) for other in duplicates)
        apply_plan(doc, planned, "Divide face with " + title.lower())
        return obj, True
    # A profile across a face's edge divides the face where it overlaps and
    # adds a face beside it, as in SketchUp, rather than lying over it.
    shapes = [obj.Shape for obj in drawable(doc, preferred) if obj not in duplicates]
    pieces = [item for edge in profile.Edges for item in drawing.split_at_face_edges(edge, shapes)]
    if len({on for _, on in pieces}) == 2:
        return draw_pieces(doc, pieces, preferred, title)
    if preferred is not None and preferred not in duplicates:
        # A profile started on a face must fit on it, never fall back to an
        # overlapping free face when the containment check fails.
        geo.profile_support_faces(preferred.Shape, profile)
    return new_shape(doc, profile, title), False


def draw_line(doc, first, second, preferred=None):
    """Divide a face, complete missing triangles, or create a free 3D edge.

    Return the resulting object and whether a face was created/changed.
    """
    return draw_edge(doc, geo.line(first, second), preferred, "Line")


def draw_surface_line(doc, first, second, obj, face):
    """Follow a curved CAD surface, retaining incomplete chains as loose edges."""
    from ..surfaces.line import SurfacePath
    return draw_surface_curve(doc, SurfacePath(face, first, second).edge(), obj, face, 'Surface line')


def draw_surface_curve(doc, curve, obj, face, title, closed=False):
    """Split with an exact surface edge or closed outline in one Undo step."""
    from ..surfaces.line import covered, comparison_cache
    editable(obj)
    if obj.Document != doc or not any(f.isSame(face) for f in obj.Shape.Faces):
        raise ValueError('The surface changed. Pick the starting face again.')
    locking.require_face_unlocked(obj, face)
    geo.validate(curve)
    # A wrapped outline can touch several faces. Protect all of them, not only
    # its original support; this is still checked before a document transaction.
    locked,stale = locking.state(obj)
    if stale or locked:
        for i in locked:
            target = obj.Shape.Faces[i-1]
            if target.common(curve).Length > geo.EPS:
                locking.require_face_unlocked(obj,target)
    if not covered(obj.Shape, curve):
        raise ValueError('The drawing leaves the surface or crosses an opening. Make it smaller or move it.')
    with comparison_cache():
        return draw_edge(doc, curve, obj, title, surface=True, closed=closed)


def draw_arc(doc, edge, preferred=None):
    if len(edge.Vertexes) != 2 or not isinstance(edge.Curve, Part.Circle):
        raise ValueError("Choose an open circular arc.")
    return draw_edge(doc, edge, preferred, "Arc")


def drawable(doc, preferred=None):
    """The visible plain shapes a new edge can divide or join, preferred first."""
    candidates = ([preferred] if preferred is not None else []) + [
        obj for obj in doc.Objects if obj != preferred]
    usable = []
    for obj in candidates:
        if obj.Document != doc or obj.TypeId != "Part::Feature":
            continue
        if App.GuiUp and not obj.ViewObject.Visibility:
            continue
        try:
            editable(obj)
        except ValueError:
            continue
        usable.append(obj)
    return usable


def draw_edge(doc, edge, preferred=None, title="Line", surface=False, closed=False):
    usable = drawable(doc, preferred)
    pieces = [(edge, False)] if surface else drawing.split_at_face_edges(edge, [obj.Shape for obj in usable])
    if len(pieces) == 1:
        return _draw_edge(doc, edge, usable, preferred, title, surface, closed)
    return draw_pieces(doc, pieces, preferred, title, edge.Vertexes[-1].Point)


def draw_pieces(doc, pieces, preferred, title, end=None):
    """Draw the pieces of edges split at flat faces' edges, in one Undo step.

    Pieces on a face come first and divide it; the face's boundary then
    gains the vertices that the pieces beside it close loops through.
    """
    names = []
    with transaction(doc, title):
        for piece, _ in sorted(pieces, key=lambda item: not item[1]):
            obj, divided = _draw_edge(doc, piece, drawable(doc, preferred), preferred, title)
            names.append((obj.Name, divided))
    # A later piece can take up the loose line an earlier one left.
    results = [(doc.getObject(name), divided) for name, divided in names if doc.getObject(name)]
    faces = [obj for obj, divided in results if divided]
    # Report the face the edge ends on, as for an edge drawn whole, so a line
    # that closes a loop there still ends the chain.
    ending = [obj for obj in faces
              if end is not None and geo.on_face_boundary(obj.Shape, end, geo.modeling_precision())]
    if faces:
        return (ending or faces)[0], True
    return results[-1][0], False


def _draw_edge(doc, edge, usable, preferred, title, surface=False, closed=False):
    loose = [(obj, coinc.loose_edges(obj.Shape)) for obj in usable if not obj.InList]
    edges = [edge for _, lines in loose for edge in lines]
    targets = ([preferred] if preferred in usable else []) if surface else usable
    for obj in targets:
        divided = (geo.divide_face_with_edges(obj.Shape, edge, edges, surface=True) if surface
                   else geo.divide_face_with_edges(obj.Shape, edge, edges))
        if divided is not None:
            shape, boundary = divided
            if surface:
                from ..surfaces.line import preserves_area, preserves_volume
                # Curved splits keep the same solid/surface, area and volume.
                # The volume check comes straight after validation, which it
                # then need not repeat; the area check's Booleans come later.
                geo.validate(shape, solid=bool(obj.Shape.Solids))
                if (len(shape.Solids) != len(obj.Shape.Solids)
                        or obj.Shape.Solids and not preserves_volume(obj.Shape,shape,valid=True)
                        or not preserves_area(obj.Shape,shape)):
                    raise ValueError('The line could not divide this surface without changing its geometry.')
            consumed = []
            for source, lines in loose:
                if source == obj:
                    continue
                used = [line for line in lines if boundary.common(line).Length > geo.EPS]
                if not used:
                    continue
                names = ["Edge" + str(i + 1) for i, line in enumerate(source.Shape.Edges)
                         if any(coinc.same(line, item) for item in used)]
                remaining = geo.erase_elements(source.Shape, names)
                rest = geo.remaining_lines(used, boundary)
                parts = ([remaining] if remaining is not None else []) + rest
                remaining = None
                if parts:
                    remaining = parts[0] if len(parts) == 1 else Part.makeCompound(parts)
                if remaining is not None:
                    geo.validate(remaining)
                consumed.append((source, remaining))
            # The newest segment may also have a dangling portion beyond a
            # junction; preserve it just like older incomplete lines.
            rest = geo.remaining_lines(edge.Edges if surface else [edge], boundary)
            if rest:
                kept = [shape] + [s for _, s in consumed if s is not None]
                existing = Part.makeCompound([e for s in kept for e in s.Edges])
                rest = geo.remaining_lines(rest, existing)
            loose_shape = coinc.assemble([], rest)
            with transaction(doc, "Divide face"):
                obj.Shape = shape
                for source, remaining in consumed:
                    if remaining is None:
                        doc.removeObject(source.Name)
                    else:
                        source.Shape = remaining
                if loose_shape is not None:
                    line = doc.addObject("Part::Feature", "SimpleShape")
                    line.Label = "Line"
                    line.Shape = loose_shape
                    if App.GuiUp:
                        line.ViewObject.LineColor = (0.15, 0.23, 0.29)
                        line.ViewObject.LineWidth = 2.0
            return obj, True
    if surface:
        if closed:
            from ..surfaces.line import covered
            if covered(Part.makeCompound(preferred.Shape.Edges), edge):
                return preferred, True  # Retracing an existing region is a no-op.
            raise ValueError('The drawing could not divide this surface into a region. Make it smaller.')
        return new_shape(doc, edge, title), False
    shapes = [obj.Shape for obj in usable]
    faces = arcs.completions(shapes, edge, edges)
    arc_region = bool(faces)
    if not faces and isinstance(edge.Curve, Part.Line):
        first, second = [v.Point for v in edge.Vertexes]
        faces = drawing.triangle_completions(shapes, first, second)
    if not faces:
        faces = drawing.loop_completions(shapes, edge, edges)
    if faces:
        target, joined = None, None
        for obj in usable:
            joined = drawing.attach_triangles(obj.Shape, faces)
            if joined is not None:
                target = obj
                break
        boundary = drawing.boundary_of(faces)
        consumed = []
        for obj in usable:
            if obj.Shape.Faces or obj.InList:
                continue
            names = ["Edge" + str(i + 1) for i, e in enumerate(obj.Shape.Edges)
                     if abs(boundary.common(e).Length - e.Length) <= drawing.TOL]
            if names:
                consumed.append((obj, geo.erase_elements(obj.Shape.copy(), names)))
        with transaction(doc, "Complete arc face" if arc_region else "Complete triangle"):
            if target is not None:
                target.Shape = joined
                result = target
            else:
                result = doc.addObject("Part::Feature", "SimpleShape")
                triangles = all(len(face.Edges) == 3 and all(isinstance(e.Curve, Part.Line) for e in face.Edges)
                                for face in faces)
                result.Label = ("Arc face" if arc_region else ("Triangle" if triangles else "Face")
                                if len(faces) == 1 else "Triangles" if triangles else "Faces")
                result.Shape = coinc.assemble(faces)
                if App.GuiUp:
                    result.ViewObject.ShapeColor = (0.76, 0.84, 0.88)
                    result.ViewObject.LineColor = (0.15, 0.23, 0.29)
                    result.ViewObject.LineWidth = 2.0
            for obj, remaining in consumed:
                if remaining is None:
                    doc.removeObject(obj.Name)
                else:
                    obj.Shape = remaining
        return result, True
    # Only an edge whose bounds meet the new one's can coincide with it.
    lookup = drawing.edge_index(shapes)
    matches = {lookup.owners[i] for i in lookup.overlapping(edge.BoundBox, 1e-6)
               if coinc.same(edge, lookup.edges[i])}
    for owner, obj in enumerate(usable):
        if owner in matches:
            return obj, bool(obj.Shape.countElement('Face'))
    return new_shape(doc, edge, title), False


def transform(objects, delta, copy=False):
    if not objects:
        raise ValueError("Select an object first.")
    for obj in objects:
        editable(obj)
        if not copy: locking.require_unlocked(obj)
    doc = objects[0].Document
    if any(obj.Document != doc for obj in objects):
        raise ValueError("Select objects from one document.")
    if delta.Length < geo.EPS:
        raise ValueError("Choose a different destination.")
    results = []
    with transaction(doc, "Copy" if copy else "Move"):
        for obj in objects:
            if copy:
                result = doc.addObject("Part::Feature", "SimpleCopy")
                result.Label = obj.Label + " copy"
                result.Shape = obj.Shape.copy()
                if App.GuiUp:
                    result.ViewObject.ShapeAppearance = obj.ViewObject.ShapeAppearance
                    result.ViewObject.LineColor = obj.ViewObject.LineColor
            else:
                result = obj
                if "SC_Support" in result.PropertiesList:
                    # Moving a profile detaches it from its old support.
                    result.removeProperty("SC_Support")
            placement = App.Placement(result.Placement)
            placement.Base = placement.Base + delta
            result.Placement = placement
            results.append(result)
    return results


MIRROR_PLANES = ('Center', 'Min', 'Max', 'Origin')


def mirror_plane(objects, axis, through='Center'):
    """World point and normal of the plane flipping ``objects`` along ``axis``.

    Center, Min and Max refer to the combined bounding box of the objects, so
    a group mirrors as one unit; Min and Max place a mirrored copy right
    beside the originals. Origin mirrors across the world plane through 0.
    """
    if axis not in ('X', 'Y', 'Z'):
        raise ValueError("Choose the X, Y or Z axis to mirror along.")
    if through not in MIRROR_PLANES:
        raise ValueError("Choose where the mirror plane passes: Center, Min, Max or Origin.")
    index = 'XYZ'.index(axis)
    normal = App.Vector(*[1.0 if i == index else 0.0 for i in range(3)])
    if through == 'Origin':
        return App.Vector(), normal
    box = App.BoundBox()
    for obj in objects:
        box.add(obj.Shape.BoundBox)
    level = {'Center': box.Center[index], 'Min': (box.XMin, box.YMin, box.ZMin)[index],
             'Max': (box.XMax, box.YMax, box.ZMax)[index]}[through]
    return App.Vector(*[level if i == index else 0.0 for i in range(3)]), normal


def mirror(objects, axis, copy=True, through='Center'):
    """Flip whole objects along X, Y or Z in one Undo step.

    By default each object gets a mirrored copy and stays as it is; with
    ``copy=False`` the objects themselves are mirrored. Faces keep their
    order, so colors, hidden faces and locks stay on the same faces.
    """
    objects = list(dict.fromkeys(objects))
    if not objects:
        raise ValueError("Select the objects to mirror first.")
    doc = objects[0].Document
    for obj in objects:
        editable(obj)
        if obj.Document != doc:
            raise ValueError("Select objects from one document.")
        if not copy:
            locking.require_unlocked(obj)
            if obj.InList or obj.ExpressionEngine:
                raise ValueError("Another object depends on this shape. Mirror a copy instead.")
    base, normal = mirror_plane(objects, axis, through)
    planned = []
    for obj in objects:
        mirrored = obj.Shape.mirror(base, normal)
        if mirrored.Solids and mirrored.Volume < 0:
            mirrored.reverse()
        planned.append((obj, geo.validate(mirrored)))
    materials, results = [], []
    if App.GuiUp and not copy:
        materials = [(obj, tuple(obj.ViewObject.ShapeAppearance)) for obj, _ in planned]
    with transaction(doc, "Mirror", face_materials=materials):
        for obj, shape in planned:
            if copy:
                result = doc.addObject("Part::Feature", "SimpleMirror")
                result.Label = obj.Label + " mirrored"
                result.Shape = shape
                if App.GuiUp:
                    result.ViewObject.ShapeAppearance = obj.ViewObject.ShapeAppearance
                    result.ViewObject.LineColor = obj.ViewObject.LineColor
                    from . import visibility
                    hidden = visibility.hidden_faces(obj)
                    if hidden:
                        visibility.set_hidden(result, sorted(hidden))
            else:
                result = obj
                if "SC_Support" in result.PropertiesList:
                    # A mirrored profile no longer lies where it was drawn.
                    result.removeProperty("SC_Support")
                from . import visibility
                hidden = visibility.hidden_faces(obj)
                result.Shape = shape
                if hidden:
                    visibility.set_hidden(result, sorted(hidden))
            results.append(result)
    return results


def delete(objects):
    return delete_selection([(obj, ()) for obj in objects])


def unite(objects):
    """Replace the selected whole objects with one refined solid in one Undo."""
    from ..modeling import union
    objects = list(dict.fromkeys(objects))
    if not objects:
        raise ValueError('Select overlapping objects first, then choose Union (J).')
    doc = objects[0].Document
    originals = []
    for obj in objects:
        editable(obj)
        if obj.Document != doc:
            raise ValueError('Select objects from one document for Union.')
        if obj.InList or 'SC_Support' in obj.PropertiesList or obj.ExpressionEngine:
            raise ValueError('This shape has links or expressions. Make a Part simple copy before Union.')
        originals.append(obj.Shape)
    result = union.combine(originals)
    if any(not obj.isValid() or not obj.Shape.isSame(shape) for obj, shape in zip(objects, originals)):
        raise ValueError('A selected shape changed. Select the objects and try Union again.')
    with transaction(doc, 'Union'):
        target = objects[0]
        target.Shape = result
        target.Label = 'Union'
        for obj in objects[1:]:
            doc.removeObject(obj.Name)
    return target


def intersect(selection):
    """Combine selected owners into editable surfaces, splitting chosen faces."""
    from ..modeling import intersection
    if not selection:
        raise ValueError('Select intersecting faces or whole objects, then Intersect Faces (I).')
    doc = selection[0][0].Document
    targets = {}
    for obj, names in selection:
        editable(obj)
        if obj.Document != doc:
            raise ValueError('Select objects from one document.')
        if obj.InList or 'SC_Support' in obj.PropertiesList or obj.ExpressionEngine:
            raise ValueError('This shape has links or expressions. Make a Part simple copy before intersecting.')
        # Combining owners removes their independent identities; protect all
        # their locked geometry, including otherwise unchanged surfaces.
        locking.require_unlocked(obj)
        if not obj.Shape.Faces:
            raise ValueError('Intersect Faces needs faces or objects with surfaces.')
        names = set(names)
        if any(not re.fullmatch(r'Face[1-9][0-9]*', name) for name in names):
            raise ValueError('Select faces or whole objects for Intersect Faces, not edges or vertices.')
        if any(int(name[4:]) > len(obj.Shape.Faces) for name in names):
            raise ValueError('The face selection is no longer current. Select it again.')
        if obj not in targets: targets[obj] = names
        elif not names: targets[obj] = set()
        elif targets[obj]: targets[obj].update(names)
    selected, remaining, edges = [], [], []
    originals = []
    for obj, names in targets.items():
        shape = obj.Shape
        originals.append(shape)
        for i, face in enumerate(shape.Faces, 1):
            (selected if not names or 'Face'+str(i) in names else remaining).append(face)
        edges.extend(coinc.loose_edges(shape))
        # An isolated vertex cannot be displayed/erased with the face editor.
        boundary_vertices = {}
        for edge in shape.Edges:
            for vertex in edge.Vertexes:
                boundary_vertices.setdefault(hash(vertex), []).append(vertex)
        if any(not any(vertex.isSame(v) for v in boundary_vertices.get(hash(vertex), ()))
               for vertex in shape.Vertexes):
            raise ValueError('Separate loose points before intersecting surfaces.')
    result = intersection.split(selected, remaining, edges)
    objects = list(targets)
    if any(not obj.Shape.isSame(original) for obj, original in zip(objects, originals)):
        raise ValueError('A selected object changed. Select the faces again.')
    with transaction(doc, 'Intersect Faces', material_groups=[objects]):
        target = objects[0]
        target.Shape = result
        target.Label = 'Intersection'
        for obj in objects[1:]: doc.removeObject(obj.Name)
    return target


def delete_selection(selection):
    """Apply one planned edit; return (changed objects, ignored seam selections)."""
    if not selection:
        raise ValueError("Select an edge, face, or object to delete.")
    doc = selection[0][0].Document
    targets = {}
    for obj, names in selection:
        editable(obj)
        if obj.Document != doc:
            raise ValueError("Select objects from one document.")
        if obj.Name not in targets:
            targets[obj.Name] = (obj, set(names))
        elif not names:
            targets[obj.Name][1].clear()  # Whole-object selection takes priority.
        elif targets[obj.Name][1]:
            targets[obj.Name][1].update(names)
    # Resolve original names before topology changes, and reach every visible
    # full geometric match. Whole-object selection deliberately does not spread.
    whole_objects = {name for name, (_, names) in targets.items() if not names}
    seeds, ignored_seams = [], 0
    for obj, names in targets.values():
        # Edges of faces selected on the same object go with those faces. A
        # box selection picks them up too, but they must not reach into other
        # objects whose edges merely coincide, such as a rod's rim lying on
        # the rim of the hole it sits in.
        chosen_faces = []
        for name in names:
            if re.match(r"^Face[1-9][0-9]*$", name):
                try:
                    chosen_faces.append(obj.Shape.getElement(name))
                except Exception:
                    pass
        for raw_name in tuple(names):
            m = re.match(r"^(Edge|Face)[1-9][0-9]*", raw_name)
            if not m:
                raise ValueError("Select an edge, a face, or a whole object in the Model tree.")
            name = m.group(0)
            if name != raw_name:
                names.remove(raw_name)
                names.add(name)
            try:
                part = obj.Shape.getElement(name)
            except Exception as error:
                raise ValueError("The selection is no longer current. Select it again.") from error
            if part.ShapeType == "Edge" and geo.is_seam_edge(obj.Shape, part):
                names.remove(name)
                ignored_seams += 1
            elif not (part.ShapeType == "Edge" and any(part.isSame(edge) for face in chosen_faces for edge in face.Edges)):
                seeds.append(part)
    # An emptied subelement selection is a no-op, never a whole-object delete.
    targets = {name: item for name, item in targets.items() if item[1] or name in whole_objects}
    if seeds:
        seed_compound = Part.makeCompound(seeds) if len(seeds) > 1 else seeds[0]
        seed_bb = seed_compound.BoundBox
        seed_bb.enlarge(coinc.TOL)
        seed_lookup = coinc.Index(seeds)
        seed_kinds = {seed.ShapeType for seed in seeds}
        for obj in visible_shapes(doc):
            if obj.Name in targets and not targets[obj.Name][1]:
                continue
            if not obj.Shape.BoundBox.intersect(seed_bb):
                continue
            matches = set()
            for kind in ("Edge", "Face"):
                if kind not in seed_kinds:
                    continue
                for i, part in enumerate(getattr(obj.Shape, kind + "s")):
                    if not part.BoundBox.intersect(seed_bb):
                        continue
                    if next(seed_lookup.matches(part), None) is not None:
                        if kind == "Edge" and geo.is_seam_edge(obj.Shape, part):
                            continue
                        matches.add(kind + str(i + 1))
            if matches:
                if obj.Name not in targets:
                    targets[obj.Name] = (obj, matches)
                else:
                    targets[obj.Name][1].update(matches)

    # Open surfaces sharing the selected edge must be erased together, so two
    # flat faces in separate objects merge rather than both losing a boundary.
    entries = list(targets.values())
    groups = []
    for obj, names in entries:
        selected = [obj.Shape.getElement(name) for name in names if name.startswith("Edge")]
        # A solid joins a separate surface too: a face drawn beside a block
        # merges with the block's coplanar face, as in SketchUp.
        touching = [group for group in groups if names
                    and any(other_names and not (obj.Shape.Solids and other.Shape.Solids)
                            and any(coinc.same(edge, other.Shape.getElement(name))
                                    for edge in selected for name in other_names if name.startswith("Edge"))
                            for other, other_names in group)]
        combined = [(obj, names)]
        for group in touching:
            combined.extend(group)
            groups.remove(group)
        groups.append(combined)
    planned = []
    for group in groups:
        obj, names = group[0]
        if len(group) == 1:
            planned.append((obj, geo.erase_elements(obj.Shape, names) if names else None))
            continue
        shape = Part.makeCompound([member.Shape for member, _ in group])
        if shape.Solids:
            # Erase on the faces of all members as one surface; a result that
            # closes becomes a solid again.
            shape = Part.makeCompound([face for member, _ in group for face in member.Shape.Faces])
        selected = [member.Shape.getElement(name) for member, names in group for name in names]
        selected_lookup = coinc.Index(selected)
        names = [kind + str(i + 1) for kind in ("Edge", "Face")
                 for i, part in enumerate(getattr(shape, kind + "s"))
                 if next(selected_lookup.matches(part), None) is not None]
        result = geo.erase_elements(shape, names)
        # Retain a referenced object's identity where possible.
        # A solid's object keeps its identity over a surface split off it.
        keeper = next((member for member, _ in group if member.InList),
                      next((member for member, _ in group if member.Shape.Solids), obj))
        planned.append((keeper, result))
        planned.extend((member, None) for member, _ in group if member != keeper)
    apply_plan(doc, planned, "Delete")
    return len(planned), ignored_seams


def apply_plan(doc, planned, title):
    deleted = {obj.Name for obj, result in planned if result is None}
    for obj, result in planned:
        if result is None and any(parent.Name not in deleted for parent in obj.InList):
            raise ValueError("Another object depends on this shape. Select its dependents too.")
    if not planned:
        return
    with transaction(doc, title):
        for obj, result in planned:
            if result is None:
                doc.removeObject(obj.Name)
            else:
                obj.Shape = result


def heal_dangling_wires(doc, objects=None):
    """Integrate any standalone elongation or offset profiles into their carrying solid faces."""
    from ..modeling.offsetting import partition, partition_concentric_circle
    healed = 0
    all_objs = visible_shapes(doc) if objects is None else objects
    wire_objs = [obj for obj in all_objs
                 if hasattr(obj, 'Shape') and obj.Shape
                 and not obj.Shape.Faces and not obj.Shape.Solids
                 and obj.Shape.Edges
                 and (obj.Label.startswith(('Elongated ', 'Offset edge')) or obj.Name.startswith('SimpleShape'))]
    if not wire_objs:
        return 0

    solids = [obj for obj in doc.Objects
              if hasattr(obj, 'Shape') and obj.Shape and obj.Shape.Solids]
    if not solids:
        return 0

    for wire_obj in wire_objs:
        wire = wire_obj.Shape
        for solid_obj in solids:
            try:
                editable(solid_obj)
            except Exception:
                continue
            target_face = None
            target_plane = None
            for face in solid_obj.Shape.Faces:
                if not isinstance(face.Surface, Part.Plane):
                    continue
                f_bb = face.BoundBox
                w_bb = wire.BoundBox
                if (w_bb.XMin >= f_bb.XMin - 0.5 and w_bb.XMax <= f_bb.XMax + 0.5 and
                    w_bb.YMin >= f_bb.YMin - 0.5 and w_bb.YMax <= f_bb.YMax + 0.5 and
                    w_bb.ZMin >= f_bb.ZMin - 0.5 and w_bb.ZMax <= f_bb.ZMax + 0.5):
                    dist, _, _ = face.distToShape(wire)
                    if dist < 0.05:
                        target_face = face
                        target_plane = geo.Plane.from_face(face)
                        break
            if target_face is not None and target_plane is not None:
                all_already_present = all(
                    any(coinc.same(w_edge, s_edge) for s_edge in target_face.Edges)
                    for w_edge in wire.Edges
                )
                if all_already_present:
                    with transaction(doc, 'Remove redundant wire'):
                        doc.removeObject(wire_obj.Name)
                    healed += 1
                    break

                repartitioned = None
                if len(wire.Edges) == 1 and isinstance(getattr(wire.Edges[0], 'Curve', None), Part.Circle):
                    try:
                        repartitioned = partition_concentric_circle(solid_obj.Shape, wire.Edges[0], target_plane)
                    except Exception:
                        repartitioned = None

                if repartitioned is None or not repartitioned.isValid() or len(repartitioned.Faces) <= len(solid_obj.Shape.Faces):
                    try:
                        repartitioned, _ = partition(solid_obj.Shape, wire, target_plane)
                    except Exception:
                        repartitioned = None

                if repartitioned is not None and repartitioned.isValid() and len(repartitioned.Faces) > len(solid_obj.Shape.Faces):
                    with transaction(doc, 'Heal wire into face'):
                        solid_obj.Shape = repartitioned
                        doc.removeObject(wire_obj.Name)
                    healed += 1
                    break

    return healed


heal_dangling_elongations = heal_dangling_wires


def heal(doc, objects, tolerance=None):
    """Heal the named shapes to the modeling precision in one Undo step.

    Each shape is healed in an isolated worker process, so a kernel crash on
    damaged geometry cannot take FreeCAD down. A shape healing cannot improve
    is left exactly as it is; its reason is returned with the reports.
    """
    from ..repair import healing
    from ..core import preferences
    tolerance = preferences.precision() if tolerance is None else tolerance
    objects = list(dict.fromkeys(objects))
    if not objects:
        raise ValueError("Select the shapes to heal.")
    planned, reports = [], []
    for obj in objects:
        editable(obj)
        if obj.Document != doc:
            raise ValueError("Select objects from one document.")
        locking.require_unlocked(obj)
        try:
            healed, report = healing.heal_isolated(obj.Shape, tolerance)
        except ValueError as error:
            reports.append({'object': obj.Name, 'healed': False, 'reason': str(error)})
            continue
        planned.append((obj, healed))
        reports.append({'object': obj.Name, 'healed': True, **report})
    if planned:
        apply_plan(doc, planned, "Heal to precision")
    return reports


def cleanup(doc, objects=None):
    """Collapse exact duplicates and join touching open surfaces in one Undo.

    Closed solids retain their boundaries; extra surfaces are not fused into a
    solid. Partial overlaps and nearby geometry are not duplicate faces/edges.
    """
    heal_dangling_wires(doc, objects=objects)
    objects = list(dict.fromkeys(visible_shapes(doc) if objects is None else objects))
    for obj in objects:
        editable(obj)
        if obj.Document != doc:
            raise ValueError("Select objects from one document.")
    # Keep solid topology intact and use it as the first owner of matching
    # overlay faces/lines. Do not strip a boundary shared by different solids.
    ordered = sorted(objects, key=lambda obj: not bool(obj.Shape.Solids))
    owned_faces, owned_edges, kept_solids = [], [], []
    planned, surfaces = [], []
    for obj in ordered:
        shape = obj.Shape
        if len(shape.Solids) > 1 or (shape.Solids and (shape.ShapeType not in ("Solid", "CompSolid"))):
            raise ValueError("Separate compound solids or mixed solid/surface objects before merging geometry.")
        if shape.Solids:
            duplicate = any(len(shape.Faces) == len(other.Faces)
                            and abs(shape.Volume - other.Volume) <= max(1e-7, shape.Volume * 1e-9)
                            and all(any(coinc.same(face, old) for old in other.Faces) for face in shape.Faces)
                            for other in kept_solids)
            if duplicate:
                planned.append((obj, None))
                continue
            kept_solids.append(shape)
            owned_faces.extend(shape.Faces)
            owned_edges.extend(shape.Edges)
            continue
        faces = []
        for face in shape.Faces:
            if not any(coinc.same(face, other) for other in owned_faces):
                faces.append(face)
                owned_faces.append(face)
        edges = [edge for edge in coinc.loose_edges(shape)
                 if not any(coinc.same(edge, other) for other in owned_edges)]
        owned_edges.extend(shape.Edges)
        result = coinc.assemble(faces, edges)
        if result is None:
            planned.append((obj, None))
        else:
            surfaces.append((obj, result))
    # Remove loose lines covered by a later surface too, independent of tree order.
    surfaces = [(obj, coinc.assemble(shape.Faces, [edge for edge in coinc.loose_edges(shape)
                 if not any(coinc.same(edge, boundary) for face in owned_faces for boundary in face.Edges)]))
                for obj, shape in surfaces]
    groups = []
    for obj, shape in surfaces:
        if shape is None:
            planned.append((obj, None))
            continue
        touching = [group for group in groups
                    if any(coinc.shares_edge(shape, other) for _, other in group)]
        combined = [(obj, shape)]
        for group in touching:
            combined.extend(group)
            groups.remove(group)
        groups.append(combined)
    for group in groups:
        keeper = next((obj for obj, _ in group if obj.InList), group[-1][0])
        shape = coinc.assemble([face for _, result in group for face in result.Faces],
                               [edge for _, result in group for edge in coinc.loose_edges(result)])
        # Repeating cleanup should not create empty Undo steps.
        if len(group) > 1 or (len(shape.Faces), len(shape.Edges)) != (len(keeper.Shape.Faces), len(keeper.Shape.Edges)):
            planned.append((keeper, shape))
        planned.extend((obj, None) for obj, _ in group if obj != keeper)
    apply_plan(doc, planned, "Merge coincident geometry")
    return len(planned)


def offset(obj, name, distance, normal=None):
    """Offset a face into regions, or copy an edge without creating a face."""
    from ..modeling.offsetting import Profile, partition
    editable(obj)
    if obj.InList or 'SC_Support' in obj.PropertiesList or obj.ExpressionEngine:
        raise ValueError('This shape has links or expressions. Make a Part simple copy before offsetting.')
    if not re.fullmatch(r'(Face|Edge)[1-9][0-9]*',name):
        raise ValueError('Select one face or edge to offset.')
    try: element=obj.Shape.getElement(name)
    except Exception as error: raise ValueError('The selected face or edge no longer exists.') from error
    source=Profile(element,normal)
    if source.face and not getattr(source, 'is_cylinder', False): locking.require_unlocked(obj,[name])
    profile=source.offset(distance)
    # Open edge offsets intentionally bypass draw_line/draw_arc: no face completion,
    # imprints or closing caps, even if the copied edge touches other lines.
    if not source.face or getattr(source, 'is_cylinder', False):
        is_closed = getattr(source, 'is_cylinder', False) or element.isClosed() or (
            isinstance(getattr(element, 'Curve', None), Part.Circle)
            and abs(element.Length - element.Curve.Radius * math.tau) < 1e-4
        )
        if is_closed and obj.Shape.Faces:
            if getattr(source, 'is_cylinder', False):
                adjacent = []
                for e in element.Edges:
                    for f in obj.Shape.ancestorsOfType(e, Part.Face):
                        if not f.isSame(element) and isinstance(f.Surface, Part.Plane):
                            if not any(f.isSame(existing) for existing in adjacent):
                                adjacent.append(f)
            else:
                adjacent = [f for f in obj.Shape.ancestorsOfType(element, Part.Face) if isinstance(f.Surface, Part.Plane)]
                if not adjacent:
                    adjacent = [f for f in obj.Shape.Faces if isinstance(f.Surface, Part.Plane) and any(e.isSame(element) for e in f.Edges)]
            if adjacent:
                face_plane = geo.Plane.from_face(adjacent[0])
                if getattr(source, 'is_cylinder', False):
                    center = face_plane.project(source.center)
                    radius = source.radius + distance
                    if radius > geo.EPS:
                        circle = Part.Circle(center, face_plane.normal, radius)
                        profile = circle.toShape()
                elif isinstance(getattr(element, 'Curve', None), Part.Circle):
                    center = face_plane.project(element.Curve.Center)
                    radius = element.Curve.Radius + distance
                    if radius > geo.EPS:
                        circle = Part.Circle(center, face_plane.normal, radius)
                        profile = circle.toShape()
                try:
                    planned, extra = partition(obj.Shape, profile, face_plane)
                    if len(planned.Faces) > len(obj.Shape.Faces):
                        with transaction(obj.Document, 'Offset edge to face'):
                            obj.Shape = planned
                        return [obj]
                except Exception:
                    pass
        return [new_shape(obj.Document, profile, 'Offset edge')]
    planned,extra=partition(obj.Shape,profile,source.plane)
    material=None
    if App.GuiUp:
        from .appearance import clone
        materials=obj.ViewObject.ShapeAppearance
        material=clone(materials[min(int(name[4:])-1,len(materials)-1)])
    results=[obj]
    with transaction(obj.Document,'Offset face'):
        obj.Shape=planned
        if extra:
            border=obj.Document.addObject('Part::Feature','SimpleOffset')
            border.Label='Offset border'; border.Shape=coinc.assemble(extra)
            if App.GuiUp:
                border.ViewObject.ShapeAppearance=[material]*len(border.Shape.Faces)
                border.ViewObject.LineColor=obj.ViewObject.LineColor
                border.ViewObject.LineWidth=obj.ViewObject.LineWidth
            results.append(border)
    return results


def elongate(obj, name, distance, direction, mode='ellipse', cut_hole=False, symmetric=True, point=None):
    """Elongate a circular hole/rim or flat face into an ellipse or slot along a direction."""
    from ..modeling.elongating import ElongateProfile
    from ..modeling.offsetting import partition
    editable(obj)
    if obj.InList or 'SC_Support' in obj.PropertiesList or obj.ExpressionEngine:
        raise ValueError('This shape has links or expressions. Make a Part simple copy before elongating.')
    if not re.fullmatch(r'(Face|Edge)[1-9][0-9]*', name):
        raise ValueError('Select one face or edge to elongate.')
    try:
        element = obj.Shape.getElement(name)
    except Exception as error:
        raise ValueError('The selected face or edge no longer exists.') from error

    profile_builder = ElongateProfile(element, point=point)
    if profile_builder.is_face:
        locking.require_unlocked(obj, [name])

    face_plane = profile_builder.plane
    if profile_builder.is_cylinder:
        adjacent = []
        for e in element.Edges:
            for f in obj.Shape.ancestorsOfType(e, Part.Face):
                if not f.isSame(element) and isinstance(f.Surface, Part.Plane):
                    if not any(f.isSame(existing) for existing in adjacent):
                        adjacent.append(f)
        if adjacent:
            if point is not None:
                target_face = min(adjacent, key=lambda f: (f.CenterOfMass - point).Length)
            else:
                target_face = max(adjacent, key=lambda f: f.Area)
            face_plane = geo.Plane.from_face(target_face)
            profile_builder.center = face_plane.project(profile_builder.center)
            profile_builder.plane = face_plane
    elif not profile_builder.is_face:
        adjacent = [f for f in obj.Shape.ancestorsOfType(element, Part.Face) if isinstance(f.Surface, Part.Plane)]
        if not adjacent:
            adjacent = [f for f in obj.Shape.Faces if isinstance(f.Surface, Part.Plane) and any(e.isSame(element) for e in f.Edges)]
        if adjacent:
            target_face = min(adjacent, key=lambda f: (f.CenterOfMass - point).Length) if point is not None else adjacent[0]
            face_plane = geo.Plane.from_face(target_face)
            profile_builder.plane = face_plane
            if profile_builder.is_circle:
                profile_builder.center = face_plane.project(profile_builder.center)

    profile = profile_builder.elongate(distance, direction, mode=mode, symmetric=symmetric)

    if cut_hole and obj.Shape.Solids:
        cyl_face = None
        if profile_builder.is_cylinder:
            cyl_face = element
        elif element.ShapeType == 'Edge':
            adjacent_cyls = [f for f in obj.Shape.ancestorsOfType(element, Part.Face) if isinstance(getattr(f, 'Surface', None), Part.Cylinder)]
            if adjacent_cyls:
                cyl_face = adjacent_cyls[0]
        if cyl_face is not None:
            cyl_axis = geo.unit(cyl_face.Surface.Axis)
            bb = obj.Shape.BoundBox
            height = max(bb.XLength, bb.YLength, bb.ZLength) * 2.0
            base_wire = profile if isinstance(profile, Part.Wire) else Part.Wire([profile])
            cutter = Part.Face(base_wire).extrude(cyl_axis * height)
            cutter.translate(-cyl_axis * (height * 0.5))
            cut_shape = obj.Shape.cut(cutter)
            if cut_shape.isValid() and cut_shape.Solids:
                with transaction(obj.Document, 'Elongate hole'):
                    obj.Shape = cut_shape.Solids[0]
                return [obj]

    if obj.Shape.Faces:
        try:
            planned, extra = partition(obj.Shape, profile, face_plane)
            if len(planned.Faces) > len(obj.Shape.Faces):
                with transaction(obj.Document, 'Elongate hole / face'):
                    obj.Shape = planned
                return [obj]
        except Exception:
            pass

    return [new_shape(obj.Document, profile, 'Elongated ' + ('ellipse' if mode == 'ellipse' else 'slot'))]


def prepare_vertex(obj, name):
    from ..modeling.vertex_edit import Neighborhood
    editable(obj)
    if obj.InList or 'SC_Support' in obj.PropertiesList or obj.ExpressionEngine:
        raise ValueError('This shape has links or expressions. Make a Part simple copy before moving vertices.')
    neighborhood = Neighborhood(obj.Shape, name)
    locking.require_unlocked(obj, ['Face'+str(i+1) for i in neighborhood.faces] or [name])
    return neighborhood


def move_vertex(obj, name, delta, captured=None):
    current = prepare_vertex(obj, name) if captured is None else captured
    editable(obj)
    if not obj.Shape.isEqual(current.shape):
        raise ValueError('The shape changed. Select the vertex again.')
    locking.require_unlocked(obj, ['Face'+str(i+1) for i in current.faces] or [name])
    result, origins = current.build(delta)
    materials = ()
    if App.GuiUp and origins:
        values = tuple(obj.ViewObject.ShapeAppearance)
        mapped = [values[i] if len(values)==len(current.shape.Faces) else values[0] for i in origins]
        materials = [(obj, mapped)]
    with transaction(obj.Document, 'Move Vertex', face_materials=materials):
        obj.Shape = result
    return obj


def prepare_scaling(selection):
    try:
        return prepare_rotation(selection)
    except ValueError as error:
        raise ValueError(str(error).replace('Rotate', 'Scale / Stretch').replace('rotating', 'scaling')) from error


def check_scaling(targets):
    try:
        check_rotation(targets)
        for obj, _ in targets: locking.require_unlocked(obj)
    except ValueError as error:
        raise ValueError(str(error).replace('Rotate', 'Scale / Stretch')) from error


def scale_objects(targets, values, axes='World', pivot='Selection'):
    from ..modeling import forming
    check_scaling(targets)
    values=forming.factors(values)
    frames=forming.scale_frames([s for _,s in targets], axes, pivot)
    if values==(1,1,1): return False
    planned=[]; materials=[]; hidden=[]
    for (obj,original),frame in zip(targets,frames):
        result,origins=forming.scaled(original,frame,values)
        planned.append((obj,result))
        if App.GuiUp and origins:
            from . import visibility
            hidden_before=visibility.hidden_faces(obj)
            if hidden_before:hidden.append((obj,[i+1 for i,source in enumerate(origins) if source+1 in hidden_before]))
            old=tuple(obj.ViewObject.ShapeAppearance)
            materials.append((obj,[old[i] if len(old)==len(original.Faces) else old[0] for i in origins]))
    with transaction(targets[0][0].Document,'Scale / Stretch',face_materials=materials):
        for obj,result in planned:obj.Shape=result
        for obj,indices in hidden:visibility.set_hidden(obj,indices)
    return True


def prepare_profiles(selection, mode='Loft'):
    """Keep selection order; edges selected on one object form one path/profile."""
    targets=[];doc=None
    for obj,names in selection:
        editable(obj)
        if doc is not None and doc!=obj.Document:raise ValueError('Select profiles from one document.')
        doc=obj.Document
        original=obj.Shape
        names=tuple(n for n in names if n)
        if names and all(re.fullmatch(r'Edge[1-9][0-9]*',n) for n in names):
            try: selected=Part.makeCompound([original.getElement(n) for n in names])
            except Exception as error:raise ValueError('An edge no longer exists. Select it again.') from error
            targets.append((obj,original,names,selected))
        elif names:
            for name in names:
                if not re.fullmatch(r'Face[1-9][0-9]*',name):raise ValueError('Select faces or connected edges, not vertices.')
                try:selected=original.getElement(name)
                except Exception as error:raise ValueError('A face no longer exists. Select it again.') from error
                targets.append((obj,original,(name,),selected))
        else:targets.append((obj,original,(),original))
    if mode=='Loft' and not 2<=len(targets)<=32:raise ValueError('Select 2 to 32 face or wire profiles in order, then choose Loft.')
    if mode=='Sweep' and len(targets)!=2:raise ValueError('Select a profile first and a connected path second, then choose Sweep.')
    check_profiles(targets)
    return targets


def check_profiles(targets):
    for obj,original,_,_ in targets:
        if not obj.isValid() or not obj.Name or obj.Document is None or not editable(obj).Shape.isSame(original):
            raise ValueError('A source changed. Select the profiles/path again.')


def form_preview(targets,mode,**options):
    from ..modeling import forming
    check_profiles(targets)
    shapes=[s for _,_,_,s in targets]
    try:
        if mode=='Loft':return forming.loft(shapes,**options)
        if mode=='Sweep':return forming.sweep(*shapes,**options)
        raise ValueError('Choose Loft or Sweep.')
    except Part.OCCError as error:
        raise ValueError('The profiles/path cannot form this shape. Adjust their spacing, size or orientation.') from error


def commit_form(targets,mode,result,hide_sources=True):
    check_profiles(targets)
    geo.validate(result)
    doc=targets[0][0].Document
    with transaction(doc,mode):
        obj=doc.addObject('Part::Feature','SimpleShape');obj.Label=mode;obj.Shape=result
        if App.GuiUp:
            source=targets[0][0]
            obj.ViewObject.ShapeColor=source.ViewObject.ShapeColor
            obj.ViewObject.LineColor=source.ViewObject.LineColor
            obj.ViewObject.LineWidth=source.ViewObject.LineWidth
            if hide_sources:
                for owner,original,names,_ in targets:
                    # A selected face/edge may belong to a larger solid: keep it visible.
                    if not names and not original.Solids:owner.ViewObject.Visibility=False
    return obj


def prepare_deformation(selection,detail=6):
    from ..modeling.deformation import Region
    objects=list(dict.fromkeys(obj for obj,_ in selection))
    if len(objects)!=1:raise ValueError('Select a face, vertex or region on one object, then choose Bend / Soft Deform.')
    obj=objects[0];prepare_scaling([(obj,())])
    names=tuple(dict.fromkeys(n for _,names in selection for n in names if n))
    for name in names:
        if not re.fullmatch(r'(Face|Edge|Vertex)[1-9][0-9]*',name):raise ValueError('Select native faces, edges or vertices.')
        obj.Shape.getElement(name)
    return obj,Region(obj.Shape,detail),names


def check_deformation(target):
    obj,region,_=target
    check_scaling([(obj,region.shape)])


def commit_deformation(target,points):
    from . import visibility
    check_deformation(target)
    obj,region,_=target
    result,origins=region.build(points)
    if result.isSame(region.shape):return False
    materials=();hidden=[]
    if App.GuiUp:
        old=tuple(obj.ViewObject.ShapeAppearance)
        materials=[(obj,[old[i] if len(old)==len(region.shape.Faces) else old[0] for i in origins])]
        before=visibility.hidden_faces(obj)
        hidden=[i+1 for i,source in enumerate(origins) if source+1 in before]
    with transaction(obj.Document,'Bend / Soft Deform',face_materials=materials):
        obj.Shape=result
        if App.GuiUp:
            if hidden:visibility.set_hidden(obj,hidden)
            # Fine triangle edges obscure the shape; geometry is still normal
            # selectable Part faces, and Flat Lines can be restored in View.
            obj.ViewObject.DisplayMode='Shaded'
    return True
