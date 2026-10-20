"""Cheap command availability, shared by toolbars, shortcuts and context menus.

FreeCAD polls IsActive repeatedly, including while a large imported model is
selected, so never walk a model's faces, its Mesh or face-lock matching here.
The one exception is a small selection (at most CLASSIFY_LIMIT subelements on
shapes of at most CLASSIFY_FACES faces): its faces, edges and vertices are
classified once as flat or curved, cached until that object's Shape changes,
so flat-only tools grey out on curved faces.
Operation-specific geometry validation still runs when a command is invoked.
"""
from dataclasses import dataclass, field
import sys
import time


DRAW = frozenset(('Line', 'Rectangle', 'Circle', 'Arc', 'Arc2Point', 'Polygon', 'Sphere'))
PICK = frozenset(('PushPull', 'Offset', 'Elongate', 'VertexMove', 'Measure'))
SMART = frozenset(('SmartSelect', 'SelectHole', 'SelectLoop', 'SelectFlat', 'SelectSmooth'))
SURFACE = frozenset(('Imprint', 'OffsetFace', 'Shell', 'Draft', 'HealFaces', 'RemoveRounds', 'FillHole', 'Unwrap'))
ALWAYS = DRAW | {'Select', 'Settings', 'MCP'}
CLASSIFY_LIMIT = 16  # larger selections stay unclassified; invoke-time checks still apply
# Each element lookup on a dense faceted shape rebuilds its index (about 40 ms
# per edge and 200 ms per vertex at 22,000 faces). Such shapes come from flat
# mesh conversion and have no curved faces, so they are not classified.
CLASSIFY_FACES = 2000

# Kinds of selected subelements. Faces: flat, cylinder, curved (any other
# surface, such as a fitted B-spline, sphere, cone or torus). Edges: straight,
# circular, freeform. Vertices: corner, or curved-corner when an adjoining edge
# or face is not straight/flat.
NOT_FLAT = frozenset(('cylinder', 'curved'))
FLAT_ONLY = {
    'PushPull': 'Push/Pull needs a flat face. Use Offset face (Surface) to push or pull curved faces.',
    'Subdivide': 'Subdivide needs a flat face. Curved faces cannot be subdivided yet.',
}
FLAT_OR_ROUND = {
    'Offset': 'Offset supports flat faces, cylinders, straight edges and arcs, not free-form curved faces or edges.',
    'Elongate': 'Elongate supports flat faces, cylinders and circular rims, not free-form curved faces or edges.',
    'Draft': 'Draft supports flat faces and cylinders, not free-form curved faces.',
}

REQUIREMENTS = {
    **{key: 'No selection needed; click in the view to draw.' for key in DRAW},
    'Select': 'Click geometry or drag a selection window in the view.',
    'Measure': 'Open a CAD model, then click geometry to measure; no preselection needed.',
    'PushPull': 'Click a flat CAD face after starting, or preselect one flat face.',
    'Offset': 'Click a flat CAD face or an edge after starting, or preselect one.',
    'Elongate': 'Click a CAD face or hole rim after starting, or preselect one.',
    'VertexMove': 'Click a CAD vertex after starting, or preselect one.',
    'Move': 'Select CAD objects, or start and click a CAD object in the view.',
    'Copy': 'Select CAD objects, or start and click a CAD object in the view.',
    'ConvertMesh': 'Select one STL mesh, or leave only one mesh visible with nothing selected.',
    'MeshSplit': 'Select one STL mesh, or leave only one mesh visible with nothing selected.',
    'MeshStretch': 'Select one STL mesh object first.',
    'MeshRegion': 'Select one STL mesh object, then click patches in the view to edit them.',
    'Analytic': 'Select circular edges, cylindrical faces, or one faceted CAD object. Convert a raw mesh to editable CAD first.',
    'Round': 'Select CAD edges, faces, or solid objects first.',
    'Subdivide': 'Select one flat CAD face, or a single-face object, first.',
    'Slice': 'Select CAD objects first. A selected STL mesh opens Split mesh.',
    'Intersect': 'Select crossing CAD faces or objects; selections must contain faces or whole objects.',
    'Union': 'Select the CAD objects to join. Solids inside one compound can also be joined.',
    'Rotate': 'Select CAD objects, faces, or edges first.',
    'Deform': 'Select a region or a whole object on exactly one CAD object first.',
    'Scale': 'Select the CAD objects to resize first.',
    'Loft': 'Select at least two CAD face or wire profiles in order.',
    'Sweep': 'Select a CAD face/wire profile first, then its edge or wire path.',
    'Mirror': 'Select the CAD objects to mirror first.',
    'Pattern': 'Select whole CAD objects to repeat; add an edge on another object to follow it as a path.',
    'Imprint': 'Select the CAD faces to draw on, all on one object; where you click centres the drawing.',
    'OffsetFace': 'Select the CAD faces to offset, all on one closed solid.',
    'Shell': 'Select one CAD solid, or the faces to leave open on it; or a surface object to thicken.',
    'Draft': 'Select the flat or round side faces to tilt, all on one closed solid.',
    'HealFaces': 'Select faces of one closed CAD solid to remove.',
    'RemoveRounds': 'Select one closed CAD solid, or some of its faces to search only those.',
    'FillHole': 'Select an open CAD surface object, or rim edges of the openings to fill.',
    'Unwrap': 'Select one CAD face to flatten.',
    'Curvature': 'Open a CAD model; selected objects, or all visible ones, are coloured. Click again to hide.',
    'Delete': 'Select CAD edges, faces, or whole objects. Individual vertices cannot be deleted.',
    **{key: 'Select CAD faces or edges first; raw STL triangles need conversion.' for key in SMART},
    'Isolate': 'Select objects to isolate. Click again to restore visibility, even with nothing selected.',
    'Appearance': 'Select CAD faces or whole CAD objects first.',
    'Cleanup': 'Select CAD objects, or clear the selection to clean up visible CAD objects.',
    'Heal': 'Select CAD objects to heal first.',
    'Settings': 'Configure SimpleCAD display, snapping and modeling precision.',
    'MCP': 'Start or stop the AI connection; no model or selection needed.',
}


