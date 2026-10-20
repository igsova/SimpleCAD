"""Exact curves, closed arc/line faces, partitions, locks, persistence and undo."""
import math
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import FreeCAD as App
import Part
from simplecad.modeling import arcs
from simplecad.core import geometry as g
from simplecad.document import operations as op, locking
V = App.Vector


class ArcTests(unittest.TestCase):
    def test_center_sweep_both_directions_and_major_arcs(self):
        for angle in (30, 90, 180, 270, -30, -180, -270):
            arc = arcs.centered(V(3,4,5), V(13,4,5), V(0,0,1), angle)
            edge = arc.edge()
            self.assertIsInstance(edge.Curve, Part.Circle)
            self.assertAlmostEqual(edge.Length, 10*abs(math.radians(angle)), places=6)
            self.assertTrue(edge.isValid())
            for point in arc.points():
                self.assertAlmostEqual((point-arc.center).Length, 10, places=7)
                self.assertAlmostEqual(point.z, 5)

    def test_two_point_signed_bulges_including_major_arcs(self):
        for height in (.2, 2, 5, 12, -.2, -5, -12):
            arc = arcs.two_point(V(-5,0,3), V(5,0,3), V(0,0,1), height)
            self.assertLess((arc.point(0)-V(-5,0,3)).Length, 1e-7)
            self.assertLess((arc.point(1)-V(5,0,3)).Length, 1e-7)
            self.assertLess((arc.point(.5)-V(0,height,3)).Length, 1e-7)
            self.assertIsInstance(arc.edge().Curve, Part.Circle)

    def test_oblique_and_reversed_plane(self):
        rotation = App.Rotation(V(1,2,3), 48)
        normal = rotation.multVec(V(0,0,1)); start = rotation.multVec(V(-5,0,0)); end = rotation.multVec(V(5,0,0))
        for sign in (-1,1):
            arc = arcs.two_point(start, end, normal*sign, 3)
            self.assertLess((arc.point(.5)-rotation.multVec(V(0,3*sign,0))).Length, 1e-7)
            self.assertTrue(arc.edge().isValid())

    def test_invalid_input(self):
        for angle in (0, 360, -360, math.nan, math.inf, True):
            with self.assertRaises(ValueError): arcs.centered(V(),V(1,0,0),V(0,0,1),angle)
        for height in (0, math.nan, math.inf, True):
            with self.assertRaises(ValueError): arcs.two_point(V(),V(1,0,0),V(0,0,1),height)
        for center,start,normal in ((V(),V(),V(0,0,1)),(V(),V(0,0,1),V(0,0,1)),(V(),V(1,0,0),V()),(V(math.nan,0,0),V(1,0,0),V(0,0,1))):
            with self.assertRaises(ValueError): arcs.centered(center,start,normal,90)
        with self.assertRaises(ValueError): arcs.two_point(V(),V(),V(0,0,1),1)
        with self.assertRaises(ValueError): arcs.two_point(V(),V(0,0,2),V(0,0,1),1)

    def test_preview_without_kernel_work(self):
        with patch.object(Part, 'Arc', side_effect=AssertionError('kernel preview')):
            for _ in range(100):
                self.assertGreater(len(arcs.two_point(V(),V(10,0,0),V(0,0,1),3).points()),8)

    def document(self):
        doc = App.newDocument('ArcTest'); doc.UndoMode = 1
        name = doc.Name
        self.addCleanup(lambda: App.closeDocument(name) if name in App.listDocuments() else None)
        return doc

    def test_arc_and_diameter_close_in_both_orders_undo_redo(self):
        for arc_last in (True,False):
            doc = self.document()
            edge = arcs.two_point(V(-5,0,0),V(5,0,0),V(0,0,1),5).edge()
            if arc_last:
                op.draw_line(doc,V(-5,0,0),V(5,0,0))
                count=doc.UndoCount
                result,changed=op.draw_arc(doc,edge)
            else:
                op.draw_arc(doc,edge); count=doc.UndoCount
                result,changed=op.draw_line(doc,V(-5,0,0),V(5,0,0))
            self.assertTrue(changed)
            self.assertEqual(len(doc.Objects),1)
            self.assertAlmostEqual(result.Shape.Area,math.pi*25/2,places=6)
            self.assertEqual(len(result.Shape.Faces),1)
            self.assertTrue(result.Shape.isValid())
            self.assertEqual(doc.UndoCount,count+1)
            doc.undo(); self.assertEqual(len(doc.Objects),1); self.assertEqual(len(doc.Objects[0].Shape.Faces),0)
            doc.redo(); self.assertEqual(len(doc.Objects[0].Shape.Faces),1)

    def test_two_arcs_close_circle(self):
        doc=self.document()
        for height in (5,-5):
            result,changed=op.draw_arc(doc,arcs.two_point(V(-5,0,0),V(5,0,0),V(0,0,1),height).edge())
        self.assertTrue(changed)
        self.assertEqual(len(doc.Objects),1)
        self.assertAlmostEqual(result.Shape.Area,math.pi*25,places=6)

    def test_radial_lines_close_sector_and_keep_branch(self):
        doc=self.document()
        op.draw_line(doc,V(),V(5,0,0)); op.draw_line(doc,V(),V(0,5,0))
        branch,_=op.draw_line(doc,V(),V(-2,0,0))
        result,changed=op.draw_arc(doc,arcs.centered(V(),V(5,0,0),V(0,0,1),90).edge())
        self.assertTrue(changed); self.assertEqual(len(doc.Objects),2)
        self.assertAlmostEqual(result.Shape.Area,math.pi*25/4,places=6)
        self.assertAlmostEqual(branch.Shape.Length,2)

    def test_arc_partitions_support_and_can_pull_region(self):
        doc=self.document(); host=op.new_shape(doc,Part.makeBox(20,20,10),'Box')
        result,changed=op.draw_arc(doc,arcs.two_point(V(0,0,10),V(20,0,10),V(0,0,1),5).edge(),host)
        self.assertTrue(changed); self.assertEqual(result,host)
        self.assertEqual(len(host.Shape.Faces),7); self.assertAlmostEqual(host.Shape.Volume,4000)
        region=min((f for f in host.Shape.Faces if abs(f.CenterOfMass.z-10)<1e-7),key=lambda f:f.Area)
        area=region.Area
        op.extrude(host,region,3)
        self.assertTrue(host.Shape.isValid() and host.Shape.isClosed())
        self.assertAlmostEqual(host.Shape.Volume,4000+area*3,places=5)

    def test_interior_loop_divides_face_when_line_finishes(self):
        doc=self.document(); host=op.new_shape(doc,Part.makeBox(20,20,10),'Box')
        arc,changed=op.draw_arc(doc,arcs.two_point(V(5,5,10),V(15,5,10),V(0,0,1),5).edge(),host)
        self.assertFalse(changed)
        result,changed=op.draw_line(doc,V(5,5,10),V(15,5,10),host)
        self.assertTrue(changed); self.assertEqual(result,host); self.assertEqual(len(doc.Objects),1)
        self.assertEqual(len(host.Shape.Faces),7); self.assertAlmostEqual(host.Shape.Volume,4000)

    def test_locked_support_rolls_back(self):
        doc=self.document(); host=op.new_shape(doc,Part.makeBox(20,20,10),'Box')
        locking.set_locked([(host,())],True)
        before=host.Shape.copy(); count=doc.UndoCount
        with self.assertRaises(ValueError):
            op.draw_arc(doc,arcs.two_point(V(0,0,10),V(20,0,10),V(0,0,1),5).edge(),host)
        self.assertAlmostEqual(host.Shape.Volume,before.Volume); self.assertEqual(len(host.Shape.Faces),6)
        self.assertEqual(doc.UndoCount,count)

    def test_native_persistence_and_duplicate_arc(self):
        doc=self.document(); edge=arcs.centered(V(),V(5,0,0),V(0,0,1),-270).edge()
        obj,_=op.draw_arc(doc,edge); again,_=op.draw_arc(doc,edge)
        self.assertEqual(obj,again); self.assertEqual(len(doc.Objects),1)
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'arc.FCStd'); doc.saveAs(path); App.closeDocument(doc.Name)
            copy=App.openDocument(path); self.addCleanup(lambda:App.closeDocument(copy.Name))
            self.assertIsInstance(copy.Objects[0].Shape.Edges[0].Curve,Part.Circle)
            self.assertAlmostEqual(copy.Objects[0].Shape.Length,edge.Length)
