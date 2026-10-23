"""Per-face alpha during native selection, without changing saved materials.

FreeCAD 1.1's SoBrepFaceSet highlight borrows the first nonzero transparency
from the object. For mixed opacity, draw an unpickable Coin surface instead;
retain the native face set (and its FaceN details) for picking. Both share the
same coordinate indices, including the reversible eye masks.
"""
import FreeCADGui as Gui
from pivy import coin


def mixed_opacity(materials):
    values = [m.Transparency for m in materials]
    return len(values) > 1 and any(value != values[0] for value in values[1:])


def face_parts(root):
    """Native face sets, the materials they inherit, and their direct parents."""
    found = []
    def visit(node, material=None, parent=None):
        kind = str(node.getTypeId().getName())
        if isinstance(node, coin.SoMaterial):
            return node
        if kind == 'SoBrepFaceSet' and material is not None:
            if not any(parent == p and node == n for p, n, _ in found):
                found.append((parent, node, material))
        if hasattr(node, 'getNumChildren'):
            state = material
            for i in range(node.getNumChildren()):
                state = visit(node.getChild(i), state, node)
            if not node.isOfType(coin.SoSeparator.getClassTypeId()):
                return state
        return material
    visit(root)
    return found


def selected_faces(obj, entries=None):
    selected = set()
    for entry in Gui.Selection.getSelectionEx(obj.Document.Name) if entries is None else entries:
        if entry.Object == obj:
            if not entry.SubElementNames:
                return None  # whole object
            selected.update(entry.SubElementNames)
    return selected


def highlight_colors(obj):
    # Read the view's actual colors, including user/theme preferences.
    root = Gui.getDocument(obj.Document.Name).activeView().getSceneGraph()
    search = coin.SoSearchAction()
    search.setType(coin.SoType.fromName('SoFCUnifiedSelection'))
    search.setSearchingAll(True)
    search.apply(root)
    path = search.getPath()
    node = path.getTail() if path else root
    fields = [node.getField(name) for name in ('colorSelection', 'colorHighlight')]
    if all(field is not None for field in fields):
        return tuple(tuple(field.getValue().getValue()) for field in fields)
    # Standard FreeCAD colors if a secondary view lacks a selection root.
    return (0., 1., 0.), (0., 1., 0.)


