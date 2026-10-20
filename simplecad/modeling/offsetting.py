"""Planar offsets: native face boundaries, parallel lines and concentric arcs."""
import math
import Part
from ..core import geometry as g, coincident as coinc


def _filled_offset(face,distance,allow_empty=False):
    """Offset a filled loop; handle periodic circle seams analytically."""
    if len(face.Edges)==1 and isinstance(face.Edges[0].Curve,Part.Circle):
        curve=face.Edges[0].Curve
        radius=curve.Radius+distance
        if radius<=g.EPS:
            if allow_empty: return None
            raise ValueError('Offset reaches the center.')
        result=Part.Face(Part.Wire([Part.makeCircle(radius,curve.Center,curve.Axis)]))
        if g.face_normal(result).dot(g.face_normal(face))<0: result.reverse()
        return result
    result=face.makeOffset2D(distance,join=2,fill=False,openResult=False,intersection=False)
    if result.isNull() or not result.Faces or result.Area<=g.EPS:
        if allow_empty: return None
        raise ValueError('Offset collapses the face.')
    return result


class Profile:
    def __init__(self, element, normal=None):
        self.source = element
        self.face = element.ShapeType == 'Face'
        self.is_cylinder = False
        if self.face and isinstance(getattr(element, 'Surface', None), Part.Cylinder):
            cyl = element.Surface
            self.is_cylinder = True
            self.cylinder_axis = g.unit(cyl.Axis)
            self.radius = cyl.Radius
            self.center = element.CenterOfMass
            circular_ends = [e for e in element.Edges if isinstance(getattr(e, 'Curve', None), Part.Circle)]
            if circular_ends:
                self.center = circular_ends[0].Curve.Center
            ref_normal = normal if normal is not None else self.cylinder_axis
            self.plane = g.Plane.from_normal(self.center, ref_normal)
        elif self.face:
            self.plane = g.Plane.from_face(element)
            self.boundary = Part.makeCompound(element.Edges)
        elif element.ShapeType == 'Edge' and isinstance(element.Curve, Part.Circle):
            curve = element.Curve
            plane_normal = normal if normal is not None else curve.Axis
            self.plane = g.Plane.from_normal(curve.Center, plane_normal)
        elif element.ShapeType == 'Edge' and isinstance(element.Curve, Part.Line):
            if normal is None:
                raise ValueError('Choose a drawing plane for this line offset.')
            if not all(math.isfinite(value) for value in (normal.x,normal.y,normal.z)):
                raise ValueError('The offset plane normal must be finite.')
            self.start = element.valueAt(element.FirstParameter)
            self.end = element.valueAt(element.LastParameter)
            self.direction = g.unit(self.end-self.start)
            self.plane = g.Plane.from_normal(self.start, normal)
            if abs(self.direction.dot(self.plane.normal)) > g.EPS:
                raise ValueError('The offset plane must contain the line. Choose another plane.')
            self.left = self.plane.normal.cross(self.direction)
        else:
            raise ValueError('Offset supports flat faces, straight edges and circular arcs or circles.')

    def distance_at(self, point):
        point = self.plane.project(point)
        if self.is_cylinder:
            return (point - self.center).Length - self.radius
        if self.face:
            distance = self.boundary.distToShape(Part.Vertex(point))[0]
            return -distance if self.source.isInside(point, g.EPS, True) else distance
        if isinstance(self.source.Curve, Part.Circle):
            return (point-self.source.Curve.Center).Length-self.source.Curve.Radius
        return (point-self.start).dot(self.left)

    def offset(self, distance):
        if isinstance(distance,bool) or not math.isfinite(distance) or abs(distance) < g.EPS:
            raise ValueError('Enter a nonzero offset distance.')
        if self.is_cylinder:
            radius = self.radius + distance
            if radius < g.EPS:
                raise ValueError('The inward offset reaches the arc center. Use a distance smaller than its radius.')
            result = Part.Circle(self.center, self.plane.normal, radius)
            edge = result.toShape()
            g.validate(edge)
            return edge
        if self.face:
            try:
                result = _filled_offset(Part.Face(self.source.OuterWire),distance)
                for wire in self.source.Wires:
                    if wire.isSame(self.source.OuterWire): continue
                    hole=_filled_offset(Part.Face(wire),-distance,allow_empty=distance>0)
                    if hole is not None: result=result.cut(hole)
                if result.isNull() or not result.Faces or result.Area<=g.EPS or not result.isValid():
                    raise ValueError()
                common = self.source.common(result).Area
                expected = self.source.Area if distance > 0 else result.Area
                if abs(common-expected) > max(1e-6, expected*1e-7):
                    raise ValueError()
                if abs(result.Area-self.source.Area) < g.EPS:
                    raise ValueError()
            except Exception as error:
                raise ValueError('This offset collapses or crosses the face boundary. Try a smaller distance.') from error
            return result
        if isinstance(self.source.Curve, Part.Line):
            result=self.source.copy(); result.translate(self.left*distance)
            return result
        curve = self.source.Curve
        radius = curve.Radius+distance
        if radius < g.EPS:
            raise ValueError('The inward offset reaches the arc center. Use a distance smaller than its radius.')
        result = Part.Circle(curve.Center, self.plane.normal if hasattr(self, 'plane') else curve.Axis, radius)
        # Preserve the circle basis, arc endpoints' angles and traversal.
        result.XAxis = curve.XAxis
        edge = result.toShape(self.source.FirstParameter, self.source.LastParameter)
        if self.source.Orientation == 'Reversed': edge.reverse()
        g.validate(edge)
        return edge


