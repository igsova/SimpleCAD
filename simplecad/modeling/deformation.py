"""Bounded, conforming surface samples for soft movement and axial bending."""
import math
import FreeCAD as App
import Part
import Mesh
import MeshPart
from ..core import geometry as g
from . import rotation
V=App.Vector
MAX_FACES=4000


def vector(value):
    value=V(value)
    if not all(math.isfinite(x) and abs(x)<=1e7 for x in value):raise ValueError('Enter finite coordinates within the supported range.')
    return value


def smooth_weight(distance,radius):
    t=max(0.,min(1.,1-distance/radius))
    return t*t*t*(10+t*(-15+6*t))


class Region:
    def __init__(self,shape,detail=6):
        g.validate(shape)
        if isinstance(detail,bool) or not isinstance(detail,int) or not 3<=detail<=16:raise ValueError('Detail must be between 3 and 16.')
        if not shape.Faces or (shape.Solids and (len(shape.Solids)!=1 or len(shape.Shells)!=1 or len(shape.Faces)!=len(shape.Solids[0].Faces))):
            raise ValueError('Choose one solid without internal cavity shells, or an open surface.')
        if not shape.Solids and len(shape.Shells)>1:raise ValueError('Choose one connected surface.')
        face_edges={hash(e) for f in shape.Faces for e in f.Edges}
        if any(hash(e) not in face_edges for e in shape.Edges):raise ValueError('Separate loose lines from the surface before deforming.')
        self.shape=shape;self.detail=detail
        self.size=shape.optimalBoundingBox(False).DiagonalLength;self.step=self.size/detail
        if self.size<g.EPS:raise ValueError('The selected shape is too small.')
        mesh=MeshPart.meshFromShape(Shape=shape,LinearDeflection=self.size/(detail*12),AngularDeflection=.5,Relative=False,Segments=True)
        self.points,self.triangles=mesh.Topology
        self.points=[V(p) for p in self.points];self.triangles=[tuple(t) for t in self.triangles]
        if mesh.countSegments()!=len(shape.Faces):raise ValueError('Cannot track source faces for this surface.')
        self.origins=[None]*len(self.triangles)
        for i in range(mesh.countSegments()):
            for t in mesh.getSegment(i):self.origins[t]=i
        if any(i is None for i in self.origins):raise ValueError('Cannot track every surface region.')
        if len(self.triangles)>MAX_FACES:raise ValueError('This shape is too detailed. Reduce detail or deform a simpler object.')
        for _ in range(12):
            edges={tuple(sorted((t[i],t[(i+1)%3]))) for t in self.triangles for i in range(3)}
            split={e for e in edges if (self.points[e[0]]-self.points[e[1]]).Length>self.step*1.001}
            if not split:break
            mids={e:len(self.points)+i for i,e in enumerate(sorted(split))}
            self.points.extend([(self.points[a]+self.points[b])*.5 for a,b in sorted(split)])
            triangles=[];origins=[]
            for tri,source in zip(self.triangles,self.origins):
                flags=[tuple(sorted((tri[i],tri[(i+1)%3]))) in split for i in range(3)];n=sum(flags)
                if n==0:parts=[tri]
                else:
                    first=next((i for i in range(3) if flags[i] and (n!=2 or flags[(i+1)%3])),0)
                    a,b,c=[tri[(first+i)%3] for i in range(3)]
                    ab=mids.get(tuple(sorted((a,b))));bc=mids.get(tuple(sorted((b,c))));ca=mids.get(tuple(sorted((c,a))))
                    if n==1:parts=[(a,ab,c),(ab,b,c)]
                    elif n==2:parts=[(b,bc,ab),(a,ab,c),(ab,bc,c)]
                    else:parts=[(a,ab,ca),(ab,b,bc),(ca,bc,c),(ab,bc,ca)]
                triangles.extend(parts);origins.extend([source]*len(parts))
            if len(triangles)>MAX_FACES:raise ValueError('This detail exceeds 4000 surface faces. Reduce Detail.')
            self.triangles,self.origins=triangles,origins
        self.edges=sorted({tuple(sorted((t[i],t[(i+1)%3]))) for t in self.triangles for i in range(3)})

    def move(self,center,radius,delta):
        center,delta=vector(center),vector(delta)
        if not math.isfinite(radius) or radius<=g.EPS:raise ValueError('Influence radius must be positive.')
        weights=[smooth_weight((p-center).Length,radius) for p in self.points]
        if max(weights)<1e-10:raise ValueError('The influence radius does not reach the surface. Increase it or move the center.')
        return [p+delta*w for p,w in zip(self.points,weights)],weights

    def bend(self,origin,axis,toward,length,angle):
        origin=vector(origin);axis=g.unit(vector(axis));toward=vector(toward)
        toward=g.unit(toward-axis*toward.dot(axis))
        if not math.isfinite(length) or length<=g.EPS:raise ValueError('Bend length must be positive.')
        if not math.isfinite(angle) or abs(angle)>170:raise ValueError('Choose a bend angle between -170° and 170°.')
        side=axis.cross(toward);k=math.radians(angle)/length
        result=[];weights=[]
        for p in self.points:
            d=p-origin;s=d.dot(axis);t=d.dot(toward);b=d.dot(side)
            u=max(0,min(length,s));weights.append(u/length)
            if s<=0 or abs(k)<1e-12:result.append(V(p));continue
            if 1-k*t<=.05:raise ValueError('This bend compresses the inside too far. Reduce the angle or increase bend length.')
            theta=k*u;sn,cs=math.sin(theta),math.cos(theta)
            line=axis*(sn/k)+toward*((1-cs)/k)
            result.append(origin+line+(toward*cs-axis*sn)*t+side*b+(axis*cs+toward*sn)*max(0,s-length))
        if max(weights)<1e-10:raise ValueError('The object lies before the bend origin. Move the origin or reverse the axis.')
        return result,weights

    def build(self,points):
        if len(points)!=len(self.points):raise ValueError('The deformation preview is stale.')
        if max((a-b).Length for a,b in zip(points,self.points))<g.EPS:return self.shape,list(range(len(self.shape.Faces)))
        facets=[]
        for tri in self.triangles:
            a,b,c=[points[i] for i in tri]
            if (b-a).cross(c-a).Length<g.EPS*g.EPS:raise ValueError('The deformation collapses a face. Reduce its strength.')
            facets.append((a,b,c))
        mesh=Mesh.Mesh(facets)
        if mesh.hasSelfIntersections():raise ValueError('The deformation intersects itself. Reduce its strength or increase the affected distance.')
        if self.shape.Solids and not mesh.isSolid():raise ValueError('The deformation would open the solid.')
        inverse=self.shape.Placement.inverse()
        local=[tuple(inverse.multVec(p) for p in tri) for tri in facets]
        faces=[Part.Face(Part.makePolygon([a,b,c,a])) for a,b,c in local]
        shell=Part.makeShell(faces);shell.sewShape()
        if self.shape.Solids:
            if not shell.isClosed():raise ValueError('The deformation could not keep a closed solid.')
            result=Part.makeSolid(shell)
            if result.Volume<0:result.reverse()
            g.validate(result,solid=True)
        else:result=g.validate(shell)
        by_hash={}
        for face,source in zip(faces,self.origins):by_hash.setdefault(hash(face),[]).append((face,source))
        sources=[]
        centers={tuple(round(x,7) for x in f.CenterOfMass):i for f,i in zip(faces,self.origins)}
        for face in result.Faces:
            source=next((i for old,i in by_hash.get(hash(face),[]) if face.isSame(old)),None)
            if source is None:source=centers.get(tuple(round(x,7) for x in face.CenterOfMass))
            if source is None:raise ValueError('Cannot safely preserve face appearance for this result.')
            sources.append(source)
        if len(sources)!=len(faces):raise ValueError('The deformation changed surface connectivity.')
        result.Placement=self.shape.Placement.multiply(result.Placement)
        return result,sources


def default_center(shape,names):
    if names:return Part.makeCompound([shape.getElement(n) for n in names]).optimalBoundingBox(False).Center
    return shape.optimalBoundingBox(False).Center


def bend_frame(shape,axis='Main'):
    direction=rotation.direction(shape,axis);plane=g.Plane.from_normal(V(),direction)
    align=App.Rotation(direction,V(0,0,1))
    local=shape.copy();local.Placement=App.Placement(V(),align).multiply(shape.Placement)
    bb=local.optimalBoundingBox(False)
    origin=align.inverted().multVec(V(bb.Center.x,bb.Center.y,bb.ZMin))
    return origin,direction,plane.u,bb.ZLength
