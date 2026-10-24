# Connect SimpleCAD to an AI client

SimpleCAD includes a local MCP server with 76 tools for inspecting open models and using the same modeling operations as the toolbar. It runs with FreeCAD's bundled libraries and a normal Python 3.9+ interpreter for the MCP client process; no pip packages are required.

## Start the connection

1. Start FreeCAD and choose **SimpleCAD**. After installing or updating SimpleCAD, restart FreeCAD first.
2. Open **SimpleCAD → AI connection (MCP)…** and click **Start server**.
3. Leave **Allow model changes** checked for modeling, or turn it off for inspection only.
4. Close the panel if desired. The connection stays active across workbench changes. **Stop server** disconnects it; restarting FreeCAD requires starting it again.

The server can see all open documents, including hidden objects and faces. It only changes the explicitly named active document. It refuses model edits while a manual SimpleCAD tool, selection drag or modal dialog is active. Finish the interaction or press Esc, then retry.

## Codex setup

Use **Copy Codex setup command** in the panel, paste it into Terminal, and run it once. It registers this addon location as the `simplecad` server. The command has this form:

```sh
codex mcp add simplecad -- python3 "/absolute/path/to/SimpleCAD/scripts/simplecad_mcp.py"
```

Start a new Codex task so it can load the added tools. Keep this addon folder in place. If it moves, update the MCP command to the new location. To remove the connection from Codex, run `codex mcp remove simplecad`.

Codex supports local stdio servers and the `codex mcp add` setup command. Its client controls tool approvals independently of SimpleCAD's **Allow model changes** switch. See the [official Codex MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

Try asking:

> Inspect the model open in SimpleCAD. List its objects and describe which faces are flat, without changing anything.

Or:

> Create a new SimpleCAD document with a 30 × 20 × 10 mm block. Add a circle of radius 3 mm at the center of its top face and pull it up 5 mm. Show me the result.

A running server is not needed for Codex to discover the tool list. Model calls explain how to start it if FreeCAD is disconnected.

## Other MCP clients and multiple FreeCAD instances

Expand **Connection details / other MCP clients**, then use **Copy MCP configuration**. It provides a standard `mcpServers` entry with a Python command and the absolute server script path. The client launches that process using stdio; the internal localhost bridge URL is not a Streamable HTTP MCP endpoint.

Automatic discovery succeeds only when one SimpleCAD server is running. With multiple FreeCAD processes, add `--connection` followed by the connection file shown in the intended FreeCAD panel to the MCP server's arguments. This chooses one process explicitly. A connected client stays bound to that process and does not silently switch models when a server stops. Restart the MCP client after restarting the FreeCAD server.

## Available tools

All tool names start with `simplecad_`. Dimensions are millimeters, areas mm², volumes mm³ and angles degrees. Tool schemas describe required arguments and supported choices.

