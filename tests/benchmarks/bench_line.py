"""Line tool timings: hover moves, clicks, loop closure and face splits (FreeCAD GUI).

    SC_GUI_TESTS=bench_line FreeCAD scripts/run_gui_tests.py

Drives the real Line tool through controller.motion/click with snapping on and
profiles each tool start, mouse move and click. Scenes: a flat XY loop, a box
divided twice plus an inner loop, a 340 x 340 mm plate with 225 holes, a loop
beside 40 loose lines, and two scenes that need a model in SC_BENCH_DATA:
'surface' (hood.brep, a fitted B-spline part: two loops drawn in Surface mode,
the second on the first's result, plus hovers of all six surface tools and a
first cross-face hover) and 'dense'
(dense.brep, or hood.stl converted to flat faces). Those two are skipped when
their files are missing. SC_BENCH_ONLY=plane,box limits the scenes;
SC_BENCH_OUT names the output prefix (.txt summary, .json with profiles; a
temporary folder by default). Uses temporary documents.

After a surface Line click, building the next segment's guide mesh (deferred
until the redraw) is timed separately from the click and its redraw.

Timings are not pass/fail, but a fast click that missed its target is not a
result: every click reports MISSED when it lands more than MISS_MM from its
target (a click that closes a loop ends Line, so its hover point counts), and every chain whose face count did not change as intended reports
it. The summary ends with the number of such misses.
"""
import cProfile
import io
import json
import os
import pstats
import tempfile
import time

import FreeCAD as App
import FreeCADGui as Gui
import Mesh
import Part

from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen
from simplecad.surfaces import edit as surface_edit  # noqa: F401  (import cost outside timings)

V = App.Vector
HERE = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
OUT = os.environ.get('SC_BENCH_OUT', os.path.join(tempfile.gettempdir(), 'simplecad_bench_line'))
ONLY = [n for n in os.environ.get('SC_BENCH_ONLY', '').split(',') if n]
DATA = os.environ.get('SC_BENCH_DATA', HERE)
MOVES = 8
MISS_MM = .5


def ms(seconds):
    return round(seconds * 1000, 1)


def inner_loop(face, limit, skew=None):
    """A square loop on the face, centred where it is farthest from the face's boundary.

    skew: a direction for the first side, projected into the face. Line's axis
    inference otherwise pulls sides on a slightly tilted face onto world axes.
    """
    points, triangles = face.tessellate(max(.05, face.BoundBox.DiagonalLength / 150))
    boundary = Part.makeCompound(face.Edges)
    # A planar polygon's tessellation vertices all lie on its boundary; use
    # triangle centroids, which are interior.
    centroids = [(points[a] + points[b] + points[c]) * (1 / 3) for a, b, c in triangles]
    sample = (centroids + list(points))[::max(1, (len(centroids) + len(points)) // 240)]
    clearance = [boundary.distToShape(Part.Vertex(p))[0] for p in sample]
    best = max(range(len(sample)), key=lambda i: clearance[i])
    center, room = sample[best], clearance[best]
    u, v = face.Surface.parameter(center)
    normal = face.normalAt(u, v)
    tangent = face.derivative1At(u, v)[0] if skew is None else V(*skew)
    tangent = (tangent - normal * tangent.dot(normal)).normalize()
    other = normal.cross(tangent)
    size = min(limit, room * .45)
    loop = []
    for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1), (-1, -1)):
        guess = center + tangent * a * size + other * b * size
        loop.append(face.Surface.value(*face.Surface.parameter(guess)))
    if not all(face.isInside(p, 1e-4, True) for p in loop):
        return None
    if face.Orientation == 'Reversed':
        normal = -normal
    return loop, center, normal, size


