"""Line split on a 72-face solid: stable materials, native Undo and latency."""
from pathlib import Path
import tempfile
import time
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import operations as ops, appearance as a, locking
from simplecad.modeling import subdivision
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen
from simplecad.gui.qt import QtWidgets, QtGui
try:
    from PySide import QtTest
except ImportError:
    from PySide6 import QtTest
V=App.Vector


def rubik():
    box=Part.makeBox(60,60,60)
    for old in list(box.Faces):
        index=next(i for i,f in enumerate(box.Faces) if (f.CenterOfMass-old.CenterOfMass).Length<1e-6 and abs(f.Area-3600)<1e-6)
        box,_=subdivision.divide(box,index,3,3,pattern='spaced')
    for tool in (Part.makeBox(100,20,20,V(-20,20,20)),Part.makeBox(20,100,20,V(20,-20,20)),Part.makeBox(20,20,100,V(20,20,-20))):
        box=box.cut(tool)
    assert len(box.Faces)==72 and abs(box.Volume-160000)<1e-6
    return box


def run(screenshots=False):
    Gui.activateWorkbench('SimpleCADWorkbench'); c=instance();c.cancel(quiet=True)
    doc=App.newDocument('MaterialMappingSmoke');doc.UndoMode=1
    obj=ops.new_shape(doc,rubik(),'Rubik test')
    red_index=next(i for i,f in enumerate(obj.Shape.Faces) if (f.CenterOfMass-V(10,0,10)).Length<1e-6)
    red=obj.Shape.Faces[red_index]
    target=next(f for f in obj.Shape.Faces if (f.CenterOfMass-V(10,0,30)).Length<1e-6)
    a.commit(a.prepare([(obj,['Face'+str(red_index+1)])]),color=[1,0,0],opacity=57)
    original=a.fingerprint(obj.ViewObject.ShapeAppearance,precision=6)
    view=Gui.activeDocument().activeView()
    normal=red.normalAt(red.ParameterRange[0],red.ParameterRange[2])
    view.getCameraNode().orientation.setValue(*App.Rotation(V(0,0,1),normal).Q);view.fitAll()
    def flush():
        for _ in range(3):QtWidgets.QApplication.processEvents();Gui.updateGui()
        c.seams.refresh();c.faces.refresh()
    def pixel(label):
        Gui.Selection.clearSelection();Gui.Selection.clearPreselection();c.faces.clear_hover();flush()
        view.getCameraNode().orientation.setValue(*App.Rotation(V(0,0,1),normal).Q)
        view.fitAll();view.redraw()
        width,height=view.getSize()
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'view.png');view.saveImage(path,width,height,'Current')
            image=QtGui.QImage(path)
            x,y=screen(view,red.CenterOfMass)
            value=image.pixelColor(round(x),height-1-round(y)).getRgb()[:3]
            if screenshots:image.save(str(ROOT.parent.parent/'work'/('material-'+label+'.png')))
            return value
    def check_red_regions(count):
        values=a.expanded(obj);red_faces=[]
        for i,face in enumerate(obj.Shape.Faces):
            # Exact region overlap, not array positions, determines expectations.
            in_red=abs(face.common(red).Area-face.Area)<1e-6
            material=values[i]
            if in_red:
                red_faces.append(i+1)
                assert tuple(material.DiffuseColor[:3])==(1.,0.,0.)
                assert abs(material.Transparency-.43)<1e-6
            else:
                assert material.DiffuseColor[0]<.9 and material.Transparency==0,(i,material)
        assert len(red_faces)==count,red_faces
        return red_faces
    try:
        Gui.getMainWindow().resize(1400,900)
        QtTest.QTest.qWait(700);flush();view.fitAll();QtTest.QTest.qWait(100)
        flush();baseline_pixel=pixel('before');undo=doc.UndoCount
        assert baseline_pixel[0]>1.3*max(baseline_pixel[1:]), baseline_pixel
        points=[v.Point for v in target.Vertexes];first=points[0];last=max(points,key=lambda p:(p-first).Length)
        # Exercise the active tool's whole commit. The line divides the face,
        # so the commit also ends Line and cleans up its preview and selection.
        c.start('Line');c.anchor=first;c.point=last;c.support=obj
        start=time.perf_counter();c.commit();commit=time.perf_counter()-start
        assert c.tool is None and c.preview is None
        c.cancel(quiet=True)
        flush();complete=time.perf_counter()-start
        assert commit<.6,(commit,complete)
        assert len(obj.Shape.Faces)==73 and doc.UndoCount==undo+1
        assert abs(obj.Shape.Volume-160000)<1e-5 and obj.Shape.isValid()
        check_red_regions(1)
        after_pixel=pixel('after')
        assert all(abs(a-b)<=3 for a,b in zip(baseline_pixel,after_pixel)),(baseline_pixel,after_pixel)
        after=a.fingerprint(obj.ViewObject.ShapeAppearance,precision=6)
        doc.undo();doc.recompute();flush()
        assert len(obj.Shape.Faces)==72
        assert a.fingerprint(obj.ViewObject.ShapeAppearance,precision=6)==original
        doc.redo();doc.recompute();flush()
        assert a.fingerprint(obj.ViewObject.ShapeAppearance,precision=6)==after
        check_red_regions(1)
        # Divide the colored source itself: both children must inherit its style.
        points=[v.Point for v in red.Vertexes];first=points[0];last=max(points,key=lambda p:(p-first).Length)
        ops.draw_line(doc,first,last,preferred=obj);flush();red_faces=check_red_regions(2)
        style=a.fingerprint(obj.ViewObject.ShapeAppearance,precision=6);shape=obj.Shape
        locking.set_locked([(obj,['Face'+str(red_faces[0])])],True)
        try:ops.delete_selection([(obj,['Face'+str(red_faces[0])])])
        except ValueError as error:assert 'locked' in str(error)
        else:raise AssertionError('Locked face deleted')
        flush();assert a.fingerprint(obj.ViewObject.ShapeAppearance,precision=6)==style
        assert len(obj.Shape.Faces)==len(shape.Faces)
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'Materials.FCStd');name=obj.Name
            doc.saveAs(path);App.closeDocument(doc.Name);doc=App.openDocument(path);doc.UndoMode=1;obj=doc.getObject(name)
            view=Gui.activeDocument().activeView();flush();check_red_regions(2)
            restored=a.fingerprint(obj.ViewObject.ShapeAppearance,precision=6)
            assert len(restored)==len(style)
            # Native FCStd stores RGB as 8-bit channels; alpha is independent.
            for old,new in zip(style,restored):
                for old_color,new_color in zip(old[:4],new[:4]):
                    assert all(abs(x-y)<=1/255 for x,y in zip(old_color,new_color))
                assert all(abs(x-y)<1e-6 for x,y in zip(old[4:],new[4:]))
        return 'PASS: 72-face line split %.1f ms; including redraw %.1f ms; stable rendered RGB/alpha; split inheritance; Undo/Redo; lock rollback; FCStd persistence' % (commit*1000,complete*1000)
    finally:
        Gui.Selection.clearSelection();App.closeDocument(doc.Name)
