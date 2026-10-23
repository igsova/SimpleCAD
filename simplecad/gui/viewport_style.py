"""Dark viewport with a ground grid, axes and camera-following lights.

Only per-view Coin state changes: documents, saved colours and FreeCAD's
preferences stay as they are. Grid and axes are unpickable, outside every
bounding box, and drawn first through their own camera, whose clipping range
spans the whole grid; the model keeps FreeCAD's camera, depth range and pick
ray and covers them, except axis parts in front of it, drawn again last.
Three neutral lights turn with the camera, so a face turned up is bright,
turned left a little darker and turned right darker still, from any side. A
specular override removes shiny highlights without touching any colour.
Faces and edges keep their colour unless it is a default one: such faces are
drawn in the chosen face colour (a light blue-grey unless set otherwise),
edges black on faces and light on loose lines. FreeCAD highlights a hovered
or selected face by adding a colour, which a light face cannot show, so the
style draws such faces again in a tint of that colour; a raw mesh, highlighted
whole, takes a tint as its face colour. FreeCAD resets its background
whenever a View preference changes; the style puts its own back before the
next frame. Stopping restores FreeCAD's background (from its preferences),
lights, ambient light and face and edge colours, and removes the tints.
"""
import math

import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin

from . import surface_display
from .qt import QtCore, QtWidgets

VIEW_PATH = "User parameter:BaseApp/Preferences/View"
MESH_PATH = "User parameter:BaseApp/Preferences/Mod/Mesh"
NAME = "SimpleCADViewportStyle"
BACKGROUND = (0.153, 0.153, 0.165)
GRID = (0.2, 0.2, 0.212)
AXES = ((0.451, 0.169, 0.153), (0.196, 0.341, 0.176), (0.192, 0.29, 0.533))
# Travel directions in camera space (x right, y up, z towards the viewer) and
# grey levels. Each visible face of an isometric box faces exactly one light,
# so with ambient light a white box reads 0.94 on top, 0.78 left, 0.56 right.
LIGHTS = (((0., -0.816, -0.577), (0.873,) * 3),
          ((0.707, 0.408, -0.577), (0.713,) * 3),
          ((-0.707, 0.408, -0.577), (0.493,) * 3))
AMBIENT = (0.2, (1., 1., 1.))
FACE = (227/255, 227/255, 236/255)  # #E3E3EC, a light grey with a touch of blue
EDGE = (0., 0., 0.)
LOOSE = (0.8, 0.82, 0.85)
# SimpleCAD's own face and edge colours for new shapes; FreeCAD's come from
# preferences, and converted meshes keep the mesh's colour.
SIMPLECAD_FACE = (0.76, 0.84, 0.88)
SIMPLECAD_EDGE = (0.15, 0.23, 0.29)
FREECAD_FACE = 2914369023  # 0xADB5BDFF, FreeCAD 1.1's default shape and mesh colour
CELLS = 40
TOLERANCE = 2e-3
# Share of FreeCAD's highlight colour in a hovered or selected face's colour.
HIGHLIGHT = 0.6


def spacing(size, cells=CELLS):
    """Power of ten giving at most `cells` grid cells across `size` mm."""
    exponent = math.ceil(math.log10(max(size, 1e-9) / cells) - 1e-9)
    return 10. ** min(5, max(-3, exponent))


def grid_plan(position, direction, height, aspect=1., perspective=False, focal=0.):
    """(spacing, centre, half width in cells) of a ground grid filling the view.

    `height` is the view height at the focal distance. The grid is centred
    where the view axis meets Z = 0 and reaches further at grazing angles.
    """
    size = height * max(1., aspect)
    step = spacing(size)
    centre = (position[0] + direction[0]*focal, position[1] + direction[1]*focal)
    if abs(direction[2]) > 1e-6:
        t = -position[2] / direction[2]
        if t > 0 or not perspective:
            hit = (position[0] + t*direction[0], position[1] + t*direction[1])
            # A grazing view meets the ground far away; stay near the focus.
            offset, limit = math.hypot(hit[0]-centre[0], hit[1]-centre[1]), 10*size
            scale = 1. if offset <= limit else limit / offset
            centre = tuple(c + (h-c)*scale for c, h in zip(centre, hit))
    reach = size * (1 + 1 / max(abs(direction[2]), 0.1))
    return step, (round(centre[0]/step)*step, round(centre[1]/step)*step), math.ceil(reach/step)


def covers(current, needed):
    """Whether a built grid still fills the needed one without being wasteful."""
    step, centre, cells = current
    need_step, need_centre, need_cells = needed
    return (math.isclose(step, need_step) and cells <= 2*need_cells + 16 and
            all(abs(a-b) + need_cells*need_step <= cells*step*(1+1e-9) for a, b in zip(centre, need_centre)))


def grid_points(step, centre, cells):
    """Segment end points of the grid lines, two per line."""
    cx, cy = centre
    reach = cells * step
    points = []
    for i in range(-cells, cells+1):
        x, y = cx + i*step, cy + i*step
        points += [(x, cy-reach, 0.), (x, cy+reach, 0.), (cx-reach, y, 0.), (cx+reach, y, 0.)]
    return points


