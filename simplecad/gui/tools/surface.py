"""Dialogs of the curved-surface tools: Draw on surface, Offset face,
Shell/Thicken, Draft, Delete & heal, Remove rounds, Fill hole, Unwrap and
Pattern.

Previews are temporary overlays; the document changes only when a dialog is
applied, through surface_ops in one Undo step.
"""
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part

from ...core import coincident
from ...modeling import patterns
from ..previews import overlay as preview
from ...surfaces import edit as se, offset as surface_offset, operations as so
from ..qt import QtCore, QtWidgets
from ..panels import anchor_panel

V = App.Vector
PREVIEW_EDGES = 400  # objects with more edges preview as their bounding boxes


def selection():
    return [(item.Object, tuple(item.SubElementNames)) for item in Gui.Selection.getSelectionEx()
            if item.Object.Document == App.ActiveDocument]


def one_object(chosen, what):
    owners = list(dict.fromkeys(obj for obj, _ in chosen))
    if len(owners) != 1:
        raise ValueError('Select %s on one object.' % what)
    obj = owners[0]
    names = [name for o, names in chosen if o == obj for name in names]
    return obj, list(dict.fromkeys(names))


def picked_point(obj, names):
    """Where the user clicked one of the selected faces, when the selection recorded it."""
    if not names:
        return None
    faces = Part.makeCompound([obj.Shape.getElement(name) for name in names])
    for item in Gui.Selection.getSelectionEx():
        if item.Object != obj:
            continue
        for point in getattr(item, 'PickedPoints', ()):
            if faces.distToShape(Part.Vertex(point))[0] < 1e-4:
                return V(point)
    return None


def plural(count, word, many=None):
    return '%d %s' % (count, word if count == 1 else many or word + 's')


def spin(value, low, high, suffix=' mm', decimals=3, name=None):
    box = QtWidgets.QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setValue(value)
    box.setSuffix(suffix)
    box.setKeyboardTracking(False)
    if name:
        box.setObjectName(name)
    return box


def count_spin(value, low, high, name=None):
    box = QtWidgets.QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    box.setKeyboardTracking(False)
    if name:
        box.setObjectName(name)
    return box


def boundary_normals(shape, indices):
    """Points along the edges of the faces, each with the face normal there."""
    lines = []
    for i in indices:
        face = shape.Faces[i]
        for edge in face.Edges:
            if edge.Degenerated:
                continue
            line = []
            for point in edge.discretize(max(4, min(48, int(edge.Length / 2)))):
                try:
                    line.append((point, face.normalAt(*face.Surface.parameter(point))))
                except (Part.OCCError, RuntimeError):
                    continue
            if len(line) >= 2:
                lines.append(line)
    return lines


def moved_lines(samples, distance):
    """Edges moved along the normals, with a wall line at the start of each."""
    lines = []
    for line in samples:
        lines.append([p + n * distance for p, n in line])
        lines.append([line[0][0], line[0][0] + line[0][1] * distance])
    return lines


def face_lines(shape):
    return [line for face in shape.Faces for line in preview.edges(face)]


def box_lines(box):
    corners = [V(x, y, z) for x in (box.XMin, box.XMax) for y in (box.YMin, box.YMax) for z in (box.ZMin, box.ZMax)]
    pairs = ((0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7))
    return [[corners[a], corners[b]] for a, b in pairs]


