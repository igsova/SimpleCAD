"""Scale, ordered profile lofts and profile/path sweeps, without document writes."""
import math
import FreeCAD as App
import Part
from ..core import geometry as g, coincident
V=App.Vector


def factors(values):
    if len(values)!=3 or any(isinstance(v,bool) or not math.isfinite(v) or not 1e-4<=v<=10000 for v in values):
        raise ValueError('Enter three positive scale factors between 0.0001 and 10000. Use 1 to keep a dimension.')
    return tuple(values)


def scale_frames(shapes,axes='World',pivot='Selection'):
    if axes not in ('World','Local') or pivot not in ('Selection','Each','Origin'):
        raise ValueError('Choose World/Local axes and Selection/Each/Origin pivot.')
    combined=Part.makeCompound(shapes)
    center=combined.optimalBoundingBox(False).Center
    return [(V() if pivot=='Origin' else s.optimalBoundingBox(False).Center if pivot=='Each' else center,
             s.Placement.Rotation if axes=='Local' else App.Rotation()) for s in shapes]


def scale_matrix(frame,values):
    values=factors(values);center,rotation=frame
    diagonal=App.Matrix();diagonal.A11,diagonal.A22,diagonal.A33=values
    basis=rotation.toMatrix();matrix=basis.multiply(diagonal).multiply(rotation.inverted().toMatrix())
    offset=center-matrix.multVec(center)
    matrix.A14,matrix.A24,matrix.A34=offset
    return matrix


def scaled(shape,frame,values):
    # Work in the object's own coordinates and retain its orientation for later
    # Local-axis edits, including after nonuniform scaling baked into geometry.
    placement=shape.Placement
    local=shape.copy();local.Placement=App.Placement()
    local_frame=(placement.inverse().multVec(frame[0]),placement.Rotation.inverted().multiply(frame[1]))
    result,sources=_scaled(local,local_frame,values)
    result.Placement=placement.multiply(result.Placement)
    return result,sources


def _scaled(shape,frame,values):
    values=factors(values)
    if len(set(values))==1:
        result=shape.copy();result.scale(values[0],frame[0])
        return g.validate(result), list(range(len(shape.Faces)))
    matrix=scale_matrix(frame,values)
    # Transform once so all neighbouring faces retain shared edge topology.
    native=shape.transformGeometry(matrix)
    transformed=[]
    straight=all(not e.Degenerated and isinstance(e.Curve,Part.Line) for e in shape.Edges)
    planar={i for i,f in enumerate(shape.Faces) if isinstance(f.Surface,Part.Plane)}
    def face(f):
        index=next(i for i,n in enumerate(native.Faces) if n.isSame(f))
        if index in planar:
            wires=f.Wires
            if straight:
                wires=[Part.Wire([Part.makeLine(matrix.multVec(e.Vertexes[0].Point),matrix.multVec(e.Vertexes[-1].Point)) for e in w.OrderedEdges]) for w in shape.Faces[index].Wires]
            result=Part.Face(wires,'Part::FaceMakerBullseye')
            plane=g.Plane.from_face(shape.Faces[index]);origin=matrix.multVec(plane.origin)
            normal=(matrix.multVec(plane.origin+plane.u)-origin).cross(matrix.multVec(plane.origin+plane.v)-origin)
            if g.face_normal(result).dot(normal)<0:result.reverse()
        else:result=f
        transformed.append((shape.Faces[index],result));return result
    def shell(s):
        if not any(i in planar and any(f.isSame(n) for f in s.Faces) for i,n in enumerate(native.Faces)):
            for f in s.Faces:face(f)
            return s
        result=Part.makeShell([face(f) for f in s.Faces]);result.sewShape();return result
    def rebuild(s):
        if s.ShapeType=='Solid':
            shells=[shell(sh) for sh in s.Shells]
            if not all(sh.isClosed() for sh in shells):raise ValueError('Stretch could not preserve the closed solid.')
            result=Part.makeSolid(Part.makeCompound(shells))
            if result.Volume<0:result.reverse()
            return result
        if s.ShapeType=='Shell':return shell(s)
        if s.ShapeType=='Face':return face(s)
        if s.ShapeType=='Compound':return Part.makeCompound([rebuild(c) for c in s.childShapes()])
        if s.ShapeType=='Wire':return Part.Wire([rebuild(e) for e in s.OrderedEdges])
        if s.ShapeType=='Edge':
            index=next(i for i,e in enumerate(native.Edges) if e.isSame(s))
            original=shape.Edges[index]
            if not original.Degenerated and isinstance(original.Curve,Part.Line):
                return Part.makeLine(matrix.multVec(original.Vertexes[0].Point),matrix.multVec(original.Vertexes[-1].Point))
        return s
    if planar or not shape.Faces:
        result=g.validate(rebuild(native))
    else:
        result=g.validate(native)
        transformed=list(zip(shape.Faces,native.Faces))
    if len(result.Solids)!=len(shape.Solids) or len(result.Faces)!=len(shape.Faces):raise ValueError('Stretch could not preserve the shape topology.')
    sources=[]
    old=shape.Faces
    for current in result.Faces:
        pair=next(((a,b) for a,b in transformed if b.isSame(current)),None)
        if pair is None:pair=next(((a,b) for a,b in transformed if coincident.same(b,current)),None)
        if pair is None:raise ValueError('Stretch could not track the surface appearance.')
        sources.append(next(i for i,f in enumerate(old) if f.isSame(pair[0])))
    return result,sources


