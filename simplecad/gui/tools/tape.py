"""Measure Tape: measure from a point and leave a guide, as SketchUp's Tape Measure.

From an edge or a guide line the tape measures straight out from it and
leaves a guide line parallel to it; from any other point it measures to the
pointer and leaves a guide point. A typed distance places the guide exactly.
Guides are construction, not geometry: drawing snaps to them, and the model
itself is never changed.
"""
from ...core import geometry as geo
from ...document import guides
from ..guide_view import GuideNodes


class TapeInput:
    def __init__(self, controller):
        self.c = controller
        self.along = None  # unit direction of the edge or guide measured from; None from a point
        self.end = None  # where the guide goes
        self.nodes = GuideNodes(pickable=False)
        controller.view.getSceneGraph().addChild(self.nodes.root)

    def begin(self, snap):
        """The first click: from an edge or guide line, the guide goes parallel to it."""
        self.along = snap.direction if snap.label in ('On edge', 'On guide') else None
        self.c.message('Move out from the ' + ('edge' if snap.label == 'On edge' else 'guide')
                       + ' · Click to place a parallel guide · Tab for distance · Esc ends'
                       if self.along is not None else
                       'Click to measure and place a guide point · Tab for distance · X/Y/Z locks an axis · Esc ends')

    def offset(self, point):
        """From the start to the pointer; from an edge, only the part straight out from it."""
        delta = point - self.c.anchor
        return delta if self.along is None else delta - self.along * delta.dot(self.along)

    def preview(self, snap):
        c = self.c
        self.end = c.anchor + self.offset(c.point)
        distance = (self.end - c.anchor).Length
        # The tape itself, and the guide it would leave.
        self.nodes.set([[c.anchor, self.end]] if distance > geo.EPS else [],
                       [(self.end, self.along)] if self.along is not None else [],
                       [self.end] if self.along is None else [])
        text = '%.2f mm' % distance
        c.preview.update([], c.point, axis=snap.axis if snap else '',
                         lengths=[([c.anchor, self.end], text)] if distance > geo.EPS else [])
        c.controls.value.setPlaceholderText(text)
        if snap is not None:
            c.controls.label.setText(snap.label + ' · ' + text)

    def numeric(self, text):
        """A typed distance, along the pointer's direction or straight out from the edge."""
        c = self.c
        distance = geo.parse_length(text)
        direction = self.offset(c.point)
        if direction.Length < geo.EPS:
            if self.along is not None:
                raise ValueError('Move the pointer to the side the guide goes, then type its distance.')
            direction = c.axis if c.axis is not None else c.plane.u
        self.end = c.anchor + geo.unit(direction) * distance

    def commit(self):
        c = self.c
        if self.along is None and (self.end - c.anchor).Length < geo.EPS:
            raise ValueError('Choose a different point to measure to.')
        guides.add(c.doc, self.end, self.along)
        distance = (self.end - c.anchor).Length
        # Ready for the next measurement, which can snap to this guide.
        from ..snapping import Snapper
        c.snapper = Snapper(c.doc, c.view)
        c.line_undo_count = c.doc.UndoCount
        c.anchor = c.point = c.axis = None
        self.along = self.end = None
        self.nodes.set()
        c.preview.update()
        c.controls.value.clear()
        c.controls.value.setPlaceholderText('Distance')
        c.focus_view()
        c.message('Guide placed %.2f mm away · Click to measure again · Esc ends · Undo with ⌘Z' % distance)

    def close(self):
        try:
            self.c.view.getSceneGraph().removeChild(self.nodes.root)
        except (AttributeError, RuntimeError, ReferenceError):
            pass
