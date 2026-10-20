"""Actual Qt controls, saved native materials, transparency rendering and Undo."""
from pathlib import Path
import tempfile
import FreeCAD as App
import FreeCADGui as Gui
import Part
import MeshPart
from simplecad import ROOT
from simplecad.document import appearance as a, operations as ops, visibility
from simplecad.gui.controller import instance
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
try:
    from PySide import QtTest
except ImportError:
    from PySide6 import QtTest


def run(screenshots=False):
    Gui.activateWorkbench('SimpleCADWorkbench')
    c=instance(); c.cancel(quiet=True)
    original_docs=set(App.listDocuments())
    doc=App.newDocument('AppearanceSmoke'); doc.UndoMode=1
    obj=ops.new_shape(doc,Part.makeBox(30,30,30),'Appearance block')
    inside=ops.new_shape(doc,Part.makeSphere(8,App.Vector(15,15,15)),'Inner sphere')
    a.commit(a.prepare([(inside,())]),color=[1,.4,.05])
    view=Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(App.Rotation(App.Vector(0,0,1),App.Vector(1,-1,1)).Q)
    view.fitAll()
    main=Gui.getMainWindow(); main.resize(1400,950)
    def flush():
        for _ in range(3): QtWidgets.QApplication.processEvents(); Gui.updateGui()
        c.seams.refresh(); c.faces.refresh()
    def rendered(target):
        flush()
        materials=target.ViewObject.ShapeAppearance
        expected=tuple(m.Transparency for m in materials)
        nodes=a.face_material_nodes(target.ViewObject.RootNode)
        assert nodes, 'No native surface material found'
        for node in nodes:
            assert tuple(node.transparency.getValues())==expected,(node.transparency.getValues(),expected)
    def select(target,names):
        Gui.Selection.clearSelection()
        for name in names or ('',): Gui.Selection.addSelection(target,name)
        flush()
    errors=[]
    def dialog(edit,apply=False,swatch=False):
        def act():
            try:
                panel=QtWidgets.QApplication.activeModalWidget()
                from simplecad.gui.tools.appearance import AppearanceDialog
                assert isinstance(panel,AppearanceDialog),panel
                edit(panel); flush()
                if screenshots:
                    panel.grab().save(str(ROOT.parent.parent/'work/appearance-panel.png'))
                (panel.accept if apply else panel.reject)()
            except BaseException as error:
                errors.append(error)
                if QtWidgets.QApplication.activeModalWidget(): QtWidgets.QApplication.activeModalWidget().reject()
        QtCore.QTimer.singleShot(120,act)
        if swatch:
            b=c.faces; item=b.records[obj.Name]['item']; item.setExpanded(True); b.populate(obj.Name)
            target=item.child(5); b.tree.scrollToItem(target)
            rect=b.tree.visualItemRect(target)
            pos=QtCore.QPoint(b.tree.columnViewportPosition(2)+17,rect.center().y())
            QtTest.QTest.mouseClick(b.tree.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,pos)
            QtTest.QTest.qWait(180)
        else: Gui.runCommand('SimpleCAD_Appearance',0)
        assert not errors,errors
        flush()
    try:
        flush(); b=c.faces
        dock=b.tabs
        while dock and not isinstance(dock,QtWidgets.QDockWidget): dock=dock.parentWidget()
        if dock: dock.show(); dock.raise_()
        b.tabs.setCurrentIndex(0);flush()
        shape=obj.Shape; count=doc.UndoCount; original=a.fingerprint(obj.ViewObject.ShapeAppearance)
        select(obj,('Face6',))
        def preview(panel):
            panel.set_color(QtGui.QColor('#00AACC'))
            panel.opacity.setValue(35)
            expected=a.plan(panel.targets,panel.color_value,panel.opacity_value)[0][1]
            assert abs(expected[5].Transparency-.65)<1e-6
            assert all(expected[i].Transparency==0 for i in range(5))
            assert a.fingerprint(obj.ViewObject.ShapeAppearance)==original, 'Preview must not edit saved materials'
            assert obj.Shape.isSame(shape)
            flush()
            for node in a.face_material_nodes(obj.ViewObject.RootNode):
                assert tuple(node.transparency.getValues())==tuple(m.Transparency for m in expected)
        dialog(preview,swatch=True)
        assert doc.UndoCount==count and a.fingerprint(obj.ViewObject.ShapeAppearance)==original
        assert not visibility.hidden_faces(obj)
        select(obj,('Face6',)); dialog(preview,apply=True,swatch=True)
        assert doc.UndoCount==count+1 and a.describe(obj,6)['opacity']==35
        edited=a.fingerprint(obj.ViewObject.ShapeAppearance)
        doc.undo();flush();assert a.fingerprint(obj.ViewObject.ShapeAppearance)==original
        redo_count=doc.RedoCount
        select(obj,('Face6',));dialog(preview)
        assert doc.RedoCount==redo_count, 'Cancel must preserve prior Redo history'
        doc.redo();rendered(obj);assert a.fingerprint(obj.ViewObject.ShapeAppearance)==edited
        # Face 1 changes native global Transparency: its neighbors must stay opaque.
        a.commit(a.prepare([(obj,('Face1',))]),color=[1,0,0],opacity=15);rendered(obj)
        assert a.describe(obj,2)['opacity']==100
        doc.undo();rendered(obj);doc.redo();rendered(obj)
        # Parent opacity updates every face while keeping their different colors.
        before=[tuple(m.DiffuseColor) for m in a.expanded(obj)]
        select(obj,());dialog(lambda p:p.opacity.setValue(50),apply=True)
        assert [tuple(m.DiffuseColor) for m in a.expanded(obj)]==before
        assert a.describe(obj)['opacity']==50 and a.describe(obj)['color'] is None
        select(obj,('Face1','Face6'))
        dialog(lambda p:p.set_color(QtGui.QColor('#3388EE')),apply=True)
        assert a.describe(obj,1)['color']==a.describe(obj,6)['color']
        assert a.describe(obj,1)['opacity']==50
        a.commit(a.prepare([(obj,('Face6',))]),opacity=0);rendered(obj)
        assert a.describe(obj,6)['opacity']==0 and obj.ViewObject.Visibility
        a.commit(a.prepare([(obj,('Face6',))]),opacity=100);rendered(obj)
        assert a.describe(obj,6)['opacity']==100
        # Existing eyes and transparency are independent and recover together.
        with ops.transaction(doc,'Hide top'):
            visibility.set_hidden(obj,{6})
        obj.ViewObject.Visibility=False;flush();obj.ViewObject.Visibility=True;flush()
        assert visibility.hidden_faces(obj)=={6} and a.describe(obj,6)['opacity']==100
        visibility.set_hidden(obj,set());flush()
        for mode in ('Wireframe','Flat Lines','Flat Lines'):
            obj.ViewObject.DisplayMode=mode;obj.ViewObject.Deviation=.15;rendered(obj)
        Gui.activateWorkbench('PartWorkbench');rendered(obj)
        Gui.activateWorkbench('SimpleCADWorkbench');rendered(obj)
        copied=ops.transform([obj],App.Vector(45,0,0),copy=True)[0]
        assert a.fingerprint(copied.ViewObject.ShapeAppearance)==a.fingerprint(obj.ViewObject.ShapeAppearance)
        copied.ViewObject.Visibility=False
        before=a.fingerprint(obj.ViewObject.ShapeAppearance)
        ops.transform([obj],App.Vector(1,2,3));rendered(obj)
        assert a.fingerprint(obj.ViewObject.ShapeAppearance)==before
        volume=obj.Shape.Volume
        mesh=MeshPart.meshFromShape(Shape=obj.Shape,LinearDeflection=.1,AngularDeflection=.3,Relative=False)
        assert mesh.isSolid() and abs(mesh.Volume-volume)<1e-5
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'Appearance.FCStd');name=obj.Name
            doc.saveAs(path);App.closeDocument(doc.Name);doc=App.openDocument(path);obj=doc.getObject(name)
            # Native FCStd color storage quantizes RGB to 8-bit channels.
            restored=a.fingerprint(obj.ViewObject.ShapeAppearance)
            assert len(restored)==len(before)
            for old,new in zip(before,restored):
                for old_color,new_color in zip(old[:4],new[:4]):
                    assert all(abs(x-y)<=1/255 for x,y in zip(old_color,new_color))
                assert all(abs(x-y)<1e-6 for x,y in zip(old[4:],new[4:]))
            before=restored
            rendered(obj)
        # Invalid targets and values fail before changing any material.
        for color,opacity in ((None,-1),(None,101),(None,float('nan')),([2,0,0],None),(None,True)):
            try:a.commit(a.prepare([(obj,())]),color,opacity);assert False
            except ValueError:pass
        try:a.prepare([(obj,('Edge1',))]);assert False
        except ValueError:pass
        assert a.fingerprint(obj.ViewObject.ShapeAppearance)==before
        # Whole-object color alone retains each face's opacity.
        opacities=[m.Transparency for m in a.expanded(obj)]
        a.commit(a.prepare([(obj,())]),color=[.2,.6,.9]);rendered(obj)
        assert [m.Transparency for m in a.expanded(obj)]==opacities
        # Verify rendered pixels, not only native/Coin fields: restored views
        # can otherwise keep drawing old material colors from their cache.
        view=Gui.activeDocument().activeView()
        # Resolve by label because references from the closed document expired.
        inside=next(o for o in doc.Objects if o.Label=='Inner sphere')
        inside.ViewObject.Visibility=False
        view.getCameraNode().orientation.setValue(0.,0.,0.,1.)
        view.fitAll();flush()
        def pixel():
            flush();view.redraw()
            with tempfile.TemporaryDirectory() as folder:
                path=str(Path(folder)/'surface.png')
                view.saveImage(path,400,400,'Current')
                return QtGui.QImage(path).pixelColor(200,200)
        a.commit(a.prepare([(obj,())]),opacity=0)
        a.commit(a.prepare([(obj,('Face6',))]),color=[0,1,0],opacity=100)
        Gui.Selection.clearSelection();Gui.Selection.clearPreselection();c.faces.clear_hover()
        rendered(obj)
        green=pixel();assert green.green()>2*max(green.red(),green.blue()),green.getRgb()
        def red_preview(panel):
            panel.set_color(QtGui.QColor('#FF0000'))
            red=pixel();assert red.red()>2*max(red.green(),red.blue()),red.getRgb()
        select(obj,('Face6',));dialog(red_preview)
        Gui.Selection.clearSelection();Gui.Selection.clearPreselection();c.faces.clear_hover()
        assert pixel()==green, 'Cancel did not restore the rendered color'
        def clear_preview(panel):
            panel.opacity.setValue(0)
            clear=pixel();assert max(clear.red(),clear.green(),clear.blue())-min(clear.red(),clear.green(),clear.blue())<5,clear.getRgb()
        select(obj,('Face6',));dialog(clear_preview)
        Gui.Selection.clearSelection();Gui.Selection.clearPreselection();c.faces.clear_hover()
        assert pixel()==green, 'Cancel did not restore the rendered opacity'
        inside.ViewObject.Visibility=True
        # Render a clear cutaway preview with a colored object inside.
        a.commit(a.prepare([(obj,())]),color=[.2,.6,.9])
        a.commit(a.prepare([(obj,())]),opacity=22)
        a.commit(a.prepare([(obj,('Face6',))]),color=[.15,.8,.55],opacity=65)
        rendered(obj);view=Gui.activeDocument().activeView()
        Gui.Selection.clearSelection();Gui.Selection.clearPreselection();c.faces.clear_hover()
        view.viewIsometric();QtTest.QTest.qWait(600)
        view.fitAll();flush()
        if screenshots:
            view.saveImage(str(ROOT.parent.parent/'work/appearance-model.png'),1000,850,'Current')
            c.faces.records[obj.Name]['item'].setExpanded(True);c.faces.populate(obj.Name);flush()
            c.faces.tree.grab().save(str(ROOT.parent.parent/'work/appearance-tree.png'))
        return 'PASS: face/object color and opacity; real swatch/dialog; preview cancel; Undo/Redo; material alpha; eyes; copy/move; save/reopen; unchanged printable geometry'
    finally:
        c.cancel(quiet=True)
        for name in set(App.listDocuments())-original_docs:App.closeDocument(name)
