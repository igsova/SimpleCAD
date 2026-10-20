"""Keep class definitions out of FreeCAD's function-local exec namespace."""
import FreeCADGui as Gui
from simplecad.gui.workbench import SimpleCADWorkbench

Gui.addWorkbench(SimpleCADWorkbench())
