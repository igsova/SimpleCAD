"""Reversible face, boundary and seam display for native Part view providers.

Keep each edge's polyline slot and vertex count: Coin uses the line number as
the native EdgeN pick detail. Removing a slot silently renumbers later edges.
Face masks likewise preserve native face indices. Visibility metadata is saved
separately from these temporary display arrays; model geometry is untouched.
"""
import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin

from .qt import QtCore
from ..document import visibility, appearance
from . import surface_display, snapping
from ..core import geometry


def mask_indices(values, seams, edge_count):
    # Fail open for an unfamiliar renderer layout; never renumber native picks.
    if sum(value < 0 for value in values) != edge_count or (values and values[-1] >= 0):
        return tuple(values)
    result = []
    section = 0
    first = None
    for value in values:
        if value < 0:
            section += 1
            first = None
        else:
            if first is None:
                first = value
            if section in seams:
                value = first
        result.append(value)
    return tuple(result)


def edge_nodes(root):
    """Shared nodes occur in both Flat Lines and Wireframe; visit each once."""
    found = []
    def visit(node):
        if str(node.getTypeId().getName()) == "SoBrepEdgeSet":
            if not any(node == existing for existing in found):
                found.append(node)
        elif hasattr(node, "getNumChildren"):
            for index in range(node.getNumChildren()):
                visit(node.getChild(index))
    visit(root)
    return found


def face_nodes(root):
    found = []
    def visit(node):
        if str(node.getTypeId().getName()) == 'SoBrepFaceSet':
            if not any(node == existing for existing in found):
                found.append(node)
        elif hasattr(node, 'getNumChildren'):
            for i in range(node.getNumChildren()): visit(node.getChild(i))
    visit(root)
    return found


def mask_faces(values, counts, hidden):
    """Degenerate hidden triangles without changing FaceN or triangle indices."""
    if any(count < 0 for count in counts) or sum(counts) * 4 != len(values):
        raise ValueError('This FreeCAD face display format is not supported.')
    result = list(values)
    offset = 0
    for index, count in enumerate(counts, 1):
        if index in hidden:
            for start in range(offset, offset + count * 4, 4):
                result[start:start+3] = [values[start]] * 3
        offset += count * 4
    return tuple(result)


class EdgeMask:
    def __init__(self, node, changed):
        self.node = node
        self.original = None
        self.filtered = None
        self.sensor = coin.SoFieldSensor(lambda *unused: changed(), None)
        self.sensor.attach(node.coordIndex)

    def write(self, values):
        self.sensor.detach()
        try:
            self.node.coordIndex.setNum(len(values))
            self.node.coordIndex.setValues(list(values))
        finally:
            self.sensor.attach(self.node.coordIndex)

    def apply(self, seams, edge_count):
        current = tuple(self.node.coordIndex.getValues())
        if current != self.filtered:
            self.original = current
        filtered = mask_indices(self.original, seams, edge_count)
        self.filtered = filtered
        if current != filtered:
            self.write(filtered)

    def close(self):
        if self.original is not None and tuple(self.node.coordIndex.getValues()) == self.filtered:
            self.write(self.original)
        self.sensor.detach()


class FaceMask(EdgeMask):
    def apply(self, hidden, face_count):
        current = tuple(self.node.coordIndex.getValues())
        if current != self.filtered:
            self.original = current
        counts = tuple(self.node.getField('partIndex').getValues())
        if len(counts) != face_count:
            raise ValueError('Face display is still updating. Try the eye again.')
        filtered = mask_faces(self.original, counts, hidden)
        self.filtered = filtered
        if current != filtered:
            self.write(filtered)


class PointMask:
    """Retain original VertexN coordinate indices for visible point ranges."""
    def __init__(self, root, hidden, count):
        self.entries = []
        def visit(parent):
            if not hasattr(parent, 'getNumChildren'): return
            for i in range(parent.getNumChildren()):
                node = parent.getChild(i)
                if str(node.getTypeId().getName()) != 'SoBrepPointSet':
                    visit(node); continue
                replacement = coin.SoSeparator()
                start = node.startIndex.getValue()
                for index in range(count):
                    if index+1 not in hidden:
                        point = coin.SoPointSet()
                        point.startIndex = start+index
                        point.numPoints = 1
                        replacement.addChild(point)
                self.entries.append((parent, node, replacement))
                parent.replaceChild(i, replacement)
        visit(root)

    def close(self):
        for parent, node, replacement in self.entries:
            index = parent.findChild(replacement)
            if index >= 0: parent.replaceChild(index, node)
        self.entries.clear()


