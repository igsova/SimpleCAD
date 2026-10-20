"""The sizes shown beside a Line, Rectangle, Circle, Sphere or Polygon while it is drawn."""
import math
import unittest
from unittest.mock import patch

import FreeCAD as App
from pivy import coin
from simplecad.gui.previews.overlay import AXIS_COLORS, LINE_COLOR, Preview, beside, halfway

V = App.Vector


class FakeView:
    """Looks down -Z; one model millimetre is ten screen pixels."""
    def __init__(self):
        self.graph = coin.SoSeparator()

    def getSceneGraph(self):
        return self.graph

    def getViewDirection(self):
        return V(0, 0, -1)

    def getPointOnScreen(self, point):
        return point.x * 10, point.y * 10

    def redraw(self):
        pass


def ray(view, pos):
    return V(pos[0] / 10, pos[1] / 10, 100), V(0, 0, -1)


class HalfwayTests(unittest.TestCase):
    def test_a_line_is_labelled_at_its_midpoint(self):
        middle, segment = halfway([V(2, 4, 6), V(12, 4, 6)])
        self.assertLess((middle - V(7, 4, 6)).Length, 1e-12)
        self.assertEqual(segment, (V(2, 4, 6), V(12, 4, 6)))

    def test_a_surface_line_is_labelled_half_way_along_it(self):
        middle, segment = halfway([V(), V(10, 0, 0), V(10, 30, 0)])
        self.assertLess((middle - V(10, 10, 0)).Length, 1e-12)
        self.assertEqual(segment, (V(10, 0, 0), V(10, 30, 0)))

    def test_a_line_without_length_has_no_label(self):
        self.assertEqual(halfway([V(1, 1, 1), V(1, 1, 1)]), (None, None))
        self.assertEqual(halfway([V(1, 1, 1)]), (None, None))


class BesideTests(unittest.TestCase):
    def test_the_text_sits_above_a_flat_line_and_right_of_an_upright_one(self):
        x, y = beside((0, 0), (100, 0), (50, 0), "25.00 mm")
        self.assertEqual(x, 50)
        self.assertGreater(y, 5)
        for end in ((0, 100), (0, -100)):
            x, y = beside((0, 0), end, (0, 50 if end[1] > 0 else -50), "25.00 mm")
            self.assertGreater(x, 32)
        # Drawn leftwards the text still goes up the screen.
        self.assertGreater(beside((100, 0), (0, 0), (50, 0), "25.00 mm")[1], 5)

    def test_the_text_goes_to_the_side_away_from_a_point(self):
        # The sides of a rectangle: the text goes outside it.
        self.assertLess(beside((0, 0), (100, 0), (50, 0), "25.00 mm", away=(100, 40))[1], -5)
        self.assertGreater(beside((0, 0), (100, 0), (50, 0), "25.00 mm", away=(100, -40))[1], 5)
        self.assertGreater(beside((100, 0), (100, 40), (100, 20), "25.00 mm", away=(0, 0))[0], 132)
        self.assertLess(beside((100, 0), (100, 40), (100, 20), "25.00 mm", away=(200, 0))[0], 68)
        # A point on the line itself does not choose a side.
        self.assertEqual(beside((0, 0), (100, 0), (50, 0), "25.00 mm", away=(80, 0)),
                         beside((0, 0), (100, 0), (50, 0), "25.00 mm"))

    def test_the_text_clears_the_line_at_every_angle(self):
        text = "1234.56 mm"
        for ratio in (1.0, 2.0):
            width, height = 8 * len(text) * ratio, 10 * ratio
            for degrees in range(0, 360, 5):
                angle = math.radians(degrees)
                end = (300 * math.cos(angle), 300 * math.sin(angle))
                middle = (end[0] / 2, end[1] / 2)
                for away in (None, (-50 * math.sin(angle), 50 * math.cos(angle)),
                             (50 * math.sin(angle), -50 * math.cos(angle))):
                    cx, cy = beside((0, 0), end, middle, text, ratio, away)
                    # Signed distance of each corner of the text box from the line.
                    gaps = [(math.cos(angle) * (cy + sy * height / 2) - math.sin(angle) * (cx + sx * width / 2))
                            for sx in (-1, 1) for sy in (-1, 1)]
                    with self.subTest(ratio=ratio, degrees=degrees, away=away):
                        self.assertTrue(all(gap > 0 for gap in gaps) or all(gap < 0 for gap in gaps))
                        self.assertAlmostEqual(min(abs(gap) for gap in gaps), 6 * ratio, places=9)
                        if away is not None:
                            # Opposite sides of the line from the point.
                            side = math.cos(angle) * away[1] - math.sin(angle) * away[0]
                            self.assertLess(gaps[0] * side, 0)


