# Draw

The Draw toolbar makes lines, faces and solids, and divides existing faces into regions. For a guided tour, see the [user guide](../user-guide.md#drawing).

## Select { #select }

Select picks faces, edges and vertices with a click, or many at once with a box. The direction you drag decides whether the box takes only what is fully inside it or also what it touches.

![](../../Resources/icons/select.svg){ .tool-icon } Draw toolbar · Shortcut <kbd>S</kbd> / <kbd>Esc</kbd> · MCP `simplecad_select`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/select.mp4" poster="clips/select.jpg" controls muted loop playsinline preload="none" aria-label="A left-to-right box takes only the block it fully encloses, a right-to-left box also takes the cylinder it touches, then a click selects a single face and a click in empty space clears the selection."></video>
<figcaption>A left-to-right box takes only the block it fully encloses, a right-to-left box also takes the cylinder it touches, then a click selects a single face and a click in empty space clears the selection.</figcaption>
</figure>

**Steps**

1. Click Select or press S with the 3D view focused. Pressing Esc after drawing also returns to Select.
2. Click a face, edge or vertex to select just that element.
3. To select with a box, hold the left mouse button and drag.
4. Drag from left to right for a solid blue Window box: only faces and edges completely inside it are selected.
5. Drag from right to left for a dashed green Crossing box: faces and edges inside it or crossing its border are selected.
6. Release the button to apply the selection. Click empty space to clear it.

**Options**

| Option | What it does |
| --- | --- |
| Select filter (status bar) | All, Faces, Edges, Vertices or Objects. It controls what clicks and boxes pick. Objects selects whole objects; in Edges mode a click on a face takes the nearest edge. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Shift</kbd> | Hold while releasing a box to add to the current selection. |
| <kbd>Ctrl</kbd> / <kbd>⌘</kbd> | Hold while releasing a box to toggle the items in it. Ctrl-click keeps FreeCAD's normal behavior. |
| <kbd>Esc</kbd> | During a drag, cancel the box and keep the previous selection. |
| <kbd>Double-click</kbd> | Grow a face or edge into its hole, edge loop, flat region or smooth surface. |

**Notes**

- The box mode follows the current horizontal direction of the drag, even if you reverse while dragging. You can start the box over geometry or in empty space.
- A box selects individual faces and edges, so it can take just one end of a block. Like a selection volume, it also reaches faces and edges hidden behind the front of a visible object.
- Hidden objects, hidden faces and surface seams are never selected. Meshes, links and components are not picked by the box.
- Selecting changes nothing in the model and adds no Undo step.
- Move, Rotate and Copy act on the whole objects that own the selected faces or edges. Delete acts on exactly the selected faces and edges.

**See also:** [Smart select](inspect.md#smartselect) · [Delete](modify.md#delete) · [Move](modify.md#move)

## Line { #line }

Line draws connected straight segments, one per click. It follows the world X, Y and Z axes and snaps to existing points, and a closed loop or a line across a face makes new faces.

![](../../Resources/icons/line.svg){ .tool-icon } Draw toolbar · Shortcut <kbd>L</kbd> · MCP `simplecad_create_line`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/line.mp4" poster="clips/line.jpg" controls muted loop playsinline preload="none" aria-label="Lines along X (red) and Y (green, typed 30 mm) are closed back at the start into a filled face, then the preview turns blue along Z before Esc finishes."></video>
<figcaption>Lines along X (red) and Y (green, typed 30 mm) are closed back at the start into a filled face, then the preview turns blue along Z before Esc finishes.</figcaption>
</figure>

**Steps**

1. Click Line or press L with the 3D view focused.
2. Click the first point.
3. Move the pointer. Near a world axis through the last point the preview locks to it and turns red for X, green for Y or blue for Z.
4. Click to add a segment. Its end becomes the start of the next one.
5. For an exact length, press Tab, type the length and press Enter. The segment follows the current preview direction.
6. Keep clicking. When a segment closes a loop into a face, Line stops; press Esc to finish sooner, or L to start another line.

**Options**

| Option | What it does |
| --- | --- |
| Plane (status bar) | Auto lets Line move freely in 3D, follow all three world axes and snap to points on any face. XY, XZ or YZ keeps the whole chain on that world plane through the origin and offers only its two axes. Choose it before the first click, with the selector or the arrow keys; restart Line to change it. |
| Draw (status bar) | Plane, the default, draws on a flat plane. Surface draws on curved CAD faces and wraps across the connected faces of one object; see [drawing on curved faces](../user-guide.md#draw-directly-on-curved-faces). |
| Snap (status bar) | Turns automatic axis alignment and point snapping on or off. Key locks still work with Snap off. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Lock the next segment to that world axis; press the same key again to unlock. The lock resets after each segment. |
| <kbd>→ ← ↑ ↓</kbd> | Before the first click, choose the plane: → YZ, ← XZ, ↑ XY, ↓ Auto. After it, lock the direction to X, Y or Z, like the letter keys. |
| <kbd>Tab</kbd> | Open a box on the length label to type a length, such as 20 or 2 cm. Typing a number opens it too. A negative length reverses the direction. |
| <kbd>Enter</kbd> | Add the typed segment and continue from its end. |
| <kbd>Esc</kbd> | Finish the line. Every clicked segment stays; only the unfinished preview is discarded. |
| <kbd>⌘Z</kbd> | End the line and undo the last segment, one segment at a time. |

**Notes**

- A closed loop of connected loose lines and arcs on one plane becomes a filled face, and Line stops there. Retracing an existing edge, or crossing one to a free end, keeps it going.
- The current segment's length is shown beside it. A typed length is shown there until the pointer moves.
- A line drawn on a flat face from one boundary point to another divides that face into regions you can Push/Pull or delete. Snap its ends to corners or edge midpoints so they lie exactly on the boundary.
- Snaps to endpoints, edge midpoints and face centers take priority over axis alignment.
- If an axis points straight at the camera, orbit to see it, or lock it with its key and type a length.
- Each segment is its own Undo step. Selecting another tool also finishes the line.

**See also:** [Snapping](#snapping) · [Push/Pull](modify.md#pushpull) · [Delete](modify.md#delete) · [Exact values](../user-guide.md#first-five-minutes)

## Rectangle { #rectangle }

Rectangle draws a filled rectangular face from two opposite corners. Use it as a profile for Push/Pull.

![](../../Resources/icons/rectangle.svg){ .tool-icon } Draw toolbar · Shortcut <kbd>R</kbd> · MCP `simplecad_create_rectangle`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/rectangle.mp4" poster="clips/rectangle.jpg" controls muted loop playsinline preload="none" aria-label="A rectangle is drawn on the ground plane with two clicks, then a second one is made exactly 30 by 18 mm by typing the size after the first corner."></video>
<figcaption>A rectangle is drawn on the ground plane with two clicks, then a second one is made exactly 30 by 18 mm by typing the size after the first corner.</figcaption>
</figure>

**Steps**

1. Click Rectangle or press R with the 3D view focused.
2. Click the first corner on the drawing plane or on a flat face.
3. Move the pointer to size the rectangle, then click the opposite corner.
4. For an exact size, press Tab after the first corner, type width, height (for example 30, 18) and press Enter.

**Options**

| Option | What it does |
| --- | --- |
| Plane (status bar) | Auto draws on the flat face under the pointer, otherwise on XY. XY, XZ or YZ draws on that world plane. The plane stays fixed after the first corner. |
| Draw (status bar) | Plane, the default, draws on a flat plane. Surface draws on curved CAD faces and wraps across the connected faces of one object; see [drawing on curved faces](../user-guide.md#draw-directly-on-curved-faces). |
| Snap (status bar) | Snaps both corners to vertices, edge midpoints and face centers on the plane. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>→ ← ↑ ↓</kbd> | Choose the plane: → YZ, ← XZ, ↑ XY, ↓ back to Auto. The plane passes through the point you start from; after the first click the preview turns about that point. |
| <kbd>Tab</kbd> | Open a width and a height box on the rectangle's sides. Type width, height, such as 40, 30 or 4 cm, 3 cm; the comma, or Tab, moves to the height box. Negative values extend the other way along the plane's axes. |
| <kbd>Enter</kbd> | Create the rectangle with the typed size. |
| <kbd>Esc</kbd> | Cancel the unfinished rectangle. |

**Notes**

- Its width and height are shown beside its first two sides while you draw.
- On a face, the rectangle divides that face into its own region, as Circle and Polygon do, ready for Push/Pull. It must fit on that flat surface. Drawn across an earlier rectangle, circle or line there, it divides each region it crosses, so the overlap becomes a region of its own. In empty space it creates a filled face.
- Creating a rectangle is one Undo step.

**See also:** [Push/Pull](modify.md#pushpull) · [Polygon](#polygon) · [Circle](#circle)

## Circle { #circle }

Circle draws a filled circle from its center and radius. On a flat face it divides the face into a round region you can pull into a boss, push into a pocket or delete to open a hole.

![](../../Resources/icons/circle.svg){ .tool-icon } Draw toolbar · Shortcut <kbd>O</kbd> · MCP `simplecad_create_circle`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/circle.mp4" poster="clips/circle.jpg" controls muted loop playsinline preload="none" aria-label="A circle snapped to the center of a block&#x27;s top face divides it into a round region, then a second circle on the front face gets an exact 4 mm radius by typing."></video>
<figcaption>A circle snapped to the center of a block&#x27;s top face divides it into a round region, then a second circle on the front face gets an exact 4 mm radius by typing.</figcaption>
</figure>

**Steps**

1. Click Circle or press O with the 3D view focused.
2. Click the center. Over a face, an amber target marks the face center; it reads Center snapped when caught.
3. Move the pointer to preview the radius and click to finish.
4. For an exact size, press Tab after the center, type the radius and press Enter.

**Options**

| Option | What it does |
| --- | --- |
| Plane (status bar) | Auto draws on the flat face under the pointer, otherwise on XY. XY, XZ or YZ draws on that world plane. The plane stays fixed after the center click. |
| Draw (status bar) | Plane, the default, draws on a flat plane. Surface draws on curved CAD faces and wraps across the connected faces of one object; see [drawing on curved faces](../user-guide.md#draw-directly-on-curved-faces). |
| Snap (status bar) | Snaps the center and the radius point to vertices, edge midpoints and face centers on the plane. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>→ ← ↑ ↓</kbd> | Choose the plane: → YZ, ← XZ, ↑ XY, ↓ back to Auto. The plane passes through the point you start from; after the first click the preview turns about that point. |
| <kbd>Tab</kbd> | Type the radius, such as 5 or 1 cm. Radius is half the diameter: 5 makes a circle 10 mm across. |
| <kbd>Enter</kbd> | Create the circle with the typed radius. |
| <kbd>Esc</kbd> | Cancel the unfinished circle. |

**Notes**

- The radius is shown beside the preview. A typed size is shown there until the pointer moves.
- On existing geometry the circle must fit on one flat surface. It may cross lines and regions drawn there earlier, dividing each one. The object keeps its volume; the face is only divided.
- In empty space the circle becomes a standalone filled disk.
- To open a hole, select the inner region and press Delete. To cut a hole with walls, Push/Pull the region to the Opposite face target.
- Deleting the circular edge merges the two regions again.
- Creating a circle is one Undo step.

**See also:** [Push/Pull](modify.md#pushpull) · [Snapping](#snapping) · [Arc](#arc) · [Delete](modify.md#delete)

## Arc { #arc }

Arc draws a circular arc from its center, a start point and an end point. Use it for rounded outlines and curved dividers on a face.

![](../../Resources/icons/arc.svg){ .tool-icon } Draw toolbar · Shortcut <kbd>A</kbd> · MCP `simplecad_create_arc`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/arc.mp4" poster="clips/arc.jpg" controls muted loop playsinline preload="none" aria-label="On a plate the arc&#x27;s center snaps to a corner and its start to an edge midpoint, the pointer sweeps around to preview, and a typed sweep of 90 degrees leaves a quarter arc that divides the face."></video>
<figcaption>On a plate the arc&#x27;s center snaps to a corner and its start to an edge midpoint, the pointer sweeps around to preview, and a typed sweep of 90 degrees leaves a quarter arc that divides the face.</figcaption>
</figure>

**Steps**

1. Click Arc or press A with the 3D view focused.
2. Click the center.
3. Click the start point. Its distance from the center sets the radius.
4. Move around the center. The direction you move chooses the sweep, including arcs larger than 180 degrees.
5. Click the end point, or press Tab, type the sweep in degrees and press Enter.

**Options**

| Option | What it does |
| --- | --- |
| Plane (status bar) | Auto uses the flat face under the pointer, otherwise XY. XY, XZ or YZ draws on that world plane. The plane stays fixed after the first click. |
| Draw (status bar) | Plane, the default, draws on a flat plane. Surface draws on curved CAD faces and wraps across the connected faces of one object; see [drawing on curved faces](../user-guide.md#draw-directly-on-curved-faces). |
| Snap (status bar) | Snaps the center, start and end to vertices, edge midpoints and face centers on the plane. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>→ ← ↑ ↓</kbd> | Choose the plane: → YZ, ← XZ, ↑ XY, ↓ back to Auto. The plane passes through the point you start from; after the first click the preview turns about that point. |
| <kbd>Tab</kbd> | After the center, type the radius; after the start point, type a signed sweep such as 90, -180 deg or 270 deg. Positive angles turn counterclockwise seen from the plane's normal side. |
| <kbd>Enter</kbd> | Accept the typed value. |
| <kbd>Esc</kbd> | Cancel without adding geometry. |

**Notes**

- An arc that crosses a flat face from boundary to boundary divides it into regions.
- A closed loop of connected loose arcs and lines becomes a face. Open arcs stay edges; no chord or radius lines are added.
- A zero sweep and a full circle are refused. Use Circle for a full circle.
- There is no tangent snapping or three-point arc.
- Finishing an arc is one Undo step.

**See also:** [2 Point Arc](#arc2point) · [Circle](#circle) · [Line](#line)

## 2 Point Arc { #arc2point }

2 Point Arc draws an arc between two endpoints and lets you set how far it bulges from the straight line between them. Use it when you know where an arc must start and end.

![](../../Resources/icons/arc2point.svg){ .tool-icon } Draw toolbar · Shortcut <kbd>H</kbd> · MCP `simplecad_create_2_point_arc`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/arc2point.mp4" poster="clips/arc2point.jpg" controls muted loop playsinline preload="none" aria-label="Two clicks on the front corners of a plate set the endpoints, and moving away from the edge sets the bulge before a third click leaves an arch that divides the face."></video>
<figcaption>Two clicks on the front corners of a plate set the endpoints, and moving away from the edge sets the bulge before a third click leaves an arch that divides the face.</figcaption>
</figure>

**Steps**

1. Click 2 Point Arc or press H with the 3D view focused.
2. Click the first endpoint.
3. Click the second endpoint.
4. Move the pointer away from the line between them to set the bulge, then click to finish.

**Options**

| Option | What it does |
| --- | --- |
| Plane (status bar) | Auto uses the flat face under the pointer, otherwise XY. XY, XZ or YZ draws on that world plane. The plane stays fixed after the first click. |
| Draw (status bar) | Plane, the default, draws on a flat plane. Surface draws on curved CAD faces and wraps across the connected faces of one object; see [drawing on curved faces](../user-guide.md#draw-directly-on-curved-faces). |
| Snap (status bar) | Snaps the endpoints and the bulge point to vertices, edge midpoints and face centers on the plane. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>→ ← ↑ ↓</kbd> | Choose the plane: → YZ, ← XZ, ↑ XY, ↓ back to Auto. The plane passes through the point you start from; after the first click the preview turns about that point. |
| <kbd>Tab</kbd> | After the first endpoint, type the distance to the second along the pointer direction; after the second endpoint, type a signed bulge such as 5 mm or -1 cm. |
| <kbd>Enter</kbd> | Accept the typed value. |
| <kbd>Esc</kbd> | Cancel without adding geometry. |

**Notes**

- The bulge is the distance from the middle of the chord to the middle of the arc. Positive bulge lies to the left of the first-to-second direction, seen from the plane's normal side.
- A bulge larger than half the endpoint distance makes an arc larger than a semicircle.
- A zero bulge is refused.
- Like Arc, it divides a flat face it crosses from boundary to boundary, and closed loops of arcs and lines become faces.
- Finishing an arc is one Undo step.

**See also:** [Arc](#arc) · [Line](#line)

## Polygon { #polygon }

Polygon draws a filled regular polygon from its center and one vertex. You choose the number of sides in the status bar.

![](../../Resources/icons/polygon.svg){ .tool-icon } Draw toolbar · Shortcut <kbd>G</kbd> · MCP `simplecad_create_polygon`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/polygon.mp4" poster="clips/polygon.jpg" controls muted loop playsinline preload="none" aria-label="Sides is set to 5, the center snaps to the middle of a block&#x27;s top face, and changing Sides to 8 updates the preview before a click leaves an octagonal region on the face."></video>
<figcaption>Sides is set to 5, the center snaps to the middle of a block&#x27;s top face, and changing Sides to 8 updates the preview before a click leaves an octagonal region on the face.</figcaption>
</figure>

**Steps**

1. Click Polygon or press G with the 3D view focused.
2. Set Sides in the status bar, for example 3 for a triangle or 6 for a hexagon.
3. Click the center on a flat face or the drawing plane.
4. Move the pointer to place a vertex. This sets both the size and the orientation.
5. Click to finish, or press Tab, type the radius and press Enter.

**Options**

| Option | What it does |
| --- | --- |
| Sides (status bar) | Number of equal sides, from 3 to 100, initially 6. You can change it before or after the center click and the preview follows. The count is remembered until FreeCAD closes. |
| Draw (status bar) | Plane, the default, draws on a flat plane. Surface draws on curved CAD faces and wraps across the connected faces of one object; see [drawing on curved faces](../user-guide.md#draw-directly-on-curved-faces). |
| Plane (status bar) | Auto draws on the flat face under the pointer, otherwise on XY. XY, XZ or YZ draws on that world plane. The plane stays fixed after the center click. |
| Snap (status bar) | Snaps the center and the vertex to vertices, edge midpoints and face centers on the plane. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>→ ← ↑ ↓</kbd> | Choose the plane: → YZ, ← XZ, ↑ XY, ↓ back to Auto. The plane passes through the point you start from; after the first click the preview turns about that point. |
| <kbd>Tab</kbd> | Type the radius from the center to a vertex, such as 5 mm or 1 cm. The pointer's direction keeps the orientation. |
| <kbd>Enter</kbd> | In the radius field, create the polygon. In the Sides field, Enter only confirms the count. |
| <kbd>Esc</kbd> | Cancel, also while editing Sides. |

**Notes**

- The radius is shown beside the preview. A typed size is shown there until the pointer moves.
- The radius reaches a vertex, not the middle of a side.
- On a face the polygon becomes a region of that face; in empty space it becomes a standalone filled face.
- A polygon started on a face must fit on that flat surface; it may cross regions drawn there earlier, dividing each one. An oversized polygon or one crossing a hole or gap is refused and the face stays unchanged.
- Changing Sides and moving the preview make no document changes. Creating the polygon is one Undo step.
- For irregular outlines, use Line.

**See also:** [Circle](#circle) · [Push/Pull](modify.md#pushpull) · [Line](#line)

## Sphere { #sphere }

Sphere creates a complete, smooth solid ball from its center and radius. It is a separate object; use Union to join it to another solid.

![](../../Resources/icons/sphere.svg){ .tool-icon } Draw toolbar · Shortcut <kbd>B</kbd> · MCP `simplecad_create_sphere`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/sphere.mp4" poster="clips/sphere.jpg" controls muted loop playsinline preload="none" aria-label="A sphere is centered on the snapped middle of a block&#x27;s top face and sized with a click, then a second sphere on a corner gets an exact 5 mm radius by typing."></video>
<figcaption>A sphere is centered on the snapped middle of a block&#x27;s top face and sized with a click, then a second sphere on a corner gets an exact 5 mm radius by typing.</figcaption>
</figure>

**Steps**

1. Click Sphere or press B with the 3D view focused.
2. Click the center on the drawing plane or on a face.
3. Move the pointer to preview the radius and click to finish.
4. For an exact size, press Tab after the center, type the radius and press Enter.

**Options**

| Option | What it does |
| --- | --- |
| Plane (status bar) | Sets the plane on which you pick the radius. Auto uses the flat face under the pointer, a plane facing the view on a curved face, or XY in empty space. XY, XZ or YZ uses that world plane. |
| Snap (status bar) | Snaps the center and radius point to vertices, edge midpoints and face centers. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>→ ← ↑ ↓</kbd> | Choose the plane: → YZ, ← XZ, ↑ XY, ↓ back to Auto. The plane passes through the point you start from; after the first click the preview turns about that point. |
| <kbd>Tab</kbd> | Type a positive radius, such as 5 mm or 1 cm. |
| <kbd>Enter</kbd> | Create the sphere with the typed radius. |
| <kbd>Esc</kbd> | Cancel the unfinished sphere. |

**Notes**

- The radius is shown beside the preview. A typed size is shown there until the pointer moves.
- A center on a face leaves half of the sphere on each side of that face. The sphere does not cut or change objects it overlaps.
- Push/Pull and Subdivide need flat faces, so they do not work on the sphere's surface.
- Creating a sphere is one Undo step.

**See also:** [Union](modify.md#union) · [Move](modify.md#move) · [Slice / Separate](modify.md#slice)

## Snapping { #snapping }

While you draw, the pointer snaps to corners, edge midpoints and face centers of existing parts, so new lines and shapes start and end at exact points. Drawing on a face of a part divides that face into regions you can pull or delete.

Draw tools, Snap in the status bar
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/snapping.mp4" poster="clips/snapping.jpg" controls muted loop playsinline preload="none" aria-label="Line picks up a block&#x27;s corner, top face center and front edge midpoint through their snap targets, and the two lines close a triangle that becomes its own face."></video>
<figcaption>Line picks up a block&#x27;s corner, top face center and front edge midpoint through their snap targets, and the two lines close a triangle that becomes its own face.</figcaption>
</figure>

**Steps**

1. Keep Snap checked in the status bar and the plane on Auto.
2. Start a drawing tool, such as Line, and hover a flat face. An amber target labeled Center marks the face center.
3. Move toward a target. It fills and its label adds snapped when the point is caught.
4. Click while the target is snapped to use that exact point.
5. On a face, draw lines between snapped points until they close a region against the face's boundary. The face divides and the region becomes its own face.

**Options**

| Option | What it does |
| --- | --- |
| Snap (status bar) | Turns all automatic snapping off or on. With it off, the guides are hidden and X/Y/Z key locks still work. |
| SimpleCAD Settings | Open Settings in the status bar or the SimpleCAD menu to turn endpoints, edge midpoints, face and circle centers or axis alignment on and off, and to change each capture distance in pixels. |

**Notes**

- Corners (Endpoint) show a green square and edge midpoints (Midpoint) a blue diamond; both catch within 24 pixels. Face centers and the centers of circles, arcs and round holes show an amber target that catches within 40 pixels and appears before you reach it.
- A rectangular face has nine targets: four corners, four edge midpoints and its center. Curved faces have no center target.
- When targets crowd together, a corner within about 12 pixels wins over nearby centers and midpoints.
- After the first click, Rectangle, Circle, Arc, 2 Point Arc, Sphere and Polygon accept only points on their plane. Line in Auto can snap to points anywhere in 3D.
- Targets on the far side of a part are not hidden, so a hidden corner or face center can be caught and can even choose the drawing plane. Orbit so the point you want faces you, and check the snap label before you click.
- Two lines from a corner to the face center and on to an edge midpoint close a triangle; the first line stays loose until the second closes the region.
- Guides left by [Measure Tape](inspect.md#tape) are targets too: along a guide line (On guide), at a guide point (Guide point), and where a guide crosses an edge or another guide (Intersection).

**See also:** [Line](#line) · [Circle](#circle) · [Measure Tape](inspect.md#tape) · [Settings](panels.md#settings) · [Push/Pull](modify.md#pushpull)