def axis_points(step, centre, cells):
    cx, cy = centre
    reach = cells * step
    return [(cx-reach, 0., 0.), (cx+reach, 0., 0.), (0., cy-reach, 0.), (0., cy+reach, 0.),
            (0., 0., -reach), (0., 0., reach)]


def unpack(value):
    """RGB of FreeCAD's packed 0xRRGGBBAA colour preference."""
    return tuple(((value >> shift) & 255) / 255. for shift in (24, 16, 8))


def close(first, second):
    return all(abs(a-b) < TOLERANCE for a, b in zip(first, second))


def freecad_background(params):
    """FreeCAD's own background for its View preferences: style and colours.

    Mirrors FreeCAD's handling of these preferences: the simple colour, then
    the gradient's top, bottom and optional middle colours.
    """
    if params.GetBool("Gradient", True):
        style = "LINEAR"
    elif params.GetBool("RadialGradient", False):
        style = "RADIAL"
    else:
        style = "NONE"
    colours = [unpack(params.GetUnsigned(name, default)) for name, default in (
        ("BackgroundColor", 336897023), ("BackgroundColor2", 859006463), ("BackgroundColor3", 2543299327))]
    if params.GetBool("UseBackgroundColorMid", False):
        colours.append(unpack(params.GetUnsigned("BackgroundColor4", 1869583359)))
    return style, colours


def face_defaults(view_params, mesh_params):
    """Face colours that mean "no colour of its own": SimpleCAD's and FreeCAD's."""
    return (SIMPLECAD_FACE, unpack(view_params.GetUnsigned("DefaultShapeColor", FREECAD_FACE)),
            unpack(mesh_params.GetUnsigned("MeshColor", FREECAD_FACE)))


def shown_faces(values, colour, defaults, owned=()):
    """Face colours as drawn: entries in a default colour, or `owned` ones, become `colour`.

    Returns the new values and the indices drawn in `colour`.
    """
    shown, drawn = list(values), []
    for index, value in enumerate(values):
        if index in owned or any(close(value, default) for default in defaults):
            shown[index] = colour
            drawn.append(index)
    return shown, drawn


def edge_colour(colour, defaults, faces, mode):
    """Display colour for an object's lines, or None to keep its own colour."""
    if not any(close(colour, default) for default in defaults):
        return None
    return EDGE if faces and mode not in ("Wireframe", "Points") else LOOSE


def colour_of(field):
    return tuple(field.getValues()[0].getValue()) if field.getNum() == 1 else None


def tint(highlight):
    """Colour of a hovered or selected face: FreeCAD's highlight colour, lightened."""
    return tuple(1 - HIGHLIGHT + HIGHLIGHT*value for value in highlight)


def mesh_tint(highlight):
    """Face colour of a hovered or selected mesh, to which FreeCAD adds `highlight`."""
    return tuple(max(0., a - b) for a, b in zip(tint(highlight), highlight))


def face_ranges(counts, size):
    """(start, end) of each face's triangles in a native face set's coordIndex.

    FreeCAD writes each triangle as three indices and -1, face after face, and
    each face's triangle count in partIndex. None for any other layout.
    """
    if any(count < 0 for count in counts) or sum(counts) * 4 != size:
        return None
    ranges, start = [], 0
    for count in counts:
        ranges.append((start, start + count*4))
        start += count * 4
    return ranges


def highlight_targets(selection, preselection):
    """{(document, object): (selected, hovered)} sub-element names.

    `selection` lists (document, object, names) and `preselection` is one or
    None. "" stands for a whole object; a nested name such as "Body.Pad.Face3"
    belongs to its innermost object.
    """
    targets = {}
    for slot, entries in ((0, selection), (1, [preselection] if preselection else [])):
        for document, name, subnames in entries:
            for subname in subnames or ("",):
                parts = subname.split(".")
                key = (document, parts[-2] if len(parts) > 1 and parts[-2] else name)
                targets.setdefault(key, (set(), set()))[slot].add(parts[-1])
    return targets


def current_targets():
    """highlight_targets() of FreeCAD's selection in every document and its preselection."""
    selection = [(entry.Object.Document.Name, entry.Object.Name, entry.SubElementNames)
                 for entry in Gui.Selection.getSelectionEx("*") if entry.Object is not None]
    pre = Gui.Selection.getPreselection()
    preselection = (pre.DocumentName, pre.ObjectName, pre.SubElementNames) if pre and pre.ObjectName else None
    return highlight_targets(selection, preselection)


def pixel_ratio():
    try:
        return max(1., float(Gui.getMainWindow().devicePixelRatioF()))
    except (AttributeError, RuntimeError, TypeError):
        return 1.


def is_perspective(camera):
    return camera.isOfType(coin.SoPerspectiveCamera.getClassTypeId())


def camera_plan(camera, aspect):
    position = tuple(camera.position.getValue().getValue())
    direction = tuple(camera.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1)).getValue())
    focal = camera.focalDistance.getValue()
    if is_perspective(camera):
        height = 2 * focal * math.tan(camera.heightAngle.getValue() / 2)
        return grid_plan(position, direction, height, aspect, True, focal)
    return grid_plan(position, direction, camera.height.getValue(), aspect, False, focal)