class PreviewDialog(QtWidgets.QDialog):
    """Apply/Cancel dialog that redraws a temporary preview after edits."""
    title = 'SimpleCAD'

    def __init__(self, name, apply_text='Apply', parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setWindowTitle(self.title)
        self.setObjectName(name)
        self.preview = preview.Preview(Gui.activeDocument().activeView())
        self.column = QtWidgets.QVBoxLayout(self)
        self.form = QtWidgets.QFormLayout()
        self.column.addLayout(self.form)
        self.info = QtWidgets.QLabel()
        self.info.setObjectName(name + 'Info')
        self.info.setWordWrap(True)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.redraw)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.apply_button = self.buttons.button(QtWidgets.QDialogButtonBox.Ok)
        self.apply_button.setText(apply_text)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.setMinimumWidth(440)
        anchor_panel(self)

    def finish_layout(self, note=''):
        self.column.addWidget(self.info)
        if note:
            hint = QtWidgets.QLabel(note)
            hint.setWordWrap(True)
            self.column.addWidget(hint)
        self.column.addWidget(self.buttons)
        self.schedule()

    def watch(self, *widgets):
        for widget in widgets:
            for signal in ('valueChanged', 'currentIndexChanged', 'toggled', 'textChanged'):
                if hasattr(widget, signal):
                    getattr(widget, signal).connect(self.schedule)
                    break

    def schedule(self, *_):
        self.timer.start(150)

    def redraw(self):
        try:
            lines, text = self.lines()
            self.apply_button.setEnabled(True)
        except ValueError as error:
            lines, text = [], str(error)
            self.apply_button.setEnabled(False)
        self.info.setText(text)
        self.preview.update(polylines=lines)

    def lines(self):
        return [], ''

    def done(self, result):
        self.timer.stop()
        self.preview.close()
        super().done(result)


# --- Remove rounds -----------------------------------------------------------------

class RoundsDialog(PreviewDialog):
    title = 'Remove rounds'

    def __init__(self, obj, names):
        super().__init__('SimpleCADRemoveRounds', 'Remove')
        self.obj, self.names = obj, names
        self.radius = spin(5.0, .001, 10000, name='SimpleCADRoundRadius')
        self.radius.setToolTip('Rounds with this radius or smaller are removed.')
        self.form.addRow('Largest radius', self.radius)
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName('SimpleCADRoundKind')
        for key, text in (('any', 'Outside and inside rounds'), ('convex', 'Outside rounds (convex) only'),
                          ('concave', 'Inside rounds (concave) only')):
            self.kind.addItem(text, key)
        self.form.addRow('Which rounds', self.kind)
        self.watch(self.radius, self.kind)
        self.found = []
        self.finish_layout('Highlighted faces are removed and their neighbours extended until they meet again, '
                           'leaving a sharp edge. %s One Undo step.' % (
                               'Only the selected faces are searched.' if names else 'The whole object is searched.'))

    def values(self):
        return self.radius.value(), self.kind.currentData()

    def lines(self):
        self.found = so.rounds(self.obj, self.radius.value(), self.kind.currentData(), self.names)
        if not self.found:
            raise ValueError('No rounds up to this radius found.')
        radii = [r['radius'] for r in self.found]
        faces = [self.obj.Shape.Faces[r['index']] for r in self.found]
        return face_lines(Part.makeCompound(faces)), '%s found, radius %.3g to %.3g mm.' % (
            plural(len(self.found), 'round'), min(radii), max(radii))


# --- Draw on surface -------------------------------------------------------------

