"""Matching V-shaped cut surfaces; preserve the mesh away from the seam."""
import struct
import numpy as np
import FreeCAD as App
import Mesh
from .slicing import finite, edge_counts, cap_boundary

V = App.Vector
MAX_CAP_TRIANGLES = 120000


def options(value):
    if value is None: return None
    if not isinstance(value, dict) or set(value) - {'depth', 'clearance', 'flip'}:
        raise ValueError('Glue seam settings must contain depth, clearance and/or flip.')
    depth = finite(value.get('depth', 2), 'Maximum groove depth', .05, 20)
    clearance = finite(value.get('clearance', .15), 'Glue clearance', 0, depth/2)
    flip = value.get('flip', False)
    if not isinstance(flip, bool): raise ValueError('Flip glue seam must be true or false.')
    return {'depth': depth, 'clearance': clearance, 'flip': flip}


def penetrates(first, second, tolerance):
    """Confirm native float32 collision candidates with double plane tests.

    Near-horizontal original STL slivers otherwise appear to intersect a cap
    along its boundary even though they lie strictly below the cutting plane.
    """
    a,b = [[V(*p) for p in face.Points] for face in (first,second)]
    na=(a[1]-a[0]).cross(a[2]-a[0]);nb=(b[1]-b[0]).cross(b[2]-b[0])
    if min(na.Length,nb.Length)<1e-16: return True
    na.normalize();nb.normalize()
    da=[(p-b[0]).dot(nb) for p in a];db=[(p-a[0]).dot(na) for p in b]
    if max(map(abs,da))<=tolerance and max(map(abs,db))<=tolerance:
        # Coplanar overlap of positive area is a real breakthrough (for
        # example a groove exactly reaching the opposite skin of a thin lid).
        drop=max(range(3),key=lambda i:abs(tuple(na)[i]))
        polygon=[tuple(v for i,v in enumerate(p) if i!=drop) for p in a]
        clip=[tuple(v for i,v in enumerate(p) if i!=drop) for p in b]
        def cross(a,b,p):return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])
        if cross(*clip)<0:clip.reverse()
        for start,end in zip(clip,clip[1:]+clip[:1]):
            output=[]
            for p,q in zip(polygon,polygon[1:]+polygon[:1]):
                dp,dq=cross(start,end,p),cross(start,end,q)
                if dp>=0:output.append(p)
                if (dp>=0)!=(dq>=0):
                    t=dp/(dp-dq);output.append((p[0]+t*(q[0]-p[0]),p[1]+t*(q[1]-p[1])))
            polygon=output
        area=abs(sum(p[0]*q[1]-p[1]*q[0] for p,q in zip(polygon,polygon[1:]+polygon[:1])))/2
        return area>tolerance*tolerance*10
    return min(da)<-tolerance and max(da)>tolerance and min(db)<-tolerance and max(db)>tolerance


def clean_precision(points, tagged, tolerance, xyz):
    """Remove zero-area facets and opposite pairs of collapsed seam flaps."""
    if not tagged:return [],{}
    triangles=xyz[np.asarray([f for f,_ in tagged])]
    normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    groups={}
    for (face,is_body),nonzero in zip(tagged,np.any(normals,axis=1)):
        if not nonzero:continue
        a,b,c=face;forward=min((a,b,c),(b,c,a),(c,a,b));backward=min((c,b,a),(b,a,c),(a,c,b))
        key=tuple(sorted(face));direction=1 if forward<backward else -1
        entry=groups.setdefault(key,[0,{}]);entry[0]+=direction;entry[1][direction]=(face,is_body)
    tagged = [entry[1][1 if entry[0]>0 else -1] for entry in groups.values() if entry[0]]
    counts = edge_counts([face for face,_ in tagged])
    if not any(count>2 for count in counts.values()):return tagged,counts
    cleaned = []
    for face,is_body in tagged:
        edges = [tuple(sorted((a,b))) for a,b in zip(face,face[1:]+face[:1])]
        # A near-collinear seam flap can survive float32 rounding while its
        # two short edges are already shared by the skin and cap. Remove only
        # this sub-resolution, non-manifold remnant before the native builder
        # can discard its legitimate neighbors as well.
        if any(counts[e]>2 for e in edges):
            a,b,c = (points[i] for i in face)
            length = max((b-a).Length,(c-a).Length,(c-b).Length)
            if length and (b-a).cross(c-a).Length/length<=tolerance:
                for edge in edges:counts[edge]-=1
                continue
        cleaned.append((face,is_body))
    return cleaned,counts


