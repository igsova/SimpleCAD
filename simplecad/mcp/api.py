"""Explicit SimpleCAD automation operations. Call only on FreeCAD's GUI thread."""
import base64
from dataclasses import asdict, replace
import math
from pathlib import Path
import tempfile
import uuid

import FreeCAD as App
import FreeCADGui as Gui
import Part
from ..core import geometry as geo, preferences
from ..document import operations as ops, visibility, appearance, locking
from ..modeling import rotation, slicing, joints
from ..mesh.conversion import is_mesh, cached_fingerprints
from .catalog import BY_NAME, MUTATIONS, validate
from ..gui.qt import QtCore, QtWidgets


def xyz(point): return [point.x, point.y, point.z]


class Revisions:
    """Snapshot native shape identity and view metadata without editing documents."""
    def __init__(self):
        self.states = {}
        self.session = uuid.uuid4().hex
        self.serial = 0

    def get(self, doc):
        live = App.listDocuments()
        for name in set(self.states)-set(live): self.states.pop(name)
        state = []
        for item in doc.Objects:
            view = item.ViewObject
            state.append((item.Name, item.Label, item.TypeId,
                          item.Shape if hasattr(item, 'Shape') else None,
                          locking.whole(item), getattr(item, locking.FACES, ''),
                          bool(view.Visibility) if view else None,
                          getattr(view, visibility.PROPERTY, '') if view else '',
                          # Native redraw may round material channels to six
                          # decimals. That is not a user/model appearance edit.
                          appearance.fingerprint(view.ShapeAppearance, precision=6) if view and hasattr(view,'ShapeAppearance') else None,
                          # Hashed again only after the mesh changes: a hidden
                          # source mesh must not slow every status request.
                          cached_fingerprints.get(item) if is_mesh(item) else None))
        old = self.states.get(doc.Name)
        history = (doc.UndoCount, doc.RedoCount)
        same = bool(old and old[0] == doc and old[2] == history and len(old[1]) == len(state))
        if same:
            for a, b in zip(old[1], state):
                if a[:3] != b[:3] or a[4:] != b[4:]: same = False; break
                if (a[3] is None) != (b[3] is None): same = False; break
                if a[3] is not None and not a[3].isSame(b[3]): same = False; break
        if not same:
            self.serial += 1
            self.states[doc.Name] = (doc, state, history, self.session+':'+str(self.serial))
        return self.states[doc.Name][3]