def partition_concentric_circle(original, circle_edge, face_plane):
    """Partition a solid or planar face with a concentric circle around a hole, creating an annular face."""
    is_solid = hasattr(original, 'Solids') and bool(original.Solids)
    faces = original.Faces if is_solid else ([original] if original.ShapeType == 'Face' else original.Faces)

    c = getattr(circle_edge, 'Curve', None)
    if not isinstance(c, Part.Circle):
        return None
    center_on_plane = face_plane.project(c.Center)
    radius = c.Radius

    target_face = None
    target_hole_wire = None
    for f in faces:
        if not isinstance(f.Surface, Part.Plane):
            continue
        if abs(abs(g.face_normal(f).dot(face_plane.normal)) - 1) > 1e-4:
            continue
        if abs((f.CenterOfMass - face_plane.origin).dot(face_plane.normal)) > 0.05:
            continue
        for w in f.Wires[1:]:
            for e in w.Edges:
                if isinstance(getattr(e, 'Curve', None), Part.Circle):
                    ec = e.Curve
                    e_center = face_plane.project(ec.Center)
                    if (e_center - center_on_plane).Length < 0.1 and ec.Radius < radius - 1e-4:
                        target_face = f
                        target_hole_wire = w
                        break
            if target_face:
                break
        if target_face:
            break

    if not target_face or not target_hole_wire:
        return None

    offset_circle = Part.makeCircle(radius, center_on_plane, face_plane.normal)
    offset_wire = Part.Wire([offset_circle])

    rem_f = Part.Face(target_face.OuterWire)
    for w in target_face.Wires[1:]:
        if w.isSame(target_hole_wire):
            rem_f.addWire(offset_wire)
        else:
            w_rev = w.copy()
            w_rev.reverse()
            rem_f.addWire(w_rev)

    ann_outer = offset_wire.copy()
    ann_outer.reverse()
    ann_shape = Part.Face(ann_outer).cut(Part.Face(target_hole_wire))
    if not ann_shape.Faces:
        return None
    ann_f = ann_shape.Faces[0]

    if rem_f.Orientation != target_face.Orientation:
        rem_f.reverse()
    if ann_f.Orientation != target_face.Orientation:
        ann_f.reverse()

    if is_solid:
        f_idx = next(i for i, face in enumerate(original.Faces) if face.isSame(target_face))
        other_faces = [face for i, face in enumerate(original.Faces) if i != f_idx]
        shell = Part.makeShell(other_faces + [rem_f, ann_f])
        res = Part.Solid(shell)
        if not res.isValid():
            res.fix(1e-6, 1e-6, 1e-6)
        if res.isValid() and abs(res.Volume - original.Volume) <= max(1e-4, min(0.5, original.Volume * 0.05), original.Volume * 1e-4):
            return res
        return None
    else:
        from .subdivision import replace_surface_face
        f_idx = next(i for i, face in enumerate(faces) if face.isSame(target_face))
        res, _ = replace_surface_face(original, f_idx, [rem_f, ann_f])
        return res


