"""Display layers own the view-provider nodes they keep between refreshes.

An Undo followed at once by a new edit can delete an object's view provider
before the next refresh lets go of its nodes; reading them then crashed.
"""
import unittest

from pivy import coin
from simplecad.gui import display, viewport_style as vs


def borrowed(kind):
    """A node held only by its parent and reached through getChild, as FreeCAD's are."""
    parent = coin.SoSeparator()
    parent.addChild(kind())
    return parent, parent.getChild(0)


class BorrowedNodeTests(unittest.TestCase):
    def test_masks_and_colours_hold_their_node_until_closed(self):
        holders = (
            (coin.SoIndexedLineSet, lambda node: display.EdgeMask(node, lambda: None), lambda held: held.close()),
            (coin.SoIndexedFaceSet, lambda node: display.FaceMask(node, lambda: None), lambda held: held.close()),
            (coin.SoMaterial, lambda node: vs.Recolour(node, lambda: None), lambda held: held.release()),
            (coin.SoMaterial, lambda node: vs.FaceRecolour(node, lambda: None), lambda held: held.release()),
            (coin.SoMaterial, lambda node: vs.Recolour(node, lambda: None), lambda held: held.detach()),
        )
        for kind, make, close in holders:
            with self.subTest(kind=kind.__name__):
                parent, node = borrowed(kind)
                self.assertEqual(node.getRefCount(), 1)
                held = make(node)
                self.assertEqual(node.getRefCount(), 2)
                close(held)
                self.assertEqual(node.getRefCount(), 1)

    def test_closing_after_the_view_provider_let_go_reads_a_live_node(self):
        edge_parent, edges = borrowed(coin.SoIndexedLineSet)
        edges.coordIndex.setValues(0, 6, [0, 1, -1, 1, 2, -1])
        mask = display.EdgeMask(edges, lambda: None)
        mask.apply({0}, 2)
        material_parent, material = borrowed(coin.SoMaterial)
        recolour = vs.Recolour(material, lambda: None)
        recolour.apply((.8, .8, .8), (1., 0., 0.))
        self.assertEqual(tuple(material.diffuseColor[0].getValue()), (1., 0., 0.))
        # The view provider is deleted: its nodes now live only through the holders.
        del edge_parent, material_parent
        self.assertEqual((edges.getRefCount(), material.getRefCount()), (1, 1))
        mask.close()
        recolour.release((.8, .8, .8))
        mask.close()  # a second close is harmless


if __name__ == "__main__":
    unittest.main()