def stitch_precision(points, faces, body_count, tolerance):
    """Resolve edge chains left when zero-width seam slivers collapse in STL.

    This only subdivides existing edges at coincident boundary vertices; it
    cannot fill a real hole or change an unrelated part of the source skin.
    """
    tagged = [(face,i<body_count) for i,face in enumerate(faces)]
    xyz=np.asarray([tuple(p) for p in points],dtype=np.float32)
    for _ in range(64):
        tagged,counts=clean_precision(points,tagged,tolerance,xyz)
        boundary = {e for e,count in counts.items() if count==1}
        if not boundary:break
        indices = sorted({i for edge in boundary for i in edge})
        coords = np.asarray([tuple(points[i]) for i in indices])
        # Adjacent samples can round to neighboring float32 values rather than
        # exactly the same value. Weld only the newly exposed precision cracks,
        # preferring the earlier (original skin) point, never the whole mesh.
        parent={i:i for i in indices}
        def root(i):
            while parent[i]!=i:i=parent[i]
            return i
        for j,i in enumerate(indices):
            near=np.flatnonzero(((coords[j+1:]-coords[j])**2).sum(axis=1)<=tolerance*tolerance)
            for k in near:
                other=indices[j+1+int(k)];a,b=root(i),root(other)
                parent[max(a,b)]=min(a,b)
        remap={i:root(i) for i in indices}
        if any(i!=j for i,j in remap.items()):
            welded=[]
            for face,is_body in tagged:
                a,b,c=(remap.get(i,i) for i in face)
                if len({a,b,c})==3 and (points[b]-points[a]).cross(points[c]-points[a]).Length>1e-15:
                    welded.append(((a,b,c),is_body))
            tagged=welded
            continue
        chains = {}
        for a,b in boundary:
            start=np.asarray(tuple(points[a]));direction=np.asarray(tuple(points[b]-points[a]));length2=float(direction@direction)
            if length2<=tolerance*tolerance:continue
            t=((coords-start)@direction)/length2
            distance2=((coords-start-t[:,None]*direction)**2).sum(axis=1)
            matches=[(t[j],i) for j,i in enumerate(indices) if i not in (a,b) and 1e-8<t[j]<1-1e-8 and distance2[j]<=tolerance*tolerance]
            if matches:chains[(a,b)] = [a]+[i for _,i in sorted(matches)]+[b]
        if not chains:break
        refined=[]
        for face,is_body in tagged:
            chain=None;k=0
            for candidate_k,(a,b) in enumerate(zip(face,face[1:]+face[:1])):
                candidate=chains.get((a,b) if a<b else (b,a))
                if candidate and (chain is None or len(candidate)>len(chain)):
                    chain,k=candidate,candidate_k
            if not chain:refined.append((face,is_body));continue
            a,b,c=face[k:]+face[:k]
            chain=chain if chain[0]==a else list(reversed(chain))
            for p,q in zip(chain,chain[1:]):
                if (points[q]-points[p]).cross(points[c]-points[p]).Length>1e-15:
                    refined.append(((p,q,c),is_body))
        tagged=refined
    tagged,_=clean_precision(points,tagged,tolerance,xyz)
    body=[face for face,is_body in tagged if is_body]
    return body+[face for face,is_body in tagged if not is_body],len(body)


