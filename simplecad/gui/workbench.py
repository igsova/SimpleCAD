"""Workbench definition with normal module scope, independent of the loader."""
import FreeCADGui as Gui
from .. import ROOT


class SimpleCADWorkbench(Gui.Workbench):
    MenuText = "SimpleCAD"
    ToolTip = "Draw, pull, and move shapes directly"
    Icon = str(ROOT / "Resources" / "icons" / "workbench.svg")

    def Initialize(self):
        from .commands import GROUPS, MENU_EXTRAS, names, register
        self.commands = register()
        for group, keys in GROUPS:
            self.appendToolbar('SimpleCAD ' + group, names(keys))
            self.appendMenu(['SimpleCAD', group], names(keys + MENU_EXTRAS.get(group, ())))
        self.appendMenu('SimpleCAD', names(('Separator', 'Settings', 'MCP')))

    def Activated(self):
        from .controller import instance
        instance().activate()
        from .toolbar import schedule
        schedule()

    def ContextMenu(self, recipient):
        from .command_state import context_groups
        from .commands import names
        for group, keys in context_groups():
            self.appendContextMenu(['SimpleCAD', group], names(keys))

    def Deactivated(self):
        from .controller import instance
        instance().deactivate()

    def GetClassName(self):
        return "Gui::PythonWorkbench"