class LengthLabelTests(unittest.TestCase):
    def test_preview_shows_the_length_beside_the_line_and_hides_it_after(self):
        view = FakeView()
        with patch("simplecad.gui.previews.overlay.ray", ray):
            preview = Preview(view)
            self.assertEqual(preview.length_labels, [])
            points = [V(0, 0, 7), V(25, 0, 7)]
            preview.update([points], points[1], lengths=[(points, "25.00 mm")])
            label, = preview.length_labels
            self.assertEqual(label.switch.whichChild.getValue(), 0)
            self.assertEqual([text.string.getValues()[0] for text in label.texts], ["25.00 mm"] * 2)
            self.assertEqual(label.texts[1].justification.getValue(), coin.SoText2.CENTER)
            at = V(*label.positions[1].translation.getValue())
            self.assertAlmostEqual(at.x, 12.5, places=5)
            self.assertAlmostEqual(at.z, 7, places=5)
            self.assertGreater(at.y, 0)
            self.assertLess(at.y, 3)
            self.assertEqual(tuple(label.colors[1].rgb[0].getValue()), tuple(float(c) for c in coin.SbColor(*LINE_COLOR)))
            # An axis-locked line colors its label too.
            preview.update([points], points[1], axis="X", lengths=[(points, "25.00 mm")])
            self.assertEqual(tuple(label.colors[1].rgb[0].getValue()),
                             tuple(float(c) for c in coin.SbColor(*AXIS_COLORS["X"])))
            preview.update([points], points[1])
            self.assertEqual(label.switch.whichChild.getValue(), coin.SO_SWITCH_NONE)
            preview.update([points], points[1], lengths=[(points[:1], "0.00 mm")])
            self.assertEqual(label.switch.whichChild.getValue(), coin.SO_SWITCH_NONE)
            preview.close()

    def test_a_typed_length_relabels_the_line_until_the_next_update(self):
        view = FakeView()
        with patch("simplecad.gui.previews.overlay.ray", ray):
            preview = Preview(view)
            preview.relabel(["80.00 mm"])  # Nothing drawn: nothing to label.
            self.assertEqual(preview.length_labels, [])
            points = [V(0, 0, 7), V(25, 0, 7)]
            preview.update([points], points[1], axis="X", lengths=[(points, "25.00 mm")])
            label, = preview.length_labels
            drawn = [tuple(p) for p in [preview.coords.point[i].getValue() for i in range(2)]]
            at = V(*label.positions[1].translation.getValue())
            preview.relabel(["80.00 mm"])
            self.assertEqual([text.string.getValues()[0] for text in label.texts], ["80.00 mm"] * 2)
            self.assertEqual(label.switch.whichChild.getValue(), 0)
            # Same line, same color; the text moves only by its own width.
            self.assertEqual([tuple(p) for p in [preview.coords.point[i].getValue() for i in range(2)]], drawn)
            self.assertEqual(tuple(label.colors[1].rgb[0].getValue()),
                             tuple(float(c) for c in coin.SbColor(*AXIS_COLORS["X"])))
            self.assertAlmostEqual(label.positions[1].translation.getValue()[0], at.x, places=5)
            preview.relabel([None])
            self.assertEqual(label.texts[1].string.getValues()[0], "25.00 mm")
            preview.relabel(["80.00 mm"])
            preview.update([points], points[1], lengths=[(points, "25.00 mm")])
            self.assertEqual(label.texts[1].string.getValues()[0], "25.00 mm")
            preview.update([points], points[1])
            preview.relabel(["80.00 mm"])
            self.assertEqual(label.switch.whichChild.getValue(), coin.SO_SWITCH_NONE)
            preview.close()

    def test_a_rectangle_shows_width_and_height_outside_it(self):
        view = FakeView()
        with patch("simplecad.gui.previews.overlay.ray", ray):
            preview = Preview(view)
            a, b, c, d = V(0, 0, 7), V(40, 0, 7), V(40, 30, 7), V(0, 30, 7)
            sizes = [([a, b], "40.00 mm", c), ([b, c], "30.00 mm", a)]
            preview.update([[a, b, c, d, a]], c, lengths=sizes)
            width, height = preview.length_labels

            def shown(label):
                if label.switch.whichChild.getValue() != 0:
                    return None
                return label.texts[1].string.getValues()[0], V(*label.positions[1].translation.getValue())
            self.assertEqual(shown(width)[0], "40.00 mm")
            self.assertAlmostEqual(shown(width)[1].x, 20, places=5)
            self.assertLess(shown(width)[1].y, 0)  # Below the bottom side, outside.
            self.assertEqual(shown(height)[0], "30.00 mm")
            self.assertAlmostEqual(shown(height)[1].y, 15 - 0.4, places=5)
            self.assertGreater(shown(height)[1].x, 40)  # Right of the right side.
            # Typed sizes: the width first, then both; an empty one keeps its own.
            preview.relabel(["25.00 mm"])
            self.assertEqual([shown(width)[0], shown(height)[0]], ["25.00 mm", "30.00 mm"])
            preview.relabel([None, "12 c"])
            self.assertEqual([shown(width)[0], shown(height)[0]], ["40.00 mm", "12 c"])
            preview.update([[a, b, c, d, a]], c, lengths=sizes)
            self.assertEqual([shown(width)[0], shown(height)[0]], ["40.00 mm", "30.00 mm"])
            # A shape with one size hides the second label.
            preview.update([[a, c]], c, lengths=[([a, c], "R 50.00 mm")])
            self.assertEqual(shown(width)[0], "R 50.00 mm")
            self.assertIsNone(shown(height))
            preview.relabel(["R 2.00 mm", "3.00 mm"])
            self.assertEqual(shown(width)[0], "R 2.00 mm")
            self.assertIsNone(shown(height))
            self.assertEqual(len(preview.length_labels), 2)
            preview.close()


if __name__ == "__main__":
    unittest.main()
