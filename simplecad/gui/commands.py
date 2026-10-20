import FreeCADGui as Gui
from .. import ROOT
from . import command_state

TOOLS = [
    ("ConvertMesh", "Make mesh editable…", "Convert an imported STL mesh to editable faces; keep the original mesh as a backup"),
    ("Analytic", "Fit Circle / Cylinder", "Convert selected faceted circular edges or cylindrical faces into native analytic geometry, or replace a faceted hole inside its solid with one analytic cylinder"),
    ("Select", "Select", "S / Esc: select; drag right for fully inside, left for inside or touching"),
    ("Measure", "Measure", "Z: click a vertex, edge, face or hole to measure it; click a second one for distance, spacing and angle. Place offsets a dimension and leaves it in view"),
    ("Rectangle", "Rectangle", "R: click two corners; choose Draw: Plane or Draw: Surface; Tab for width, height in the local drawing frame"),
    ("Circle", "Circle", "O: click center, then radius; choose Draw: Plane or Draw: Surface; Tab for exact local radius"),
    ("Arc", "Arc", "A: center, start, end in Draw: Plane or Draw: Surface; Tab for local radius and signed sweep in degrees"),
    ("Arc2Point", "2 Point Arc", "H: first endpoint, second endpoint, bulge in Draw: Plane or Draw: Surface; Tab for local endpoint distance and signed bulge"),
    ("Sphere", "Sphere", "B: click center, then radius to create a sphere; Tab for exact radius"),
    ("Polygon", "Polygon", "G: choose sides, click center, then a vertex in Draw: Plane or Draw: Surface; Tab for exact local radius"),
    ("Line", "Line", "L: connected lines; Draw: Plane makes straight lines; Draw: Surface wraps across connected faces and splits closed regions; X/Y/Z for straight lines; Esc finishes"),
    ("Offset", "Offset", "E: select a face or edge, move inward/outward or to either side; Tab for exact distance"),
    ("Elongate", "Elongate / Make Elliptical", "X: select a face or hole rim, drag to elongate into an ellipse along any direction; Tab for exact distance and angle"),
    ("PushPull", "Push/Pull", "P: drag a flat face; snap onto the opposite face for a hole; continue past it to extend"),
    ("Round", "Round edges", "F: round selected edges, a face boundary, or a solid; preview the radius before applying"),
    ("Subdivide", "Subdivide face", "D: divide a flat face into triangles, a center fan, or evenly spaced rows and columns"),
    ("MeshSplit", "Split mesh…", "Split an STL mesh across X/Y/Z or its main/local axes; keep triangle detail and optionally close cut surfaces"),
    ("MeshStretch", "Stretch mesh / Move region…", "Keep one end fixed and move the other; stretch only between two planes, with mesh output and the original kept"),
    ("MeshRegion", "Mesh region · Move / Rotate / Extrude…", "Select connected flat or smooth mesh patches, then move, rotate, or extrude with a live preview and an original backup"),
    ("Slice", "Slice / Separate", "U: slice across X/Y/Z or the main axis; add optional printable studs/sockets and spread the pieces apart"),
    ("Intersect", "Intersect Faces", "I: select crossing faces or objects; split both surfaces and keep the regions for deletion"),
    ("Union", "Union", "J: join selected whole objects into one closed solid; remove internal faces and redundant dividing edges; Undo restores the pieces"),
    ("VertexMove", "Move Vertex", "V: drag a corner to deform adjoining flat faces; X/Y/Z locks an axis; Tab for dx, dy, dz"),
    ("Move", "Move", "M: select objects, click a base point, then a destination"),
    ("Rotate", "Rotate", "T: rotate whole objects or selected lines/arcs around a center or axis; preview before applying"),
    ("Deform", "Bend / Soft Deform", "N: select a region on one object; move it with smooth falloff or bend along an axis; preview before applying"),
    ("Scale", "Scale / Stretch", "K: resize whole objects uniformly or stretch X/Y/Z independently, using world or local axes"),
    ("Loft", "Loft", "Q: select face or wire profiles in order, then connect them with a smooth or ruled solid/surface"),
    ("Sweep", "Sweep", "W: select a face/wire profile first and a connected edge/path second; carry the profile along the path"),
    ("Copy", "Copy", "C: place independent copies of selected objects"),
    ("Pattern", "Pattern…", "Repeat whole objects in a grid, around an axis, or along a selected edge path; preview before applying"),
    ("Mirror", "Mirror", "Flip whole objects along X, Y or Z; makes a mirrored copy unless you choose to mirror the original"),
    ("Delete", "Delete", "Delete / Backspace: erase selected edges, faces, or objects; coplanar faces merge"),
]


SURFACE = [
    ("Imprint", "Draw on surface…", "Project or wrap a rectangle, circle, polygon or text onto curved or flat faces: split them into a selectable region, or raise or recess it by a depth"),
    ("OffsetFace", "Offset face…", "Move faces, flat or curved, along their own normals by a distance: outward adds material, inward cuts it. The curved-face Push/Pull; side walls go straight along the normals"),
    ("Shell", "Shell / Thicken…", "Hollow a solid to a wall thickness, leaving the selected faces open; or turn a surface object into a solid wall of a thickness"),
    ("Draft", "Draft faces…", "Tilt flat or round side walls by an angle about a hinge plane, so a moulded or cast part releases"),
    ("HealFaces", "Delete && heal faces", "Remove selected faces from a solid and grow the neighbouring faces until the solid closes again, such as a boss, a pocket or a round"),
    ("RemoveRounds", "Remove rounds…", "Find rounded edges (fillets) up to a radius, outside, inside or both, and remove them so the corners are sharp again; preview before applying"),
    ("FillHole", "Fill hole…", "Close openings in a surface with patches that blend smoothly into the neighbouring faces; a fully closed surface becomes a solid"),
    ("Unwrap", "Unwrap face", "Flatten a curved face into a flat outline of the same area, placed beside the part, for templates and cutting"),
    ("Curvature", "Curvature map", "Colour curved faces by how tightly they bend: red tight, blue gentle. Click again to hide. Measure shows the radius at a clicked point"),
]