| Tools | Behavior |
| --- | --- |
| `list_documents`, `inspect_document`, `inspect_object` | Open documents, internal names, labels, model revision, shape counts, bounds, placement, validity and visibility |
| `inspect_elements` | Paged faces, edges or vertices; areas, centers, planar normals, edge midpoints, coordinates and adjacency |
| `measure` | One element or two: hole diameter, center and axis (faceted holes are fitted), center spacing and wall between holes, distance and angle between faces, point distances and XYZ delta; a curved face's bend (convex, concave or saddle) and its tightest and gentlest radius. Changes nothing |
| `expand_selection` | Grow a face or edge into its whole hole or cylinder wall, edge loop, flat region or smooth surface; returns and optionally selects the names. Changes nothing |
| `get_selection`, `select` | Read, replace, add or clear native object/face/edge/vertex selection |
| `create_document`, `activate_document` | Create an unsaved model or explicitly switch to an already-open one |
| `create_rectangle`, `create_circle`, `create_polygon`, `create_line` | Exact drawing coordinates and planes; split existing face regions; create connected lines by repeating endpoints. Each optionally follows a CAD surface with `support` and `surface_face` |
| `create_arc`, `create_2_point_arc` | Planar analytic arcs or native surface curves; center/start/signed sweep, or endpoints/signed bulge; optional `support` and `surface_face` |
| `create_sphere` | World-space center (`origin`) and positive radius; creates a separate complete solid |
| `offset` | Face/edge offset by signed mm; face regions or unfilled copied curves |
| `move_vertex` | Move one VertexN by a world-space `delta: [dx, dy, dz]` in mm; deform adjoining polygon faces |
| `push_pull` | Signed face extrusion, pockets and opposite-face contact behavior |
| `move`, `copy`, `rotate` | Whole-object transforms, including local axes and the principal object axis |
| `mirror` | Mirror whole objects along X, Y or Z, as a mirrored copy by default or in place |
| `round_edges` | Native edge fillets, selected face boundaries or whole-solid edges |
| `subdivide` | Triangle divisions, center fans, circular radial sectors, spaced grids and equal-area grids |
| `slice`, `fit_test` | Plane slices, separation gaps, optional studs/sockets and a separate clearance-test model |
| `intersect_faces` | Split selected crossing faces into regions and combine their owners; retains surfaces for subsequent deletion |
| `union`, `cleanup`, `delete` | Native solid union, coincident-geometry cleanup, or object/face/edge deletion |
| `heal` | Align faces and holes of the named shapes to the modeling precision in an isolated worker; per-object reports, unchanged shapes include the reason |
| `draw_on_surface` | Project a rectangle, circle, polygon or text onto curved or flat faces, or with `wrap` lay it onto one face like a label keeping its lengths; split them (returns the new region face names) or raise/recess the outline by `depth` |
| `offset_faces` | Move flat or curved faces of a closed solid along their own normals by a signed `distance`: the curved Push/Pull |
| `shell` | Hollow a closed solid to a wall `thickness` with the named faces left open, or thicken a surface object into a solid on its `front`, `back` or `both` sides |
| `draft_faces` | Tilt flat, cylindrical or conical faces by `angle` degrees about a hinge plane square to world X, Y or Z |
| `heal_faces` | Delete faces of a closed solid and grow the neighbours to close it; faces that cannot heal stay and are counted |
| `find_rounds`, `remove_rounds` | List fillet faces up to `max_radius` (convex, concave or any), or remove them so the corners are sharp again. `find_rounds` changes nothing |
| `fill_holes` | Close all openings of a surface, or those whose rim `edges` are given; smooth patches by default; a closed result becomes a solid |
| `unwrap_face` | Flatten one face into a new flat face object beside the source; returns the area change |
| `pattern` | Independent copies of whole objects in a `grid`, `radial` around an axis, or along a `path` of edges; counts include the original |
| `set_locked` | Lock/unlock faces or whole objects; inspect object `locked`, `locked_faces` and `lock_references_stale`, or face `locked` |
| `set_visibility` | Set face/object eye states without changing the geometry |
| `set_appearance` | Set face/object RGB color and/or opacity (0–100%) in one Undo step |
| `get_settings`, `set_settings` | Snap distances/switches, curved-surface seam display, the dark viewport style (`viewport_style`) and its face color (`face_color`, `#RRGGBB`) |
| `view`, `capture_view` | Standard camera directions, Fit All and viewport images |
| `undo`, `redo` | One native document transaction |

`create_line` keeps its straight 3D behavior by default. Add `support` (the
internal Part object name) and `surface_face` (`FaceN`) to draw a face-following
curve between the world-space `start` and `end` points. Both endpoints must be
on that underlying surface; the whole curve must fit its trimmed faces without
crossing holes. Connected curves can close regions across existing divisions or
a periodic seam. The route is straight in the surface's parameters, not a
geodesic. Each segment is one Undo step. Read the returned `divided_face` flag
and re-inspect face numbers after a split. Restart FreeCAD and reconnect clients
to discover the added argument.

The GUI Draw: Plane / Draw: Surface selector does not affect MCP calls;
`surface_face` explicitly selects surface drawing. These MCP routes retain their
original single-underlying-surface UV mapping. The newer GUI connected-skin wrap
uses a separate cached development; it is not silently enabled for existing MCP
calls. Crossing different underlying surfaces through MCP is not exposed yet.

`create_rectangle`, `create_circle`, `create_polygon`, `create_arc` and
`create_2_point_arc` also accept `support` and `surface_face`. Without the face
argument their planar behavior is unchanged. With it, `origin` (or the first
`start` for a 2 Point Arc) is a world-space point on the surface. Dimensions,
radius, angle and bulge use an orthogonal local frame in mm at that point.
`x_direction` for Rectangle/Circle/Polygon is projected onto the tangent plane;
the normal comes from the face, regardless of an optional planar `normal`.
Arc `start` and 2 Point Arc `end` remain world-space points on that surface.
On cylinders the frame unrolls the wall exactly. Other surfaces can distort
larger profiles away from the anchor; these are not geodesic shapes. Closed
profiles split the existing object, never create an overlapping filled disk.
Incomplete arcs stay loose native curves and can close regions with Line.
Holes, trims, singular poles and full periodic wraps are checked before writing.
All curves are native surface curves, with one Undo transaction per operation;
re-inspect element numbers after a split. Restart FreeCAD and reconnect clients
to refresh the argument schemas.

