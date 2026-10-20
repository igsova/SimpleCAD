"""Tool panels open in the bottom-right corner of the 3D view, clear of the model."""
import os
import unittest

from simplecad.gui.panels import PANEL_MARGIN, panel_position


class PanelPositionTests(unittest.TestCase):
    def test_corner_of_view_with_margin(self):
        x, y = panel_position((100, 50, 1000, 800), (300, 200))
        self.assertEqual((x + 300, y + 200), (100 + 1000 - PANEL_MARGIN, 50 + 800 - PANEL_MARGIN))
        self.assertEqual(panel_position((0, 0, 800, 600), (200, 100), margin=0), (600, 500))

    def test_clear_of_the_view_centre(self):
        x, y = panel_position((0, 0, 1200, 800), (380, 300))
        self.assertGreater(x, 600)
        self.assertGreater(y, 400)

    def test_panel_bigger_than_view_starts_at_its_top_left(self):
        self.assertEqual(panel_position((100, 50, 400, 300), (500, 350)), (100, 50))
        # Barely fits: the margin gives way before the panel leaves the view.
        self.assertEqual(panel_position((0, 0, 305, 205), (300, 200)), (0, 0))

    def test_screen_keeps_panel_reachable(self):
        screen = (0, 0, 1920, 1080)
        self.assertEqual(panel_position((1500, 0, 1000, 800), (300, 200), screen), (1620, 800 - 200 - PANEL_MARGIN))
        self.assertEqual(panel_position((0, 900, 800, 400), (300, 200), screen), (800 - 300 - PANEL_MARGIN, 880))
        # Too big for the screen as well: its title bar stays on screen.
        self.assertEqual(panel_position((-50, -20, 200, 200), (300, 300), screen), (0, 0))


class AnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from simplecad.gui.qt import QtWidgets
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_dialog_follows_corner_until_moved(self):
        from unittest.mock import patch
        from simplecad.gui import panels as ui
        main = ui.QtWidgets.QWidget(); main.setGeometry(40, 30, 700, 600); main.show()
        self.addCleanup(main.deleteLater)
        dialog = ui.QtWidgets.QDialog(main)
        dialog.setWindowFlags(ui.QtCore.Qt.Tool)
        layout = ui.QtWidgets.QVBoxLayout(dialog); layout.addWidget(ui.QtWidgets.QLabel('Distance'))
        flush = lambda: [self.app.processEvents() for _ in range(5)]
        corner = lambda: (dialog.frameGeometry().right() + 1, dialog.frameGeometry().bottom() + 1)
        target = (40 + 700 - PANEL_MARGIN, 30 + 600 - PANEL_MARGIN)  # inside the 800 px offscreen screen
        with patch.object(ui, 'view_widget', return_value=main):
            self.assertIs(ui.anchor_panel(dialog), dialog)
            self.assertIs(ui.anchor_panel(dialog).simplecad_anchor, dialog.simplecad_anchor)  # installed once
            dialog.show(); flush()
            self.assertEqual(corner(), target)
            height = dialog.height()
            for _ in range(4):  # Rows appear: the bottom-right corner stays.
                layout.addWidget(ui.QtWidgets.QPushButton('More'))
            flush()
            self.assertGreater(dialog.height(), height)
            self.assertEqual(corner(), target)
            dialog.move(60, 50); flush()  # The user moved it: leave it there.
            layout.addWidget(ui.QtWidgets.QPushButton('Extra')); flush()
            self.assertEqual((dialog.x(), dialog.y()), (60, 50))
        dialog.deleteLater()


if __name__ == '__main__':
    unittest.main()
