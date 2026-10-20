"""Label native toolbars and migrate the old single row once.

FreeCAD owns action registration/availability and workbench visibility. Keep
the native movable toolbars so View > Toolbars and saved layouts still work.
"""
import FreeCAD as App
import FreeCADGui as Gui
from .commands import GROUPS
from .qt import QtCore, QtWidgets

PLACED = 'GroupedToolbarsPlacedSurface'  # was GroupedToolbarsPlaced before the Surface group


def schedule():
    # Workbench toolbar widgets are populated after Activated returns.
    QtCore.QTimer.singleShot(0, arrange)


def arrange():
    if Gui.activeWorkbench().name() != 'SimpleCADWorkbench':
        return
    window = Gui.getMainWindow()
    bars = window.findChildren(QtWidgets.QToolBar)
    found = {}
    for bar in bars:
        title = bar.windowTitle()
        identity = bar.objectName()
        if title == 'SimpleCAD' or identity == 'SimpleCAD':
            # An older version may leave its persisted toolbar behind.
            bar.hide()
        for group, _ in GROUPS:
            if title == 'SimpleCAD ' + group or identity == 'SimpleCAD ' + group:
                found[group] = bar
                label_name = 'SimpleCADGroupLabel' + group
                if bar.findChild(QtWidgets.QLabel, label_name) is None:
                    label = QtWidgets.QLabel(group, bar)
                    label.setObjectName(label_name)
                    label.setAccessibleName(group + ' tools')
                    color = '#62d26f' if group == 'Mesh' else '#00bfae'
                    label.setStyleSheet('QLabel { color: %s; font-weight: 600; padding: 0 6px; }' % color)
                    label.setToolTip('STL mesh conversion, splitting, stretching and region editing' if group == 'Mesh'
                                     else 'SimpleCAD ' + group + ' tools')
                    actions = bar.actions()
                    if actions:
                        bar.insertWidget(actions[0], label)
                    else:
                        bar.addWidget(label)
    preferences = App.ParamGet('User parameter:BaseApp/Preferences/Mod/SimpleCAD')
    if len(found) == len(GROUPS) and not preferences.GetBool(PLACED, False):
        # Start a dedicated row, ordered left to right with the green mesh group
        # last. Afterwards leave positions to FreeCAD's normal saved layout.
        # PLACED changes when a group is added, so the row is laid out once more.
        for group, _ in GROUPS:
            window.removeToolBar(found[group])
        window.addToolBarBreak(QtCore.Qt.TopToolBarArea)
        for group, _ in GROUPS:
            window.addToolBar(QtCore.Qt.TopToolBarArea, found[group])
            found[group].show()
        preferences.SetBool(PLACED, True)