`offset` requires `object`, `element` (`FaceN` or `EdgeN`) and signed `distance` in mm. Positive expands faces, circles and arcs; negative shrinks. Straight edges additionally require a plane `normal` perpendicular to the line; positive moves along `normal × start-to-end`, using the edge's curve parameter direction. Face and circular-edge planes come from the source, regardless of the optional normal. Face offsets preserve regions, imprinted boundaries, locks and native materials. An extension beyond a solid creates a separate border surface. Edge offsets stay unfilled curves, even if they meet other edges. Returns `objects`; re-inspect face numbers after edits. Supported sources are flat faces, straight edges and circular arcs/circles.

`create_arc` requires `origin` (center), `start` (radius start point) and `sweep` (signed degrees). `create_2_point_arc` requires `start`, `end` and `bulge` (signed mm from chord midpoint to arc midpoint). Both accept `normal` (default +Z) and optional `support`. Start/end must lie in that plane. Positive sweep is counterclockwise from +normal; positive bulge lies left of the start-to-end chord. Sweep excludes zero and ±360°; bulge excludes zero. Arcs are native circular edges and can complete closed arc/line faces or split a support. Responses include `divided_face`; inspect elements again after a split. The same transaction, lock and material-preservation rules as Line apply.

Spheres use `origin` as their world-space center and a positive `radius` in mm. They create a separate closed solid without modifying intersecting objects. They do not take a plane or `support`; use `union` explicitly to combine objects.

Rectangles use `origin` as their first corner; circles and polygons use it as the center. The default plane normal is +Z. Its x direction is projected world X, or world Y when the normal is parallel to X. Supply `x_direction` to choose another orientation. An optional `support` is the internal name of a host object to divide. Geometry is still checked for coplanarity and containment. Polygon radius reaches a vertex, not a side.

`subdivide` uses `rows`/`columns` for `grid` and `equal_area`; `divisions` controls `triangles`, `fan` and `radial`. Circular faces use the existing fan operation for radial sectors. `slice` uses an offset from the combined bounding center along the chosen plane normal, and separates each side by half the requested total gap.

The curved-surface edits (`draw_on_surface`, `offset_faces`, `shell`, `draft_faces`, `heal_faces`, `remove_rounds`, `fill_holes`, `unwrap_face`) run the kernel in an isolated worker process and wait for it without a progress window, so FreeCAD does not respond until they finish. The object keeps its Placement; each edit is one Undo step, and a refused edit leaves the object unchanged. `draw_on_surface` centres the outline at `point` (world mm), or else at a point of the first face far from its edges; only faces turned toward the outline are marked. With `wrap`, the outline is unrolled onto the one face under `point` through a flattened copy of that face, so a 40 mm label stays 40 mm around a cylinder, and emboss/deboss follow the face normals; it must fit on that face, may cross the seam of a closed face such as a full cylinder, and is refused when it would run around onto itself. `offset_faces` builds a slab along each face's normals and adds it (positive) or cuts it (negative); the side walls run straight along the normals and neighbouring faces do not stretch, so it suits raising or sinking a patch rather than resizing a blended part. Offsetting every face offsets the whole part. `shell` uses the kernel's thick-solid operation; it is refused where the kernel cannot offset every face, which is common on B-spline surfaces fitted to a mesh. `draft_faces` runs a PartDesign Draft in a hidden temporary document inside the worker; free-form faces, faces square to the pull, and walls blended into rounds that are not drafted with them are refused. Face and edge numbers change after these edits; inspect again.

The MCP interface supplies exact values directly. It does not simulate mouse dragging, snapping gestures or dialog sliders. The same native operations and restrictions apply: for example, Push/Pull requires a flat face, and linked/parametric features may need a Part simple copy.

## Mesh region editing

Raw meshes do not need CAD conversion for this workflow:

