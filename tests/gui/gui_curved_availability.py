"""Flat-only tools grey out on curved faces, using real Part shapes and selection."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.gui import command_state
from simplecad.gui.controller import instance


def active(key):
    command_state.current(fresh=True)
    return Gui.Command.get('SimpleCAD_' + key).isActive()


def run():
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument('CurvedAvailabilityTest')
    try:
        box = Part.makeBox(20, 20, 20)
        rounded = doc.addObject('Part::Feature', 'Rounded')
        rounded.Shape = box.makeFillet(3, [box.Edges[0]])
        free = doc.addObject('Part::Feature', 'Freeform')
        free.Shape = Part.makeSphere(8, App.Vector(50, 0, 0)).Faces[0].toNurbs()
        doc.recompute()
        shape = rounded.Shape
        flat = next('Face%d' % i for i, f in enumerate(shape.Faces, 1) if isinstance(f.Surface, Part.Plane))
        cylinder = next('Face%d' % i for i, f in enumerate(shape.Faces, 1) if isinstance(f.Surface, Part.Cylinder))
        corner = next('Vertex%d' % i for i, v in enumerate(shape.Vertexes, 1)
                      if all(isinstance(f.Surface, Part.Plane) for f in shape.ancestorsOfType(v, Part.Face)))
        rounded_corner = next('Vertex%d' % i for i, v in enumerate(shape.Vertexes, 1)
                              if any(isinstance(f.Surface, Part.Cylinder) for f in shape.ancestorsOfType(v, Part.Face)))

        def pick(obj, name):
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(obj, name)

        pick(rounded, flat)
        for key in ('PushPull', 'Subdivide', 'Offset', 'Elongate', 'SelectFlat'):
            assert active(key), key
        pick(rounded, cylinder)
        for key in ('PushPull', 'Subdivide'):
            assert not active(key), key
        for key in ('Offset', 'Elongate', 'SelectHole', 'SmartSelect', 'Round'):
            assert active(key), key
        pick(free, 'Face1')
        for key in ('PushPull', 'Subdivide', 'Offset', 'Elongate', 'SelectHole', 'SelectFlat'):
            assert not active(key), key
        for key in ('SmartSelect', 'SelectSmooth', 'Deform', 'Appearance', 'Measure', 'Rotate'):
            assert active(key), key
        assert 'flat face' in command_state.reason('PushPull', command_state.current(fresh=True))
        pick(rounded, corner)
        assert active('VertexMove')
        pick(rounded, rounded_corner)
        assert not active('VertexMove')
        # The shape changes under the same selection name: kinds follow the new shape.
        pick(rounded, cylinder)
        assert not active('PushPull')
        rounded.Shape = box
        doc.recompute()
        pick(rounded, cylinder)  # the same face number on the plain box is flat
        assert active('PushPull')
        Gui.Selection.clearSelection()
        assert active('PushPull')  # still available to pick a face after starting
        App.Console.PrintMessage('PASS: curved availability\n')
    finally:
        Gui.Selection.clearSelection()
        App.closeDocument(doc.Name)
