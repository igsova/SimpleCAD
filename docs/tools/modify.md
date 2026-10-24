# Modify

The Modify toolbar changes faces, edges and whole objects. For a guided tour, see the [user guide](../user-guide.md#modifying).

## Push/Pull { #pushpull }

Push/Pull moves a flat face along its normal. Use it to pull a drawn outline into a solid, raise a boss, cut a pocket, or push a profile onto the opposite face to make a through-hole.

![](../../Resources/icons/pushpull.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>P</kbd> · MCP `simplecad_push_pull`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/pushpull.mp4" poster="clips/pushpull.jpg" controls muted loop playsinline preload="none" aria-label="A rectangle is pulled 12 mm into a block, then a circle drawn on top is pushed onto the opposite face to make a through-hole."></video>
<figcaption>A rectangle is pulled 12 mm into a block, then a circle drawn on top is pushed onto the opposite face to make a through-hole.</figcaption>
</figure>

**Steps**

1. Click Push/Pull or press P with the 3D view focused. You can also select one flat face first.
2. Click a flat face. A small panel opens with the distance and direction.
3. Move the pointer along the face normal to preview the extrusion, or press and drag.
4. Click, or release the drag, to finish. For an exact value, type it in the panel's Distance field, or press Tab and type it in the box that opens beside the pointer, then press Enter.
5. To make a through-hole, push a profile toward the far side until the amber target reads Opposite face snapped, then click.

**Options**

| Option | What it does |
| --- | --- |
| Distance | The extrusion length. Accepts units such as 2 cm or 1 in; bare numbers are millimeters. A leading - pushes inward and a leading + pulls outward. |
| Direction | Outward (Extrude / Boss) or Inward (Pocket / Cut) on a solid; Along normal or Opposite normal on a surface. Flip swaps them. |
| +1 / +2 / +5 / +10 mm, Reset | Add a fixed step to the distance, or clear it. |
| Through to opposite face | Shown when the face has a parallel opposite face. Sets the exact depth for a through-hole. |
| Snap (status bar) | Turns on the opposite-face magnet and the Face level and Edge level snaps, which match the height of another parallel face or a level edge. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Tab</kbd> | Open a box beside the pointer to type a distance. |
| <kbd>Enter</kbd> | Apply the typed distance. |
| <kbd>Esc</kbd> | Cancel the preview without changing the model. |

**Notes**

- Push/Pull works on flat faces only. Use Offset face to move curved faces.
- On a solid, pulling outward adds material and pushing inward cuts it. On a 20 mm block, -10 mm makes a pocket, -20 mm a through-hole, and -30 mm a capped cylinder 10 mm past the far side that keeps the far face intact.
- A typed distance is used exactly; the snap magnet does not change it.
- Pulling a face of an open surface extrudes it into its own solid and leaves the other faces in a separate object. A closed shell becomes a solid first.
- The result must stay one valid, non-empty solid. Pushing a whole prism down to zero thickness is refused.
- Each completed Push/Pull is one Undo step. Existing face divisions survive the edit.
- A Push/Pull that ends within 0.005 mm of an existing flat level ends exactly on it.

**See also:** [Offset](#offset) · [Subdivide face](#subdivide) · [Offset face](surface.md#offsetface) · [Rectangle](draw.md#rectangle) · [Circle](draw.md#circle)

## Offset { #offset }

Offset draws a parallel copy of a flat face's outline, or of a single straight edge, arc or circle. An inward face offset creates a separate inner region that you can push, pull or delete.

![](../../Resources/icons/offset.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>E</kbd> · MCP `simplecad_offset`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/offset.mp4" poster="clips/offset.jpg" controls muted loop playsinline preload="none" aria-label="The top face of a block is offset 5 mm inward, and the new inner region is pushed down 10 mm to make a tray."></video>
<figcaption>The top face of a block is offset 5 mm inward, and the new inner region is pushed down 10 mm to make a tray.</figcaption>
</figure>

**Steps**

1. Click Offset or press E with the 3D view focused. You can also select one face or edge first.
2. Click a flat face, or click an edge away from its vertices.
3. Move the pointer inside or outside the face boundary, or to either side of a line, to preview the offset.
4. Click to finish, or press Tab, type a distance such as 2 mm and press Enter.

**Options**

| Option | What it does |
| --- | --- |
| Distance | An unsigned value keeps the side you chose with the pointer. On faces, arcs and circles, -2 mm forces inward and +2 mm forces outward. On straight lines, positive and negative choose left and right in the drawing plane. |
| Plane (status bar) | Auto uses the flat face beside a line, or a plane facing the view for a loose line. Choose XY, XZ or YZ before picking a line to set its plane explicitly. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Tab</kbd> | Open a box beside the pointer to type a distance. |
| <kbd>Enter</kbd> | Apply the typed distance. |
| <kbd>Esc</kbd> | Cancel the preview without changing the model. |

**Notes**

- On a face, the distance is measured from the nearest boundary, including hole boundaries. An inset grows holes and an outward offset shrinks them. Corners stay sharp.
- Before you move the pointer, a face offset goes inward and an edge offset goes to the positive side.
- An outward offset on a solid imprints the new outline on the coplanar faces it reaches. Any border beyond them becomes a separate Offset border surface, so the solid stays closed.
- An edge offset creates only a new edge: no end caps and no closing faces. Arcs keep their center, plane and sweep. Splines and curved faces are not supported.
- Offsets that collapse or cross the boundary are refused without changing the model. Each completed offset is one Undo step.

**See also:** [Push/Pull](#pushpull) · [Offset face](surface.md#offsetface) · [Subdivide face](#subdivide)

## Elongate / Make Elliptical { #elongate }

Elongate stretches a round hole, a hole rim or a flat face along a direction you choose, into an ellipse or a slot. Use it to turn a drilled hole into an adjustment slot.

![](../../Resources/icons/elongate.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>X</kbd> · MCP `simplecad_elongate`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/elongate.mp4" poster="clips/elongate.jpg" controls muted loop playsinline preload="none" aria-label="A round through-hole is stretched along X, switched to Slot, and cut through the plate as a slot."></video>
<figcaption>A round through-hole is stretched along X, switched to Slot, and cut through the plate as a slot.</figcaption>
</figure>

**Steps**

1. Click Elongate or press X with the 3D view focused. You can also select the face or rim first.
2. Click a cylindrical hole wall, a circular rim, or a flat face. A panel opens.
3. Move the pointer away from the center in the direction to stretch. Near a multiple of 15°, the direction snaps to it.
4. In the panel, choose Ellipse or Slot, and turn on Cut hole through solid to cut the new shape through the part.
5. Click in the view or click Apply to keep the result.

**Options**

| Option | What it does |
| --- | --- |
| Distance | How far the outline grows beyond its radius. The new half-length is the radius plus this distance. |
| Direction | The stretch angle in the face plane, from 0° to 360°. Use the slider, the 0°, 45°, 90°, 180° and 270° buttons, or Flip (180°). |
| Mode | Ellipse (smooth) or Slot (stadium): two straight sides joined by half circles. The same choice is in the status bar. |
| Symmetrical (both sides) | On: the outline grows both ways from the center. Off: it grows only toward the direction and the opposite side stays where it was. |
| Cut hole through solid | Shown for a solid. Cuts the elongated outline through the part along the hole's axis instead of only drawing it on the face. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Tab</kbd> | Type a distance, or a distance and angle such as 8 @ 45, in a box beside the pointer. |
| <kbd>Enter</kbd> | Apply the typed value. |
| <kbd>Esc</kbd> | Cancel the preview without changing the model. |

**Notes**

- Without Cut hole through solid, the new outline is drawn on the flat face around the rim. It becomes a selectable region that you can Push/Pull. If it cannot divide the face, it is added as a separate Elongated object.
- A flat face that is not a circle is stretched along the direction. Straight edges are not supported.
- Shapes with links or expressions need a Part simple copy first.
- Each Apply is one Undo step.

**See also:** [Offset](#offset) · [Push/Pull](#pushpull) · [Fit Circle / Cylinder](#analytic)

## Fit Circle / Cylinder { #analytic }

Fit Circle / Cylinder replaces faceted circular geometry with true circles and cylinders. Use it on parts converted from STL, where a round hole is made of many flat facets.

![](../../Resources/icons/analytic.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>Y</kbd>
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/analytic.mp4" poster="clips/analytic.jpg" controls muted loop playsinline preload="none" aria-label="A hole made of 48 flat facets is selected with a double-click and replaced by a single true cylinder."></video>
<figcaption>A hole made of 48 flat facets is selected with a double-click and replaced by a single true cylinder.</figcaption>
</figure>

**Steps**

1. Select the faceted geometry: the facets of a hole wall, both circular rims, or one rim. Double-click a wall facet to select the whole hole.
2. Click Fit Circle / Cylinder or press Y with the 3D view focused.
3. Check the fitted radius and length, and choose what to create.
4. Click Apply.

**Options**

| Option | What it does |
| --- | --- |
| Replace the hole in this shape | Rebuilds a hole inside its solid with one cylindrical wall and two circular rims. This is the default when a complete hole is selected. |
| Replace circular edge in this shape | Replaces a faceted circular loop on a flat face with one true circle edge. |
| Analytic circle edge (new object) | Adds a separate circle edge object at the fitted position. |
| Analytic cylinder solid | Adds a separate cylinder solid with the fitted radius and length. |
| Replace the source when the whole object is selected | When the whole object is a faceted cylinder, replace it instead of adding a new object. |

**Notes**

- A single rim is paired with the opposite rim automatically, so one rim is enough to rebuild a through-hole. Blind holes keep their depth.
- The fit is conservative: points must lie on one circle or cylinder. Partial or ambiguous selections are refused with a message and nothing changes.
- A raw STL mesh must first be converted with Make mesh editable.
- Locked faces block the in-place replacement. Undo restores the facets in one step.

**See also:** [Make mesh editable](mesh.md#convertmesh) · [Elongate / Make Elliptical](#elongate) · [Measure](inspect.md#measure)

## Round edges { #round }

Round edges replaces sharp edges with smooth rounds (fillets) of a radius you set, with a shaded preview before anything changes.

![](../../Resources/icons/round.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>F</kbd> · MCP `simplecad_round_edges`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/round.mp4" poster="clips/round.jpg" controls muted loop playsinline preload="none" aria-label="The top face of a block is selected and its four edges are rounded, with the radius stepped from 2 to 5 mm in the preview."></video>
<figcaption>The top face of a block is selected and its four edges are rounded, with the radius stepped from 2 to 5 mm in the preview.</figcaption>
</figure>

**Steps**

1. Select one or more edges. Selecting a face rounds its boundary edges; selecting the whole solid in the Model tree rounds all its sharp edges.
2. Click Round edges or press F with the 3D view focused.
3. Set the radius with the slider or type a size such as 2 mm. The preview follows.
4. Click Apply, or press Enter after typing the radius.

**Options**

| Option | What it does |
| --- | --- |
| Radius | The round's radius. Accepts units such as 2 mm or 0.2 cm. |
| Show original (radius 0) | Shows the shape as it was when you opened the tool. Applying zero makes no edit. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Enter</kbd> | Apply the typed radius. |
| <kbd>Esc</kbd> | Cancel and restore the original shape and selection. |

**Notes**

- Works on closed single solids, including rounded box corners and circular rims. Several selected solids are rounded together in one Undo step.
- A radius that does not fit disables Apply and shows the original shape. Reduce the radius or select fewer edges.
- Coplanar drawn dividers, smooth tangent boundaries and cylinder seams are skipped. Open surfaces and flat 2D corners are not supported.
- The radius is not stored. To change it, Undo and round again.

**See also:** [Remove rounds](surface.md#removerounds) · [Push/Pull](#pushpull)

## Subdivide face { #subdivide }

Subdivide face divides one flat face into triangles, a center fan, or a grid of evenly spaced cells. Each piece is a real face that you can push, pull, delete or divide again.

![](../../Resources/icons/subdivide.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>D</kbd> · MCP `simplecad_subdivide`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/subdivide.mp4" poster="clips/subdivide.jpg" controls muted loop playsinline preload="none" aria-label="The top face of a block is divided into a 3 × 4 grid, and one cell is pulled up 8 mm."></video>
<figcaption>The top face of a block is divided into a 3 × 4 grid, and one cell is pulled up 8 mm.</figcaption>
</figure>

**Steps**

1. Select one flat face.
2. Click Subdivide face or press D with the 3D view focused. The tool picks a pattern to suit the outline.
3. Change the pattern and counts in the panel. The preview reports the actual number of faces.
4. Click Apply.

**Options**

| Option | What it does |
| --- | --- |
| Pattern | Triangles (for triangular faces), Center fan (for convex polygons and circular disks), Evenly spaced grid, or Equal-area grid. |
| Divisions per side / Sectors | For Triangles and Center fan: how many times each side or triangle is divided. On a disk, Sectors sets equal-angle wedges. |
| Set by | For grids: a total count (9 makes 3 × 3, 12 makes 3 × 4), Rows and columns, Rows only, or Columns only. |
| Grid angle / Start angle | Turns the grid or fan. Zero follows the longest straight outer edge. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Esc</kbd> | Cancel and keep the original face. |

**Notes**

- Up to 100 resulting faces per operation. A layout that makes only one piece makes no edit.
- Triangles and Center fan need a triangle, a convex polygon or a circular disk without holes. Concave faces and faces with holes use the grid patterns.
- Curved faces, several selected faces, and compound or mixed solids are not supported. Linked or parametric objects need a Part simple copy first.
- A solid keeps its volume. Undo removes the whole subdivision in one step.

**See also:** [Push/Pull](#pushpull) · [Offset](#offset) · [Delete](#delete)

## Slice / Separate { #slice }

Slice / Separate cuts whole objects with a plane and can move the pieces apart. For 3D printing, it can also add matching studs and sockets so the halves plug back together.

![](../../Resources/icons/slice.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>U</kbd> · MCP `simplecad_slice`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/slice.mp4" poster="clips/slice.jpg" controls muted loop playsinline preload="none" aria-label="A rounded block is sliced across its long axis, the halves are spread apart, and two printable studs with matching sockets are added."></video>
<figcaption>A rounded block is sliced across its long axis, the halves are spread apart, and two printable studs with matching sockets are added.</figcaption>
</figure>

**Steps**

1. Select one or more objects, in the Model tree or by clicking one of their faces.
2. Click Slice / Separate or press U with the 3D view focused.
3. Choose the cut direction and move Cut offset from center to place the blue plane, or click Pick face and click a flat face to cut on its plane.
4. Turn on Separate pieces and set Gap between sides to spread the pieces apart.
5. For a printable joint, turn on Add studs and sockets and set the pattern and sizes.
6. Click Apply, or press Enter in a length field.

**Options**

| Option | What it does |
| --- | --- |
| Cut across | Object main axis (across the long direction, also on rotated shapes), X (YZ plane), Y (XZ plane) or Z (XY plane). Selected face appears when you cut on a face that is not square to these axes. |
| Pick face | Click a flat face in the view to put the cut exactly on its plane. |
| Cut offset from center | Signed position of the plane from the middle of the selection, such as -5 mm. |
| Separate pieces / Gap between sides | Moves both sides away from the cut equally. A 10 mm gap moves each side 5 mm. With a zero gap, the pieces touch but are separate objects. |
| Add studs and sockets | Adds round studs to one half and matching blind sockets to the other: one stud, a row of two to six, or a 2 × 2 or 2 × 3 grid. Set Stud diameter, Stud length and Fit clearance per side (positive is looser, negative tighter). |
| Put studs on the other side | Swaps which half gets the studs. |
| Layout and wall | Stud spacing (Auto spreads them evenly), moves along or across the row, and the minimum surrounding wall (1.2 mm by default). |
| Make a fit test | Opens a separate document with three small stud and socket pairs: your clearance, 0.10 mm tighter and 0.10 mm looser. Print it before the full model. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Enter</kbd> | Apply from a length field. |
| <kbd>Esc</kbd> | Cancel and keep the original. |

**Notes**

- Closed solids get closed cut faces; open surfaces stay open. Concave solids can give more than two pieces.
- One plane spans all selected objects. Objects entirely on one side move with that side.
- Studs and sockets need one closed solid cut into exactly two pieces. Sockets that would break through the wall, or studs without enough support, are refused; move or shrink the pattern.
- The joint is a friction fit. Retention depends on your printer and material, so print a fit test first.
- Gap between sides only positions the pieces; it does not change the joint fit.
- A selected STL mesh opens Split mesh instead. Linked or parametric objects need a Part simple copy. Undo restores the original in one step.

**See also:** [Split mesh](mesh.md#meshsplit) · [Union](#union) · [Intersect Faces](#intersect)

## Intersect Faces { #intersect }

Intersect Faces splits crossing faces along the lines where they meet, so you can delete the pieces you do not want. Use it to make recesses, such as a spherical bowl in a block.

![](../../Resources/icons/intersect.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>I</kbd> · MCP `simplecad_intersect_faces`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/intersect.mp4" poster="clips/intersect.jpg" controls muted loop playsinline preload="none" aria-label="A sphere centered on a block&#x27;s top face is intersected with it; deleting the upper half and the disk leaves a spherical recess."></video>
<figcaption>A sphere centered on a block&#x27;s top face is intersected with it; deleting the upper half and the disk leaves a spherical recess.</figcaption>
</figure>

**Steps**

1. Select the crossing faces, such as a block's top face and then Ctrl-click a sphere, or select whole objects in the Model tree.
2. Click Intersect Faces or press I with the 3D view focused. The objects become one Intersection object.
3. Select the regions you do not want and press Delete. For a bowl, delete the upper half of the sphere, then the disk over the opening.

**Notes**

- Selecting faces limits which crossings are cut; selecting whole objects intersects all their faces.
- Every region is kept, including internal ones, until you delete it. When the deletions leave a closed shell, it becomes a solid again.
- Crossings that do not exist, point contacts, and coplanar overlaps make no edit. Use Union to merge overlapping solids.
- Locked faces and objects must be unlocked first. The intersection and each deletion are separate Undo steps; undoing the intersection restores the original objects and their colors.

**See also:** [Union](#union) · [Delete](#delete) · [Sphere](draw.md#sphere)

## Union { #union }

Union joins overlapping whole objects into one closed solid. Overlapping material counts once, internal faces disappear, and redundant dividing edges are removed.

![](../../Resources/icons/union.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>J</kbd> · MCP `simplecad_union`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/union.mp4" poster="clips/union.jpg" controls muted loop playsinline preload="none" aria-label="A plate and a cylinder that passes through it are selected and joined into one solid named Union."></video>
<figcaption>A plate and a cylinder that passes through it are selected and joined into one solid named Union.</figcaption>
</figure>

**Steps**

1. Move the pieces so their volumes overlap or they share a face.
2. Select the objects: Ctrl-click one face on each object in the view, or select their rows in the Model tree.
3. Click Union or press J with the 3D view focused.

**Notes**

- Union always acts on the whole selected objects, even when you select single faces or edges.
- The result is one object named Union with the first selected object's appearance.
- Pieces that do not overlap, or touch only at an edge or a point, are refused. Open surfaces, loose lines and points, and linked or parametric shapes must be resolved first.
- A failed Union leaves every piece unchanged. Undo restores all the original pieces in one step.

**See also:** [Intersect Faces](#intersect) · [Slice / Separate](#slice) · [Move](#move)

## Move Vertex { #vertexmove }

Move Vertex drags one corner of a part and reshapes the flat faces around it. Faces that stay flat remain whole; faces that bend become connected triangles.

![](../../Resources/icons/vertexmove.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>V</kbd> · MCP `simplecad_move_vertex`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/vertexmove.mp4" poster="clips/vertexmove.jpg" controls muted loop playsinline preload="none" aria-label="A top corner of a block is locked to the Z axis and raised 12 mm, so the top face becomes two sloped triangles."></video>
<figcaption>A top corner of a block is locked to the Z axis and raised 12 mm, so the top face becomes two sloped triangles.</figcaption>
</figure>

**Steps**

1. Click Move Vertex or press V with the 3D view focused. You can also select a vertex first.
2. Click a corner, or press on it and drag.
3. Move the pointer to the new position. Press X, Y or Z to lock movement to that axis.
4. Click again, or release the drag, to finish. For an exact move, press Tab, type dx, dy, dz such as 5, 0, -2, and press Enter.

**Options**

| Option | What it does |
| --- | --- |
| Plane (status bar) | Auto moves the vertex in a plane facing the view. XY, XZ or YZ start the movement on that plane. |
| Snap (status bar) | Snaps the destination to endpoints, midpoints, centers and axes. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Lock movement to that world axis; press again to unlock. |
| <kbd>Tab</kbd> | Type a displacement: dx, dy, dz, or one signed distance along a locked axis. |
| <kbd>Esc</kbd> | Cancel the preview without changing the model. |

**Notes**

- The faces next to the vertex must be flat, and the edges meeting at it straight. A circle or other curve drawn elsewhere on one of those faces is kept exactly: moving the vertex within that face keeps it one face, and tilting it folds off only the corner, along straight lines clear of the curves. When no such fold fits, the tilt is refused; move the vertex within the face instead.
- Collapsed, folded or self-intersecting results are refused and the part is unchanged.
- Locked adjoining faces block the move. Colors follow the reshaped regions.
- Other objects stay independent, even where they touch. One Undo restores the geometry and colors.

**See also:** [Push/Pull](#pushpull) · [Bend / Soft Deform](#deform) · [Move](#move)

## Move { #move }

Move slides whole objects from a base point to a destination. Both points snap to corners, edge midpoints, face centers and hole or circle centers, so you can set one part exactly onto another.

![](../../Resources/icons/move.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>M</kbd>
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/move.mp4" poster="clips/move.jpg" controls muted loop playsinline preload="none" aria-label="A block is moved corner to corner onto a plate, then moved exactly 20 mm along Y with the axis locked and a typed distance."></video>
<figcaption>A block is moved corner to corner onto a plate, then moved exactly 20 mm along Y with the axis locked and a typed distance.</figcaption>
</figure>

**Steps**

1. Select the objects to move, or start Move with nothing selected and click the object you want.
2. Click Move or press M with the 3D view focused.
3. Click a base point on the objects. A snap marker shows which point is caught.
4. Move the pointer. An outline of the objects follows it.
5. Click the destination, or drag from the base point and release there.
6. For an exact distance, press X, Y or Z to lock an axis, then press Tab, type the distance and press Enter.

**Options**

| Option | What it does |
| --- | --- |
| Snap (status bar) | Turns automatic snapping on or off for both points. Move can snap to other objects anywhere in 3D, not only on a drawing plane. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Lock or unlock movement along that world axis. |
| <kbd>Tab</kbd> | Open a box beside the pointer to type a distance. |
| <kbd>Enter</kbd> | Move by the typed distance along the locked axis, or along the current pointer direction. |
| <kbd>Esc</kbd> | Cancel without moving anything. |

**Notes**

- Move always acts on whole objects, even when you selected a face or an edge.
- A typed distance follows the locked axis, or the direction from the base point to the pointer. Move the pointer or lock an axis before you type. Units such as 2 cm or 1 in are accepted.
- Locked objects are refused; unlock them first. Copy still works on locked objects.
- Moving a rectangle or other profile drawn on a solid detaches it from that solid.
- Each move is one Undo step.

**See also:** [Copy](#copy) · [Rotate](#rotate) · [Move Vertex](#vertexmove) · [Exact values](../user-guide.md#first-five-minutes)

## Rotate { #rotate }

Rotate turns whole objects around a world axis or one of the object's own axes. A panel previews the angle before anything changes.

![](../../Resources/icons/rotate.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>T</kbd> · MCP `simplecad_rotate`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/rotate.mp4" poster="clips/rotate.jpg" controls muted loop playsinline preload="none" aria-label="An L bracket is turned around world Z with the angle slider, set to the +90 preset and applied."></video>
<figcaption>An L bracket is turned around world Z with the angle slider, set to the +90 preset and applied.</figcaption>
</figure>

**Steps**

1. Select one or more objects.
2. Click Rotate or press T with the 3D view focused. A colored arrow and ring show the axis.
3. Choose the axis and the center to rotate around.
4. Drag the angle slider, click a preset, or type an exact angle such as 37.5 or -90.
5. Click Apply or press Enter to keep the rotation.

**Options**

| Option | What it does |
| --- | --- |
| Axis | X, Y or Z world for a fixed direction; Object main axis for the shape's long direction; Object X, Y or Z local for the object's own placement axes. |
| Rotate around | Selection center (together), Each object's center, or World origin. Choosing an object axis switches to Each object's center; you can change it back. |
| Angle | Degrees by default; units such as rad also work. Positive angles turn counterclockwise looking from the arrow tip toward the center. Typed angles may go beyond the slider's -180 to +180 range. |
| -90, -45, Reset, +45, +90 | Set the angle to a preset, or back to the starting orientation. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Enter</kbd> | Apply the angle in the Angle field. |
| <kbd>Esc</kbd> | Cancel and restore the original orientation. |

**Notes**

- The preview does not change the model. Cancel, Esc or closing the panel leaves the objects as they were.
- Apply changes only the objects' placement, so dimensions, curved surfaces, face divisions and colors are kept. Several objects rotate in one Undo step.
- A whole turn such as 360 or 720 degrees makes no edit.
- If you select only edges (lines or arcs), Rotate turns those edges instead of the object. The panel then offers the face or plane normal as the axis, the curve or hole center, start point or end point as the center, and a Keep original (copy) option.
- Locked objects, linked or parametric objects and objects driven by expressions are refused. Make a Part simple copy first.

**See also:** [Move](#move) · [Mirror](#mirror) · [Scale / Stretch](#scale)

## Bend / Soft Deform { #deform }

Bend / Soft Deform reshapes one object freely. Soft Move pushes a region with a smooth falloff, and Bend curves the object along an axis. The result is a faceted approximation made of small flat faces.

![](../../Resources/icons/deform.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>N</kbd> · MCP `simplecad_deform`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/deform.mp4" poster="clips/deform.jpg" controls muted loop playsinline preload="none" aria-label="A bar previews a Soft Move bulge, then switches to Bend, is bent 75 degrees along its main axis and applied."></video>
<figcaption>A bar previews a Soft Move bulge, then switches to Bend, is bent 75 degrees along its main axis and applied.</figcaption>
</figure>

**Steps**

1. Select a face, edge or vertex on one object, or the whole object.
2. Click Bend / Soft Deform or press N. The panel opens in Soft Move.
3. For Soft Move, set the influence center, the radius and the X, Y, Z displacement.
4. For Bend, choose Bend in Operation, pick the axis and drag the angle slider.
5. Watch the colored preview: blue barely moves and orange moves most.
6. Click Apply. The deformed surface is built and checked before it replaces the object.

**Options**

| Option | What it does |
| --- | --- |
| Operation | Soft Move or Bend. |
| Influence center | Soft Move only. The point that moves most. A point you clicked on the object seeds it; otherwise the selection's center is used. |
| Influence radius | Soft Move only. The movement fades smoothly to zero at this distance from the center. |
| Displacement X / Y / Z | Soft Move only. How far the center moves, in mm. |
| Bend along | Main axis, world X, Y or Z, or the object's local X, Y or Z. |
| Bend origin and Bend length | Where the bend starts and how long it is. By default it starts at the low end and spans the object. Geometry before the origin stays fixed; geometry past the length follows the final direction. |
| Bend direction | Turns the bend plane around the chosen axis. |
| Bend angle | The signed bend, up to plus or minus 170 degrees, also set by the Angle slider. |
| Surface detail | 3 to 16, default 6. Higher detail gives smaller faces and takes longer to apply. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Esc</kbd> | Cancel and remove the preview. |

**Notes**

- The whole surface is rebuilt as small flat faces, including curved areas outside the influence region. Face numbers change, so reselect faces after Apply. Results are limited to 4000 faces.
- Folds, self-intersections, collapsed faces and bends that crush the inside too much are refused, and the object stays unchanged.
- Zero displacement or zero angle keeps the exact original and adds no Undo step.
- Supported: one closed solid without internal cavities, or an open surface. Locked objects and locked faces are refused.
- Face colors, opacity and hidden faces follow the result. One Undo step restores the original analytic surfaces.
- The operation approximates the surface and does not preserve volume. Use enough Surface detail for the size you print.

**See also:** [Scale / Stretch](#scale) · [Move Vertex](#vertexmove) · [Rotate](#rotate)

## Scale / Stretch { #scale }

Scale / Stretch resizes whole objects by factors. Keep X, Y and Z linked for a uniform scale, or unlink them to stretch one direction.

![](../../Resources/icons/scale.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>K</kbd> · MCP `simplecad_scale`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/scale.mp4" poster="clips/scale.jpg" controls muted loop playsinline preload="none" aria-label="A block with a hole is previewed at a uniform 1.5, then stretched along X only, so the round hole becomes an oval."></video>
<figcaption>A block with a hole is previewed at a uniform 1.5, then stretched along X only, so the round hole becomes an oval.</figcaption>
</figure>

**Steps**

1. Select one or more objects, or any face on them.
2. Click Scale / Stretch or press K. The factors start at 1.
3. Change the X factor; with Uniform scale checked, Y and Z follow.
4. To stretch, uncheck Uniform scale and set each factor separately.
5. Choose the axes and the center, check the preview, and click Apply.

**Options**

| Option | What it does |
| --- | --- |
| Uniform scale | Links the X, Y and Z factors so the shape keeps its proportions. |
| X, Y and Z factor | 1 keeps the size, 2 doubles it, 0.5 halves it. Factors must be positive; use Mirror to flip. |
| Axes | World X / Y / Z, or each object's local placement axes. |
| Scale around | Selection center (together), Each object's center, or World origin. Centers use the exact bounding box. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Esc</kbd> | Cancel without changing the objects. |

**Notes**

- Flat faces and straight edges stay editable with Push/Pull and the drawing tools.
- A non-uniform stretch turns curved surfaces into spline surfaces: a round hole becomes an oval and a sphere becomes an ellipsoid. A uniform scale keeps circles and spheres exact.
- Closed solids stay closed, including internal cavities. Colors, hidden faces and object identity are kept.
- Locked objects and faces are refused; linked or parametric features need a Part simple copy first.
- All selected objects change in one Undo step.

**See also:** [Bend / Soft Deform](#deform) · [Mirror](#mirror) · [Rotate](#rotate)

## Loft { #loft }

Loft connects two or more profiles, in order, into a new solid or surface. Use it for shapes that change cross-section along their length, such as a vase or a duct transition.

![](../../Resources/icons/loft.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>Q</kbd> · MCP `simplecad_loft`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/loft.mp4" poster="clips/loft.jpg" controls muted loop playsinline preload="none" aria-label="A circle, a square and a smaller circle are selected bottom to top and lofted, with the ruled option shown before Apply."></video>
<figcaption>A circle, a square and a smaller circle are selected bottom to top and lofted, with the ruled option shown before Apply.</figcaption>
</figure>

**Steps**

1. Select two or more profiles in the order to connect them: circle, rectangle or polygon faces, flat faces, or connected outlines. Hold Ctrl or Cmd to add to the selection.
2. Click Loft or press Q. The panel lists the profiles and the preview appears.
3. Use Move up and Move down to fix the order if needed.
4. Choose smooth or straight (ruled) transitions, and a solid or a surface.
5. Click Apply.

**Options**

| Option | What it does |
| --- | --- |
| Profiles in order | The order the loft passes through. Select a row and use Move up or Move down. |
| Create a closed solid | On by default. Needs closed flat outlines without holes. Turn it off for a surface, also between open profiles. |
| Straight transitions between profiles (ruled) | Straight sides between neighboring profiles instead of a smooth blend through all of them. |
| Hide source outline objects after Apply | Hides whole profile objects after Apply. A face or edge picked on a larger object never hides that object. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Esc</kbd> | Cancel; nothing is created. |

**Notes**

- Up to 32 profiles. Profiles must be different from each other.
- Loft creates a new, independent object and keeps the profiles. Editing a profile later does not update the loft.
- One Undo step removes the loft and shows the profiles again.

**See also:** [Sweep](#sweep) · [Push/Pull](#pushpull)

## Sweep { #sweep }

Sweep carries a profile along a path to make a new solid or surface, such as a pipe, a rail or a handle.

![](../../Resources/icons/sweep.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>W</kbd> · MCP `simplecad_sweep`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/sweep.mp4" poster="clips/sweep.jpg" controls muted loop playsinline preload="none" aria-label="A square profile is swept along a path with two sharp corners: Transformed fails, Right and Rounded corners work, and the rounded version is applied."></video>
<figcaption>A square profile is swept along a path with two sharp corners: Transformed fails, Right and Rounded corners work, and the rounded version is applied.</figcaption>
</figure>

**Steps**

1. Select the profile first: a flat face or a wire.
2. Add the path: a line, arc or wire object, or connected edges of one object.
3. Click Sweep or press W. The preview appears.
4. If the path has sharp corners, choose Right corners or Rounded corners.
5. Click Apply.

**Options**

| Option | What it does |
| --- | --- |
| Profile first, path second | Lists the two selections. Move up and Move down swap them if you picked them the other way round. |
| Create a closed solid | On by default for closed profiles. Turn it off for a surface. |
| Align profile center to start of path | On by default: the profile's center goes to the path start, square to the path. Turn it off when the profile is already in place; this also allows sweeping an open profile into a surface. |
| Follow path curvature (Frenet) | Changes how the section turns as it follows a curved path. |
| Path corners | Transformed, Right corners or Rounded corners: how the section turns at the joints between path segments. |
| Hide source outline objects after Apply | Hides the whole profile and path objects after Apply. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Esc</kbd> | Cancel; nothing is created. |

**Notes**

- On a path with sharp corners, Transformed can fail with an invalid-geometry message; Right corners or Rounded corners usually work.
- Disconnected or branching paths, and results that intersect themselves, are refused. A profile too large for a tight bend may need to be smaller, or the path gentler.
- Sweep creates a new, independent object and keeps the profile and path. One Undo step removes it and shows the sources again.

**See also:** [Loft](#loft) · [Pattern](#pattern)

## Copy { #copy }

Copy places an independent copy of the selected objects, using the same base point and destination interaction as Move.

![](../../Resources/icons/copy.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>C</kbd>
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/copy.mp4" poster="clips/copy.jpg" controls muted loop playsinline preload="none" aria-label="A peg is copied 30 mm along a locked X axis, then the copy is copied again to make a row of three."></video>
<figcaption>A peg is copied 30 mm along a locked X axis, then the copy is copied again to make a row of three.</figcaption>
</figure>

**Steps**

1. Select the objects to copy, or start Copy and click an object.
2. Click Copy or press C.
3. Click a base point. Corners, midpoints and circle centers snap.
4. Click the destination, or lock an axis with X, Y or Z, press Tab, type the distance and press Enter.
5. The copy stays selected, so you can copy it again the same way to make a row.

**Options**

| Option | What it does |
| --- | --- |
| Snap (status bar) | Turns automatic snapping on or off for both points. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Lock or unlock the copy direction to that world axis. |
| <kbd>Tab</kbd> | Open a box beside the pointer to type a distance. |
| <kbd>Enter</kbd> | Place the copy at the typed distance. |
| <kbd>Esc</kbd> | Cancel without copying. |

**Notes**

- Each copy is a separate object with its own geometry and the same face colors. Editing one does not change the other.
- Copy works on whole objects, even when a face or edge is selected, and also on locked objects.
- For many copies at once, use Pattern.
- Each copy is one Undo step.
- To copy with the keyboard, see [Copy, cut and paste](#clipboard).

**See also:** [Copy, cut and paste](#clipboard) · [Move](#move) · [Pattern](#pattern) · [Mirror](#mirror)

## Copy, cut and paste { #clipboard }

⌘C, ⌘X and ⌘V (Ctrl+C, Ctrl+X and Ctrl+V on Windows and Linux) copy, cut and paste whole objects. A paste lands where the original was and starts Move, so you can place it.

3D view and Model tab · Shortcut <kbd>⌘C</kbd> / <kbd>⌘X</kbd> / <kbd>⌘V</kbd>
{ .tool-facts }

**Steps**

1. Select one or more objects.
2. Press ⌘C to copy them, or ⌘X to cut them.
3. Press ⌘V. The copy appears where the original was, selected, and Move starts.
4. Click a base point, then the new position, or press Esc to leave the copy where it was pasted.

**Notes**

- Paste works in any open document and as often as you like. Each paste is one Undo step and the move after it another; a cut is one Undo step.
- Plain shapes and STL meshes are copied as plain geometry with their colors. A pasted mesh is not moved automatically.
- Parametric features go through FreeCAD's own Copy and Paste, so they keep their history, and cannot be cut. Cut refuses locked objects and objects another object depends on.
- In text fields these keys copy and paste text as usual.

**See also:** [Copy](#copy) · [Move](#move) · [Delete](#delete)

## Pattern { #pattern }

Pattern repeats whole objects in a grid, around an axis, or along a path in one step. The preview shows every copy before you make them.

![](../../Resources/icons/pattern.svg){ .tool-icon } Modify toolbar · MCP `simplecad_pattern`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/pattern.mp4" poster="clips/pattern.jpg" controls muted loop playsinline preload="none" aria-label="One peg previews a pattern along an arc, as a grid and around the Z axis, then six are made around the axis."></video>
<figcaption>One peg previews a pattern along an arc, as a grid and around the Z axis, then six are made around the axis.</figcaption>
</figure>

**Steps**

1. Select the whole objects to repeat, in the Objects list or with the status-bar filter set to Select: Objects.
2. To follow a path, also select an edge, or connected edges, on another object.
3. Click Pattern.
4. Choose Grid along X, Y and Z, Around an axis, or Along the selected path, and set the counts.
5. Check the outline preview and the number of copies, then click Make copies.

**Options**

| Option | What it does |
| --- | --- |
| Grid along X, Y and Z | A count and a spacing for each world axis. The spacing starts at 1.5 times the selection's largest size. |
| Around an axis | Count, Total angle, Axis (world X, Y or Z) and Through (world origin or selection centre). A full 360 degrees spreads the copies evenly; a smaller angle puts the last one at that angle. |
| Along the selected path | Count and Turn the copies with the path. Copies are spaced evenly by length. The original stays where it is and each copy keeps the original's offset from the path, so place the original at the path's start. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Esc</kbd> | Cancel; no copies are made. |

**Notes**

- Counts include the original: a count of 6 makes 5 copies.
- Each copy is a separate object with the same colors and hidden faces. The originals do not change.
- At most 500 copies per pattern. All copies are one Undo step.
- The path must be connected end to end, without branches or gaps.

**See also:** [Copy](#copy) · [Mirror](#mirror) · [Sweep](#sweep)

## Mirror { #mirror }

Mirror flips whole objects along X, Y or Z. By default it makes a mirrored copy and leaves the original as it is.

![](../../Resources/icons/mirror.svg){ .tool-icon } Modify toolbar · MCP `simplecad_mirror`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/mirror.mp4" poster="clips/mirror.jpg" controls muted loop playsinline preload="none" aria-label="A stepped part is mirrored along X with the plane on its + side, so the copy lands beside it and forms a symmetric channel."></video>
<figcaption>A stepped part is mirrored along X with the plane on its + side, so the copy lands beside it and forms a symmetric channel.</figcaption>
</figure>

**Steps**

1. Select one or more objects, or a face or edge on them.
2. Click Mirror.
3. Choose the axis to flip along.
4. Choose where the mirror plane passes.
5. Click Mirror.

**Options**

| Option | What it does |
| --- | --- |
| Mirror along | X flips across the YZ plane, Y across XZ, Z across XY. |
| Plane through | Selection center (flip in place), the selection's + or - side (the copy lands right beside it, touching), or the world origin. Several objects mirror together as one group. |
| Mirror the original instead of making a copy | Flips the selected objects themselves instead of adding copies. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Esc</kbd> | Close the dialog without mirroring. |

**Notes**

- There is no live preview; the dialog applies when you click Mirror.
- Faces keep their order, so face colors, hidden faces and locks stay on the same faces.
- Mirroring the original needs it to be unlocked and not used by another object. A copy can always be made.
- One Undo step.

**See also:** [Copy](#copy) · [Rotate](#rotate) · [Pattern](#pattern)

## Delete { #delete }

Delete erases the selected edges, faces or objects. Erasing a line between two coplanar faces merges them; deleting a face opens the shape.

![](../../Resources/icons/delete.svg){ .tool-icon } Modify toolbar · Shortcut <kbd>Delete</kbd> / <kbd>Backspace</kbd> · MCP `simplecad_delete`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/delete.mp4" poster="clips/delete.jpg" controls muted loop playsinline preload="none" aria-label="The line dividing a block&#x27;s top face is deleted so the two faces merge, then the top face is deleted to open the box."></video>
<figcaption>The line dividing a block&#x27;s top face is deleted so the two faces merge, then the top face is deleted to open the box.</figcaption>
</figure>

**Steps**

1. Select an edge or a face in the 3D view, or a whole object in the Objects list.
2. Click Delete, or press Delete or Backspace with the 3D view focused.

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Delete</kbd> / <kbd>Backspace</kbd> | Delete the selection, the same as the toolbar button. |

**Notes**

- An edge between two faces in the same plane merges them; other divisions stay and a solid keeps its volume.
- An edge between faces that meet at an angle removes both faces and opens the shape. An edge on just one face removes that face.
- Deleting a face removes it and leaves an open surface. Deleting the complete wall of a hole in a solid closes the hole instead, and the part stays a solid.
- Matching edges in other visible objects are erased together, so one Delete reaches every adjoining face.
- Seam lines of curved surfaces are kept. Vertices cannot be deleted on their own. Deleting a whole object refuses when other objects depend on it.
- Everything selected is deleted in one Undo step.

**See also:** [Delete & heal faces](surface.md#healfaces) · [Union](#union) · [Push/Pull](#pushpull) · [Select](draw.md#select)