`get_selection` also reports an active Mesh region dialog's source object,
1-based selected triangle numbers (up to 1,000, with `total` and `truncated`),
world-space operation parameters, and validation error. This read-only snapshot
does not close the dialog, change its preview, or alter the document. Normal
FreeCAD selection remains in `targets`; the dialog state is in `mesh_region`.

1. `inspect_mesh_triangles` returns a page (maximum 100) of 1-based triangle
   numbers, world coordinates, centers, normals and areas.
2. `inspect_mesh_region` expands a `seed_triangle` using `selection` (`Flat`,
   `Smooth`, or `Triangle`) and `crease` (0–90°, default 15°). Alternatively,
   supply explicit `triangles`. Supply exactly one selection method. Optional
   signed `grow` adds/removes up to 30 triangle rings. The result includes
   region counts, area, center, average normal, boundary-edge count and a page
   of triangle numbers. `rings` reports the transition size for Move/Rotate.
3. `edit_mesh_region` accepts the same selection, plus `mode`:
   - `Move`: `delta: [dx,dy,dz]` in world millimeters.
   - `Rotate`: `angle` in degrees (−180…180), optional world `axis` vector and
     world `pivot` (default area-weighted region center).
   - `Extrude`: signed `distance` in mm, optional world `axis` vector. The
     default Rotate/Extrude axis is the average region normal; if it cancels
     out, provide an explicit axis. Extrude requires a non-branching patch
     boundary and does not boolean-cut other mesh surfaces.
   `rings` (1–30, default 1) controls linear, connected-vertex-ring transition
   for Move/Rotate; selected vertices always move rigidly. Extrude ignores it.
4. Poll `mesh_region_status`, then use `finish_mesh_region` or
   `cancel_mesh_region`. Finish creates a Mesh object, hides the original,
   and adds one Undo step. Stale/locked sources are rejected. All edit/finish/
   cancel calls require the latest document revision.

Example arguments for `edit_mesh_region`:

```json
{
  "document": "YourDocument",
  "object": "YourMesh",
  "expected_revision": "revision-from-the-latest-read",
  "seed_triangle": 123,
  "selection": "Flat",
  "mode": "Move",
  "delta": [0, 0, 5],
  "rings": 3
}
```

Triangle numbers refer to the current raw mesh topology. Re-inspect after any
edit. Source/result meshes are limited to 500,000 triangles; validation runs in
an isolated worker. Cancel/failure leaves the source unchanged. The worker
rejects non-manifold or inconsistently oriented input, new or changed
self-intersections, newly collapsed triangles, boundary changes and closed
shell inversion. Open input remains open. Move may change internal diagonals
on adjoining flat surfaces when the original triangulation folds around a
hole. It preserves vertices, hole outlines and selected facets; native
collision checks still apply. Curved CAD fitting is not involved.

Existing intersecting triangles may remain only with exactly unchanged
coordinates. The report includes `self_intersecting_triangles_before`,
`self_intersecting_triangles` and a warning for remaining defects. This is not
automatic repair; modifying an intersecting region must resolve its defects.

## Revisions, Undo and persistence

Read the document first and pass its returned `revision` as `expected_revision` when editing. A changed shape, placement, label, eye state or Undo/Redo history invalidates older revisions. Re-inspect the model and choose the new FaceN/EdgeN references after a geometry edit. Never reuse a face number from an older model revision.

Geometry and eye edits use the existing single native transactions. Undo/Redo also includes edits made manually, so inspect the history before requesting it. Document creation and camera/selection changes are not geometry transactions. Settings are application preferences; document Undo does not revert them.

The server does not save, open, close or export user files and has no arbitrary Python or shell execution tool. Save or export from FreeCAD as usual. Hidden faces remain part of the saved/exported geometry. A client cancellation can cancel requests that have not started; an OpenCascade operation already running finishes atomically. If a response is interrupted or reports that an operation is still running, inspect the model before retrying so the edit is not repeated accidentally.

## Connection boundary

The bridge binds only to `127.0.0.1` on a randomly assigned port. Each start creates a new secret token in a private connection file under `~/.simplecad/mcp/`. The directory is mode 700 and files mode 600 on macOS/Linux. Tokens are not included in the copied configuration or logs. Requests require the token, reject browser Origin headers and verify the local Host header. Stop removes the current connection file.