@dataclass(frozen=True)
class Target:
    kind: str
    names: tuple = ()
    locked: bool = False
    surfaces: frozenset = frozenset()  # kinds of the selected subelements, when classified
    face_count: int = field(init=False)
    edge_count: int = field(init=False)

    def __post_init__(self):
        # Summarize a large region once, rather than walking its element names
        # separately for every toolbar button in every availability batch.
        object.__setattr__(self, 'face_count', sum(n.startswith('Face') for n in self.names))
        object.__setattr__(self, 'edge_count', sum(n.startswith('Edge') for n in self.names))


@dataclass(frozen=True)
class Context:
    document: bool = False
    selected: tuple = ()
    visible_cad: bool = False
    visible_meshes: int = 0
    isolated: bool = False
    curvature: bool = False  # the curvature map is shown on this document


def kind(obj):
    if obj.isDerivedFrom('Mesh::Feature'):
        return 'mesh'
    return 'cad' if 'Shape' in obj.PropertiesList else 'other'


def classify(shape, name):
    """Kind of one face, edge or vertex; None when it cannot be resolved."""
    import Part
    try:
        element = shape.getElement(name)
    except Exception:
        return None
    if name.startswith('Face'):
        surface = element.Surface
        if isinstance(surface, Part.Plane):
            return 'flat'
        return 'cylinder' if isinstance(surface, Part.Cylinder) else 'curved'
    if name.startswith('Edge'):
        curve = None if element.Degenerated else element.Curve
        if isinstance(curve, (Part.Line, Part.LineSegment)):
            return 'straight'
        return 'circular' if isinstance(curve, Part.Circle) else 'freeform'
    if name.startswith('Vertex'):
        edges = shape.ancestorsOfType(element, Part.Edge)
        faces = shape.ancestorsOfType(element, Part.Face)
        straight = all(not e.Degenerated and isinstance(e.Curve, (Part.Line, Part.LineSegment)) for e in edges)
        flat = all(isinstance(f.Surface, Part.Plane) for f in faces)
        return 'corner' if straight and flat else 'curved-corner'
    return None


_kinds = {}


def surface_kinds(doc, obj, names):
    """Kinds of a few selected subelements, cached while the Shape is the same."""
    shape = obj.Shape
    key = (doc.Name, obj.Name)
    cached = _kinds.get(key)
    if cached is None or not cached[0].isSame(shape):
        cached = _kinds[key] = (shape, {} if shape.countElement('Face') <= CLASSIFY_FACES else None)
        # Keep the cache to recently selected objects, not every object ever picked.
        for old in list(_kinds)[:-8]:
            del _kinds[old]
    kinds = cached[1]
    if kinds is None:
        return frozenset()
    for name in names:
        if name not in kinds:
            kinds[name] = classify(shape, name)
    return frozenset(kinds[name] for name in names) - {None}


