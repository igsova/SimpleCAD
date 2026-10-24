# Inspect

The Inspect tools help you select, measure and look at a part without changing it. For a guided tour, see the [user guide](../user-guide.md#selecting-and-inspecting).

## Smart select { #smartselect }

Smart select grows one face or edge into what you most likely meant: a whole hole, an edge loop, a flat region or a smooth curved surface. It is most useful on converted meshes, where a hole wall or a flat side is made of many small faces.

Inspect toolbar · MCP `simplecad_expand_selection`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/smartselect.mp4" poster="clips/smartselect.jpg" controls muted loop playsinline preload="none" aria-label="On a faceted part, double-clicks select a whole hole wall, the edge loop around a raised pad and a flat region of triangles; the dropdown then shows the four modes."></video>
<figcaption>On a faceted part, double-clicks select a whole hole wall, the edge loop around a raised pad and a flat region of triangles; the dropdown then shows the four modes.</figcaption>
</figure>

**Steps**

1. In Select mode, double-click a face or an edge. A hole's wall or rim selects the whole hole, another edge its edge loop, a flat face its flat region, and a curved face its smooth surface.
2. Hold Shift while you double-click to add the result to the selection.
3. To choose the kind yourself, select faces or edges, then pick a mode from the Smart select dropdown in the Inspect toolbar.

**Options**

| Option | What it does |
| --- | --- |
| Select hole | Grows a face or rim edge into its whole hole or cylinder wall, analytic or faceted. Not available for a free-form curved face. |
| Select edge loop | Grows an edge into the loop it lies on, such as a hole's rim, taking the loop of the face turned toward you. |
| Select flat region | Grows a face into the connected faces on its plane, within 0.5°, such as a flat area of mesh triangles. |
| Select smooth surface | Grows a face across creases gentler than 30°, such as a faceted fillet or curved wall. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Double-click</kbd> | Grow the face or edge under the pointer, choosing the mode automatically. |
| <kbd>Shift</kbd> + <kbd>double-click</kbd> | Add the grown result to the selection. |

**Notes**

- The dropdown modes, also in the face list's right-click menu, grow every selected face or edge at once.
- Hidden faces are left out. Smart select works on CAD faces; raw STL triangles need Make mesh editable first.
- A selected hole can go straight to Delete to close it, or to Measure.
- Only the selection changes; the model does not.

**See also:** [Select](draw.md#select) · [Measure](#measure) · [Delete & heal faces](surface.md#healfaces) · [Make mesh editable](mesh.md#convertmesh)

## Measure { #measure }

Measure reads sizes from the model without changing it: a hole's diameter, an edge's length, a face's area, the radius of a curve, and distances and angles between two picks.

![](../../Resources/icons/measure.svg){ .tool-icon } Inspect toolbar · Shortcut <kbd>Z</kbd> · MCP `simplecad_measure`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/measure.mp4" poster="clips/measure.jpg" controls muted loop playsinline preload="none" aria-label="Two parallel faces measure 16 mm apart at 0°, then a third click on a round reads it as a cylinder of diameter 12 mm, radius 6 mm."></video>
<figcaption>Two parallel faces measure 16 mm apart at 0°, then a third click on a round reads it as a cylinder of diameter 12 mm, radius 6 mm.</figcaption>
</figure>

**Steps**

1. Click Measure or press Z. Nothing needs to be selected.
2. Click a vertex, edge, face or hole. A panel lists the measurements, and an orange dimension appears in the view.
3. Click a second element to measure between the two.
4. Click again to start a new measurement, or press Esc to finish.

**Options**

| Option | What it does |
| --- | --- |
| Place | Move the pointer to offset the dimension off the part, with extension lines back to the measured points, and click to leave it there. |
| Clear placed | Remove the placed dimensions. |
| Copy | Copy the results to the clipboard. |
| Close | End Measure. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Z</kbd> | Start Measure. |
| <kbd>Esc</kbd> | End Measure. A right-click does the same. |

**Notes**

- One pick: a hole's wall or rim edge gives its diameter, radius, center, axis and depth; a round reads as a cylinder the same way. Faceted holes of converted parts are fitted, and the result says (faceted). A vertex gives its position, an edge its length and XYZ delta, a flat face its area and normal.
- A curved face that is not a cylinder reports how it bends at the click: whether it bulges outward, is hollow or is saddle-shaped, and its tightest and gentlest radius.
- Two picks: two holes give their center spacing and the wall between them; two flat faces their distance when parallel and the angle between them; two points their distance and ΔX ΔY ΔZ. Every pair also shows the minimum distance.
- A third click starts a new measurement. Placed dimensions stay in view while you edit and keep their arrow size as you zoom; they do not change the model.

**See also:** [Measure Tape](#tape) · [Smart select](#smartselect) · [Curvature map](#curvature)

## Measure Tape { #tape }

Measure Tape measures out from an edge or a point and leaves a dashed guide there, as SketchUp's Tape Measure does. Lines and shapes then snap to the guide, so you can start or end them at an exact distance from an edge.

![](../../Resources/icons/tape.svg){ .tool-icon } Inspect toolbar · Shortcut <kbd>T</kbd>
{ .tool-facts }

![Two dashed guides placed 15 mm and 25 mm in from the edges of a plate, and a third being measured 20 mm in from its right edge](../images/measure-tape.png)

**Steps**

1. Click Measure Tape or press T. Nothing needs to be selected.
2. Click an edge, away from its ends and middle, or a guide line. Move the pointer to the side the guide should go: the tape measures straight out from the edge, and a dashed line parallel to it follows the pointer.
3. Click to place the guide, or type the distance and press Enter.
4. Measure again from another edge, or press Esc to finish.

To leave a guide point instead of a line, start on a corner, a midpoint, a face or a guide point. The tape then measures from that point to the pointer, and the guide point goes where you click or at the distance you type, toward the pointer. A dashed tail runs from the start to the guide point, as in SketchUp, and drawing snaps along it. Type 0 to leave a guide point on the start itself, without a tail.

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>T</kbd> | Start Measure Tape. |
| <kbd>Tab</kbd> or a digit | Type the distance in a box on the tape. |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Measure from a point along a world axis. |
| <kbd>Esc</kbd> | End Measure Tape. The guides stay. |

**Notes**

- Drawing tools snap to guides: along a guide line or a guide point's tail (**On guide**), to a guide point (**Guide point**), and where a guide crosses an edge or another guide (**Intersection**).
- Guides are construction, not geometry. They never change the model, and modeling tools, selection windows and exports pass them by. Fit All frames the model, not the guide lines.
- Each guide is one Undo step. The guides are kept in a **Guides** group on the Objects tab: hide the group to hide them all, or select it and press Delete to remove them all. Click a single guide and press Delete to remove just that one.
- Guides are saved with the model. FreeCAD without SimpleCAD opens the file but cannot show them.

**See also:** [Measure](#measure) · [Snapping](draw.md#snapping) · [Line](draw.md#line)

## Curvature map { #curvature }

Curvature map colours curved faces by how tightly they bend, from red for tight bends through yellow and green to blue for gentle ones. Use it to find small rounds, uneven fitted surfaces, or where a surface flattens out.

![](../../Resources/icons/curvature.svg){ .tool-icon } Inspect toolbar
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/curvature.mp4" poster="clips/curvature.jpg" controls muted loop playsinline preload="none" aria-label="On a soap-bar shaped part, the 1.5 mm top rounds show orange, the 10 mm corner rounds green and the gently curved top blue; a second click hides the map."></video>
<figcaption>On a soap-bar shaped part, the 1.5 mm top rounds show orange, the 10 mm corner rounds green and the gently curved top blue; a second click hides the map.</figcaption>
</figure>

**Steps**

1. Select the objects to map, or select nothing to map every visible object.
2. Click Curvature map. The status bar gives the radii shown as red and as blue.
3. Orbit the view to inspect the colours.
4. Click Curvature map again to hide it.

**Notes**

- The scale follows the size of the model: red is a radius of 1/200 of the model's diagonal or tighter, blue is half the diagonal or gentler, on a logarithmic scale in between. Flat faces keep their own colour.
- The map is a picture of the moment you turned it on. After editing, click twice: once to hide it and once to show it again.
- It is a temporary overlay; the model and its colours do not change. For the exact radius at a point, click the face with Measure.
- Objects with only flat faces have nothing to map, and the status bar says so.

**See also:** [Measure](#measure) · [Remove rounds](surface.md#removerounds)

## Isolate selection { #isolate }

Isolate selection hides every object except the selected ones, so you can work on one part of a crowded model. Click it again to show everything it hid.

![](../../Resources/icons/isolate.svg){ .tool-icon } Inspect toolbar
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/isolate.mp4" poster="clips/isolate.jpg" controls muted loop playsinline preload="none" aria-label="In a small assembly the shaft is isolated and orbited on its own, then Isolate again brings back the other parts."></video>
<figcaption>In a small assembly the shaft is isolated and orbited on its own, then Isolate again brings back the other parts.</figcaption>
</figure>

**Steps**

1. Select the objects to keep, or any of their faces or edges.
2. Click Isolate selection. Every other CAD object and mesh is hidden.
3. When you are done, click Isolate selection again, with or without a selection, to show the hidden objects.

**Notes**

- Only visibility changes; nothing in the model changes.
- Restoring shows only the objects Isolate hid. Objects you had hidden before stay hidden.

**See also:** [Select](draw.md#select) · [Smart select](#smartselect)