def native_lights(manager, root, own):
    """FreeCAD's lights: before the camera, and at the top of the view root."""
    found = []
    scene = manager.getSceneGraph()
    camera = manager.getCamera()
    for index in range(scene.getNumChildren()):
        node = scene.getChild(index)
        if node == camera:
            break
        if node.isOfType(coin.SoLight.getClassTypeId()):
            found.append(node)
    for index in range(root.getNumChildren()):
        node = root.getChild(index)
        if node == own:
            continue
        if node.isOfType(coin.SoLight.getClassTypeId()):
            found.append(node)
        elif node.isOfType(coin.SoTransformSeparator.getClassTypeId()):
            found += [node.getChild(i) for i in range(node.getNumChildren())
                      if node.getChild(i).isOfType(coin.SoLight.getClassTypeId())]
    return found


# FreeCAD releases a viewer's Python object in the viewer's destructor, which
# can run while Qt holds no GIL (Python 3.14 then crashes deallocating it).
# Each record keeps that object; forgotten ones wait here until their view is
# gone, so the destructor's release is never the last.
RETIRED = []


def alive(view):
    try:
        view.getSize()
        return True
    except (RuntimeError, ReferenceError, AttributeError):
        return False


def purge_retired():
    RETIRED[:] = [entry for entry in RETIRED if alive(entry[0])]


def overlay(name):
    """Unpickable display-only lines; close_bounds() keeps them out of bounding boxes."""
    # FreeCAD excludes this group only while fitting the view.
    group = coin.SoType.fromName("SoSkipBoundingGroup").createInstance()
    group.ref()  # createInstance() proxies do not own their node; forget() unrefs.
    group.setName(name)
    scene = coin.SoSeparator()
    scene.renderCaching = coin.SoSeparator.OFF
    group.addChild(scene)
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    scene.addChild(pick)
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    scene.addChild(light)
    return group, scene


def close_bounds(scene):
    """Empty the bounding box gathered inside `scene`, for every action."""
    reset = coin.SoResetTransform()
    reset.whatToReset = coin.SoResetTransform.BBOX
    scene.addChild(reset)


def line_part(colours, width, coords, lines):
    part = coin.SoSeparator()
    style = coin.SoDrawStyle()
    style.lineWidth = width
    part.addChild(style)
    binding = coin.SoMaterialBinding()
    binding.value = coin.SoMaterialBinding.PER_PART if len(colours) > 1 else coin.SoMaterialBinding.OVERALL
    part.addChild(binding)
    base = coin.SoBaseColor()
    base.rgb.setValues(0, len(colours), list(colours))
    part.addChild(base)
    part.addChild(coords)
    part.addChild(lines)
    return part