def capture():
    import FreeCAD as App
    import FreeCADGui as Gui
    doc = App.ActiveDocument
    if doc is None:
        return Context()
    # Merge duplicate SelectionEx entries without resolving any subshapes.
    picked, owners = {}, {}
    for item in Gui.Selection.getSelectionEx():
        obj = item.Object
        if obj is None or obj.Document != doc:
            continue
        names = tuple(item.SubElementNames)
        prior = picked.get(obj.Name)
        if prior is not None:
            names = tuple(dict.fromkeys(prior.names + names)) if prior.names and names else ()
        picked[obj.Name] = Target(kind(obj), names, bool(getattr(obj, 'SC_Locked', False)))
        owners[obj.Name] = obj
    if sum(len(t.names) for t in picked.values()) <= CLASSIFY_LIMIT:
        for name, target in picked.items():
            if target.kind == 'cad' and target.names:
                try:
                    kinds = surface_kinds(doc, owners[name], target.names)
                except Exception:
                    continue  # Unknown kinds leave the tool to its own checks.
                picked[name] = Target(target.kind, target.names, target.locked, kinds)
    cad, meshes = False, 0
    for obj in doc.Objects:
        if obj.ViewObject is None or not obj.ViewObject.Visibility:
            continue
        obj_kind = kind(obj)
        cad |= obj_kind == 'cad'
        meshes += obj_kind == 'mesh'
    module = sys.modules.get('simplecad.gui.tools.smart_select')
    isolated = module is not None and doc.Name in module._isolated
    module = sys.modules.get('simplecad.gui.tools.curvature')
    curvature = module is not None and doc.Name in module._shown
    return Context(True, tuple(picked.values()), cad, meshes, isolated, curvature)


_cached = None
_expires = 0


def current(fresh=False):
    """One lightweight snapshot for a batch of IsActive polls, not per button.

    Clicks and context menus always ask for a fresh snapshot. The short cache
    also expires after document/visibility/lock changes without extra observers.
    """
    global _cached, _expires
    now = time.monotonic()
    if fresh or _cached is None or now >= _expires:
        try:
            _cached = capture()
        except (ReferenceError, RuntimeError):
            # A native polling callback can coincide with closing a document.
            _cached = Context()
        _expires = now + .1
    return _cached


def surface_reason(key, selected):
    """Why a flat-only tool cannot use the selected curved geometry, or ''."""
    kinds = frozenset().union(*(t.surfaces for t in selected))
    if not kinds:
        return ''
    if key in FLAT_ONLY and kinds & NOT_FLAT:
        return FLAT_ONLY[key]
    if key in FLAT_OR_ROUND and kinds & {'curved', 'freeform'}:
        return FLAT_OR_ROUND[key]
    if key == 'VertexMove' and 'curved-corner' in kinds:
        return 'Move Vertex needs a corner between flat faces and straight edges, not a curved one.'
    if key == 'SelectHole' and 'curved' in kinds:
        return 'Select hole needs a cylinder, a faceted hole wall or a rim edge, not a free-form curved face.'
    if key == 'SelectFlat' and kinds <= NOT_FLAT:
        return 'Select flat region needs a flat face or an edge; use Select smooth surface for curved faces.'
    return ''


