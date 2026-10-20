"""Exercise InitGui with separate loader globals and locals, as at startup.

No Qt or FreeCAD process is needed; only the registration boundary is stubbed.
"""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


class StartupTests(unittest.TestCase):
    def load_workbench(self, separate_namespaces):
        gui = types.ModuleType("FreeCADGui")
        gui.Workbench = type("Workbench", (), {})
        gui.addWorkbench = Mock()
        package = __import__("simplecad.gui", fromlist=["gui"])
        previous = sys.modules.pop("simplecad.gui.workbench", None)
        previous_attribute = getattr(package, "workbench", None)
        try:
            with patch.dict(sys.modules, {"FreeCADGui": gui}):
                globals_dict = {"__name__": "FreeCADGuiInit", "Workbench": gui.Workbench}
                locals_dict = {} if separate_namespaces else globals_dict
                path = ROOT / "InitGui.py"
                exec(compile(path.read_text(), str(path), "exec"), globals_dict, locals_dict)
                gui.addWorkbench.assert_called_once()
                workbench = gui.addWorkbench.call_args.args[0]
                self.assertIsInstance(workbench, gui.Workbench)
                self.assertEqual(type(workbench).__name__, "SimpleCADWorkbench")
                self.assertEqual(workbench.MenuText, "SimpleCAD")
                self.assertEqual(workbench.GetClassName(), "Gui::PythonWorkbench")
                self.assertEqual(Path(workbench.Icon), ROOT / "Resources/icons/workbench.svg")
                self.assertTrue(Path(workbench.Icon).is_file())
                # Hooks must resolve their own imports after the loader scope is gone.
                if separate_namespaces:
                    locals_dict.clear()
                commands = types.ModuleType("simplecad.gui.commands")
                commands.register = Mock(return_value=["SimpleCAD_Select"])
                commands.GROUPS = (('Draw', ('Select',)), ('Mesh', ('MeshSplit',)))
                commands.MENU_EXTRAS = {}
                commands.names = lambda keys: [k if k == 'Separator' else 'SimpleCAD_' + k for k in keys]
                toolbar = types.ModuleType('simplecad.gui.toolbar')
                toolbar.schedule = Mock()
                controller = types.ModuleType("simplecad.gui.controller")
                controller.instance = Mock()
                workbench.appendToolbar = Mock()
                workbench.appendMenu = Mock()
                with patch.dict(sys.modules, {"simplecad.gui.commands": commands,
                                              "simplecad.gui.toolbar": toolbar,
                                              "simplecad.gui.controller": controller}):
                    workbench.Initialize()
                    workbench.Activated()
                    workbench.Deactivated()
                self.assertEqual(workbench.appendToolbar.call_count, 2)
                self.assertEqual(workbench.appendMenu.call_count, 3)
                workbench.appendToolbar.assert_any_call('SimpleCAD Draw', ['SimpleCAD_Select'])
                workbench.appendToolbar.assert_any_call('SimpleCAD Mesh', ['SimpleCAD_MeshSplit'])
                workbench.appendMenu.assert_any_call(['SimpleCAD', 'Mesh'], ['SimpleCAD_MeshSplit'])
                workbench.appendMenu.assert_any_call('SimpleCAD', ['Separator', 'SimpleCAD_Settings', 'SimpleCAD_MCP'])
                toolbar.schedule.assert_called_once_with()
                controller.instance.return_value.activate.assert_called_once_with()
                controller.instance.return_value.deactivate.assert_called_once_with()
        finally:
            sys.modules.pop("simplecad.gui.workbench", None)
            if previous is not None:
                sys.modules["simplecad.gui.workbench"] = previous
            if previous_attribute is not None:
                package.workbench = previous_attribute
            elif hasattr(package, "workbench"):
                del package.workbench

    def test_startup_loader_scopes(self):
        self.load_workbench(separate_namespaces=True)

    def test_console_loader_scope(self):
        self.load_workbench(separate_namespaces=False)


if __name__ == "__main__":
    unittest.main()
