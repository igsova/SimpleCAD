"""Availability must be useful without querying a model's thousands of faces."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from simplecad.gui import command_state as state
from simplecad.gui.command_state import Context, Target, reason


def selected(*targets, **values):
    return Context(document=True, selected=targets, **values)


class AvailabilityTests(unittest.TestCase):
    def test_new_document_workflow_remains_available(self):
        for key in state.ALWAYS:
            with self.subTest(key=key):
                self.assertFalse(reason(key, Context()))
        for key in set(state.REQUIREMENTS) - state.ALWAYS:
            with self.subTest(key=key):
                self.assertTrue(reason(key, Context()))

    def test_interactive_tools_do_not_require_preselection(self):
        context = Context(document=True, visible_cad=True)
        for key in state.PICK | {'Move', 'Copy'}:
            self.assertFalse(reason(key, context), key)
        for key in ('Round', 'Subdivide', 'Deform', 'Loft', 'Sweep', 'Delete', 'Scale'):
            self.assertTrue(reason(key, context), key)

    def test_raw_mesh_and_cad_are_not_confused(self):
        mesh = selected(Target('mesh'))
        cad = selected(Target('cad'))
        for key in ('ConvertMesh', 'MeshSplit', 'MeshStretch', 'MeshRegion'):
            self.assertFalse(reason(key, mesh))
            self.assertTrue(reason(key, cad))
        for key in ('Analytic', 'Delete', 'Scale', 'Move', 'PushPull', 'Round'):
            self.assertTrue(reason(key, mesh), key)
        self.assertFalse(reason('Slice', mesh))  # Existing shortcut dispatches to mesh split.
        self.assertFalse(reason('Analytic', cad))

    def test_mesh_fallback_and_ambiguous_selection(self):
        context = Context(document=True, visible_meshes=1)
        for key in ('ConvertMesh', 'MeshSplit'):
            self.assertFalse(reason(key, context))
            self.assertTrue(reason(key, Context(document=True, visible_meshes=2)))
            self.assertTrue(reason(key, selected(Target('mesh'), Target('cad'))))
            self.assertTrue(reason(key, selected(Target('mesh'), Target('mesh'))))
        for key in ('MeshStretch','MeshRegion'):
            self.assertTrue(reason(key, context))  # These dialogs require an explicit source.

    def test_wrong_subelements_and_single_face_operations(self):
        vertex = selected(Target('cad', ('Vertex1',)))
        edge = selected(Target('cad', ('Edge1',)))
        face = selected(Target('cad', ('Face1',)))
        two_faces = selected(Target('cad', ('Face1', 'Face2')))
        for key in ('Delete', 'Round', 'Appearance', 'Analytic', 'SmartSelect', 'Intersect'):
            self.assertTrue(reason(key, vertex), key)
        self.assertFalse(reason('Delete', edge))
        self.assertTrue(reason('Appearance', edge))
        self.assertFalse(reason('Appearance', face))
        self.assertFalse(reason('Subdivide', face))
        self.assertTrue(reason('Subdivide', edge))
        self.assertTrue(reason('Subdivide', two_faces))
        self.assertFalse(reason('Deform', two_faces))
        self.assertTrue(reason('Deform', selected(Target('cad'), Target('cad'))))

    def test_profile_count_matches_operation_semantics(self):
        loop = Target('cad', ('Edge1', 'Edge2', 'Edge3'))
        face = Target('cad', ('Face1',))
        for key in ('Loft', 'Sweep'):
            self.assertTrue(reason(key, selected(loop)))
            self.assertFalse(reason(key, selected(face, loop)))
            self.assertFalse(reason(key, selected(Target('cad', ('Face1', 'Face2')))))
            self.assertTrue(reason(key, selected(Target('cad', ('Face1', 'Edge1')))))
        self.assertTrue(reason('Sweep', selected(face, face, face)))
        self.assertFalse(reason('Loft', selected(face, face, face)))

    def test_locks_and_isolation_escape_route(self):
        locked = selected(Target('cad', locked=True))
        for key in ('Delete', 'Move', 'Rotate', 'Scale', 'Heal'):
            self.assertTrue(reason(key, locked), key)
        for key in ('Copy', 'Appearance', 'Measure', 'Isolate'):
            self.assertFalse(reason(key, locked), key)
        for key in ('MeshStretch','MeshRegion'):
            self.assertTrue(reason(key, selected(Target('mesh', locked=True))))
        self.assertTrue(reason('Isolate', Context(document=True)))
        self.assertFalse(reason('Isolate', Context(document=True, isolated=True)))

    def test_surface_tools_follow_their_selection(self):
        whole = selected(Target('cad'))
        faces = selected(Target('cad', ('Face1', 'Face2')))
        face = selected(Target('cad', ('Face1',)))
        edges = selected(Target('cad', ('Edge1', 'Edge2')))
        two_objects = selected(Target('cad', ('Face1',)), Target('cad', ('Face1',)))
        for key in ('Imprint', 'HealFaces', 'OffsetFace', 'Draft'):
            self.assertFalse(reason(key, faces), key)
            self.assertTrue(reason(key, whole), key)
            self.assertTrue(reason(key, edges), key)
            self.assertTrue(reason(key, two_objects), key)
        self.assertFalse(reason('RemoveRounds', whole))
        self.assertFalse(reason('RemoveRounds', faces))
        self.assertTrue(reason('RemoveRounds', edges))
        self.assertFalse(reason('FillHole', whole))
        self.assertFalse(reason('FillHole', edges))
        self.assertTrue(reason('FillHole', faces))
        self.assertFalse(reason('Unwrap', face))
        self.assertTrue(reason('Unwrap', faces))
        # Shell hollows a whole solid, optionally opening faces, or thickens a surface object.
        self.assertFalse(reason('Shell', whole))
        self.assertFalse(reason('Shell', faces))
        self.assertTrue(reason('Shell', edges))
        self.assertTrue(reason('Shell', two_objects))
        self.assertTrue(reason('Shell', selected(Target('cad', ('Face1',), locked=True))))
        self.assertFalse(reason('Pattern', whole))
        self.assertFalse(reason('Pattern', selected(Target('cad'), Target('cad', ('Edge3',)))))
        self.assertTrue(reason('Pattern', edges))
        self.assertTrue(reason('Pattern', selected(Target('cad'), Target('cad', ('Face3',)))))
        for key in ('Imprint', 'OffsetFace', 'Shell', 'Draft', 'HealFaces', 'RemoveRounds', 'FillHole', 'Unwrap',
                    'Pattern'):
            self.assertTrue(reason(key, selected(Target('mesh'))), key)
        # Copies and a flat outline leave a locked source as it is.
        self.assertFalse(reason('Unwrap', selected(Target('cad', ('Face1',), locked=True))))
        self.assertFalse(reason('Pattern', selected(Target('cad', locked=True))))
        self.assertTrue(reason('HealFaces', selected(Target('cad', ('Face1',), locked=True))))
        # Curved faces are what these tools are for.
        curved = selected(Target('cad', ('Face1',), surfaces=frozenset({'curved'})))
        for key in ('Imprint', 'OffsetFace', 'Shell', 'HealFaces', 'RemoveRounds', 'Unwrap'):
            self.assertFalse(reason(key, curved), key)
        # Draft tilts flat and round walls; Push/Pull points curved faces to Offset face.
        self.assertIn('free-form', reason('Draft', curved))
        self.assertFalse(reason('Draft', selected(Target('cad', ('Face1',), surfaces=frozenset({'cylinder'})))))
        self.assertIn('Offset face', reason('PushPull', curved))

    def test_curvature_map_toggles(self):
        self.assertTrue(reason('Curvature', Context(document=True)))
        self.assertFalse(reason('Curvature', Context(document=True, visible_cad=True)))
        self.assertFalse(reason('Curvature', selected(Target('cad'))))
        self.assertTrue(reason('Curvature', selected(Target('mesh'), visible_cad=True)))
        self.assertFalse(reason('Curvature', Context(document=True, curvature=True)))

    def test_context_menu_follows_selection_type(self):
        def entries(context):
            return {key for _, keys in state.context_groups(context) for key in keys}
        mesh = entries(selected(Target('mesh')))
        self.assertTrue({'ConvertMesh', 'MeshSplit', 'MeshStretch', 'MeshRegion', 'Isolate'} <= mesh)
        self.assertNotIn('PushPull', mesh)
        face = entries(selected(Target('cad', ('Face1',))))
        self.assertTrue({'PushPull', 'Subdivide', 'Analytic', 'SelectFlat', 'Appearance'} <= face)
        self.assertNotIn('MeshStretch', face)
        vertex = entries(selected(Target('cad', ('Vertex1',))))
        self.assertIn('VertexMove', vertex)
        self.assertNotIn('Delete', vertex)
        self.assertTrue({'Imprint', 'OffsetFace', 'Shell', 'Draft', 'HealFaces', 'RemoveRounds', 'Unwrap', 'FillHole',
                         'Curvature'} <= face)
        self.assertIn('Shell', entries(selected(Target('cad'))))
        self.assertNotIn('OffsetFace', entries(selected(Target('cad'))))
        self.assertTrue({'FillHole', 'Pattern'} <= entries(selected(Target('cad', ('Edge1',)))))
        self.assertNotIn('Imprint', entries(selected(Target('cad'))))
        self.assertNotIn('Imprint', vertex)

    def test_polling_does_not_inspect_geometry(self):
        class Object:
            def __init__(self, name, kind, visible=True):
                self.Name = name
                self.kind = kind
                self.PropertiesList = ['Shape'] if kind == 'cad' else ['Mesh']
                self.ViewObject = SimpleNamespace(Visibility=visible)
                self.Document = doc

            def isDerivedFrom(self, name):
                return self.kind == 'mesh' and name == 'Mesh::Feature'

            @property
            def Shape(self):
                raise AssertionError('Availability inspected a Shape')

            @property
            def Mesh(self):
                raise AssertionError('Availability inspected a Mesh')

        doc = SimpleNamespace(Name='Test')
        cad = Object('CAD', 'cad')
        mesh = Object('STL', 'mesh')
        doc.Objects = [cad, mesh]
        # A large selection should be gathered only once per polling batch.
        selection = Mock(return_value=[SimpleNamespace(Object=cad, SubElementNames=tuple(
            'Face%d' % i for i in range(1, 13001)))])
        gui = SimpleNamespace(Selection=SimpleNamespace(getSelectionEx=selection))
        with patch.dict(sys.modules, {'FreeCAD': SimpleNamespace(ActiveDocument=doc), 'FreeCADGui': gui}), \
                patch.object(state.time, 'monotonic', return_value=100), \
                patch.object(state, '_cached', None):
            snapshot = state.current(fresh=True)
            self.assertTrue(snapshot.visible_cad)
            self.assertEqual(snapshot.visible_meshes, 1)
            for key in state.REQUIREMENTS:
                reason(key)
            self.assertEqual(selection.call_count, 1)
            selection.return_value = []
            self.assertFalse(state.current(fresh=True).selected)


class CurvedSurfaceTests(unittest.TestCase):
    def test_flat_only_tools_grey_out_on_curved_faces(self):
        def face(*kinds):
            return selected(Target('cad', ('Face1',), surfaces=frozenset(kinds)))
        flat, cylinder, curved = face('flat'), face('cylinder'), face('curved')
        for key in ('PushPull', 'Subdivide', 'Offset', 'Elongate', 'SelectHole', 'SelectFlat'):
            self.assertFalse(reason(key, flat), key)
        for key in ('PushPull', 'Subdivide'):
            self.assertIn('flat face', reason(key, cylinder))
            self.assertIn('flat face', reason(key, curved))
            self.assertTrue(reason(key, face('flat', 'curved')), key)
        for key in ('Offset', 'Elongate', 'SelectHole'):
            self.assertFalse(reason(key, cylinder), key)
            self.assertIn('curved', reason(key, curved))
        self.assertTrue(reason('SelectFlat', curved))
        self.assertFalse(reason('SelectFlat', face('curved', 'straight')))  # An edge still seeds a flat face.
        # Tools that handle any surface stay available on curved faces.
        for key in ('SmartSelect', 'SelectSmooth', 'SelectLoop', 'Round', 'Deform', 'Analytic',
                    'Appearance', 'Delete', 'Intersect', 'Rotate', 'Measure', 'Slice'):
            self.assertFalse(reason(key, curved), key)
        self.assertTrue(reason('Offset', selected(Target('cad', ('Edge1',), surfaces=frozenset({'freeform'})))))
        self.assertFalse(reason('Offset', selected(Target('cad', ('Edge1',), surfaces=frozenset({'circular'})))))
        corner = Target('cad', ('Vertex1',), surfaces=frozenset({'curved-corner'}))
        self.assertTrue(reason('VertexMove', selected(corner)))
        self.assertFalse(reason('VertexMove', selected(Target('cad', ('Vertex1',), surfaces=frozenset({'corner'})))))

    def test_unclassified_selection_keeps_invoke_time_checks(self):
        self.assertFalse(reason('PushPull', selected(Target('cad', ('Face1',)))))

    def test_small_selection_is_classified_once_per_shape(self):
        class Surface: pass
        class Plane(Surface): pass
        class Cylinder(Surface): pass
        class BSplineSurface(Surface): pass
        part = SimpleNamespace(Plane=Plane, Cylinder=Cylinder, Line=type('Line', (), {}),
                               LineSegment=type('LineSegment', (), {}), Circle=type('Circle', (), {}),
                               Edge=object(), Face=object())

        class Shape:
            def __init__(self, surfaces):
                self.surfaces = surfaces
                self.lookups = 0

            def isSame(self, other):
                return other is self

            def countElement(self, kind):
                return len(self.surfaces)

            def getElement(self, name):
                self.lookups += 1
                return SimpleNamespace(Surface=self.surfaces[name]())

        class Object:
            Name = 'Hood'
            PropertiesList = ['Shape']
            ViewObject = SimpleNamespace(Visibility=True)

            def __init__(self, shape):
                self.shape = shape
                self.reads = 0
                self.Document = doc

            def isDerivedFrom(self, name):
                return False

            @property
            def Shape(self):
                self.reads += 1
                return self.shape

        doc = SimpleNamespace(Name='Test')
        shape = Shape({'Face1': BSplineSurface, 'Face2': Plane})
        obj = Object(shape)
        doc.Objects = [obj]
        selection = Mock(return_value=[SimpleNamespace(Object=obj, SubElementNames=('Face1',))])
        gui = SimpleNamespace(Selection=SimpleNamespace(getSelectionEx=selection))
        with patch.dict(sys.modules, {'FreeCAD': SimpleNamespace(ActiveDocument=doc), 'FreeCADGui': gui,
                                      'Part': part}), patch.object(state, '_kinds', {}):
            for _ in range(3):
                snapshot = state.current(fresh=True)
            self.assertEqual(snapshot.selected[0].surfaces, {'curved'})
            self.assertTrue(reason('PushPull', snapshot))
            self.assertEqual(shape.lookups, 1)  # Polling reuses the classification.
            selection.return_value = [SimpleNamespace(Object=obj, SubElementNames=('Face2',))]
            self.assertFalse(reason('PushPull', state.current(fresh=True)))
            # An edit replaces the Shape; the same face name is classified again.
            obj.shape = Shape({'Face1': Plane})
            selection.return_value = [SimpleNamespace(Object=obj, SubElementNames=('Face1',))]
            self.assertFalse(reason('PushPull', state.current(fresh=True)))
            self.assertEqual(obj.shape.lookups, 1)
            # A large selection is never classified, so polling never reads the Shape.
            reads = obj.reads
            selection.return_value = [SimpleNamespace(Object=obj, SubElementNames=tuple(
                'Face%d' % i for i in range(1, state.CLASSIFY_LIMIT + 2)))]
            self.assertFalse(state.current(fresh=True).selected[0].surfaces)
            self.assertEqual(obj.reads, reads)
            # A dense faceted shape is not classified element by element.
            obj.shape = Shape({'Face1': BSplineSurface})
            selection.return_value = [SimpleNamespace(Object=obj, SubElementNames=('Face1',))]
            with patch.object(state, 'CLASSIFY_FACES', 0):
                self.assertFalse(reason('PushPull', state.current(fresh=True)))
            self.assertEqual(obj.shape.lookups, 0)


class CommandRegistrationTests(unittest.TestCase):
    def test_inventory_grouping_and_help(self):
        gui = SimpleNamespace(addCommand=Mock())
        path = Path(__file__).resolve().parents[2] / 'simplecad/gui/commands.py'
        spec = importlib.util.spec_from_file_location('simplecad.gui._command_test', path)
        commands = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'FreeCADGui': gui}):
            spec.loader.exec_module(commands)
            toolbar_names = commands.register()
        self.assertEqual(commands.GROUPS[-1][0], 'Mesh')
        self.assertEqual(len(toolbar_names), len(set(toolbar_names)))
        registered = {call.args[0]: call.args[1] for call in gui.addCommand.call_args_list}
        self.assertTrue(set(toolbar_names) <= registered.keys())
        self.assertTrue({'SimpleCAD_' + key for key, _, _ in commands.TOOLS} <= set(toolbar_names))
        for key, command in registered.items():
            resources = command.GetResources()
            self.assertTrue(resources['ToolTip'])
            if 'Pixmap' in resources:
                self.assertTrue(Path(resources['Pixmap']).is_file(), key)
            with patch.object(state, 'current', return_value=Context()):
                self.assertEqual(command.IsActive(), key[10:] in state.ALWAYS, key)
        for key in dict(commands.GROUPS)['Mesh']:
            resources = registered['SimpleCAD_' + key].GetResources()
            self.assertIn('#62d26f', Path(resources['Pixmap']).read_text())


if __name__ == '__main__':
    unittest.main()