def wire(shape,closed=False):
    if shape.ShapeType=='Face':
        if len(shape.Wires)!=1:raise ValueError('Profiles with holes are not supported; select a single outline.')
        result=shape.OuterWire
    elif shape.ShapeType in ('Edge','Wire'):
        result=Part.Wire(shape.Edges)
    elif shape.ShapeType=='Compound' and not shape.Faces and shape.Edges:
        groups=Part.sortEdges(shape.Edges)
        if len(groups)!=1:raise ValueError('Select one connected, unbranched path or outline.')
        result=Part.Wire(groups[0])
    else:raise ValueError('Select a face, a wire, or connected edges; a whole solid is not a profile.')
    g.validate(result)
    if any(e.Degenerated for e in result.Edges):raise ValueError('The outline has a collapsed edge.')
    for vertex in result.Vertexes:
        degree=sum(sum(v.isSame(vertex) for v in e.Vertexes) + (1 if e.isClosed() and any(v.isSame(vertex) for v in e.Vertexes) else 0) for e in result.Edges)
        if degree>2:raise ValueError('Select one connected, unbranched path or outline.')
    if closed and not result.isClosed():raise ValueError('A solid needs closed profile outlines.')
    return result.copy()


def profile(shape,solid=True):
    result=wire(shape,solid)
    if result.isClosed():
        f=Part.Face(result);g.face_normal(f);g.validate(f)
    return result


def loft(shapes,solid=True,ruled=False):
    if not 2<=len(shapes)<=32:raise ValueError('Select 2 to 32 profiles in order.')
    profiles=[profile(s,solid) for s in shapes]
    if any(len(a.Edges)==len(b.Edges) and
           all(any(coincident.same(e,f) for f in b.Edges) for e in a.Edges)
           for a,b in zip(profiles,profiles[1:])):
        raise ValueError('Adjacent loft profiles must be different.')
    result=Part.makeLoft(profiles,solid,ruled,False)
    return validate_result(result,solid)


def sweep(section,path,solid=True,frenet=False,align=True,transition=0):
    if transition not in (0,1,2):raise ValueError('Choose transformed, right, or rounded path corners.')
    section=profile(section,solid);path=wire(path)
    groups=Part.sortEdges(path.Edges)
    if len(groups)!=1:raise ValueError('Select one connected sweep path.')
    path=Part.Wire(groups[0])
    if align:
        if not section.isClosed():raise ValueError('Automatic alignment needs a closed planar profile.')
        face=Part.Face(section);normal=g.face_normal(face)
        first=path.OrderedEdges[0]
        reverse=first.Orientation=='Reversed'
        parameter=first.LastParameter if reverse else first.FirstParameter
        start=first.valueAt(parameter);tangent=first.tangentAt(parameter)*(-1 if reverse else 1)
        center=face.CenterOfMass
        placement=App.Placement(start,App.Rotation(normal,tangent)).multiply(App.Placement(-center,App.Rotation()))
        section.Placement=placement.multiply(section.Placement)
    result=path.makePipeShell([section],solid,frenet,transition)
    return validate_result(result,solid)


def validate_result(result,solid):
    g.validate(result,solid=solid)
    if solid and not result.isClosed():raise ValueError('The result is not a closed solid. Adjust the profiles/path.')
    result.check(True)
    return result.Solids[0] if solid else result
