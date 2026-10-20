"""Cached polygon neighborhoods for vertex deformation; no preview writes."""
import math
import re
import FreeCAD as App
import Part
from ..core import geometry as g, coincident
V=App.Vector


def same(a,b): return (a-b).Length <= g.EPS


class Neighborhood:
    def __init__(self, shape, name):
        match=re.fullmatch(r'Vertex([1-9][0-9]*)',name)
        if not match or int(match[1])>len(shape.Vertexes):
            raise ValueError('Choose one vertex of the object.')
        g.validate(shape)
        if shape.Solids and (len(shape.Solids)!=1 or len(shape.Shells)!=1
                             or len(shape.Faces)!=len(shape.Solids[0].Faces)
                             or len(shape.Edges)!=len(shape.Solids[0].Edges)
                             or len(shape.Vertexes)!=len(shape.Solids[0].Vertexes)):
            raise ValueError('Move Vertex needs one solid without separate cavity shells, or open faces/lines.')
        self.shape=shape
        self.point=V(shape.Vertexes[int(match[1])-1].Point)
        self.faces={}
        self.lines=[]
        for edge in shape.Edges:
            if not any(same(v.Point,self.point) for v in edge.Vertexes): continue
            if edge.Degenerated:
                raise ValueError('Move Vertex supports straight edges and flat faces; curved vertices cannot be moved yet.')
            if len(edge.Vertexes)!=2 or not isinstance(edge.Curve,Part.Line):
                raise ValueError('Move Vertex supports straight edges and flat faces; curved vertices cannot be moved yet.')
        for index,face in enumerate(shape.Faces):
            if not any(same(v.Point,self.point) for v in face.Vertexes): continue
            normal=g.face_normal(face)
            if any(e.Degenerated or not isinstance(e.Curve,Part.Line) for e in face.Edges):
                raise ValueError('The touching faces must have straight boundaries for Move Vertex.')
            loops=[[V(v.Point) for v in wire.OrderedVertexes] for wire in face.Wires]
            points,triangles=face.tessellate(.1)
            triangles=[[V(points[i]) for i in tri] for tri in triangles]
            for tri in triangles:
                if (tri[1]-tri[0]).cross(tri[2]-tri[0]).dot(normal)<0: tri.reverse()
            if not triangles or not any(same(p,self.point) for tri in triangles for p in tri):
                raise ValueError('This face could not be triangulated at the selected vertex.')
            self.faces[index]=(loops,triangles,normal)
        for edge in shape.Edges:
            if not any(same(v.Point,self.point) for v in edge.Vertexes): continue
            self.lines.append([V(v.Point) for v in edge.Vertexes])
        if not self.lines: raise ValueError('Choose a vertex connected to an edge or face.')

    def shifted(self, point, delta):
        return point+delta if same(point,self.point) else point

    def preview(self, delta):
        # Only the captured neighborhood; no sewing, booleans or tessellation
        # while the pointer moves. Includes the possible triangulation folds.
        lines=[]
        for loops,triangles,_ in self.faces.values():
            for tri in triangles:
                moved=[self.shifted(p,delta) for p in tri]
                lines.append(moved+moved[:1])
        lines.extend([[self.shifted(p,delta) for p in line] for line in self.lines])
        return lines

    def build(self, delta):
        delta=V(delta)
        if not all(math.isfinite(x) for x in (delta.x,delta.y,delta.z)) or delta.Length<g.EPS:
            raise ValueError('Enter a finite, non-zero displacement.')
        destination=self.point+delta
        if any(not same(v.Point,self.point) and same(v.Point,destination) for v in self.shape.Vertexes):
            raise ValueError('That move collapses vertices. Choose a different destination.')
        faces=[];sources=[]
        for index,face in enumerate(self.shape.Faces):
            if index not in self.faces:
                faces.append(face);sources.append(index);continue
            loops,triangles,normal=self.faces[index]
            moved=[[self.shifted(p,delta) for p in loop] for loop in loops]
            all_points=[p for loop in moved for p in loop]
            new_triangles=[]
            for tri in triangles:
                pts=[self.shifted(p,delta) for p in tri]
                cross=(pts[1]-pts[0]).cross(pts[2]-pts[0])
                if cross.Length<g.EPS or cross.dot(normal)<=g.EPS:
                    raise ValueError('That move folds or collapses a face. Choose a smaller displacement.')
                new_triangles.append(pts)
            n=g.unit((new_triangles[0][1]-new_triangles[0][0]).cross(new_triangles[0][2]-new_triangles[0][0]))
            if all(abs((p-all_points[0]).dot(n))<g.EPS for p in all_points):
                wires=[Part.makePolygon(loop+loop[:1]) for loop in moved]
                replacements=[Part.Face(wires,'Part::FaceMakerBullseye')]
                if g.face_normal(replacements[0]).dot(n)<0: replacements[0].reverse()
            else:
                replacements=[Part.Face(Part.makePolygon(tri+tri[:1])) for tri in new_triangles]
            for replacement in replacements:g.validate(replacement)
            faces.extend(replacements);sources.extend([index]*len(replacements))
        loose=[]
        face_edges=[edge for face in self.shape.Faces for edge in face.Edges]
        for edge in self.shape.Edges:
            if any(edge.isSame(e) for e in face_edges):continue
            if any(same(v.Point,self.point) for v in edge.Vertexes):
                a,b=[self.shifted(v.Point,delta) for v in edge.Vertexes]
                loose.append(g.line(a,b))
            else:loose.append(edge)
        if self.shape.Solids:
            shell=Part.makeShell(faces);shell.sewShape()
            if not shell.isClosed(): raise ValueError('That move would open the solid. No changes were kept.')
            result=Part.makeSolid(shell)
            if result.Volume<0:result.reverse()
            g.validate(result,solid=True)
        else:
            result=Part.Wire(loose) if self.shape.ShapeType=='Wire' else coincident.assemble(faces,loose)
            g.validate(result)
        # BOP analysis detects self-intersections as well as basic validity.
        try:
            result.check(True)
        except Exception as error:
            raise ValueError('That move creates intersecting or invalid geometry. Choose a different displacement.') from error
        if len(result.Faces)!=len(faces):
            raise ValueError('The move could not preserve the face regions.')
        origins=[]
        for current in result.Faces:
            matches=[i for i,face in enumerate(faces) if current.isSame(face)]
            if not matches: matches=[i for i,face in enumerate(faces) if coincident.same(current,face)]
            if not matches: raise ValueError('The moved face could not be tracked safely.')
            origins.append(sources[matches[0]])
        return result,origins
