# Roadmap: precise, convenient editing of imported parts

SimpleCAD already has a broad set of creation tools. The next work makes
imported and converted parts quick to inspect and edit precisely. Items are
ticked as they are finished.

## New features, in priority order

- [x] **1. Measure / Inspect** — click a hole to see its diameter; select two
  holes for center spacing; measure face distances, angles and XYZ
  displacement. Keep measurements visible while editing.
  Reference: Fusion's Measure tool. *Measure (Z) and the `measure` MCP tool;
  faceted holes are fitted from one rim side or wall facet.*
- [x] **2. Smart selection** — select an entire hole, a connected edge loop,
  a tangent surface or a coplanar region. Face/edge/object selection
  filters and "Isolate selection". Make the loop and wall expansion that
  analytic fitting already does useful throughout the app.
  *Double-click, the Smart select dropdown and the face list menu; the
  Select: filter; Isolate hides other objects; `expand_selection` MCP tool.*
- [ ] **3. Edit Hole** — click an existing hole and set its diameter, depth
  and position directly. Counterbore/countersink options and "apply to
  matching holes". Builds on cylinder recognition and hole rebuilding.
- [ ] **4. Subtract / Trim** — select a cutting object and a target, preview
  the removed volume, optionally keep the cutter.
  Reference: SketchUp's Subtract and Trim tools.
- [ ] **5. Check and export for printing** — show open/non-manifold edges,
  disconnected pieces and repair results. Export selected parts
  individually and validate the exported mesh by reopening it. Starts from
  the existing Heal mesh checks.
- [x] **6. Linear and circular patterns** — repeat mounting holes, vents,
  supports or objects by count and spacing. Generalizes the automatic stud
  layout. *Pattern… (Modify) and the `pattern` MCP tool: grid along X/Y/Z,
  around an axis, or along a selected edge path, as independent copies of
  whole objects. Patterning features inside one solid is not done yet.*
- [x] **7. Curved-surface editing** — tools that work on the curved faces
  that smooth-surface conversion produces (ideas in the project file
  `curved-surfaces/curved-surfaces.md`). *Surface group: Draw on surface
  (imprint, raise or recess a rectangle, circle, polygon or text, projected
  straight or wrapped onto one face like a label), Offset face (Push/Pull on
  flat or curved faces), Shell / Thicken, Draft faces, Delete & heal faces,
  Remove rounds, Fill hole (smooth patches), Unwrap face; the Curvature map
  in Inspect and bend radii in Measure; MCP tools for each. Kernel work runs
  in `scripts/shape_worker.py` with Cancel.*
  - **Direct drawing on surfaces:** explicit Draw: Plane / Draw: Surface mode
    for Line, Rectangle, Circle, Polygon and both Arc tools; Surface follows
    native CAD faces, with snapping, typed
    dimensions, selectable regions and Undo. GUI drawings wrap across connected
    faces, differently parameterized curved patches and creases of one object.
    Line chains can continue while orbiting. Cached development is approximate on
    general skins; cylinders retain exact unrolled coordinates within their wall.
    Openings, disconnected components and ambiguous/overlapping wraps are guarded.

  Remaining surface work:
  - Offset face keeps straight side walls along the normals; stretching the
    neighbouring faces to follow (true replace-face offset) needs deeper
    kernel work, and some free-form faces of fitted parts refuse to offset;
  - Shell fails on parts whose fitted B-spline faces the kernel cannot
    offset, such as the sensor hood; Draft takes only flat, cylindrical and
    conical faces and needs blended rounds drafted with them or removed;
  - wrapped drawings must fit on one face (they may cross a full cylinder's
    seam); wrapping across several faces and bending whole bodies around a
    curve (Deform) are not done;
  - Fill hole for a curved opening with an island inside it;
  - Delete & heal often fails where a round meets other rounds; growing the
    neighbouring curved faces further needs deeper kernel work;
  - a live curvature map that follows edits, and an asynchronous MCP path
    for the surface tools.

## Direct editing of dense STL meshes

Keep triangle meshes as meshes for regional edits, with preview, Undo, source
backup and MCP access. CAD conversion remains available for analytic work.

- [x] **Stretch between two planes** — fixed geometry on one side, rigidly
  moving geometry on the other, and a stretching transition between them.
  World/local/main axes, numeric length change, and XYZ end-region movement.
  *Stretch mesh / Move region command and mesh context menu; cached mesh
  preview, background Apply, original backup, one Undo step and MCP jobs.
  Plane frames/handles can be dragged in the viewport; shared X/Y/Z rotation
  rings and numeric angles keep the planes parallel. Fast drag preview refines
  on release; optional MCP rotation uses the same frame.
  Native FreeCAD integration regression in tests/gui/gui_mesh_stretch.py passed
  in a Linux FreeCAD 1.1.3 container (15 October 2026); not yet run on macOS.*