class ImprintDialog(PreviewDialog):
    title = 'Draw on surface'
    SHAPES = (('rectangle', 'Rectangle'), ('circle', 'Circle'), ('polygon', 'Polygon'), ('text', 'Text'))
    MODES = (('imprint', 'Split into a selectable region'), ('emboss', 'Raise it (emboss)'),
             ('deboss', 'Recess it (deboss)'))

    def __init__(self, obj, names, point):
        super().__init__('SimpleCADImprint', 'Draw')
        self.obj, self.names, self.point = obj, names, point
        self.shape = QtWidgets.QComboBox()
        self.shape.setObjectName('SimpleCADImprintShape')
        for key, text in self.SHAPES:
            self.shape.addItem(text, key)
        self.form.addRow('Shape', self.shape)
        self.width = spin(10, .01, 10000, name='SimpleCADImprintWidth')
        self.height = spin(10, .01, 10000, name='SimpleCADImprintHeight')
        self.diameter = spin(10, .01, 10000, name='SimpleCADImprintDiameter')
        self.sides = count_spin(6, 3, 64, 'SimpleCADImprintSides')
        self.text = QtWidgets.QLineEdit('ABC')
        self.text.setObjectName('SimpleCADImprintText')
        self.size = spin(5, .1, 1000, name='SimpleCADImprintTextSize')
        self.font = se.default_font()
        self.font_button = QtWidgets.QPushButton(os.path.basename(self.font) or 'Choose a font…')
        self.font_button.clicked.connect(self.choose_font)
        self.rows = {}
        for key, label, widget in (('width', 'Width', self.width), ('height', 'Height', self.height),
                                   ('diameter', 'Diameter', self.diameter), ('sides', 'Sides', self.sides),
                                   ('text', 'Text', self.text), ('size', 'Letter height', self.size),
                                   ('font', 'Font', self.font_button)):
            self.form.addRow(label, widget)
            self.rows[key] = widget
        self.angle = spin(0, -360, 360, '°', 2, 'SimpleCADImprintAngle')
        self.shift_x = spin(0, -10000, 10000, name='SimpleCADImprintShiftX')
        self.shift_y = spin(0, -10000, 10000, name='SimpleCADImprintShiftY')
        self.form.addRow('Rotation', self.angle)
        self.form.addRow('Move across', self.shift_x)
        self.form.addRow('Move up', self.shift_y)
        self.mode = QtWidgets.QComboBox()
        self.mode.setObjectName('SimpleCADImprintMode')
        for key, text in self.MODES:
            self.mode.addItem(text, key)
        self.form.addRow('Result', self.mode)
        self.depth = spin(1, .001, 1000, name='SimpleCADImprintDepth')
        self.form.addRow('Depth', self.depth)
        self.wrap = QtWidgets.QCheckBox('Wrap onto the curve, keeping its size')
        self.wrap.setObjectName('SimpleCADImprintWrap')
        self.wrap.setToolTip('Wrapped drawings follow one face like a label, keeping their lengths, and rise along '
                             'the face normals. Unwrapped drawings are projected straight and can span faces.')
        self.wrap.setChecked(len(names) == 1 and not isinstance(obj.Shape.getElement(names[0]).Surface, Part.Plane))
        self.form.addRow('', self.wrap)
        self.flat_maps = {}
        self.shape.currentIndexChanged.connect(self.show_fields)
        self.mode.currentIndexChanged.connect(self.show_fields)
        self.watch(self.shape, self.width, self.height, self.diameter, self.sides, self.text, self.size,
                   self.angle, self.shift_x, self.shift_y, self.mode, self.depth, self.wrap)
        self.show_fields()
        self.finish_layout('The drawing is centred where you clicked the face, then wrapped onto that face or '
                           'projected straight onto the selected faces. Split regions can be coloured, offset or '
                           'deleted. One Undo step.')

    def choose_font(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Font for the text', os.path.dirname(self.font),
                                                        'Fonts (*.ttf *.otf *.ttc)')
        if path:
            self.font = path
            self.font_button.setText(os.path.basename(path))
            self.schedule()

    def show_fields(self, *_):
        kind = self.shape.currentData()
        shown = {'rectangle': ('width', 'height'), 'circle': ('diameter',), 'polygon': ('diameter', 'sides'),
                 'text': ('text', 'size', 'font')}[kind]
        for key, widget in self.rows.items():
            widget.setVisible(key in shown)
            self.form.labelForField(widget).setVisible(key in shown)
        raised = self.mode.currentData() != 'imprint'
        self.depth.setVisible(raised)
        self.form.labelForField(self.depth).setVisible(raised)

    def outline(self):
        return se.outline(self.shape.currentData(), width=self.width.value(), height=self.height.value(),
                          diameter=self.diameter.value(), sides=self.sides.value(), text=self.text.text(),
                          size=self.size.value(), font=self.font)

    def values(self):
        return dict(outline=self.outline(), point=self.point, angle=self.angle.value(),
                    shift=(self.shift_x.value(), self.shift_y.value()), mode=self.mode.currentData(),
                    depth=self.depth.value(), wrap=self.wrap.isChecked())

    def wrapped_lines(self):
        profile, (origin, normal, x) = so.wrapping(self.obj, self.names, self.outline(), self.point,
                                                   self.angle.value(), (self.shift_x.value(), self.shift_y.value()))
        shape = so.local(self.obj)
        index = min(so.indices(self.obj, self.names), key=lambda i: shape.Faces[i].distToShape(Part.Vertex(origin))[0])
        if index not in self.flat_maps:
            self.flat_maps[index] = se.FlatMap(shape.Faces[index])
        lines = se.wrap_lines(self.flat_maps[index], profile, origin, normal, x)
        placement = self.obj.Placement
        return ([[placement.multVec(p) for p in line] for line in lines],
                'The drawing wraps onto Face%d keeping its size.' % (index + 1))

    def lines(self):
        if self.wrap.isChecked():
            return self.wrapped_lines()
        profile, direction = so.drawing(self.obj, self.names, self.outline(), self.point, self.angle.value(),
                                        (self.shift_x.value(), self.shift_y.value()))
        lines = preview.edges(so.world(profile, self.obj))
        try:
            projected = se.project(so.local(self.obj), so.indices(self.obj, self.names), profile, direction)
        except ValueError as error:
            raise ValueError(str(error)) from error
        lines += preview.edges(so.world(Part.makeCompound(projected), self.obj))
        text = 'The outline lands on the faces in %s.' % plural(len(projected), 'piece')
        try:
            loose = any(not Part.Wire(group).isClosed() for group in Part.sortEdges(projected))
        except (Part.OCCError, RuntimeError):
            loose = True
        if loose:
            text += ' Part of it runs off the selected faces; only closed parts become regions.'
        return lines, text


