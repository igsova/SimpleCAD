"""Viewport style arithmetic: grid extent, FreeCAD's background, face and edge colours."""
from dataclasses import asdict, replace
import math
import unittest
from unittest.mock import patch

import FreeCAD as App
from simplecad.core import preferences as prefs
from simplecad.gui import viewport_style as vs
from simplecad.mcp.catalog import SETTINGS, validate


class Params:
    def __init__(self, **values):
        self.values = values

    def GetBool(self, name, default):
        return self.values.get(name, default)

    def GetUnsigned(self, name, default):
        return self.values.get(name, default)


def normal(*vector):
    length = math.sqrt(sum(c*c for c in vector))
    return tuple(c/length for c in vector)


class GridTests(unittest.TestCase):
    def test_spacing_is_a_power_of_ten_with_at_most_forty_cells(self):
        for size, step in ((90, 10), (400, 10), (401, 100), (0.05, 0.01), (1e-6, 0.001), (1e9, 1e5)):
            with self.subTest(size=size):
                self.assertAlmostEqual(vs.spacing(size), step)
        for size in (0.3, 7, 55, 1234, 98765):
            step = vs.spacing(size)
            self.assertLessEqual(size / step, vs.CELLS + 1e-9)
            self.assertGreater(size / step, vs.CELLS / 10)

    def corners_inside(self, position, direction, height, aspect):
        """Every ortho view corner that sees the ground lands on the grid."""
        step, centre, cells = vs.grid_plan(position, direction, height, aspect)
        up = normal(*App.Vector(0, 0, 1).cross(App.Vector(*direction)).cross(App.Vector(*direction)) * -1) \
            if abs(direction[2]) < 0.999 else (0., 1., 0.)
        right = tuple(App.Vector(*direction).cross(App.Vector(*up)))
        width = height * aspect
        for sx in (-1, 1):
            for sy in (-1, 1):
                start = [p + r*sx*width/2 + u*sy*height/2 for p, r, u in zip(position, right, up)]
                t = -start[2] / direction[2]
                hit = (start[0] + t*direction[0], start[1] + t*direction[1])
                self.assertLessEqual(max(abs(hit[0]-centre[0]), abs(hit[1]-centre[1])), cells*step, (sx, sy))
        return step, centre, cells

    def test_grid_fills_top_and_isometric_views(self):
        step, centre, cells = self.corners_inside((3, 4, 100), (0, 0, -1), 90, 1.0)
        self.assertEqual((step, centre), (10, (0, 0)))
        iso = normal(-1, 1, -1)
        step, centre, _ = self.corners_inside(tuple(-50*c for c in iso), iso, 78.75, 2000/1750)
        self.assertEqual(step, 10)
        self.assertEqual(centre, (0, 0))
        for direction in (normal(1, 2, -0.5), normal(-3, 1, -1), normal(0.2, -1, 0.4)):
            with self.subTest(direction=direction):
                self.corners_inside((40 - 200*direction[0], -10 - 200*direction[1], -200*direction[2]),
                                    direction, 120, 1.6)

    def test_grazing_and_upward_views_stay_near_the_focus(self):
        step, centre, cells = vs.grid_plan((0, 0, 10), normal(1, 0, -1e-4), 50, 1.0, False, 100)
        self.assertLessEqual(math.hypot(centre[0] - 100, centre[1]), 10*50 + step)
        self.assertLessEqual(cells, 11*50/step + 1)
        step, centre, _ = vs.grid_plan((7, 3, 10), normal(0, 0, 1), 50, 1.0, True, 20)
        self.assertEqual(centre, (10, 0))
        step, centre, _ = vs.grid_plan((0, 0, 10), (1, 0, 0), 50, 1.0, True, 100)
        self.assertEqual(centre, (100, 0))

    def test_built_grid_is_reused_until_the_view_leaves_it(self):
        needed = (10., (0., 0.), 20)
        built = (10., (0., 0.), 28)
        self.assertTrue(vs.covers(built, needed))
        self.assertTrue(vs.covers(built, (10., (80., 0.), 20)))
        self.assertFalse(vs.covers(built, (10., (90., 0.), 20)))
        self.assertFalse(vs.covers(built, (100., (0., 0.), 3)))
        self.assertFalse(vs.covers((10., (0., 0.), 200), needed))

    def test_grid_and_axis_segments(self):
        points = vs.grid_points(10., (20., -30.), 3)
        self.assertEqual(len(points), 4 * 7)
        self.assertTrue(all(p[2] == 0 for p in points))
        self.assertEqual(min(p[0] for p in points), -10)
        self.assertEqual(max(p[1] for p in points), 0)
        self.assertIn((50., -60., 0.), points)
        axes = vs.axis_points(10., (20., -30.), 3)
        self.assertEqual(axes, [(-10., 0., 0.), (50., 0., 0.), (0., -60., 0.), (0., 0., 0.), (0., 0., -30.), (0., 0., 30.)])


