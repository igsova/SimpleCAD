"""Mesh Region timings on a dense 17,400-triangle STL-like part (FreeCAD GUI).

    SC_GUI_TESTS=bench_mesh_region FreeCAD scripts/run_gui_tests.py

Builds a thin-walled skirt with a drilled flange and radial holes (float32
STL coordinates, like an imported scan), then times the steps a user waits
for. Prints one 'RESULTS {...}' JSON line, in milliseconds. Uses a temporary
document; set SC_BENCH_STL to time another STL instead. Not a pass/fail test.
"""
import json
import math
import os
import tempfile
import time
from pathlib import Path
import numpy as np
import FreeCAD as App
import FreeCADGui as Gui
import Mesh
import MeshPart
import Part
from simplecad.gui.controller import instance
from simplecad.gui.qt import QtWidgets


def skirt(path):
    body = Part.makeCylinder(60, 30).cut(Part.makeCylinder(56, 30, App.Vector(0, 0, 2)))
    body = body.fuse(Part.makeBox(150, 20, 4, App.Vector(-75, -10, 0)))
    for x in (-65, -50, 50, 65):
        body = body.cut(Part.makeCylinder(2.5, 10, App.Vector(x, 0, -1)))
    for angle in range(0, 360, 45):
        d = App.Vector(math.cos(math.radians(angle)), math.sin(math.radians(angle)), 0)
        body = body.cut(Part.makeCylinder(4, 10, d*54+App.Vector(0, 0, 15), d))
    mesh = MeshPart.meshFromShape(Shape=body.removeSplitter(), LinearDeflection=.005,
                                  AngularDeflection=.05, Relative=False)
    mesh.write(path)  # STL stores float32 coordinates.
    return Mesh.Mesh(path)


def run():
    results = {}

    def timed(name, action, repeat=1):
        best = None
        for _ in range(repeat):
            start = time.perf_counter(); value = action()
            elapsed = (time.perf_counter()-start)*1000
            best = elapsed if best is None else min(best, elapsed)
        results[name] = round(best, 1)
        return value

    def wait(predicate, limit=120):
        end = time.monotonic()+limit
        while not predicate() and time.monotonic() < end:
            QtWidgets.QApplication.processEvents(); time.sleep(.002)

    Gui.activateWorkbench('SimpleCADWorkbench'); c = instance(); c.cancel(quiet=True)
    doc = App.newDocument('MeshRegionBenchmark'); doc.UndoMode = 1
    try:
        with tempfile.TemporaryDirectory() as folder:
            mesh = Mesh.Mesh(os.environ['SC_BENCH_STL']) if os.environ.get('SC_BENCH_STL') else skirt(str(Path(folder)/'skirt.stl'))
        source = doc.addObject('Mesh::Feature', 'Skirt'); source.Mesh = mesh
        source.Placement = App.Placement(App.Vector(5, -3, 2), App.Rotation(App.Vector(0, 0, 1), 10))
        doc.recompute(); view = Gui.activeDocument().activeView(); view.viewIsometric(); view.fitAll(); Gui.updateGui()
        results['triangles'] = source.Mesh.CountFacets
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(source)
        timed('start tool', lambda: c.start('MeshRegion'))
        s = c.mesh_region_session; t = s.topology; Gui.updateGui()
        # The flange top beside a mounting hole, or the largest flat patch.
        flat = np.flatnonzero(t.normals[:, 2] > .999)
        seed = int(flat[np.argmin(t.centers[flat, 0])]) if len(flat) else 0
        timed('pick ray', lambda: t.pick(t.centers[seed]+(0, 0, 50), (0, 0, -1)), 5)
        region = timed('flat region', lambda: t.region(seed+1, 'Flat'), 5)
        results['selected'] = len(region)
        s.selected = set(region); s.changed()
        timed('first preview', s.update_preview)
        s.delta[1].setValue(-3.0); QtWidgets.QApplication.processEvents()
        timed('preview (cached plan)', s.update_preview, 5)
        timed('redraw', lambda: (view.redraw(), Gui.updateGui()), 3)
        for rings in (1, 3) if hasattr(s, 'collision') else ():
            s.rings.setValue(rings); s.update_preview()
            start = last = time.perf_counter(); gap = 0
            while time.perf_counter()-start < 60:
                QtWidgets.QApplication.processEvents(); now = time.perf_counter()
                gap = max(gap, now-last); last = now
                if s.collision is not None and (s.collision[2] is None or s.collision[3] is not None): break
                time.sleep(.002)
            results['collision check, %d ring(s)' % rings] = round((time.perf_counter()-start)*1000)
            results['longest UI pause during check, %d ring(s)' % rings] = round(gap*1000)
        s.rings.setValue(1); s.mode.setCurrentText('Rotate'); s.angle.setValue(5)
        timed('preview rotate', s.update_preview, 3)
        s.mode.setCurrentText('Extrude'); s.distance.setValue(3)
        timed('preview extrude', s.update_preview)
        s.mode.setCurrentText('Move'); s.delta[1].setValue(0); s.delta[2].setValue(1); s.update_preview()
        start = time.perf_counter()
        timed('Apply on GUI thread', s.apply)
        wait(lambda: s.closed or (s.job and s.job.state == 'failed'))
        results['Apply until done'] = round((time.perf_counter()-start)*1000)
        results['applied'] = bool(s.closed)
        print('RESULTS', json.dumps(results), flush=True)
    finally:
        c.cancel(quiet=True); App.closeDocument(doc.Name)
