# Surface

The Surface toolbar works on faces of any shape, curved ones included. For a guided tour, see the [user guide](../user-guide.md#curved-surfaces).

## Draw on surface { #imprint }

Draw on surface puts a rectangle, circle, polygon or text onto curved or flat faces. It can split the faces into a new region you can select, or raise or recess the outline by a depth, like a label wrapped around a drum.

![](../../Resources/icons/imprint.svg){ .tool-icon } Surface toolbar · MCP `simplecad_draw_on_surface`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/imprint.mp4" poster="clips/imprint.jpg" controls muted loop playsinline preload="none" aria-label="The word CAD is wrapped onto a drum and raised 1.5 mm, then a 30 by 7 mm rectangle lower down splits the face into a new region, which is left selected."></video>
<figcaption>The word CAD is wrapped onto a drum and raised 1.5 mm, then a 30 by 7 mm rectangle lower down splits the face into a new region, which is left selected.</figcaption>
</figure>

**Steps**

1. Select the faces to draw on, all on one object. Click the face exactly where the drawing should go: that point becomes its centre.
2. Click Draw on surface. A dialog opens and the outline is previewed on the face.
3. Choose the Shape and set its size: width and height, diameter and sides, or the text and its letter height.
4. If needed, turn and shift the drawing with Rotation, Move across and Move up.
5. Choose the Result. For Raise or Recess, set the Depth.
6. Click Draw.

**Options**

| Option | What it does |
| --- | --- |
| Shape | Rectangle (Width, Height), Circle (Diameter), Polygon (Diameter, Sides from 3 to 64) or Text (Text, Letter height, Font). Text uses the font bundled with FreeCAD; click the font button to choose a .ttf, .otf or .ttc file instead. |
| Rotation, Move across, Move up | Turn the drawing about its centre and shift it along the surface away from the point you clicked. |
| Result | Split into a selectable region (the default) divides the faces along the outline. Raise it (emboss) adds the outline as material; Recess it (deboss) cuts it in. |
| Depth | How far a raised drawing stands out or a recessed one sinks in. Shown only for Raise and Recess. |
| Wrap onto the curve, keeping its size | On by default when one curved face is selected. The drawing follows that face like a label and keeps its lengths: a 40 mm rectangle stays 40 mm long around a drum, and raised or recessed drawings follow the face normals. Turned off, the outline is projected straight onto the selected faces and can span several of them. |

**Notes**

- A wrapped drawing must fit on the one face under the click. On a full cylinder it may cross the seam, where its region is split in two, but it cannot run all the way around onto itself.
- A projected drawing marks only faces turned toward it, so the far side of a hole or drum is left alone. If part of the outline runs off the selected faces, the dialog says so; only closed parts of it become regions.
- Raise and Recess need a closed solid.
- After a split, the new regions are selected, ready for Color & opacity, Offset face or Delete.
- Each drawing is one Undo step. If the edit is not possible, the object stays exactly as it was and the status bar says why.

**See also:** [Offset face](#offsetface) · [Unwrap face](#unwrap) · [Delete](modify.md#delete)

## Offset face { #offsetface }

Offset face moves faces of a solid, flat or curved, along their own normals by a distance. It is the Push/Pull for curved faces: a positive distance makes the faces stick out and adds material, a negative one sinks them into the part.

![](../../Resources/icons/offsetface.svg){ .tool-icon } Surface toolbar · MCP `simplecad_offset_faces`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/offsetface.mp4" poster="clips/offsetface.jpg" controls muted loop playsinline preload="none" aria-label="The curved top face of a block is moved 5 mm out along its normals; the side faces do not stretch, so it becomes a raised pad that follows the curve."></video>
<figcaption>The curved top face of a block is moved 5 mm out along its normals; the side faces do not stretch, so it becomes a raised pad that follows the curve.</figcaption>
</figure>

**Steps**

1. Select the faces to move, all on one closed solid.
2. Click Offset face.
3. Enter the Distance. The preview shows the moved edges and the new side walls.
4. Click Offset.

**Options**

| Option | What it does |
| --- | --- |
| Distance | Positive moves the faces outward and adds material; negative moves them inward and cuts into the part. Zero is refused. |

**Notes**

- This is the tool for making one face of a part stick out. Shell does not do that: it hollows the part inward.
- The new side walls run straight along the normals, as with Push/Pull. The neighbouring faces do not stretch to follow, so a curved panel becomes a raised or sunken pad.
- Selecting every face of the solid offsets the whole part, making it larger or smaller all round.
- A face that curves too tightly for the distance, or an offset that cannot join the neighbouring faces cleanly, is refused. Try a smaller distance, or fewer faces at once.
- The object must be a closed solid. It runs in a separate process with a progress window and Cancel, keeps the object where it is, and is one Undo step. If the edit is not possible, the object stays exactly as it was and the status bar says why.

**See also:** [Push/Pull](modify.md#pushpull) · [Shell](#shell) · [Thicken](#thicken)

## Shell { #shell }

Shell hollows a closed solid inward, leaving walls of the thickness you enter. The faces you select are removed, so the part is open there like the top of a box; with no face selected it becomes a closed hollow.

![](../../Resources/icons/shell.svg){ .tool-icon } Surface toolbar (Shell / Thicken) · MCP `simplecad_shell`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/shell.mp4" poster="clips/shell.jpg" controls muted loop playsinline preload="none" aria-label="The top face of a rounded block is selected and the block is hollowed to 3 mm walls, leaving the top open."></video>
<figcaption>The top face of a rounded block is selected and the block is hollowed to 3 mm walls, leaving the top open.</figcaption>
</figure>

**Steps**

1. Select the faces to leave open, all on one closed solid. For a closed hollow, select the whole object instead.
2. Click Shell / Thicken. With a solid selected, the dialog is called Shell and the faces to open are outlined.
3. Enter the Wall thickness.
4. Click Hollow.

**Options**

| Option | What it does |
| --- | --- |
| Wall thickness | The thickness of the walls that remain, measured inward from the outside faces. The outside size of the part does not change. It is not a distance to move a face. |

**Notes**

- The selected faces are the ones removed, not the ones made thicker. Shell never makes a face stick out; for that, use Offset face, or Push/Pull on a flat face.
- The wall has to fit inside the part with room left for the hollow. Choose a wall thinner than the part's thinnest section; where two opposite faces both stay closed, less than half the distance between them. A part that is already thin cannot take a thick wall: a 100 mm wall on a part a few millimetres thick is refused with "The kernel could not hollow this part with a 100 mm wall."
- Shell works on parts made of flat faces, cylinders and simple curves. On surfaces fitted to a mesh it usually fails, and so does opening a face that a round blends into. Try a thinner wall, or remove small rounds first with Remove rounds.
- Leave at least one face closed, and shell one solid at a time. An object with loose faces or openings is refused.
- When the selected object is a surface (faces with no solid inside), the same button opens Thicken instead.
- It runs in a separate process with a progress window and Cancel, keeps the object where it is, and is one Undo step. If the edit is not possible, the object stays exactly as it was and the status bar says why.

**See also:** [Thicken](#thicken) · [Offset face](#offsetface) · [Remove rounds](#removerounds)

## Thicken { #thicken }

Thicken turns a surface object, made of faces with no solid inside, into a solid wall of the thickness you enter. It shares the Shell / Thicken button, which opens Thicken whenever the selected object is a surface.

![](../../Resources/icons/shell.svg){ .tool-icon } Surface toolbar (Shell / Thicken) · MCP `simplecad_shell`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/thicken.mp4" poster="clips/thicken.jpg" controls muted loop playsinline preload="none" aria-label="A curved panel with no thickness is selected whole and thickened into a 4 mm solid, after trying the Grow options in the preview."></video>
<figcaption>A curved panel with no thickness is selected whole and thickened into a 4 mm solid, after trying the Grow options in the preview.</figcaption>
</figure>

**Steps**

1. Select the surface object, or any face of it. Thicken always uses the whole object.
2. Click Shell / Thicken. The dialog is called Thicken, and the preview shows where the new wall will be.
3. Enter the Thickness and choose which side to Grow.
4. Click Thicken.

**Options**

| Option | What it does |
| --- | --- |
| Thickness | The thickness of the new solid wall, measured along the face normals. The surface itself stays where it is; material is added beside it. |
| Grow | In front, along the face normals (the default); Behind the faces; or Both sides, half each. Watch the preview to see which side is which. |

**Notes**

- Thicken works on objects that have faces but no solid, such as an open surface or an Unwrap face result. A solid is refused with "This is already a solid. Use Shell to hollow it."
- To hollow a solid, use Shell. To make one face of a solid stick out, use Offset face.
- If the surface cannot be offset that far, for example toward the inside of a tight curve, it is refused. Try a smaller thickness or the other side.
- The surface object becomes the solid; Undo brings the surface back. It runs in a separate process with a progress window and Cancel, keeps the object where it is, and is one Undo step. If the edit is not possible, the object stays exactly as it was and the status bar says why.

**See also:** [Shell](#shell) · [Offset face](#offsetface) · [Unwrap face](#unwrap) · [Fill hole](#fillhole)

## Draft faces { #draft }

Draft faces tilts flat or round side walls of a solid by a small angle, so a moulded or cast part releases from its mould. The walls pivot about a hinge plane, and the part gets narrower toward one end.

![](../../Resources/icons/draft.svg){ .tool-icon } Surface toolbar · MCP `simplecad_draft_faces`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/draft.mp4" poster="clips/draft.jpg" controls muted loop playsinline preload="none" aria-label="The four side walls of a block are drafted 10° about a hinge at the bottom, so the block narrows toward the top."></video>
<figcaption>The four side walls of a block are drafted 10° about a hinge at the bottom, so the block narrows toward the top.</figcaption>
</figure>

**Steps**

1. Select the side walls to tilt, all on one closed solid.
2. Click Draft faces. The preview shows the hinge plane as a frame and the pull direction as an arrow.
3. Set the Angle, Pull direction, Hinge and Taper.
4. Click Draft.

**Options**

| Option | What it does |
| --- | --- |
| Angle | How far each wall tilts, from 0.01° to 89.9°. The default is 3°. |
| Pull direction | World Z (up), World X or World Y: the direction the part leaves the mould. The hinge plane is square to it, and the top is the end it points to. |
| Hinge | At the bottom of the faces (the default) or at the top. The walls stay in place where they cross this plane. |
| Taper | Narrower toward the top (the default) or narrower toward the bottom. |

**Notes**

- Draft works on flat, cylindrical and conical faces. Free-form curved faces, and faces square to the pull direction such as a top face, are refused in the dialog.
- Rounds that blend into a drafted wall must be drafted with it or removed first with Remove rounds. If the faces cannot be drafted about the hinge, try the other hinge or a smaller angle.
- It runs in a separate process with a progress window and Cancel, keeps the object where it is, and is one Undo step. If the edit is not possible, the object stays exactly as it was and the status bar says why.

**See also:** [Remove rounds](#removerounds) · [Offset face](#offsetface)

## Delete & heal faces { #healfaces }

Delete & heal faces removes selected faces of a solid, such as a boss, a pocket, a hole or a round, and grows the neighbouring faces until the solid is closed again. Use it to take a feature off a part, including an imported one.

![](../../Resources/icons/healfaces.svg){ .tool-icon } Surface toolbar · MCP `simplecad_heal_faces`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/healfaces.mp4" poster="clips/healfaces.jpg" controls muted loop playsinline preload="none" aria-label="A boss is removed from a plate by selecting its wall and top, then a hole is closed by selecting its wall."></video>
<figcaption>A boss is removed from a plate by selecting its wall and top, then a hole is closed by selecting its wall.</figcaption>
</figure>

**Steps**

1. Select the faces to remove, all on one closed solid. For a boss, select its wall and its top; for a hole, its wall.
2. Click Delete & heal faces. There is no dialog; the edit starts at once.

**Notes**

- The neighbouring faces must be able to grow until they meet. Faces they cannot close stay in place and are counted in the message; if none can be removed, nothing changes.
- The status bar gives the number of faces removed and the face count before and after.
- The object must be a closed solid, and at least one face must remain. Plain Delete opens the shape instead of healing it.
- It runs in a separate process with a progress window and Cancel, keeps the object where it is, and is one Undo step. If the edit is not possible, the object stays exactly as it was and the status bar says why.

**See also:** [Remove rounds](#removerounds) · [Smart select](inspect.md#smartselect) · [Delete](modify.md#delete)

## Remove rounds { #removerounds }

Remove rounds finds rounded edges (fillets) up to a radius and removes them, so the corners are sharp again. Use it to simplify a part, or before Draft or Shell, which often fail on small rounds.

![](../../Resources/icons/removerounds.svg){ .tool-icon } Surface toolbar · MCP `simplecad_remove_rounds`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/removerounds.mp4" poster="clips/removerounds.jpg" controls muted loop playsinline preload="none" aria-label="With the largest radius at 5 mm only the 3 mm top rounds of a block are found (10 mm also catches its 8 mm corners); removing them leaves sharp top edges."></video>
<figcaption>With the largest radius at 5 mm only the 3 mm top rounds of a block are found (10 mm also catches its 8 mm corners); removing them leaves sharp top edges.</figcaption>
</figure>

**Steps**

1. Select the solid, or some of its faces to search only those.
2. Click Remove rounds. The rounds found are highlighted, and the dialog gives their number and radius range.
3. Set the Largest radius and choose Which rounds.
4. Click Remove.

**Options**

| Option | What it does |
| --- | --- |
| Largest radius | Rounds with this radius or smaller are found. The default is 5 mm. |
| Which rounds | Outside and inside rounds (the default), Outside rounds (convex) only, or Inside rounds (concave) only. |

**Notes**

- A round is part of a cylinder less than half a turn, a torus, part of a sphere, or a free-form face curved tightly in one direction with about the same radius everywhere, as fitted rounds of converted meshes are. Holes and bosses are not rounds.
- The highlighted faces are removed and their neighbours extended until they meet in a sharp edge. Rounds that cannot be removed stay and are counted in the message.
- When nothing matches, the dialog says "No rounds up to this radius found." and Remove is unavailable.
- It runs in a separate process with a progress window and Cancel, keeps the object where it is, and is one Undo step. If the edit is not possible, the object stays exactly as it was and the status bar says why.

**See also:** [Round edges](modify.md#round) · [Delete & heal faces](#healfaces) · [Draft faces](#draft) · [Curvature map](inspect.md#curvature)

## Fill hole { #fillhole }

Fill hole closes the openings of an open surface with patches that blend smoothly into the faces around them. When no openings are left, the surface becomes a solid.

![](../../Resources/icons/fillhole.svg){ .tool-icon } Surface toolbar · MCP `simplecad_fill_holes`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/fillhole.mp4" poster="clips/fillhole.jpg" controls muted loop playsinline preload="none" aria-label="A tube with a curved, open top is closed with a smooth patch, and the closed surface becomes a solid."></video>
<figcaption>A tube with a curved, open top is closed with a smooth patch, and the closed surface becomes a solid.</figcaption>
</figure>

**Steps**

1. Select the open surface object, or the rim edges of the openings to fill.
2. Click Fill hole. The rims to be closed are highlighted and counted.
3. Leave Blend smoothly on for a patch that meets the faces around it smoothly.
4. Click Fill.

**Options**

| Option | What it does |
| --- | --- |
| Blend smoothly into the neighbouring faces | On by default. A curved opening gets a patch tangent to the faces around it. Flat openings always get a flat face, whatever this setting. |

**Notes**

- Without rim edges selected, every opening is filled. One rim edge is enough to choose its opening.
- A flat opening keeps flat islands inside it open.
- Refused: a patch that would cut through the part, a curved opening with another opening inside it, and a rim that crosses itself. A closed solid has nothing to fill.
- The message says how many openings were filled and whether the object is now a closed solid. It runs in a separate process with a progress window and Cancel, keeps the object where it is, and is one Undo step. If the edit is not possible, the object stays exactly as it was and the status bar says why.

**See also:** [Thicken](#thicken) · [Delete & heal faces](#healfaces) · [Shell](#shell)

## Unwrap face { #unwrap }

Unwrap face flattens one face into a new flat face beside the part, for a template, a label or a cut sheet. The part itself does not change.

![](../../Resources/icons/unwrap.svg){ .tool-icon } Surface toolbar · MCP `simplecad_unwrap_face`
{ .tool-facts }

<figure class="tool-clip">
<video src="clips/unwrap.mp4" poster="clips/unwrap.jpg" controls muted loop playsinline preload="none" aria-label="The side of a cone-shaped lampshade is unwrapped into a flat, arc-shaped strip beside the unchanged part."></video>
<figcaption>The side of a cone-shaped lampshade is unwrapped into a flat, arc-shaped strip beside the unchanged part.</figcaption>
</figure>

**Steps**

1. Select one face.
2. Click Unwrap face. There is no dialog.
3. The flat face appears beside the part, selected, and the status bar gives its size.

**Notes**

- The flat face is a new object named after the part and the face, such as Part Face1 unwrapped. It lies on the XY plane, at the +X side of the part.
- The outline is a fine polygon. A cylinder or cone unrolls with almost no stretch; a doubly curved face has to stretch a little, and the message gives the area change.
- An outline that would cross itself is refused; split the face first, for example with Draw on surface.
- The result is a surface object, so Thicken can turn it into a solid plate. Creating it is one Undo step.

**See also:** [Thicken](#thicken) · [Draw on surface](#imprint)