class ColourTests(unittest.TestCase):
    def test_freecad_background_follows_its_preferences(self):
        self.assertEqual(vs.unpack(0xF7F7F7FF), (247/255,) * 3)
        simple = Params(Gradient=False, RadialGradient=False, BackgroundColor=0xF7F7F7FF)
        style, colours = vs.freecad_background(simple)
        self.assertEqual(style, "NONE")
        self.assertEqual(colours[0], (247/255,) * 3)
        self.assertEqual(len(colours), 3)
        style, colours = vs.freecad_background(Params(Gradient=False, RadialGradient=True,
                                                      UseBackgroundColorMid=True, BackgroundColor4=0x102030FF))
        self.assertEqual(style, "RADIAL")
        self.assertEqual(colours[3], (16/255, 32/255, 48/255))
        self.assertEqual(vs.freecad_background(Params())[0], "LINEAR")

    def test_only_default_edge_colours_are_restyled(self):
        defaults = (vs.SIMPLECAD_EDGE, vs.unpack(421075455))
        self.assertEqual(vs.edge_colour((0.15, 0.23, 0.29), defaults, True, "Flat Lines"), vs.EDGE)
        self.assertEqual(vs.edge_colour((0.098, 0.098, 0.098), defaults, True, "Flat Lines"), vs.EDGE)
        self.assertEqual(vs.edge_colour((0.15, 0.23, 0.29), defaults, True, "Wireframe"), vs.LOOSE)
        self.assertEqual(vs.edge_colour((0.15, 0.23, 0.29), defaults, False, "Flat Lines"), vs.LOOSE)
        self.assertIsNone(vs.edge_colour((1., 0., 0.), defaults, True, "Flat Lines"))

    def test_loose_lines_lying_on_a_face_count_as_on_it(self):
        import Part
        V = App.Vector
        top = [face for face in Part.makeBox(10, 10, 10).Faces if face.CenterOfMass.z > 9.9]
        on, above = Part.makeLine(V(2, 2, 10), V(8, 2, 10)), Part.makeLine(V(2, 2, 11), V(8, 2, 11))
        arc = Part.makeCircle(3, V(5, 5, 10))
        self.assertTrue(vs.on_faces([on, arc], top))
        self.assertFalse(vs.on_faces([above], top))
        # Every edge has to lie on a face; a line off the box keeps the loose colour.
        self.assertFalse(vs.on_faces([on, Part.makeLine(V(12, 2, 10), V(18, 2, 10))], top))
        self.assertFalse(vs.on_faces([on], []))
        self.assertFalse(vs.on_faces([], top))

    def test_only_default_face_colours_take_the_face_colour(self):
        defaults = vs.face_defaults(Params(), Params())
        self.assertEqual(defaults, (vs.SIMPLECAD_FACE, vs.unpack(vs.FREECAD_FACE), vs.unpack(vs.FREECAD_FACE)))
        self.assertEqual(vs.face_defaults(Params(DefaultShapeColor=0x102030FF), Params(MeshColor=0x405060FF))[1:],
                         ((16/255, 32/255, 48/255), (64/255, 80/255, 96/255)))
        red, white, blue = (1., 0., 0.), (1., 1., 1.), (0.2, 0.4, 0.9)
        # SimpleCAD's and FreeCAD's default (float32-rounded) become the face colour; red stays.
        values = [(0.7599999904632568, 0.8399999737739563, 0.8799999952316284), red,
                  (0.67843097448349, 0.7098039984703064, 0.7411760091781616)]
        self.assertEqual(vs.shown_faces(values, white, defaults), ([white, red, white], [0, 2]))
        # Faces already drawn in the previous face colour follow a new one.
        self.assertEqual(vs.shown_faces([white, red, white], blue, defaults, {0, 2}), ([blue, red, blue], [0, 2]))
        self.assertEqual(vs.shown_faces([red], white, defaults), ([red], []))

    def test_lights_give_sketchup_like_greys_on_white_faces(self):
        # Each face of an isometric box faces one light; ambient adds 0.2 * 1/3.
        diffuse, ambient = (1., 1., 1.), vs.AMBIENT[0] / 3
        faces = {"top": ((0, 0.816, 0.577), (0.94,) * 3),
                 "left": ((-0.707, -0.408, 0.577), (0.78,) * 3),
                 "right": ((0.707, -0.408, 0.577), (0.56,) * 3)}
        for name, (normal_, expected) in faces.items():
            colour = [ambient] * 3
            for direction, light in vs.LIGHTS:
                facing = max(0., -sum(n*d for n, d in zip(normal_, direction)))
                colour = [c + facing*l*m for c, l, m in zip(colour, light, diffuse)]
            with self.subTest(face=name):
                self.assertTrue(all(abs(a - b) < 0.01 for a, b in zip(colour, expected)), (colour, expected))


