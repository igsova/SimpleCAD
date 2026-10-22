"""Tests for Elongate: stretch circular holes and faces into ellipses or slots."""
import unittest
import FreeCAD as App
import Part
from simplecad.core import geometry as g
from simplecad.document import operations as ops
from simplecad.modeling.elongating import ElongateProfile
from simplecad.mcp.api import ModelAPI
V = App.Vector


class ElongateTests(unittest.TestCase):
    def doc(self):
        doc = App.newDocument('ElongateTest')
        doc.UndoMode = 1
        name = doc.Name
        self.addCleanup(lambda: App.closeDocument(name) if name in App.listDocuments() else None)
        return doc

    def test_circle_edge_ellipse_geometry(self):
        circle_edge = Part.makeCircle(10)
        profile = ElongateProfile(circle_edge)
        self.assertTrue(profile.is_circle)
        self.assertAlmostEqual(profile.radius, 10.0)

        # Elongate by +5 along X
        ellipse_edge = profile.elongate(5.0, V(1, 0, 0), mode='ellipse')
        self.assertTrue(ellipse_edge.isValid())
        self.assertIsInstance(ellipse_edge.Curve, Part.Ellipse)
        self.assertAlmostEqual(ellipse_edge.Curve.MajorRadius, 15.0)
        self.assertAlmostEqual(ellipse_edge.Curve.MinorRadius, 10.0)
        self.assertAlmostEqual(ellipse_edge.Curve.Center.x, 0.0)
        self.assertAlmostEqual(ellipse_edge.Curve.Center.y, 0.0)

        # Elongate by +8 along Y
        ellipse_y = profile.elongate(8.0, V(0, 1, 0), mode='ellipse')
        self.assertTrue(ellipse_y.isValid())
        self.assertAlmostEqual(ellipse_y.Curve.MajorRadius, 18.0)
        self.assertAlmostEqual(ellipse_y.Curve.MinorRadius, 10.0)

        # Zero elongation returns circular edge
        zero_edge = profile.elongate(0.0, V(1, 0, 0), mode='ellipse')
        self.assertTrue(zero_edge.isValid())
        self.assertAlmostEqual(zero_edge.Curve.Radius, 10.0)

        # Negative distance within radius
        shrunk_edge = profile.elongate(-3.0, V(1, 0, 0), mode='ellipse')
        self.assertTrue(shrunk_edge.isValid())
        self.assertAlmostEqual(shrunk_edge.Curve.MajorRadius, 10.0)
        self.assertAlmostEqual(shrunk_edge.Curve.MinorRadius, 7.0)

        # Negative distance collapsing radius raises ValueError
        with self.assertRaises(ValueError):
            profile.elongate(-10.0, V(1, 0, 0))

    def test_circle_edge_slot_geometry(self):
        circle_edge = Part.makeCircle(10)
        profile = ElongateProfile(circle_edge)
        slot_wire = profile.elongate(5.0, V(1, 0, 0), mode='slot')
        self.assertTrue(slot_wire.isValid())
        self.assertEqual(len(slot_wire.Edges), 4)  # 2 straight segments, 2 arcs
        bb = slot_wire.BoundBox
        # Major length along X is 2*(radius + distance) = 2*(10 + 5) = 30
        self.assertAlmostEqual(bb.XLength, 30.0)
        # Minor length along Y is 2*radius = 20
        self.assertAlmostEqual(bb.YLength, 20.0)

    def test_planar_face_elongation(self):
        rect_face = g.rectangle(g.Plane.named(), V(0, 0, 0), V(20, 10, 0))
        profile = ElongateProfile(rect_face)
        self.assertFalse(profile.is_circle)
        stretched = profile.elongate(5.0, V(1, 0, 0))
        self.assertTrue(stretched.isValid())
        self.assertGreater(stretched.Area, rect_face.Area)

    def test_elongate_hole_rim_partitions_solid_face(self):
        doc = self.doc()
        # Create a box with a through hole
        box = Part.makeBox(40, 40, 10)
        cyl = Part.makeCylinder(5, 10)
        cyl.translate(V(20, 20, 0))
        solid = box.cut(cyl).Solids[0]
        obj = ops.new_shape(doc, solid, 'SolidBox')
        initial_face_count = len(obj.Shape.Faces)

        # Find circular rim edge on top face (z=10)
        rim_edge_name = None
        for i, edge in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(edge, 'Curve', None), Part.Circle) and abs(edge.CenterOfMass.z - 10.0) < 1e-4:
                rim_edge_name = f'Edge{i}'
                break
        self.assertIsNotNone(rim_edge_name)

        # Elongate rim edge by 4 mm along X
        results = ops.elongate(obj, rim_edge_name, 4.0, V(1, 0, 0), mode='ellipse')
        self.assertEqual(results, [obj])
        self.assertTrue(obj.Shape.isValid())
        # The carrying top face has been partitioned with the ellipse
        self.assertGreater(len(obj.Shape.Faces), initial_face_count)

    def test_elongate_cut_hole_on_solid(self):
        doc = self.doc()
        # Create a box with a through hole
        box = Part.makeBox(40, 40, 10)
        cyl = Part.makeCylinder(5, 10)
        cyl.translate(V(20, 20, 0))
        solid = box.cut(cyl).Solids[0]
        obj = ops.new_shape(doc, solid, 'SolidBox')

        # Find the cylindrical face
        cyl_face_name = None
        for i, face in enumerate(obj.Shape.Faces, 1):
            if isinstance(getattr(face, 'Surface', None), Part.Cylinder):
                cyl_face_name = f'Face{i}'
                break
        self.assertIsNotNone(cyl_face_name)

        # Elongate with cut_hole=True
        results = ops.elongate(obj, cyl_face_name, 3.0, V(1, 0, 0), mode='ellipse', cut_hole=True)
        self.assertEqual(results, [obj])
        self.assertTrue(obj.Shape.isValid())
        self.assertTrue(bool(obj.Shape.Solids))
        # Volume of solid should be strictly less than before cutting
        self.assertLess(obj.Shape.Volume, solid.Volume)

    def test_elongate_mcp_api(self):
        doc = self.doc()
        box = Part.makeBox(40, 40, 10)
        cyl = Part.makeCylinder(5, 10)
        cyl.translate(V(20, 20, 0))
        solid = box.cut(cyl).Solids[0]
        obj = ops.new_shape(doc, solid, 'SolidBox')

        rim_edge_name = None
        for i, edge in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(edge, 'Curve', None), Part.Circle) and abs(edge.CenterOfMass.z - 10.0) < 1e-4:
                rim_edge_name = f'Edge{i}'
                break

        api = ModelAPI()
        response = api.execute('elongate', doc, {
            'object': obj.Name,
            'element': rim_edge_name,
            'distance': 4.0,
            'direction': [1.0, 0.0, 0.0],
            'mode': 'ellipse'
        })
        self.assertIn('objects', response)
        self.assertTrue(obj.Shape.isValid())

    def test_elongate_slot_mode_partitions_solid(self):
        doc = self.doc()
        box = Part.makeBox(40, 40, 10)
        cyl = Part.makeCylinder(5, 10)
        cyl.translate(V(20, 20, 0))
        solid = box.cut(cyl).Solids[0]
        obj = ops.new_shape(doc, solid, 'SolidBox')
        initial_face_count = len(obj.Shape.Faces)

        rim_edge_name = None
        for i, edge in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(edge, 'Curve', None), Part.Circle) and abs(edge.CenterOfMass.z - 10.0) < 1e-4:
                rim_edge_name = f'Edge{i}'
                break

        results = ops.elongate(obj, rim_edge_name, 5.0, V(1, 0, 0), mode='slot')
        self.assertEqual(results, [obj])
        self.assertTrue(obj.Shape.isValid())
        self.assertGreater(len(obj.Shape.Faces), initial_face_count)

    def test_elongated_face_can_be_push_pulled(self):
        doc = self.doc()
        box = Part.makeBox(40, 40, 10)
        cyl = Part.makeCylinder(5, 10)
        cyl.translate(V(20, 20, 0))
        solid = box.cut(cyl).Solids[0]
        obj = ops.new_shape(doc, solid, 'SolidBox')

        rim_edge_name = None
        for i, edge in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(edge, 'Curve', None), Part.Circle) and abs(edge.CenterOfMass.z - 10.0) < 1e-4:
                rim_edge_name = f'Edge{i}'
                break

        ops.elongate(obj, rim_edge_name, 4.0, V(1, 0, 0), mode='ellipse')

        # Find newly created crescent/elliptical face on z=10
        new_face = None
        for face in obj.Shape.Faces:
            if abs(face.CenterOfMass.z - 10.0) < 1e-4 and face.Area < 100.0:
                new_face = face
                break
        self.assertIsNotNone(new_face)

        # Push/pull the newly created face upwards by 5 mm
        vol_before = obj.Shape.Volume
        ops.extrude(obj, new_face, 5.0)
        self.assertTrue(obj.Shape.isValid())
        self.assertGreater(obj.Shape.Volume, vol_before)

    def test_one_sided_slot_geometry(self):
        circle_edge = Part.makeCircle(10)
        profile = ElongateProfile(circle_edge)

        # Symmetrical slot: extends to both sides (-15 to +15)
        sym_slot = profile.elongate(5.0, V(1, 0, 0), mode='slot', symmetric=True)
        self.assertTrue(sym_slot.isValid())
        bb_sym = sym_slot.BoundBox
        self.assertAlmostEqual(bb_sym.XMin, -15.0)
        self.assertAlmostEqual(bb_sym.XMax, 15.0)
        self.assertAlmostEqual(bb_sym.XLength, 30.0)
        self.assertAlmostEqual(bb_sym.YLength, 20.0)

        # One-sided slot: extends only to +X side (anchored at -10 to +15)
        one_slot = profile.elongate(5.0, V(1, 0, 0), mode='slot', symmetric=False)
        self.assertTrue(one_slot.isValid())
        bb_one = one_slot.BoundBox
        self.assertAlmostEqual(bb_one.XMin, -10.0)
        self.assertAlmostEqual(bb_one.XMax, 15.0)
        self.assertAlmostEqual(bb_one.XLength, 25.0)
        self.assertAlmostEqual(bb_one.YLength, 20.0)

    def test_one_sided_ellipse_geometry(self):
        circle_edge = Part.makeCircle(10)
        profile = ElongateProfile(circle_edge)

        # One-sided ellipse: distance 6 along X
        # Center shifted to X = 3.0 (distance / 2)
        # MajorRadius = 10 + 3 = 13.0, MinorRadius = 10.0
        one_ellipse = profile.elongate(6.0, V(1, 0, 0), mode='ellipse', symmetric=False)
        self.assertTrue(one_ellipse.isValid())
        self.assertIsInstance(one_ellipse.Curve, Part.Ellipse)
        self.assertAlmostEqual(one_ellipse.Curve.Center.x, 3.0)
        self.assertAlmostEqual(one_ellipse.Curve.Center.y, 0.0)
        self.assertAlmostEqual(one_ellipse.Curve.MajorRadius, 13.0)
        self.assertAlmostEqual(one_ellipse.Curve.MinorRadius, 10.0)
        bb = one_ellipse.BoundBox
        self.assertAlmostEqual(bb.XMin, -10.0)
        self.assertAlmostEqual(bb.XMax, 16.0)

        # One-sided ellipse along Y: distance 4 along Y
        one_ellipse_y = profile.elongate(4.0, V(0, 1, 0), mode='ellipse', symmetric=False)
        self.assertTrue(one_ellipse_y.isValid())
        self.assertAlmostEqual(one_ellipse_y.Curve.Center.y, 2.0)
        self.assertAlmostEqual(one_ellipse_y.Curve.MajorRadius, 12.0)
        self.assertAlmostEqual(one_ellipse_y.Curve.MinorRadius, 10.0)
        bb_y = one_ellipse_y.BoundBox
        self.assertAlmostEqual(bb_y.YMin, -10.0)
        self.assertAlmostEqual(bb_y.YMax, 14.0)

    def test_one_sided_planar_face_elongation(self):
        rect_face = g.rectangle(g.Plane.named(), V(0, 0, 0), V(20, 10, 0))
        profile = ElongateProfile(rect_face)
        self.assertFalse(profile.is_circle)
        stretched_one = profile.elongate(5.0, V(1, 0, 0), symmetric=False)
        self.assertTrue(stretched_one.isValid())
        self.assertGreater(stretched_one.Area, rect_face.Area)

    def test_one_sided_hole_rim_partitions_solid(self):
        doc = self.doc()
        box = Part.makeBox(40, 40, 10)
        cyl = Part.makeCylinder(5, 10)
        cyl.translate(V(20, 20, 0))
        solid = box.cut(cyl).Solids[0]
        obj = ops.new_shape(doc, solid, 'SolidBox')
        initial_face_count = len(obj.Shape.Faces)

        rim_edge_name = None
        for i, edge in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(edge, 'Curve', None), Part.Circle) and abs(edge.CenterOfMass.z - 10.0) < 1e-4:
                rim_edge_name = f'Edge{i}'
                break

        results = ops.elongate(obj, rim_edge_name, 4.0, V(1, 0, 0), mode='ellipse', symmetric=False)
        self.assertEqual(results, [obj])
        self.assertTrue(obj.Shape.isValid())
        self.assertGreater(len(obj.Shape.Faces), initial_face_count)

    def test_one_sided_cut_hole_on_solid(self):
        doc = self.doc()
        box = Part.makeBox(40, 40, 10)
        cyl = Part.makeCylinder(5, 10)
        cyl.translate(V(20, 20, 0))
        solid = box.cut(cyl).Solids[0]
        obj = ops.new_shape(doc, solid, 'SolidBox')

        cyl_face_name = None
        for i, face in enumerate(obj.Shape.Faces, 1):
            if isinstance(getattr(face, 'Surface', None), Part.Cylinder):
                cyl_face_name = f'Face{i}'
                break

        results = ops.elongate(obj, cyl_face_name, 3.0, V(1, 0, 0), mode='slot', cut_hole=True, symmetric=False)
        self.assertEqual(results, [obj])
        self.assertTrue(obj.Shape.isValid())
        self.assertTrue(bool(obj.Shape.Solids))
        self.assertLess(obj.Shape.Volume, solid.Volume)

    def test_elongate_mcp_api_one_sided(self):
        doc = self.doc()
        box = Part.makeBox(40, 40, 10)
        cyl = Part.makeCylinder(5, 10)
        cyl.translate(V(20, 20, 0))
        solid = box.cut(cyl).Solids[0]
        obj = ops.new_shape(doc, solid, 'SolidBox')

        rim_edge_name = None
        for i, edge in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(edge, 'Curve', None), Part.Circle) and abs(edge.CenterOfMass.z - 10.0) < 1e-4:
                rim_edge_name = f'Edge{i}'
                break

        api = ModelAPI()
        response = api.execute('elongate', doc, {
            'object': obj.Name,
            'element': rim_edge_name,
            'distance': 4.0,
            'direction': [1.0, 0.0, 0.0],
            'mode': 'slot',
            'symmetric': False
        })
        self.assertIn('objects', response)
        self.assertTrue(obj.Shape.isValid())

    def test_elongate_input_helpers(self):
        from simplecad.gui.tools.elongate import parse_angle_deg
        self.assertAlmostEqual(parse_angle_deg('45'), 45.0)
        self.assertAlmostEqual(parse_angle_deg('90°'), 90.0)
        self.assertAlmostEqual(parse_angle_deg('180 deg'), 180.0)
        self.assertAlmostEqual(parse_angle_deg('-30°'), -30.0)
        with self.assertRaises(ValueError):
            parse_angle_deg('')
        with self.assertRaises(ValueError):
            parse_angle_deg('abc')

    def test_elongate_dialog_widgets(self):
        from simplecad.gui.tools.elongate import ElongateDialog, ElongateInput
        from simplecad.gui.qt import QtWidgets
        _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

        class FakeLabel:
            def setText(self, t): pass
            def setPlaceholderText(self, t): pass

        class FakeComboBox:
            def currentText(self): return "Ellipse"
            def hide(self): pass
            def show(self): pass
            def findText(self, t): return 0
            def setCurrentIndex(self, i): pass
            def blockSignals(self, b): pass

        class FakePreview:
            def update(self, *args, **kwargs): pass

        class FakeControls:
            def __init__(self):
                self.label = FakeLabel()
                self.value = FakeLabel()
                self.elongate_mode = FakeComboBox()

        class FakeController:
            def __init__(self):
                self.cancelled = False
                self.committed = False
                self.controls = FakeControls()
                self.preview = FakePreview()
            def cancel(self, quiet=False):
                self.cancelled = True
            def commit(self):
                self.committed = True
            def message(self, msg):
                pass

        ctrl = FakeController()
        inp = ElongateInput(ctrl)
        circle_edge = Part.makeCircle(10)
        inp.profile = ElongateProfile(circle_edge)
        inp.name = "Edge1"
        inp.distance = 0.0

        dialog = ElongateDialog(inp)
        self.assertTrue(dialog.symmetric_check.isChecked())
        self.assertEqual(inp.symmetric, True)

        # Toggle symmetrical
        dialog.symmetric_check.setChecked(False)
        self.assertEqual(inp.symmetric, False)

        # Set preset angle
        dialog.set_preset_angle(90)
        self.assertAlmostEqual(inp.angle_deg, 90.0)

        # Flip angle
        dialog.flip_angle()
        self.assertAlmostEqual(inp.angle_deg, 270.0)

        # Add distance
        dialog.add_distance(5.0)
        self.assertAlmostEqual(inp.distance, 5.0)

        # Apply
        dialog.apply()
        self.assertTrue(ctrl.committed)

        dialog.close()

    def test_elongate_cylindrical_face_partitions_adjacent_planar_face(self):
        doc = self.doc()
        box = Part.makeBox(40, 40, 10)
        hole = Part.makeCylinder(5, 6)
        hole.translate(V(20, 20, 4))
        solid = box.cut(hole).Solids[0]
        obj = ops.new_shape(doc, solid, 'SolidBox')
        initial_face_count = len(obj.Shape.Faces)

        cyl_face_name = None
        for i, face in enumerate(obj.Shape.Faces, 1):
            if isinstance(getattr(face, 'Surface', None), Part.Cylinder):
                cyl_face_name = f'Face{i}'
                break
        self.assertIsNotNone(cyl_face_name)

        # Elongate cylindrical face directly without cut_hole
        # Should partition the top carrying planar face at z=10
        results = ops.elongate(obj, cyl_face_name, 5.0, V(0, 1, 0), mode='slot', symmetric=False)
        self.assertEqual(results, [obj])
        self.assertTrue(obj.Shape.isValid())
        self.assertGreater(len(obj.Shape.Faces), initial_face_count)

        # Confirm new face exists at z=10 with area = 2*R*d = 10 * 5 = 50 mm^2
        new_face = None
        for face in obj.Shape.Faces:
            if abs(face.CenterOfMass.z - 10.0) < 1e-4 and abs(face.Area - 50.0) < 1e-2:
                new_face = face
                break
        self.assertIsNotNone(new_face)

    def test_elongate_hole_in_multi_hole_plate_partitions_face(self):
        doc = self.doc()
        # Plate with 4 through holes
        plate = Part.makeBox(60, 60, 5)
        for x, y in [(15, 15), (45, 15), (15, 45), (45, 45)]:
            h = Part.makeCylinder(3, 5)
            h.translate(V(x, y, 0))
            plate = plate.cut(h).Solids[0]
        obj = ops.new_shape(doc, plate, 'MultiHolePlate')
        initial_face_count = len(obj.Shape.Faces)

        # Find one circular rim edge on z=0
        rim_edge = None
        for i, edge in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(edge, 'Curve', None), Part.Circle) and abs(edge.CenterOfMass.z) < 1e-4:
                rim_edge = f'Edge{i}'
                break
        self.assertIsNotNone(rim_edge)

        # Elongate 1-sided slot by 4 mm
        res = ops.elongate(obj, rim_edge, 4.0, V(1, 0, 0), mode='slot', symmetric=False)
        self.assertEqual(res, [obj])
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(len(obj.Shape.Solids), 1)
        # 1-sided elongation creates 1 new face on the solid
        self.assertEqual(len(obj.Shape.Faces), initial_face_count + 1)

    def test_heal_dangling_elongation_integrates_wire_into_solid(self):
        doc = self.doc()
        box = Part.makeBox(40, 40, 10)
        hole = Part.makeCylinder(5, 10)
        hole.translate(V(20, 20, 0))
        solid = box.cut(hole).Solids[0]
        solid_obj = ops.new_shape(doc, solid, 'SolidBox')
        initial_face_count = len(solid_obj.Shape.Faces)

        # Create a standalone wire lying on the top face (z=10)
        c_edge = Part.makeCircle(5, V(20, 20, 10), V(0, 0, 1))
        profile = ElongateProfile(c_edge)
        slot_wire = profile.elongate(4.0, V(1, 0, 0), mode='slot', symmetric=True)
        ops.new_shape(doc, slot_wire, 'Elongated slot')

        self.assertEqual(len(doc.Objects), 2)
        healed = ops.heal_dangling_elongations(doc)
        self.assertEqual(healed, 1)
        # Wire object should be consumed/removed from document
        self.assertEqual(len(doc.Objects), 1)
        # Solid should have 2 new faces
        self.assertEqual(len(solid_obj.Shape.Faces), initial_face_count + 2)
        self.assertTrue(solid_obj.Shape.isValid())

    def test_cleanup_integrates_dangling_elongations(self):
        doc = self.doc()
        box = Part.makeBox(40, 40, 10)
        hole = Part.makeCylinder(5, 10)
        hole.translate(V(20, 20, 0))
        solid = box.cut(hole).Solids[0]
        solid_obj = ops.new_shape(doc, solid, 'SolidBox')
        initial_face_count = len(solid_obj.Shape.Faces)

        c_edge = Part.makeCircle(5, V(20, 20, 10), V(0, 0, 1))
        profile = ElongateProfile(c_edge)
        slot_wire = profile.elongate(4.0, V(0, 1, 0), mode='slot', symmetric=False)
        ops.new_shape(doc, slot_wire, 'Elongated slot')

        ops.cleanup(doc)
        self.assertEqual(len(doc.Objects), 1)
        self.assertEqual(len(solid_obj.Shape.Faces), initial_face_count + 1)
        self.assertTrue(solid_obj.Shape.isValid())


if __name__ == '__main__':
    unittest.main()