class Bench:
    def __init__(self):
        self.c = instance()
        self.results = {}
        self.text = []
        self.misses = []

    def say(self, *parts):
        line = ' '.join(str(p) for p in parts)
        self.text.append(line)
        print(line, flush=True)

    def camera(self, view, direction=None, up=None, zoom=1.0):
        if direction is None:
            view.viewIsometric()
        else:
            z = -V(*direction).normalize()
            y = V(*(up or (0, 0, 1)))
            y = (y - z * y.dot(z))
            if y.Length < 1e-6:
                y = V(0, 1, 0) - z * z.y
            y.normalize()
            x = y.cross(z)
            m = App.Matrix(x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0)
            view.getCameraNode().orientation.setValue(*App.Rotation(m).Q)
        view.fitAll()
        cam = view.getCameraNode()
        if zoom != 1.0 and hasattr(cam, 'height'):
            cam.height.setValue(cam.height.getValue() * zoom)
        Gui.updateGui()

    def focus(self, view, center, height):
        cam = view.getCameraNode()
        d = view.getViewDirection()
        position = V(*cam.position.getValue().getValue())
        focal = position + d * cam.focalDistance.getValue()
        cam.position.setValue(*(position + (center - focal)))
        cam.height.setValue(height)
        Gui.updateGui()

    def line(self, name, doc, view, chains, plane='Auto', mode=0, snap=True, faces=None):
        """Draw each chain of 3D points as one Line session; profile every click.

        faces: the intended change of the document's face count per chain.
        """
        c = self.c
        c.controls.plane.setCurrentText(plane)
        c.controls.drawing_mode.setCurrentIndex(mode)
        c.controls.snap.setChecked(snap)
        record = self.results.setdefault(name, {'start': [], 'moves': [], 'clicks': [], 'redraw': []})
        click_stats = None
        move_profile = cProfile.Profile()

        def pos(point):
            return tuple(int(round(v)) for v in screen(view, point))

        for number, chain in enumerate(chains):
            chain_faces = sum(len(o.Shape.Faces) for o in doc.Objects if hasattr(o, 'Shape'))
            start_profile = cProfile.Profile()
            t = time.perf_counter()
            start_profile.enable()
            try:
                c.start('Line')
            finally:
                start_profile.disable()
            record['start'].append(ms(time.perf_counter() - t))
            out = io.StringIO()
            pstats.Stats(start_profile, stream=out).sort_stats('cumulative').print_stats(25)
            record.setdefault('start_profile', []).append(out.getvalue())
            previous = None
            for index, point in enumerate(chain):
                target = pos(point)
                if previous is not None:
                    for k in range(1, MOVES + 1):
                        f = k / MOVES
                        p = (round(previous[0] + (target[0] - previous[0]) * f),
                             round(previous[1] + (target[1] - previous[1]) * f))
                        t = time.perf_counter()
                        move_profile.enable()
                        try:
                            c.motion(p)
                        finally:
                            move_profile.disable()
                        record['moves'].append((index, ms(time.perf_counter() - t)))
                else:
                    t = time.perf_counter()
                    move_profile.enable()
                    try:
                        c.motion(target)
                    finally:
                        move_profile.disable()
                    record['moves'].append((index, ms(time.perf_counter() - t)))
                faces_before = sum(len(o.Shape.Faces) for o in doc.Objects if hasattr(o, 'Shape'))
                objects_before = len(doc.Objects)
                # A click that closes a loop ends Line and clears its anchor;
                # it landed where its hover point was.
                aimed = None if c.point is None else V(c.point)
                profile = cProfile.Profile()
                t = time.perf_counter()
                profile.enable()
                try:
                    c.click(target)
                finally:
                    profile.disable()
                elapsed = time.perf_counter() - t
                # A continuing surface Line meshes its guide once the click's
                # redraw is done; time the redraw alone, then that build.
                guide, after = getattr(c, 'guide_timer', None), None
                pending = guide is not None and guide.isActive()
                if pending:
                    guide.stop()
                t = time.perf_counter()
                Gui.updateGui()
                redraw = time.perf_counter() - t
                if pending:
                    t = time.perf_counter()
                    c.build_guide()
                    after = time.perf_counter() - t
                faces_after = sum(len(o.Shape.Faces) for o in doc.Objects if hasattr(o, 'Shape'))
                landed = c.anchor if c.tool is not None else aimed
                out = io.StringIO()
                pstats.Stats(profile, stream=out).sort_stats('cumulative').print_stats(22)
                if click_stats is None:
                    click_stats = pstats.Stats(profile)
                else:
                    click_stats.add(profile)
                record['clicks'].append({'index': index, 'ms': ms(elapsed), 'redraw_ms': ms(redraw),
                                         'guide_ms': None if after is None else ms(after),
                                         'faces': [faces_before, faces_after],
                                         'objects': [objects_before, len(doc.Objects)],
                                         'tool': c.tool, 'label': c.controls.label.text(), 'anchor': [round(v, 3) for v in landed] if landed is not None else None, 'want': [round(v, 3) for v in point],
                                         'profile': out.getvalue()})
                landed = record['clicks'][-1]['anchor']
                if landed is None or (V(*landed) - point).Length > MISS_MM:
                    record['clicks'][-1]['missed'] = True
                    self.misses.append('%s click %d' % (name, index))
                previous = target
            c.cancel(quiet=True)
            if faces is not None:
                change = sum(len(o.Shape.Faces) for o in doc.Objects if hasattr(o, 'Shape')) - chain_faces
                if change != faces[number]:
                    self.misses.append('%s chain %d: faces changed by %d, intended %d' % (name, number, change, faces[number]))
                    self.say('!! %s chain %d changed the face count by %d, intended %d' % (name, number, change, faces[number]))
        out = io.StringIO()
        if click_stats is not None:
            click_stats.stream = out
            click_stats.sort_stats('cumulative').print_stats(45)
        record['click_profile'] = out.getvalue()
        out = io.StringIO()
        pstats.Stats(move_profile, stream=out).sort_stats('cumulative').print_stats(35)
        record['move_profile'] = out.getvalue()
        moves = [m for _, m in record['moves']]
        self.say('== %s: tool start %s ms; hover move mean %.1f ms, max %.1f ms over %d moves' % (
            name, record['start'], sum(moves) / max(len(moves), 1), max(moves or [0]), len(moves)))
        for click in record['clicks']:
            self.say('   click %d: %7.1f ms (+%5.1f ms redraw%s)  faces %s objects %s  %s  at %s want %s%s' % (
                click['index'], click['ms'], click['redraw_ms'],
                '' if click['guide_ms'] is None else ', then guide %.1f ms' % click['guide_ms'],
                click['faces'], click['objects'], click['label'],
                click['anchor'], click['want'], '  MISSED' if click.get('missed') else ''))

    # --- scenarios -----------------------------------------------------------

    def plane(self):
        doc = App.newDocument('BenchPlane'); doc.UndoMode = 1
        view = Gui.activeDocument().activeView()
        doc.addObject('Part::Feature', 'Marker').Shape = Part.Vertex(V(30, 20, 0))
        doc.recompute()
        self.camera(view, (0, 0, -1), (0, 1, 0))
        view.getCameraNode().height.setValue(120)
        Gui.updateGui()
        square = [V(0, 0, 0), V(60, 0, 0), V(60, 40, 0), V(0, 40, 0), V(0, 0, 0)]
        self.line('plane loop (XY)', doc, view, [square], plane='XY', faces=[1])
        self.line('plane divide', doc, view, [[V(0, 0, 0), V(60, 40, 0)]], plane='Auto', faces=[1])
        App.closeDocument(doc.Name)

    def box(self):
        doc = App.newDocument('BenchBox'); doc.UndoMode = 1
        view = Gui.activeDocument().activeView()
        doc.addObject('Part::Feature', 'Box').Shape = Part.makeBox(100, 80, 40)
        doc.recompute()
        self.camera(view, (-0.6, 0.8, -1.4), (0, 0, 1))
        self.line('box divide x2', doc, view, [[V(50, 0, 40), V(50, 80, 40)], [V(0, 40, 40), V(100, 40, 40)]],
                  faces=[1, 2])
        loop = [V(10, 10, 40), V(30, 10, 40), V(30, 30, 40), V(10, 30, 40), V(10, 10, 40)]
        # From above: at an angle, the end face's centre hint (60 px) caught a corner.
        self.camera(view, (0, 0, -1), (0, 1, 0))
        self.focus(view, V(20, 20, 40), 70)
        self.line('box inner loop', doc, view, [loop], faces=[1])
        App.closeDocument(doc.Name)

    def plate(self):
        doc = App.newDocument('BenchPlate'); doc.UndoMode = 1
        view = Gui.activeDocument().activeView()
        # A 26 mm margin keeps the divide's edge points out of reach of the
        # holes' midpoint hints (60 px); at 6 mm both of its clicks missed.
        plate = Part.makeBox(340, 340, 10, V(-20, -20, 0))
        holes = [Part.makeCylinder(4, 10, V(10 + 20 * i, 10 + 20 * j, 0)) for i in range(15) for j in range(15)]
        shape = plate.cut(Part.makeCompound(holes)).removeSplitter()
        doc.addObject('Part::Feature', 'Plate').Shape = shape
        doc.recompute()
        self.say('plate faces', len(shape.Faces), 'edges', len(shape.Edges))
        self.camera(view, (-0.3, 0.4, -1), (0, 1, 0))
        self.line('plate divide (225 holes)', doc, view, [[V(-20, 200, 10), V(320, 200, 10)]], faces=[1])
        loop = [V(20, 20, 10), V(40, 20, 10), V(40, 40, 10), V(20, 40, 10), V(20, 20, 10)]
        self.focus(view, V(30, 30, 10), 70)
        self.line('plate loop around a hole', doc, view, [loop], faces=[1])
        App.closeDocument(doc.Name)

    def dense(self):
        """A converted part of thousands of planar faces, like an imported STL."""
        from simplecad.mesh import conversion as mc
        cached, source = os.path.join(DATA, 'dense.brep'), os.path.join(DATA, 'hood.stl')
        if not (os.path.exists(cached) or os.path.exists(source)):
            self.say('dense: no dense.brep or hood.stl in SC_BENCH_DATA; skipped')
            return
        doc = App.newDocument('BenchDense'); doc.UndoMode = 1
        view = Gui.activeDocument().activeView()
        if os.path.exists(cached):
            shape = Part.Shape(); shape.read(cached)
            if shape.ShapeType == 'Compound' and len(shape.Solids) == 1:
                shape = shape.Solids[0]
        else:
            mesh = Mesh.Mesh(source)
            result = mc.convert(mesh, tolerance=.1, surfaces=False)
            shape = result[0] if isinstance(result, tuple) else result
            shape.exportBrep(cached)
        self.say('dense faces', len(shape.Faces), 'edges', len(shape.Edges))
        obj = doc.addObject('Part::Feature', 'Dense'); obj.Shape = shape
        doc.recompute()
        found = None
        for face in sorted((f for f in shape.Faces if isinstance(f.Surface, Part.Plane)), key=lambda f: -f.Area)[:12]:
            candidate = inner_loop(face, 8.0, skew=(1, .6, .35))
            if candidate is not None and (found is None or candidate[3] > found[3]):
                found, best = candidate, face
            if found is not None and found[3] >= 4:
                break
        face = best if found is not None else None
        if found is None:
            self.say('dense: no loop fits inside the largest flat face; skipped')
            App.closeDocument(doc.Name)
            return
        loop, center, normal, size = found
        self.say('dense face area', round(face.Area), 'loop size', round(2 * size, 1))
        self.camera(view, -normal, (0, 0, 1))
        self.focus(view, center, size * 8)
        self.line('dense loop on largest flat face', doc, view, [loop], faces=[1])
        App.closeDocument(doc.Name)

    def surface(self):
        """Surface mode on a fitted part: a small loop on its largest B-spline face."""
        path = os.path.join(DATA, 'hood.brep')
        if not os.path.exists(path):
            self.say('surface: no hood.brep in SC_BENCH_DATA; skipped')
            return
        doc = App.newDocument('BenchSurface'); doc.UndoMode = 1
        view = Gui.activeDocument().activeView()
        shape = Part.Shape(); shape.read(path)
        if shape.ShapeType == 'Compound' and len(shape.Solids) == 1:
            shape = shape.Solids[0]
        obj = doc.addObject('Part::Feature', 'Hood'); obj.Shape = shape
        doc.recompute()
        faces = sorted((f for f in shape.Faces if isinstance(f.Surface, Part.BSplineSurface)), key=lambda f: -f.Area)
        loops = []
        for face in faces[:6]:
            found = inner_loop(face, 6.0)
            if found is not None:
                loops.append(found)
                self.say('surface face area', round(face.Area), 'loop size', round(2 * found[3], 1))
            if len(loops) == 2:
                break
        if not loops:
            self.say('surface: no loop fits on the large B-spline faces; skipped')
            App.closeDocument(doc.Name)
            return
        loop, center, normal, size = loops[0]
        self.camera(view, -normal, (1, 0, 0))
        self.focus(view, center, size * 8)
        self.surface_tools(view, center)
        self.cross_face(shape)
        self.line('surface loop on hood (Surface mode)', doc, view, [loop], mode=1, snap=True, faces=[1])
        # The second loop divides the first loop's result, as repeated edits do.
        for loop, center, normal, size in loops[1:]:
            self.camera(view, -normal, (1, 0, 0))
            self.focus(view, center, size * 8)
            self.line('second surface loop on hood', doc, view, [loop], mode=1, snap=True, faces=[1])
        # The same loop drawn again in Plane mode is a chord, not a surface split; skip it.
        App.closeDocument(doc.Name)

    def surface_tools(self, view, center, count=40):
        """Hover each Surface tool's outline in 40 places around a small circle."""
        import math
        import numpy as np
        c = self.c

        def pos(point):
            return tuple(int(round(v)) for v in screen(view, point))

        c.controls.drawing_mode.setCurrentIndex(1)
        c.controls.snap.setChecked(True)
        for tool in ('Line', 'Circle', 'Rectangle', 'Polygon', 'Arc', 'Arc2Point'):
            c.cancel(quiet=True)
            c.start(tool)
            c.motion(pos(center))
            c.click(pos(center))
            frame = c.surface_frame
            if frame is None:
                self.misses.append('surface tools: %s did not start on the surface' % tool)
                self.say('!! surface tools: %s did not start on the surface' % tool)
                continue
            if tool in ('Arc', 'Arc2Point'):
                second = pos(frame.point(V(4, 0, 0)))
                c.motion(second)
                c.click(second)
            targets = [pos(frame.point(V(3 + 2 * math.cos(k / 7), 3 + 2 * math.sin(k / 7), 0))) for k in range(count)]
            profile = cProfile.Profile()
            elapsed, misses = [], 0
            for target in targets:
                t = time.perf_counter()
                profile.enable()
                try:
                    c.motion(target)
                finally:
                    profile.disable()
                elapsed.append(ms(time.perf_counter() - t))
                misses += c.point is None
            out = io.StringIO()
            pstats.Stats(profile, stream=out).sort_stats('cumulative').print_stats(30)
            self.results['surface hover ' + tool] = {'moves': elapsed, 'profile': out.getvalue(), 'no point': misses}
            rest = elapsed[1:]  # The first move can still wait for SciPy or the corridor.
            self.say('== surface hover %-9s first %6.1f ms; then mean %5.1f ms, p95 %5.1f ms, max %5.1f ms over %d moves%s' % (
                tool, elapsed[0], float(np.mean(rest)), float(np.percentile(rest, 95)), max(rest), len(rest),
                '  (%d without a point)' % misses if misses else ''))
            if misses:
                self.misses.append('surface hover %s: %d moves without a point' % (tool, misses))
        c.cancel(quiet=True)

    def cross_face(self, shape):
        """The first hover onto another face: corridor search, solve and preview."""
        from simplecad.surfaces.skin import Skin
        from simplecad.surfaces.wrap import WrapFrame
        a = V(-28.876125593381285, -95.45146364674233, 183.29413435552036)
        b = V(-31.34728941508978, -43.1455539166672, 224.5160844330051)
        source = min(shape.Faces, key=lambda f: f.distToShape(Part.Vertex(a))[0])
        target = min(shape.Faces, key=lambda f: f.distToShape(Part.Vertex(b))[0])
        if source.isSame(target) or source.distToShape(Part.Vertex(a))[0] > 1e-3 or target.distToShape(Part.Vertex(b))[0] > 1e-3:
            self.say('cross-face hover: the probe points are not on two hood faces; skipped')
            return
        frame = WrapFrame(Skin(shape, source), source, a)
        profile = cProfile.Profile()
        t = time.perf_counter()
        profile.enable()
        try:
            q = frame.local(b, target)
            frame.points([V(), q])
            error = None
        except ValueError as exc:
            error = str(exc)
        finally:
            profile.disable()
        elapsed = ms(time.perf_counter() - t)
        out = io.StringIO()
        pstats.Stats(profile, stream=out).sort_stats('cumulative').print_stats(30)
        self.results['cross-face first hover'] = {'ms': elapsed, 'error': error, 'profile': out.getvalue()}
        self.say('== cross-face first hover (corridor, solve, preview): %.1f ms%s' % (elapsed, '  FAILED: ' + error if error else ''))
        if error:
            self.misses.append('cross-face hover: ' + error)

    def loose(self):
        """Forty loose lines already in the document, then a fresh loop."""
        from simplecad.document import operations as ops
        from simplecad.core import geometry as geo
        doc = App.newDocument('BenchLoose'); doc.UndoMode = 1
        view = Gui.activeDocument().activeView()
        for i in range(40):
            ops.new_shape(doc, geo.line(V(i * 4, -30, 0), V(i * 4, -10, 0)), 'Line')
        doc.recompute()
        self.camera(view, (0, 0, -1), (0, 1, 0))
        square = [V(0, 0, 0), V(60, 0, 0), V(60, 40, 0), V(0, 40, 0), V(0, 0, 0)]
        self.line('loop with 40 loose lines', doc, view, [square], plane='XY', faces=[1])
        App.closeDocument(doc.Name)

    def run(self):
        Gui.activateWorkbench('SimpleCADWorkbench')
        c = self.c
        c.cancel(quiet=True)
        saved = c.controls.plane.currentText(), c.controls.snap.isChecked(), c.controls.drawing_mode.currentIndex()
        try:
            for name in ('plane', 'box', 'plate', 'loose', 'surface', 'dense'):
                if ONLY and name not in ONLY:
                    continue
                t = time.perf_counter()
                try:
                    getattr(self, name)()
                except Exception:
                    import traceback
                    self.say('!! scenario', name, 'failed:\n' + traceback.format_exc())
                    c.cancel(quiet=True)
                self.say('-- scenario %s took %.1f s' % (name, time.perf_counter() - t))
        finally:
            self.say('%d missed clicks or edits%s' % (len(self.misses), ''.join('\n   ' + m for m in self.misses)))
            c.cancel(quiet=True)
            c.controls.plane.setCurrentText(saved[0])
            c.controls.snap.setChecked(saved[1])
            c.controls.drawing_mode.setCurrentIndex(saved[2])
            with open(OUT + '.json', 'w') as f:
                json.dump(self.results, f, indent=1)
            with open(OUT + '.txt', 'w') as f:
                f.write('\n'.join(self.text) + '\n')


def run():
    Bench().run()