- [x] **Mesh Region Move / Rotate / Extrude** — click connected flat/smooth
  patches or individual triangles; add/remove, Shift-add, grow/shrink. World
  XYZ Move, axis/pivot Rotate and boundary-wall Extrude stay mesh-only. Selected
  vertices move rigidly; neighboring vertex rings control the transition.
  Cached preview, background topology/self-intersection/orientation checks,
  hidden source backup, Undo and six MCP tools. Native end-to-end regression
  `tests/gui/gui_mesh_region.py` passed in a Linux FreeCAD 1.1.3 container
  (15 October 2026); not yet run on macOS, and no manual test there.
  Painting, pinned regions and adjustable soft falloff belong to the next item.
  *The preview marks predicted collisions red (background estimate that
  matched FreeCAD's check on 96 test edits); a rejected Apply marks the
  triangles it found.*
- [ ] **Mesh Soft Move / Bend** — direct vertex deformation with adjustable
  falloff, connected-surface influence and pinned regions.
- [ ] **Lattice / deformation cage** — reshape dense meshes with a small
  control grid and protected regions.
- [ ] **Mesh Subtract / Union** — mesh cutters for openings and added mounts,
  with background calculation and printable-result checks.
- [ ] **Controlled mesh simplification** — protect sharp edges and hole rims,
  show measured deviation, and retain the original mesh.
- [ ] **Feature-edges display** — hide internal triangulation while showing
  boundaries and sharp creases, without changing geometry.

## Improvements to existing behavior

- [ ] **Cancellable long operations** — Heal runs in a separate process but
  waits for it synchronously, so the interface can still freeze. Reuse the
  asynchronous job pattern of mesh conversion (`repair/healing.py`).
- [ ] **Reject invalid input visibly** — after a valid Push/Pull distance,
  invalid text can leave the previous distance available to Apply. Disable
  Apply until the displayed value is valid and keep errors beside the field
  (`gui/tools/push_pull.py`).
- [x] **Organize the growing interface** — Draw, Modify, Inspect and Mesh
  toolbars and menus; green mesh tools at the right end of the initial toolbar
  row. Lightweight selection checks, requirement tooltips and contextual commands
  in the viewport, Objects tree and Faces tree. Interactive tools retain pick-after-start
  behavior. Native FreeCAD layout verification remains a manual check.
- [x] **Grey out flat-only tools on curved faces** — Push/Pull, Subdivide,
  Offset, Elongate, Select hole/flat region and Move Vertex are disabled with
  an explanatory tooltip when the selection is curved geometry they cannot
  edit (`gui/command_state.py`). Next: make those tools work on curved faces; the
  options are listed in the project file `curved-surfaces/curved-surfaces.md`.
  New curved-surface tools are item 7 above.
- [x] **Fewer faces when making a mesh editable** — *Fit smooth surfaces
  (fewest faces)* rebuilds each component from fitted planes, cylinders and
  smooth B-spline faces within the tolerance, with shared smoothed seams,
  volume and validity checks, and a flat-face fallback (`surfaces/fit.py`,
  `mesh/surfaces.py`). A smooth region that one cylinder follows (a hole, a
  boss, a corner round) becomes one analytic cylinder with circular rims.
  The 22,464-triangle sensor hood went from 3,816 faces to 146 in about 27 s;
  the 17,364-triangle wheel skirt, which used to fail, to 513 in about 60 s.
  Next steps:
  - recognize cylinders that share a smooth region with other surfaces (a
    round blending into a flat area), and cones and spheres, as analytic
    faces;
  - fit a whole wrap-around band (now split into height-field pieces where
    it turns past 60°) as one surface;
  - optionally keep large flat areas as planes beside their fillets, for
    Push/Pull, when fewest faces matters less than flat faces;
  - speed up fitting on 30k+ triangle meshes (sparse normal equations
    dominate).
- [ ] **Show precision and repair effects clearly** — display the active
  modeling precision and a persistent before/after report: changed faces,
  repaired holes, maximum displacement and remaining problems.
- [ ] **Complete MCP coverage** — add manual Fit Circle / Cylinder, and
  measurement, validation and controlled save/export commands.
- [ ] **Repeatable performance benchmarks** — record selection, preview,
  deletion and commit timings on representative imported parts, so
  slowdowns are caught early. *Started: `tests/benchmarks/bench_mesh_region.py` times
  Mesh Region on a 17,400-triangle STL-like part; `tests/benchmarks/bench_line.py` times
  Line hover, clicks, splits and loop closure (two loops on the fitted part,
  the second on the first's result), the hover of all six Surface tools and a
  first cross-face hover (a fitted part and a converted part are
  read from `SC_BENCH_DATA`), and reports clicks and edits that missed their
  target. Other CAD tools are not covered.*

## Later geometry additions

- [ ] Chamfer
- [ ] Shell / Thicken
- [ ] Revolve
- [ ] Align, using faces or hole axes
- [ ] Temporary section view, to inspect internal cuts without splitting the
  model
