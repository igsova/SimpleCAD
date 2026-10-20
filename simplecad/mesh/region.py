"""Connected triangle regions and indexed edits, independent of CAD and Qt."""
from collections import deque
import math
import numpy as np
from .transform import MAX_TRIANGLES, MIN_DOUBLE_AREA, double_areas, scalar, vector


class _Sets:
    """Read-only neighbor sets per item, from (row, value) pairs on demand."""
    def __init__(self, size, rows, values):
        keys = np.sort(rows*max(size,1)+values)
        keys = keys[np.r_[True, keys[1:]!=keys[:-1]]] if len(keys) else keys
        self.values = keys % max(size,1)
        self.starts = np.searchsorted(keys//max(size,1), np.arange(size+1))
        self.cache = {}

    def __len__(self):
        return len(self.starts)-1

    def __getitem__(self, i):
        found = self.cache.get(i)
        if found is None:
            if not -len(self) <= i < len(self): raise IndexError(i)
            i = int(i) % len(self)
            found = self.cache[i] = frozenset(self.values[self.starts[i]:self.starts[i+1]].tolist())
        return found

    def __iter__(self):
        return (self[i] for i in range(len(self)))


class Topology:
    def __init__(self, points, triangles):
        self.points = np.asarray(points, dtype=float)
        self.triangles = np.asarray(triangles)
        p, f = self.points, self.triangles
        if (p.ndim != 2 or p.shape[1] != 3 or not len(p) or not np.isfinite(p).all()
                or np.max(abs(p)) > 1e7 or f.ndim != 2 or f.shape[1] != 3
                or f.dtype.kind not in 'iu' or not 0 < len(f) <= MAX_TRIANGLES
                or f.min() < 0 or f.max() >= len(p)):
            raise ValueError('Choose a finite indexed mesh with 1 to 500000 triangles.')
        self.triangles = f = f.astype(np.int64, copy=True)
        samples = p[f]
        self.centers = samples.mean(axis=1)
        self.cross = np.cross(samples[:,1]-samples[:,0], samples[:,2]-samples[:,0])
        self.areas = np.linalg.norm(self.cross,axis=1)
        self.normals = self.cross / np.maximum(self.areas[:,None], MIN_DOUBLE_AREA)
        # Vectorized connectivity: Python loops over every half-edge took
        # ~0.3 s on a 17k-triangle STL, every time a tool or Apply started.
        # Half-edges keep triangle order: (a,b), (b,c), (c,a) for each face.
        self.half_edges = np.stack((f, np.roll(f,-1,axis=1)), axis=2).reshape(-1,2)
        self.half_faces = np.repeat(np.arange(len(f)), 3)
        low, high = self.half_edges.min(axis=1), self.half_edges.max(axis=1)
        keys = low*len(p)+high
        order = np.argsort(keys, kind='stable')
        sorted_keys = keys[order]
        starts = np.flatnonzero(np.r_[True, sorted_keys[1:]!=sorted_keys[:-1]])
        counts = np.diff(np.r_[starts, len(keys)])
        self.edge_counts = counts
        self.edge_group = np.empty(len(keys), dtype=np.int64)
        self.edge_group[order] = np.repeat(np.arange(len(starts)), counts)
        self._edge_order, self._edge_starts, self._edge_keys = order, starts, sorted_keys[starts]
        self.border_faces = set(self.half_faces[counts[self.edge_group]!=2].tolist())
        pairs = starts[counts==2]
        first, second = self.half_faces[order[pairs]], self.half_faces[order[pairs+1]]
        self.adjacent = _Sets(len(f), np.r_[first,second], np.r_[second,first])
        low, high = low[order[starts]], high[order[starts]]
        self.neighbors = _Sets(len(p), np.r_[low,high], np.r_[high,low])
        self._edges = None

    @property
    def edges(self):
        """{(low, high): [(triangle, a, b), ...]} in first-appearance order.

        Built on demand; editing paths use the indexed arrays instead.
        """
        if self._edges is None:
            order, starts = self._edge_order, self._edge_starts
            stops = np.r_[starts[1:], len(order)]
            faces, half = self.half_faces.tolist(), self.half_edges.tolist()
            self._edges = {}
            for group in np.argsort(order[starts], kind='stable').tolist():
                entries = [(faces[k],*half[k]) for k in order[starts[group]:stops[group]].tolist()]
                a,b = entries[0][1:]
                self._edges[(min(a,b),max(a,b))] = entries
        return self._edges

    def edge_faces(self, a, b):
        """Triangles that use edge a-b in the original connectivity."""
        key = min(a,b)*len(self.points)+max(a,b)
        group = int(np.searchsorted(self._edge_keys, key))
        if group == len(self._edge_keys) or self._edge_keys[group] != key:
            return []
        start = self._edge_starts[group]
        return self.half_faces[self._edge_order[start:start+self.edge_counts[group]]].tolist()

    def components(self):
        """Connected-component label per triangle and whether each is closed."""
        pairs = self._edge_starts[self.edge_counts==2]
        a = self.half_faces[self._edge_order[pairs]]; b = self.half_faces[self._edge_order[pairs+1]]
        labels = np.arange(len(self.triangles))
        while True:
            # Hook each pair to its smaller root, then compress paths.
            low = np.minimum(labels[a], labels[b])
            previous = labels.copy()
            np.minimum.at(labels, labels[a], low); np.minimum.at(labels, labels[b], low)
            while True:
                jumped = labels[labels]
                if np.array_equal(jumped, labels): break
                labels = jumped
            if np.array_equal(labels, previous): break
        roots, labels = np.unique(labels, return_inverse=True)
        border = np.zeros(len(roots), dtype=bool)
        border[labels[sorted(self.border_faces)]] = True
        return labels.astype(np.int64), ~border

    def indices(self, values):
        if not isinstance(values,(list,tuple)) or not values or len(values)>len(self.triangles):
            raise ValueError('Select at least one triangle region.')
        if any(type(v) is not int or not 1 <= v <= len(self.triangles) for v in values):
            raise ValueError('Triangle numbers must refer to the current mesh, starting at 1.')
        return set(v-1 for v in values)

    def grow(self, selected, rings):
        if type(rings) is not int or not -30 <= rings <= 30:
            raise ValueError('Grow/shrink must be between -30 and 30 rings.')
        result = set(selected)
        for _ in range(abs(rings)):
            if rings > 0:
                result |= {n for i in result for n in self.adjacent[i]}
            else:
                result -= {i for i in result if self.adjacent[i]-result or i in self.border_faces}
        return result

    def region(self, seed_triangle, mode='Flat', angle=15, grow=0):
        seed = next(iter(self.indices([seed_triangle])))
        if mode not in ('Flat','Smooth','Triangle'):
            raise ValueError('Choose Flat, Smooth, or Triangle selection.')
        angle = scalar(angle,'Crease angle')
        if not 0 <= angle <= 90:
            raise ValueError('Choose a crease angle between 0 and 90 degrees.')
        found = {seed}
        if mode != 'Triangle':
            queue = deque([seed])
            cosine = math.cos(math.radians(.1 if mode == 'Flat' else angle))
            while queue:
                i = queue.popleft()
                for j in self.adjacent[i]-found:
                    reference = seed if mode == 'Flat' else i
                    if self.areas[j] <= MIN_DOUBLE_AREA or self.normals[reference] @ self.normals[j] < cosine:
                        continue
                    if mode == 'Flat' and np.max(abs((self.points[self.triangles[j]]-self.centers[seed]) @ self.normals[seed])) > .005:
                        continue
                    found.add(j); queue.append(j)
        return self.grow(found,grow)

    def pick(self, origin, direction, points=None, triangles=None):
        """Vectorized ray hit: only on click, never a per-mouse-move mesh scan."""
        p = self.points if points is None else points
        f = self.triangles if triangles is None else triangles
        tri = p[f]; a = tri[:,1]-tri[:,0]; b = tri[:,2]-tri[:,0]
        direction = vector(direction,'Ray direction'); length = np.linalg.norm(direction)
        if length < 1e-10: raise ValueError('Ray direction must be nonzero.')
        direction /= length
        h = np.cross(direction,b); det = np.einsum('ij,ij->i',a,h)
        valid = abs(det) > 1e-12
        inv = np.divide(1.,det,out=np.zeros_like(det),where=valid)
        s = vector(origin,'Ray origin')-tri[:,0]
        u = inv*np.einsum('ij,ij->i',s,h)
        q = np.cross(s,a); v = inv*(q @ direction)
        t = inv*np.einsum('ij,ij->i',b,q)
        valid &= (u >= -1e-9) & (v >= -1e-9) & (u+v <= 1+1e-9) & (t >= 0)
        return int(np.argmin(np.where(valid,t,np.inf))) if valid.any() else None


def resolve(topology, triangles=None, seed_triangle=None, selection='Flat', crease=15, grow=0):
    if (triangles is None) == (seed_triangle is None):
        raise ValueError('Specify either selected triangle numbers or one seed triangle.')
    if triangles is not None:
        return topology.grow(topology.indices(triangles),grow)
    return topology.region(seed_triangle,selection,crease,grow)


def rotate(points, axis, angles):
    cs,sn = np.cos(angles)[:,None],np.sin(angles)[:,None]
    return points*cs + np.cross(axis,points)*sn + (points @ axis)[:,None]*axis*(1-cs)


class RegionPlan:
    def __init__(self, topology, selected, rings=1):
        if not selected or any(i<0 or i>=len(topology.triangles) for i in selected):
            raise ValueError('Select at least one triangle region.')
        if type(rings) is not int or not 1 <= rings <= 30:
            raise ValueError('Transition must contain 1 to 30 neighboring vertex rings.')
        self.topology = topology
        self.selected = np.asarray(sorted(selected),dtype=np.int64)
        self.vertices = np.unique(topology.triangles[self.selected])
        areas = topology.areas[self.selected]
        if areas.sum() <= MIN_DOUBLE_AREA: raise ValueError('The selected region has no usable surface area.')
        self.center = np.average(topology.centers[self.selected],axis=0,weights=areas)
        normal = topology.cross[self.selected].sum(axis=0)
        self.normal = normal/np.linalg.norm(normal) if np.linalg.norm(normal)>1e-10 else None
        self.weights = np.zeros(len(topology.points))
        self.weights[self.vertices] = 1
        visited = set(self.vertices.tolist()); frontier = visited.copy()
        for ring in range(1,rings):
            frontier = {j for i in frontier for j in topology.neighbors[i]}-visited
            if not frontier: break
            self.weights[list(frontier)] = 1-ring/rings
            visited |= frontier
        mask = np.zeros(len(topology.triangles),dtype=bool); mask[self.selected] = True
        chosen = mask[topology.half_faces]
        per_edge = np.bincount(topology.edge_group,weights=chosen,minlength=len(topology.edge_counts))
        if np.any((topology.edge_counts>2) & (per_edge>0)):
            raise ValueError('Repair non-manifold edges before editing this region.')
        outline = chosen & (per_edge[topology.edge_group]==1)
        # Directed as in the selected triangle; walls and orientation checks
        # use the triangle that owns each boundary edge.
        self.boundary = [tuple(e) for e in topology.half_edges[outline].tolist()]
        self.boundary_faces = topology.half_faces[outline]
        self.extrusion = None

    def extrusion_topology(self):
        if self.extrusion is None:
            if not self.boundary: raise ValueError('Extrude needs a surface patch with a boundary, not an entire closed component.')
            degree = {}
            for a,b in self.boundary:
                degree[a] = degree.get(a,0)+1; degree[b] = degree.get(b,0)+1
            if any(n!=2 for n in degree.values()): raise ValueError('The region boundary branches. Select one or more complete surface patches.')
            p,f = self.topology.points,self.topology.triangles
            remap = np.arange(len(p)); remap[self.vertices] = np.arange(len(p),len(p)+len(self.vertices))
            keep = np.ones(len(f),dtype=bool); keep[self.selected] = False
            walls = [(a,b,int(remap[b])) for a,b in self.boundary] + [(a,int(remap[b]),int(remap[a])) for a,b in self.boundary]
            faces = np.vstack((f[keep],remap[f[self.selected]],walls))
            if len(faces)>MAX_TRIANGLES: raise ValueError('The extrusion exceeds 500000 triangles.')
            inherited = np.r_[self.topology.areas[keep]<=MIN_DOUBLE_AREA,
                              self.topology.areas[self.selected]<=MIN_DOUBLE_AREA,np.zeros(len(walls),dtype=bool)]
            self.extrusion = faces,inherited
        return self.extrusion

    def transform(self, mode='Move', delta=(0,0,0), axis=None, angle=0, distance=0, pivot=None):
        p,f = self.topology.points,self.topology.triangles
        if mode not in ('Move','Rotate','Extrude'): raise ValueError('Choose Move, Rotate, or Extrude.')
        if mode == 'Move':
            moved = p+self.weights[:,None]*vector(delta,'Movement')
        else:
            axis = self.normal if axis is None else vector(axis,'Direction')
            if axis is None or np.linalg.norm(axis)<1e-10: raise ValueError('Choose an explicit direction for this region.')
            axis = axis/np.linalg.norm(axis)
            if mode == 'Rotate':
                angle = scalar(angle,'Rotation angle')
                if abs(angle)>180: raise ValueError('Choose an angle between -180 and 180 degrees.')
                center = self.center if pivot is None else vector(pivot,'Pivot')
                moved = center+rotate(p-center,axis,np.radians(angle)*self.weights)
                moved[self.weights==0] = p[self.weights==0]
            else:
                distance = scalar(distance,'Extrusion distance')
                if abs(distance)<1e-7: raise ValueError('Enter a nonzero extrusion distance.')
                f,_ = self.extrusion_topology()
                moved = np.vstack((p,p[self.vertices]+axis*distance))
        if not np.isfinite(moved).all() or np.max(abs(moved))>1e7:
            raise ValueError('The result exceeds the supported coordinate range.')
        if mode == 'Move':
            from .retriangulate import planar_diagonals
            f = planar_diagonals(self.topology,moved,self.selected)
        return moved,f

    def validate(self, moved, triangles, mode):
        allowed = self.extrusion_topology()[1] if mode=='Extrude' else self.topology.areas<=MIN_DOUBLE_AREA
        if np.any((double_areas(moved,triangles)<=MIN_DOUBLE_AREA) & ~allowed):
            raise ValueError('This edit collapses triangles. Reduce the movement or select a larger transition.')

    def validate_shell_orientation(self, moved, triangles, mode):
        """Reject closed shells turned inside out, even in multipart meshes.

        Run on Apply, not each preview frame. The native self-intersection
        check alone cannot detect an already fully inverted closed shell.
        """
        t=self.topology
        labels,closed=t.components()
        first=np.unique(labels,return_index=True)[1]
        origins=t.points[t.triangles[first,0]]
        def volumes(points,faces,groups):
            samples=points[faces]-origins[groups,None,:]
            values=np.einsum('ij,ij->i',samples[:,0],np.cross(samples[:,1],samples[:,2]))/6
            return np.bincount(groups,weights=values,minlength=len(origins))
        before=volumes(t.points,t.triangles,labels)
        groups=labels
        if mode=='Extrude':
            keep=np.ones(len(labels),dtype=bool); keep[self.selected]=False
            walls=labels[self.boundary_faces]
            groups=np.r_[labels[keep],labels[self.selected],walls,walls].astype(np.int64)
        after=volumes(moved,triangles,groups)
        if np.any(closed & (before*after<=0)):
            raise ValueError('This edit turns a closed mesh shell inside out or flattens it. Reduce the movement.')

    def summary(self):
        return {'triangles':len(self.selected), 'vertices':len(self.vertices),
                'center':self.center.tolist(), 'normal':None if self.normal is None else self.normal.tolist(),
                'area':float(self.topology.areas[self.selected].sum()/2), 'boundary_edges':len(self.boundary),
                'transition_vertices':int(np.count_nonzero((self.weights>0)&(self.weights<1)))}