# --- Offset face -------------------------------------------------------------------------

class OffsetDialog(PreviewDialog):
    title = 'Offset face'

    def __init__(self, obj, names):
        super().__init__('SimpleCADOffsetFace', 'Offset')
        self.obj, self.names = obj, names
        self.distance = spin(1, -10000, 10000, name='SimpleCADOffsetDistance')
        self.distance.setToolTip('Positive moves the faces outward and adds material; negative moves them '
                                 'inward and cuts.')
        self.form.addRow('Distance', self.distance)
        self.watch(self.distance)
        self.samples = boundary_normals(obj.Shape, so.indices(obj, names))
        self.finish_layout('Each face moves along its own normal, like Push/Pull on a flat face. Side walls '
                           'run straight along the normals; neighbouring faces do not stretch. One Undo step.')

    def lines(self):
        distance = self.distance.value()
        if abs(distance) < 1e-6:
            raise ValueError('Enter a distance other than zero.')
        return moved_lines(self.samples, distance), '%s move %.3g mm %s.' % (
            plural(len(self.names), 'face'), abs(distance),
            'outward, adding material' if distance > 0 else 'inward, cutting into the part')


# --- Shell and thicken -------------------------------------------------------------------

class ShellDialog(PreviewDialog):
    SIDES = (('front', 'In front, along the face normals'), ('back', 'Behind the faces'),
             ('both', 'Both sides, half each'))

    def __init__(self, obj, names):
        self.surface = so.is_surface(obj)
        self.title = 'Thicken' if self.surface else 'Shell'
        super().__init__('SimpleCADShell', 'Thicken' if self.surface else 'Hollow')
        self.obj, self.names = obj, names
        self.thickness = spin(1, .001, 1000, name='SimpleCADShellThickness')
        self.form.addRow('Thickness' if self.surface else 'Wall thickness', self.thickness)
        self.side = QtWidgets.QComboBox()
        self.side.setObjectName('SimpleCADShellSide')
        for key, text in self.SIDES:
            self.side.addItem(text, key)
        if self.surface:
            self.form.addRow('Grow', self.side)
            self.samples = boundary_normals(obj.Shape, range(len(obj.Shape.Faces)))
        self.watch(self.thickness, self.side)
        self.finish_layout('The surface becomes a solid wall of this thickness. One Undo step.' if self.surface else
                           'The part is hollowed inward to this wall. Selected faces are left open; with none '
                           'selected it becomes a closed hollow. One Undo step.')

    def lines(self):
        thickness = self.thickness.value()
        if self.surface:
            side = self.side.currentData()
            distances = {'front': [thickness], 'back': [-thickness], 'both': [thickness / 2, -thickness / 2]}[side]
            lines = [line for d in distances for line in moved_lines(self.samples, d)]
            return lines, 'The surface becomes a %.3g mm thick solid.' % thickness
        if not self.names:
            return [], 'A closed hollow inside, %.3g mm walls.' % thickness
        faces = Part.makeCompound([self.obj.Shape.getElement(name) for name in self.names])
        return face_lines(faces), '%s left open, %.3g mm walls.' % (plural(len(self.names), 'face'), thickness)