class ModelAPI:
    def __init__(self, allow_changes=True):
        self.allow_changes = allow_changes
        self.revisions = Revisions()
        self.last_action = 'No requests yet'

    def controller(self):
        from ..gui.controller import instance
        return instance()

    def ensure_idle(self):
        c = self.controller()
        if c.tool or c.selection.widget is not None:
            raise ValueError('A manual SimpleCAD interaction is active. Finish it or press Esc before an AI edit.')
        if QtWidgets.QApplication.activeModalWidget() is not None:
            raise ValueError('Close the current FreeCAD dialog before an AI edit.')

    def document(self, name):
        doc = App.listDocuments().get(name)
        if doc is None: raise ValueError('That document is no longer open. List documents again.')
        return doc

    @staticmethod
    def object(doc, name):
        result = doc.getObject(name)
        if result is None: raise ValueError('Object '+name+' no longer exists. Inspect the document again.')
        return result

    def element(self, doc, name, element):
        owner = self.object(doc, name)
        if not hasattr(owner, 'Shape'): raise ValueError('This object has no Part geometry.')
        try: return owner, owner.Shape.getElement(element)
        except (RuntimeError, ValueError): raise ValueError('That element no longer exists. Inspect elements again.')

    def targets(self, doc, data):
        result = []
        for target in data:
            owner = self.object(doc, target['object'])
            names = tuple(target.get('elements', ()))
            for name in names:
                if name: self.element(doc, owner.Name, name)
            result.append((owner, () if '' in names else names))
        return result

    def stamp(self, doc, **data):
        return {'document': doc.Name, 'revision': self.revisions.get(doc), **data}

    def summary(self, owner, detail=False):
        view = owner.ViewObject
        result = {'name': owner.Name, 'label': owner.Label, 'type': owner.TypeId,
                  'visible': bool(view.Visibility) if view else False, 'locked': locking.whole(owner)}
        try: ops.editable(owner); result['editable'] = True
        except ValueError as error: result.update(editable=False, edit_note=str(error))
        if is_mesh(owner):
            result.update(mesh_triangles=owner.Mesh.CountFacets, mesh_points=owner.Mesh.CountPoints, conversion_available=True, mesh_split_available=True, mesh_closed=owner.Mesh.isSolid())
            result['mesh_region_available'] = not locking.whole(owner) and not owner.InList and not owner.ExpressionEngine
            result['mesh_stretch_available'] = not locking.whole(owner) and not owner.InList and not owner.ExpressionEngine
        if not hasattr(owner, 'Shape') or owner.Shape.isNull(): return result
        shape = owner.Shape
        protected, stale = locking.state(owner)
        result.update(locked_faces=['Face'+str(i) for i in sorted(protected)], lock_references_stale=stale)
        if locking.whole(owner) or stale: result.update(editable=False, edit_note='Unlock geometry before editing.')
        result.update(shape_type=shape.ShapeType, faces=len(shape.Faces), edges=len(shape.Edges), vertices=len(shape.Vertexes), solids=len(shape.Solids))
        if detail:
            box = shape.BoundBox
            result.update(valid=shape.isValid(), closed=shape.isClosed(), area=shape.Area,
                          appearance=appearance.describe(owner),
                          volume=sum(abs(s.Volume) for s in shape.Solids),
                          bounds={'min': [box.XMin,box.YMin,box.ZMin], 'max': [box.XMax,box.YMax,box.ZMax]},
                          placement={'translation': xyz(owner.Placement.Base), 'quaternion_xyzw': list(owner.Placement.Rotation.Q)},
                          hidden_faces=['Face'+str(i) for i in sorted(visibility.hidden_faces(owner))],
                          coordinate_system='World for plain objects; Shape coordinates for objects inside containers.')
        return result

    @staticmethod
    def element_maps(owner):
        """Adjacency, locks and colors read once for a whole inspection page."""
        shape = owner.Shape
        edges = {}
        for i, edge in enumerate(shape.Edges, 1):
            edges.setdefault(hash(edge), []).append((i, edge))
        face_edges, edge_faces = {}, {}
        for i, face in enumerate(shape.Faces, 1):
            for edge in face.Edges:
                for j, known in edges.get(hash(edge), ()):
                    if known.isSame(edge):
                        face_edges.setdefault(i, set()).add(j)
                        edge_faces.setdefault(j, set()).add(i)
        protected, stale = locking.state(owner)
        return {'shape': shape, 'face_edges': face_edges, 'edge_faces': edge_faces,
                'locked': (locking.whole(owner) or stale, protected),
                'appearance': appearance.describe_all(owner)[1]}

    def describe_element(self, owner, kind, index, shape, maps=None):
        if maps is None and kind != 'Vertex':
            maps = self.element_maps(owner)
        name = kind+str(index)
        result = {'name': name, 'visible': visibility.element_visible(owner, name)}
        if kind == 'Face':
            locked, protected = maps['locked']
            result['locked'] = locked or index in protected
            colors = maps['appearance']
            result.update(surface=type(shape.Surface).__name__, area=shape.Area, center=xyz(shape.CenterOfMass),
                          appearance=colors[index-1] if index <= len(colors) else None,
                          edges=['Edge'+str(i) for i in sorted(maps['face_edges'].get(index, ()))])
            try: result['normal'] = xyz(geo.face_normal(shape))
            except ValueError: pass
        elif kind == 'Edge':
            result.update(curve=type(shape.Curve).__name__, length=shape.Length,
                          midpoint=xyz(shape.valueAt(shape.getParameterByLength(shape.Length/2))),
                          endpoints=[xyz(v.Point) for v in shape.Vertexes],
                          faces=['Face'+str(i) for i in sorted(maps['edge_faces'].get(index, ()))],
                          seam=geo.is_seam_edge(maps['shape'], shape))
        else: result['point'] = xyz(shape.Point)
        return result

    def call(self, name, arguments):
        if QtCore.QThread.currentThread() != QtWidgets.QApplication.instance().thread():
            raise RuntimeError('Model access must run on the FreeCAD GUI thread.')
        tool = BY_NAME.get(name)
        if tool is None: raise ValueError('Unknown SimpleCAD tool.')
        validate(arguments, tool['inputSchema'])
        a = arguments
        doc = self.document(a['document']) if 'document' in a else None
        if name in MUTATIONS:
            if not self.allow_changes: raise ValueError('This connection is read-only. Enable Allow model changes in SimpleCAD’s AI connection panel.')
            self.ensure_idle()
        if 'expected_revision' in a:
            if a['expected_revision'] != self.revisions.get(doc):
                raise ValueError('The model changed since it was inspected. Inspect it again and use its new revision; do not reuse old face numbers.')
        operation = name.removeprefix('simplecad_')
        if doc and operation not in ('inspect_document','inspect_object','inspect_elements','measure','find_rounds','expand_selection','mesh_axis','inspect_mesh_triangles','inspect_mesh_region','get_selection','activate_document') and doc != App.ActiveDocument:
            raise ValueError('Activate this document first. AI edits never silently switch the current model.')
        # Native operations open their own single transaction. Refuse editing
        # when undo is disabled instead of making remote edits irreversible.
        if doc and name in MUTATIONS and operation not in ('activate_document','select') and not doc.UndoMode:
            raise ValueError('Enable Undo for this FreeCAD document before editing it through MCP.')
        self.last_action = operation.replace('_',' ')
        value = self.execute(operation, doc, a)
        if name in MUTATIONS:
            c = self.controller()
            c.seams.refresh(); c.faces.schedule()
        return value

    def surface(self, operation, doc, a):
        from ..surfaces import edit as surface_edit, operations as so
        if operation == 'pattern':
            objects = list(dict.fromkeys(self.object(doc, n) for n in a['objects']))
            path = None
            if 'path' in a:
                path = so.path_shape(self.targets(doc, [a['path']]))
            placements = so.placements(a['kind'], objects, path=path, count=a.get('count', 3),
                                       counts=a.get('counts'), spacing=a.get('spacing', (10.0, 0.0, 0.0)),
                                       axis=a.get('axis', (0, 0, 1)), center=a.get('center'),
                                       angle=a.get('angle', 360.0), align=a.get('align', True))
            copies = so.pattern(objects, placements)
            return self.stamp(doc, objects=[self.summary(o) for o in copies])
        owner = self.object(doc, a['object'])
        if operation == 'find_rounds':
            found = so.rounds(owner, a['max_radius'], a.get('convexity', 'any'), a.get('faces', ()))
            return self.stamp(doc, object=owner.Name, rounds=[{'face': 'Face%d' % (r['index'] + 1), 'radius': r['radius'],
                                                               'convex': r['convex']} for r in found])
        if operation == 'remove_rounds':
            report = so.remove_rounds(owner, a['max_radius'], a.get('convexity', 'any'), a.get('faces', ()), dialog=False)
        elif operation == 'heal_faces':
            report = so.heal_faces(owner, a['faces'], dialog=False)
        elif operation == 'draw_on_surface':
            shape = a['shape']
            outline = surface_edit.outline(shape, width=a.get('width', 10.0), height=a.get('height', 10.0),
                                           diameter=a.get('diameter', 10.0), sides=a.get('sides', 6),
                                           text=a.get('text', ''), size=a.get('size', 5.0),
                                           font=surface_edit.default_font())
            report = so.imprint(owner, a['faces'], outline, geo.V(*a['point']) if 'point' in a else None,
                                a.get('angle', 0.0), tuple(a.get('shift', (0.0, 0.0))), a.get('mode', 'imprint'),
                                a.get('depth', 0.0), dialog=False, wrap=a.get('wrap', False))
        elif operation == 'offset_faces':
            report = so.offset_faces(owner, a['faces'], a['distance'], dialog=False)
        elif operation == 'shell':
            if so.is_surface(owner):
                report = so.thicken(owner, a['thickness'], a.get('side', 'front'), dialog=False)
            else:
                report = so.shell(owner, a.get('faces', ()), a['thickness'], dialog=False)
        elif operation == 'draft_faces':
            report = so.draft(owner, a['faces'], a['angle'], a.get('axis', 'Z'), a.get('hinge', 'bottom'),
                              a.get('narrower', 'top'), dialog=False)
        elif operation == 'fill_holes':
            report = so.fill_holes(owner, a.get('edges', ()), a.get('smooth', True), dialog=False)
        else:
            flat, report = so.unwrap(owner, a['face'], dialog=False)
            return self.stamp(doc, object=self.summary(flat, True), report=report)
        return self.stamp(doc, object=self.summary(owner, True), report=report)

    def execute(self, operation, doc, a):
        if operation == 'list_documents':
            return {'active_document': App.ActiveDocument.Name if App.ActiveDocument else None,
                    'allow_changes': self.allow_changes, 'manual_tool': self.controller().tool,
                    'documents': [self.stamp(d, label=d.Label, objects=len(d.Objects), undo_count=d.UndoCount, redo_count=d.RedoCount)
                                  for d in App.listDocuments().values()]}
        if operation in ('inspect_mesh_triangles','inspect_mesh_region'):
            from ..mesh.region_edit import topology_for
            from ..mesh.region import RegionPlan, resolve
            owner = self.object(doc,a['object'])
            if not is_mesh(owner): raise ValueError('Select an STL mesh.')
            # Shared one-mesh cache, rebuilt after a geometry/placement change.
            # Status requests never build triangle adjacency.
            topology = topology_for(owner)
            offset,limit = a.get('offset',0),a.get('limit',50)
            if operation=='inspect_mesh_triangles':
                indices = range(offset,min(offset+limit,len(topology.triangles)))
                return self.stamp(doc,object=owner.Name,total=len(topology.triangles),offset=offset,
                    triangles=[{'triangle':i+1,'points':topology.points[topology.triangles[i]].tolist(),
                                'center':topology.centers[i].tolist(),'normal':topology.normals[i].tolist(),
                                'area':float(topology.areas[i]/2)} for i in indices])
            selected = resolve(topology,**{key:a[key] for key in ('triangles','seed_triangle','selection','crease','grow') if key in a})
            plan = RegionPlan(topology,selected,a.get('rings',1))
            return self.stamp(doc,object=owner.Name,region=plan.summary(),total=len(selected),offset=offset,
                              triangles=[i+1 for i in sorted(selected)[offset:offset+limit]])
        if operation in ('edit_mesh_region','mesh_region_status','finish_mesh_region','cancel_mesh_region'):
            from ..jobs import mesh as mesh_jobs
            if operation=='edit_mesh_region':
                values = {key:a[key] for key in ('triangles','seed_triangle','selection','crease','grow',
                          'mode','rings','delta','axis','angle','distance','pivot') if key in a}
                job = mesh_jobs.start_region(self.object(doc,a['object']),**values)
            else:
                job = mesh_jobs.get(doc,a['job_id'])
                if job.operation!='region': raise ValueError('This is not a mesh region job.')
                if operation=='finish_mesh_region':
                    result = job.apply()
                    return self.stamp(doc,**job.status(),object=self.summary(result,True))
                if operation=='cancel_mesh_region': job.cancel()
            return self.stamp(doc,**job.status())
        if operation == 'mesh_axis':
            from ..mesh import stretch as mesh_stretch
            owner = self.object(doc, a['object'])
            if not is_mesh(owner): raise ValueError('Select an STL mesh.')
            plane = mesh_stretch.control_plane(owner.Mesh, a.get('axis', 'Main'), a.get('rotation', (0,0,0)))
            span = plane.upper - plane.lower
            return self.stamp(doc, object=owner.Name, center=xyz(plane.center), normal=xyz(plane.normal),
                              minimum=plane.lower, maximum=plane.upper,
                              lower=plane.lower+span/3, upper=plane.upper-span/3)
        if operation in ('stretch_mesh','mesh_stretch_status','finish_mesh_stretch','cancel_mesh_stretch'):
            from ..jobs import mesh as mesh_jobs
            if operation == 'stretch_mesh':
                values = {key: a[key] for key in ('axis','rotation','lower','upper','distance','delta','reverse') if key in a}
                job = mesh_jobs.start_stretch(self.object(doc, a['object']), **values)
            else:
                job = mesh_jobs.get(doc, a['job_id'])
                if job.operation != 'stretch': raise ValueError('This is not a mesh stretch job.')
                if operation == 'finish_mesh_stretch':
                    result = job.apply()
                    return self.stamp(doc, **job.status(), object=self.summary(result, True))
                if operation == 'cancel_mesh_stretch': job.cancel()
            return self.stamp(doc, **job.status())
        if operation in ('split_mesh','mesh_split_status','finish_mesh_split','cancel_mesh_split'):
            from ..jobs import mesh as mesh_jobs
            if operation == 'split_mesh':
                job = mesh_jobs.start_split(self.object(doc,a['object']),a.get('axis','Main'),a.get('offset',0),a.get('gap',0),a.get('cap',True),glue=a.get('glue'))
            else:
                job = mesh_jobs.get(doc,a['job_id'])
                if job.operation != 'split': raise ValueError('This is not a mesh split job.')
                if operation == 'finish_mesh_split':
                    results = job.apply()
                    return self.stamp(doc, **job.status(), objects=[self.summary(obj,True) for obj in results])
                if operation == 'cancel_mesh_split': job.cancel()
            return self.stamp(doc, **job.status())
        if operation in ('convert_mesh', 'mesh_conversion_status', 'finish_mesh_conversion', 'cancel_mesh_conversion'):
            from ..jobs import mesh as mesh_jobs
            if operation == 'convert_mesh':
                job = mesh_jobs.start(self.object(doc, a['object']), a.get('tolerance', preferences.precision()), a.get('simplify', 0),
                                      a.get('surfaces', preferences.smooth_surfaces()))
            else:
                job = mesh_jobs.get(doc, a['job_id'])
                if job.operation != 'convert': raise ValueError('This is not a mesh conversion job.')
                if operation == 'finish_mesh_conversion':
                    result = job.apply()
                    return self.stamp(doc, **job.status(), object=self.summary(result, True))
                if operation == 'cancel_mesh_conversion':
                    job.cancel()
            return self.stamp(doc, **job.status())
        if operation == 'inspect_document':
            offset, limit = a.get('offset',0), a.get('limit',50)
            objects = doc.Objects
            return self.stamp(doc, label=doc.Label, objects=[self.summary(o) for o in objects[offset:offset+limit]],
                              total=len(objects), next_offset=offset+limit if offset+limit<len(objects) else None,
                              undo_count=doc.UndoCount, redo_count=doc.RedoCount)
        if operation == 'inspect_object': return self.stamp(doc, object=self.summary(self.object(doc,a['object']),True))
        if operation == 'measure':
            from ..inspection import measuring
            targets = []
            for key in ('first', 'second'):
                if key in a:
                    owner = self.object(doc, a[key]['object'])
                    if not hasattr(owner, 'Shape'): raise ValueError('This object has no Part geometry.')
                    try:
                        targets.append(measuring.resolve(owner.Shape, a[key]['element']))
                    except (IndexError, RuntimeError, Part.OCCError) as error:
                        raise ValueError('That element does not exist. Inspect the object again.') from error
            result = measuring.describe(targets[0]) if len(targets) == 1 else measuring.between(*targets)
            return self.stamp(doc, targets=[t.label for t in targets],
                              measurements=[{'name': row.name, 'unit': row.unit or None,
                                             'value': xyz(row.value) if isinstance(row.value, App.Vector) else row.value}
                                            for row in result.rows])
        if operation == 'inspect_elements':
            owner = self.object(doc, a['object'])
            if not hasattr(owner,'Shape'): raise ValueError('This object has no Part geometry.')
            kind = a['kind']; offset, limit = a.get('offset',0), a.get('limit',50)
            values = getattr(owner.Shape, {'Face':'Faces','Edge':'Edges','Vertex':'Vertexes'}[kind])
            maps = self.element_maps(owner) if kind != 'Vertex' else None
            return self.stamp(doc, object=owner.Name, kind=kind, total=len(values),
                              elements=[self.describe_element(owner,kind,i+1,values[i],maps) for i in range(offset,min(offset+limit,len(values)))],
                              next_offset=offset+limit if offset+limit<len(values) else None)
        if operation == 'get_selection':
            result = self.stamp(doc, targets=[{'object':s.ObjectName,'elements':list(s.SubElementNames)} for s in Gui.Selection.getSelectionEx(doc.Name)])
            # Region picking belongs to the preview, not Gui.Selection. Expose
            # that state too so a failed edit can be diagnosed without closing
            # the dialog or changing the user's selection.
            session = getattr(self.controller(), 'mesh_region_session', None)
            if session is not None and not session.closed and session.source.Document == doc:
                selected = sorted(session.selected)
                result['mesh_region'] = dict(object=session.source.Name,
                    triangles=[int(i)+1 for i in selected[:1000]], total=len(selected),
                    truncated=len(selected)>1000, parameters=session.values(),
                    validation_error=session.validation_error)
            return result
        if operation == 'expand_selection':
            from ..inspection import smart_select
            owner = self.object(doc, a['object'])
            if not hasattr(owner, 'Shape'): raise ValueError('This object has no Part geometry.')
            try:
                names, kind = smart_select.expand(owner.Shape, a['element'], a.get('mode', 'smart'))
            except (IndexError, RuntimeError, Part.OCCError) as error:
                raise ValueError('That element does not exist. Inspect the object again.') from error
            if a.get('select', True):
                if doc != App.ActiveDocument: raise ValueError('Activate this document first to select in it.')
                Gui.Selection.clearSelection(doc.Name)
                Gui.Selection.addSelection(owner, names, False)
            return self.stamp(doc, object=owner.Name, kind=kind, elements=names)
        if operation == 'select':
            targets = self.targets(doc,a['targets'])
            if not a.get('add',False): Gui.Selection.clearSelection(doc.Name)
            for owner,names in targets:
                for name in names or ('',): Gui.Selection.addSelection(owner,name)
            return self.execute('get_selection',doc,{})
        if operation == 'create_document':
            doc = App.newDocument('SimpleCADModel'); doc.Label = a['label']; doc.UndoMode=1
            return self.stamp(doc, label=doc.Label)
        if operation == 'activate_document':
            App.setActiveDocument(doc.Name)
            return self.stamp(doc, active=True)
        if operation in ('create_rectangle', 'create_circle', 'create_polygon', 'create_arc', 'create_2_point_arc') and 'surface_face' in a:
            from ..modeling import arcs
            from ..surfaces.drawing import SurfaceFrame
            if 'support' not in a:
                raise ValueError('A surface drawing needs its support object and surface_face.')
            support = self.object(doc, a['support'])
            _, face = self.element(doc, support.Name, a['surface_face'])
            anchor = geo.V(*a['start' if operation == 'create_2_point_arc' else 'origin'])
            frame = SurfaceFrame(face, anchor, geo.V(*a['x_direction']) if 'x_direction' in a else None)
            plane, origin = geo.Plane.named('XY'), geo.V()
            if operation == 'create_arc':
                curve = arcs.centered(origin, frame.local(geo.V(*a['start'])), plane.normal, a['sweep'])
                profile = frame.edge(curve.edge())
            elif operation == 'create_2_point_arc':
                curve = arcs.two_point(origin, frame.local(geo.V(*a['end'])), plane.normal, a['bulge'])
                profile = frame.edge(curve.edge())
            elif operation == 'create_rectangle':
                profile = frame.wire(geo.rectangle(plane, origin, geo.V(a['width'], a['height'], 0)))
            elif operation == 'create_circle':
                profile = frame.wire(geo.circle(plane, origin, a['radius']))
            else:
                angle = math.radians(a.get('angle', 0))
                vertex = geo.V(math.cos(angle), math.sin(angle), 0)*a['radius']
                if a['radius'] <= 0:
                    raise ValueError('Radius must be positive.')
                profile = frame.wire(geo.polygon(plane, origin, vertex, a['sides']))
            closed = operation not in ('create_arc', 'create_2_point_arc')
            result, divided = ops.draw_surface_curve(doc, profile, support, face, 'Surface drawing', closed=closed)
            return self.stamp(doc, object=self.summary(result, True), divided_face=divided)
        if operation in ('create_arc', 'create_2_point_arc'):
            from ..modeling import arcs
            normal = geo.V(*a.get('normal', [0,0,1]))
            start = geo.V(*a['start'])
            curve = (arcs.centered(geo.V(*a['origin']), start, normal, a['sweep']) if operation == 'create_arc'
                     else arcs.two_point(start, geo.V(*a['end']), normal, a['bulge']))
            support = self.object(doc,a['support']) if 'support' in a else None
            result, divided = ops.draw_arc(doc, curve.edge(), support)
            return self.stamp(doc, object=self.summary(result,True), divided_face=divided)
        if operation == 'create_sphere':
            result = ops.new_shape(doc, geo.sphere(geo.V(*a['origin']), a['radius']), 'Sphere')
            return self.stamp(doc, object=self.summary(result, True))
        if operation.startswith('create_') and operation != 'create_line':
            origin = geo.V(*a['origin']); normal = geo.V(*a.get('normal',[0,0,1]))
            plane = geo.Plane.from_normal(origin,normal)
            if 'x_direction' in a:
                direction = geo.V(*a['x_direction']); projected = direction-plane.normal*direction.dot(plane.normal)
                plane.u=geo.unit(projected); plane.v=plane.normal.cross(plane.u)
            support = self.object(doc,a['support']) if 'support' in a else None
            if operation == 'create_rectangle':
                profile = geo.rectangle(plane, origin, origin+plane.u*a['width']+plane.v*a['height'])
                result, divided = ops.draw_profile(doc,profile,support,'Rectangle')
            elif operation == 'create_circle':
                result, divided = ops.draw_circle(doc,geo.circle(plane,origin,a['radius']),support)
            else:
                if a['radius'] <= 0: raise ValueError('Radius must be positive.')
                angle=math.radians(a.get('angle',0))
                vertex=origin+a['radius']*(plane.u*math.cos(angle)+plane.v*math.sin(angle))
                result, divided=ops.draw_polygon(doc,geo.polygon(plane,origin,vertex,a['sides']),support)
            return self.stamp(doc, object=self.summary(result,True), divided_face=divided)
        if operation == 'create_line':
            support=self.object(doc,a['support']) if 'support' in a else None
            if 'surface_face' in a:
                if support is None:
                    raise ValueError('A surface line needs its support object and surface_face.')
                _,face=self.element(doc,support.Name,a['surface_face'])
                result, divided=ops.draw_surface_line(doc,geo.V(*a['start']),geo.V(*a['end']),support,face)
            else:
                result, divided=ops.draw_line(doc,geo.V(*a['start']),geo.V(*a['end']),support)
            return self.stamp(doc, object=self.summary(result,True), divided_face=divided)
        if operation == 'offset':
            normal=geo.V(*a['normal']) if 'normal' in a else None
            results=ops.offset(self.object(doc,a['object']),a['element'],a['distance'],normal)
            return self.stamp(doc,objects=[self.summary(obj,True) for obj in results])
        if operation == 'elongate':
            results=ops.elongate(self.object(doc,a['object']),a['element'],a['distance'],geo.V(*a['direction']),
                                 mode=a.get('mode','ellipse'),cut_hole=a.get('cut_hole',False),
                                 symmetric=a.get('symmetric',True))
            return self.stamp(doc,objects=[self.summary(obj,True) for obj in results])
        if operation == 'push_pull':
            owner, face=self.element(doc,a['object'],a['face'])
            results=ops.extrude(owner,face,a['distance'],return_pieces=True)
            return self.stamp(doc, object=self.summary(results[0],True),
                              objects=[self.summary(obj,True) for obj in results])
        if operation == 'move_vertex':
            result=ops.move_vertex(self.object(doc,a['object']),a['vertex'],geo.V(*a['delta']))
            return self.stamp(doc,object=self.summary(result,True))
        if operation in ('move','copy'):
            objects=list(dict.fromkeys(self.object(doc,n) for n in a['objects']))
            results=ops.transform(objects,geo.V(*a['delta']),copy=operation=='copy')
            return self.stamp(doc, objects=[self.summary(o,True) for o in results])
        if operation == 'mirror':
            objects=list(dict.fromkeys(self.object(doc,n) for n in a['objects']))
            results=ops.mirror(objects,a['axis'],copy=a.get('copy',True),through=a.get('through','Center'))
            return self.stamp(doc, objects=[self.summary(o,True) for o in results])
        if operation == 'rotate':
            elements = tuple(a.get('elements', ()))
            targets = ops.prepare_rotation([(self.object(doc, n), elements) for n in a['objects']])
            frames = rotation.frames([s for _, s in targets], a.get('axis', 'Z'), a.get('pivot', 'Selection'), targets=targets)
            changed = ops.commit_rotation(targets, frames, a['angle'], copy=a.get('copy', False))
            return self.stamp(doc, changed=changed, objects=[self.summary(o, True) for o, _ in targets])
        if operation == 'deform':
            from ..modeling import deformation as deform
            target=ops.prepare_deformation([(self.object(doc,a['object']),tuple(a.get('elements',())))],a.get('detail',6))
            owner,region,names=target
            if a['mode']=='Move':
                if 'delta' not in a:raise ValueError('Soft Move requires delta [dx,dy,dz].')
                center=geo.V(*a['center']) if 'center' in a else deform.default_center(region.shape,names)
                points,_=region.move(center,a.get('radius',region.size*.55),geo.V(*a['delta']))
            else:
                if 'angle' not in a:raise ValueError('Bend requires an angle in degrees.')
                origin,axis,toward,length=deform.bend_frame(region.shape,a.get('axis','Main'))
                toward=App.Rotation(axis,a.get('direction',0)).multVec(toward)
                points,_=region.bend(geo.V(*a['origin']) if 'origin' in a else origin,axis,toward,a.get('length',length),a['angle'])
            changed=ops.commit_deformation(target,points)
            return self.stamp(doc,changed=changed,object=self.summary(owner,True))
        if operation == 'scale':
            targets=ops.prepare_scaling([(self.object(doc,n),()) for n in a['objects']])
            changed=ops.scale_objects(targets,tuple(a['factors']),a.get('axes','World'),a.get('pivot','Selection'))
            return self.stamp(doc,changed=changed,objects=[self.summary(o,True) for o,_ in targets])
        if operation in ('loft','sweep'):
            mode=operation.title()
            refs=a['profiles'] if operation=='loft' else [a['profile'],a['path']]
            targets=ops.prepare_profiles(self.targets(doc,refs),mode)
            options={'solid':a.get('solid',True)}
            if operation=='loft':options['ruled']=a.get('ruled',False)
            else:options.update(align=a.get('align',True),frenet=a.get('frenet',False),transition=a.get('transition',0))
            result=ops.form_preview(targets,mode,**options)
            obj=ops.commit_form(targets,mode,result,a.get('hide_sources',True))
            return self.stamp(doc,object=self.summary(obj,True))
        if operation == 'round_edges':
            targets=ops.prepare_rounding(self.targets(doc,a['targets']))
            planned=ops.preview_rounding(targets,a['radius'])
            changed=ops.commit_rounding(targets,planned,a['radius'])
            return self.stamp(doc, changed=changed, objects=[self.summary(o,True) for o,_ in planned])
        if operation == 'subdivide':
            owner=self.object(doc,a['object']); target=ops.prepare_subdivision([(owner,(a['face'],))])
            rows,columns=a.get('rows',1),a.get('columns',1)
            pattern={'grid':'spaced','radial':'fan'}.get(a['pattern'],a['pattern'])
            planned,regions=ops.preview_subdivision(target,rows,columns,a.get('angle',0),pattern,a.get('divisions',3))
            changed=ops.commit_subdivision(target,planned,rows,columns,len(regions))
            return self.stamp(doc, changed=changed, regions=len(regions), object=self.summary(owner,True))
        if operation == 'slice':
            targets=ops.prepare_slicing([(self.object(doc,n),()) for n in a['objects']])
            if 'at_face' in a:
                _,face=self.element(doc,a['at_face']['object'],a['at_face']['face'])
                plane=slicing.cut_plane([s for _,s in targets],'Face',slicing.face_normal(face))
                offset=slicing.face_offset(plane,face)
            else:
                plane=slicing.cut_plane([s for _,s in targets],a.get('axis','Main'))
                offset=a.get('offset',0)
            cut=ops.preview_slicing(targets,plane,offset)
            if 'joint' in a: cut=ops.preview_stud_joints(cut,plane,offset,joints.StudJoint(**a['joint']).validate())
            planned=[(owner,slicing.separate(pieces,plane.normal,a.get('gap',0))) for owner,pieces in cut]
            results=ops.commit_slicing(targets,planned)
            return self.stamp(doc, objects=[self.summary(o,True) for o in results], normal=xyz(plane.normal), center=xyz(plane.center))
        if operation == 'fit_test':
            doc=ops.create_fit_test(joints.StudJoint(**a.get('joint',{})).validate())
            return self.stamp(doc, objects=[self.summary(o,True) for o in doc.Objects])
        if operation == 'intersect_faces':
            result=ops.intersect(self.targets(doc,a['targets']))
            return self.stamp(doc, object=self.summary(result,True))
        if operation == 'union':
            result=ops.unite([self.object(doc,n) for n in a['objects']])
            return self.stamp(doc, object=self.summary(result,True))
        if operation == 'heal':
            reports = ops.heal(doc, [self.object(doc, n) for n in a['objects']])
            return self.stamp(doc, reports=reports)
        if operation in ('find_rounds', 'remove_rounds', 'heal_faces', 'draw_on_surface', 'fill_holes',
                         'unwrap_face', 'pattern', 'offset_faces', 'shell', 'draft_faces'):
            return self.surface(operation, doc, a)
        if operation in ('delete','cleanup'):
            if operation=='delete':
                changed,ignored=ops.delete_selection(self.targets(doc,a['targets']))
                return self.stamp(doc, changed_objects=changed, ignored_seams=ignored)
            ops.cleanup(doc,[self.object(doc,n) for n in a['objects']])
            return self.stamp(doc, objects=[self.summary(o) for o in doc.Objects])
        if operation == 'set_appearance':
            targets = appearance.prepare(self.targets(doc,a['targets']))
            changed = appearance.commit(targets,a.get('color'),a.get('opacity'))
            for owner,_,_,_ in targets: Gui.Selection.removeSelection(owner)
            Gui.Selection.clearPreselection()
            return self.stamp(doc,changed=changed,objects=[self.summary(o,True) for o,_,_,_ in targets])
        if operation == 'set_locked':
            targets = self.targets(doc, a['targets'])
            locking.set_locked(targets, a['locked'])
            return self.stamp(doc, objects=[self.summary(o, True) for o in dict.fromkeys(o for o, _ in targets)])
        if operation == 'set_visibility':
            targets=self.targets(doc,a['targets']); parents={o.Name for o,names in targets if not names}
            for owner,names in targets:
                if names and owner.Name not in parents:
                    ops.editable(owner)
                    if any(not n.startswith('Face') for n in names): raise ValueError('Eye controls apply to faces or whole objects.')
            with ops.transaction(doc,'MCP visibility'):
                for owner,names in targets:
                    if not names: owner.ViewObject.Visibility=a['visible']
                    elif owner.Name not in parents:
                        hidden=visibility.hidden_faces(owner); indices={int(n[4:]) for n in names}
                        visibility.set_hidden(owner,hidden-indices if a['visible'] else hidden|indices)
                        if a['visible']: owner.ViewObject.Visibility=True
            # Remove cached selection overlays on changed objects.
            for owner,_ in targets: Gui.Selection.removeSelection(owner)
            Gui.Selection.clearPreselection()
            return self.stamp(doc, objects=[self.summary(o,True) for o in dict.fromkeys(o for o,_ in targets)])
        if operation in ('undo','redo'):
            count=doc.UndoCount if operation=='undo' else doc.RedoCount
            if not count: raise ValueError('There is no transaction to '+operation+'.')
            Gui.Selection.clearSelection(doc.Name); getattr(doc,operation)(); doc.recompute()
            return self.stamp(doc, undo_count=doc.UndoCount, redo_count=doc.RedoCount)
        if operation in ('get_settings','set_settings'):
            if operation=='set_settings':
                settings=replace(preferences.load(),**a['settings']); preferences.save(settings)
                self.controller().seams.configure(settings.show_seams)
                self.controller().viewport_style.configure(settings.viewport_style, preferences.color(settings.face_color))
            return {'settings':asdict(preferences.load())}
        if operation in ('view','capture_view'):
            if doc != App.ActiveDocument: raise ValueError('Activate this document before controlling its view.')
            view=Gui.activeDocument().activeView()
            if operation=='view':
                self.ensure_idle()
                if 'orientation' in a: getattr(view,'view'+{'Isometric':'Axonometric'}.get(a['orientation'],a['orientation']))()
                if a.get('fit',True): view.fitAll()
                return self.stamp(doc, view_direction=xyz(view.getViewDirection()))
            with tempfile.TemporaryDirectory(prefix='simplecad-view-') as directory:
                path=Path(directory)/'view.png'
                view.saveImage(str(path),a.get('width',1024),a.get('height',768),'Current')
                return {'content':[{'type':'image','mimeType':'image/png','data':base64.b64encode(path.read_bytes()).decode('ascii')},
                                   {'type':'text','text':'Viewport of '+doc.Name+'; revision '+self.revisions.get(doc)}]}
        raise ValueError('Tool is not implemented.')