class Roof:
    """45-degree roof from the cut boundary, capped at a maximum depth.

    Adaptive conforming subdivision follows the distance-field ridge. Boundary
    splits are propagated into the adjacent clipped triangles, never welded by
    proximity. Clearance is measured along the chosen split axis.
    """
    def __init__(self, points, caps, origin, normal, depth, clearance):
        self.points = points
        self.caps = caps
        self.normal, self.origin = normal, origin
        self.depth, self.clearance = depth, clearance
        self.boundary = {e for e, count in edge_counts(caps).items() if count == 1}
        if not self.boundary: raise ValueError('This cut has no shared boundary for a glue seam.')
        self.boundary_ids = {i for edge in self.boundary for i in edge}
        self.rotation = App.Rotation(normal, V(0,0,1))
        ends = np.asarray([[tuple(self.rotation.multVec(points[i]-origin))[:2] for i in edge] for edge in self.boundary])
        self.a = ends[:,0]; self.d = ends[:,1]-self.a
        self.length2 = (self.d*self.d).sum(axis=1)
        if np.any(self.length2 <= 1e-20): raise ValueError('The cut has a collapsed boundary edge. Move the plane slightly.')
        self.heights = {i: 0.0 for i in self.boundary_ids}
        self.midpoints, self.splits, self.center_heights = {}, {}, {}
        self.error = min(.025, depth/16)

    def height(self, points):
        xy = np.asarray([tuple(self.rotation.multVec(p-self.origin))[:2] for p in points])
        answer = []
        # Bound temporary arrays even for highly tessellated contours.
        chunk = max(1, min(128, 250000//len(self.a)))
        for start in range(0,len(xy),chunk):
            d = xy[start:start+chunk,None,:]-self.a[None,:,:]
            t = np.clip((d*self.d).sum(axis=2)/self.length2, 0, 1)
            distance2 = ((d-t[:,:,None]*self.d)**2).sum(axis=2)
            answer.extend(np.minimum(self.depth,np.sqrt(distance2.min(axis=1))))
        return answer

    def values(self, indices):
        missing = list(set(indices)-self.heights.keys())
        self.heights.update(zip(missing,self.height([self.points[i] for i in missing])))
        return np.asarray([self.heights[i] for i in indices])

    def midpoint(self, a, b):
        key = tuple(sorted((a,b)))
        if key not in self.midpoints:
            self.midpoints[key] = len(self.points)
            self.points.append((self.points[a]+self.points[b])*.5)
        return self.midpoints[key]

    def refine(self, progress):
        caps = self.caps
        for step in range(64):
            progress('Shaping the triangular glue seam')
            edges = list(edge_counts(caps))
            mids = [self.midpoint(*edge) for edge in edges]
            heights = self.values([i for face in caps for i in face]).reshape((-1,3))
            mid_heights = self.values(mids)
            marked = set()
            for clearance in (0,self.clearance):
                edge_heights = np.maximum(0,self.values([i for edge in edges for i in edge]).reshape((-1,2))-clearance)
                errors = np.abs(np.maximum(0,mid_heights-clearance)-edge_heights.mean(axis=1))
                marked.update(edge for edge,error in zip(edges,errors) if error>self.error)
            missing = [face for face in caps if face not in self.center_heights]
            centers = [(self.points[a]+self.points[b]+self.points[c])/3 for a,b,c in missing]
            self.center_heights.update(zip(missing,self.height(centers)))
            center_h = np.asarray([self.center_heights[face] for face in caps])
            errors = np.maximum(np.abs(center_h-heights.mean(axis=1)),
                                np.abs(np.maximum(0,center_h-self.clearance)-np.maximum(0,heights-self.clearance).mean(axis=1)))
            for face,error in zip(caps,errors):
                if error > self.error:
                    marked.update(tuple(sorted((a,b))) for a,b in zip(face,face[1:]+face[:1]))
            # Refine all sides of a triangle with a profile error. Splitting
            # just its failing edge can repeatedly recreate a skinny diagonal
            # with the same error instead of reducing the triangle's extent.
            failing = set(marked)
            for face in caps:
                face_edges = [tuple(sorted((a,b))) for a,b in zip(face,face[1:]+face[:1])]
                if any(edge in failing for edge in face_edges): marked.update(face_edges)
            marked = {edge for edge in marked if (self.points[edge[1]]-self.points[edge[0]]).Length>self.error}
            if not marked:
                self.caps = caps
                return
            self.splits.update({edge:self.midpoints[edge] for edge in marked})
            refined = []
            for face in caps:
                flags = [tuple(sorted((a,b))) in marked for a,b in zip(face,face[1:]+face[:1])]
                count = sum(flags)
                if count == 0: refined.append(face); continue
                if count == 3:
                    a,b,c = face; ab,bc,ca = (self.midpoint(a,b),self.midpoint(b,c),self.midpoint(c,a))
                    refined.extend(((a,ab,ca),(ab,b,bc),(ca,bc,c),(ab,bc,ca)))
                elif count == 1:
                    k=flags.index(True);a,b,c=face[k:]+face[:k];m=self.midpoint(a,b)
                    refined.extend(((a,m,c),(m,b,c)))
                else:
                    k=flags.index(False);a,b,c=face[k:]+face[:k];m,n=self.midpoint(b,c),self.midpoint(c,a)
                    # Choose the shorter diagonal in the remaining quad. A
                    # fixed diagonal can keep reproducing long STL slivers.
                    if (self.points[a]-self.points[m]).Length < (self.points[b]-self.points[n]).Length:
                        refined.extend(((c,n,m),(a,b,m),(a,m,n)))
                    else:
                        refined.extend(((c,n,m),(n,a,b),(n,b,m)))
            if len(refined)>MAX_CAP_TRIANGLES:
                raise ValueError('This glue seam needs too many triangles. Try a smaller depth or another cut position.')
            caps = refined
        raise ValueError('This cut is too detailed for a stable glue seam. Move the plane slightly.')

    def chain(self, a, b):
        mid = self.splits.get(tuple(sorted((a,b))))
        return [a] if mid is None else self.chain(a,mid)+self.chain(mid,b)

    def stitch(self, faces):
        result = []
        for face in faces:
            polygon = []
            for a,b in zip(face,face[1:]+face[:1]):
                polygon.extend(self.chain(a,b) if tuple(sorted((a,b))) in self.boundary else [a])
            if len(polygon)==3: result.append(face); continue
            # The new points lie on the cut. Split just the adjoining clipped
            # triangle so the roof and original skin use identical edge chains.
            center = len(self.points)
            self.points.append(sum((self.points[i] for i in face),V())/3)
            result.extend((a,b,center) for a,b in zip(polygon,polygon[1:]+polygon[:1]))
        return result


def build(points, sides, origin, normal, epsilon, settings, progress):
    caps = [cap_boundary(points,faces,origin,normal*-side,epsilon) for side,faces in zip((-1,1),sides)]
    boundaries = [{e for e,c in edge_counts(cap).items() if c==1} for cap in caps]
    if not caps[0] or boundaries[0] != boundaries[1]:
        raise ValueError('The glue seam needs the same cut outline on both sides. Move the plane slightly.')
    roof = Roof(points,caps[0],origin,normal,settings['depth'],settings['clearance'])
    roof.refine(progress)
    caps = roof.caps
    used_cap = {i for face in caps for i in face}
    female = {i:roof.heights.get(i,0) for i in used_cap}
    male = {i:max(0,h-settings['clearance']) for i,h in female.items()}
    if max(male.values(),default=0) <= .025:
        raise ValueError('The wall is too thin for this glue clearance. Reduce clearance or choose a thicker cut.')
    sign = -1 if settings['flip'] else 1
    male_side = 1 if settings['flip'] else -1
    results = []
    # The output coordinates are float32. Contacts within two representable
    # steps are numerically indistinguishable from their shared cut boundary.
    collision_tolerance = max(epsilon,max(abs(v) for point in points for v in point)*2**-22)
    progress('Checking ridge and groove against the mesh walls')
    for side, body in zip((-1,1),sides):
        body = roof.stitch(body)
        cap = caps if side == -1 else [(c,b,a) for a,b,c in caps]
        heights = male if side==male_side else female
        local = [point+normal*(sign*heights.get(i,0)) for i,point in enumerate(points)]
        used = sorted({i for face in body+cap for i in face})
        positions, stored, remap = {}, [], {}
        for i in used:
            key = struct.pack('<fff',*local[i])
            if key not in positions:
                positions[key] = len(stored); stored.append(V(*struct.unpack('<fff',key)))
            remap[i] = positions[key]
        # BMS can retain duplicate point identities that STL cannot represent.
        # Collapse only zero-area seam remnants at the stored precision before
        # building topology, so an STL round-trip keeps the same closed mesh.
        faces = []; body_count = 0
        for group in (body,cap):
            for face in group:
                a,b,c = (remap[i] for i in face)
                if len({a,b,c})<3 or (stored[b]-stored[a]).cross(stored[c]-stored[a]).Length<=1e-15: continue
                faces.append((a,b,c))
            if group is body: body_count = len(faces)
        faces,body_count = stitch_precision(stored,faces,body_count,collision_tolerance)
        result = Mesh.Mesh((stored,faces))
        if result.hasNonUniformOrientedFacets():
            # Stitching nearly collinear samples can invert a microscopic
            # flap. Accept winding correction only on sub-resolution facets;
            # never reorient a meaningful surface inherited from the source.
            before_points,before_faces = result.Topology
            result.harmonizeNormals()
            for old,new in zip(before_faces,result.Topology[1]):
                if old==new:continue
                a,b,c = (before_points[i] for i in old)
                length = max((b-a).Length,(c-a).Length,(c-b).Length)
                if length and (b-a).cross(c-a).Length/length>collision_tolerance:
                    raise ValueError('The glue seam could not preserve surface directions. Move the cut slightly.')
        if result.CountFacets!=len(faces) or not result.isSolid() or result.hasNonManifolds() or result.hasNonUniformOrientedFacets():
            raise ValueError('The glue seam could not remain closed. Reduce its depth or move the cut.')
        # Existing source intersections are left alone. Only intersections that
        # involve a newly shaped cap are failures of this operation.
        facets = result.Facets
        for a,b,p,q in result.getSelfIntersections():
            if min(a,b)<body_count<=max(a,b) and (q-p).Length>collision_tolerance*4 and penetrates(facets[a],facets[b],collision_tolerance):
                raise ValueError('The groove breaks through a mesh wall. Reduce depth, flip sides, or move the cut.')
        results.append(result)
    removed = 0.0
    for a,b,c in caps:
        area = (points[b]-points[a]).cross(points[c]-points[a]).Length/2
        removed += area*sum(female[i]-male[i] for i in (a,b,c))/3
    return results, {'depth':settings['depth'], 'clearance':settings['clearance'], 'flip':settings['flip'],
                     'max_ridge_height':max(male.values()), 'removed_volume':removed,
                     'profile_tolerance':roof.error}
