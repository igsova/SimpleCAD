"""Unit tests for Push/Pull interactive dialog and input session."""
import math
import unittest
from unittest.mock import MagicMock
import FreeCAD as App
import Part
from pivy import coin

from simplecad.document import operations as ops
from simplecad.core import geometry as g
from simplecad.gui.previews.overlay import Preview
from simplecad.gui.tools.push_pull import PushPullInput, PushPullDialog
from simplecad.gui.qt import QtWidgets

V = App.Vector


class DummyController:
    """Mock controller to test PushPullInput and PushPullDialog headless."""
    def __init__(self, doc):
        self.doc = doc
        self.view = None
        self.controls = MagicMock()
        self.preview = MagicMock()
        self.snapper = MagicMock()
        self.snapper.settings.pull_faces = True
        self.snapper.settings.pull_radius = 10.0
        self.anchor = None
        self.message_log = []

    def message(self, msg):
        self.message_log.append(msg)

    def cancel(self):
        pass

    def commit(self):
        pass


class PushPullUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure QApplication exists for QWidget tests
        cls.app = QtWidgets.QApplication.instance()
        if cls.app is None:
            cls.app = QtWidgets.QApplication([])

    def doc(self):
        doc = App.newDocument('PushPullUITest')
        doc.UndoMode = 1
        name = doc.Name
        self.addCleanup(lambda: App.closeDocument(name) if name in App.listDocuments() else None)
        return doc

    def test_dialog_initialization_on_solid_box(self):
        doc = self.doc()
        box = Part.makeBox(40, 40, 20)
        obj = ops.new_shape(doc, box, 'Box')

        # Find top face (z=20, normal=(0, 0, 1))
        top_face = None
        top_name = None
        for i, f in enumerate(obj.Shape.Faces, 1):
            if abs(f.CenterOfMass.z - 20) < 1e-4:
                top_face = f
                top_name = f"Face{i}"
                break
        self.assertIsNotNone(top_face)

        c = DummyController(doc)
        inp = PushPullInput(c)
        inp.choose(obj, top_name)

        self.assertTrue(inp.is_solid)
        self.assertAlmostEqual(inp.normal.z, 1.0)
        self.assertIsNotNone(inp.pull_contact)
        self.assertAlmostEqual(inp.pull_contact.distance, -20.0)

        # Create dialog
        dialog = PushPullDialog(inp)
        self.assertEqual(dialog.windowTitle(), "Push / Pull")
        self.assertEqual(dialog.dir_combo.count(), 2)
        self.assertEqual(dialog.dir_combo.itemText(0), "Outward (Extrude / Boss)")
        self.assertEqual(dialog.dir_combo.itemText(1), "Inward (Pocket / Cut)")
        self.assertEqual(dialog.dir_combo.currentIndex(), 0)  # Outward by default
        self.assertFalse(dialog.apply_button.isEnabled())  # 0 distance disabled
        self.assertIsNotNone(dialog.opp_btn)
        self.assertIn("20.00 mm", dialog.opp_btn.text())

    def test_distance_input_and_direction_flip(self):
        doc = self.doc()
        box = Part.makeBox(40, 40, 20)
        obj = ops.new_shape(doc, box, 'Box')
        top_name = None
        for i, f in enumerate(obj.Shape.Faces, 1):
            if abs(f.CenterOfMass.z - 20) < 1e-4:
                top_name = f"Face{i}"
                break

        c = DummyController(doc)
        inp = PushPullInput(c)
        inp.choose(obj, top_name)
        dialog = PushPullDialog(inp)
        inp.dialog = dialog

        # Type positive distance
        dialog.dist_edit.setText("5.0 mm")
        dialog.on_distance_edited("5.0 mm")
        self.assertAlmostEqual(inp.distance, 5.0)
        self.assertEqual(inp.direction_sign, 1)
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertIn("Extruding outward (+5.00 mm)", dialog.status.text())

        # Flip direction
        dialog.flip_direction()
        self.assertAlmostEqual(inp.distance, -5.0)
        self.assertEqual(inp.direction_sign, -1)
        self.assertEqual(dialog.dir_combo.currentIndex(), 1)
        self.assertIn("Cutting inward (-5.00 mm)", dialog.status.text())

        # Flip back
        dialog.flip_direction()
        self.assertAlmostEqual(inp.distance, 5.0)
        self.assertEqual(inp.direction_sign, 1)
        self.assertEqual(dialog.dir_combo.currentIndex(), 0)

        # Smart negative input: typing -8 mm switches to Inward
        dialog.on_distance_edited("-8 mm")
        self.assertAlmostEqual(inp.distance, -8.0)
        self.assertEqual(inp.direction_sign, -1)
        self.assertEqual(dialog.dir_combo.currentIndex(), 1)

    def test_distance_presets_and_reset(self):
        doc = self.doc()
        box = Part.makeBox(30, 30, 10)
        obj = ops.new_shape(doc, box, 'Box')

        c = DummyController(doc)
        inp = PushPullInput(c)
        inp.choose(obj, "Face1")
        dialog = PushPullDialog(inp)
        inp.dialog = dialog

        dialog.add_distance(2.0)
        self.assertAlmostEqual(inp.distance, 2.0)
        self.assertEqual(dialog.dist_edit.text(), "2.00 mm")

        dialog.add_distance(5.0)
        self.assertAlmostEqual(inp.distance, 7.0)
        self.assertEqual(dialog.dist_edit.text(), "7.00 mm")

        dialog.reset_distance()
        self.assertAlmostEqual(inp.distance, 0.0)
        self.assertEqual(dialog.dist_edit.text(), "")
        self.assertFalse(dialog.apply_button.isEnabled())

    def test_opposite_face_button(self):
        doc = self.doc()
        box = Part.makeBox(50, 50, 15)
        obj = ops.new_shape(doc, box, 'Box')
        top_name = None
        for i, f in enumerate(obj.Shape.Faces, 1):
            if abs(f.CenterOfMass.z - 15) < 1e-4:
                top_name = f"Face{i}"
                break

        c = DummyController(doc)
        inp = PushPullInput(c)
        inp.choose(obj, top_name)
        dialog = PushPullDialog(inp)
        inp.dialog = dialog

        self.assertIsNotNone(dialog.opp_btn)
        dialog.to_opposite_face()
        self.assertAlmostEqual(inp.distance, -15.0)
        self.assertEqual(inp.direction_sign, -1)
        self.assertEqual(dialog.dir_combo.currentIndex(), 1)
        self.assertIn("Through-hole cut to opposite face (-15.00 mm)", dialog.status.text())

    def test_inward_preview_is_drawn_inward_and_through_faces(self):
        doc = self.doc()
        obj = ops.new_shape(doc, Part.makeBox(40, 40, 20), 'Box')
        profile = g.circle(g.Plane.named('XY', V(20, 20, 20)), V(20, 20, 20), 8)
        ops.draw_circle(doc, profile, obj)
        circle = next(f for f in obj.Shape.Faces if abs(f.Area - profile.Area) < 1e-6)
        c = DummyController(doc)
        inp = PushPullInput(c)
        inp.choose(obj, circle)
        dialog = PushPullDialog(inp)
        inp.dialog = dialog

        def drawn():
            args, kwargs = c.preview.update.call_args
            return kwargs['see_through'], args[0], args[1], kwargs['offset'], kwargs['moving']

        self.assertFalse(drawn()[0])  # Zero distance: only the face and a stub.
        dialog.on_distance_edited('5 mm')
        self.assertFalse(drawn()[0])
        for change, depth in ((dialog.flip_direction, -5), (dialog.to_opposite_face, -20),
                              (lambda: dialog.on_distance_edited('-8'), -8), (lambda: inp.numeric('-3'), -3)):
            change()
            see_through, polylines, target, offset, moving = drawn()
            self.assertAlmostEqual(inp.distance, depth)
            self.assertTrue(see_through)
            # Walls, cap and target lie inside the solid, never on the outward side.
            self.assertAlmostEqual(offset.z, depth)
            self.assertAlmostEqual(target.z, 20 + depth)
            self.assertTrue(all(depth + 20 - 1e-9 <= p.z <= 20 + 1e-9 for line in polylines for p in line))
            self.assertTrue(all(abs(p.z - 20) < 1e-9 for line in moving for p in line))
        dialog.reset_distance()
        self.assertFalse(drawn()[0])
        dialog.dir_combo.setCurrentIndex(0)
        dialog.on_distance_edited('4')
        self.assertAlmostEqual(inp.distance, 4)
        self.assertFalse(drawn()[0])

    def test_commit_extrude_outward(self):
        doc = self.doc()
        box = Part.makeBox(20, 20, 10)
        obj = ops.new_shape(doc, box, 'Box')
        init_vol = obj.Shape.Volume  # 4000
        top_name = None
        for i, f in enumerate(obj.Shape.Faces, 1):
            if abs(f.CenterOfMass.z - 10) < 1e-4:
                top_name = f"Face{i}"
                break

        c = DummyController(doc)
        inp = PushPullInput(c)
        inp.choose(obj, top_name)
        dialog = PushPullDialog(inp)
        inp.dialog = dialog

        dialog.on_distance_edited("5 mm")
        results = inp.commit()

        self.assertEqual(len(results), 1)
        self.assertTrue(obj.Shape.isValid())
        # Volume increases by 20*20*5 = 2000 => 6000
        self.assertAlmostEqual(obj.Shape.Volume, init_vol + 2000.0)

    def test_commit_extrude_inward_pocket(self):
        doc = self.doc()
        # Plate with a smaller central face to pocket
        box = Part.makeBox(40, 40, 20)
        # Create a pocket face by drawing a 20x20 rectangle on top (z=20)
        top_face = [f for f in box.Faces if abs(f.CenterOfMass.z - 20) < 1e-4][0]
        rect_face = Part.Face(Part.Wire(Part.makePolygon([
            V(10, 10, 20), V(30, 10, 20), V(30, 30, 20), V(10, 30, 20), V(10, 10, 20)
        ])))
        divided = top_face.cut(rect_face)
        # Fuse divided faces with box
        faces = [f for f in box.Faces if abs(f.CenterOfMass.z - 20) >= 1e-4] + divided.Faces + [rect_face]
        shell = Part.Shell(faces)
        solid = Part.Solid(shell)
        obj = ops.new_shape(doc, solid, 'Solid')
        init_vol = obj.Shape.Volume

        # Find the inner 20x20 face
        inner_face = None
        for f in obj.Shape.Faces:
            if abs(f.CenterOfMass.z - 20) < 1e-4 and abs(f.Area - 400) < 1e-2:
                inner_face = f
                break
        self.assertIsNotNone(inner_face)

        c = DummyController(doc)
        inp = PushPullInput(c)
        inp.choose(obj, inner_face)
        dialog = PushPullDialog(inp)
        inp.dialog = dialog

        dialog.flip_direction()  # Inward
        dialog.on_distance_edited("5 mm")
        self.assertAlmostEqual(inp.distance, -5.0)

        results = inp.commit()
        self.assertEqual(len(results), 1)
        self.assertTrue(obj.Shape.isValid())
        # Volume decreases by 20*20*5 = 2000
        self.assertAlmostEqual(obj.Shape.Volume, init_vol - 2000.0)

    def test_commit_annular_face_collar_boss(self):
        doc = self.doc()
        # Plate with a central through-hole
        plate = Part.makeBox(40, 40, 10)
        hole = Part.makeCylinder(5, 10)
        hole.translate(V(20, 20, 0))
        solid = plate.cut(hole).Solids[0]
        obj = ops.new_shape(doc, solid, 'PlateWithHole')

        top_hole_name = None
        for i, e in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(e, 'Curve', None), Part.Circle) and abs(e.CenterOfMass.z - 10) < 1e-4:
                top_hole_name = f"Edge{i}"
                break
        self.assertIsNotNone(top_hole_name)

        # Offset the hole edge by 3 mm outward to create an annular face
        ops.offset(obj, top_hole_name, 3.0)
        self.assertTrue(obj.Shape.isValid())

        # Find the annular face (inner radius 5, outer radius 8, area pi*(64-25)=39*pi~122.5)
        annular_face = None
        for f in obj.Shape.Faces:
            if abs(f.CenterOfMass.z - 10) < 1e-4 and len(f.Wires) == 2:
                annular_face = f
                break
        self.assertIsNotNone(annular_face)

        c = DummyController(doc)
        inp = PushPullInput(c)
        inp.choose(obj, annular_face)
        dialog = PushPullDialog(inp)
        inp.dialog = dialog

        # Extrude collar boss by +2.0 mm
        dialog.on_distance_edited("2 mm")
        self.assertAlmostEqual(inp.distance, 2.0)
        results = inp.commit()

        self.assertEqual(len(results), 1)
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(len(obj.Shape.Solids), 1)
        # Check that top height now reaches 12 mm
        self.assertAlmostEqual(obj.Shape.BoundBox.ZMax, 12.0)

    def test_commit_annular_face_pocket(self):
        doc = self.doc()
        # Plate with a central through-hole
        plate = Part.makeBox(40, 40, 10)
        hole = Part.makeCylinder(5, 10)
        hole.translate(V(20, 20, 0))
        solid = plate.cut(hole).Solids[0]
        obj = ops.new_shape(doc, solid, 'PlateWithHole')

        top_hole_name = None
        for i, e in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(e, 'Curve', None), Part.Circle) and abs(e.CenterOfMass.z - 10) < 1e-4:
                top_hole_name = f"Edge{i}"
                break
        self.assertIsNotNone(top_hole_name)

        ops.offset(obj, top_hole_name, 3.0)
        self.assertTrue(obj.Shape.isValid())

        annular_face = None
        for f in obj.Shape.Faces:
            if abs(f.CenterOfMass.z - 10) < 1e-4 and len(f.Wires) == 2:
                annular_face = f
                break
        self.assertIsNotNone(annular_face)

        c = DummyController(doc)
        inp = PushPullInput(c)
        inp.choose(obj, annular_face)
        dialog = PushPullDialog(inp)
        inp.dialog = dialog

        # Inward 3mm pocket (counterbore)
        dialog.flip_direction()
        dialog.on_distance_edited("3 mm")
        self.assertAlmostEqual(inp.distance, -3.0)
        results = inp.commit()

        self.assertEqual(len(results), 1)
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(len(obj.Shape.Solids), 1)

    def test_trim_overlapping_walls_cancels_hole_wall(self):
        doc = self.doc()
        plate = Part.makeBox(40, 40, 10)
        hole = Part.makeCylinder(5, 10)
        hole.translate(V(20, 20, 0))
        obj = ops.new_shape(doc, plate.cut(hole).Solids[0], 'PlateWithHole')
        rim = next(f"Edge{i}" for i, e in enumerate(obj.Shape.Edges, 1)
                   if isinstance(getattr(e, 'Curve', None), Part.Circle) and abs(e.CenterOfMass.z - 10) < 1e-4)
        ops.offset(obj, rim, 3.0)
        solid = obj.Shape
        face = next(f for f in solid.Faces if len(f.Wires) == 2 and abs(f.CenterOfMass.z - 10) < 1e-6
                    and f.Area < 500)
        prism = face.extrude(V(0, 0, -3))
        walls = [f.reversed() for f in prism.Faces if not g.coinc.same(f, face)
                 and abs(f.CenterOfMass.z - 10) > 1e-6]

        kept, substitutions = g.trim_overlapping_walls(solid, face, walls)

        # The inner swept wall lies on the hole wall; only the outer remains.
        self.assertEqual(len(kept), 2)
        self.assertEqual(len(substitutions), 1)
        old, new = substitutions[0]
        self.assertAlmostEqual(old.Area, 2 * math.pi * 5 * 10, places=4)
        self.assertAlmostEqual(new.Area, 2 * math.pi * 5 * 7, places=4)
        self.assertAlmostEqual(new.BoundBox.ZMax, 7.0, places=6)

    def test_non_solid_sheet_extrude(self):
        doc = self.doc()
        # Create a standalone 2D rectangular sheet face
        rect_face = Part.Face(Part.Wire(Part.makePolygon([
            V(0, 0, 0), V(30, 0, 0), V(30, 20, 0), V(0, 20, 0), V(0, 0, 0)
        ])))
        obj = ops.new_shape(doc, rect_face, 'Sheet')

        c = DummyController(doc)
        inp = PushPullInput(c)
        inp.choose(obj, obj.Shape.Faces[0])
        dialog = PushPullDialog(inp)
        inp.dialog = dialog

        self.assertFalse(inp.is_solid)
        self.assertEqual(dialog.dir_combo.itemText(0), "Along normal (+)")
        self.assertEqual(dialog.dir_combo.itemText(1), "Opposite normal (-)")

        dialog.on_distance_edited("10 mm")
        results = inp.commit()

        self.assertEqual(len(results), 1)
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(len(obj.Shape.Solids), 1)
        self.assertAlmostEqual(obj.Shape.Volume, 30 * 20 * 10)


    def test_curved_face_rejection(self):
        doc = self.doc()
        cyl = Part.makeCylinder(10, 20)
        obj = ops.new_shape(doc, cyl, 'Cylinder')

        curved_face = None
        for f in obj.Shape.Faces:
            if isinstance(f.Surface, Part.Cylinder):
                curved_face = f
                break
        self.assertIsNotNone(curved_face)

        c = DummyController(doc)
        inp = PushPullInput(c)
        with self.assertRaises(ValueError) as ctx:
            inp.choose(obj, curved_face)
        self.assertIn("flat face", str(ctx.exception).lower())


    def test_mesh_converted_chassis_annular_pocket(self):
        import os
        if not os.path.exists('EditableMesh001.Shape.brp'):
            return
        doc = self.doc()
        shape = Part.Shape()
        shape.read('EditableMesh001.Shape.brp')
        solid_obj = ops.new_shape(doc, shape, 'EditableMesh001')

        for name in ['SimpleShape', 'SimpleShape001', 'SimpleShape002', 'SimpleShape003']:
            f_name = f'{name}.Shape.brp'
            if os.path.exists(f_name):
                w_shape = Part.Shape()
                w_shape.read(f_name)
                ops.new_shape(doc, w_shape, name)

        healed_count = ops.heal_dangling_wires(doc)
        print('Healed dangling wires count:', healed_count)
        print('Solid faces after healing:', len(solid_obj.Shape.Faces))

        # Find the annular face created around the hole by offset healing (Face93, Area ~ 14.7 mm^2)
        annular_face = next((f for f in solid_obj.Shape.Faces if len(f.Wires) == 2 and f.Area < 100), None)
        self.assertIsNotNone(annular_face)

        # Test cutting -3 mm inward pocket (counterbore)
        res = g.push_pull(solid_obj.Shape, annular_face, -3.0)
        self.assertTrue(res.isValid())
        self.assertEqual(len(res.Solids), 1)
        self.assertAlmostEqual(res.Volume, solid_obj.Shape.Volume - 44.36, delta=1.0)

        # The hole wall is trimmed to the pocket floor, not kept beside a
        # second swept wall.
        hole_radius = min(e.Curve.Radius for e in annular_face.Edges)
        floor_z = min(f.CenterOfMass.z for f in res.Faces
                      if isinstance(f.Surface, Part.Plane) and len(f.Wires) == 2 and f.Area < 100
                      and 2.9 < f.distToShape(annular_face)[0] < 3.1)
        walls = [f for f in res.Faces if isinstance(f.Surface, Part.Cylinder)
                 and abs(f.Surface.Radius - hole_radius) < 1e-2
                 and f.distToShape(annular_face)[0] < 5]
        self.assertTrue(walls)
        for wall in walls:
            self.assertGreater(wall.BoundBox.ZMin, floor_z - 0.01)

        # Pushing exactly to the far side opens a through-hole of the ring's
        # outer size: ring and hole wall go, one outer wall is added, and the
        # top face gets the larger opening.
        for depth in (-3.996, -4.0):
            through = g.push_pull(solid_obj.Shape, annular_face, depth)
            self.assertTrue(through.isValid())
            self.assertTrue(through.isClosed())
            self.assertEqual(len(through.Faces), len(solid_obj.Shape.Faces) - 1)
            self.assertAlmostEqual(through.Volume, solid_obj.Shape.Volume - annular_face.Area * 4.0, delta=0.5)
            self.assertFalse([f for f in through.Faces if isinstance(f.Surface, Part.Cylinder)
                              and abs(f.Surface.Radius - hole_radius) < 1e-2
                              and f.distToShape(annular_face)[0] < 1e-3])

        # Pushing past the plate cannot be cut on this solid; refuse it
        # instead of leaving a cap outside the model.
        with self.assertRaises(ValueError):
            g.push_pull(solid_obj.Shape, annular_face, -5.0)

        # Test cutting -2.04 mm inward pocket (counterbore as in user screenshot)
        res2 = g.push_pull(solid_obj.Shape, annular_face, -2.04)
        self.assertTrue(res2.isValid())
        self.assertEqual(len(res2.Solids), 1)
        self.assertAlmostEqual(res2.Volume, solid_obj.Shape.Volume - 30.20, delta=1.0)

        # Test through PushPullInput dialog commit
        c = DummyController(doc)
        inp = PushPullInput(c)
        inp.choose(solid_obj, annular_face)
        dialog = PushPullDialog(inp)
        inp.dialog = dialog

        dialog.flip_direction()  # Inward
        dialog.on_distance_edited("3 mm")
        self.assertAlmostEqual(inp.distance, -3.0)
        results = inp.commit()
        self.assertEqual(len(results), 1)
        self.assertTrue(solid_obj.Shape.isValid())
        self.assertEqual(len(solid_obj.Shape.Solids), 1)


