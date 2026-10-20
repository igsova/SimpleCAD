"""A cached polyhedral development for interactive drawing over a native skin.

Only the coordinate map uses a triangulation. Saved curves are rebuilt in the
original faces' UV coordinates and pass the ordinary strict CAD split checks.
The map follows connected geometry, transports directions over shared edges,
and stops at openings instead of bridging empty space.
"""
import functools
import math
import threading

import FreeCAD as App
import numpy as np
import Part

from ..core import geometry as geo
from .drawing import SurfaceFrame
from .line import snap_point, same_surface, covered, on_surface

V = App.Vector
DEFLECTION = .02
CURVE_TOLERANCE = .001


_solver_loading = None


def warm_solver():
    """Load SciPy's solver off the GUI thread before the first surface hover.

    Its first import reads hundreds of modules and took seconds during a
    hover. A hover that arrives earlier waits for this import, as before.
    """
    global _solver_loading
    if _solver_loading is None:
        def load():
            try:
                import scipy.optimize  # noqa: F401
                import scipy.sparse.csgraph  # noqa: F401
            except Exception:
                pass  # The hover's own import reports a missing SciPy.
        _solver_loading = threading.Thread(target=load, name='SimpleCAD solver import', daemon=True)
        _solver_loading.start()


def neighbors(triangles):
    """For each triangle side (opposite each corner), the triangle across it.

    Only a side shared by exactly two triangles has a neighbour (-1 otherwise).
    """
    count = len(triangles)
    result = np.full((count,3),-1,dtype=np.int64)
    if not count:
        return result
    first = triangles[:,[1,2,0]].ravel()
    second = triangles[:,[2,0,1]].ravel()
    low,high = np.minimum(first,second),np.maximum(first,second)
    order = np.lexsort((high,low))
    low,high = low[order],high[order]
    start = np.ones(len(order),dtype=bool)
    start[1:] = (low[1:]!=low[:-1])|(high[1:]!=high[:-1])
    group = np.cumsum(start)-1
    pairs = np.flatnonzero(start & (np.bincount(group)[group]==2))
    i,j = order[pairs],order[pairs+1]
    result[i//3,i%3] = j//3
    result[j//3,j%3] = i//3
    return result


_last_mesh = None


def wrap_mesh(skin, faces=None):
    """The drawing triangulation of a skin, reused while its faces are unchanged.

    Line rebuilds its frame after every segment. Most segments leave the
    surface untouched, and meshing a fitted part takes about a second.
    faces: positions in skin.faces that must be meshed (default: all). A
    partial mesh that lacks some grows to hold both sets.
    """
    global _last_mesh
    known = _last_mesh
    if known is not None and known.matches(skin):
        if known.subset is None or faces is not None and known.subset.issuperset(faces):
            return known
        if faces is not None:
            faces = known.subset.union(faces)
    _last_mesh = WrapMesh(skin, faces)
    return _last_mesh


class WrapMesh:
    def __init__(self, skin, faces=None):
        """Triangulate the skin, or only the faces at these positions.

        owners always counts positions in skin.faces. subset is None when
        every face is meshed.
        """
        self.skin = skin
        order = sorted(set(faces)) if faces is not None else range(len(skin.faces))
        self.subset = frozenset(order) if len(order) < len(skin.faces) else None
        # Mesh the connected compound first, so adjacent faces use the same
        # native edge discretization. Never sew separated faces by proximity.
        work = (skin.surface if self.subset is None
                else Part.makeCompound([skin.faces[i] for i in order])).copy()
        work.tessellate(DEFLECTION)
        points, triangles, owners, offset = [], [], [], 0
        for i,face in zip(order,work.Faces):
            vertices,facets = face.tessellate(DEFLECTION)
            if facets:
                points.extend((p.x,p.y,p.z) for p in vertices)
                triangles.append(np.asarray(facets,dtype=np.int64)+offset)
                owners.append(np.full(len(facets),i,dtype=np.int64))
            offset = len(points)
        if not triangles:
            raise ValueError('This surface has no usable drawing triangulation.')
        points = np.asarray(points,dtype=float)
        _,first,inverse = np.unique(np.round(points/1e-7).astype(np.int64),axis=0,
                                    return_index=True,return_inverse=True)
        self.points = points[first]
        self.triangles = inverse.reshape(-1)[np.concatenate(triangles)]
        self.owners = np.concatenate(owners)
        self.xyz = self.points[self.triangles]
        self.a,self.b = self.xyz[:,1]-self.xyz[:,0],self.xyz[:,2]-self.xyz[:,0]
        cross = np.cross(self.a,self.b)
        size = np.linalg.norm(cross,axis=1)
        good = size > 1e-14
        if not good.all():
            self.triangles,self.owners = self.triangles[good],self.owners[good]
            self.xyz,self.a,self.b,cross,size = self.xyz[good],self.a[good],self.b[good],cross[good],size[good]
        self.normals = cross/size[:,None]
        self.centers = self.xyz.mean(axis=1)
        # Pseudo-inverse of each [a b] edge pair, (MᵀM)⁻¹Mᵀ in closed form:
        # a per-triangle SVD took a fifth of the build.
        aa = np.einsum('ij,ij->i',self.a,self.a)
        ab = np.einsum('ij,ij->i',self.a,self.b)
        bb = np.einsum('ij,ij->i',self.b,self.b)
        det = (size*size)[:,None]  # aa*bb-ab*ab, the squared doubled area
        self.dual = np.stack(((bb[:,None]*self.a-ab[:,None]*self.b)/det,
                              (aa[:,None]*self.b-ab[:,None]*self.a)/det),axis=1)
        self.neighbors = neighbors(self.triangles)
        self._graph = None

    def paths(self, seed):
        """Shortest centre-to-centre path tree from one triangle (-1: none).

        SciPy's compiled Dijkstra finds the distances; a Python heap walk over
        a fitted part's graph took about 0.3 s on the first crossing. Equal
        paths are common on symmetric meshes, so each triangle keeps the
        predecessor that walk chose: the first one settled, by (distance,
        index), that reaches it at its distance.
        """
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import dijkstra
        if self._graph is None:
            count = len(self.triangles)
            rows = np.repeat(np.arange(count),3)
            cols = self.neighbors.ravel()
            keep = cols >= 0
            # Two sides shared by the same pair would add their weights.
            rows,cols = np.unique(np.column_stack((rows[keep],cols[keep])),axis=0).T
            step = self.centers[cols]-self.centers[rows]
            # Row dot products round like the former per-pair norm; positive
            # weights keep SciPy from reading a zero as a missing edge.
            lengths = np.maximum(np.sqrt((step[:,None,:]@step[:,:,None])[:,0,0]),1e-15)
            self._graph = (rows,cols,lengths,csr_matrix((lengths,(rows,cols)),shape=(count,count)))
        rows,cols,lengths,graph = self._graph
        distance = dijkstra(graph,indices=seed)
        reach = np.isfinite(distance[rows]) & (distance[rows]+lengths == distance[cols]) & (cols != seed)
        rows,cols = rows[reach],cols[reach]
        order = np.lexsort((rows,distance[rows],cols))
        rows,cols = rows[order],cols[order]
        first = np.ones(len(cols),dtype=bool)
        first[1:] = cols[1:] != cols[:-1]
        result = np.full(len(self.triangles),-1,dtype=np.int64)
        result[cols[first]] = rows[first]
        return result

    def matches(self, skin):
        """Whether this mesh was built from exactly these faces, in order."""
        return (len(self.skin.faces)==len(skin.faces)
                and all(a.isSame(b) and a.Orientation==b.Orientation
                        for a,b in zip(self.skin.faces,skin.faces)))

    def locate(self, point, face):
        owner = next((i for i,f in enumerate(self.skin.faces) if f.isSame(face)),None)
        candidates = np.flatnonzero(self.owners==owner)
        if not len(candidates):
            raise ValueError('Keep drawing on connected faces of the same object.')
        p = np.asarray(tuple(point))
        uv = np.einsum('nij,nj->ni',self.dual[candidates],p-self.xyz[candidates,0])
        weights = np.column_stack((1-uv.sum(axis=1),uv))
        projected = np.einsum('ni,nij->nj',weights,self.xyz[candidates])
        outside = np.maximum(-weights,0).sum(axis=1)
        score = np.linalg.norm(projected-p,axis=1)+outside*np.linalg.norm(self.a[candidates],axis=1)
        i = int(candidates[np.argmin(score)])
        w = weights[np.argmin(score)].clip(0,1)
        w /= w.sum()
        return i,w@self.xyz[i]


def _whole_guide_on_failure(method):
    """Repeat on the whole skin's guide what failed on the faces around the start.

    A path that leaves those faces meets the border of their guide. On the
    whole guide every answer, and every refusal, is the one it always was.
    """
    @functools.wraps(method)
    def call(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except ValueError:
            if not self._complete():
                raise
            return method(self, *args, **kwargs)
    return call


class WrapFrame:
    """Local millimetres developed over connected faces, including creases.

    A radial straight line in the drawing plane follows a transported surface
    direction. Curvature makes large outlines distort; a cut locus or opening
    can limit their size. This is not a global flattening of a closed solid.
    """
    def __init__(self, skin, face, anchor, x_direction=None, build=True):
        self.skin,self.face,self.anchor = skin,face,V(anchor)
        self.owner = next((i for i,f in enumerate(skin.faces) if f.isSame(face)),None)
        if self.owner is None:
            raise ValueError('Choose a starting face in this connected surface.')
        self.native = SurfaceFrame(face,anchor,x_direction)
        self.analytic = isinstance(face.Surface,(Part.Plane,Part.Cylinder))
        self.native_skin = Part.makeCompound([f for f in skin.faces if same_surface(face,f)]) if self.analytic else None
        self.plane = self.native.plane
        self._mesh = None
        self._inverse = None
        self._previous = None
        self._cache = {}
        self._picked = {}
        self._boundaries = {}
        if build and not self.analytic:
            self.mesh  # Fitted faces trace every point; meet errors on the first click.

    @property
    def mesh(self):
        """The guide triangulation, built on first use.

        A plane or cylinder outline that stays on its native surface never
        needs it; meshing a large connected skin took about 0.2 s per click.
        A frame made with build=False defers it on fitted faces as well.
        The guide first holds the starting face and the faces sharing an edge
        with it: meshing the whole fitted hood took 0.5 s after each split,
        its neighbourhood under 0.1 s. Anything that reaches farther repeats
        on the whole skin's guide.
        """
        if self._mesh is None:
            self._use(wrap_mesh(self.skin,self._around()))
        return self._mesh

    def _around(self):
        """Positions of the starting face and its edge neighbours in the skin."""
        adj,indices = getattr(self.skin,'adj',None),getattr(self.skin,'indices',None)
        if adj is None or indices is None:
            return None
        order = sorted(indices)
        if len(order) != len(self.skin.faces):
            return None
        position = {index:number for number,index in enumerate(order)}
        start = order[self.owner]
        return {self.owner} | {position[j] for j,_ in adj.neighbours(start) if j in position}

    def _use(self, mesh):
        self.seed,self.start = mesh.locate(self.anchor,self.face)
        self._mesh = mesh
        # Triangle numbers differ between guides.
        self._cache.clear()
        self._inverse = None

    def _complete(self):
        """Switch to the whole skin's guide; False when it is already in use."""
        if self._mesh is None or self._mesh.subset is None:
            return False
        self._use(wrap_mesh(self.skin))
        return True

    def trace(self, q):
        key = (round(q.x,9),round(q.y,9))
        if key in self._cache:
            return self._cache[key]
        distance = math.hypot(q.x,q.y)
        if not math.isfinite(distance):
            raise ValueError('Enter finite surface dimensions.')
        mesh = self.mesh
        i,point = self.seed,self.start.copy()
        if distance < geo.EPS:
            return self.seed,self.start.copy()
        direction = np.asarray(tuple(self.plane.u*q.x+self.plane.v*q.y))
        normal = mesh.normals[i]
        direction -= normal*direction.dot(normal)
        direction /= np.linalg.norm(direction)
        previous = -1
        for _ in range(min(20000,len(mesh.triangles)*4)):
            uv = mesh.dual[i]@(point-mesh.xyz[i,0])
            w = np.array((1-uv.sum(),uv[0],uv[1]))
            dv = mesh.dual[i]@direction
            dw = np.array((-dv.sum(),dv[0],dv[1]))
            times = np.divide(-w,dw,out=np.full(3,np.inf),where=dw < -1e-12)
            times[times < -1e-7] = np.inf
            # At an edge or vertex do not immediately walk back into the
            # triangle just left because of roundoff.
            times[(mesh.neighbors[i]==previous) & (times < 1e-7)] = np.inf
            side = int(np.argmin(times))
            step = max(0.,float(times[side]))
            if distance <= step+1e-8:
                result = i,point+direction*distance
                if len(self._cache)>8192:
                    self._cache.clear()
                self._cache[key] = result
                return result
            if not math.isfinite(step):
                raise ValueError('The wrap meets a surface corner. Move its starting point slightly.')
            point += direction*step
            distance -= step
            other = int(mesh.neighbors[i,side])
            if other < 0:
                raise ValueError('The wrapped drawing reaches an opening or an unconnected boundary.')
            edge = mesh.points[mesh.triangles[i,(side+2)%3]]-mesh.points[mesh.triangles[i,(side+1)%3]]
            edge /= np.linalg.norm(edge)
            # Transport over the shared edge without changing travelled length.
            into = mesh.centers[other]-point
            into -= edge*into.dot(edge)
            into /= np.linalg.norm(into)
            parallel = float(direction.dot(edge))
            direction = edge*parallel+into*math.sqrt(max(0.,1-parallel*parallel))
            previous,i = i,other
        raise ValueError('The wrapped drawing winds too far around the object. Make it smaller.')

    @_whole_guide_on_failure
    def point(self, q, exact=True):
        """The surface point for drawing coordinates q.

        exact=False is for previews: off a native plane or cylinder it returns
        the traced guide position instead of inverting the fitted surface for
        every sample. That is a few hundredths of a millimetre off the surface
        (0.04 mm at most on the fitted hood), far inside FreeCAD's own shaded
        display. Saved curves always use exact points.
        """
        if q.Length < geo.EPS:
            return V(self.anchor)
        picked = self._picked.get((round(q.x,8),round(q.y,8)))
        if picked is not None:
            return V(picked[0])
        if self.analytic:
            exact = self.native.point(q)
            if self.native_skin.distToShape(Part.Vertex(exact))[0] <= 1e-7:
                return exact
        tri,point = self.trace(q)
        if not exact:
            return V(*point)
        face = self.skin.faces[int(self.mesh.owners[tri])]
        return face.valueAt(*face.Surface.parameter(V(*point)))

    @_whole_guide_on_failure
    def face_at(self,q):
        picked = self._picked.get((round(q.x,8),round(q.y,8)))
        if picked is not None:
            return picked[1]
        if self.analytic and self.native_skin.distToShape(Part.Vertex(self.native.point(q)))[0] <= 1e-7:
            return self.face
        tri,_ = self.trace(q)
        return self.skin.faces[int(self.mesh.owners[tri])]

    @_whole_guide_on_failure
    def points(self, points):
        # Sample straight preview edges too: their image can cross a crease.
        mapped = []
        for a,b in zip(points,points[1:]):
            count = 1 if len(points)>32 else max(1,min(128,int((b-a).Length/.5)+1))
            mapped.extend(a+(b-a)*(i/count) for i in range(count))
        if points:
            mapped.append(points[-1])
        self._warm_points(mapped)
        world = [self.point(q,exact=False) for q in mapped]
        owners = []
        for q,p in zip(mapped,world):
            if self.analytic and on_surface(self.face,p):
                owners.append(self.owner)
            else:
                tri,_ = self.trace(q)
                owners.append(int(self.mesh.owners[tri]))
        result = world[:1]
        for a,b,left,right in zip(world,world[1:],owners,owners[1:]):
            if left != right:
                edges = self._shared_edges(left,right)
                if edges:
                    middle = (a+b)*.5
                    edge = min(edges,key=lambda e:e.distToShape(Part.Vertex(middle))[0])
                    _,pairs,_ = edge.distToShape(Part.Vertex(middle))
                    origin = pairs[0][0]
                    tangent = edge.tangentAt(edge.Curve.parameter(origin))
                    da,db = (a-origin).cross(tangent).Length,(b-origin).cross(tangent).Length
                    fraction = da/(da+db) if da+db>geo.EPS else .5
                    target = origin+tangent*((a-origin).dot(tangent)+(b-a).dot(tangent)*fraction)
                    _,pairs,_ = edge.distToShape(Part.Vertex(target))
                    result.append(pairs[0][0])
            result.append(b)
        return result

    def _shared_edges(self,left,right):
        key = tuple(sorted((left,right)))
        if key not in self._boundaries:
            a,b = self.skin.faces[left],self.skin.faces[right]
            self._boundaries[key] = [e for e in a.Edges if any(e.isSame(f) for f in b.Edges)]
        return self._boundaries[key]

    def _warm_points(self, points):
        """March a preview's rays together with NumPy, rather than per point."""
        pending = {(round(q.x,9),round(q.y,9)):q for q in points if q.Length>=geo.EPS}
        pending = {key:q for key,q in pending.items() if key not in self._cache}
        if self.analytic:
            pending = {key:q for key,q in pending.items()
                       if self.native_skin.distToShape(Part.Vertex(self.native.point(q)))[0] > 1e-7}
        if not pending:
            return
        keys = list(pending)
        q = np.asarray([(pending[key].x,pending[key].y) for key in keys])
        remaining = np.linalg.norm(q,axis=1)
        if not np.isfinite(remaining).all():
            raise ValueError('Enter finite surface dimensions.')
        mesh = self.mesh
        direction = q[:,0,None]*np.asarray(tuple(self.plane.u))+q[:,1,None]*np.asarray(tuple(self.plane.v))
        normal = mesh.normals[self.seed]
        direction -= (direction@normal)[:,None]*normal
        direction /= np.linalg.norm(direction,axis=1)[:,None]
        position = np.tile(self.start,(len(keys),1))
        indices = np.full(len(keys),self.seed,dtype=np.int64)
        previous = np.full(len(keys),-1,dtype=np.int64)
        active = np.arange(len(keys))
        for _ in range(min(20000,len(mesh.triangles)*4)):
            if not len(active):
                if len(self._cache)+len(keys)>8192:
                    self._cache.clear()
                self._cache.update((key,(int(i),p.copy())) for key,i,p in zip(keys,indices,position))
                return
            i = indices[active]
            uv = np.einsum('nij,nj->ni',mesh.dual[i],position[active]-mesh.xyz[i,0])
            w = np.column_stack((1-uv.sum(axis=1),uv))
            dv = np.einsum('nij,nj->ni',mesh.dual[i],direction[active])
            dw = np.column_stack((-dv.sum(axis=1),dv))
            times = np.divide(-w,dw,out=np.full_like(w,np.inf),where=dw < -1e-12)
            times[times < -1e-7] = np.inf
            times[(mesh.neighbors[i]==previous[active,None]) & (times<1e-7)] = np.inf
            side = np.argmin(times,axis=1)
            steps = np.maximum(0,times[np.arange(len(active)),side])
            done = remaining[active] <= steps+1e-8
            finished = active[done]
            position[finished] += direction[finished]*remaining[finished,None]
            moving = active[~done]
            if not len(moving):
                active = moving
                continue
            step = steps[~done]
            if not np.isfinite(step).all():
                raise ValueError('The wrap meets a surface corner. Move its starting point slightly.')
            position[moving] += direction[moving]*step[:,None]
            remaining[moving] -= step
            i,side = i[~done],side[~done]
            other = mesh.neighbors[i,side]
            if (other<0).any():
                raise ValueError('The wrapped drawing reaches an opening or an unconnected boundary.')
            edge = mesh.points[mesh.triangles[i,(side+2)%3]]-mesh.points[mesh.triangles[i,(side+1)%3]]
            edge /= np.linalg.norm(edge,axis=1)[:,None]
            into = mesh.centers[other]-position[moving]
            into -= edge*np.einsum('ij,ij->i',into,edge)[:,None]
            into /= np.linalg.norm(into,axis=1)[:,None]
            parallel = np.einsum('ij,ij->i',direction[moving],edge)
            direction[moving] = edge*parallel[:,None]+into*np.sqrt(np.maximum(0,1-parallel**2))[:,None]
            previous[moving],indices[moving] = i,other
            active = moving
        raise ValueError('The wrapped drawing winds too far around the object. Make it smaller.')

    def _unfold(self, target, point):
        mesh = self.mesh
        if self._inverse is None:
            self._inverse = mesh.paths(self.seed)
        chain,i = [target],target
        while i != self.seed:
            i = int(self._inverse[i])
            if i < 0:
                raise ValueError('That face is not connected to the starting surface.')
            chain.append(i)
        # Develop the target backwards over its corridor into the seed plane.
        p = np.asarray(point).copy()
        for j,i in zip(chain,chain[1:]):
            shared = list(set(mesh.triangles[i]) & set(mesh.triangles[j]))
            a,b = mesh.points[shared]
            axis = (b-a)/np.linalg.norm(b-a)
            left = mesh.centers[j]-a
            left -= axis*left.dot(axis)
            left /= np.linalg.norm(left)
            right = mesh.centers[i]-a
            right -= axis*right.dot(axis)
            right /= np.linalg.norm(right)
            d = p-a
            p = a+axis*d.dot(axis)-right*d.dot(left)-np.cross(axis,right)*d.dot(np.cross(axis,left))
        delta = V(*(p-self.start))
        return V(delta.dot(self.plane.u),delta.dot(self.plane.v),0)

    @_whole_guide_on_failure
    def local(self, point, face=None):
        face = face or self.face
        if not self.skin.contains(face) or not on_surface(face,point):
            raise ValueError('Choose a point on a connected face of the same object.')
        if self.analytic and same_surface(self.face,face):
            q = self.native.local(point)
            if self._previous is not None:
                for axis,name in enumerate(('U','V')):
                    if getattr(self.face.Surface,'is'+name+'Periodic')():
                        period = getattr(self.face.Surface,name+'Period')()
                        u,v = (period,0.) if axis==0 else (0.,period)
                        step = V((u*self.native.y[1]-v*self.native.y[0])/self.native.det,
                                 (v*self.native.x[0]-u*self.native.x[1])/self.native.det,0)
                        q += step*round((self._previous-q).dot(step)/step.dot(step))
            self._previous = q
            if len(self._picked)>4096:
                self._picked.clear()
            self._picked[(round(q.x,8),round(q.y,8))] = V(point),face
            return q
        # Import only off the analytic path; it may still be loading.
        from scipy.optimize import least_squares
        target,p = self.mesh.locate(point,face)
        basis = self.mesh.dual[target]

        def residual(q):
            try:
                _,value = self.trace(V(float(q[0]),float(q[1]),0))
                return basis@(value-p)
            except ValueError:
                if self._mesh.subset is not None:
                    raise  # Solve on the whole guide, as before it was partial.
                return np.array((1e3,1e3))

        seeds = []
        if same_surface(self.face,face):
            seeds.insert(0,self.native.local(point))
        if self._previous is not None:
            seeds.insert(0,self._previous)
        if not seeds:
            seeds.append(self._unfold(target,p))
        # The triangle corridor is an initial guess only. Defer its graph walk
        # when the previous hover or native coordinates already solve locally.
        seeds.append(None)
        for seed in seeds:
            if seed is None:
                seed = self._unfold(target,p)
            found = least_squares(residual,[seed.x,seed.y],diff_step=1e-4,max_nfev=20,
                                  ftol=1e-9,xtol=1e-9,gtol=1e-9)
            q = V(float(found.x[0]),float(found.x[1]),0)
            try:
                i,world = self.trace(q)
                if np.linalg.norm(world-p) <= max(.002,DEFLECTION*2):
                    self._previous = q
                    if len(self._picked)>4096:
                        self._picked.clear()
                    self._picked[(round(q.x,8),round(q.y,8))] = V(point),face
                    return q
            except ValueError:
                if self._mesh.subset is not None:
                    raise
        raise ValueError('No continuous wrap there. Click an intermediate point around the corner or opening.')

    def _boundary(self, left, right, point):
        edges = self._shared_edges(left,right)
        if not edges:
            raise ValueError('The outline skips a surface boundary. Make it smaller or move its start.')
        vertex = Part.Vertex(point)
        edge = min(edges,key=lambda e:e.distToShape(vertex)[0])
        _,pairs,_ = edge.distToShape(vertex)
        return pairs[0][0],max(geo.EPS,edge.getTolerance(1))

    @_whole_guide_on_failure
    def curves(self, profile):
        """Refit per-face pcurves, sharing exact native boundary endpoints."""
        if self.analytic:
            try:
                exact = self.native.curves(profile)
                if all(covered(self.native_skin,e) for e in exact):
                    return exact
            except ValueError as error:
                if 'wraps all the way' in str(error):
                    raise
        result = []
        # A seam crossing is shared by the end of one face's curve and the
        # start of the next. Key it by (edge, crossing number): a crossing
        # point is freed after its edge, and a later point can reuse its id().
        seam_vertices = {}
        for number,edge in enumerate(profile.Edges):
            count = max(16,min(2048,int(edge.Length/.25)+1))
            lo,hi = edge.FirstParameter,edge.LastParameter

            def sample(t):
                q = edge.valueAt(t)
                tri,p = self.trace(q)
                return self.mesh.owners[tri],self.point(q)

            samples = [(lo,*sample(lo))]
            for t in np.linspace(lo,hi,count)[1:]:
                samples.append((float(t),*sample(float(t))))
            groups,group = [],[samples[0][2]]
            tolerances = []
            owner = int(samples[0][1])
            for (t0,a,p0),(t1,b,p1) in zip(samples,samples[1:]):
                a,b = int(a),int(b)
                if a != b:
                    low,high = t0,t1
                    for _ in range(32):
                        mid = (low+high)/2
                        if int(sample(mid)[0]) == a:
                            low = mid
                        else:
                            high = mid
                    crossing,tolerance = self._boundary(a,b,sample((low+high)/2)[1])
                    tolerances.append(tolerance)
                    group.append(crossing)
                    groups.append((owner,group))
                    owner,group = b,[crossing]
                group.append(p1)
            groups.append((owner,group))
            for index,(owner,points) in enumerate(groups):
                face = self.skin.faces[owner]
                uv = []
                for i,p in enumerate(points):
                    captured = snap_point(face,p,'On edge') if i in (0,len(points)-1) else None
                    value = face.Surface.parameter(captured or p)
                    value = list(value)
                    if uv:
                        for j,axis in enumerate(('U','V')):
                            if getattr(face.Surface,'is'+axis+'Periodic')():
                                period = getattr(face.Surface,axis+'Period')()
                                value[j] += round((uv[-1][j]-value[j])/period)*period
                    if not uv or math.dist(value,uv[-1]) > 1e-10:
                        uv.append(value)
                if len(uv)<2:
                    continue
                values = [App.Base.Vector2d(*p) for p in uv]
                delta = values[-1]-values[0]
                length = math.hypot(delta.x,delta.y)
                straight = length>1e-10 and all(abs((p.x-values[0].x)*delta.y-(p.y-values[0].y)*delta.x)
                                               <= length*1e-10 for p in values)
                if straight:
                    spline = Part.Geom2d.Line2dSegment(values[0],values[-1])
                else:
                    spline = Part.Geom2d.BSplineCurve2d()
                    spline.interpolate(Points=values,Tolerance=1e-12)
                if not straight and len(values)>8:
                    du,dv = face.derivative1At(*uv[len(uv)//2])
                    tolerance = CURVE_TOLERANCE/max(du.Length,dv.Length)
                    reference = spline.copy()
                    knots = reference.getKnots()
                    for k in range(spline.NbKnots-1,1,-1):
                        spline.removeKnot(k,0,tolerance*.1)
                    # Knot removal keeps the parameterization. Bound the total
                    # fit change, rather than accumulating a tolerance per knot.
                    samples = knots+[(a+b)/2 for a,b in zip(knots,knots[1:])]
                    if any(math.hypot(spline.value(t).x-reference.value(t).x,
                                      spline.value(t).y-reference.value(t).y) > tolerance for t in samples):
                        spline = reference
                curve = spline.toShape(face.Surface)
                # Fitted source faces may disagree in 3D at their shared edge
                # within that edge's existing BREP tolerance. Give only these
                # new seam vertices the required source-bounded accuracy; do
                # not move the surface or enlarge a shape validation threshold.
                # Group i starts at crossing i-1 and ends at crossing i.
                for p,vertex,crossing in ((points[0],curve.Vertexes[0],index-1),
                                          (points[-1],curve.Vertexes[-1],index)):
                    if 0 <= crossing < len(tolerances):
                        tolerance = tolerances[crossing]
                        error = (vertex.Point-p).Length
                        if error > tolerance+geo.EPS:
                            raise ValueError('The wrap could not meet the native surface seam within its existing accuracy.')
                        vertex.fixTolerance(max(geo.EPS,error+geo.EPS))
                        seam_vertices.setdefault((number,crossing),[]).append((vertex,tolerance))
                result.append(curve)
        for vertices in seam_vertices.values():
            error = max((a.Point-b.Point).Length for a,_ in vertices for b,_ in vertices)
            for vertex,tolerance in vertices:
                if error > tolerance+geo.EPS:
                    raise ValueError('The wrap exceeds the existing surface seam accuracy.')
                vertex.fixTolerance(max(vertex.getTolerance(1),error+geo.EPS))
        if not result:
            raise ValueError('Choose a nonzero surface outline.')
        return result

    def edge(self, profile):
        edges = self.curves(profile)
        return edges[0] if len(edges)==1 else Part.Wire(edges)

    def wire(self, profile):
        wire = Part.Wire(self.curves(profile))
        if not wire.isClosed() or not wire.isValid():
            raise ValueError('The wrapped outline could not close cleanly across these faces.')
        return wire
