# Panels and settings

The Model tab, the status bar and the SimpleCAD menu. For a guided tour, see the [user guide](../user-guide.md#settings).

## Faces and Objects panels { #facespanel }

The Faces tab lists the shapes in the active document and, when you expand one, each of its faces. Use it to find and select faces that are small or hidden in the view. The Objects tab is FreeCAD's normal tree.

Model panel, Faces tab · MCP `simplecad_select`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/facespanel.mp4" poster="clips/facespanel.jpg" controls muted loop playsinline preload="none" aria-label="Hovering face rows highlights the top, front and hole faces; a click and a Ctrl-click select faces, the object row selects the whole block, and a hidden back face picked from the list is pulled out 8 mm with P."></video>
<figcaption>Hovering face rows highlights the top, front and hole faces; a click and a Ctrl-click select faces, the object row selects the whole block, and a hidden back face picked from the list is pulled out 8 mm with P.</figcaption>
</figure>

**Steps**

1. In the Model panel, click Faces.
2. Click the arrow beside a shape to list Face 1, Face 2 and so on.
3. Point at a row to highlight that face in the view. A tooltip shows its surface type and area.
4. Click a row to select the face. Click the shape's own row to select the whole shape.
5. With a face selected, press P to start Push/Pull on it, D to subdivide it, or Delete to remove it.

**Options**

| Option | What it does |
| --- | --- |
| Eye | Shows or hides the object or face. See Show or hide. |
| Color swatch | Opens Color & opacity for that face or object. |
| Padlock | Locks or unlocks the row. See Lock faces and objects. |
| Right-click menu | Show / hide, Lock geometry and Unlock geometry for the selected rows, followed by the tools that fit the selection. |
| Objects tab | FreeCAD's normal tree, with renaming, visibility and groups. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Ctrl-click (⌘-click on macOS)</kbd> | Add a row to the selection. |
| <kbd>Shift-click</kbd> | Select a range of rows. |
| <kbd>P</kbd> | Start Push/Pull on the selected flat face. Move in the view, or type a distance and press Enter. |
| <kbd>D</kbd> | Open Subdivide on the selected flat face. |
| <kbd>Delete or Backspace</kbd> | Remove only the selected faces. |

**Notes**

- Face numbers describe the current shape and can change after an edit. Old face selections are cleared when the shape changes.
- Picking a face in the view highlights its row too.
- Hidden shapes stay listed with muted names. Selecting them does not show them.
- Move, Rotate and Copy act on the whole parent object even when a face row is selected.
- Curved faces can be selected and deleted, but Push/Pull and Subdivide still need a flat face.
- A raw mesh is listed as a single (mesh) row without faces. Use Make mesh editable to get selectable faces.
- The list shows the shapes of the active document without the Objects tree's group hierarchy, and adds no saved objects.

**See also:** [Show or hide](#visibility) · [Lock faces and objects](#lock) · [Color & opacity](#appearance) · [Push/Pull](modify.md#pushpull) · [Subdivide face](modify.md#subdivide) · [Select](draw.md#select)

## Lock faces and objects { #lock }

A padlock protects geometry from accidental edits. Lock single faces that must not change, or lock a whole object.

Model panel, Faces tab · MCP `simplecad_set_locked`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/lock.mp4" poster="clips/lock.jpg" controls muted loop playsinline preload="none" aria-label="The top face of a block is padlocked and Push/Pull on it is refused; the object padlock is locked and unlocked, which keeps the face lock, and then the face is unlocked."></video>
<figcaption>The top face of a block is padlocked and Push/Pull on it is refused; the object padlock is locked and unlocked, which keeps the face lock, and then the face is unlocked.</figcaption>
</figure>

**Steps**

1. In the Faces tab, expand the object.
2. Click the padlock on a face row to lock that face, or on the object row to lock the whole object.
3. Click the padlock again to unlock it.
4. For several rows, select them and choose Lock geometry or Unlock geometry from the right-click menu.

**Notes**

- Locked geometry stays visible, selectable and available for snapping. You can still change its color, opacity and eye, or make an unlocked copy.
- SimpleCAD refuses any edit that would move, reshape or delete a locked face, including indirect changes through a shared edge, and says why in the status bar. Other faces can still be edited. A refused edit leaves no partial change.
- An object lock protects the entire object. Unlock the object before changing its face locks. Unlocking the object keeps the individual face locks.
- Moving or rotating a whole object requires all of its face locks to be cleared.
- Mesh tools other than Make mesh editable are disabled on a locked mesh.
- Locks are saved in the FCStd file and support Undo and Redo. They protect SimpleCAD tools and MCP edits; other workbenches and direct Python edits do not enforce them.

**See also:** [Faces and Objects panels](#facespanel) · [Show or hide](#visibility) · [Push/Pull](modify.md#pushpull) · [Copy](modify.md#copy)

## Show or hide { #visibility }

The eyes in the Faces tab hide or show whole objects or single faces. This changes only the view; the shape stays complete.

Model panel, Faces tab · MCP `simplecad_set_visibility`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/visibility.mp4" poster="clips/visibility.jpg" controls muted loop playsinline preload="none" aria-label="Face eyes hide the front and top of a box to show an orange ball inside; the object eye hides and shows the whole box with those choices remembered, and the face eyes show the faces again."></video>
<figcaption>Face eyes hide the front and top of a box to show an orange ball inside; the object eye hides and shows the whole box with those choices remembered, and the face eyes show the faces again.</figcaption>
</figure>

**Steps**

1. Click the eye on an object row to hide or show the whole object.
2. Expand an object and click the eye on a face row to hide just that face.
3. Click a crossed eye to show the face or object again.
4. For several rows, select them and choose Show / hide from the right-click menu.

**Notes**

- An open eye means visible and a crossed eye means hidden. Clicking an eye leaves your other selections alone.
- The object eye remembers which faces you hid. Showing a hidden face also shows its object if needed.
- Edges shared with visible faces stay visible. Hidden geometry is excluded from selection in the view, box selection and snapping, but stays in the list.
- The solid stays complete, and exporting it includes hidden faces. Use Delete when you mean to remove geometry.
- Eye changes support Undo and Redo and are saved in the FCStd file. Files opened without SimpleCAD still contain the complete shapes.
- Face eyes work on ordinary Part shapes. For linked or parametric features, make a Part simple copy first.

**See also:** [Faces and Objects panels](#facespanel) · [Color & opacity](#appearance) · [Lock faces and objects](#lock) · [Isolate selection](inspect.md#isolate) · [Delete](modify.md#delete)

## Color & opacity { #appearance }

Color & opacity sets the surface color and transparency of faces or whole objects. The view previews the change before you apply it.

SimpleCAD menu · MCP `simplecad_set_appearance`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/appearance.mp4" poster="clips/appearance.jpg" controls muted loop playsinline preload="none" aria-label="The top face&#x27;s swatch turns it blue; the object&#x27;s swatch then sets the housing to 30% opacity, showing the orange ball inside while the blue top keeps its color."></video>
<figcaption>The top face&#x27;s swatch turns it blue; the object&#x27;s swatch then sets the housing to 30% opacity, showing the orange ball inside while the blue top keeps its color.</figcaption>
</figure>

**Steps**

1. Click the color swatch beside a face or object eye in the Faces tab. Or select faces or objects and choose SimpleCAD → Modify → Color & opacity…, or use the right-click menu.
2. Click Surface color and choose a color.
3. Drag the Opacity slider or type a percentage.
4. Click Apply, or Cancel to restore the previous look.

**Options**

| Option | What it does |
| --- | --- |
| Surface color | Opens a color chooser. The view previews the color. |
| Opacity | 0% is fully transparent and 100% is fully opaque. |

**Notes**

- Only the controls you change are applied, so changing an object's opacity keeps its individual face colors.
- Selecting an object row applies the change to every face of that object. Mixed selections show a mixed swatch or an opacity note.
- Opacity affects surfaces only; edges stay visible. Use the eye to hide a face or object completely.
- Apply is one Undo step. Colors and opacity are saved in the FCStd file as native materials and are kept by Copy. They do not change geometry or exported solids.
- When an edit splits a face, each piece keeps its style. When faces merge, the largest one supplies the style. Check the result after edits that rebuild the shape.
- The command needs CAD faces or objects. Raw mesh objects are not supported.

**See also:** [Faces and Objects panels](#facespanel) · [Show or hide](#visibility) · [Copy](modify.md#copy)

## Merge coincident geometry { #cleanup }

Merge coincident geometry removes duplicate faces and lines that exactly cover other geometry, and joins open surfaces that share an edge into one object. Use it to tidy a model built from separate pieces.

SimpleCAD menu · MCP `simplecad_cleanup`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/cleanup.mp4" poster="clips/cleanup.jpg" controls muted loop playsinline preload="none" aria-label="Three surfaces that touch at their edges and an exact orange copy under the base (shown by hiding Base) are merged into one surface object with three faces."></video>
<figcaption>Three surfaces that touch at their edges and an exact orange copy under the base (shown by hiding Base) are merged into one surface object with three faces.</figcaption>
</figure>

**Steps**

1. Clear the selection to clean up every visible editable object, or select the objects to include.
2. Choose SimpleCAD → Modify → Merge coincident geometry.
3. Expand the result in the Faces tab to check its faces.

**Notes**

- Only full overlaps in world coordinates count, so moved or rotated copies are found. Partial overlaps, nearby surfaces and equal sizes elsewhere are not treated as duplicates.
- Deliberate flat-face divisions stay until you erase their edges.
- Closed solids keep their boundaries. Exact duplicate solids collapse, but different touching solids stay separate, and an extra sheet on a solid stays a separate surface.
- Hidden objects are excluded unless you select them.
- Separate compounds that mix solids and surfaces, or hold several solids, before merging. Removing an object that others depend on is refused before anything changes.
- The whole cleanup is one Undo step, which restores the original objects.

**See also:** [Union](modify.md#union) · [Heal to precision](#heal) · [Delete](modify.md#delete) · [Show or hide](#visibility)

## Heal to precision { #heal }

Heal to precision snaps nearly parallel, axis-aligned or coplanar flat faces and slightly skewed holes to exact alignment. Use it on converted meshes where tiny tilts stop faces from merging or leave a skin in a through-hole.

SimpleCAD menu · MCP `simplecad_heal`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/heal.mp4" poster="clips/heal.jpg" controls muted loop playsinline preload="none" aria-label="A block whose top is 0.069° off level and whose hole is 0.115° off square is healed (6 faces and 1 hole aligned, largest move 0.0504 mm), and both angles become 0.000°."></video>
<figcaption>A block whose top is 0.069° off level and whose hole is 0.115° off square is healed (6 faces and 1 hole aligned, largest move 0.0504 mm), and both angles become 0.000°.</figcaption>
</figure>

**Steps**

1. Select one or more shapes.
2. Choose SimpleCAD → Modify → Heal to precision.
3. Read the status bar message. It lists how many faces and holes were aligned and the largest vertex move.

**Options**

| Option | What it does |
| --- | --- |
| Precision (Settings) | Only deviations within SimpleCAD → Settings… → Modeling → Precision are corrected (default 0.1 mm). |

**Notes**

- Flat faces become exactly parallel, axis-aligned or coplanar, hole walls become square to their rims, and each vertex moves onto the aligned faces that meet there. Face numbers and colors are kept.
- Through-holes whose wall fell apart into strips and slivers between two flat faces are rebuilt as one cylinder between two exact circles.
- Healing runs in a separate process, so a failure on damaged geometry cannot close FreeCAD.
- The result is applied only if it is valid, changes area and volume no more than the vertex moves allow, and adds no check issues or larger tolerances. Otherwise the shape stays exactly as it was and the message explains why.
- Faces of other curved types, and the vertices they touch, are left unchanged. Parts full of sub-precision slivers are not yet cleaned.
- The change is usually too small to see. The heal is one Undo step.

**See also:** [Make mesh editable](mesh.md#convertmesh) · [Merge coincident geometry](#cleanup) · [Settings](#settings) · [Delete & heal faces](surface.md#healfaces) · [Measure](inspect.md#measure)

## Settings { #settings }

Settings controls the viewport look, whether curved-surface seams are drawn, the modeling precision, and which snap targets are active and how far they reach.

SimpleCAD menu · MCP `simplecad_set_settings`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/settings.mp4" poster="clips/settings.jpg" controls muted loop playsinline preload="none" aria-label="Show seams on curved surfaces is turned on, the endpoint capture distance is raised to 32 px and edge midpoints are toggled; after OK the cylinder&#x27;s seam line appears."></video>
<figcaption>Show seams on curved surfaces is turned on, the endpoint capture distance is raised to 32 px and edge midpoints are toggled; after OK the cylinder&#x27;s seam line appears.</figcaption>
</figure>

**Steps**

1. Choose SimpleCAD → Settings…, or click Settings… in the status bar. No document needs to be open.
2. Change the options.
3. Click OK to save and apply them, or Cancel to discard.

**Options**

| Option | What it does |
| --- | --- |
| Show seams on curved surfaces | Off by default. Draws the seam line where a curved surface such as a cylinder wall joins itself. Circular rims and drawn edges stay visible either way. |
| Dark viewport with ground grid and axes | On by default. Gives every 3D view a dark background, a ground grid that follows the zoom, red, green and blue axes and lights that turn with the camera. The grid and axes cannot be picked or snapped to and are never saved. |
| Face color | The color of faces that have none of their own, #E3E3EC by default. It is never saved in a model. |
| Precision | Default 0.1 mm. Details smaller than this are treated as noise. Used for new mesh conversions, Push/Pull and Heal to precision; models already converted keep their geometry. |
| Snap to | Turn each target on or off: Endpoints (vertices), Edge midpoints, Points on edges and axis crossings, Face and circle centers, Automatic axis alignment, and Push/Pull to faces and edge levels. Turning off midpoint or center snaps also hides that guide. |
| Capture distance | How close the pointer must be, in pixels, to catch each target. Larger values make snapping easier without moving the target. Defaults: 24 px for endpoints, midpoints and Push/Pull, 16 px for edge points, 40 px for centers, and 12 px for axes. |
| Restore Defaults | Resets the fields. Click OK to keep the defaults. |

**Notes**

- Settings are saved with your FreeCAD user preferences, not in the model. They do not edit the model or add an Undo step.
- Seams stay protected from Delete even when they are shown. Deleting a seam-only selection changes nothing.
- Opening Settings finishes the active drawing session but keeps completed lines. Start the next tool to use the new snap settings.
- The status bar's Snap switch still turns all automatic snapping off temporarily, and X/Y/Z key locks work even when automatic axis alignment is off.

**See also:** [Snapping](draw.md#snapping) · [Make mesh editable](mesh.md#convertmesh) · [Heal to precision](#heal) · [Delete](modify.md#delete)

## AI connection (MCP) { #mcp }

AI connection starts a local MCP server so that an AI client such as Codex can inspect your open models and edit them with SimpleCAD's own tools. See docs/MCP.md for setup, the tool list, revision checks and Undo behavior.

SimpleCAD menu
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/mcp.mp4" poster="clips/mcp.jpg" controls muted loop playsinline preload="none" aria-label="The AI connection panel starts the server, turns Allow model changes off (read-only) and back on, copies the Codex setup command, shows the connection details for other clients, and stops the server."></video>
<figcaption>The AI connection panel starts the server, turns Allow model changes off (read-only) and back on, copies the Codex setup command, shows the connection details for other clients, and stops the server.</figcaption>
</figure>

**Steps**

1. Choose SimpleCAD → AI connection (MCP)….
2. Click Start server.
3. Leave Allow model changes on for modeling, or turn it off for inspection only.
4. For Codex, click Copy Codex setup command, run the copied command once in Terminal, then start a new Codex task.
5. For other MCP clients, open Connection details / other MCP clients and click Copy MCP configuration.
6. Close the panel if you like; the server keeps running. Click Stop server to disconnect.

**Options**

| Option | What it does |
| --- | --- |
| Start server, Stop server | Starts or stops the local connection. After restarting FreeCAD, start it again. |
| Allow model changes | When off, the AI client can only inspect. When on, it can edit; model edits support Undo, while settings changes are application preferences. |
| Copy Codex setup command | Copies a codex mcp add command that registers this SimpleCAD folder as the simplecad server. |
| Connection details / other MCP clients | Shows a standard mcpServers entry with the Python command and server script path, and Copy MCP configuration. |

**Notes**

- A connected client can list open documents, inspect objects, faces, edges and meshes, measure, select, capture view images, and draw and edit with the same operations as the toolbar, including mesh conversion and mesh edits, locks, visibility, color and settings.
- Edits go to the named document only and must quote its current model revision, so a client cannot act on an outdated view of the model. Each edit is a normal Undo step and respects locks.
- Edits are refused while a manual SimpleCAD tool, a selection drag or a modal dialog is active. Finish the interaction or press Esc, then retry.
- The server does not save, open, close or export files, and it has no tool to run arbitrary Python or shell commands.
- The connection listens only on this computer (127.0.0.1) and uses a new secret token each time it starts. The client receives the model data and images it requests, and its own data policies apply.
- With several FreeCAD processes running, point the client at one with the --connection option described in docs/MCP.md.
- Reconnect the client after updating SimpleCAD so it sees new tools. Full details are in docs/MCP.md.

**See also:** [Settings](#settings) · [Lock faces and objects](#lock)