class FakeView:
    def __init__(self):
        self.graph = coin.SoSeparator()
        self.redraws = 0

    def getSceneGraph(self):
        return self.graph

    def redraw(self):
        self.redraws += 1


class SeeThroughPreviewTests(unittest.TestCase):
    def test_see_through_pass_is_opt_in_and_reuses_the_drawn_nodes(self):
        view = FakeView()
        p = Preview(view)
        hidden = p.see_through.getChild(0)
        children = [hidden.getChild(i) for i in range(hidden.getNumChildren())]
        depth = next(n for n in children if n.isOfType(coin.SoDepthBuffer.getClassTypeId()))
        self.assertEqual(depth.function.getValue(), coin.SoDepthBuffer.ALWAYS)
        self.assertFalse(depth.getField('write').getValue())  # SoNode.write is a method
        style = next(n for n in children if n.isOfType(coin.SoDrawStyle.getClassTypeId()))
        self.assertNotEqual(style.linePattern.getValue(), 0xFFFF)
        self.assertLess(style.lineWidth.getValue(), 2.5)
        # The same coordinates, lines, translated cap and marker: no copy to keep in step.
        for node in (p.coords, p.lines, p.marker_coords, p.marker):
            self.assertGreaterEqual(hidden.findChild(node), 0)
            self.assertGreater(p.root.findChild(node), p.root.findChild(p.see_through))
        self.assertTrue(any(child.isOfType(coin.SoSeparator.getClassTypeId())
                            and child.findChild(p.moving_coords) >= 0 for child in children))
        self.assertEqual(p.see_through.whichChild.getValue(), coin.SO_SWITCH_NONE)

        base = [[V(0, 0, 0), V(10, 0, 0), V(10, 10, 0)]]
        p.update(base + [[V(0, 0, 0), V(0, 0, -3)]], V(0, 0, -3), moving=base, offset=V(0, 0, -3),
                 see_through=True)
        self.assertEqual(p.see_through.whichChild.getValue(), 0)
        self.assertEqual(p.moving_coords.point.getNum(), 3)
        p.update(base, V(0, 0, 2), moving=base, offset=V(0, 0, 2))
        self.assertEqual(p.see_through.whichChild.getValue(), coin.SO_SWITCH_NONE)
        self.assertEqual(tuple(p.offset.translation.getValue()), (0, 0, 2))
        p.update(see_through=True)
        p.update()
        self.assertEqual(p.see_through.whichChild.getValue(), coin.SO_SWITCH_NONE)
        p.close()
        self.assertEqual(view.graph.getNumChildren(), 0)


if __name__ == '__main__':
    unittest.main()