class HighlightTests(unittest.TestCase):
    def test_tints_stay_coloured_on_lit_white_faces(self):
        selection, hover = (0.231, 0.357, 0.859), (0., 0.478, 0.)
        # Lit like a white top face, a tint keeps its hue and stays below white.
        for highlight in (selection, hover):
            shown = [0.873 * value + vs.AMBIENT[0] / 3 for value in vs.tint(highlight)]
            self.assertLess(max(shown), 0.95)
            self.assertEqual(shown.index(max(shown)), list(highlight).index(max(highlight)))
            self.assertGreater(max(shown) - min(shown), 0.2)
        # A mesh adds FreeCAD's highlight to its colour, so the two add to the tint.
        for highlight in (selection, hover):
            self.assertTrue(all(abs(a + b - c) < 1e-9 for a, b, c in
                                zip(vs.mesh_tint(highlight), highlight, vs.tint(highlight))))

    def test_face_ranges_follow_triangle_counts(self):
        self.assertEqual(vs.face_ranges((2, 1, 0, 3), 24), [(0, 8), (8, 12), (12, 12), (12, 24)])
        self.assertIsNone(vs.face_ranges((2, 1), 16))
        self.assertIsNone(vs.face_ranges((2, -1), 4))

    def test_targets_from_selection_and_preselection(self):
        targets = vs.highlight_targets(
            [("Doc", "Box", ("Face2", "Edge1")), ("Doc", "Mesh", ()), ("Doc", "Body", ("Pad.Face3",)),
             ("Doc", "Part", ("Pad.",))],
            ("Doc", "Box", ("Face5",)))
        self.assertEqual(targets, {("Doc", "Box"): ({"Face2", "Edge1"}, {"Face5"}),
                                   ("Doc", "Mesh"): ({""}, set()),
                                   ("Doc", "Pad"): ({"Face3", ""}, set())})
        self.assertEqual(vs.highlight_targets([], ("Doc", "Mesh", ("",))), {("Doc", "Mesh"): (set(), {""})})
        self.assertEqual(vs.highlight_targets([], None), {})


class SettingTests(unittest.TestCase):
    def test_viewport_style_is_on_by_default_and_saved(self):
        path = "User parameter:BaseApp/Preferences/Mod/SimpleCAD_TestViewportStyle"
        parent = App.ParamGet("User parameter:BaseApp/Preferences/Mod")
        parent.RemGroup("SimpleCAD_TestViewportStyle")
        try:
            with patch.object(prefs, "PARAMETER_PATH", path):
                self.assertTrue(prefs.load().viewport_style)
                prefs.save(replace(prefs.Settings(), viewport_style=False))
                self.assertFalse(prefs.load().viewport_style)
                self.assertFalse(App.ParamGet(path).GetBool("viewport_style", True))
        finally:
            parent.RemGroup("SimpleCAD_TestViewportStyle")

    def test_face_color_is_light_grey_by_default_and_saved_as_hex(self):
        path = "User parameter:BaseApp/Preferences/Mod/SimpleCAD_TestFaceColor"
        parent = App.ParamGet("User parameter:BaseApp/Preferences/Mod")
        parent.RemGroup("SimpleCAD_TestFaceColor")
        try:
            with patch.object(prefs, "PARAMETER_PATH", path):
                self.assertEqual(prefs.load().face_color, "#E3E3EC")
                self.assertEqual(prefs.color(prefs.load().face_color), vs.FACE)
                prefs.save(replace(prefs.Settings(), face_color="#ffd27f"))
                self.assertEqual(prefs.load().face_color, "#FFD27F")
                self.assertEqual(prefs.color("#FFD27F"), (1., 210/255, 127/255))
                # A malformed colour saves nothing, not even the other settings.
                with self.assertRaises(ValueError):
                    prefs.save(replace(prefs.Settings(), show_seams=True, face_color="white"))
                self.assertEqual(prefs.load(), replace(prefs.Settings(), face_color="#FFD27F"))
                # A hand-edited, malformed stored value reads as the default.
                App.ParamGet(path).SetString("face_color", "#12")
                self.assertEqual(prefs.load().face_color, "#E3E3EC")
        finally:
            parent.RemGroup("SimpleCAD_TestFaceColor")

    def test_mcp_settings_schema_accepts_every_setting(self):
        self.assertEqual(set(SETTINGS['properties']), set(asdict(prefs.Settings())))
        self.assertEqual(SETTINGS['properties']['viewport_style']['type'], 'boolean')
        validate({'face_color': '#A0b1C2'}, SETTINGS)
        for wrong in ('white', '#FFF', '#GGGGGG', 'FFFFFF'):
            with self.subTest(colour=wrong), self.assertRaises(ValueError):
                validate({'face_color': wrong}, SETTINGS)


if __name__ == "__main__":
    unittest.main()
