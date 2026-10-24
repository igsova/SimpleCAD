# Changelog

Notable changes to SimpleCAD. Restart FreeCAD after updating to load new
commands, and reconnect an MCP client to refresh its tool list.

## Unreleased

### Fixed

- **Make mesh editable** with smooth surfaces off no longer cuts a stepped
  bore into one straight hole. Equal counterbores at both ends of a narrower
  hole were taken for a single through hole, which removed the material
  between them without a warning. Each section now becomes its own analytic
  hole. (#4)
- **Union** joins solids that touch tangentially, such as a block whose sides
  are tangent to a round boss. Its check for unexpected material cut the
  pieces out one at a time, which left a false remainder there, and refused
  with "Union would add unexpected material". (#8)

## 0.39.0

### Added

- **Measure Tape** (**T**) works like SketchUp's Tape Measure. Click an edge,
  move out from it and type a distance: a dashed guide line is left parallel
  to the edge at that distance. Starting on a corner or a face leaves a guide
  point instead, with a dashed tail back to the start. Drawing tools snap
  along guides and tails, to guide points and to where guides cross edges or
  each other. Guides never change the model and sit in a Guides group, where
  they can be hidden or deleted; Fit All ignores them.

### Changed

- **Rotate** moves to **Q** and **Loft** to **Shift+Q**, so **T** can start
  Measure Tape. T and Q now match SketchUp.

- Sizes are typed in the 3D view. After the first click, press **Tab** or
  just start typing: a box opens on the size label beside the shape. A
  Rectangle gets a width and a height box on its sides, and **Tab**,
  **Shift+Tab** or a comma move between them. Tools without a size label,
  such as Push/Pull and Move, open the box beside the pointer. Tab used to
  move the keyboard to a small field in the status bar, which still shows
  the value and still accepts typing.

### Fixed

- Moving the pointer while the drawing plane is edge-on no longer fills the
  Report view with red "Plane is edge-on" errors. The hint shows in the
  status bar instead.
- Undo (**⌘Z**, or **Ctrl+Z** on Windows and Linux) right after a click,
  while Line, Measure Tape or another drawing tool is still open, no longer
  crashes FreeCAD. The tool ends and the Undo goes ahead, as when **Esc** is
  pressed first.

## 0.38.3

### Fixed

- Move Vertex works on a corner of a face that has a circle or other curve
  drawn on it. It used to refuse with "The touching faces must have straight
  boundaries for Move Vertex." The curve is kept exactly: within the face's
  plane the face stays whole, and a tilt folds off only the corner.
- Undo followed at once by another edit no longer crashes FreeCAD. SimpleCAD's
  seam and hidden-face masks, face colours and highlights could still read the
  undone object's display after FreeCAD had deleted it. On Windows FreeCAD
  reports such a crash as "Access violation".

### Changed

- The README and user guide say where to switch to the SimpleCAD workbench:
  the workbench list on the toolbar, or **View → Workbench → SimpleCAD**.

## 0.38.2

### Fixed

- Snapping no longer offers a corner, midpoint or center hidden behind the
  face under the pointer. A click over such a point used to start the drawing
  on that hidden point instead of on the face in front.
- A rectangle, circle or polygon drawn across a region drawn earlier on the
  same face now divides both regions, so the overlap becomes a region of its
  own. It used to be refused with "The profile must lie completely on one
  current flat face of its support."

## 0.38.1

### Added

- Continuous integration: every push and pull request runs the unit tests
  headless on Linux with FreeCAD 1.1 from conda-forge, and a ruff lint check
  for errors (`ruff.toml`). The README shows both results.
- A Privacy and safety section in the README.

### Fixed

- Rectangle now divides the face it is drawn on, as Circle and Polygon do. It
  used to add a separate face lying on top, which flickered against the face
  under it in the viewport.
- Pulling out a region drawn flush with an edge merges its side into the
  solid's side instead of leaving a seam, when the solid has no other drawn
  divisions.
- Drawing on connected surfaces: a point clicked on a face far from the last
  one, such as the opposite side of a box, could be placed the long way
  around. The solver now also measures the distance off the target face, so
  it no longer stalls on a face square to it. This depended on the
  computer's math library and showed up on the Linux CI runners.
- Removed unused imports and variables, and a leftover unused computation in
  planar mesh conversion.
- The stretch test with a hole in the rigid end measures volume in double
  precision. FreeCAD's `Mesh.Volume` sums in single precision and was off by
  0.025 mm³, so the test failed although the stretched mesh was exact.

## 0.38.0

### Changed

- The source is organized into packages by purpose: `core`, `modeling`,
  `surfaces`, `mesh`, `repair`, `inspection`, `document`, `jobs`, `mcp` and
  `gui` (with `gui/tools` and `gui/previews`). Tests are split into
  `tests/unit`, `tests/gui` and `tests/benchmarks`. Saved models store no
  module paths, so existing `.FCStd` files open unchanged, and
  `scripts/simplecad_mcp.py` keeps its path for existing MCP client setups.
- The README is a short project page. The full manual is now
  [docs/user-guide.md](docs/user-guide.md), and version notes live here.
- The documentation is also published as a searchable site on GitHub Pages,
  built from `docs/` on every change to `main`. Its **Tools** section has an
  entry for every tool, with steps, options, keys and a short clip.

### Added

- **Copy, cut and paste** whole objects with ⌘C, ⌘X and ⌘V (Ctrl on Windows
  and Linux) in the 3D view and the Model tab. Paste puts the copy in place
  and starts Move to place it; cut and paste are one Undo step each.
- **Drawing feedback.** Line shows the current segment's length beside it;
  Rectangle shows its width and height beside its first two sides; Circle,
  Polygon and Sphere show their radius. A typed size is shown there until the
  pointer moves.
- **Arrow keys choose the drawing plane**, as in SketchUp: → YZ, ← XZ, ↑ XY,
  ↓ back to Auto. After a Line's first click they lock its direction instead.
- **Dark viewport style** with a ground grid, X/Y/Z axes, camera-following
  lights, a configurable default **Face color** and lighter hover and selection
  colours. It is on by default and can be turned off in Settings.
- **Draw: Surface** mode for Line, Rectangle, Circle, Polygon, Arc and 2 Point
  Arc. Drawings wrap across the connected faces of one object and divide them
  into selectable regions.
- **Surface** group for curved faces: Draw on surface, Offset face, Shell /
  Thicken, Draft faces, Delete & heal faces, Remove rounds, Fill hole and
  Unwrap face, plus **Pattern** and a **Curvature map**.
- **Make mesh editable** can fit smooth surfaces and analytic cylinders, giving
  far fewer faces than the flat-face rebuild.
- **Mesh region · Move / Rotate / Extrude** edits patches of a raw mesh with a
  live collision preview.
- **Stretch mesh / Move region** with draggable, rotatable stretch planes.
- **Measure** with placed dimensions; **smart selection** of holes, edge loops,
  flat regions and smooth surfaces; **Isolate selection**.
- **Mirror**, **Elongate / Make Elliptical**, **Heal to precision**, and a
  **Modeling precision** setting that mesh conversion also uses.
- Slice can cut at a picked face; studs and sockets are laid out along the cut
  face with automatic spacing.
- Move and Copy snap to hole and circle centers.
- Commands that need a selection are greyed out until it is right, and
  flat-only tools are greyed out for curved geometry.

### Fixed

- A Push/Pull that ends within 0.005 mm of an existing flat level ends exactly
  on it, so Delete no longer opens the solid at a hairline step. Deleting an
  existing hairline step folds it away.
- A face click in Move, Copy or Move Vertex lands exactly on that face.
- Line stops when a segment closes a loop into a face.
- Many speed-ups for drawing, hovering, selecting and deleting on dense
  converted parts.

## 0.37.8

Adds **Fit Circle / Cylinder** (`Y`). Select a complete faceted circular edge
loop to create a native circle edge, or select both circular rims or the
complete faceted cylindrical wall to create a native cylinder. The operation is
conservative, keeps the source object unless the whole object was selected for
replacement, and is undoable.

## 0.37.7

Improves **Make mesh editable** for closed cylindrical STL components and
circular holes inside planar bodies. When the triangle normals, circular rim and
enclosed volume agree within conservative checks, a complete component becomes
one native analytic cylinder, while a verified through-hole is cut with an
analytic cylinder after its surrounding planar faces are rebuilt. Partial,
fused, noisy or ambiguous curved regions keep the faceted fallback so conversion
never silently changes their shape. Reconvert the original mesh to benefit;
existing editable objects are unchanged.

## 0.37.6

Improves **Pull contact on imported surfaces**. A pulled straight edge within
0.005 mm of a remainder face is projected onto that face and imprinted when it
crosses the perimeter, so the contact remains selectable as divided regions.
This local contact tolerance does not relax solid validity, area or volume
checks.

## 0.37.5

Speeds up **Push/Pull on dense editable STL surfaces**. Preview setup avoids
rebuilding unedited surfaces and rejects unrelated geometry before testing
previous extrusions. Height snapping uses indexed seams and resolves only the
necessary cursor hits, including overlapping edges. Commit preserves native
remainder topology and still validates the output. No reconversion is needed.

## 0.37.4

Speeds up **editing dense open shells**, including existing editable STL
conversions. Deletion reuses unchanged topology and validates the finished
result once. Drawing within one shell face updates that face and its shared
boundary without intersecting unrelated surfaces. Triangle completion uses
indexed adjacency; sidebar area details are calculated on hover.

## 0.37.3

Speeds up **edge deletion on dense solids** by replacing only the merged faces,
checking nearby topology and reusing the sidebar face icon. On the tested
2,237-face frame, deletion including redraw improved from about 2.5 s to 1.3 s.

## 0.37.2

Makes **region selection and edge deletion faster on dense editable STL
models**, using indexed lookup instead of repeated edge and face scans.

## 0.37.1

Fixes **Make mesh editable** for STL surfaces with small coordinate deviations.
Flat regions are reconstructed within the selected **Surface / repair
tolerance**, including holes, before CAD faces are built. Reconvert the original
mesh; existing converted objects are unchanged.

## 0.37.0

Adds the optional **Triangular glue seam** to Split mesh. A raised ridge on one
side fits a matching V-shaped groove on the other to help align glued parts.

## 0.36.0

Adds **Split mesh…** for cutting an STL directly into two mesh objects.

## 0.35.0

Adds **Make mesh editable…** for imported STL meshes. Conversion runs in a
cancellable background process, combines coplanar triangles, and creates
editable Part geometry with the original mesh kept as a hidden backup.

## 0.34.1

Fixes **drawing from free line endpoints and midpoints in 3D**. In Auto, Circle,
Rectangle, Polygon, Arc, 2 Point Arc and Sphere place their first point exactly
on the target, including above or below XY.

## 0.34.0

Adds **Bend / Soft Deform** (`N`), with cached previews, a surface detail
control, preserved face appearance and visibility, Undo, and `simplecad_deform`
over MCP.

## 0.33.0

Adds **Scale / Stretch** (`K`), **Loft** (`Q`) and **Sweep** (`W`), with
previews, one-step Undo and MCP tools.

## 0.32.0

Adds **Move Vertex** (`V`), also available over MCP as `simplecad_move_vertex`.

## 0.30.2

Fixes **Line divisions across rims and faces with holes**. One inner-to-outer
connection remains a line; a second connection at another corner closes a
separate selectable region.

## 0.30.1

Fixes Line's **undefined curve type** error when a scene contains a sphere or
spherical recess.

## 0.30.0

Adds **Offset** for flat faces, straight edges, arcs and circles.

## Models made with older versions

- **Circles from 0.10.0** that overlap the original face: retrace the circle
  once with Circle (`O`), snapping to the old rim. The old disk is absorbed into
  the original face in one Undo step.
- **Triangles drawn before face division**: retrace either of the two segments
  with Line, snapping to its endpoints, to divide the underlying face.
- **An incorrect vertex-to-vertex connection** from an older version: undo it or
  delete its line, then redraw it.