class ViewRecord:
    """The style's nodes in one 3D view and the native values it replaced."""
    def __init__(self, view, root, doc):
        self.view, self.root, self.doc = view, root, doc
        self.viewer = view.getViewer()
        self.graphics = self.widget = None
        self.master = self.camera = self.ray = self.sensor = self.plan = None
        self.background = False
        self.native = []
        self.lights = coin.SoTransformSeparator()
        self.lights.setName(NAME + "Lights")
        # Lights placed after this rotation turn with the camera.
        self.rotation = coin.SoRotation()
        self.lights.addChild(self.rotation)
        for direction, colour in LIGHTS:
            light = coin.SoDirectionalLight()
            light.direction = direction
            light.color = colour
            light.intensity = 1.
            self.lights.addChild(light)
        gloss = coin.SoMaterial()
        for name in ("ambientColor", "diffuseColor", "emissiveColor", "shininess", "transparency"):
            gloss.getField(name).setIgnored(True)
        gloss.specularColor = (0., 0., 0.)
        gloss.setOverride(True)
        self.lights.addChild(gloss)
        # Coin's depth test starts as LEQUAL while OpenGL's is LESS, and the
        # grid's separator puts Coin's into OpenGL when it pops. FreeCAD draws
        # a hovered or selected face first and then the rest of its faces at
        # the same depth, which only LESS keeps from covering the highlight.
        depth = coin.SoDepthBuffer()
        depth.function = coin.SoDepthBuffer.LESS
        self.lights.addChild(depth)
        ratio = pixel_ratio()
        self.grid_coords, self.grid_lines = coin.SoCoordinate3(), coin.SoLineSet()
        self.axis_coords, self.axis_lines = coin.SoCoordinate3(), coin.SoLineSet()
        grid = line_part((GRID,), ratio, self.grid_coords, self.grid_lines)
        axes = line_part(AXES, 1.5 * ratio, self.axis_coords, self.axis_lines)
        # Behind everything: grid and full-length axes through a camera whose
        # clipping range spans them, ignoring depth.
        self.backdrop, self.scene = overlay(NAME + "Grid")
        self.scene.addChild(coin.SoOrthographicCamera())  # replaced by follow()
        depth = coin.SoDepthBuffer()
        depth.test = False
        depth.write = False
        self.scene.addChild(depth)
        self.scene.addChild(grid)
        self.scene.addChild(axes)
        self.scene.addChild(coin.SoOrthographicCamera())  # replaced by follow()
        close_bounds(self.scene)
        # In front: axis parts nearer than the model, through FreeCAD's camera.
        self.front, scene = overlay(NAME + "Axes")
        depth = coin.SoDepthBuffer()
        depth.write = False
        scene.addChild(depth)
        scene.addChild(axes)
        close_bounds(scene)
        self.groups = (self.backdrop, self.front)

    def apply(self):
        viewer = self.viewer
        manager = viewer.getSoRenderManager()
        if self.root.findChild(self.lights) < 0:
            self.root.insertChild(self.lights, 0)
        if self.root.findChild(self.backdrop) < 0:
            self.root.insertChild(self.backdrop, self.root.findChild(self.lights) + 1)
        if self.root.findChild(self.front) < 0:
            self.root.addChild(self.front)
        camera = manager.getCamera()
        if not self.following() or not camera == self.master:
            self.follow(camera)
        for light in native_lights(manager, self.root, self.lights):
            self.hold(light, "on", False)
        environment = next((self.root.getChild(i) for i in range(self.root.getNumChildren())
                            if self.root.getChild(i).isOfType(coin.SoEnvironment.getClassTypeId())), None)
        if environment is not None:
            self.hold(environment, "ambientIntensity", AMBIENT[0])
            self.hold(environment, "ambientColor", AMBIENT[1])
        if not self.background or not close(manager.getBackgroundColor().getValue(), BACKGROUND):
            viewer.setGradientBackground("NONE")
            viewer.setBackgroundColor(*BACKGROUND)
            self.background = True
        self.update_grid()

    def guard(self):
        """Before a frame: put the style back if FreeCAD reapplied its own look."""
        if not close(self.viewer.getSoRenderManager().getBackgroundColor().getValue(), BACKGROUND):
            self.background = False
            self.apply()

    def follow(self, camera):
        """Track a (new) native camera: lights, grid camera and grid extent."""
        self.release_camera()
        self.master = camera
        self.rotation.rotation.connectFrom(camera.orientation)
        perspective = is_perspective(camera)
        names = ("position", "orientation", "aspectRatio", "focalDistance", "viewportMapping",
                 "heightAngle" if perspective else "height")
        self.camera, self.ray = (coin.SoPerspectiveCamera() if perspective else coin.SoOrthographicCamera()
                                 for unused in range(2))
        for name in names:
            self.camera.getField(name).connectFrom(camera.getField(name))
        # Grid and axes ignore depth, so only clipping depends on this range.
        self.camera.nearDistance = 0.01 if perspective else -1e8
        self.camera.farDistance = 1e8
        self.scene.replaceChild(2, self.camera)
        # A pick ray outlives the separator: recompute it from FreeCAD's view.
        for name in names + ("nearDistance", "farDistance"):
            self.ray.getField(name).connectFrom(camera.getField(name))
        self.scene.replaceChild(6, self.ray)
        self.plan = None
        self.sensor = coin.SoNodeSensor(lambda *unused: self.following() and self.update_grid(), None)
        self.sensor.attach(camera)

    def following(self):
        """Whether the followed camera still exists.

        FreeCAD deletes its camera on a perspective switch. Coin then detaches
        the sensor but still runs it if the camera had just moved.
        """
        return self.sensor is not None and self.sensor.getAttachedNode() is not None

    def update_grid(self):
        try:
            width, height = self.view.getSize()
            plan = camera_plan(self.master, width / max(height, 1))
        except (RuntimeError, ReferenceError, AttributeError, ValueError):
            return
        if self.plan is not None and covers(self.plan, plan):
            return
        step, centre, cells = plan
        # A margin keeps small pans and orbits from rebuilding the grid.
        self.plan = step, centre, cells + max(8, cells // 4)
        for coords, lines, points in ((self.grid_coords, self.grid_lines, grid_points(*self.plan)),
                                      (self.axis_coords, self.axis_lines, axis_points(*self.plan))):
            coords.point.setNum(len(points))
            coords.point.setValues(0, len(points), points)
            lines.numVertices.setNum(len(points) // 2)
            lines.numVertices.setValues(0, len(points) // 2, [2] * (len(points) // 2))

    def hold(self, node, name, value):
        """Set a native field, remembering FreeCAD's value, also if FreeCAD changes it."""
        field = node.getField(name)
        current = field.getValue()
        current = tuple(current.getValue()) if hasattr(current, "getValue") else current
        ours = tuple(value) if isinstance(value, tuple) else value
        entry = next((entry for entry in self.native if entry[0] == node and entry[1] == name), None)
        same = close(current, ours) if isinstance(ours, tuple) else current == ours
        if same:
            return
        if entry is None:
            self.native.append([node, name, current, ours])
        else:
            entry[2] = current
        field.setValue(value)

    def release_camera(self):
        if self.sensor is not None:
            self.sensor.detach()
            self.sensor = None
        self.rotation.rotation.disconnect()
        for node in (self.camera, self.ray):
            for name in ("position", "orientation", "aspectRatio", "focalDistance", "viewportMapping",
                         "heightAngle", "height", "nearDistance", "farDistance"):
                field = node.getField(name) if node is not None else None
                if field is not None:
                    field.disconnect()
        self.master = None

    def forget(self):
        """Drop a closed view's nodes without touching its (deleted) viewer."""
        self.release_camera()
        for node in (self.lights, self.backdrop, self.front):
            index = self.root.findChild(node)
            if index >= 0:
                self.root.removeChild(index)
        self.native.clear()
        if self.groups:
            for group in self.groups:
                group.unref()
            self.groups = ()
            RETIRED.append((self.view, self.viewer))

    def restore(self):
        for node, name, previous, ours in self.native:
            field = node.getField(name)
            current = field.getValue()
            current = tuple(current.getValue()) if hasattr(current, "getValue") else current
            if (close(current, ours) if isinstance(ours, tuple) else current == ours):
                field.setValue(previous)
        self.forget()
        if not alive(self.view):
            return
        style, colours = freecad_background(App.ParamGet(VIEW_PATH))
        self.viewer.setGradientBackgroundColor(*colours[1:])
        self.viewer.setGradientBackground(style)
        self.viewer.setBackgroundColor(*colours[0])


class FaceRecolour:
    """Display-only colour of a native face material's default-coloured entries.

    A mesh keeps its colour unless it has a single one: per-vertex colours are
    a map, not a material. Entries are checked again only after FreeCAD or a
    preview writes them, since a dense part can have one per face.
    """
    def __init__(self, node, changed, single=False):
        node.ref()  # borrowed from a view provider, which an Undo can delete first
        self.node, self.single = node, single
        self.ours = None
        self.native = {}  # index: FreeCAD's colour drawn as ours
        self.dirty = True

        def touched(*unused):
            self.dirty = True
            changed()
        self.sensor = coin.SoFieldSensor(touched, None)
        self.sensor.attach(node.diffuseColor)

    def values(self):
        return [tuple(value.getValue()) for value in self.node.diffuseColor.getValues()]

    def write(self, values):
        self.sensor.detach()
        try:
            self.node.diffuseColor.setValues(0, len(values), values)
        finally:
            self.sensor.attach(self.node.diffuseColor)

    def apply(self, colour, defaults):
        if colour is None or (self.single and self.node.diffuseColor.getNum() != 1):
            self.release(detach=False)
            return
        if not self.dirty and self.ours is not None and close(colour, self.ours):
            return
        self.dirty = False
        values = self.values()
        # Entries still drawn in our previous colour are FreeCAD's defaults too.
        owned = {index for index in self.native if index < len(values) and self.ours is not None
                 and close(values[index], self.ours)}
        shown, drawn = shown_faces(values, colour, defaults, owned)
        self.native = {index: self.native[index] if index in owned else values[index] for index in drawn}
        self.ours = colour
        if any(not close(a, b) for a, b in zip(values, shown)):
            self.write(shown)

    def release(self, detach=True):
        """Give back FreeCAD's colours; a deleted object's wait in Undo."""
        if self.native and self.ours is not None:
            values = self.values()
            restored = list(values)
            for index, native in self.native.items():
                if index < len(values) and close(values[index], self.ours):
                    restored[index] = native
            if restored != values:
                self.write(restored)
        self.native, self.ours, self.dirty = {}, None, True
        if detach:
            self.detach()

    def detach(self):
        """Stop following the material and let go of it."""
        self.sensor.detach()
        self.node.unref()


class Recolour:
    """Display-only colour of one native line or point material."""
    def __init__(self, node, changed):
        node.ref()  # borrowed from a view provider, which an Undo can delete first
        self.node = node
        self.ours = self.native = None
        self.sensor = coin.SoFieldSensor(lambda *unused: changed(), None)
        self.sensor.attach(node.diffuseColor)

    def write(self, colour):
        self.sensor.detach()
        try:
            self.node.diffuseColor.setValue(colour)
        finally:
            self.sensor.attach(self.node.diffuseColor)

    def apply(self, native, colour):
        current = colour_of(self.node.diffuseColor)
        if current is None:
            return
        if colour is None:
            self.release(native, detach=False)
        elif not close(current, colour) and (close(current, native) or
                                              self.ours is not None and close(current, self.ours)):
            # FreeCAD's colour, or ours for another display mode.
            self.ours, self.native = colour, native
            self.write(colour)

    def release(self, native=None, detach=True):
        """Give back FreeCAD's colour; a deleted object's waits in Undo."""
        current = colour_of(self.node.diffuseColor)
        if self.ours is not None and current is not None and close(current, self.ours):
            self.write(native or self.native)
        self.ours = None
        if detach:
            self.detach()

    def detach(self):
        """Stop following the material and let go of it."""
        self.sensor.detach()
        self.node.unref()


def write_indices(field, values):
    field.setNum(len(values))
    if values:
        field.setValues(0, len(values), values)


class FaceHighlight:
    """Hovered and selected faces of one native face set, drawn again in a tint.

    FreeCAD highlights a face by adding the highlight colour to its lit colour,
    which a bright face cannot show. Copies of the face's triangles follow the
    face set and are drawn at equal depth, hovered over selected, never picked.
    They are cleared as soon as FreeCAD rewrites the face set and copied again
    later, so they never index stale coordinates. Transparent and mixed opacity
    faces keep FreeCAD's highlight, which shows there.
    """
    def __init__(self, parent, native, source, changed):
        # A deleted object's nodes can go before the style lets go of them.
        for node in (parent, native, source):
            node.ref()
        self.parent, self.native, self.source = parent, native, source
        self.ranges = self.indices = self.normals = self.shown = None
        self.node = coin.SoSeparator()
        self.node.setName(NAME + "Highlight")
        self.node.renderCaching = coin.SoSeparator.OFF
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        self.node.addChild(pick)
        depth = coin.SoDepthBuffer()
        depth.function = coin.SoDepthBuffer.LEQUAL
        depth.write = False
        self.node.addChild(depth)
        binding = coin.SoMaterialBinding()
        binding.value = coin.SoMaterialBinding.OVERALL
        self.node.addChild(binding)
        self.parts = []
        for unused in range(2):  # selected, then hovered
            material, faces = coin.SoMaterial(), coin.SoIndexedFaceSet()
            faces.vertexProperty.connectFrom(native.vertexProperty)
            self.node.addChild(material)
            self.node.addChild(faces)
            self.parts.append((material, faces))
        parent.insertChild(self.node, parent.findChild(native) + 1)

        def touched(*unused):
            self.clear()
            changed()
        self.sensors = []
        for name in ("partIndex", "coordIndex"):
            # Immediate, so no frame is drawn between FreeCAD's write and clear().
            sensor = coin.SoFieldSensor(touched, None)
            sensor.setPriority(0)
            sensor.attach(native.getField(name))
            self.sensors.append(sensor)

    def clear(self):
        self.ranges = self.indices = self.normals = self.shown = None
        for unused, faces in self.parts:
            faces.coordIndex.setNum(0)
            faces.normalIndex.setNum(0)

    def read(self):
        indices = list(self.native.coordIndex.getValues())
        self.ranges = face_ranges(tuple(self.native.getField("partIndex").getValues()), len(indices))
        normals = list(self.native.normalIndex.getValues())
        self.indices = indices
        # Without its own normal indices the face set's normals follow coordIndex.
        self.normals = normals if len(normals) == len(indices) else []

    def triangles(self, names):
        """Coordinate and normal indices of faces `names`; "" is every face."""
        if not names:
            return [], []
        if self.ranges is None:
            self.read()
            if self.ranges is None:
                return [], []
        if "" in names:
            return self.indices, self.normals
        indices, normals = [], []
        numbers = sorted(int(name[4:]) for name in names if name.startswith("Face") and name[4:].isdigit())
        for number in numbers:
            if 1 <= number <= len(self.ranges):
                start, end = self.ranges[number - 1]
                indices += self.indices[start:end]
                normals += self.normals[start:end]
        return indices, normals

    def plain(self):
        """Whether FreeCAD's own highlight cannot show on these faces."""
        if any(value > 0 for value in self.source.transparency.getValues()):
            return False
        return not any(str(self.parent.getChild(index).getName()) == "SimpleCADSurface"
                       for index in range(self.parent.getNumChildren()))

    def show(self, selected, hovered, colours):
        """Draw faces `selected` and `hovered` in tints of `colours` (selection, hover).

        Without `colours` nothing is drawn.
        """
        if colours is None or not self.plain():
            selected = hovered = ()
        state = (frozenset(selected), frozenset(hovered), colours)
        if state == self.shown:
            return
        self.shown = state
        for (material, faces), names, colour in zip(self.parts, state[:2], colours or (None, None)):
            indices, normals = self.triangles(names)
            if colour is not None:
                material.diffuseColor = tint(colour)
            write_indices(faces.coordIndex, indices)
            write_indices(faces.normalIndex, normals)

    def close(self):
        for sensor in self.sensors:
            sensor.detach()
        self.sensors = []
        for unused, faces in self.parts:
            faces.vertexProperty.disconnect()
        index = self.parent.findChild(self.node)
        if index >= 0:
            self.parent.removeChild(index)
        for node in (self.parent, self.native, self.source):
            node.unref()
        self.parent = self.native = self.source = None


def materials(root):
    found = {"LineMaterial": [], "PointMaterial": [], "ShapeMaterial": []}
    def visit(node):
        if isinstance(node, coin.SoMaterial):
            nodes = found.get(str(node.getName()))
            if nodes is not None and not any(node == old for old in nodes):
                nodes.append(node)
        elif hasattr(node, "getNumChildren"):
            for index in range(node.getNumChildren()):
                visit(node.getChild(index))
    visit(root)
    return found


class ViewportStyle(QtCore.QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = self.enabled = False
        self.face = FACE
        self.views = []
        self.styled = {}
        self.faces = {}
        self.mdi = self.params = None
        self.pending = QtCore.QTimer(self)
        self.pending.setSingleShot(True)
        self.pending.timeout.connect(self.refresh)
        # Covers new views, recreated cameras and FreeCAD reapplying its lights.
        self.fallback = QtCore.QTimer(self)
        self.fallback.setInterval(500)
        self.fallback.timeout.connect(self.refresh)
        # Hover and selection change outside scene traversals only after a turn.
        self.highlight_pending = QtCore.QTimer(self)
        self.highlight_pending.setSingleShot(True)
        self.highlight_pending.timeout.connect(self.highlight)
        style = self

        class Preferences:
            def onChange(self, group, reason):
                for record in style.views:
                    record.background = False
                style.schedule()
        self.preferences = Preferences()

        class Selection:
            def changed(self, *unused):
                style.schedule_highlight()
            addSelection = removeSelection = setSelection = clearSelection = changed
            setPreselection = removePreselection = changed
        self.selection = Selection()

    def start(self, enabled=True, face=FACE):
        self.enabled, self.face = enabled, tuple(face)
        if not self.running:
            self.running = True
            App.addDocumentObserver(self)
            # The observer lives only as long as this group handle.
            self.params = App.ParamGet(VIEW_PATH)
            self.params.Attach(self.preferences)
            Gui.Selection.addObserver(self.selection)
            self.fallback.start()
            self.mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
            if self.mdi is not None:
                self.mdi.subWindowActivated.connect(self.schedule)
        self.refresh()

    def stop(self):
        if self.running:
            self.running = False
            App.removeDocumentObserver(self)
            self.params.Detach(self.preferences)
            self.params = None
            Gui.Selection.removeObserver(self.selection)
            self.fallback.stop()
            self.pending.stop()
            self.highlight_pending.stop()
            if self.mdi is not None:
                try:
                    self.mdi.subWindowActivated.disconnect(self.schedule)
                except (RuntimeError, TypeError):
                    pass
                self.mdi = None
        self.restore()

    def configure(self, enabled, face=None):
        self.enabled = enabled
        if face is not None:
            self.face = tuple(face)
        if self.running:
            self.refresh()

    def active(self):
        return self.running and self.enabled

    def shown_face(self, colour):
        """The colour a face of `colour` is drawn in, for previews in an object's colours."""
        colour = tuple(colour[:3])
        defaults = face_defaults(App.ParamGet(VIEW_PATH), App.ParamGet(MESH_PATH))
        return self.face if self.active() and any(close(colour, default) for default in defaults) else colour

    def shown_edge(self, colour):
        """The colour an edge of `colour` on a face is drawn in, for previews."""
        colour = tuple(colour[:3])
        params = App.ParamGet(VIEW_PATH)
        defaults = (SIMPLECAD_EDGE, unpack(params.GetUnsigned("DefaultShapeLineColor", 421075455)))
        return EDGE if self.active() and any(close(colour, default) for default in defaults) else colour

    def schedule(self, *unused):
        if self.running and not self.pending.isActive():
            self.pending.start(0)

    def schedule_highlight(self, *unused):
        if self.running and not self.highlight_pending.isActive():
            self.highlight_pending.start(0)

    slotCreatedDocument = schedule
    slotCreatedObject = schedule
    slotUndoDocument = schedule
    slotRedoDocument = schedule
    slotRecomputedDocument = schedule
    slotFinishRestoreDocument = schedule

    def slotDeletedDocument(self, doc):
        # Let go of the closing document's views while their nodes are alive.
        for record in [record for record in self.views if record.doc == doc.Name]:
            self.views.remove(record)
            self.drop(record)
        for key in [key for key in self.styled if key[0] == doc.Name]:
            _, lines, points, faces, highlights = self.styled.pop(key)
            for recolour in lines + points + faces:
                recolour.detach()
            for highlight in highlights or ():
                highlight.close()
        self.faces = {key: known for key, known in self.faces.items() if key[0] != doc.Name}

    def drop(self, record, restore=False):
        if record.widget is not None and alive(record.view):
            try:
                record.widget.removeEventFilter(self)
            except RuntimeError:
                pass
        record.graphics = record.widget = None
        if restore:
            record.restore()
        else:
            record.forget()

    def eventFilter(self, watched, event):
        # Starting a tool changes a FreeCAD View preference, and FreeCAD then
        # resets its background; put ours back before the frame is drawn.
        if event.type() == QtCore.QEvent.Paint:
            for record in self.views:
                if record.widget is watched:
                    try:
                        record.guard()
                    except (RuntimeError, ReferenceError, AttributeError):
                        pass
        return False

    def current_views(self):
        for name in App.listDocuments():
            document = Gui.getDocument(name)
            if document is None:
                continue
            for view in document.mdiViewsOfType("Gui::View3DInventor"):
                try:
                    yield view, view.getSceneGraph(), name
                except (RuntimeError, ReferenceError, AttributeError):
                    continue

    def refresh(self):
        if not self.running:
            return
        purge_retired()
        if not self.enabled:
            self.restore()
            return
        views = list(self.current_views())
        kept = []
        for record in self.views:
            if any(record.root == root for _, root, _ in views):
                kept.append(record)
            else:
                self.drop(record)
        self.views = kept
        for view, root, name in views:
            record = next((record for record in self.views if record.root == root), None)
            if record is None:
                record = ViewRecord(view, root, name)
                self.views.append(record)
                try:
                    # The viewport's wrapper stays valid while its view's does.
                    record.graphics = view.graphicsView()
                    record.widget = record.graphics.viewport()
                    record.widget.installEventFilter(self)
                except (RuntimeError, AttributeError):
                    record.graphics = record.widget = None
            try:
                record.apply()
            except (RuntimeError, ReferenceError, AttributeError):
                continue
        self.style_objects()

    def style_objects(self):
        params = App.ParamGet(VIEW_PATH)
        line_defaults = (SIMPLECAD_EDGE, unpack(params.GetUnsigned("DefaultShapeLineColor", 421075455)))
        point_defaults = (unpack(params.GetUnsigned("DefaultShapeVertexColor", 421075455)),)
        shape_defaults = face_defaults(params, App.ParamGet(MESH_PATH))
        targets, palette = current_targets(), {}
        present = set()
        for doc in App.listDocuments().values():
            for obj in doc.Objects:
                view = getattr(obj, "ViewObject", None)
                if view is None:
                    continue
                mesh = obj.isDerivedFrom("Mesh::Feature")
                if mesh:
                    # A raw mesh: only its faces, and only in a single colour.
                    faces, line, point, colours = True, None, None, (None, None)
                elif obj.isDerivedFrom("Part::Feature") and hasattr(view, "LineColor") and hasattr(view, "PointColor"):
                    shape = obj.Shape
                    # Counting a dense part's faces takes milliseconds; its hash does not.
                    stamp = None if shape.isNull() else shape.hashCode()
                    key = (doc.Name, obj.Name)
                    known = self.faces.get(key)
                    if known is None or known[0] != stamp:
                        known = self.faces[key] = (stamp, stamp is not None and shape.countElement("Face") > 0)
                    faces = known[1]
                    mode = view.DisplayMode
                    line, point = tuple(view.LineColor[:3]), tuple(view.PointColor[:3])
                    colours = (edge_colour(line, line_defaults, faces, mode),
                               None if faces else edge_colour(point, point_defaults, faces, mode))
                else:
                    continue
                if colours == (None, None) and not faces:
                    continue
                key = (doc.Name, obj.Name)
                entry = self.styled.get(key)
                present.add(key)
                root = view.RootNode
                if entry is not None and not entry[0] == root:
                    self.release_object(key)
                    entry = None
                if entry is None:
                    found = materials(root)
                    entry = (root, [] if mesh else [Recolour(node, self.schedule) for node in found["LineMaterial"]],
                             [] if mesh else [Recolour(node, self.schedule) for node in found["PointMaterial"]],
                             [FaceRecolour(node, self.schedule, mesh) for node in found["ShapeMaterial"]],
                             None if mesh else [])  # face highlights, made when first needed
                    self.styled[key] = entry
                for recolour in entry[1]:
                    recolour.apply(line, colours[0])
                for recolour in entry[2]:
                    recolour.apply(point, colours[1])
                face = self.mesh_face(obj, targets, palette) if mesh else self.face
                for recolour in entry[3]:
                    recolour.apply(face if faces else None, shape_defaults)
        for key in set(self.styled) - present:
            self.release_object(key)
        self.highlight(targets, palette)

    def highlight_colours(self, obj, palette):
        """FreeCAD's (selection, hover) colours in `obj`'s document, cached in `palette`."""
        name = obj.Document.Name
        if name not in palette:
            try:
                palette[name] = surface_display.highlight_colors(obj)
            except (AttributeError, RuntimeError):  # not a 3D view
                palette[name] = None
        return palette[name]

    def mesh_face(self, obj, targets, palette):
        """A raw mesh's face colour: tinted while hovered or selected, as it is whole."""
        selected, hovered = targets.get((obj.Document.Name, obj.Name), ((), ()))
        highlight = self.highlight_colours(obj, palette) if selected or hovered else None
        return mesh_tint(highlight[1 if hovered else 0]) if highlight else self.face

    def highlight(self, targets=None, palette=None):
        """Tint hovered and selected faces of styled objects, FreeCAD's highlight aside."""
        if not self.active():
            return
        if targets is None:
            targets, palette = current_targets(), {}
        defaults = None
        documents = App.listDocuments()
        for key, (root, lines, points, faces, highlights) in self.styled.items():
            selected, hovered = targets.get(key, ((), ()))
            if highlights is None:
                tinted = any(recolour.ours is not None and not close(recolour.ours, self.face)
                             for recolour in faces)
            else:
                tinted = any(highlight.shown and any(highlight.shown[:2]) for highlight in highlights)
                if not self.faces.get(key, (None, False))[1]:
                    selected = hovered = ()  # lines and points only
                else:
                    # Edges and vertices keep FreeCAD's highlight, which shows on them.
                    selected, hovered = ({name for name in names if name == "" or name.startswith("Face")}
                                         for names in (selected, hovered))
            if not (selected or hovered or tinted):
                continue
            obj = documents[key[0]].getObject(key[1]) if key[0] in documents else None
            if obj is None or not obj.isValid():
                continue  # released by the next refresh
            if highlights is None:
                if defaults is None:
                    defaults = face_defaults(App.ParamGet(VIEW_PATH), App.ParamGet(MESH_PATH))
                face = self.mesh_face(obj, targets, palette)
                for recolour in faces:
                    recolour.apply(face, defaults)
                continue
            shown = self.highlight_colours(obj, palette) if selected or hovered else None
            if shown is not None and not highlights:
                highlights += [FaceHighlight(parent, native, source, self.schedule_highlight)
                               for parent, native, source in surface_display.face_parts(root)]
            for highlight in highlights:
                highlight.show(selected, hovered, shown)

    def release_object(self, key):
        root, lines, points, faces, highlights = self.styled.pop(key)
        for highlight in highlights or ():
            highlight.close()
        doc_name, name = key
        obj = App.listDocuments().get(doc_name)
        obj = obj.getObject(name) if obj is not None else None
        view = getattr(obj, "ViewObject", None) if obj is not None else None
        for recolours, prop in ((lines, "LineColor"), (points, "PointColor")):
            native = tuple(getattr(view, prop)[:3]) if view is not None and hasattr(view, prop) else None
            for recolour in recolours:
                recolour.release(native)
        for recolour in faces:
            recolour.release()

    def restore(self):
        for record in self.views:
            self.drop(record, restore=True)
        self.views = []
        for key in list(self.styled):
            self.release_object(key)
        self.faces = {}