class SeamDisplay(QtCore.QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.show_seams = False
        self.records = {}
        self.appearances = {}
        self.topology = {}
        self.highlight_pending = QtCore.QTimer(self)
        self.highlight_pending.setSingleShot(True)
        self.highlights = surface_display.Highlights(self.schedule_highlights)
        self.highlight_pending.timeout.connect(self.highlights.refresh)
        self.pending = QtCore.QTimer(self)
        self.pending.setSingleShot(True)
        self.pending.timeout.connect(self.refresh)
        # Covers a recreated view/scene graph, even without a document edit.
        self.fallback = QtCore.QTimer(self)
        self.fallback.setInterval(500)
        self.fallback.timeout.connect(self.refresh)

    def start(self, show_seams=False):
        self.show_seams = show_seams
        if not self.running:
            self.running = True
            App.addDocumentObserver(self)
            Gui.Selection.addObserver(self.highlights)
            self.fallback.start()
        self.refresh()

    @staticmethod
    def close_record(record):
        for mask in record['masks']: mask.close()

    def stop(self):
        # Face visibility is a document view choice and stays in effect when
        # changing workbenches. Only the SimpleCAD seam preference is released.
        self.show_seams = True
        self.refresh()

    def restore(self):
        for record in self.records.values():
            self.close_record(record)
        self.records.clear()
        self.appearances.clear()
        self.topology.clear()
        self.highlights.prune(set())

    def schedule_highlights(self, *unused):
        if not self.highlight_pending.isActive():
            self.highlight_pending.start(0)

    def configure(self, show_seams):
        self.show_seams = show_seams
        self.refresh()

    def clear_seam_highlights(self, obj, seams):
        # Selection contexts can cache the old (visible) polyline separately
        # from coordIndex. Drop only seam sub-selections before first masking;
        # preserve ordinary selected edges/faces and whole-object selections.
        names = {"Edge" + str(index + 1) for index in seams}
        for selected in Gui.Selection.getSelectionEx(obj.Document.Name):
            if selected.Object == obj:
                for name in selected.SubElementNames:
                    if name in names:
                        Gui.Selection.removeSelection(obj, name)
        preselection = Gui.Selection.getPreselection()
        if (preselection and preselection.ObjectName == obj.Name and
                preselection.DocumentName == obj.Document.Name and names.intersection(preselection.SubElementNames)):
            Gui.Selection.clearPreselection()

    def schedule(self, *unused):
        if self.running and not self.pending.isActive():
            self.pending.start(0)

    slotCreatedObject = schedule
    slotDeletedObject = schedule
    slotChangedObject = schedule
    slotRecomputedDocument = schedule
    slotUndoDocument = schedule
    slotRedoDocument = schedule
    slotFinishRestoreDocument = schedule

    def slotDeletedDocument(self, doc):
        from ..document import locking
        locking.forget_document(doc.Name)
        visibility.forget_document(doc.Name)
        snapping.forget_document(doc.Name)
        from .tools.smart_select import forget_document
        forget_document(doc.Name)
        from .tools import curvature as curvature_ui
        curvature_ui.forget_document(doc.Name)
        self.appearances = {key: value for key, value in self.appearances.items() if key[0] != doc.Name}
        self.topology = {key: value for key, value in self.topology.items() if key[0] != doc.Name}
        self.highlights.prune({key for key in self.highlights.records if key[0] != doc.Name})
        # Detach while its scene graph is still alive.
        for key in list(self.records):
            if key[0] == doc.Name:
                self.close_record(self.records.pop(key))

    def refresh(self):
        if not self.running:
            return
        present = set()
        styled = set()
        for doc in App.listDocuments().values():
            for obj in doc.Objects:
                if obj.TypeId != "Part::Feature" or obj.Shape.isNull():
                    continue
                key = (doc.Name, obj.Name)
                styled.add(key)
                self.appearances[key] = appearance.sync_display(obj, self.appearances.get(key))
                mixed = surface_display.mixed_opacity(obj.ViewObject.ShapeAppearance)
                if key in appearance._previewing:
                    for material in appearance.face_material_nodes(obj.ViewObject.RootNode):
                        alpha = tuple(material.transparency.getValues())
                        mixed = mixed or len(set(alpha)) > 1
                self.highlights.sync(obj, mixed)
                shape = obj.Shape
                hidden = visibility.hidden_faces(obj)
                cached = self.topology.get(key)
                if cached is None or cached[0] != obj or not shape.isSame(cached[1]):
                    cached = (obj, shape, geometry.seam_indices(shape))
                    self.topology[key] = cached
                seams = set() if self.show_seams else cached[2]
                if not hidden and not seams:
                    continue
                present.add(key)
                record = self.records.get(key)
                if record is not None and (not shape.isSame(record['shape']) or record['hidden'] != hidden):
                    self.close_record(record)
                    record = None
                if record is None:
                    record = {'shape': shape, 'hidden': hidden, 'masks': [], 'object': obj}
                    self.records[key] = record
                    hidden_edges, hidden_vertices = visibility.hidden_elements(shape, hidden)
                    record['edges'] = {i-1 for i in hidden_edges}
                    record['vertices'] = hidden_vertices
                    if hidden_vertices:
                        record['masks'].append(PointMask(obj.ViewObject.RootNode, hidden_vertices, len(shape.Vertexes)))
                blocked_edges = seams | record['edges']
                nodes = edge_nodes(obj.ViewObject.RootNode) if blocked_edges else []
                faces = face_nodes(obj.ViewObject.RootNode) if hidden else []
                retained = []
                for mask in record['masks']:
                    if isinstance(mask, PointMask) or any(mask.node == node for node in nodes+faces):
                        retained.append(mask)
                    else:
                        mask.close()
                for node in nodes+faces:
                    if not any(isinstance(mask, EdgeMask) and mask.node == node for mask in retained):
                        retained.append((FaceMask if any(node == face for face in faces) else EdgeMask)(node, self.schedule))
                record['masks'] = retained
                for mask in retained:
                    if isinstance(mask, FaceMask):
                        mask.apply(hidden, len(shape.Faces))
                    elif isinstance(mask, EdgeMask):
                        if tuple(mask.node.coordIndex.getValues()) != mask.filtered:
                            self.clear_seam_highlights(obj, blocked_edges)
                        mask.apply(blocked_edges, len(shape.Edges))
        for key in set(self.records) - present:
            self.close_record(self.records.pop(key))
        for key in set(self.appearances) - styled:
            del self.appearances[key]
        for key in set(self.topology) - styled:
            del self.topology[key]
        self.highlights.prune(styled)
        self.highlights.refresh()
