"""Transient face tree mapping rows to native FaceN selections.

Keep Python rows out of Gui::TreeWidget: its C++ child traversal expects
DocumentObjectItem instances. Use an adjacent Qt tree, without document objects.
"""
import FreeCAD as App
import FreeCADGui as Gui
from .. import ROOT
from ..mesh.conversion import is_mesh
from ..document import visibility, operations, appearance, locking
from .qt import QtCore, QtGui, QtWidgets

ROLE = QtCore.Qt.UserRole


def alive(widget):
    if widget is None:
        return False
    try:
        widget.objectName()
        return True
    except RuntimeError:
        return False


def runs(rows):
    """First and last of each consecutive run in sorted row numbers."""
    result = []
    for row in rows:
        if result and row == result[-1][1] + 1:
            result[-1][1] = row
        elif not result or row != result[-1][1]:
            result.append([row, row])
    return [tuple(run) for run in result]


class FaceBrowser(QtCore.QObject):
    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.running = False
        self.tree = self.tabs = self.native = self.dock = None
        self.records = {}
        self.doc_name = None
        self.busy = False
        self.chosen = self.hovered = None
        self.invalidated = set()
        self.eye_pressed = None
        self.locks = {state: QtGui.QIcon(str(ROOT / 'Resources' / 'icons' / ('lock-'+state+'.svg'))) for state in ('open','closed')}
        self.lock_pressed = None
        self.swatch_pressed = None
        self.swatches = {}
        self.face_icon = QtGui.QIcon(str(ROOT / 'Resources/icons/face.svg'))
        self.eyes = {name: QtGui.QIcon(str(ROOT / ('Resources/icons/eye-' + name + '.svg')))
                     for name in ('open', 'closed')}
        self.pending = QtCore.QTimer(self)
        self.pending.setSingleShot(True)
        self.pending.timeout.connect(self.refresh)
        self.poll = QtCore.QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self.refresh)

    def start(self):
        if self.running:
            return
        self.running = True
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setObjectName('SimpleCADFaceTree')
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(4)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        self.tree.setColumnWidth(1, 34)
        self.tree.header().setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        self.tree.setColumnWidth(2, 34)
        self.tree.header().setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)
        self.tree.setColumnWidth(3, 34)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setMouseTracking(True)
        self.tree.setToolTip('Expand a shape to select its faces. Ctrl/⌘ adds faces; Shift selects a range. Delete removes selected faces; Undo restores them.')
        self.tree.itemExpanded.connect(self.expand)
        self.tree.itemSelectionChanged.connect(self.select)
        self.tree.itemEntered.connect(self.hover)
        self.tree.viewport().installEventFilter(self)
        self.tree.installEventFilter(self)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        main = Gui.getMainWindow()
        self.native = next((tree for tree in main.findChildren(QtWidgets.QTreeWidget)
                            if tree.metaObject().className() == 'Gui::TreeWidget'
                            and tree.parentWidget().layout() is not None), None)
        if self.native is not None:
            parent = self.native.parentWidget()
            self.tabs = QtWidgets.QTabBar(parent)
            self.tabs.setObjectName('SimpleCADModelTabs')
            self.tabs.setExpanding(False)
            self.tabs.addTab('Faces'); self.tabs.addTab('Objects')
            layout = parent.layout()
            index = layout.indexOf(self.native)
            layout.insertWidget(index, self.tabs)
            layout.insertWidget(index + 1, self.tree)
            self.tabs.currentChanged.connect(self.switch_view)
            self.switch_view(0)
        else:
            self.dock = QtWidgets.QDockWidget('SimpleCAD Faces', main)
            self.dock.setObjectName('SimpleCADFacesDock')
            self.dock.setWidget(self.tree)
            main.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.dock)
        App.addDocumentObserver(self)
        Gui.Selection.addObserver(self)
        self.poll.start()
        self.refresh()

    def switch_view(self, index):
        self.clear_hover()
        self.tree.setVisible(index == 0)
        self.native.setVisible(index == 1)

    def stop(self):
        if not self.running:
            return
        self.running = False
        self.pending.stop(); self.poll.stop()
        App.removeDocumentObserver(self)
        Gui.Selection.removeObserver(self)
        self.clear_hover()
        if alive(self.tabs) and alive(self.native):
            parent = self.tabs.parentWidget()
            parent.layout().removeWidget(self.tabs)
            parent.layout().removeWidget(self.tree)
            self.native.show()
            self.tree.deleteLater()
            self.tabs.deleteLater()
        elif alive(self.tabs):
            if alive(self.tree):
                self.tree.deleteLater()
            self.tabs.deleteLater()
        elif alive(self.dock):
            Gui.getMainWindow().removeDockWidget(self.dock)
            self.dock.deleteLater()
        self.tree = self.tabs = self.native = self.dock = None
        self.records.clear(); self.doc_name = self.chosen = None
        self.invalidated.clear()

    def contains(self, widget):
        return bool(alive(self.tree) and widget and (widget == self.tree or self.tree.isAncestorOf(widget)))

    def schedule(self, *unused):
        if self.running and not self.pending.isActive():
            self.pending.start(0)

    slotCreatedObject = schedule
    slotDeletedObject = schedule
    slotRecomputedDocument = schedule
    slotUndoDocument = schedule
    slotRedoDocument = schedule
    slotFinishRestoreDocument = schedule
    slotActivateDocument = schedule
    slotDeletedDocument = schedule
    addSelection = schedule
    removeSelection = schedule
    clearSelection = schedule
    setSelection = schedule

    def slotChangedObject(self, obj, prop):
        if self.running and prop == 'Shape' and obj.Document.Name == self.doc_name:
            # Record face references during the change notification, then clear
            # them after native providers finish updating their topology maps.
            for key in self.selection_keys():
                if key[:2] == (self.doc_name, obj.Name) and key[2].startswith('Face'):
                    self.invalidated.add(key)
            if self.chosen and self.chosen[:2] == (self.doc_name, obj.Name):
                self.chosen = None
            self.clear_hover()
        self.schedule()

    def refresh(self):
        if not self.running or self.busy:
            return
        if not alive(self.tree) or (self.native is not None and not alive(self.native)):
            # FreeCAD can recreate Model/Tree panels when layout settings change.
            self.stop(); self.start()
            return
        self.busy = True
        blocker = QtCore.QSignalBlocker(self.tree)
        try:
            doc = App.ActiveDocument
            name = doc.Name if doc else None
            # Native view providers can restore the old selection later in the
            # same shape-change notification. Clear those old refs after it ends.
            for owner in {key[:2] for key in self.invalidated}:
                if doc and owner[0] == name:
                    obj = doc.getObject(owner[1])
                    selected = {key for key in self.selection_keys() if key[:2] == owner}
                    if obj and selected.intersection(self.invalidated):
                        # OCC's mapped subelement reference can differ from the
                        # displayed FaceN after replacement. Remove by object,
                        # then restore any unaffected selections on that owner.
                        Gui.Selection.removeSelection(obj)
                        for key in selected - self.invalidated:
                            Gui.Selection.addSelection(*key)
            self.invalidated.clear()
            if name != self.doc_name or not self.tree.topLevelItemCount():
                self.clear_hover()
                self.tree.clear(); self.records.clear(); self.chosen = None
                self.doc_name = name
                self.root = QtWidgets.QTreeWidgetItem(self.tree, [doc.Label if doc else 'No model open'])
                self.root.setFlags(QtCore.Qt.ItemIsEnabled)
                self.root.setExpanded(True)
            if doc is None:
                return
            self.root.setText(0, doc.Label)
            present = set()
            for obj in doc.Objects:
                mesh = is_mesh(obj)
                if not mesh and (not hasattr(obj, 'Shape') or obj.Shape.isNull()):
                    continue
                present.add(obj.Name)
                shape = None if mesh else obj.Shape
                record = self.records.get(obj.Name)
                if record is None:
                    item = QtWidgets.QTreeWidgetItem(self.root)
                    item.setData(0, ROLE, (name, obj.Name, ''))
                    item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                    record = self.records[obj.Name] = {'item': item, 'shape': None}
                item = record['item']
                record['mesh'] = mesh
                if mesh:
                    item.setChildIndicatorPolicy(QtWidgets.QTreeWidgetItem.DontShowIndicator)
                    item.setText(0, obj.Label + ' (mesh)')
                    item.setIcon(0, obj.ViewObject.Icon)
                    item.setToolTip(0, '%s triangles · Right-click → Mesh → Stretch mesh / Move region…, Split mesh… or Make mesh editable…' % format(obj.Mesh.CountFacets, ','))
                    self.update_eyes(obj, item)
                    continue
                item.setText(0, obj.Label)
                item.setIcon(0, obj.ViewObject.Icon)
                item.setForeground(0, self.tree.palette().brush(QtGui.QPalette.Text if obj.ViewObject.Visibility else QtGui.QPalette.PlaceholderText))
                if record['shape'] is None or not shape.isSame(record['shape']):
                    if self.chosen and self.chosen[:2] == (name, obj.Name):
                        self.chosen = None
                    record['shape'] = shape
                    record['face_count'] = shape.countElement('Face')
                    record.pop('style', None)
                    if item.childCount():
                        # Row i always shows Face i+1. Keep the rows and only
                        # add or drop the difference: recreating thousands of
                        # them after every edit stalls the window.
                        self.resize_rows(obj.Name)
                    elif item.isExpanded():
                        self.populate(obj.Name)
                count = record['face_count']
                item.setChildIndicatorPolicy(QtWidgets.QTreeWidgetItem.ShowIndicator if count else QtWidgets.QTreeWidgetItem.DontShowIndicator)
                item.setToolTip(0, '%s · %d faces%s\nExpand to select individual faces. Click an eye to show or hide; Space toggles selected rows.' %
                               (obj.Label, count, '' if obj.ViewObject.Visibility else ' · hidden'))
                self.update_eyes(obj, item)
            for key in set(self.records) - present:
                item = self.records.pop(key)['item']
                self.root.takeChild(self.root.indexOfChild(item))
            self.sync_selection()
        finally:
            del blocker
            self.busy = False

    def populate(self, name):
        record = self.records[name]
        item = record['item']
        if item.childCount() or record.get('mesh'):
            return
        self.add_rows(name, item, 1, record['face_count'])
        obj = App.ActiveDocument.getObject(name)
        if obj: self.update_eyes(obj, item)

    def add_rows(self, name, item, first, last):
        for i in range(first, last + 1):
            sub = 'Face%d' % i
            child = QtWidgets.QTreeWidgetItem(item, ['Face %d' % i])
            child.setData(0, ROLE, (self.doc_name, name, sub))
            child.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            child.setIcon(0, self.face_icon)
            # Compute geometric details only for the row being inspected.
            # Integrating thousands of face areas on every edit stalls redraw.
            child.setToolTip(0, 'Click to select; hover to locate it in the model.')

    def resize_rows(self, name):
        record = self.records[name]
        item, count = record['item'], record['face_count']
        for i in range(item.childCount() - 1, count - 1, -1):
            item.takeChild(i)
        rows = record.get('rows')
        if rows is not None:
            del rows[count:]
        self.add_rows(name, item, item.childCount() + 1, count)

    def update_eyes(self, obj, item):
        if is_mesh(obj):
            visible = obj.ViewObject.Visibility
            item.setIcon(1, self.eyes['open' if visible else 'closed'])
            item.setToolTip(1, 'Hide mesh' if visible else 'Show mesh')
            item.setForeground(0, self.tree.palette().brush(QtGui.QPalette.Text if visible else QtGui.QPalette.PlaceholderText))
            return
        record = self.records.get(obj.Name)
        style = (item.childCount(), obj.ViewObject.Visibility,
                 getattr(obj.ViewObject, visibility.PROPERTY, ''), locking.whole(obj),
                 getattr(obj, locking.FACES, ''),
                 appearance.fingerprint(getattr(obj.ViewObject, 'ShapeAppearance', ())),
                 self.tree.palette().cacheKey())
        if record is not None and record.get('style') == style:
            return
        if record is not None:
            record['style'] = style
        locked = locking.whole(obj)
        protected, stale = locking.state(obj)
        self.update_lock(item, locked or stale, False)
        visible = obj.ViewObject.Visibility
        hidden = visibility.hidden_faces(obj)
        whole, faces = appearance.describe_all(obj)
        item.setIcon(1, self.eyes['open' if visible else 'closed'])
        item.setToolTip(1, 'Hide object' if visible else 'Show object (remember hidden faces)')
        item.setData(1, QtCore.Qt.AccessibleTextRole, 'Object visible' if visible else 'Object hidden')
        self.update_swatch(item, whole)
        # Restyle only rows whose state changed: an edit usually touches a
        # few faces of thousands, and each row takes several Qt calls.
        palette = self.tree.palette()
        rows = record.setdefault('rows', []) if record is not None else []
        if record is not None and record.get('rows_palette') != palette.cacheKey():
            record['rows_palette'] = palette.cacheKey()
            rows.clear()
        brushes = {True: palette.brush(QtGui.QPalette.Text), False: palette.brush(QtGui.QPalette.PlaceholderText)}
        for i in range(item.childCount()):
            swatch = faces[i] if i < len(faces) else None
            shown = visible and i+1 not in hidden
            state = (locked or stale or i+1 in protected, locked or stale, shown, visible,
                     None if swatch is None else (tuple(swatch['color']) if swatch['color'] else None, swatch['opacity']))
            if i < len(rows) and rows[i] == state:
                continue
            child = item.child(i)
            self.update_lock(child, state[0], state[1])
            child.setIcon(1, self.eyes['open' if shown else 'closed'])
            child.setForeground(0, brushes[shown])
            child.setToolTip(1, 'Hide face' if shown else 'Show face' + (' (and its object)' if not visible else ''))
            child.setData(1, QtCore.Qt.AccessibleTextRole, 'Face visible' if shown else 'Face hidden')
            self.update_swatch(child, swatch)
            if i < len(rows):
                rows[i] = state
            else:
                rows.append(state)

    def update_lock(self, item, locked, inherited):
        item.setIcon(3, self.locks['closed' if locked else 'open'])
        text = 'Object locked · Unlock the object first' if inherited else ('Unlock geometry' if locked else 'Lock geometry')
        item.setToolTip(3, text)
        item.setData(3, QtCore.Qt.AccessibleTextRole, text)

    def toggle_locks(self, keys, locked=None):
        hits = [(key, self.resolve(key)) for key in keys]
        if not hits or any(hit is None for _, hit in hits):
            self.refresh(); return
        if any(is_mesh(hit[0]) for _, hit in hits):
            return
        self.controller.cancel(quiet=True)
        self.clear_hover()
        targets = [(hit[0], [key[2]] if key[2] else []) for key, hit in hits]
        if locked is None:
            key, hit = hits[0]
            indices, stale = locking.state(hit[0])
            locked = not (locking.whole(hit[0]) or stale or (key[2] and int(key[2][4:]) in indices))
        try:
            locking.set_locked(targets, locked)
            self.refresh()
            self.controller.message('Geometry locked' if locked else 'Geometry unlocked')
        except Exception as error:
            self.controller.report(error)

    def update_swatch(self, item, state):
        if state is None:
            item.setIcon(2, QtGui.QIcon()); return
        color, opacity = state['color'], state['opacity']
        key = (tuple(color) if color else None, opacity)
        if key not in self.swatches:
            pix = QtGui.QPixmap(18, 18); pix.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pix)
            for x in range(0, 18, 6):
                for y in range(0, 18, 6):
                    painter.fillRect(x, y, 6, 6, QtGui.QColor('#eeeeee' if (x+y)//6 % 2 else '#777777'))
            if color is not None:
                fill = QtGui.QColor.fromRgbF(*color, (opacity if opacity is not None else 60)/100)
                painter.fillRect(1, 1, 16, 16, fill)
            if color is None or opacity is None:
                painter.setPen(QtGui.QColor('#202020')); painter.drawLine(1, 16, 16, 1)
            painter.setPen(QtGui.QColor('#8a959b')); painter.drawRect(0, 0, 17, 17); painter.end()
            if len(self.swatches) > 256: self.swatches.clear()
            self.swatches[key] = QtGui.QIcon(pix)
        item.setIcon(2, self.swatches[key])
        color_text = QtGui.QColor.fromRgbF(*color).name().upper() if color else 'Mixed colors'
        opacity_text = ('%g%% opacity' % opacity) if opacity is not None else 'Mixed opacity'
        item.setToolTip(2, color_text+' · '+opacity_text+'\nClick to set color and opacity.')
        item.setData(2, QtCore.Qt.AccessibleTextRole, 'Color and opacity: '+color_text+', '+opacity_text)

    def edit_appearance(self, item):
        hit = self.resolve(item.data(0, ROLE))
        if hit and is_mesh(hit[0]):
            return
        if not item.isSelected():
            self.tree.clearSelection(); item.setSelected(True)
        self.clear_hover()
        self.controller.start('Appearance')

    def toggle_eyes(self, keys):
        targets = [(key, self.resolve(key)) for key in keys]
        if not targets or any(hit is None for _, hit in targets):
            self.refresh(); return
        self.controller.cancel(quiet=True)
        self.clear_hover()
        owners = {key[:2] for key, _ in targets if not key[2]}
        try:
            for key, (obj, _) in targets:
                if key[2] and key[:2] not in owners:
                    operations.editable(obj)
            with operations.transaction(App.ActiveDocument, 'Toggle visibility'):
                for key, (obj, _) in targets:
                    if not key[2]:
                        obj.ViewObject.Visibility = not obj.ViewObject.Visibility
                    elif key[:2] not in owners:
                        hidden = visibility.hidden_faces(obj)
                        index = int(key[2][4:])
                        if index in hidden or not obj.ViewObject.Visibility:
                            hidden.discard(index)
                            obj.ViewObject.Visibility = True
                        else:
                            hidden.add(index)
                        visibility.set_hidden(obj, hidden)
            # Clear cached highlights that could draw a hidden element on top.
            for obj in {hit[0] for _, hit in targets}:
                selected = [key for key in self.selection_keys() if key[:2] == (obj.Document.Name, obj.Name)]
                Gui.Selection.removeSelection(obj)
                for key in selected:
                    if key[2] and visibility.element_visible(obj, key[2]):
                        Gui.Selection.addSelection(*key)
            self.controller.seams.refresh()
            self.refresh()
            self.controller.message('Visibility updated · Geometry unchanged · Click the eye again to restore')
        except Exception as error:
            self.controller.report(error)

    def expand(self, item):
        key = item.data(0, ROLE)
        if key and not key[2] and key[1] in self.records:
            self.populate(key[1])

    @staticmethod
    def selection_keys():
        result = set()
        for selection in Gui.Selection.getSelectionEx():
            for sub in selection.SubElementNames or ('',):
                result.add((selection.DocumentName, selection.ObjectName, sub))
        return result

    def sync_selection(self):
        keys = self.selection_keys()
        if self.chosen not in keys:
            self.chosen = None
        desired = set()
        selected = QtCore.QItemSelection()
        for name, record in self.records.items():
            item = record['item']
            owner = (self.doc_name, name, '')
            if owner in keys:
                desired.add(owner)
                index = self.tree.indexFromItem(item)
                selected.select(index, index)
            face_keys = {key for key in keys if key[:2] == (self.doc_name, name) and key[2].startswith('Face')}
            if face_keys:
                self.populate(name)
                item.setExpanded(True)
            # Row i shows Face i+1, so the selected rows follow from the keys
            # alone; reading every row on each poll scales with the face count.
            # One selection range per consecutive run, rather than thousands
            # of setSelected calls rebuilding Qt's selection on every poll.
            rows = []
            for key in face_keys:
                try:
                    row = int(key[2][4:]) - 1
                except ValueError:
                    continue
                if 0 <= row < item.childCount():
                    rows.append(row)
                    desired.add(key)
            rows.sort()
            for start, end in runs(rows):
                selected.select(self.tree.indexFromItem(item.child(start)), self.tree.indexFromItem(item.child(end)))
        current = {tuple(item.data(0, ROLE)) for item in self.tree.selectedItems() if item.data(0, ROLE)}
        if current != desired:
            self.tree.selectionModel().select(selected, QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)

    def resolve(self, key):
        if not key or key[0] != self.doc_name or not App.ActiveDocument or App.ActiveDocument.Name != key[0]:
            return None
        obj = App.ActiveDocument.getObject(key[1])
        record = self.records.get(key[1])
        if obj and record and record.get('mesh') and is_mesh(obj):
            return (obj, obj.Mesh) if not key[2] else None
        if not obj or not record or not hasattr(obj, 'Shape') or not obj.Shape.isSame(record['shape']):
            self.schedule()
            return None
        try:
            return obj, obj.Shape.getElement(key[2]) if key[2] else obj.Shape
        except (RuntimeError, ValueError):
            return None

    def select(self):
        if self.busy:
            return
        keys = [tuple(item.data(0, ROLE)) for item in self.tree.selectedItems() if item.data(0, ROLE)]
        owners = {key[:2] for key in keys if not key[2]}
        keys = [key for key in keys if not key[2] or key[:2] not in owners]
        if any(self.resolve(key) is None for key in keys):
            self.refresh()
            return
        self.busy = True
        try:
            self.controller.cancel(quiet=True)
            self.clear_hover()
            Gui.Selection.clearSelection()
            for key in keys:
                Gui.Selection.addSelection(*key)
            self.chosen = keys[0] if len(keys) == 1 and keys[0][2] else None
        finally:
            self.busy = False
        self.schedule()

    def selected_face(self):
        if self.chosen and self.selection_keys() == {self.chosen}:
            return self.resolve(self.chosen)
        return None

    def hover(self, item, column=0):
        key = item.data(0, ROLE)
        self.clear_hover()
        hit = self.resolve(key)
        if column == 0 and hit and visibility.element_visible(hit[0], key[2]):
            if key[2].startswith('Face'):
                face = hit[1]
                item.setToolTip(0, '%s · %s\nArea: %.4g mm²\nClick to select; hover to locate it in the model.' %
                                (key[2], type(face.Surface).__name__, face.Area))
            Gui.Selection.setPreselection(hit[0], key[2])
            self.hovered = tuple(key)

    def clear_hover(self, *unused):
        if self.hovered:
            pre = Gui.Selection.getPreselection()
            if pre and (pre.DocumentName, pre.ObjectName, next(iter(pre.SubElementNames), '')) == self.hovered:
                Gui.Selection.clearPreselection()
            self.hovered = None

    def eventFilter(self, watched, event):
        if alive(self.tree) and watched == self.tree and event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Space:
            if not event.isAutoRepeat():
                self.toggle_eyes([tuple(item.data(0, ROLE)) for item in self.tree.selectedItems() if item.data(0, ROLE)])
            return True
        if alive(self.tree) and watched == self.tree.viewport():
            if event.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseButtonRelease) and event.button() == QtCore.Qt.LeftButton:
                pos = event.pos()
                if self.tree.columnAt(pos.x()) == 3:
                    item = self.tree.itemAt(pos)
                    key = tuple(item.data(0, ROLE)) if item and item.data(0, ROLE) else None
                    if event.type() == QtCore.QEvent.MouseButtonPress:
                        self.lock_pressed = key
                    elif event.type() == QtCore.QEvent.MouseButtonRelease:
                        if key and key == self.lock_pressed: self.toggle_locks([key])
                        self.lock_pressed = None
                    return True
                self.lock_pressed = None
                if self.tree.columnAt(pos.x()) == 2:
                    item = self.tree.itemAt(pos)
                    key = tuple(item.data(0, ROLE)) if item and item.data(0, ROLE) else None
                    if event.type() == QtCore.QEvent.MouseButtonPress:
                        self.swatch_pressed = key
                    elif event.type() == QtCore.QEvent.MouseButtonRelease:
                        if key and key == self.swatch_pressed:
                            # Open the modal panel after this mouse event ends.
                            QtCore.QTimer.singleShot(0, lambda item=item: self.edit_appearance(item))
                        self.swatch_pressed = None
                    return True
                self.swatch_pressed = None
                if self.tree.columnAt(pos.x()) == 1:
                    item = self.tree.itemAt(pos)
                    key = tuple(item.data(0, ROLE)) if item and item.data(0, ROLE) else None
                    if event.type() == QtCore.QEvent.MouseButtonPress:
                        self.eye_pressed = key
                    elif event.type() == QtCore.QEvent.MouseButtonRelease:
                        if key and key == self.eye_pressed: self.toggle_eyes([key])
                        self.eye_pressed = None
                    return True
                self.eye_pressed = None
        if alive(self.tree) and watched == self.tree.viewport() and event.type() == QtCore.QEvent.Leave:
            self.clear_hover()
        return False

    def context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None or not item.data(0, ROLE):
            return
        if not item.isSelected():
            self.tree.clearSelection(); item.setSelected(True)
        menu = QtWidgets.QMenu(self.tree)
        eye = menu.addAction('Show / hide')
        eye.triggered.connect(lambda: self.toggle_eyes([tuple(row.data(0, ROLE)) for row in self.tree.selectedItems() if row.data(0, ROLE)]))
        hit = self.resolve(item.data(0, ROLE))
        if hit and not is_mesh(hit[0]):
            for label, locked in (('Lock geometry', True), ('Unlock geometry', False)):
                action = menu.addAction(label)
                action.triggered.connect(lambda checked=False, locked=locked: self.toggle_locks([tuple(row.data(0, ROLE)) for row in self.tree.selectedItems() if row.data(0, ROLE)], locked))
        menu.addSeparator()
        from .commands import populate_context_menu
        populate_context_menu(menu)
        menu.exec(self.tree.viewport().mapToGlobal(pos))
        menu.deleteLater()
