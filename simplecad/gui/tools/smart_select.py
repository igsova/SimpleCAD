"""Smart selection commands and Isolate selection; neither edits the model."""
import FreeCAD as App
import FreeCADGui as Gui

from ...inspection import smart_select
from ...mesh.conversion import is_mesh
from .selection import visible_names

KIND_TEXT = {'hole': 'hole or cylinder wall', 'loop': 'edge loop', 'flat': 'flat region', 'smooth': 'smooth surface'}
_isolated = {}  # document name -> names of the objects Isolate hid


def expand_selection(controller, mode):
    """Grow every selected face or edge into mode and select the result."""
    doc = App.ActiveDocument
    picked = [(item.Object, name) for item in Gui.Selection.getSelectionEx()
              if doc is not None and item.Object.Document == doc and hasattr(item.Object, 'Shape')
              for name in item.SubElementNames if name.startswith(('Face', 'Edge'))]
    if not picked:
        raise ValueError('Select a face or an edge first, or double-click one.')
    view = Gui.activeDocument().activeView()
    grown, kinds = {}, set()
    for obj, name in picked:
        names, kind = smart_select.expand(obj.Shape, name, mode, view.getViewDirection())
        grown.setdefault(obj, set()).update(visible_names(obj, names))
        kinds.add(kind)
    hits = [(obj, name) for obj, names in grown.items() for name in sorted(names, key=natural)]
    hits = controller.selection.filtered(hits)
    controller.selection.apply(hits, 0)
    controller.message('Selected %s · %d elements · Delete removes them; Measure reads a hole' % (
        ' and '.join(KIND_TEXT[kind] for kind in sorted(kinds)), len(hits)))


def natural(name):
    kind = name.rstrip('0123456789')
    return kind, int(name[len(kind):] or 0)


def isolate(controller):
    """Hide every other shape, or bring them back when already isolated."""
    doc = App.ActiveDocument
    if doc is None:
        raise ValueError('Open a model first.')
    hidden = _isolated.pop(doc.Name, None)
    if hidden is not None:
        for name in hidden:
            obj = doc.getObject(name)
            if obj is not None and obj.ViewObject is not None:
                obj.ViewObject.Visibility = True
        controller.message('Showing everything again')
        return False
    keep = {item.Object.Name for item in Gui.Selection.getSelectionEx() if item.Object.Document == doc}
    if not keep:
        raise ValueError('Select the objects to isolate first.')
    hidden = [obj.Name for obj in doc.Objects
              if obj.Name not in keep and obj.ViewObject is not None and obj.ViewObject.Visibility
              and (hasattr(obj, 'Shape') or is_mesh(obj))]
    for name in hidden:
        doc.getObject(name).ViewObject.Visibility = False
    _isolated[doc.Name] = hidden
    controller.message('Isolated %d object(s) · Isolate again shows everything · The model is unchanged' % len(keep))
    return True


def forget_document(name):
    _isolated.pop(name, None)
