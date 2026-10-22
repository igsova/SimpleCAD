"""Tests for rotating lines, arcs, and edges on faces and standalone objects."""
import unittest
import FreeCAD as App
import Part
from simplecad.document import operations as ops
from simplecad.modeling import rotation
from simplecad.mcp.api import ModelAPI
V = App.Vector


class RotateEdgesTests(unittest.TestCase):
    def doc(self):
        doc = App.newDocument("RotateEdgesTest")
        doc.UndoMode = 1
        name = doc.Name
        self.addCleanup(lambda: App.closeDocument(name) if name in App.listDocuments() else None)
        return doc

    def test_rotate_ellipse_half_edge_on_solid(self):
        """Rotate one half of an elongated ellipse 90 degrees around hole center (user diagram scenario)."""
        doc = self.doc()
        box = Part.makeBox(40, 40, 10)
        cyl = Part.makeCylinder(5, 10)
        cyl.translate(V(20, 20, 0))
        solid = box.cut(cyl).Solids[0]
        obj = ops.new_shape(doc, solid, "SolidBox")

        # Find rim edge and elongate along +X by 4 mm
        rim_edge_name = None
        for i, edge in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(edge, "Curve", None), Part.Circle) and abs(edge.CenterOfMass.z - 10.0) < 1e-4:
                rim_edge_name = f"Edge{i}"
                break
        self.assertIsNotNone(rim_edge_name)

        ops.elongate(obj, rim_edge_name, 4.0, V(1, 0, 0), mode="ellipse")

        # Find the right half-ellipse edges (x > 20 on top face z=10)
        sel_names = []
        for i, edge in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(edge, "Curve", None), Part.Ellipse) and edge.CenterOfMass.x > 20.0 and abs(edge.CenterOfMass.z - 10.0) < 1e-4:
                sel_names.append(f"Edge{i}")
        self.assertTrue(bool(sel_names))

        # Prepare rotation with the selected half-ellipse edges
        selection = [(obj, tuple(sel_names))]
        targets = ops.prepare_rotation(selection)
        self.assertEqual(len(targets), 1)
        target = targets[0]
        self.assertEqual(target.mode, "edge")
        self.assertEqual(set(target.elements), set(sel_names))

        # Compute frames: pivot defaults to CurveCenter (hole center), axis to FaceNormal (0,0,1)
        frames = rotation.frames([s for _, s in targets], axis="FaceNormal", pivot="CurveCenter", targets=targets)
        self.assertEqual(len(frames), 1)
        self.assertAlmostEqual((frames[0].center - V(20, 20, 10)).Length, 0.0, places=4)
        self.assertAlmostEqual(abs(frames[0].axis.dot(V(0, 0, 1))), 1.0, places=4)

        # Rotate by -90 degrees (clockwise from right to bottom)
        changed = ops.commit_rotation(targets, frames, -90.0, copy=False)
        self.assertTrue(changed)
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(len(obj.Shape.Solids), 1)

        # Verify: right half is no longer an ellipse boundary (x > 25 has no edges on top face),
        # and bottom area (y < 20) now has a crescent face!
        bottom_crescent_faces = [
            f for f in obj.Shape.Faces
            if abs(f.CenterOfMass.z - 10.0) < 1e-4 and f.CenterOfMass.y < 16.0 and f.Area < 100.0
        ]
        self.assertGreaterEqual(len(bottom_crescent_faces), 1)

        # Verify the new crescent face can be push-pulled upwards
        vol_before = obj.Shape.Volume
        ops.extrude(obj, bottom_crescent_faces[0], 5.0)
        self.assertTrue(obj.Shape.isValid())
        self.assertGreater(obj.Shape.Volume, vol_before)

    def test_rotate_edge_with_copy(self):
        """Rotate an edge on a solid with copy=True: both original and rotated exist."""
        doc = self.doc()
        box = Part.makeBox(40, 40, 10)
        cyl = Part.makeCylinder(5, 10)
        cyl.translate(V(20, 20, 0))
        solid = box.cut(cyl).Solids[0]
        obj = ops.new_shape(doc, solid, "SolidBox")

        for i, edge in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(edge, "Curve", None), Part.Circle) and abs(edge.CenterOfMass.z - 10.0) < 1e-4:
                rim_edge_name = f"Edge{i}"
                break

        ops.elongate(obj, rim_edge_name, 4.0, V(1, 0, 0), mode="ellipse")

        sel_names = []
        for i, edge in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(edge, "Curve", None), Part.Ellipse) and edge.CenterOfMass.x > 20.0 and abs(edge.CenterOfMass.z - 10.0) < 1e-4:
                sel_names.append(f"Edge{i}")

        targets = ops.prepare_rotation([(obj, tuple(sel_names))])
        frames = rotation.frames([s for _, s in targets], axis="FaceNormal", pivot="CurveCenter", targets=targets)
        changed = ops.commit_rotation(targets, frames, -90.0, copy=True)
        self.assertTrue(changed)
        self.assertTrue(obj.Shape.isValid())

        # With copy=True, we should have crescent faces on BOTH the right and bottom!
        right_faces = [f for f in obj.Shape.Faces if abs(f.CenterOfMass.z - 10.0) < 1e-4 and f.CenterOfMass.x > 24.0 and f.Area < 100.0]
        bottom_faces = [f for f in obj.Shape.Faces if abs(f.CenterOfMass.z - 10.0) < 1e-4 and f.CenterOfMass.y < 16.0 and f.Area < 100.0]
        self.assertGreaterEqual(len(right_faces), 1)
        self.assertGreaterEqual(len(bottom_faces), 1)

    def test_rotate_standalone_line(self):
        """Rotate a standalone line around its start point."""
        doc = self.doc()
        line = Part.makeLine(V(0, 0, 0), V(10, 0, 0))
        obj = ops.new_shape(doc, line, "Line")

        targets = ops.prepare_rotation([(obj, ("Edge1",))])
        frames = rotation.frames([s for _, s in targets], axis="Z", pivot="Start", targets=targets)
        self.assertAlmostEqual((frames[0].center - V(0, 0, 0)).Length, 0.0)

        changed = ops.commit_rotation(targets, frames, 90.0)
        self.assertTrue(changed)
        self.assertTrue(obj.Shape.isValid())
        end_pt = obj.Shape.Edges[0].Vertexes[-1].Point
        self.assertAlmostEqual(end_pt.x, 0.0, places=4)
        self.assertAlmostEqual(end_pt.y, 10.0, places=4)

    def test_rotate_edge_mcp_api(self):
        """Rotate edge via MCP API execute."""
        doc = self.doc()
        box = Part.makeBox(40, 40, 10)
        cyl = Part.makeCylinder(5, 10)
        cyl.translate(V(20, 20, 0))
        solid = box.cut(cyl).Solids[0]
        obj = ops.new_shape(doc, solid, "SolidBox")

        for i, edge in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(edge, "Curve", None), Part.Circle) and abs(edge.CenterOfMass.z - 10.0) < 1e-4:
                rim_edge_name = f"Edge{i}"
                break

        ops.elongate(obj, rim_edge_name, 4.0, V(1, 0, 0), mode="ellipse")

        sel_names = []
        for i, edge in enumerate(obj.Shape.Edges, 1):
            if isinstance(getattr(edge, "Curve", None), Part.Ellipse) and edge.CenterOfMass.x > 20.0 and abs(edge.CenterOfMass.z - 10.0) < 1e-4:
                sel_names.append(f"Edge{i}")

        api = ModelAPI()
        response = api.execute("rotate", doc, {
            "objects": [obj.Name],
            "elements": sel_names,
            "axis": "FaceNormal",
            "pivot": "CurveCenter",
            "angle": -90.0,
            "copy": False
        })
        self.assertTrue(response.get("changed"))
        self.assertTrue(obj.Shape.isValid())

    def test_rotate_preview_edges(self):
        """Test RotatePreview with edge targets without GUI errors."""
        from types import SimpleNamespace
        from pivy import coin
        from simplecad.gui.previews.rotate import RotatePreview
        doc = self.doc()
        box = Part.makeBox(40, 40, 10)
        obj = ops.new_shape(doc, box, "SolidBox")
        targets = ops.prepare_rotation([(obj, ("Edge1", "Edge2"))])
        fake_scene = coin.SoSeparator()
        fake_view = SimpleNamespace(getSceneGraph=lambda: fake_scene, redraw=lambda: None)

        preview = RotatePreview(fake_view, targets)
        self.assertEqual(len(preview.cached), 1)

        frames = rotation.frames([s for _, s in targets], axis="FaceNormal", pivot="CurveCenter", targets=targets)
        # Show rotation at 45 degrees
        preview.show_rotation(frames, 45.0, "FaceNormal")
        self.assertTrue(preview.models_added)

        # Move angle to 90 degrees (models should not duplicate)
        preview.show_rotation(frames, 90.0, "FaceNormal")
        self.assertEqual(preview.models.getNumChildren(), 1)

        preview.clear()
        self.assertFalse(preview.models_added)
        preview.close()


if __name__ == "__main__":
    unittest.main()