SMART = [
    ("SelectHole", "Select hole", "Grow a selected face or rim edge into its whole hole or cylinder wall, analytic or faceted"),
    ("SelectLoop", "Select edge loop", "Grow a selected edge into the loop it lies on, such as a hole's rim"),
    ("SelectFlat", "Select flat region", "Grow a selected face into the connected faces on its plane, such as a flat area of mesh triangles"),
    ("SelectSmooth", "Select smooth surface", "Grow a selected face across gentle creases, such as a faceted fillet or curved wall"),
]


# Mesh stays last, at the right end of the initial toolbar row.
GROUPS = (
    ('Draw', ('Select', 'Line', 'Rectangle', 'Circle', 'Arc', 'Arc2Point', 'Polygon', 'Sphere')),
    ('Modify', ('PushPull', 'Offset', 'Elongate', 'Analytic', 'Round', 'Subdivide', 'Slice', 'Intersect',
                'Union', 'VertexMove', 'Move', 'Rotate', 'Deform', 'Scale', 'Loft', 'Sweep',
                'Copy', 'Pattern', 'Mirror', 'Delete')),
    ('Surface', ('Imprint', 'OffsetFace', 'Shell', 'Draft', 'HealFaces', 'RemoveRounds', 'FillHole', 'Unwrap')),
    ('Inspect', ('SmartSelect', 'Measure', 'Curvature', 'Isolate')),
    ('Mesh', ('ConvertMesh', 'MeshSplit', 'MeshStretch', 'MeshRegion')),
)
MENU_EXTRAS = {'Modify': ('Separator', 'Appearance', 'Cleanup', 'Heal')}
EXTRAS = [
    ('Isolate', 'Isolate selection', 'Hide every object except the selected ones; Isolate again restores visibility. The model is unchanged'),
    ('Cleanup', 'Merge coincident geometry', 'Collapse duplicate faces and lines; join touching open surfaces in one Undo step'),
    ('Heal', 'Heal to precision', 'Align nearly parallel, axis-aligned or coplanar faces and holes within the modeling precision; one Undo step'),
    ('Settings', 'Settings…', 'Show or hide curved-surface seams and configure snapping'),
    ('MCP', 'AI connection (MCP)…', 'Start or stop a local connection for AI clients to inspect and edit your models'),
    ('Appearance', 'Color && opacity…', 'Set surface color and opacity for selected faces or whole objects; preview, Apply or Cancel'),
]
DEFINITIONS = {key: (title, hint) for key, title, hint in TOOLS + SURFACE + SMART + EXTRAS}


def names(keys):
    return [key if key == 'Separator' else 'SimpleCAD_' + key for key in keys]


class SmartSelectGroup:
    """One toolbar dropdown for the smart selection commands."""
    def GetCommands(self):
        return tuple("SimpleCAD_" + key for key, _, _ in SMART)

    def GetDefaultCommand(self):
        return 0

    def GetResources(self):
        return {"MenuText": "Smart select", "ToolTip": "Grow the selection into a hole, loop, flat region or smooth surface. Double-click a face or edge to choose automatically"}

    def IsActive(self):
        return not command_state.reason('SmartSelect')


class Command:
    def __init__(self, key, title, hint):
        self.key, self.title, self.hint = key, title, hint

    def GetResources(self):
        # Shortcuts live in a viewport-only event filter, not global QActions.
        icon = "workbench" if self.key in ("Cleanup", "Heal", "Settings", "MCP", "Appearance") else self.key.lower()
        return {"Pixmap": str(ROOT / "Resources" / "icons" / (icon + ".svg")),
                "MenuText": self.title,
                "ToolTip": self.hint + '\n\n' + command_state.REQUIREMENTS[self.key]}

    def Activated(self):
        if self.key == 'MCP':
            from .tools.mcp import show
            show()
            return
        from .controller import instance
        instance().start(self.key)

    def IsActive(self):
        return not command_state.reason(self.key)


def register():
    for key, (title, hint) in DEFINITIONS.items():
        Gui.addCommand('SimpleCAD_' + key, Command(key, title, hint))
    Gui.addCommand('SimpleCAD_SmartSelect', SmartSelectGroup())
    return names(key for _, keys in GROUPS for key in keys)


def populate_context_menu(menu):
    """The custom Faces tree uses the same commands and rules as the viewport."""
    from .qt import QtGui
    context = command_state.current(fresh=True)
    menu.setToolTipsVisible(True)
    for group, keys in command_state.context_groups(context):
        submenu = menu.addMenu(group)
        submenu.setToolTipsVisible(True)
        for key in keys:
            command = Command(key, *DEFINITIONS[key])
            resources = command.GetResources()
            action = submenu.addAction(QtGui.QIcon(resources['Pixmap']), resources['MenuText'])
            missing = command_state.reason(key, context)
            action.setEnabled(not missing)
            action.setToolTip((missing + '\n\n' if missing else '') + resources['ToolTip'])
            action.setStatusTip(missing or command_state.REQUIREMENTS[key])
            action.triggered.connect(lambda checked=False, command=command: command.Activated())
