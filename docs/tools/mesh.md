# Mesh

The green Mesh tools edit imported STL meshes, or turn them into editable CAD parts. For a guided tour, see the [user guide](../user-guide.md#meshes-stl).

## Make mesh editable { #convertmesh }

Make mesh editable rebuilds an imported STL mesh as CAD faces that you can select and edit with the modeling tools. The original mesh stays in the document as a hidden backup.

![](../../Resources/icons/convertmesh.svg){ .tool-icon } Mesh toolbar · MCP `simplecad_convert_mesh`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/convertmesh.mp4" poster="clips/convertmesh.jpg" controls muted loop playsinline preload="none" aria-label="A 688-triangle bracket mesh is converted with Fit smooth surfaces into 7 editable faces (2 flat, 5 smooth), the mesh is kept hidden, and the top face and the hole wall are selected from the Faces tab."></video>
<figcaption>A 688-triangle bracket mesh is converted with Fit smooth surfaces into 7 editable faces (2 flat, 5 smooth), the mesh is kept hidden, and the top face and the hole wall are selected from the Faces tab.</figcaption>
</figure>

**Steps**

1. Select the mesh's (mesh) row in the Faces tab, or leave only one mesh visible with nothing selected.
2. Click Make mesh editable on the Mesh toolbar. It is also in SimpleCAD → Mesh and in the row's right-click menu.
3. Check the Surface / repair tolerance and choose whether to fit smooth surfaces.
4. Click Convert. The panel shows progress while the conversion runs in the background.
5. Read the summary and click Close. Expand the new (editable) object in the Faces tab to select its faces.

**Options**

| Option | What it does |
| --- | --- |
| Surface / repair tolerance | Starts at the modeling precision from Settings (default 0.1 mm). Details smaller than this are treated as noise: nearby vertices merge, and nearly flat, parallel, axis-aligned or coplanar surfaces become exact. It is a distance, not a target face count. |
| Fit smooth surfaces (fewest faces) | On by default and remembered. Flat regions become planes, round holes and bosses become analytic cylinders, and other curved regions become smooth B-spline faces, split at sharp edges. Every mesh vertex stays within the tolerance of its face. When it is off, flat triangles merge into planar faces and other curved regions stay faceted; complete closed cylinders and verified through-holes still become analytic. |
| Reduce triangles for faster editing | Optional extra simplification of components that are not fitted, controlled by Simplification tolerance (default 0.01 mm). The source mesh is never changed. |

**Notes**

- Conversion runs in a separate process. Cancel or a failure leaves the document unchanged.
- After success the original mesh is hidden. Click its eye to compare. One Undo removes the new object and shows the mesh again.
- Closed components become solids, with cavities kept. Open meshes become editable surfaces, with a warning.
- Invalid or non-manifold input is refused. Repair it first, for example in FreeCAD's Mesh Design workbench.
- The limits are 100,000 triangles, 64 components and five minutes per conversion. Larger models take longer.
- A component whose fit, trimming, joining or volume check fails falls back to the flat-face rebuild, with a warning. No triangles are silently deleted.
- Fitted faces are ordinary Part geometry, but Push/Pull and other flat-face tools work only on the flat ones.
- To edit the mesh as triangles instead, use Split mesh, Stretch mesh or Mesh region; they need no conversion.

**See also:** [Split mesh](#meshsplit) · [Stretch mesh / Move region](#meshstretch) · [Mesh region · Move / Rotate / Extrude](#meshregion) · [Fit Circle / Cylinder](modify.md#analytic) · [Faces and Objects panels](panels.md#facespanel) · [Settings](panels.md#settings)

## Split mesh { #meshsplit }

Split mesh cuts an STL mesh into two mesh objects along a plane, without converting it to CAD faces. Use it to cut a model into pieces that print or fit separately.

![](../../Resources/icons/meshsplit.svg){ .tool-icon } Mesh toolbar · MCP `simplecad_split_mesh`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/meshsplit.mp4" poster="clips/meshsplit.jpg" controls muted loop playsinline preload="none" aria-label="A 1,708-triangle handle is cut across X 8.4 mm from its center with an 8 mm gap; the preview shows the two sides in blue and orange, and Apply creates two mesh objects."></video>
<figcaption>A 1,708-triangle handle is cut across X 8.4 mm from its center with an 8 mm gap; the preview shows the two sides in blue and orange, and Apply creates two mesh objects.</figcaption>
</figure>

**Steps**

1. Select one mesh object, or leave only one mesh visible with nothing selected.
2. Click Split mesh on the Mesh toolbar. It is also in SimpleCAD → Mesh and in the row's right-click menu.
3. In Cut across, choose an axis. The cut plane is perpendicular to it.
4. Drag the slider or type Offset from center to place the plane.
5. Optionally set Gap between sides, or turn on Triangular glue seam.
6. Click Preview split. The two sides show in blue and orange.
7. Click Apply.

**Options**

| Option | What it does |
| --- | --- |
| Cut across | Object main axis (the dominant length direction), world X, Y or Z, or object local X, Y or Z. |
| Offset from center | The plane position in millimeters from the mesh center along the axis. |
| Close cut surfaces | On by default. Adds triangles across the cut so that closed input gives closed pieces. |
| Triangular glue seam | Adds a raised ridge on one side and a matching V-shaped groove on the other to align glued parts. Maximum depth (default 2 mm) limits the groove, Glue clearance (default 0.15 mm) lowers the ridge along the split axis, and Swap ridge and groove reverses the sides. Requires a closed mesh and turns on Close cut surfaces. |
| Gap between sides | Moves the two results apart by this distance. Zero keeps them touching. |

**Notes**

- Only triangles crossed by the plane are split. The rest of the mesh keeps its detail and is not converted to CAD.
- Each side is an ordinary Mesh object that you can export as STL. A side can contain several disconnected islands.
- The original mesh stays as a hidden backup. One Undo removes both results and restores it. Cancel leaves the document unchanged.
- The calculation runs in a cancellable background process, limited to 500,000 triangles and five minutes.
- Non-manifold edges and inconsistent normals need repair first. Existing open surfaces stay open, and existing defects are not repaired.
- If the cut runs through a branching or self-intersecting boundary, move the plane slightly or turn off Close cut surfaces.
- A glue groove that breaks through the remaining wall is refused. Reduce the depth, swap the sides or move the cut.
- Meshes inside Part containers must be moved out first. Slice / Separate opens this panel when a mesh is selected.

**See also:** [Slice / Separate](modify.md#slice) · [Stretch mesh / Move region](#meshstretch) · [Mesh region · Move / Rotate / Extrude](#meshregion) · [Make mesh editable](#convertmesh)

## Stretch mesh / Move region { #meshstretch }

Stretch mesh lengthens or shortens an STL mesh between two planes while both ends keep their shape. Use it to change a part's length without distorting the holes or mounts at its ends.

![](../../Resources/icons/meshstretch.svg){ .tool-icon } Mesh toolbar · MCP `simplecad_stretch_mesh`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/meshstretch.mp4" poster="clips/meshstretch.jpg" controls muted loop playsinline preload="none" aria-label="On a 1,436-triangle strap with two holes, the second plane is dragged about 5 mm inward and Length change is set to 20 mm; after Apply the holes at both ends keep their size."></video>
<figcaption>On a 1,436-triangle strap with two holes, the second plane is dragged about 5 mm inward and Length change is set to 20 mm; after Apply the holes at both ends keep their size.</figcaption>
</figure>

**Steps**

1. Select one mesh object.
2. Click Stretch mesh / Move region on the Mesh toolbar or in the row's right-click menu.
3. Choose an Axis.
4. Place the First plane and Second plane around the section to stretch. Drag the plane frames or their labeled handles in the view, or type the positions.
5. Enter Length change: a positive value extends and a negative value shortens.
6. Check the preview. Blue stays fixed, orange moves rigidly, and only the section between the planes deforms.
7. Click Apply.

**Options**

| Option | What it does |
| --- | --- |
| Operation | Stretch along axis, or Move end region (XYZ) to shift the moving end sideways as well, using the Move X, Y and Z fields. |
| Axis | Object main axis, world X, Y or Z, or object local X, Y or Z. Choosing a new axis resets the rotation and plane positions. |
| First plane, Second plane | Signed positions in millimeters from the common origin along the axis. |
| Drag in view | Move planes drags the frames and handles. Rotate both planes shows X, Y and Z rings that tilt both planes together. |
| Plane rotation | Typed X, Y and Z angles, applied in world X, then Y, then Z order. The planes stay parallel and keep their spacing. |
| Move negative side instead | Swaps which end stays fixed. |
| Length change | How much longer (positive) or shorter (negative) the part becomes. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Shift</kbd> | While dragging a rotation ring, snap the angle to 15° steps. |

**Notes**

- Keep holes and mounts outside the section between the planes if their dimensions must stay the same.
- Only triangles that cross the two planes are subdivided, so the triangle count can rise. There is no remeshing and no conversion to CAD faces.
- While you drag a handle, the preview reuses the original triangles. Releasing refines the cuts, and Apply always uses the refined result.
- Apply checks the result in a cancellable background process, creates a new mesh and hides the original. One Undo restores it. Moving the planes and Cancel never change the source.
- Shortening that collapses or reverses the middle is refused, as are newly collapsed facets. Existing defects are not repaired, and open input stays open.
- It works on independent mesh objects outside containers, up to 500,000 triangles.
- If a rotated plane leaves the mesh, switch back to Move planes and drag it inside before applying.

**See also:** [Mesh region · Move / Rotate / Extrude](#meshregion) · [Split mesh](#meshsplit) · [Scale / Stretch](modify.md#scale) · [Bend / Soft Deform](modify.md#deform)

## Mesh region · Move / Rotate / Extrude { #meshregion }

Mesh region edits a patch of an STL mesh directly. Click a flat or smooth patch, then move it, rotate it, or extrude it with new side walls, with a live preview.

![](../../Resources/icons/meshregion.svg){ .tool-icon } Mesh toolbar · MCP `simplecad_edit_mesh_region`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/meshregion.mp4" poster="clips/meshregion.jpg" controls muted loop playsinline preload="none" aria-label="The flat top of a pad on a mesh block is clicked, previewed moved 6 mm up, then extruded 8 mm instead; Apply creates a new mesh object."></video>
<figcaption>The flat top of a pad on a mesh block is clicked, previewed moved 6 mm up, then extruded 8 mm instead; Apply creates a new mesh object.</figcaption>
</figure>

**Steps**

1. Select one mesh object.
2. Click Mesh region · Move / Rotate / Extrude on the Mesh toolbar or in the row's right-click menu.
3. Click a patch in the view. It turns orange and the panel shows how many triangles are selected.
4. Shift-click to add more patches, or use Grow and Shrink to adjust the selection.
5. Choose an Operation. For Move, type the X, Y and Z displacement. For Rotate, type an angle and choose the axis. For Extrude, type a signed distance.
6. Check the preview, then click Apply.

**Options**

| Option | What it does |
| --- | --- |
| Select patch | Flat picks connected coplanar triangles. Smooth crosses edges up to the Smooth crease angle (15° by default). Triangle picks a single triangle. |
| Pick action | Replace, Add to or Remove from the selection when you click. |
| Grow, Shrink, Clear | Expand or reduce the selection at its boundary, or clear it. |
| Operation | Move, Rotate or Extrude. |
| Transition rings | For Move and Rotate. 1 keeps every unselected vertex fixed; higher values spread the movement over that many rings of neighboring vertices. The selected patch always moves rigidly. |
| Direction / rotation axis | Region normal (the default), World X, World Y or World Z. Choose a world axis when the average normal of the patch cancels out. |
| Use custom rotation pivot | Rotates about the typed Pivot X, Y and Z world coordinates. |
| Extrusion distance | A signed distance along the chosen direction. |

**Keys**

| Key | What it does |
| --- | --- |
| <kbd>Shift-click</kbd> | Add the clicked patch to the selection. |

**Notes**

- Move and Rotate reuse the existing triangles. Extrude replaces the patch with a moved cap and adds side walls along its boundary, including around holes. It does not cut through other surfaces.
- An entire closed component cannot be extruded. Select a smaller patch.
- Smooth selection can spread around a whole curved wall. Lower the crease angle to stop it sooner.
- While you edit, triangles that would intersect other parts of the mesh turn red. This is an estimate; Apply runs its own check.
- Apply checks the mesh in a cancellable background process. It refuses self-intersections, collapsed triangles, branched extrusion boundaries and inverted closed shells introduced by the edit.
- Apply creates a new mesh and hides the original. One Undo restores the previous state, and Cancel discards the preview.
- Existing non-manifold meshes need repair first, and existing open boundaries stay open. Up to 500,000 triangles are supported.

**See also:** [Stretch mesh / Move region](#meshstretch) · [Split mesh](#meshsplit) · [Push/Pull](modify.md#pushpull) · [Make mesh editable](#convertmesh)