def reason(key, context=None):
    """Empty string means available; otherwise explain the missing requirement."""
    if key in ALWAYS:
        return ''
    c = current() if context is None else context
    if not c.document:
        return 'Open a model first.'
    selected = c.selected
    cad = bool(selected) and all(t.kind == 'cad' for t in selected)
    curved = surface_reason(key, selected) if cad else ''
    if curved:
        return curved
    if key == 'Isolate':
        return '' if selected or c.isolated else 'Select objects to isolate first.'
    if key == 'Curvature':
        return '' if c.curvature or cad or not selected and c.visible_cad else REQUIREMENTS[key]
    if key in PICK:
        return '' if c.visible_cad or cad else 'This tool needs CAD geometry. Use Make mesh editable for a raw STL.'
    if key in ('ConvertMesh', 'MeshSplit', 'MeshStretch', 'MeshRegion'):
        valid = len(selected) == 1 and selected[0].kind == 'mesh'
        if key not in ('MeshStretch','MeshRegion') and not selected:
            valid = c.visible_meshes == 1
        if not valid:
            return REQUIREMENTS[key]
        if key != 'ConvertMesh' and any(t.locked for t in selected):
            return 'Unlock the mesh before editing it.'
        return ''
    if key == 'Slice' and len(selected) == 1 and selected[0].kind == 'mesh':
        return reason('MeshSplit', c)
    if key in ('Move', 'Copy') and not selected:
        return '' if c.visible_cad else 'Open a CAD model, then select or click an object.'
    if key == 'Cleanup' and not selected:
        return '' if c.visible_cad else 'Open a model containing editable CAD objects.'
    if not cad:
        return REQUIREMENTS.get(key, 'Select CAD geometry first.')
    count = sum(len(t.names) for t in selected)
    faces = sum(t.face_count for t in selected)
    edges = sum(t.edge_count for t in selected)
    faces_edges = count == faces + edges
    if key in SMART:
        return '' if count and faces_edges else REQUIREMENTS[key]
    if key == 'Appearance':
        return '' if count == faces else REQUIREMENTS[key]
    if key == 'Pattern':
        whole = [t for t in selected if not t.names]
        return '' if whole and all(t.edge_count == len(t.names) for t in selected) else REQUIREMENTS[key]
    if key not in ('Copy', 'Mirror', 'Analytic', 'Loft', 'Sweep', 'Unwrap') and any(t.locked for t in selected):
        return 'Unlock the selected object before editing it.'
    if key == 'Subdivide' and (len(selected) != 1 or count and (count != 1 or faces != 1)):
        return REQUIREMENTS[key]
    if key in ('Deform', 'Analytic') and len(selected) != 1:
        return REQUIREMENTS[key]
    if key in SURFACE:
        one = len(selected) == 1
        valid = {'Imprint': one and count and count == faces, 'HealFaces': one and count and count == faces,
                 'OffsetFace': one and count and count == faces, 'Draft': one and count and count == faces,
                 'Shell': one and count == faces,
                 'RemoveRounds': one and count == faces, 'FillHole': one and count == edges,
                 'Unwrap': one and count == faces == 1}[key]
        return '' if valid else REQUIREMENTS[key]
    if key in ('Delete', 'Round', 'Analytic') and not faces_edges:
        return REQUIREMENTS[key]
    if key == 'Intersect' and count != faces:
        return REQUIREMENTS[key]
    if key in ('Loft', 'Sweep'):
        # Connected edges on one owner form ONE profile/path. Faces are
        # separate profiles, even when selected on the same object.
        profiles = sum(t.face_count or 1 for t in selected)
        mixed = any(t.face_count and t.edge_count for t in selected)
        if not faces_edges or mixed or not (2 <= profiles <= 32 if key == 'Loft' else profiles == 2):
            return REQUIREMENTS[key]
    return '' if key in REQUIREMENTS else 'Unknown SimpleCAD command.'


def context_groups(context=None):
    """Relevant entries, including disabled neighbors with explanatory tooltips."""
    c = current(fresh=True) if context is None else context
    if not c.selected:
        return [('Draw', ('Line', 'Rectangle', 'Circle', 'Arc', 'Arc2Point', 'Polygon', 'Sphere')),
                ('Inspect', ('Select', 'Measure', 'Curvature', 'Isolate'))]
    if all(t.kind == 'mesh' for t in c.selected):
        return [('Mesh', ('ConvertMesh', 'MeshSplit', 'MeshStretch', 'MeshRegion')),
                ('Inspect', ('Isolate',))]
    if not all(t.kind == 'cad' for t in c.selected):
        return [('Inspect', ('Isolate',))]
    names = [name for target in c.selected for name in target.names]
    modify = ['Move', 'Rotate', 'Copy', 'Pattern', 'Mirror', 'Scale']
    inspect = ['Measure', 'Curvature', 'Isolate']
    surface = ['Shell', 'RemoveRounds', 'FillHole']
    if names and all(n.startswith('Vertex') for n in names):
        modify = ['VertexMove', 'Deform'] + modify
        surface = []
    else:
        if any(n.startswith('Face') for n in names):
            modify = ['PushPull', 'Offset', 'Elongate', 'Subdivide', 'Deform'] + modify
            surface = ['Imprint', 'OffsetFace', 'Shell', 'Draft', 'HealFaces', 'RemoveRounds', 'Unwrap', 'FillHole']
        elif names:
            modify = ['Offset', 'Elongate'] + modify
            surface = ['FillHole']
        modify += ['Analytic', 'Round', 'Slice', 'Intersect', 'Union', 'Loft', 'Sweep', 'Appearance', 'Delete']
        if names:
            inspect = ['SelectHole', 'SelectLoop', 'SelectFlat', 'SelectSmooth'] + inspect
    return [('Modify', tuple(modify))] + ([('Surface', tuple(surface))] if surface else []) + [('Inspect', tuple(inspect))]
