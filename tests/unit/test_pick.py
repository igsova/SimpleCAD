"""Resolve only the winning ordinary hit while preserving picking rules."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import FreeCAD as App
import Part
from simplecad.gui.snapping import pick


class PickTests(unittest.TestCase):
    def setUp(self):
        shape = Part.makeBox(10, 10, 10)
        self.resolve = Mock(side_effect=shape.getElement)
        self.obj = SimpleNamespace(Name='Shape', PropertiesList=[], Shape=SimpleNamespace(getElement=self.resolve))
        self.doc = SimpleNamespace(Name='Doc', getObject=lambda name: self.obj if name == 'Shape' else None)

    def hit(self, name='Face1', **changes):
        value = dict(Document='Doc', Object='Shape', Component=name, x=0, y=0, z=0)
        value.update(changes)
        return value

    def run_pick(self, hits, **kwargs):
        view = SimpleNamespace(getObjectsInfo=lambda pos: hits)
        with patch('simplecad.gui.snapping.visibility.element_visible', return_value=True):
            return pick(view, self.doc, (10, 10), **kwargs)

    def test_hundreds_of_occluded_faces_only_resolve_the_first_hit(self):
        result = self.run_pick([self.hit('Face2')] + [self.hit('Face1') for _ in range(400)])
        self.assertEqual(result[3], 'Face2')
        self.resolve.assert_called_once_with('Face2')

    def test_invalid_and_foreign_hits_do_not_mask_a_valid_face(self):
        missing_position = self.hit()
        del missing_position['x']
        result = self.run_pick([self.hit(Document='Other'), self.hit(Object='Missing'),
                                self.hit('Body.Face1'), missing_position, self.hit('Face99'),
                                self.hit('Edge1'), self.hit('Face3')], face_only=True)
        self.assertEqual(result[3], 'Face3')

    def test_hidden_front_hit_does_not_mask_visible_hit(self):
        view = SimpleNamespace(getObjectsInfo=lambda pos: [self.hit('Face1'), self.hit('Face2')])
        with patch('simplecad.gui.snapping.visibility.element_visible', side_effect=lambda obj,name:name!='Face1'):
            result = pick(view, self.doc, (10,10))
        self.assertEqual(result[3], 'Face2')
        self.resolve.assert_called_once_with('Face2')

    def test_support_profile_keeps_priority(self):
        profile = SimpleNamespace(Name='Profile', PropertiesList=['SC_Support'], Shape=Part.makePlane(2,2))
        self.doc.getObject = lambda name: profile if name=='Profile' else self.obj
        result = self.run_pick([self.hit(), self.hit(Object='Profile')])
        self.assertIs(result[0], profile)
        self.resolve.assert_not_called()