class Surface:
    def __init__(self, root, changed):
        self.root = root
        self.entries = []
        self.sensors = []
        self.material_states = {}
        self.part_counts = {}
        self.applied_state = {}
        # Source colors and face parts are read again only after their
        # sensors report a change; selection and hover alone never need them.
        self.bases = {}
        self.dirty = True
        self.last = None

        def touched(*unused):
            self.dirty = True
            changed()
        for parent, native, source in face_parts(root):
            # Nodes found below the root are only borrowed; an Undo can delete
            # the object's view provider before this surface is closed.
            for node in (parent, native, source):
                node.ref()
            visual = coin.SoSeparator()
            visual.setName('SimpleCADSurface')
            visual.renderCaching = coin.SoSeparator.OFF
            pick = coin.SoPickStyle()
            pick.style = coin.SoPickStyle.UNPICKABLE
            visual.addChild(pick)
            material = coin.SoMaterial()
            # Keep previews and native material edits connected. Only RGB is
            # tinted for interaction; transparency never changes on hover.
            for name in ('ambientColor', 'specularColor', 'emissiveColor', 'shininess', 'transparency'):
                getattr(material, name).connectFrom(getattr(source, name))
            visual.addChild(material)
            binding = coin.SoMaterialBinding()
            binding.value = coin.SoMaterialBinding.PER_FACE_INDEXED
            visual.addChild(binding)
            mesh = coin.SoIndexedFaceSet()
            mesh.coordIndex.connectFrom(native.coordIndex)
            mesh.normalIndex.connectFrom(native.normalIndex)
            visual.addChild(mesh)
            invisible = coin.SoDrawStyle()
            invisible.style = coin.SoDrawStyle.INVISIBLE
            filled = coin.SoDrawStyle()
            filled.style = coin.SoDrawStyle.FILLED
            index = parent.findChild(native)
            # Keep the native face node a direct child: FreeCAD's detail-path
            # lookup depends on it, and still performs the actual picking.
            parent.insertChild(visual, index)
            parent.insertChild(invisible, index+1)
            parent.insertChild(filled, index+3)
            self.entries.append((parent, native, source, visual, invisible, filled, material, mesh))
            sensor = coin.SoNodeSensor(touched, None)
            sensor.attach(source)
            self.sensors.append(sensor)
            sensor = coin.SoFieldSensor(touched, None)
            sensor.attach(native.getField('partIndex'))
            self.sensors.append(sensor)

    def attached(self):
        current = face_parts(self.root)
        return (len(current) == len(self.entries) and
                all(any(parent == entry[0] and native == entry[1] and source == entry[2]
                        for entry in self.entries) for parent, native, source in current))

    def update(self, selected, hovered, colors):
        selected_key = tuple(sorted(selected)) if selected is not None else None
        state = (selected_key, hovered, colors)
        if not self.dirty and state == self.last:
            return
        dirty, self.dirty, self.last = self.dirty, False, state
        for index, (_, native, source, _, _, _, material, mesh) in enumerate(self.entries):
            if dirty or index not in self.bases:
                parts = tuple(native.getField('partIndex').getValues())
                source_colors = source.diffuseColor.getValues()
                if not source_colors:
                    self.bases.pop(index, None)
                    continue
                base = [tuple(c.getValue()) for c in source_colors]
                self.bases[index] = (parts, tuple(base if len(base) == len(parts) else [base[0]] * len(parts)))
            parts, base_values = self.bases[index]
            count = len(parts)
            last = self.applied_state.get(index)

            # Check if we can do a fast incremental update when only hover changed
            if (last is not None and last[0] == selected_key and last[2] == colors and last[3] == base_values):
                prev_hovered = last[1]
                if prev_hovered != hovered:
                    if prev_hovered and prev_hovered != '*':
                        try:
                            prev_i = int(prev_hovered[4:]) - 1
                            if 0 <= prev_i < count:
                                prev_name = 'Face' + str(prev_i + 1)
                                prev_col = colors[0] if (selected is None or prev_name in selected) else base_values[prev_i]
                                material.diffuseColor.set1Value(prev_i, coin.SbColor(*prev_col))
                        except (ValueError, IndexError):
                            pass
                    if hovered and hovered != '*':
                        try:
                            new_i = int(hovered[4:]) - 1
                            if 0 <= new_i < count:
                                material.diffuseColor.set1Value(new_i, coin.SbColor(*colors[1]))
                        except (ValueError, IndexError):
                            pass
                    elif hovered == '*':
                        for i in range(count):
                            material.diffuseColor.set1Value(i, coin.SbColor(*colors[1]))
                    self.applied_state[index] = (selected_key, hovered, colors, base_values)
                    continue

            values = list(base_values)
            for i in range(count):
                name = 'Face' + str(i + 1)
                if selected is None or name in selected:
                    values[i] = colors[0]
                if hovered in ('*', name):
                    values[i] = colors[1]

            cur_colors = tuple(tuple(c.getValue()) for c in material.diffuseColor.getValues())
            if cur_colors != tuple(values):
                material.diffuseColor.setNum(len(values))
                material.diffuseColor.setValues(values)
            self.applied_state[index] = (selected_key, hovered, colors, base_values)

            # Only transparency / alpha modifications invalidate packed-color VBOs.
            # Normal hover/selection diffuse tinting does not alter mesh geometry or alpha.
            transparency_state = tuple(material.transparency.getValues())
            if self.material_states.get(index) != transparency_state:
                mesh.touch()
                self.material_states[index] = transparency_state

            if self.part_counts.get(index) != parts:
                indices = [i for i, count in enumerate(parts) for _ in range(count)]
                mesh.materialIndex.setNum(len(indices))
                mesh.materialIndex.setValues(indices)
                self.part_counts[index] = parts

    def close(self):
        for sensor in self.sensors:
            sensor.detach()
        self.sensors.clear()
        for parent, native, source, visual, invisible, filled, _, _ in self.entries:
            for node in (visual, invisible, filled):
                if parent.findChild(node) >= 0:
                    parent.removeChild(node)
            for node in (parent, native, source):
                node.unref()
        self.entries.clear()


class Highlights:
    """Selection callbacks update display RGB only, without geometry work."""
    def __init__(self, schedule):
        self.records = {}
        self.schedule = schedule

    def sync(self, obj, enabled):
        key = (obj.Document.Name, obj.Name)
        current = self.records.get(key)
        root = obj.ViewObject.RootNode
        if current is not None and (current[0] != obj or current[1].root != root or
                                    not enabled or not current[1].attached()):
            current[1].close()
            del self.records[key]
            current = None
        if enabled and current is None:
            self.records[key] = (obj, Surface(root, self.schedule))

    def refresh(self, *unused):
        pre = Gui.Selection.getPreselection()
        # One selection read and one scene search per document, not per object.
        documents = {}
        for key, (obj, surface) in list(self.records.items()):
            if not obj.isValid():
                surface.close(); del self.records[key]
                continue
            hovered = ''
            if pre and key == (pre.DocumentName, pre.ObjectName):
                hovered = pre.SubElementNames[0] if pre.SubElementNames else '*'
            if key[0] not in documents:
                documents[key[0]] = (Gui.Selection.getSelectionEx(key[0]), highlight_colors(obj))
            entries, colors = documents[key[0]]
            surface.update(selected_faces(obj, entries), hovered, colors)

    def prune(self, present):
        for key in set(self.records)-present:
            self.records.pop(key)[1].close()

    def changed(self, *unused):
        self.schedule()

    addSelection = changed
    removeSelection = changed
    clearSelection = changed
    setSelection = changed
    setPreselection = changed
    removePreselection = changed
