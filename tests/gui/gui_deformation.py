"""Native deformation panels: cached preview, appearance, cancellation and Undo."""
import tempfile,time
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import operations as ops, appearance, visibility
from simplecad.gui.controller import instance
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
V=App.Vector


def run(screenshots=False):
    Gui.activateWorkbench('SimpleCADWorkbench');c=instance();c.cancel(quiet=True)
    doc=App.newDocument('DeformationGUI');doc.UndoMode=1
    obj=ops.new_shape(doc,Part.makeBox(10,10,30),'Bending ear sample')
    materials=appearance.expanded(obj)
    for i,material in enumerate(materials):material.DiffuseColor=(.2+i*.1,.8-i*.1,.3)
    materials[2].Transparency=.43;obj.ViewObject.ShapeAppearance=materials
    visibility.set_hidden(obj,[3])
    colors=appearance.fingerprint(obj.ViewObject.ShapeAppearance,6)
    original=obj.Shape;count=doc.UndoCount;display=obj.ViewObject.DisplayMode
    view=Gui.activeDocument().activeView();view.viewIsometric();view.fitAll()
    def flush():
        for _ in range(3):QtWidgets.QApplication.processEvents();Gui.updateGui()
    def start(shortcut=False):
        Gui.Selection.clearSelection();Gui.Selection.addSelection(obj,'Face6' if len(obj.Shape.Faces)>=6 else 'Face1')
        if shortcut:
            c.focus_view();flush();widget=QtWidgets.QApplication.focusWidget()
            for kind in (QtCore.QEvent.ShortcutOverride,QtCore.QEvent.KeyPress,QtCore.QEvent.KeyRelease):
                QtWidgets.QApplication.sendEvent(widget,QtGui.QKeyEvent(kind,QtCore.Qt.Key_N,QtCore.Qt.NoModifier,'n'))
        else:Gui.runCommand('SimpleCAD_Deform')
        flush();assert c.deform_session is not None and c.tool=='Deform'
        return c.deform_session
    try:
        s=start(True);assert s.update_preview(),s.status.text()
        for widget,value in zip(s.center,V(5,5,30)):widget.setValue(value)
        s.radius.setValue(20);s.delta[0].setValue(3);assert s.update_preview(),s.status.text()
        cached=s.preview.coords;begin=time.perf_counter()
        for value in (1,2,3,4,3):s.delta[0].setValue(value);assert s.update_preview()
        elapsed=(time.perf_counter()-begin)/5
        assert cached is s.preview.coords and obj.Shape.isSame(original)
        assert doc.UndoCount==count and appearance.fingerprint(obj.ViewObject.ShapeAppearance,6)==colors
        c.cancel(quiet=True);flush();assert visibility.hidden_faces(obj)=={3}
        s=start();s.mode.setCurrentIndex(s.mode.findData('Bend'));s.axis.setCurrentIndex(s.axis.findData('Z'))
        s.slider.setValue(60);assert s.update_preview(),s.status.text()
        region=s.target[1];points=list(s.points)
        result,origins=region.build(points)
        if screenshots:
            flush();s.dialog.grab().save(str(ROOT.parent.parent/'work/deformation-panel.png'))
            view.saveImage(str(ROOT.parent.parent/'work/bend-preview.png'),1100,850,'Current')
        started=time.perf_counter();s.apply();flush();apply_ms=(time.perf_counter()-started)*1000
        assert c.deform_session is None
        assert obj.Shape.isValid() and obj.Shape.isClosed() and len(obj.Shape.Faces)>6
        assert doc.UndoCount==count+1 and obj.ViewObject.DisplayMode=='Shaded'
        now=appearance.fingerprint(obj.ViewObject.ShapeAppearance,6)
        assert now==tuple(colors[i] for i in origins)
        assert visibility.hidden_faces(obj)=={i+1 for i,source in enumerate(origins) if source==2}
        doc.undo();doc.recompute();flush()
        assert len(obj.Shape.Faces)==6 and abs(obj.Shape.Volume-3000)<1e-5
        assert obj.ViewObject.DisplayMode==display and visibility.hidden_faces(obj)=={3}
        assert appearance.fingerprint(obj.ViewObject.ShapeAppearance,6)==colors
        doc.redo();doc.recompute();flush()
        # Changing documents or Undo closes the active preview safely.
        s=start();doc.undo();c.check_context();flush();assert c.deform_session is None
        # Invalid bend stays in the panel and changes no document geometry.
        s=start();before=doc.UndoCount;before_shape=obj.Shape
        s.mode.setCurrentIndex(s.mode.findData('Bend'));s.axis.setCurrentIndex(s.axis.findData('Z'))
        s.length.setValue(1);s.angle.setValue(160)
        assert not s.update_preview() and not s.apply_button.isEnabled()
        assert obj.Shape.isSame(before_shape) and doc.UndoCount==before
        c.cancel(quiet=True);flush()
        # Curved face seed can be positioned for a cheek, independently of its
        # single native spherical Face1 boundary/poles.
        sphere=ops.new_shape(doc,Part.makeSphere(10,V(30,0,0)),'Soft cheek')
        obj=sphere;s=start();s.mode.setCurrentIndex(s.mode.findData('Move'))
        for widget,value in zip(s.center,V(40,0,0)):widget.setValue(value)
        s.radius.setValue(12);s.delta[0].setValue(3);assert s.update_preview(),s.status.text()
        s.apply();flush();assert obj.Shape.isClosed() and obj.Shape.isValid()
        with tempfile.TemporaryDirectory() as folder:
            name=obj.Name;path=Path(folder)/'Deformed.FCStd';doc.saveAs(str(path));App.closeDocument(doc.Name)
            doc=App.openDocument(str(path));obj=doc.getObject(name);flush()
            assert obj.Shape.isClosed() and obj.Shape.isValid() and obj.ViewObject.DisplayMode=='Shaded'
        return {'result':'PASS','preview_update_ms':round(elapsed*1000,2),'apply_ms':round(apply_ms,1),'checks':'Shortcut, cached falloff, bend, materials/hidden faces, invalid input, Undo/Redo and save/reopen'}
    finally:
        c.cancel(quiet=True)
        if doc.Name in App.listDocuments():App.closeDocument(doc.Name)