# --- Draft -------------------------------------------------------------------------------

class DraftDialog(PreviewDialog):
    title = 'Draft faces'
    AXES = (('Z', 'World Z (up)'), ('X', 'World X'), ('Y', 'World Y'))

    def __init__(self, obj, names):
        super().__init__('SimpleCADDraft', 'Draft')
        self.obj, self.names = obj, names
        self.angle = spin(3, .01, 89.9, '°', 2, 'SimpleCADDraftAngle')
        self.form.addRow('Angle', self.angle)
        self.axis = QtWidgets.QComboBox()
        self.axis.setObjectName('SimpleCADDraftAxis')
        for key, text in self.AXES:
            self.axis.addItem(text, key)
        self.form.addRow('Pull direction', self.axis)
        self.hinge = QtWidgets.QComboBox()
        self.hinge.setObjectName('SimpleCADDraftHinge')
        self.hinge.addItem('At the bottom of the faces', 'bottom')
        self.hinge.addItem('At the top of the faces', 'top')
        self.form.addRow('Hinge', self.hinge)
        self.narrower = QtWidgets.QComboBox()
        self.narrower.setObjectName('SimpleCADDraftNarrower')
        self.narrower.addItem('Narrower toward the top', 'top')
        self.narrower.addItem('Narrower toward the bottom', 'bottom')
        self.form.addRow('Taper', self.narrower)
        self.watch(self.angle, self.axis, self.hinge, self.narrower)
        self.finish_layout('Faces tilt about the hinge plane, square to the pull direction, and stay in place '
                           'where they cross it. "Top" is the pull direction. Flat and round faces only. '
                           'One Undo step.')

    def values(self):
        return dict(angle=self.angle.value(), axis=self.axis.currentData(), hinge=self.hinge.currentData(),
                    narrower=self.narrower.currentData())

    def lines(self):
        shape = self.obj.Shape
        chosen = so.indices(self.obj, self.names)
        axis = V(*{'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}[self.axis.currentData()])
        for i in chosen:
            face = shape.Faces[i]
            if not isinstance(face.Surface, (Part.Plane, Part.Cylinder, Part.Cone)):
                raise ValueError('Draft works on flat, cylindrical and conical faces, not on free-form curved ones.')
            if isinstance(face.Surface, Part.Plane) and abs(face.normalAt(0, 0).dot(axis)) > 1 - 1e-6:
                raise ValueError('A face square to the pull direction cannot be drafted. Select the side walls.')
        height = surface_offset.hinge_height(shape, chosen, axis, self.hinge.currentData())
        box = Part.makeCompound([shape.Faces[i] for i in chosen]).BoundBox
        u = V(1, 0, 0) if abs(axis.x) < .9 else V(0, 1, 0)
        w = axis.cross(u)
        corners = [V(x, y, z) for x in (box.XMin, box.XMax) for y in (box.YMin, box.YMax) for z in (box.ZMin, box.ZMax)]
        us, ws = [c.dot(u) for c in corners], [c.dot(w) for c in corners]
        margin = .1 * max(box.DiagonalLength, 1)
        rim = [axis * height + u * a + w * b for a, b in ((min(us) - margin, min(ws) - margin),
                                                          (max(us) + margin, min(ws) - margin),
                                                          (max(us) + margin, max(ws) + margin),
                                                          (min(us) - margin, max(ws) + margin))]
        centre = axis * height + u * ((min(us) + max(us)) / 2) + w * ((min(ws) + max(ws)) / 2)
        arrow = [centre, centre + axis * (box.DiagonalLength / 3 or 5)]
        return [rim + rim[:1], arrow], '%s tilt %.3g° about the hinge plane; the part narrows toward the %s.' % (
            plural(len(chosen), 'face'), self.angle.value(), self.narrower.currentData())


# --- Fill hole ------------------------------------------------------------------------

class FillDialog(PreviewDialog):
    title = 'Fill hole'

    def __init__(self, obj, edges):
        super().__init__('SimpleCADFillHole', 'Fill')
        self.obj, self.edges = obj, edges
        self.smooth = QtWidgets.QCheckBox('Blend smoothly into the neighbouring faces')
        self.smooth.setObjectName('SimpleCADFillSmooth')
        self.smooth.setChecked(True)
        self.smooth.setToolTip('Curved openings get a patch tangent to the faces around them. Flat openings '
                               'are always closed with a flat face.')
        self.column.addWidget(self.smooth)
        self.finish_layout('Highlighted rims are closed with patches. A surface with no openings left becomes '
                           'a solid. One Undo step.')

    def lines(self):
        loops = so.openings(self.obj)
        if self.edges:
            chosen = [self.obj.Shape.getElement(name) for name in self.edges]
            loops = [w for w in loops if any(e.isSame(c) or coincident.same(e, c) for e in w.Edges for c in chosen)]
        if not loops:
            raise ValueError('The selected edges are not on the rim of an opening.' if self.edges
                             else 'This object has no openings to fill.')
        return [line for wire in loops for line in preview.edges(wire)], '%s to fill.' % plural(len(loops), 'opening')


# --- Pattern ------------------------------------------------------------------------------

class PatternDialog(PreviewDialog):
    title = 'Pattern'

    def __init__(self, objects, path):
        super().__init__('SimpleCADPattern', 'Make copies')
        self.objects, self.path = objects, path
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName('SimpleCADPatternKind')
        self.kind.addItem('Grid along X, Y and Z', 'grid')
        self.kind.addItem('Around an axis', 'radial')
        if path is not None:
            self.kind.addItem('Along the selected path', 'path')
            self.kind.setCurrentIndex(2)
        self.form.addRow('Pattern', self.kind)
        size = App.BoundBox()
        for obj in objects:
            size.add(obj.Shape.BoundBox)
        step = round(max(size.XLength, size.YLength, size.ZLength, 1) * 1.5, 1)
        self.counts = [count_spin(n, 1, 500, 'SimpleCADPatternCount' + a) for n, a in ((3, 'X'), (1, 'Y'), (1, 'Z'))]
        self.spacing = [spin(step, -100000, 100000, name='SimpleCADPatternSpacing' + a) for a in 'XYZ']
        self.grid_rows = []
        for axis, count, spacing in zip('XYZ', self.counts, self.spacing):
            row = QtWidgets.QWidget()
            line = QtWidgets.QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.addWidget(count)
            line.addWidget(QtWidgets.QLabel('every'))
            line.addWidget(spacing)
            self.form.addRow('Along %s' % axis, row)
            self.grid_rows.append(row)
        self.count = count_spin(6, 2, 500, 'SimpleCADPatternCount')
        self.form.addRow('Count', self.count)
        self.angle = spin(360, -360, 360, '°', 2, 'SimpleCADPatternAngle')
        self.form.addRow('Total angle', self.angle)
        self.axis = QtWidgets.QComboBox()
        self.axis.setObjectName('SimpleCADPatternAxis')
        for axis in 'XYZ':
            self.axis.addItem('World ' + axis, axis)
        self.axis.setCurrentIndex(2)
        self.form.addRow('Axis', self.axis)
        self.center = QtWidgets.QComboBox()
        self.center.setObjectName('SimpleCADPatternCenter')
        self.center.addItem('World origin', 'origin')
        self.center.addItem('Selection centre', 'selection')
        self.form.addRow('Through', self.center)
        self.align = QtWidgets.QCheckBox('Turn the copies with the path')
        self.align.setObjectName('SimpleCADPatternAlign')
        self.align.setChecked(True)
        self.form.addRow('', self.align)
        self.kind.currentIndexChanged.connect(self.show_fields)
        self.watch(self.kind, *self.counts, *self.spacing, self.count, self.angle, self.axis, self.center, self.align)
        self.show_fields()
        self.outlines = []
        for obj in objects:
            shape = obj.Shape
            self.outlines += box_lines(shape.BoundBox) if len(shape.Edges) > PREVIEW_EDGES else preview.edges(shape)
        self.finish_layout('The originals stay; each copy is a separate object with the same colours. '
                           'Counts include the original. One Undo step.')

    def show_fields(self, *_):
        kind = self.kind.currentData()
        for widget in self.grid_rows:
            widget.setVisible(kind == 'grid')
            self.form.labelForField(widget).setVisible(kind == 'grid')
        for widget, kinds in ((self.count, ('radial', 'path')), (self.angle, ('radial',)), (self.axis, ('radial',)),
                              (self.center, ('radial',)), (self.align, ('path',))):
            widget.setVisible(kind in kinds)
            label = self.form.labelForField(widget)
            if label is not None:
                label.setVisible(kind in kinds)

    def placements(self):
        kind = self.kind.currentData()
        axis = {'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}[self.axis.currentData()]
        center = (0, 0, 0) if self.center.currentData() == 'origin' else None
        return so.placements(kind, self.objects, path=self.path, count=self.count.value(),
                             counts=[c.value() for c in self.counts], spacing=[s.value() for s in self.spacing],
                             axis=axis, center=center, angle=self.angle.value(), align=self.align.isChecked())

    def lines(self):
        placements = self.placements()
        if len(placements) * len(self.objects) > patterns.LIMIT:
            raise ValueError('A pattern can make at most %d copies.' % patterns.LIMIT)
        lines = [[p.multVec(point) for point in line] for p in placements for line in self.outlines]
        return lines, '%s will be made.' % plural(len(placements) * len(self.objects), 'copy', 'copies')


# --- Entry point ---------------------------------------------------------------------------

def run(controller, tool):
    chosen = selection()
    if tool == 'HealFaces':
        obj, names = one_object(chosen, 'the faces to remove')
        report = so.heal_faces(obj, names)
        Gui.Selection.clearSelection()
        controller.message('%s removed and healed%s · %d → %d faces · Undo with ⌘Z' % (
            plural(report['removed'], 'face'),
            ' · %d could not heal and stayed' % report['failed'] if report['failed'] else '',
            report['faces_before'], report['faces_after']))
    elif tool == 'RemoveRounds':
        obj, names = one_object(chosen, 'a solid, or some of its faces,')
        dialog = RoundsDialog(obj, [n for n in names if n.startswith('Face')])
        if not dialog.exec():
            controller.message('Remove rounds canceled')
            return
        radius, kind = dialog.values()
        report = so.remove_rounds(obj, radius, kind, dialog.names)
        Gui.Selection.clearSelection()
        controller.message('%s removed%s · Undo with ⌘Z' % (
            plural(report['removed'], 'round'),
            ' · %d could not be removed and stayed' % report['failed'] if report['failed'] else ''))
    elif tool == 'Imprint':
        obj, names = one_object(chosen, 'the faces to draw on')
        faces = [n for n in names if n.startswith('Face')]
        dialog = ImprintDialog(obj, faces, picked_point(obj, faces))
        if not dialog.exec():
            controller.message('Draw on surface canceled')
            return
        values = dialog.values()
        report = so.imprint(obj, dialog.names, **values)
        Gui.Selection.clearSelection()
        if report['regions']:
            Gui.Selection.addSelection(obj, report['regions'])
        controller.message({'imprint': 'Drawn on the surface · %s selected for colour, Push/Pull or Delete'
                            % plural(len(report['regions']), 'region'),
                            'emboss': 'Drawing raised by %.3g mm' % values['depth'],
                            'deboss': 'Drawing recessed by %.3g mm' % values['depth']}[values['mode']]
                           + ' · Undo with ⌘Z')
    elif tool == 'OffsetFace':
        obj, names = one_object(chosen, 'the faces to offset')
        dialog = OffsetDialog(obj, [n for n in names if n.startswith('Face')])
        if not dialog.exec():
            controller.message('Offset face canceled')
            return
        distance = dialog.distance.value()
        report = so.offset_faces(obj, dialog.names, distance)
        Gui.Selection.clearSelection()
        controller.message('%s moved %.3g mm %s · Undo with ⌘Z' % (
            plural(report['faces'], 'face'), abs(distance), 'outward' if distance > 0 else 'inward'))
    elif tool == 'Shell':
        obj, names = one_object(chosen, 'a part, or the faces to leave open,')
        dialog = ShellDialog(obj, [n for n in names if n.startswith('Face')])
        if not dialog.exec():
            controller.message('%s canceled' % dialog.title)
            return
        thickness = dialog.thickness.value()
        if dialog.surface:
            so.thicken(obj, thickness, dialog.side.currentData())
            message = 'Thickened into a %.3g mm solid wall' % thickness
        else:
            report = so.shell(obj, dialog.names, thickness)
            message = 'Hollowed with %.3g mm walls%s' % (
                thickness, ' · %s open' % plural(report['open_faces'], 'face') if report['open_faces'] else '')
        Gui.Selection.clearSelection()
        controller.message(message + ' · Undo with ⌘Z')
    elif tool == 'Draft':
        obj, names = one_object(chosen, 'the faces to draft')
        dialog = DraftDialog(obj, [n for n in names if n.startswith('Face')])
        if not dialog.exec():
            controller.message('Draft canceled')
            return
        values = dialog.values()
        report = so.draft(obj, dialog.names, **values)
        Gui.Selection.clearSelection()
        controller.message('%s drafted by %.3g° · Undo with ⌘Z' % (plural(report['faces'], 'face'), values['angle']))
    elif tool == 'FillHole':
        obj, names = one_object(chosen, 'an open surface, or the rim edges of its openings,')
        dialog = FillDialog(obj, [n for n in names if n.startswith('Edge')])
        if not dialog.exec():
            controller.message('Fill hole canceled')
            return
        report = so.fill_holes(obj, dialog.edges, dialog.smooth.isChecked())
        Gui.Selection.clearSelection()
        controller.message('%s filled%s%s · Undo with ⌘Z' % (
            plural(report['filled'], 'opening'),
            ', %d blended smoothly' % report['tangent'] if report['tangent'] else '',
            ' · now a closed solid' if report['closed'] else ''))
    elif tool == 'Unwrap':
        obj, names = one_object(chosen, 'one face')
        faces = [n for n in names if n.startswith('Face')]
        if len(faces) != 1:
            raise ValueError('Select one face to unwrap.')
        flat, report = so.unwrap(obj, faces[0])
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(flat)
        change = report['area_change'] * 100
        controller.message('Unwrapped to %.2f × %.2f mm beside the part%s · Undo with ⌘Z' % (
            report['width'], report['height'],
            ' · area %+.2f%% (a doubly curved face stretches when flattened)' % change if abs(change) >= .05 else ''))
    elif tool == 'Pattern':
        objects = [obj for obj, names in chosen if not names]
        paths = [(obj, names) for obj, names in chosen if names]
        if not objects:
            raise ValueError('Select the whole objects to repeat; add an edge on another object to follow a path.')
        path = so.path_shape(paths) if paths else None
        dialog = PatternDialog(objects, path)
        if not dialog.exec():
            controller.message('Pattern canceled')
            return
        copies = so.pattern(objects, dialog.placements())
        Gui.Selection.clearSelection()
        for copy in copies:
            Gui.Selection.addSelection(copy)
        controller.message('%s made · Undo with ⌘Z' % plural(len(copies), 'copy', 'copies'))
    else:
        raise ValueError('Unknown surface tool.')
    controller.faces.refresh()
