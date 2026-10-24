"""One interaction session owns its callbacks, overlay, and captured document."""
import time
import traceback

import Part
import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin

from ..core import geometry as geo, preferences
from ..document import guides, operations as ops
from . import clipboard, snapping
from .snapping import Snapper, pick, ray, screen, pull_drag, snap_pull, shared_picks
from .previews.overlay import Preview, edges, outline
from .qt import QtCore, QtWidgets
from .size_input import SizeInput
from .status_bar import Controls

_instance = None
SURFACE_DRAW_TOOLS = ('Line', 'Rectangle', 'Circle', 'Polygon', 'Arc', 'Arc2Point')
DRAW_TOOLS = SURFACE_DRAW_TOOLS + ('Sphere',)
ARROW_KEYS = {int(QtCore.Qt.Key_Right): 'Right', int(QtCore.Qt.Key_Left): 'Left', int(QtCore.Qt.Key_Up): 'Up',
              int(QtCore.Qt.Key_Down): 'Down'}
LOCK_TEXT = {'YZ': 'Right arrow · facing red X', 'XZ': 'Left arrow · facing green Y', 'XY': 'Up arrow · facing blue Z'}


def instance():
    global _instance
    if _instance is None:
        _instance = Controller()
    return _instance


class Controller(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.active = False
        self.tool = None
        self.arc_input = None
        self.tape_input = None
        self.offset_input = None
        self.elongate_input = None
        self.push_pull_input = None
        self.measure_session = None
        self.callback = None
        self.preview = None
        self.controls = None
        self.size_input = SizeInput(self)
        self.round_session = None
        self.slice_session = None
        self.mesh_split_session = None
        self.mesh_stretch_session = None
        self.mesh_region_session = None
        self.rotate_session = None
        self.forming_session = None
        self.deform_session = None
        self.subdivide_session = None
        self.polygon_sides = 6
        self.base_snapper = None
        self.move_outline = None
        self.drawing_surface = None
        self.surface_frame = None
        self.surface_point = None
        self.surface_mode = False
        self.surface_support = None
        self.surface_skin = None
        # An arrow-key plane lock lasts for one drawing tool; the selector
        # shows it and returns to its previous choice afterwards.
        self.plane_lock = self.plane_restore = self.start_plane = None
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.check_context)
        # Drawing snaps are collected in idle slices, so a tool opens at once.
        self.warmup = QtCore.QTimer(self)
        self.warmup.setSingleShot(True)
        self.warmup.timeout.connect(self.warm_snaps)
        self.warm_work = self.warm_doc = None
        # A continuing surface Line meshes its guide after the edit is drawn.
        self.guide_timer = QtCore.QTimer(self)
        self.guide_timer.setSingleShot(True)
        self.guide_timer.timeout.connect(self.build_guide)
        from .display import SeamDisplay
        self.seams = SeamDisplay(self)
        from .viewport_style import ViewportStyle
        self.viewport_style = ViewportStyle(self)
        from .tools.selection import DragSelection
        self.selection = DragSelection(self)
        from .face_browser import FaceBrowser
        self.faces = FaceBrowser(self)

    def warm_snaps(self):
        """Collect drawing snaps a few milliseconds at a time while idle.

        On a converted part of thousands of faces the collection takes over
        a second; the first Line then finds it ready. Work pauses during a
        tool, a mouse drag or a modal dialog, and resumes where it stopped.
        """
        if not self.active:
            return
        doc = App.ActiveDocument
        app = QtWidgets.QApplication
        if (self.tool or doc is None or app.mouseButtons() != QtCore.Qt.NoButton
                or app.activeModalWidget() is not None):
            self.warm_work = None
            self.warmup.start(1000)
            return
        try:
            if self.warm_work is None or self.warm_doc != doc:
                self.warm_doc = doc
                self.warm_work = snapping.warm(doc, snapping.snap_options(preferences.load()))
            deadline = time.perf_counter() + .012
            while time.perf_counter() < deadline:
                next(self.warm_work)
        except StopIteration:
            # Everything is ready; look again later for changed objects.
            self.warm_work = None
            self.warmup.start(1000)
            return
        except (ReferenceError, RuntimeError, AttributeError, ValueError):
            self.warm_work = None
            self.warmup.start(1000)
            return
        self.warmup.start(15)

    def build_guide(self):
        """Mesh the continuing surface Line's guide once its edit is drawn.

        Meshing a fitted part took about half a second, and inside the click
        it held back the new face. A hover that comes first builds it itself.
        """
        frame = self.surface_frame
        if frame is None or frame.analytic:
            return
        try:
            frame.mesh
        except (ValueError, RuntimeError, Part.OCCError) as error:
            self.report(error)

    def message(self, text):
        Gui.getMainWindow().statusBar().showMessage("SimpleCAD · " + text, 12000)

    def activate(self):
        if self.active:
            return
        self.active = True
        self.controls = Controls(self, Gui.getMainWindow())
        Gui.getMainWindow().statusBar().addPermanentWidget(self.controls)
        QtWidgets.QApplication.instance().installEventFilter(self)
        # Undo a suspension left behind by a crash during a drawing tool.
        preferences.restore_long_press_menu()
        settings = preferences.load()
        self.seams.start(settings.show_seams)
        self.viewport_style.start(settings.viewport_style, preferences.color(settings.face_color))
        self.faces.start()
        self.warmup.start(1500)
        if App.ActiveDocument:
            try:
                ops.heal_dangling_elongations(App.ActiveDocument)
            except Exception:
                pass
        self.message("R Rectangle · O Circle · B Sphere · G Polygon · L Line · P Push/Pull · F Round edges · Y Fit Circle/Cylinder · M Move · Q Rotate · C Copy · T Measure Tape · S Select")

    def deactivate(self):
        self.cancel(quiet=True)
        self.warmup.stop()
        self.warm_work = self.warm_doc = None
        if self.active:
            self.faces.stop()
            self.seams.stop()
            self.viewport_style.stop()
            QtWidgets.QApplication.instance().removeEventFilter(self)
            Gui.getMainWindow().statusBar().removeWidget(self.controls)
            self.controls.deleteLater()
            self.controls = None
        self.active = False

    def cancel(self, quiet=False):
        if self.measure_session is not None:
            session, self.measure_session = self.measure_session, None
            session.close()
        if self.offset_input is not None:
            self.offset_input.close()
            self.offset_input = None
        if self.elongate_input is not None:
            self.elongate_input.close()
            self.elongate_input = None
        if self.push_pull_input is not None:
            self.push_pull_input.close()
            self.push_pull_input = None
        if self.subdivide_session is not None:
            session, self.subdivide_session = self.subdivide_session, None
            session.close()
        if self.deform_session is not None:
            session, self.deform_session = self.deform_session, None
            session.close()
        if self.forming_session is not None:
            session, self.forming_session = self.forming_session, None
            session.close()
        if self.rotate_session is not None:
            session, self.rotate_session = self.rotate_session, None
            session.close()
        if self.mesh_region_session is not None:
            session, self.mesh_region_session = self.mesh_region_session, None
            session.close()
        if self.mesh_stretch_session is not None:
            session, self.mesh_stretch_session = self.mesh_stretch_session, None
            session.close()
        if self.mesh_split_session is not None:
            session, self.mesh_split_session = self.mesh_split_session, None
            session.close()
        if self.slice_session is not None:
            session, self.slice_session = self.slice_session, None
            session.close()
        if self.round_session is not None:
            session, self.round_session = self.round_session, None
            session.close()
        self.selection.cancel()
        self.timer.stop()
        if self.callback is not None:
            try:
                self.view.removeEventCallbackPivy(coin.SoEvent.getClassTypeId(), self.callback)
            except (RuntimeError, ReferenceError):
                pass
            self.callback = None
        preferences.restore_long_press_menu()
        if self.preview is not None:
            self.preview.close()
            self.preview = None
        if self.tape_input is not None:
            self.tape_input.close()
            self.tape_input = None
        self.tool = None
        self.arc_input = None
        self.pull_references = None
        self.pull_reference = None
        self.vertex_neighborhood = None
        self.move_outline = None
        self.drawing_surface = None
        self.surface_frame = None
        self.surface_point = None
        self.surface_mode = False
        self.surface_support = None
        self.surface_skin = None
        self.start_plane = self.plane_lock = None
        if self.plane_restore is not None and self.controls:
            blocked = self.controls.plane.blockSignals(True)
            self.controls.plane.setCurrentText(self.plane_restore)
            self.controls.plane.blockSignals(blocked)
        self.plane_restore = None
        self.size_input.close()
        if self.controls:
            self.controls.clear()
        if not quiet:
            self.message("Select · R Rectangle · O Circle · B Sphere · G Polygon · L Line · P Push/Pull · F Round edges · Y Fit Circle/Cylinder · M Move · Q Rotate · C Copy · X Elongate · T Measure Tape")

    def check_context(self):
        if not self.tool:
            return
        try:
            if App.ActiveDocument != self.doc or Gui.activeDocument().activeView() != self.view:
                self.cancel()
            elif self.tool in ("Rectangle", "Circle", "Offset", "Elongate", "Arc", "Arc2Point", "Sphere", "Polygon", "Line", "Tape", "VertexMove", "PushPull", "Round", "Slice", "MeshSplit", "MeshStretch", "MeshRegion", "Rotate", "Subdivide", "Scale", "Loft", "Sweep", "Deform") and self.doc.UndoCount != self.line_undo_count:
                # Menu/toolbar Undo invalidates cached anchors, faces and
                # opposite-face contact, just as the keyboard shortcut does.
                self.cancel()
            elif self.tool == "VertexMove" and self.anchor is not None:
                if not self.obj.Shape.isEqual(self.vertex_neighborhood.shape):
                    self.cancel()
            elif self.offset_input is not None:
                self.offset_input.check()
            elif self.elongate_input is not None:
                self.elongate_input.check()
            elif self.round_session is not None:
                ops.check_rounding(self.round_session.targets)
            elif self.mesh_split_session is not None:
                self.mesh_split_session.check()
            elif self.mesh_stretch_session is not None:
                self.mesh_stretch_session.check()
            elif self.mesh_region_session is not None:
                self.mesh_region_session.check()
            elif self.slice_session is not None:
                ops.check_slicing(self.slice_session.targets)
            elif self.deform_session is not None:
                self.deform_session.check()
            elif self.forming_session is not None:
                self.forming_session.check()
            elif self.rotate_session is not None:
                ops.check_rotation(self.rotate_session.targets)
            elif self.subdivide_session is not None:
                ops.check_subdivision(self.subdivide_session.target)
        except (RuntimeError, ReferenceError, AttributeError, ValueError):
            self.cancel()

    def selected(self):
        return list(dict.fromkeys(item.Object for item in Gui.Selection.getSelectionEx()
                                  if item.Object.Document == App.ActiveDocument))

    def start(self, tool):
        from .command_state import current, reason
        missing = reason(tool, current(fresh=True))
        if missing:
            self.message(missing)
            return
        self.cancel(quiet=True)
        if not self.active:
            self.activate()
        if tool == "Settings":
            from .settings_dialog import SettingsDialog
            dialog = SettingsDialog(Gui.getMainWindow())
            if dialog.exec() == QtWidgets.QDialog.Accepted:
                settings = dialog.values()
                preferences.save(settings)
                # Clear cached preselection/selection overlays before changing
                # native edge display. This is a view change, not an Undo edit.
                Gui.Selection.clearSelection()
                Gui.Selection.clearPreselection()
                self.seams.configure(settings.show_seams)
                self.viewport_style.configure(settings.viewport_style, preferences.color(settings.face_color))
                self.message("Settings saved · Ready to draw")
            dialog.deleteLater()
            self.focus_view()
            return
        if tool == "Select":
            self.focus_view()
            self.message("Select · Drag right: fully inside · Drag left: inside or touching · Esc cancels")
            return
        try:
            if tool == "ConvertMesh":
                from .tools.mesh_convert import show
                show(self)
                self.focus_view()
                return
            if tool == "Analytic":
                from .tools.analytic import show
                show(self)
                self.focus_view()
                return
            if tool == "Appearance":
                from .tools.appearance import show
                show(self)
                self.focus_view()
                return
            if tool in ("Imprint", "OffsetFace", "Shell", "Draft", "HealFaces", "RemoveRounds", "FillHole", "Unwrap",
                        "Pattern"):
                from .tools.surface import run
                run(self, tool)
                self.focus_view()
                return
            if tool == "Curvature":
                from .tools.curvature import toggle
                toggle(self)
                self.focus_view()
                return
            if tool == "Mirror":
                from .tools.mirror import show
                show(self)
                self.focus_view()
                return
            if tool == "Subdivide":
                from .tools.subdivide import SubdivideSession
                selection = [(item.Object, tuple(item.SubElementNames)) for item in Gui.Selection.getSelectionEx()
                             if item.Object.Document == App.ActiveDocument]
                target = ops.prepare_subdivision(selection)
                self.doc, self.view = App.ActiveDocument, Gui.activeDocument().activeView()
                self.tool, self.anchor = "Subdivide", None
                self.line_undo_count = self.doc.UndoCount
                self.subdivide_session = SubdivideSession(self, target, selection)
                self.timer.start(200); self.subdivide_session.open()
                self.controls.label.setText("Subdivide face")
                self.message("Set divisions or rows/columns · Equal-area preview · Apply to keep · Esc cancels")
                return
            if tool == "Deform":
                from .tools.deform import DeformSession
                selection = [(item.Object, tuple(item.SubElementNames)) for item in Gui.Selection.getSelectionEx()
                             if item.Object.Document == App.ActiveDocument]
                self.doc, self.view = App.ActiveDocument, Gui.activeDocument().activeView()
                self.tool, self.anchor = tool, None
                self.line_undo_count = self.doc.UndoCount
                seed = None
                for item in Gui.Selection.getSelectionEx():
                    if item.Object.Document != self.doc: continue
                    for point in getattr(item, 'PickedPoints', ()):
                        if point.Length > geo.EPS and item.Object.Shape.distToShape(Part.Vertex(point))[0] < 1e-5:
                            seed = point; break
                    if seed is not None: break
                self.deform_session = DeformSession(self, selection, seed)
                self.timer.start(200); self.deform_session.open()
                self.controls.label.setText("Bend / Soft Deform")
                self.message("Adjust the region and strength · Apply to keep · Esc cancels")
                return
            if tool in ("Scale", "Loft", "Sweep"):
                from .tools.forming import FormingSession
                selection = [(item.Object, tuple(item.SubElementNames)) for item in Gui.Selection.getSelectionEx()
                             if item.Object.Document == App.ActiveDocument]
                self.doc, self.view = App.ActiveDocument, Gui.activeDocument().activeView()
                self.tool, self.anchor = tool, None
                self.line_undo_count = self.doc.UndoCount
                self.forming_session = FormingSession(self, tool, selection)
                self.timer.start(200); self.forming_session.open()
                self.controls.label.setText("Scale / Stretch" if tool == "Scale" else tool)
                self.message("Adjust the preview · Apply to keep · Esc cancels")
                return
            if tool == "Rotate":
                from .tools.rotate import RotateSession
                selection = [(item.Object, tuple(item.SubElementNames)) for item in Gui.Selection.getSelectionEx()
                             if item.Object.Document == App.ActiveDocument]
                targets = ops.prepare_rotation(selection)
                self.doc, self.view = App.ActiveDocument, Gui.activeDocument().activeView()
                self.tool, self.anchor = "Rotate", None
                self.line_undo_count = self.doc.UndoCount
                self.rotate_session = RotateSession(self, targets, selection)
                self.timer.start(200)
                self.rotate_session.open()
                self.controls.label.setText("Rotate")
                self.message("Choose an axis and center · Adjust the angle · Apply to rotate · Esc cancels")
                return
            if tool == "Slice":
                from ..mesh.conversion import is_mesh
                selected = self.selected()
                if len(selected) == 1 and is_mesh(selected[0]): tool = "MeshSplit"
            if tool == "MeshRegion":
                from .tools.mesh_region import MeshRegionSession
                selected=self.selected()
                if len(selected)!=1:
                    raise ValueError('Select one STL mesh, then choose Mesh region.')
                self.doc,self.view=App.ActiveDocument,Gui.activeDocument().activeView()
                self.tool,self.anchor="MeshRegion",None
                self.line_undo_count=self.doc.UndoCount
                self.mesh_region_session=MeshRegionSession(self,selected[0])
                self.timer.start(500); self.mesh_region_session.open()
                self.controls.label.setText('Mesh region')
                self.message('Click connected mesh patches · Move, Rotate or Extrude · Apply keeps a backup')
                return
            if tool == "MeshStretch":
                from .tools.mesh_stretch import MeshStretchSession
                selected = self.selected()
                if len(selected) != 1:
                    raise ValueError('Select one STL mesh, then choose Stretch mesh / Move region.')
                self.doc, self.view = App.ActiveDocument, Gui.activeDocument().activeView()
                self.tool, self.anchor = tool, None
                self.line_undo_count = self.doc.UndoCount
                self.mesh_stretch_session = MeshStretchSession(self, selected[0])
                self.timer.start(500); self.mesh_stretch_session.open()
                self.controls.label.setText('Stretch mesh / Move region')
                self.message('Drag the plane handles · Rotate both planes with rings or angle fields · Apply to keep the mesh result')
                return
            if tool == "MeshSplit":
                from .tools.mesh_split import MeshSplitSession
                from ..mesh.conversion import is_mesh
                selected = self.selected()
                if not selected and App.ActiveDocument:
                    selected = [obj for obj in App.ActiveDocument.Objects if is_mesh(obj) and obj.ViewObject.Visibility]
                if len(selected) != 1 or not is_mesh(selected[0]):
                    raise ValueError("Select one STL mesh, then choose Split mesh…")
                self.doc, self.view = App.ActiveDocument, Gui.activeDocument().activeView()
                self.tool, self.anchor = "MeshSplit", None
                self.line_undo_count = self.doc.UndoCount
                self.mesh_split_session = MeshSplitSession(self, selected[0])
                self.timer.start(500); self.mesh_split_session.open()
                self.controls.label.setText("Split mesh")
                self.message("Choose the axis and position · Preview split · Apply to keep the mesh sides")
                return
            if tool == "Slice":
                from .tools.slice import SliceSession
                selection = [(item.Object, tuple(item.SubElementNames)) for item in Gui.Selection.getSelectionEx()
                             if item.Object.Document == App.ActiveDocument]
                targets = ops.prepare_slicing(selection)
                self.doc, self.view = App.ActiveDocument, Gui.activeDocument().activeView()
                self.tool, self.anchor = "Slice", None
                self.line_undo_count = self.doc.UndoCount
                self.slice_session = SliceSession(self, targets, selection)
                self.timer.start(200)
                self.slice_session.open()
                self.controls.label.setText("Slice / Separate")
                self.message("Choose a plane and position · Adjust the gap · Apply to split · Esc cancels")
                return
            if tool == "Round":
                from .tools.round import RoundSession
                selection = [(item.Object, tuple(item.SubElementNames)) for item in Gui.Selection.getSelectionEx()
                             if item.Object.Document == App.ActiveDocument]
                targets = ops.prepare_rounding(selection)
                self.doc, self.view = App.ActiveDocument, Gui.activeDocument().activeView()
                self.tool, self.anchor = "Round", None
                self.line_undo_count = self.doc.UndoCount
                self.round_session = RoundSession(self, targets, selection)
                self.timer.start(200)
                self.round_session.open()
                self.controls.label.setText("Round edges")
                self.message("Adjust the radius · Apply to keep the rounded edges · Esc cancels")
                return
            if tool == "Cleanup":
                if App.ActiveDocument is None:
                    self.message("Open a model to merge coincident geometry.")
                    return
                count = ops.cleanup(App.ActiveDocument, self.selected() or None)
                Gui.Selection.clearSelection()
                self.message("Coincident geometry merged · Undo with ⌘Z" if count else "No coincident geometry to merge.")
                return
            if tool == "Heal":
                targets = self.selected()
                if App.ActiveDocument is None or not targets:
                    self.message("Select the shapes to heal, then choose Heal to precision.")
                    return
                self.message("Healing to the modeling precision…")
                QtWidgets.QApplication.processEvents()
                reports = ops.heal(App.ActiveDocument, targets)
                Gui.Selection.clearSelection()
                healed = [r for r in reports if r['healed']]
                parts = []
                if healed:
                    rebuilt = sum(r.get('rebuilt_holes', 0) for r in healed)
                    parts.append("%s%d aligned face(s), %d hole(s), largest move %.4f mm · Undo with ⌘Z" % (
                        "%d broken hole(s) rebuilt, " % rebuilt if rebuilt else "",
                        sum(r['aligned_faces'] for r in healed), sum(r['aligned_holes'] for r in healed),
                        max(r['max_vertex_move'] for r in healed)))
                    before = sum(r.get('mesh_issues_before', 0) for r in healed)
                    after = sum(r.get('mesh_issues_after', 0) for r in healed)
                    if before or after:
                        parts.append("printable mesh: %d → %d open or non-manifold edge(s)" % (before, after))
                parts.extend(r['reason'] for r in reports if not r['healed'])
                self.message(" · ".join(parts) if parts else "Nothing to heal.")
                return
            if tool == 'Intersect':
                selection = [(item.Object, tuple(item.SubElementNames)) for item in Gui.Selection.getSelectionEx()
                             if item.Object.Document == App.ActiveDocument]
                result = ops.intersect(selection)
                Gui.Selection.clearSelection()
                self.faces.refresh()
                self.focus_view()
                self.message('Intersections split · Select and delete unwanted faces · Closed surfaces become solids · Undo with ⌘Z')
                return
            if tool == 'Union':
                result = ops.unite(self.selected())
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(result)
                self.faces.refresh()
                self.focus_view()
                self.message('Union complete · One closed solid · Internal faces and redundant edges removed · Undo with ⌘Z')
                return
            if tool in ("SelectHole", "SelectLoop", "SelectFlat", "SelectSmooth"):
                from .tools.smart_select import expand_selection
                expand_selection(self, tool[len("Select"):].lower())
                self.focus_view()
                return
            if tool == "Isolate":
                from .tools.smart_select import isolate
                isolate(self)
                self.focus_view()
                return
            if tool == "Delete":
                selection = [(item.Object, tuple(item.SubElementNames))
                             for item in Gui.Selection.getSelectionEx()
                             if item.Object.Document == App.ActiveDocument]
                removed = guides.remove([obj for obj, _ in selection])
                selection = [(obj, subs) for obj, subs in selection
                             if not (guides.is_guide(obj) or guides.is_group(obj))]
                if removed and not selection:
                    Gui.Selection.clearSelection()
                    self.message("Guides deleted · Undo with ⌘Z")
                    return
                changed, seams = ops.delete_selection(selection)
                changed = changed or removed
                Gui.Selection.clearSelection()
                if seams:
                    msg = ("Selection deleted; surface seams kept · Undo with ⌘Z" if changed else
                           "That line is a surface seam · The curved wall is unchanged")
                    self.message(msg)
                    if not changed:
                        App.Console.PrintWarning(f"SimpleCAD: {msg}\n")
                elif changed:
                    self.message("Selection deleted · Undo with ⌘Z")
                else:
                    self.message("Nothing to delete")
                    App.Console.PrintWarning("SimpleCAD: Nothing to delete\n")
                return
            if App.ActiveDocument is None:
                App.newDocument("SimpleCAD")
                Gui.activeDocument().activeView().viewIsometric()
                camera = Gui.activeDocument().activeView().getCameraNode()
                if hasattr(camera, "height"):
                    camera.height = 120
            chosen_face = self.faces.selected_face() if tool == 'PushPull' else None
            if not chosen_face and tool == 'PushPull':
                sel_faces = [(item.Object, name) for item in Gui.Selection.getSelectionEx()
                             if item.Object.Document == App.ActiveDocument and hasattr(item.Object, "Shape")
                             for name in (item.SubElementNames or (["Face1"] if len(item.Object.Shape.Faces) == 1 else []))
                             if name.startswith("Face")]
                if len(sel_faces) == 1:
                    obj, name = sel_faces[0]
                    face = obj.Shape.getElement(name)
                    if hasattr(face, 'Surface') and isinstance(face.Surface, Part.Plane):
                        chosen_face = (obj, face)
            self.doc = App.ActiveDocument
            self.view = Gui.activeDocument().activeView()
            self.tool = tool
            from .tools.arc import ArcInput
            self.arc_input = ArcInput(self) if tool in ("Arc", "Arc2Point") else None
            self.anchor = None
            self.point = None
            self.plane = None
            self.axis = None
            self.support = None
            self.line_faces = []
            self.drawing_surface = None
            self.surface_frame = None
            self.surface_point = None
            self.surface_mode = tool in SURFACE_DRAW_TOOLS and self.controls.drawing_mode.currentIndex() == 1
            from ..surfaces.skin import has_faces
            plane_only = self.surface_mode and not has_faces(self.doc)
            if plane_only:
                # Surface mode carries over between documents. Where nothing
                # has a face, it would wait for one and ignore every click.
                blocked = self.controls.drawing_mode.blockSignals(True)
                self.controls.drawing_mode.setCurrentIndex(0)
                self.controls.drawing_mode.blockSignals(blocked)
                self.surface_mode = False
            self.surface_support = None
            self.surface_skin = None
            if self.surface_mode:
                selected = self.faces.selected_face()
                if not selected:
                    faces = [(item.Object, name) for item in Gui.Selection.getSelectionEx()
                             if item.Object.Document == self.doc and hasattr(item.Object, 'Shape')
                             for name in item.SubElementNames if name.startswith('Face')]
                    if len(faces) == 1:
                        obj, name = faces[0]
                        selected = (obj, obj.Shape.getElement(name))
                self.surface_support = selected
                from ..surfaces.wrap import warm_solver
                warm_solver()
            self.auto_line = False
            self.line_undo_count = self.doc.UndoCount
            self.last_pos = None
            self.objects = self.selected() if tool in ("Move", "Copy") else []
            for obj in self.objects:
                ops.editable(obj)
            self.distance = 0.0
            self.pull_contact = None
            self.pull_references = None
            self.pull_reference = None
            self.down_pos = None
            self.dragging = False
            self.snapper = None if tool in ("Offset", "Elongate") else Snapper(self.doc, self.view, self.objects,
                                                                collect=tool != "PushPull")
            # Move/Copy pick their base point on the moved objects themselves.
            self.base_snapper = None
            if tool == "PushPull":
                Gui.Selection.clearSelection()
            self.preview = Preview(self.view)
            if tool == "Tape":
                from .tools.tape import TapeInput
                self.tape_input = TapeInput(self)
            if tool == "Offset":
                if self.doc:
                    try:
                        ops.heal_dangling_wires(self.doc)
                    except Exception:
                        pass
                from .tools.offset import OffsetInput
                self.offset_input = OffsetInput(self)
            elif tool == "Elongate":
                if self.doc:
                    try:
                        ops.heal_dangling_elongations(self.doc)
                    except Exception:
                        pass
                from .tools.elongate import ElongateInput
                self.elongate_input = ElongateInput(self)
            elif tool == "PushPull":
                from .tools.push_pull import PushPullInput
                self.push_pull_input = PushPullInput(self)
            elif tool == "Measure":
                from .tools.measure import MeasureSession
                self.measure_session = MeasureSession(self)
            self.callback = self.view.addEventCallbackPivy(coin.SoEvent.getClassTypeId(), self.coin_event)
            preferences.suspend_long_press_menu()
            self.timer.start(200)
            self.controls.label.setText(tool)
            self.controls.configure_drawing(tool)
            self.controls.sides_label.setVisible(tool == "Polygon")
            self.controls.sides.setVisible(tool == "Polygon")
            self.focus_view()
            self.message({"Measure": "Click a vertex, edge, face or hole · Click a second one to measure between them · Esc ends",
                          "VertexMove": "Click and drag a vertex · X/Y/Z locks an axis · Tab: dx, dy, dz or axis distance · Esc cancels",
                          "Offset": "Click a face or edge to offset · Move to either side · Tab for distance · Esc cancels",
                          "Elongate": "Click a circular hole, hole rim, or planar face · Drag along a direction to elongate into an ellipse · Tab for distance and angle · Esc cancels",
                          "Rectangle": "Click first corner · Draw: Plane / Surface chooses how the outline is placed · Tab for width, height",
                          "Arc": "Click center, then start, then arc end · Tab for radius / sweep · Esc cancels",
                          "Arc2Point": "Click first endpoint, second endpoint, then bulge · Tab for exact size · Esc cancels",
                          "Circle": "Click circle center · Snap to an endpoint, midpoint or face center · Tab for radius",
                          "Sphere": "Click sphere center · then set radius · Tab for exact radius",
                          "Polygon": "Choose Sides below · Click center, then a vertex for size and orientation · Tab for radius",
                          "Line": "Click first endpoint · Keep clicking to continue · Esc finishes",
                          "Tape": "Click an edge or guide to measure out from it, or a point to measure from · Esc ends",
                          "PushPull": "Click a flat face or use the dialog to push/pull · Esc cancels",
                          "Move": "Click a base point on the selected objects, or click an object",
                          "Copy": "Click a base point on the selected objects, or click an object"}[tool]
                         + (" · Arrows lock a plane" if tool in DRAW_TOOLS else ""))
            if self.surface_mode:
                self.message('Surface '+tool+' · Wrap across connected faces of one object · Snap is independent')
            elif plane_only:
                self.message('Draw: Plane · Nothing in this document has a face to draw on in Surface mode')
            if tool in ("Offset", "Elongate"):
                selected = [(item.Object, name) for item in Gui.Selection.getSelectionEx()
                            if item.Object.Document == self.doc and hasattr(item.Object, "Shape")
                            for name in (item.SubElementNames or (["Face1"] if len(item.Object.Shape.Faces) == 1 else ["Edge1"] if len(item.Object.Shape.Edges) == 1 else []))]
                if len(selected) == 1:
                    obj, name = selected[0]
                    if tool == "Offset":
                        self.offset_input.choose(obj, name, obj.Shape.getElement(name).CenterOfMass)
                    else:
                        self.elongate_input.choose(obj, name, obj.Shape.getElement(name).CenterOfMass)
            if tool == "VertexMove":
                vertices = [(item.Object, name) for item in Gui.Selection.getSelectionEx()
                            if item.Object.Document == self.doc for name in item.SubElementNames if name.startswith('Vertex')]
                if len(vertices) == 1:
                    self.choose_vertex(*vertices[0])
            if chosen_face:
                if tool == "PushPull":
                    self.push_pull_input.choose(chosen_face[0], chosen_face[1])
                else:
                    self.obj, self.face = chosen_face
                    ops.editable(self.obj)
                    self.normal = ops.extrusion_normal(self.obj, self.face)
                    self.pull_contact = ops.extrusion_contact(self.obj, self.face)
                    self.anchor = self.point = self.face.CenterOfMass
                    self.prepare_pull_references()
                    self.down_pos = screen(self.view, self.anchor)
                    self.show_points()
                    self.message('Move to pull the selected face · Tab for exact distance · Esc cancels')
        except Exception as error:
            self.cancel(quiet=True)
            self.report(error)

    def choose_vertex(self, obj, name):
        self.vertex_neighborhood = ops.prepare_vertex(obj, name)
        self.obj, self.vertex_name = obj, name
        self.anchor = self.point = self.vertex_neighborhood.point
        plane_name = self.controls.plane.currentText()
        self.plane = (geo.Plane.from_normal(self.anchor, self.view.getViewDirection()) if plane_name == 'Auto'
                      else geo.Plane.named(plane_name, self.anchor))
        self.snapper = Snapper(self.doc, self.view, [obj])
        Gui.Selection.clearSelection()
        Gui.Selection.clearPreselection()
        self.show_points()
        self.message('Move vertex · X/Y/Z locks an axis · Tab: dx, dy, dz or axis distance · Esc cancels')

    def focus_view(self):
        self.size_input.close()  # back to the view: typing a size is over
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        if mdi and mdi.currentSubWindow():
            mdi.currentSubWindow().widget().setFocus()

    def polygon_sides_changed(self, sides):
        self.polygon_sides = sides
        if self.tool == "Polygon" and self.anchor is not None and self.point is not None:
            try:
                self.show_points()
            except ValueError as error:
                self.report(error)

    def drawing_mode_changed(self, index):
        """Restart only the unfinished interaction; committed lines stay saved."""
        if self.controls is None:
            return
        if index == 1:
            # Choosing Surface before a tool gives SciPy time to load.
            from ..surfaces.wrap import warm_solver
            warm_solver()
        tool = self.tool
        self.controls.configure_drawing(tool)
        if tool in SURFACE_DRAW_TOOLS:
            self.start(tool)
            self.message(('Surface' if self.surface_mode else 'Plane')+' drawing · Choose a new starting point · Completed lines are kept')

    def surface_snap(self, pos, target=None):
        """The starting face chooses one connected skin, not a permanent face lock."""
        from ..surfaces.skin import Skin
        from ..surfaces.line import same_surface
        hit = pick(self.view, self.doc, pos, face_only=True)
        if target is None:
            if hit is None:
                return None
            target = hit[0], hit[1]
        owner, face = target
        if hit is not None and hit[0] != owner:
            return None
        if (self.surface_skin is None or self.anchor is None and self.surface_support is None
                and (not self.surface_skin.shape.isSame(owner.Shape) or not self.surface_skin.contains(face))):
            self.surface_skin = Skin(owner.Shape,face)
        if hit is not None and not self.surface_skin.contains(hit[1]):
            return None
        compatible = hit is not None and same_surface(face,hit[1])
        if not compatible:
            # At a shared boundary retain the deliberately selected face for
            # an exact endpoint snap; farther inside the next face, follow it.
            snap = self.snapper.snap_surface(pos,face,hit,self.controls.snap.isChecked(),project_hit=False)
            if snap is not None:
                return snap,target
            if hit is None or not self.surface_skin.contains(hit[1]):
                return None
        if hit is not None:
            target = owner,hit[1]
        snap = self.snapper.snap_surface(pos,target[1],hit,self.controls.snap.isChecked(),project_hit=hit is not None)
        return (snap,target) if snap is not None else None

    def miss_surface(self):
        self.point = self.surface_point = None
        self.preview.show_endpoint(None)
        self.preview.update()
        self.controls.label.setText('Surface: choose a point on the face')
        self.controls.value.setPlaceholderText('Choose a surface point')
        self.message('Draw: Surface · Click a connected face on this object · Esc starts a new drawing')
        return False

    def report(self, error):
        self.message(str(error))
        App.Console.PrintError(f"SimpleCAD: {error}\n")
        if not isinstance(error, ValueError):
            App.Console.PrintError("SimpleCAD: " + traceback.format_exc() + "\n")

    def coin_event(self, callback):
        # Mesh-region picking is handled by its Qt event filter. Leave the
        # remaining Coin events to FreeCAD's camera/navigation style.
        if self.mesh_region_session is not None:
            return
        if not self.tool:
            return
        self.check_context()
        if not self.tool:
            return
        event = callback.getEvent()
        pos = tuple(event.getPosition().getValue())
        try:
            if event.isOfType(coin.SoMouseButtonEvent.getClassTypeId()):
                button = event.getButton()
                if button == coin.SoMouseButtonEvent.BUTTON2:
                    callback.setHandled()
                    if event.getState() == coin.SoButtonEvent.DOWN:
                        self.cancel()
                    return
                if button != coin.SoMouseButtonEvent.BUTTON1:
                    return
                callback.setHandled()
                if event.getState() == coin.SoButtonEvent.DOWN:
                    self.click(pos)
                elif self.tool and self.dragging:
                    self.dragging = False
                    if self.down_pos and sum((a - b) ** 2 for a, b in zip(pos, self.down_pos)) > 16:
                        self.motion(pos)
                        self.commit()
            elif event.isOfType(coin.SoLocation2Event.getClassTypeId()):
                try:
                    self.motion(pos)
                except ValueError as error:
                    # Such as an edge-on plane: every move would repeat it, so
                    # it is a status-bar hint rather than a Report view error.
                    self.message(str(error))
        except Exception as error:
            self.report(error)
            if not isinstance(error, ValueError):
                self.cancel(quiet=True)

    def drawing_plane(self, pos):
        self.support = None
        self.drawing_surface = None
        name = 'Auto' if self.free_start() else self.controls.plane.currentText()
        hit = pick(self.view, self.doc, pos, face_only=True)
        if name == "Auto" and hit:
            if self.tool == "Sphere":
                try:
                    return geo.Plane.from_face(hit[1])
                except ValueError:
                    # On a curved surface, size in a view-facing plane through
                    # the picked point. A sphere never edits its support.
                    return geo.Plane.from_normal(hit[2], self.view.getViewDirection())
            if not isinstance(hit[1].Surface, Part.Plane):
                # Plane mode remains flat even over curved geometry. A view
                # plane through the hit avoids an edge-on XY fallback.
                return geo.Plane.from_normal(hit[2], self.view.getViewDirection())
            plane = geo.Plane.from_face(hit[1])
            if hit[0].TypeId == "Part::Feature" and (self.tool in ("Circle", "Polygon", "Arc", "Arc2Point") or len(hit[0].Shape.Solids) == 1):
                self.support = hit[0]
            return plane
        if self.plane_lock:
            return geo.locked_start(self.plane_lock, ray(self.view, pos)[1])
        return geo.Plane.named("XY" if name == "Auto" else name)

    def free_start(self):
        """Auto and arrow locks start at any 3D target; XY/XZ/YZ only on their own plane."""
        return self.plane_lock is not None or self.controls.plane.currentText() == "Auto"

    def drawing_start(self, pos):
        """Use the same 3D target and workplane for hover and first click.

        An arrow lock turns the Auto start's plane to the locked orientation
        through the snapped point, keeping a support face only in that plane.
        """
        if self.surface_mode:
            chosen = self.surface_snap(pos, self.surface_support)
            if chosen is None:
                self.drawing_surface = None
                return None
            snap, self.drawing_surface = chosen
            face = self.drawing_surface[1]
            return snap, geo.Plane.from_normal(snap.point, face.normalAt(*face.Surface.parameter(snap.point)))
        plane = self.drawing_plane(pos)
        enabled = self.controls.snap.isChecked()
        if not self.free_start():
            self.start_plane = plane, None
            return self.snapper.snap(pos, plane, enabled=enabled), plane
        snap, resolved = self.snapper.snap_start(pos, plane, enabled)
        # An endpoint in front of a hovered face can be at another height or
        # belong to another plane. That background face is not its support.
        if (abs((snap.point - plane.origin).dot(plane.normal)) > 1e-5
                or abs(resolved.normal.dot(plane.normal)) < 1 - 1e-7):
            self.support = None
        # Down returns a started drawing to this unlocked plane.
        self.start_plane = resolved, self.support
        if self.plane_lock is None:
            return snap, resolved
        locked = geo.Plane.named(self.plane_lock, snap.point)
        if not geo.same_plane(resolved, locked):
            self.support = None
        return snap, locked

    def click(self, pos):
        if self.measure_session is not None:
            self.measure_session.click(pos)
            return
        if self.offset_input is not None:
            if self.offset_input.click(pos): self.commit()
            return
        if self.elongate_input is not None:
            if self.elongate_input.click(pos): self.commit()
            return
        if self.push_pull_input is not None:
            if self.push_pull_input.click(pos): self.commit()
            return
        if self.anchor is not None:
            if self.motion(pos) is False:
                return
            self.commit()
            return
        if self.tool in ("Rectangle", "Circle", "Sphere", "Polygon", "Line", "Arc", "Arc2Point", "Tape"):
            start = self.drawing_start(pos)
            if start is None:
                self.miss_surface()
                return
            snap, self.plane = start
            if self.drawing_surface is not None:
                from ..surfaces.wrap import WrapFrame
                self.surface_frame = WrapFrame(self.surface_skin,self.drawing_surface[1],snap.point)
                self.plane = self.surface_frame.plane
                self.surface_point = geo.V()
            self.anchor = snap.point
            if self.tool == "Tape" or (self.tool == "Line" and self.plane_lock is None
                                       and self.controls.plane.currentText() == "Auto"):
                self.auto_line = True
                self.line_faces = self.snapper.faces_at(self.anchor)
            if self.tape_input is not None:
                self.tape_input.begin(snap)
        elif self.tool == "VertexMove":
            hit = pick(self.view, self.doc, pos, prefer_boundary=True)
            if not hit or not hit[3].startswith('Vertex'):
                raise ValueError('Click a vertex (corner point).')
            self.choose_vertex(hit[0], hit[3])
            self.down_pos = pos
            self.dragging = True
        elif self.tool == "PushPull":
            hit = pick(self.view, self.doc, pos, face_only=True)
            if not hit:
                raise ValueError("Click a flat face.")
            self.obj, self.face, self.anchor, _ = hit
            ops.editable(self.obj)
            self.normal = ops.extrusion_normal(self.obj, self.face)
            self.pull_contact = ops.extrusion_contact(self.obj, self.face)
            self.prepare_pull_references()
            self.down_pos = pos
            self.dragging = True
        else:
            hit = pick(self.view, self.doc, pos)
            if not self.objects:
                if not hit:
                    raise ValueError("Click an object to " + self.tool.lower() + ".")
                self.objects = [ops.editable(hit[0])]
                self.snapper = Snapper(self.doc, self.view, self.objects)
            self.anchor = self.base_snap(pos, hit).point
            self.plane.origin = self.anchor
            self.down_pos = pos
            self.dragging = True
        self.point = self.anchor
        if self.tool == "Line":
            self.last_pos = screen(self.view, self.anchor)
            self.message('Click next endpoint on the surface · Tab for surface length · Esc finishes'
                         if self.drawing_surface else "Click next endpoint · X/Y/Z or arrows lock an axis · Tab for size · Esc finishes")
        elif self.tool in ("Circle", "Sphere", "Polygon", "Arc", "Arc2Point"):
            # Once its center is fixed, snapping back to it would trap small
            # circles at zero radius inside the large face-center magnet.
            self.snapper.points = [(point, label) for point, label in self.snapper.points
                                   if (point - self.anchor).Length >= geo.EPS]
            self.controls.value.setPlaceholderText("Radius in mm")
            self.message("Click a vertex to set size and orientation · Sides changes the preview · Tab for radius · Esc cancels"
                         if self.tool == "Polygon" else "Click to set radius · Tab for exact radius · Esc cancels")
        if self.arc_input:
            self.message("Click radius start · Tab for radius · Esc cancels" if self.tool == "Arc" else
                         "Click second endpoint · Tab for endpoint distance · Esc cancels")
        elif self.tool == 'Rectangle':
            self.message('Click opposite corner · Tab for width, height' +
                         (' in the local surface frame · Esc cancels' if self.surface_frame else ' · Esc cancels'))
        elif self.tool not in ("Line", "Circle", "Sphere", "Polygon", "Tape"):
            self.message("Choose destination · Tab for size · Esc cancels" +
                         (" · X/Y/Z locks an axis" if self.tool in ("Move", "Copy", "VertexMove") else ""))

    def center_hint(self, pos, snap, plane):
        if (self.tool not in ("Line", "Circle", "Sphere", "Polygon", "Arc", "Arc2Point", "Move", "Copy", "Tape")
                or not self.controls.snap.isChecked()):
            return None
        if snap.label in ("Face center", "Circle center"):
            return snap.point
        if self.tool in ("Move", "Copy"):
            snapper = self.base_snapper if self.anchor is None else self.snapper
            return snapper.center_hint(pos) if snapper else None
        auto = self.drawing_surface is not None or (self.auto_line if self.anchor is not None else self.free_start())
        center = self.snapper.center_hint(pos, None if auto else plane)
        if center is not None and self.drawing_surface is not None:
            from ..surfaces.line import on_surface
            if not on_surface(self.drawing_surface[1], center):
                return None
        return center

    def base_snap(self, pos, hit=None):
        """Move/Copy base point: every snap, including on the moved objects."""
        if self.base_snapper is None:
            self.base_snapper = Snapper(self.doc, self.view)
        hit = hit or pick(self.view, self.doc, pos)
        origin = hit[2] if hit else (self.objects[0].Shape.BoundBox.Center if self.objects else geo.V())
        self.plane = geo.Plane.from_normal(origin, self.view.getViewDirection())
        return self.base_snapper.snap(pos, self.plane, spatial=True, enabled=self.controls.snap.isChecked())

    @staticmethod
    def hint_captured(snap, center):
        return (center is not None and snap is not None
                and snap.label in ("Endpoint", "Midpoint", "Face center", "Circle center")
                and (snap.point - center).Length < geo.EPS)

    def endpoint_hint(self, pos, snap, plane):
        """The vertex captured, or the nearest one just beyond capture."""
        if (self.tool not in ("Line", "Circle", "Sphere", "Polygon", "Arc", "Arc2Point", "Rectangle", "Move", "Copy", "Tape")
                or not self.controls.snap.isChecked()):
            return None
        if snap is not None and snap.label == "Endpoint":
            return snap.point
        snapper = self.base_snapper if self.tool in ("Move", "Copy") and self.anchor is None else self.snapper
        if snapper is None:
            return None
        hit = pick(self.view, self.doc, pos, face_only=True)
        if self.tool in ("Move", "Copy"):
            return snapper.endpoint_hint(pos, hit=hit)
        auto = self.drawing_surface is not None or (self.auto_line if self.anchor is not None else self.free_start())
        return snapper.endpoint_hint(pos, None if auto else plane, hit)

    def show_endpoint(self, pos, snap, plane):
        endpoint = self.endpoint_hint(pos, snap, plane) if pos is not None else None
        if endpoint is not None and self.drawing_surface is not None:
            from ..surfaces.line import on_surface
            if not on_surface(self.drawing_surface[1], endpoint):
                endpoint = None
        self.preview.show_endpoint(endpoint, self.hint_captured(snap, endpoint))

    def midpoint_hint(self, pos, snap, plane):
        if (self.tool not in ("Line", "Circle", "Sphere", "Polygon", "Arc", "Arc2Point", "Tape")
                or not self.controls.snap.isChecked()):
            return None
        if snap.label == "Midpoint":
            return snap.point
        auto = self.drawing_surface is not None or (self.auto_line if self.anchor is not None else self.free_start())
        midpoint = self.snapper.midpoint_hint(pos, None if auto else plane)
        if midpoint is not None and self.drawing_surface is not None:
            from ..surfaces.line import on_surface
            if not on_surface(self.drawing_surface[1], midpoint):
                return None
        return midpoint

    def motion(self, pos):
        if self.measure_session is not None:
            self.measure_session.hover(pos)
            return
        if self.offset_input is not None:
            self.offset_input.motion(pos)
            return
        if self.elongate_input is not None:
            self.elongate_input.motion(pos)
            return
        if self.push_pull_input is not None:
            self.push_pull_input.motion(pos)
            return
        # The snap and both hints read the same native ray pick of this pixel.
        with shared_picks():
            return self.hover(pos)

    def hover(self, pos):
        self.last_pos = pos
        if self.anchor is None:
            if self.tool in ("Rectangle", "Circle", "Sphere", "Polygon", "Line", "Arc", "Arc2Point", "Tape"):
                start = self.drawing_start(pos)
                if start is None:
                    return self.miss_surface()
                snap, plane = start
                center = self.center_hint(pos, snap, plane)
                midpoint = self.midpoint_hint(pos, snap, plane)
                self.show_endpoint(pos, snap, plane)
                self.preview.update(point=snap.point, center=center,
                                    center_snapped=self.hint_captured(snap, center),
                                    midpoint=midpoint, midpoint_snapped=self.hint_captured(snap, midpoint))
                self.controls.label.setText(snap.label)
            elif self.tool in ("Move", "Copy"):
                snap = self.base_snap(pos)
                center = self.center_hint(pos, snap, None)
                self.show_endpoint(pos, snap, None)
                self.preview.update(point=snap.point, center=center,
                                    center_snapped=self.hint_captured(snap, center))
                self.controls.label.setText(snap.label)
            elif self.tool == "VertexMove":
                hit = pick(self.view, self.doc, pos, prefer_boundary=True)
                self.preview.update(point=hit[1].Point if hit and hit[3].startswith('Vertex') else None)
            elif self.tool == "PushPull":
                hit = pick(self.view, self.doc, pos, face_only=True)
                self.preview.update(outline(hit[1]) if hit else [], hit[2] if hit else None)
            return
        if self.tool == "PushPull":
            step = max(self.face.BoundBox.DiagonalLength, 10.0)
            self.distance, scale = pull_drag(self.view, pos, self.anchor, self.normal, self.down_pos, step)
            self.pull_reference = None
            if self.controls.snap.isChecked() and self.snapper.settings.pull_faces:
                self.pull_reference = self.pull_references.snap(pos, self.snapper.settings.pull_radius)
                contact_distance = (snap_pull(self.view, self.distance, self.pull_contact.distance,
                                             self.anchor, self.normal, scale, self.snapper.settings.pull_radius)
                                    if self.pull_contact else None)
                if self.pull_contact and abs(contact_distance-self.pull_contact.distance) <= geo.EPS:
                    # Keep the exact contact magnet reliable when a farther
                    # reference projects behind it (e.g. returning a cut cap).
                    self.distance = contact_distance
                    if self.pull_reference and abs(self.pull_reference.distance-contact_distance) > geo.EPS:
                        self.pull_reference = None
                elif self.pull_reference:
                    self.distance = self.pull_reference.distance
            self.show_pull()
            return
        if self.tool == "VertexMove":
            snap, self.plane = self.snapper.snap_line(pos, self.plane, self.anchor, [],
                                                    self.controls.snap.isChecked(), axis=self.axis)
        elif self.drawing_surface is not None:
            chosen = self.surface_snap(pos, self.drawing_surface)
            if chosen is None:
                return self.miss_surface()
            snap, self.drawing_surface = chosen
        elif self.tool in ('Line', 'Tape'):
            snap, self.plane = self.snapper.snap_line(pos, self.plane, self.anchor,
                                                        self.line_faces, self.controls.snap.isChecked(),
                                                        axis=self.axis, fixed=not self.auto_line)
        else:
            snap = self.snapper.snap(pos, self.plane, self.anchor, self.controls.snap.isChecked(),
                                     self.axis, spatial=self.tool in ("Move", "Copy", "VertexMove"),
                                     infer_axes=self.tool not in ("Circle", "Sphere", "Polygon", "Arc", "Arc2Point"))
        self.point = snap.point
        if self.surface_frame is not None:
            try:
                self.surface_point = self.surface_frame.local(self.point,self.drawing_surface[1])
            except ValueError:
                return self.miss_surface()
        if self.arc_input:
            self.arc_input.update()
        self.controls.label.setText(snap.label)
        self.show_endpoint(pos, snap, self.plane)
        try:
            self.show_points(snap, self.center_hint(pos, snap, self.plane),
                             self.midpoint_hint(pos, snap, self.plane))
        except ValueError:
            if self.surface_frame is None:
                raise
            return self.miss_surface()

    def prepare_pull_references(self):
        from .pull_snapping import PullReferences
        self.pull_references = PullReferences(self.doc, self.view, self.anchor, self.normal, self.face)
        self.pull_reference = None

    def show_pull(self):
        delta = self.normal * self.distance
        base = outline(self.face)
        polylines = base + [[v.Point, v.Point + delta] for v in self.face.Vertexes]
        contact = None
        snapped = self.pull_contact is not None and abs(self.distance - self.pull_contact.distance) <= geo.EPS
        if self.pull_contact and self.controls.snap.isChecked() and self.snapper.settings.pull_faces:
            contact = self.face.CenterOfMass + self.normal * self.pull_contact.distance
        label = 'Opposite face'
        reference = self.pull_reference
        if reference and self.controls.snap.isChecked() and self.snapper.settings.pull_faces:
            contact = reference.point
            label = 'Opposite face' if snapped else reference.label
            snapped = True
        self.preview.update(polylines, self.anchor + delta, contact=contact, contact_snapped=snapped,
                            contact_label=label, moving=base, offset=delta)
        self.controls.label.setText((("On opposite face" if label == 'Opposite face' else label + ' snapped')
                                     if snapped else "Push/Pull") + " %.2f mm" % self.distance)

    def moving_outline(self):
        """The moved objects' outline, sampled once per drag and then translated."""
        shapes = [obj.Shape for obj in self.objects]
        cached = self.move_outline
        if (cached is None or len(cached[0]) != len(shapes)
                or not all(a.isSame(b) for a, b in zip(cached[0], shapes))):
            cached = self.move_outline = (shapes, [line for shape in shapes for line in edges(shape)])
        return cached[1]

    def show_points(self, snap=None, center=None, midpoint=None):
        if snap is None:
            self.preview.show_endpoint(None)  # Typed input or a fresh anchor.
        delta = self.point - self.anchor
        if self.arc_input:
            self.arc_input.preview(snap, center, midpoint)
        elif self.tape_input is not None:
            self.tape_input.preview(snap)
        elif self.surface_frame is not None and self.tool != 'Line':
            frame, plane = self.surface_frame, geo.Plane.named('XY')
            point = self.surface_point
            if self.tool == 'Rectangle':
                # Mapped side by side, so the width and height sides can be labelled.
                corners = geo.rectangle_points(plane, geo.V(), point)
                sides = [frame.points(corners[i:i + 2]) for i in range(4)]
                polylines = [sides[0] + [p for side in sides[1:] for p in side[1:]]]
                lengths = [(sides[0], '%.2f mm' % abs(point.x), self.point),
                           (sides[1], '%.2f mm' % abs(point.y), self.anchor)]
                hint = '%.2f, %.2f mm' % (abs(point.x), abs(point.y))
            else:
                if self.tool == 'Circle':
                    lines = [geo.circle_points(plane, geo.V(), point.Length), [geo.V(), point]]
                else:
                    lines = ([geo.polygon_points(plane, geo.V(), point, self.polygon_sides),
                              [geo.V(), point]] if point.Length >= geo.EPS else [])
                polylines = [frame.points(line) for line in lines]
                lengths = [(polylines[1], 'R %.2f mm' % point.Length)] if polylines else []
                hint = 'Radius %.2f mm' % point.Length
            self.preview.update(polylines, self.point, center=center,
                                center_snapped=self.hint_captured(snap, center),
                                midpoint=midpoint, midpoint_snapped=self.hint_captured(snap, midpoint),
                                lengths=lengths)
            self.controls.value.setPlaceholderText(hint+' on surface')
        elif self.tool == "Rectangle":
            corners = geo.rectangle_points(self.plane, self.anchor, self.point)
            width, height = abs(delta.dot(self.plane.u)), abs(delta.dot(self.plane.v))
            # Each size beside its side, outside the rectangle.
            self.preview.update([corners], self.point, lengths=[(corners[:2], "%.2f mm" % width, corners[2]),
                                                                (corners[1:3], "%.2f mm" % height, corners[0])])
            self.controls.value.setPlaceholderText("%.2f, %.2f mm" % (width, height))
        elif self.tool in ("Circle", "Sphere"):
            rings = (geo.sphere_points(self.anchor, delta.Length) if self.tool == "Sphere"
                     else [geo.circle_points(self.plane, self.anchor, delta.Length)])
            self.preview.update(rings + [[self.anchor, self.point]], self.point, center=center,
                                center_snapped=self.hint_captured(snap, center),
                                midpoint=midpoint, midpoint_snapped=self.hint_captured(snap, midpoint),
                                lengths=[([self.anchor, self.point], "R %.2f mm" % delta.Length)])
            self.controls.value.setPlaceholderText("Radius %.2f mm" % delta.Length)
        elif self.tool == "Polygon":
            polylines = ([geo.polygon_points(self.plane, self.anchor, self.point, self.polygon_sides),
                          [self.anchor, self.point]] if delta.Length >= geo.EPS else [])
            self.preview.update(polylines, self.point, center=center,
                                center_snapped=self.hint_captured(snap, center),
                                midpoint=midpoint, midpoint_snapped=self.hint_captured(snap, midpoint),
                                lengths=[([self.anchor, self.point], "R %.2f mm" % delta.Length)])
            self.controls.value.setPlaceholderText("Radius %.2f mm" % delta.Length)
        elif self.tool == "VertexMove":
            self.preview.update(self.vertex_neighborhood.preview(delta)+[[self.anchor,self.point]],
                                self.point, axis=snap.axis if snap else '')
            self.controls.value.setPlaceholderText('Δ %.2f, %.2f, %.2f mm' % (delta.x,delta.y,delta.z))
        elif self.tool == "Line":
            points = [self.anchor, self.point]
            if self.drawing_surface is not None:
                points = self.surface_frame.points([geo.V(),self.surface_point])
            length = sum((b-a).Length for a, b in zip(points, points[1:]))
            self.preview.update([points], self.point, center=center,
                                center_snapped=self.hint_captured(snap, center),
                                midpoint=midpoint, midpoint_snapped=self.hint_captured(snap, midpoint),
                                axis=snap.axis if snap else "", lengths=[(points, "%.2f mm" % length)])
            self.controls.value.setPlaceholderText("%.2f mm%s" % (length, ' on surface' if self.drawing_surface else ''))
        else:
            self.preview.update([[self.anchor, self.point]], self.point, center=center,
                                center_snapped=self.hint_captured(snap, center),
                                moving=self.moving_outline(), offset=delta)
            self.controls.value.setPlaceholderText("%.2f mm" % delta.Length)

    def typed_size(self, text):
        """Show a size being typed beside the shape being drawn; Enter draws it.

        A Line shows its length, Circle, Sphere and Polygon their radius, and
        a Rectangle its width and height as each is typed. The next pointer
        move shows the shape's own sizes again, while the field keeps the
        typed text for Enter.
        """
        if (self.tool not in ("Line", "Rectangle", "Circle", "Sphere", "Polygon", "Tape")
                or self.anchor is None or self.preview is None):
            return

        def label(value):
            value = value.strip()
            if not value:
                return None
            try:
                value = "%.2f mm" % geo.parse_length(value)
            except Exception:
                pass  # Unfinished, such as "2 c": shown as typed.
            return value if self.tool in ("Line", "Rectangle", "Tape") else "R " + value
        values = text.split(",")[:2] if self.tool == "Rectangle" else [text]
        self.preview.relabel([label(value) for value in values])

    def numeric(self):
        if not self.tool or self.anchor is None:
            self.message("Choose a starting point or face first.")
            return
        if self.drawing_surface is not None and self.point is None:
            self.message('Choose a point on the surface before entering a size.')
            return
        try:
            text = self.controls.value.text()
            if self.tape_input is not None:
                self.tape_input.numeric(text)
                self.commit()
                return
            if self.offset_input is not None:
                self.offset_input.numeric(text)
                self.commit()
                return
            if self.elongate_input is not None:
                self.elongate_input.numeric(text)
                self.commit()
                return
            if self.push_pull_input is not None:
                self.push_pull_input.numeric(text)
                self.commit()
                return
            if self.arc_input:
                if self.arc_input.numeric(text):
                    self.commit()
                return
            if self.surface_frame is not None:
                frame = self.surface_frame
                if self.tool == 'Rectangle':
                    values = text.split(',')
                    if len(values) != 2:
                        raise ValueError('Enter width, height; for example 40, 30 or 4 cm, 3 cm.')
                    width, height = map(geo.parse_length, values)
                    self.surface_point = geo.V(width, height, 0)
                else:
                    radius = geo.parse_length(text)
                    if self.tool == 'Line' and abs(radius)<geo.EPS:
                        raise ValueError('Enter a nonzero surface length.')
                    if self.tool != 'Line' and radius < geo.EPS:
                        raise ValueError('Enter a positive radius.')
                    direction = self.surface_point
                    direction = geo.unit(direction) if direction.Length >= geo.EPS else geo.V(1,0,0)
                    self.surface_point = direction*radius
                self.point = frame.point(self.surface_point)
            elif self.tool == "Rectangle":
                values = text.split(",")
                if len(values) != 2:
                    raise ValueError("Enter width, height; for example 40, 30 or 4 cm, 3 cm.")
                width, height = map(geo.parse_length, values)
                self.point = self.anchor + self.plane.u * width + self.plane.v * height
            elif self.tool == "VertexMove":
                values = text.split(',')
                if len(values) == 3:
                    delta = geo.V(*[geo.parse_length(value) for value in values])
                elif len(values) == 1:
                    direction = self.axis if self.axis is not None else self.point-self.anchor
                    delta = geo.unit(direction)*geo.parse_length(text)
                else:
                    raise ValueError('Enter dx, dy, dz (for example 5, 0, -2), or one distance on a locked axis.')
                self.point = self.anchor+delta
            elif self.tool == "PushPull":
                self.distance = geo.parse_length(text)
            elif self.tool in ("Circle", "Sphere"):
                radius = geo.parse_length(text)
                if radius < geo.EPS:
                    raise ValueError(self.tool + " needs a positive radius.")
                self.point = self.anchor + self.plane.u * radius
            elif self.tool == "Polygon":
                radius = geo.parse_length(text)
                if radius < geo.EPS:
                    raise ValueError("Polygon needs a positive radius.")
                direction = self.point - self.anchor
                direction = geo.unit(direction) if direction.Length >= geo.EPS else self.plane.u
                self.point = self.anchor + direction * radius
            else:
                length = geo.parse_length(text)
                direction = self.axis if self.axis is not None else self.point - self.anchor
                if self.tool == "Line" and self.axis is not None and (self.point - self.anchor).dot(self.axis) < 0:
                    direction = -self.axis
                self.point = self.anchor + geo.unit(direction) * length
            self.commit()
        except Exception as error:
            self.report(error)

    def commit(self):
        if self.drawing_surface is not None and self.point is None:
            return
        face_changed = False
        if self.tape_input is not None:
            self.tape_input.commit()
            return
        if self.offset_input is not None:
            results = self.offset_input.commit()
            face_changed = self.offset_input.profile.face
        elif self.elongate_input is not None:
            results = self.elongate_input.commit()
            face_changed = self.elongate_input.profile.is_face
        elif self.push_pull_input is not None:
            results = self.push_pull_input.commit()
        elif self.arc_input:
            if self.arc_input.second is None:
                self.arc_input.advance()
                return
            if self.surface_frame is not None:
                owner, _ = self.drawing_surface
                result, face_changed = ops.draw_surface_curve(self.doc, self.arc_input.edge(), owner, self.surface_frame.face, 'Surface arc')
            else:
                result, face_changed = ops.draw_arc(self.doc, self.arc_input.edge(), self.support)
            results = [result]
        elif self.surface_frame is not None and self.tool != 'Line':
            frame, plane = self.surface_frame, geo.Plane.named('XY')
            point = self.surface_point
            if self.tool == 'Rectangle':
                profile = geo.rectangle(plane, geo.V(), point)
            elif self.tool == 'Circle':
                profile = geo.circle(plane, geo.V(), point.Length)
            else:
                self.controls.sides.interpretText()
                profile = geo.polygon(plane, geo.V(), point, self.polygon_sides)
            owner, _ = self.drawing_surface
            result, face_changed = ops.draw_surface_curve(self.doc, frame.wire(profile), owner, frame.face,
                                                         'Surface '+self.tool.lower(), closed=True)
            results = [result]
        elif self.tool == "Rectangle":
            result, face_changed = ops.draw_profile(self.doc, geo.rectangle(self.plane, self.anchor, self.point),
                                                    self.support, "Rectangle")
            results = [result]
        elif self.tool == "Sphere":
            results = [ops.new_shape(self.doc, geo.sphere(self.anchor,
                       (self.point - self.anchor).Length), "Sphere")]
        elif self.tool == "Circle":
            result, face_changed = ops.draw_circle(self.doc, geo.circle(self.plane, self.anchor,
                                                                       (self.point - self.anchor).Length), self.support)
            results = [result]
        elif self.tool == "Polygon":
            # Commit any side count still being edited before a viewport click.
            self.controls.sides.interpretText()
            profile = geo.polygon(self.plane, self.anchor, self.point, self.polygon_sides)
            result, face_changed = ops.draw_polygon(self.doc, profile, self.support)
            results = [result]
        elif self.tool == "Line":
            if (self.point - self.anchor).Length < geo.EPS:
                self.message("Choose a different endpoint · Esc finishes")
                return
            surface_owner = None
            faces = {obj.Name: obj.Shape.countElement('Face') for obj in self.doc.Objects if obj.TypeId == 'Part::Feature'}
            if self.drawing_surface is not None:
                surface_owner, surface_face = self.drawing_surface
                surface_face = self.surface_frame.face_at(self.surface_point)
                curve = self.surface_frame.edge(geo.line(geo.V(),self.surface_point))
                result, face_changed = ops.draw_surface_curve(self.doc,curve,surface_owner,self.surface_frame.face,'Surface line')
            else:
                result, face_changed = ops.draw_line(self.doc, self.anchor, self.point, self.support)
            if (face_changed and result.Shape.countElement('Face') > faces.get(result.Name, 0)
                    and geo.on_face_boundary(result.Shape, self.point, geo.modeling_precision())):
                # A segment that closes a loop into a new or divided face ends
                # the chain, as in SketchUp. Retracing an edge does not, nor does
                # one that crosses an edge (such as a hidden seam) to a free end.
                self.cancel(quiet=True)
                Gui.Selection.clearSelection()
                self.focus_view()
                self.message('Loop closed · Face created' + (' · Surface → Offset face' if surface_owner else ' · P: Push/Pull')
                             + ' · L draws another line · Undo with ⌘Z')
                return
            # Each segment is already an independent Undo transaction. Keep one
            # callback/overlay and refresh the snapshot after native face edits
            # consume lines or change the face numbering.
            self.anchor = geo.V(self.point)
            self.line_undo_count = self.doc.UndoCount
            self.last_pos = screen(self.view, self.anchor)
            self.axis = None
            self.support = None
            self.snapper = Snapper(self.doc, self.view)
            self.line_faces = self.snapper.faces_at(self.anchor)
            if surface_owner is not None:
                from ..surfaces.line import same_surface
                hit = pick(self.view, self.doc, self.last_pos, face_only=True)
                region = Part.Vertex(self.anchor).BoundBox
                # A fitted face's 3D edge bounds can be off its exact surface
                # boundary within the source's native BREP tolerance.
                region.enlarge(max(1e-5,2*surface_owner.Shape.getTolerance(1)))
                index = geo.face_index(surface_owner.Shape)
                candidates = [index.faces[i] for i in index.near(region)
                              if same_surface(surface_face,index.faces[i])]
                if not candidates:
                    candidates = [f for f in surface_owner.Shape.Faces
                                  if same_surface(surface_face,f)]
                # Retain the underlying surface, not one side of the new
                # boundary. At fitted corners the native 3D distance to either
                # trimmed face can be nonzero; the next hit chooses its region.
                if not candidates:
                    # The segment is already committed and valid. Finish the
                    # session instead of retaining a stale support or crashing.
                    self.cancel(quiet=True)
                    self.focus_view()
                    self.message('Line added · Select a face and restart Line to continue')
                    return
                face = (hit[1] if hit and hit[0] == surface_owner
                        and any(hit[1].isSame(f) for f in candidates) else candidates[0])
                self.drawing_surface = (surface_owner, face)
                from ..surfaces.skin import Skin
                from ..surfaces.wrap import WrapFrame
                # A segment that divided nothing left the part as it was;
                # its connected skin is the same (40 ms on a fitted part).
                skin = self.surface_skin
                if skin is None or not skin.shape.isEqual(surface_owner.Shape) or not skin.contains(face):
                    skin = Skin(surface_owner.Shape,face)
                self.surface_skin = skin
                self.surface_frame = WrapFrame(self.surface_skin,face,self.anchor,build=False)
                self.surface_point = geo.V()
                if not self.surface_frame.analytic:
                    self.guide_timer.start(50)
            if self.auto_line:
                self.plane.origin = geo.V(self.anchor)
            Gui.Selection.clearSelection()
            self.controls.value.clear()
            self.controls.value.setPlaceholderText("Next length")
            self.controls.label.setText("Line")
            self.preview.update(point=self.anchor)
            self.focus_view()
            self.message(("Face updated" if face_changed else "Line added") +
                         (' · Click next endpoint on the surface · Tab for surface length · Esc finishes'
                          if self.drawing_surface else " · Click next endpoint · X/Y/Z or arrows lock an axis · Tab for size · Esc finishes"))
            return
        elif self.tool == "VertexMove":
            results = [ops.move_vertex(self.obj, self.vertex_name, self.point-self.anchor, self.vertex_neighborhood)]
        elif self.tool == "PushPull":
            results = ops.extrude(self.obj, self.face, self.distance, return_pieces=True)
        else:
            results = ops.transform(self.objects, self.point - self.anchor, copy=self.tool == "Copy")
        title = "Move Vertex" if self.tool == "VertexMove" else self.tool
        if title == 'PushPull' and len(results) > 1:
            title = 'Push/Pull · ' + str(len(results)) + ' pieces'
        surface_drawing = self.drawing_surface is not None
        self.cancel(quiet=True)
        Gui.Selection.clearSelection()
        for obj in ([] if face_changed else results):
            Gui.Selection.addSelection(obj)
        self.focus_view()
        if face_changed:
            shape = results[0].Shape
            hint = (" · Surface → Offset face" if surface_drawing else " · P: Push/Pull") if shape.Faces else ""
            self.message("Face updated" + hint + " · Undo with ⌘Z")
        else:
            self.message(title + " complete · Undo with ⌘Z · Choose the next tool")

    def lock_axis(self, char):
        """X/Y/Z, or a started Line's Right/Left/Up arrow, toggles a world axis; None unlocks."""
        if self.tool == 'Line' and self.anchor is not None and self.drawing_surface is not None:
            self.message('Surface lines follow the face · Switch to Draw: Plane for straight lines and X/Y/Z locks')
            return
        if self.tool in ("Line", "Tape") and self.anchor is None:
            self.message("Click the first " + ("endpoint" if self.tool == "Line" else "point") + " before locking an axis.")
            return
        direction = {"X": geo.V(1, 0, 0), "Y": geo.V(0, 1, 0), "Z": geo.V(0, 0, 1)}.get(char)
        if (direction is not None and self.tool == "Line" and self.anchor is not None and not self.auto_line
                and abs(direction.dot(self.plane.normal)) > geo.EPS):
            self.message("Choose an axis on the drawing plane, or restart Line in Auto.")
            return
        self.axis = None if direction is None or self.axis == direction else direction
        self.message((char + " axis " if char else "Axis ") + ("locked" if self.axis else "unlocked"))
        if self.tool in ("Line", "Tape", "VertexMove") and self.anchor is not None and self.last_pos is not None:
            try:
                self.motion(self.last_pos)
            except ValueError as error:
                self.report(error)

    def arrow_key(self, arrow):
        """Right/Left/Up lock the YZ/XZ/XY plane through the start point; Down is Auto.

        A started drawing turns about its first point at once; an arc keeps
        its plane once its second point lies off the new one. After a Line's
        first click the arrows lock its direction instead, as X/Y/Z do.
        """
        if self.surface_mode:
            self.message('Draw: Surface follows the face · Arrow keys choose a plane in Draw: Plane')
            return
        if self.tool == 'Line' and self.anchor is not None:
            self.lock_axis(geo.ARROW_AXES.get(arrow))
            return
        name = geo.arrow_plane(arrow, self.plane_lock)
        plane = support = None
        if self.anchor is not None:
            plane, support = self.start_plane or (self.plane, self.support)
            if name:
                locked = geo.Plane.named(name, self.anchor)
                support = support if geo.same_plane(plane, locked) else None
                plane = locked
            second = self.arc_input.second if self.arc_input else None
            if second is not None and abs((second - self.anchor).dot(plane.normal)) > 1e-5:
                self.message("The arc's first two points fix its plane · Esc starts again")
                return
        if self.plane_restore is None:
            self.plane_restore = self.controls.plane.currentText()
        self.plane_lock = name
        blocked = self.controls.plane.blockSignals(True)
        self.controls.plane.setCurrentText(name or 'Auto')
        self.controls.plane.blockSignals(blocked)
        if plane is not None:
            self.plane, self.support = plane, support
        if name:
            self.message(name + ' plane locked · ' + LOCK_TEXT[name] + ' · Through the ' +
                         ('first point' if self.anchor is not None else 'start point') + ' · Down returns to Auto')
        else:
            self.message('Auto plane · ' + ('Back to the plane at the first point' if self.anchor is not None else
                         'A flat face, a view plane over curves, or XY in empty space') + ' · Arrows lock a plane')
        if self.last_pos is not None:
            try:
                self.motion(self.last_pos)
            except Exception as error:
                # An edge-on plane is reported; the drawing stays open to orbit.
                self.report(error)
                if not isinstance(error, ValueError):
                    self.cancel(quiet=True)

    def plane_chosen(self, *unused):
        """A selector choice replaces an arrow lock; a started drawing keeps its plane."""
        self.plane_lock = self.plane_restore = None

    def eventFilter(self, watched, event):
        if not self.active:
            return False
        if self.mesh_region_session is not None:
            try:
                if self.mesh_region_session.handle_event(watched,event): return True
            except (ValueError,RuntimeError,ReferenceError) as error:
                self.cancel(quiet=True); self.report(error); return True
        if self.mesh_stretch_session is not None:
            try:
                if self.mesh_stretch_session.handles.handle_event(watched, event):
                    return True
            except (ValueError, RuntimeError, ReferenceError) as error:
                self.cancel(quiet=True)
                self.report(error)
                return True
        if self.selection.handle_event(watched, event):
            return True
        if event.type() not in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride):
            return False
        focus = QtWidgets.QApplication.focusWidget()
        in_box = self.size_input.owns(focus)
        in_value = bool(focus and (in_box or focus == self.controls.value or focus == self.controls.sides
                                  or self.controls.sides.isAncestorOf(focus)))
        if in_value:
            if event.key() == QtCore.Qt.Key_Escape:
                event.accept()
                if event.type() == QtCore.QEvent.KeyPress:
                    self.cancel()
                    self.focus_view()
                return True
            if in_box and event.key() in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab):
                # Between the width and height boxes, not on to other widgets.
                event.accept()
                if event.type() == QtCore.QEvent.KeyPress:
                    self.size_input.step(-1 if event.key() == QtCore.Qt.Key_Backtab else 1)
                return True
            return False
        edit = clipboard.command(event)
        if edit and clipboard.in_scope(self, focus):
            # Claim the shortcut so FreeCAD's own Copy/Paste does not also run.
            event.accept()
            if event.type() == QtCore.QEvent.KeyPress and not event.isAutoRepeat():
                clipboard.run(self, edit)
            return True
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        if not focus or not mdi or not (mdi.isAncestorOf(focus) or self.faces.contains(focus)):
            return False
        if isinstance(focus, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)):
            return False
        if event.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier | QtCore.Qt.AltModifier):
            if self.tool and event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Z:
                self.cancel()
            return False
        key, char = event.key(), event.text().upper()
        shortcuts = {"N": "Deform", "K": "Scale", "W": "Sweep", "V": "VertexMove", "E": "Offset", "X": "Elongate", "A": "Arc", "H": "Arc2Point", "S": "Select", "R": "Rectangle", "O": "Circle", "B": "Sphere", "G": "Polygon", "L": "Line", "P": "PushPull", "F": "Round", "D": "Subdivide", "Y": "Analytic", "U": "Slice", "J": "Union", "I": "Intersect", "M": "Move", "Q": "Rotate", "T": "Tape", "C": "Copy", "Z": "Measure"}
        numeric = bool(self.tool and self.anchor is not None and (key == QtCore.Qt.Key_Tab or event.text() in "0123456789.-" and event.text()))
        if char == "Q" and event.modifiers() & QtCore.Qt.ShiftModifier:
            shortcuts["Q"] = "Loft"
        axis = self.tool in ("Line", "Tape", "Move", "Copy", "VertexMove") and char in ("X", "Y", "Z")
        # Arrows belong to FreeCAD's navigation unless a drawing tool has the view.
        arrow = ARROW_KEYS.get(int(key)) if self.tool in DRAW_TOOLS and mdi.isAncestorOf(focus) else None
        handled = (key == QtCore.Qt.Key_Escape or char in shortcuts or key in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace)
                   or numeric or axis or arrow is not None)
        if not handled:
            return False
        event.accept()
        if event.type() == QtCore.QEvent.ShortcutOverride:
            return True
        if numeric:
            text = "" if key == QtCore.Qt.Key_Tab else event.text()
            if not self.size_input.open(text):
                self.controls.value.setFocus()
                self.controls.value.setText(text)
        elif arrow is not None:
            if not event.isAutoRepeat():
                self.arrow_key(arrow)
        elif axis:
            self.lock_axis(char)
        elif key == QtCore.Qt.Key_Escape:
            self.cancel()
        else:
            self.start(shortcuts.get(char, "Delete"))
        return True