def partition(original, profile, plane):
    """Imprint offset boundaries on the owner's coplanar faces; return new outside area."""
    if not original.isValid():
        raise ValueError('The shape is invalid.')
    if len(original.Solids)>1 or (original.Solids and len(original.Faces)!=len(original.Solids[0].Faces)):
        raise ValueError('Separate compound solids or mixed solids/surfaces before offsetting a face.')

    if not bool(profile.Faces):
        circular_edges = [e for e in profile.Edges if isinstance(getattr(e, 'Curve', None), Part.Circle) and e.isClosed()]
        if circular_edges:
            concentric_res = partition_concentric_circle(original, circular_edges[0], plane)
            if concentric_res is not None and len(concentric_res.Faces) > len(original.Faces):
                return concentric_res, []

    coplanar=[]
    for face in original.Faces:
        if isinstance(face.Surface,Part.Plane) and abs(abs(g.face_normal(face).dot(plane.normal))-1)<1e-4 and abs((face.CenterOfMass-plane.origin).dot(plane.normal))<0.05:
            coplanar.append(face)
    result=original
    footprint=Part.makeCompound(coplanar) if coplanar else None
    tools=[]
    if footprint is not None:
        try:
            tools=[piece for edge in profile.Edges for piece in edge.common(footprint).Edges if piece.Length>g.EPS]
        except Exception:
            tools=[]
    if not tools and footprint is not None:
        tools=[edge for edge in profile.Edges if edge.Length>g.EPS]
    if original.Solids and tools:
        candidate_tool_sets = [tools]
        all_profile_edges = [edge for edge in profile.Edges if edge.Length > g.EPS]
        if all_profile_edges != tools:
            candidate_tool_sets.append(all_profile_edges)

        output = None
        for candidate_tools in candidate_tool_sets:
            for fuzzy in (0.0, 0.01, 0.02):
                try:
                    if fuzzy == 0.0:
                        output, _ = original.Solids[0].generalFuse(candidate_tools)
                    else:
                        output, _ = original.Solids[0].generalFuse(candidate_tools, fuzzy)
                except (RuntimeError, Part.OCCError, TypeError):
                    output = None
                if output is not None and len(output.Solids) == 1 and len(output.Solids[0].Faces) > len(original.Solids[0].Faces) and output.Solids[0].isValid():
                    break
            if output is not None and len(output.Solids) == 1 and len(output.Solids[0].Faces) > len(original.Solids[0].Faces) and output.Solids[0].isValid():
                break

        if output is None or len(output.Solids) != 1:
            raise ValueError('Offset could not preserve the solid.')
        result = output.Solids[0]
        if not result.isValid():
            raise ValueError('The offset result is invalid.')
        vol_tol = max(1e-4, min(0.5, original.Volume * 0.05), original.Volume * 1e-4)
        if abs(result.Volume - original.Volume) > vol_tol:
            raise ValueError('Offset must preserve the original solid volume.')
    elif not original.Solids:
        from .subdivision import replace_surface_face
        surface_tools = tools if len(tools) >= len(profile.Edges) else [edge for edge in profile.Edges if edge.Length > g.EPS]
        for face in coplanar if surface_tools else []:
            output = None
            try:
                output, _ = face.generalFuse(surface_tools)
            except (RuntimeError, Part.OCCError, TypeError):
                output = None
            if output is None or len(output.Faces) <= 1:
                fuzzy = 0.01 if len(face.Wires) > 1 or len(face.Edges) > 8 else 0.0
                if fuzzy > 0.0:
                    try:
                        output, _ = face.generalFuse(surface_tools, fuzzy)
                    except TypeError:
                        pass
            if output is None or len(output.Faces) <= 1: continue
            index = next(i for i, f in enumerate(result.Faces) if coinc.same(f, face))
            result, _ = replace_surface_face(result, index, output.Faces)
    # Extension excludes *all* existing coplanar regions, including neighboring
    # subdivisions, rather than laying a second face over their area.
    extra=[]
    if footprint is not None and bool(profile.Faces):
        try:
            extension=profile.cut(footprint)
            extra=[face for face in extension.Faces if face.Area>g.EPS]
            if extra:
                g.validate(Part.makeCompound(extra))
            if extra and not original.Solids and len(coplanar)==len(original.Faces):
                result=coinc.assemble(result.Faces+extra)
                extra=[]
        except Exception:
            extra=[]
    # Preserve loose lines and isolated vertices omitted by native face assembly.
    if not original.Solids:
        loose=[edge for edge in coinc.loose_edges(original) if not any(edge.isSame(e) for e in result.Edges)]
        boundary_v = {}
        for edge in original.Edges:
            for vertex in edge.Vertexes:
                boundary_v.setdefault(hash(vertex), []).append(vertex)
        result_v = {}
        for vertex in result.Vertexes:
            result_v.setdefault(hash(vertex), []).append(vertex)
        vertices=[v for v in original.Vertexes
                  if not any(v.isSame(w) for w in result_v.get(hash(v), ()))
                  and not any(v.isSame(w) for w in boundary_v.get(hash(v), ()))]
        if loose or vertices:
            result=Part.makeCompound([result]+loose+vertices)
    if not result.isValid():
        raise ValueError('The offset result is invalid.')
    return result,extra