An AI client receives the model data and viewport images it requests; its own account and data policies apply. Labels and other model text are returned as data and are never executed. The stdio transport follows the [MCP transport specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), with [initialization and capability negotiation](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle) and [tool schemas/results](https://modelcontextprotocol.io/specification/2025-11-25/server/tools). The server advertises tools only; it does not implement resources, prompts, sampling or remote HTTP MCP hosting.

## Color and opacity

`inspect_object` and face results from `inspect_elements` include `appearance`: RGB `color` components from 0 to 1 and `opacity` from 0 to 100. A whole object's field is `null` when its faces have mixed values.

`set_appearance` accepts the same face/object `targets` as visibility, plus `color`, `opacity`, or both. Omitted fields retain their current values on each face. A whole-object target applies to all its faces. Zero opacity is transparent; 100 is opaque. This changes native saved surface materials, independently of eye visibility and without changing geometry. Material changes invalidate model revisions, including manual changes made outside MCP. Reconnect the MCP client after updating to discover the new tool.

## Geometry locks

`simplecad_set_locked` takes `targets` and a boolean `locked`, plus the usual document and expected revision. Parent targets take precedence. A whole-object unlock retains individual face locks; unlock the parent before changing a child lock. Inspection remains available. Geometry edits use the same atomic lock checks as the UI, including indirect changes to locked faces. Visibility, appearance, selection and copying remain allowed; independent copies start unlocked. Lock changes invalidate model revisions and support Undo/Redo. Reconnect your MCP client after updating to discover the tool.

## Surface intersection example

For a sphere centered on a block's face, call `intersect_faces` with `targets` naming that block face and the sphere's `Face1`, or both whole objects. The result replaces the participating objects with one surface object. Inspect its faces again, then delete the outside spherical region and the planar circular disk. Inspect between edits because face numbers change. When the remaining shell is closed and valid, Delete makes it a solid with the spherical recess. The lower spherical region is retained; starting from an open sheet yields an open surface instead. Materials from both inputs are mapped to their regions. Use a fresh revision for each edit; Undo restores each step.

Push/Pull cursor reference snapping is configured through the existing `pull_faces` and `pull_radius` settings (default 24 px, range 2–40). These settings govern the manual GUI interaction. MCP `push_pull` continues to use its exact signed distance; mouse snapping never alters an MCP distance.

When `push_pull` disconnects a wedge or bridge, every remaining valid solid is kept as a separate object. Its response retains `object` for the primary result and includes `objects` for all resulting owners (including any open-surface remainder). The largest solid keeps the original identity. Use these returned names and the new revision for subsequent edits; one Undo restores the entire cut.

`simplecad_move_vertex` takes `document`, `expected_revision`, `object`, `vertex` (for example `Vertex3`) and `delta` (for example `[5, 0, -2]`). Inspect vertices first and use the current revision. It returns the edited `object` and a new revision; re-inspect elements afterward because face and vertex numbers can change. It shares the GUI's restrictions (flat faces, straight edges at the vertex), curve-preserving folds, lock checks, triangulation, material inheritance and Undo transaction. Restart the FreeCAD server and reconnect the client after updating to discover the tool.

## Scale, Loft and Sweep

All three mutations require `document` and the latest `expected_revision`, and use the same operations and Undo behavior as the UI.

- `simplecad_scale`: `objects`, `factors: [x,y,z]`, optional `axes: "World" | "Local"` and `pivot: "Selection" | "Each" | "Origin"`. Factors range from 0.0001 to 10000; `[1,1,1]` makes no edit. Whole-object and face locks are respected. Nonuniform stretches can turn curved geometry into splines while flat faces stay planar.
- `simplecad_loft`: ordered `profiles`, each `{ "object": "internalName", "elements": ["Face1"] }` or an object reference with elements omitted for its entire outline. Connected EdgeN elements can define one profile. `solid` defaults true, `ruled` false. A solid requires closed planar profiles without holes; there must be 2–32 profiles.
- `simplecad_sweep`: `profile` and `path` references in the same format. Optional `solid` (true), `align` (true), `frenet` (false), and `transition` (0 transformed, 1 right corners, 2 rounded corners). Automatic alignment centers a closed planar profile at the start of the path with its normal along the path tangent. Set `align: false` for an already positioned or open surface profile.

Loft/Sweep return a new `object`. They retain their source geometry; `hide_sources` defaults true and only hides whole non-solid outline objects. Selecting subelements does not hide their larger owners. Set false to leave all source visibility unchanged. Sources are snapshots, not parametric dependencies. Re-inspect names after scaling; face indices can change during rebuilding even though materials follow their source faces.

## Bend / Soft Deform

`simplecad_deform` edits one `object` and requires `mode: "Move" | "Bend"`, `document`, and the latest `expected_revision`. It uses the same operation as the toolbar and preserves face materials, hidden regions and local orientation in one Undo step.

For **Move**, supply `delta: [dx,dy,dz]` in world mm. Optional `center` is a world-space vector, `radius` is positive mm, and `elements` names FaceN/EdgeN/VertexN elements that seed the default center. If neither center nor elements is supplied, the object bounding-box center is used. The default radius is 55% of the bounding-box diagonal. To deform a cheek on a sphere, supply an explicit center on its surface, not its internal center.

For **Bend**, supply `angle` in degrees (−170 to 170). Optional `axis` is Main (default), X/Y/Z or LocalX/LocalY/LocalZ; `origin` is a world vector, `length` is positive mm, and `direction` (−180 to 180 degrees) turns the bend plane around the axis. Defaults span the object from its low end to its high end on the chosen axis. Geometry before the origin stays fixed; beyond the specified length it follows the final tangent. The direction zero vector is projected world X, or projected world Y when X is nearly parallel to the bend axis.

Both modes accept `detail` from 3 to 16 (default 6). Results are **faceted Part approximations**, limited to 4000 faces, with Shaded display. The whole object's surface is retessellated, so re-inspect face names afterward. Zero strength leaves the exact original shape unchanged. Whole-object/face locks, invalid surface payloads, folds and self-intersections are rejected. This version supports one closed solid without separate cavity shells, or an open surface; deformation does not guarantee preserved volume.

## Imported mesh conversion

Imported Mesh objects are included in inspection with `mesh_triangles`, `mesh_points`, `conversion_available` and an edit note. Their native mesh content participates in revision checks.

1. Call `simplecad_convert_mesh` with `document`, `expected_revision`, `object`, optional `tolerance` (defaults to the modeling precision setting, 0.1 mm unless changed; surfaces are flattened and aligned within it, smaller details merged, and it bounds planar reconstruction and boundary repairs), optional `simplify` (default 0, disabling extra triangle reduction), and optional `surfaces`. A positive simplify value is a decimation tolerance in mm. With `surfaces` true, each component is rebuilt from as few fitted planes, cylinders and smooth B-spline faces as stay within the tolerance; with false, flat regions are reconstructed and curved regions remain faceted. Omitted, `surfaces` follows the **Fit smooth surfaces** choice last made in **Make mesh editable**, which starts on, so an agent and a person get the same result. This starts an isolated worker and returns `job_id` promptly.
2. Poll `simplecad_mesh_conversion_status` with `document` and `job_id`. Status is `running`, `ready`, `failed`, `cancelled` or `applied`. Ready results include face/solid counts, open-surface warnings and whether simplification was used. `surface_tolerance`, `planar_regions`, `planar_triangles` and `max_plane_deviation` describe the planar reconstruction before final divider cleanup. Without fitted surfaces, curved regions remain faceted; difficult components retain validated triangles with a warning.
3. Call `simplecad_finish_mesh_conversion` with the latest revision to create the editable Part object and hide the original mesh in one Undo step. Finish rejects a source that was moved, changed, deleted or moved into a Part container during conversion, and rejects repeated application.
4. Alternatively, `simplecad_cancel_mesh_conversion` stops the worker or discards a ready result. It requires the document, latest revision and job ID.

Start, finish and cancel require model-change permission. Status is read-only. One mesh operation (conversion, split or stretch) may run or await application at a time. Jobs live only in the current FreeCAD session; native documents change only on finish. These tools accept an already imported object, not arbitrary filesystem paths or executable code. After finishing, use ordinary inspection, appearance, editing and Undo tools on the returned Part object.

## Split a mesh without CAD conversion

Mesh inspection includes `mesh_split_available` and `mesh_closed`. Splitting preserves the source triangles away from the cut and returns native Mesh objects; it does not enable Part face-editing tools.

1. Call `simplecad_split_mesh` with `document`, `expected_revision`, `object`, and optional `axis` (`Main` by default, or `X`, `Y`, `Z`, `LocalX`, `LocalY`, `LocalZ`). `offset` is the signed distance in mm from the center of the mesh's extent along that axis, default 0. The cutting plane is perpendicular to the chosen axis. Optional `cap` defaults to true, closing the new cut surfaces; `gap` defaults to 0 mm and moves the two sides by half that distance in opposite directions.
2. Poll `simplecad_mesh_split_status` with `document` and `job_id`. A ready report includes triangle counts and closedness for each side, plus any open-surface warnings.
3. Call `simplecad_finish_mesh_split` with `document`, `job_id`, and the latest `expected_revision`. It returns two `objects`, hides the unchanged source and creates one Undo step. A source that changed, moved, was deleted or was placed in a Part container is rejected.
4. Alternatively, `simplecad_cancel_mesh_split` with the latest revision stops the worker or discards the ready result.

Mesh splitting shares the worker slot with conversion. Start/finish/cancel require model-change permission; status is read-only. Inputs are limited to 500,000 triangles; splits are not general mesh repair, and open source surfaces remain open. Save the document as FCStd or export the resulting mesh objects as STL through FreeCAD.

Optional `glue: {"depth": 2, "clearance": 0.15, "flip": false}` on `simplecad_split_mesh` adds a matching triangular ridge and groove. Omit `glue` for the ordinary planar split; an empty object enables default settings. `depth` is the maximum groove depth in mm (0.05–20), limited further by local cut width. Slopes are 45°; wide interiors level off at the specified depth. `clearance` lowers the ridge along the split axis (0 to half the depth); it leaves room for glue and assembly, and zero yields matching geometry. `flip` swaps ridge and groove sides. The source must be closed with `cap: true`.

Ready reports include `glue` settings, `max_ridge_height`, `removed_volume` (clearance space in mm³), and `profile_tolerance` (up to 0.025 mm). Finish labels the mesh results as ridge/groove and preserves the original in the same Undo transaction. The groove is checked against the existing skin; breakthrough, excessive refinement or a clearance larger than the available ridge produces a recoverable error. This remains mesh-only and does not use the solid Slice tool's stud/socket system.

## Stretch a mesh / move an end region

1. Call `simplecad_mesh_axis` with `document`, `object`, and optional `axis`
   (`Main`, `X`, `Y`, `Z`, `LocalX`, `LocalY`, `LocalZ`). It returns the axis
   `center` and unit `normal` in world coordinates, the `minimum`/`maximum`
   signed offsets, and suggested `lower`/`upper` control planes.
   Optional `rotation: [rx,ry,rz]` rotates the axis and both control planes
   about the preset's common origin, in world X, then Y, then Z order.
   Each angle is between -180 and 180 degrees. The returned bounds and normal
   include the rotation; the center remains fixed.
2. Call `simplecad_stretch_mesh` with the latest revision, object, axis,
   optional `lower`/`upper` offsets, and **either** `distance` **or** `delta`.
   `distance` is the axial length change in mm: positive grows, negative
   shortens. `delta: [dx,dy,dz]` is an explicit world-space end displacement.
   With `reverse: false` (default), geometry below the lower plane stays
   fixed and geometry above the upper plane moves rigidly. `reverse: true`
   swaps the fixed/moving ends; a positive distance still grows the mesh.
   Default planes bound the middle third of the axis extent.
   Pass the **same axis and rotation** used for `mesh_axis`. Existing clients
   that omit rotation retain the preset's original direction. Explicit plane
   offsets preserve their separation under rotation and must lie inside the
   rotated mesh extent; axial distance follows the rotated normal, while XYZ
   delta remains a world-space movement.
3. Poll `simplecad_mesh_stretch_status`, then use
   `simplecad_finish_mesh_stretch` with the latest revision to create one
   mesh object, hide the unchanged original, and record one Undo step.
   `simplecad_cancel_mesh_stretch` cancels a running or ready result.

The transition is a linear stretch/shear. Triangles crossing the control
planes are subdivided so untouched end geometry retains its shape. This does
not simplify, repair, or convert the STL to CAD faces. Result counts may grow;
input and output have a 500,000-triangle limit. Collapse/reversal is rejected.
Planes must lie within the mesh extent and lower must be less than upper.
Zero movement creates no job. Keep mounting features outside the transition
when their dimensions must stay fixed. Existing open boundaries remain open.

Reports contain `triangles_before`, `triangles`, `closed`, fixed/moving/
transition vertex counts and warnings. Start/finish/cancel require edit
permission; axis inspection and status are read-only. Source changes,
placement changes, new locks or dependencies invalidate Apply. The worker
slot and five-minute timeout are shared with conversion and splitting.
