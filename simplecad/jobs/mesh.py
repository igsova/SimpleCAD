"""Cancellable mesh conversion, splitting and deformation in a native worker."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

import FreeCAD as App
import FreeCADGui as Gui
import Part
import Mesh
from .. import ROOT
from ..document import operations
from ..mesh.conversion import is_mesh, fingerprint, options, MAX_FACETS
from .runtime import runtime
from .diagnostics import failure_details
from ..gui.qt import QtCore, QtWidgets

_jobs = {}


class Job(QtCore.QObject):
    def __init__(self, source, tolerance=.01, simplify=0, *, operation="convert", parameters=None, surfaces=False):
        super().__init__(QtWidgets.QApplication.instance())
        if not is_mesh(source):
            raise ValueError('Select one imported mesh first.')
        if any(parent.hasExtension('App::GeoFeatureGroupExtension') for parent in source.InList):
            raise ValueError('Move the mesh out of its Part container before starting this operation.')
        self.operation = operation
        self.parameters = parameters or {}
        tolerance, simplify = options(tolerance, simplify)
        if not isinstance(surfaces, bool):
            raise ValueError('Fit smooth surfaces must be true or false.')
        limit = MAX_FACETS if operation == 'convert' else 500000
        if not 0 < source.Mesh.CountFacets <= limit:
            raise ValueError('Choose a mesh with 1 to %d triangles. Simplify larger meshes in Mesh Design first.' % limit)
        python = runtime()
        self.id = uuid.uuid4().hex
        self.doc = source.Document
        self.source = source
        self.source_name = source.Name
        self.placement = App.Placement(source.Placement)
        self.original = fingerprint(source.Mesh)
        self.state, self.stage, self.error = 'running', 'Preparing mesh', None
        self.report = None
        self.diagnostics = None
        self.failed_triangles = []
        self.result_name = None
        self.result_names = []
        self.folder = Path(tempfile.mkdtemp(prefix='simplecad-mesh-'))
        try:
            mesh = source.Mesh.copy()
            mesh.Placement = App.Placement()
            mesh.write(str(self.folder / ('source.stl' if operation == 'convert' else 'source.bms')))
            data = ({'tolerance': tolerance, 'simplify': simplify, 'surfaces': surfaces} if operation == 'convert'
                    else self.parameters)
            (self.folder / 'options.json').write_text(json.dumps({'operation': operation, **data}))
            self.process = QtCore.QProcess(self)
            environment = QtCore.QProcessEnvironment.systemEnvironment()
            environment.insert('PYTHONPATH', os.pathsep.join([str(ROOT), str(Path(App.getHomePath()).resolve() / 'lib'), os.environ.get('PYTHONPATH', '')]))
            self.process.setProcessEnvironment(environment)
            self.process.setStandardOutputFile(str(self.folder / 'worker.log'))
            self.process.setStandardErrorFile(str(self.folder / 'worker-error.log'))
            self.process.finished.connect(self.finished)
            self.process.errorOccurred.connect(self.failed)
            self.deadline = QtCore.QTimer(self)
            self.deadline.setSingleShot(True)
            self.deadline.timeout.connect(self.timed_out)
            self.watch = QtCore.QTimer(self)
            self.watch.setInterval(500)
            self.watch.timeout.connect(self.check_context)
            self.watch.start()
            self.process.start(python, [str(ROOT / 'scripts/mesh_worker.py'), str(self.folder)])
            self.deadline.start(300000)
            QtWidgets.QApplication.instance().aboutToQuit.connect(self.dispose)
        except Exception:
            shutil.rmtree(self.folder, ignore_errors=True)
            self.deleteLater()
            raise

    def check_context(self):
        if self.state not in ('running', 'ready'):
            self.watch.stop()
            return
        try:
            alive = (App.listDocuments().get(self.doc.Name) == self.doc
                     and self.doc.getObject(self.source_name) == self.source)
        except (ReferenceError, RuntimeError):
            alive = False
        if not alive:
            self.cancel()

    def cleanup(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def dispose(self):
        if self.state == 'running':
            self.cancel()
        self.cleanup()

    def failed(self, error):
        if self.state != 'running':
            return
        if error == QtCore.QProcess.FailedToStart:
            self.state, self.error = 'failed', 'The FreeCAD mesh worker could not start.'
            self.deadline.stop()
            self.cleanup()

    def finished(self, code, status):
        self.deadline.stop()
        if self.state != 'running':
            self.cleanup()
            return
        if status == QtCore.QProcess.CrashExit:
            self.record_failure(code, True)
            return
        try:
            data = json.loads((self.folder / 'result.json').read_text())
            if code != 0 or 'error' in data:
                # Rejected region edits name the colliding result triangles.
                self.failed_triangles = [int(i) for i in data.get('triangles', ())]
                raise ValueError(data.get('error', 'The mesh worker stopped unexpectedly.'))
            outputs = {'convert': ['result.brep'], 'stretch': ['result.bms'], 'region': ['result.bms'],
                       'split': ['piece-0.bms', 'piece-1.bms']}[self.operation]
            if not all((self.folder / name).is_file() for name in outputs):
                raise ValueError('The mesh worker did not produce its result files.')
            self.report = data
            self.state, self.stage = 'ready', 'Ready to apply'
        except OSError:
            self.record_failure(code, False)
        except ValueError as error:
            self.record_failure(code, False, str(error))

    def record_failure(self, code, crashed, message=None):
        summary, self.diagnostics = failure_details(self.folder, code, crashed)
        self.state, self.error = 'failed', message or summary
        self.watch.stop()
        App.Console.PrintError('SimpleCAD mesh worker:\n'+self.diagnostics+'\n')
        self.cleanup()

    def timed_out(self):
        self.cancel()
        self.state, self.error = 'failed', 'The mesh operation exceeded five minutes. Original mesh unchanged.'

    def cancel(self):
        if self.state not in ('running', 'ready'):
            return
        self.state, self.stage = 'cancelled', 'Cancelled; original mesh unchanged'
        self.deadline.stop()
        self.watch.stop()
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
        self.cleanup()

    def status(self):
        if self.state == 'running':
            try:
                self.stage = json.loads((self.folder / 'progress.json').read_text())['stage']
            except (OSError, ValueError, KeyError):
                pass
        return {'job_id': self.id, 'operation': self.operation, 'source': self.source_name, 'status': self.state,
                'stage': self.stage, 'error': self.error, 'report': self.report, 'diagnostics': self.diagnostics,
                'result_object': self.result_name, 'result_objects': self.result_names}

    def apply(self):
        if self.state != 'ready':
            raise ValueError('The mesh operation must be ready and not previously applied.')
        try:
            if App.listDocuments().get(self.doc.Name) != self.doc or self.doc.getObject(self.source_name) != self.source:
                raise ValueError('The source document or mesh no longer exists.')
            if App.ActiveDocument != self.doc:
                raise ValueError('Activate the source document before applying the result.')
            if fingerprint(self.source.Mesh) != self.original or not self.source.Placement.isSame(self.placement):
                raise ValueError('The source mesh changed. Start the mesh operation again.')
            if any(parent.hasExtension('App::GeoFeatureGroupExtension') for parent in self.source.InList):
                raise ValueError('The mesh moved into a Part container. Start the mesh operation again outside it.')
        except (ReferenceError, RuntimeError) as error:
            raise ValueError('The source mesh is no longer available. Start the mesh operation again.') from error
        if self.operation == 'split':
            return self.apply_split()
        if self.operation in ('stretch','region'):
            return self.apply_stretch()
        shape = Part.Shape()
        shape.read(str(self.folder / 'result.brep'))
        if shape.isNull() or not shape.isValid():
            raise ValueError('The converted shape failed validation. Original mesh unchanged.')
        with operations.transaction(self.doc, 'Make mesh editable'):
            result = self.doc.addObject('Part::Feature', 'EditableMesh')
            result.Label = self.source.Label + ' (editable)'
            result.Shape = shape
            result.Placement = self.placement
            result.addProperty('App::PropertyString', 'SC_MeshConversion', 'SimpleCAD', 'Conversion detail and validation report')
            result.SC_MeshConversion = json.dumps(self.report)
            result.setEditorMode('SC_MeshConversion', 1)
            result.ViewObject.ShapeColor = self.source.ViewObject.ShapeColor
            result.ViewObject.Transparency = self.source.ViewObject.Transparency
            result.ViewObject.LineColor = (0.15, 0.23, 0.29)
            result.ViewObject.DisplayMode = 'Flat Lines'
            self.source.ViewObject.Visibility = False
        self.state, self.stage, self.result_name = 'applied', 'Editable shape created', result.Name
        self.watch.stop()
        self.cleanup()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(result)
        return result

    def apply_stretch(self):
        from ..mesh.stretch import check_source
        check_source(self.source)
        mesh = Mesh.Mesh(str(self.folder / 'result.bms'))
        if (mesh.CountFacets != self.report['triangles'] or mesh.hasNonManifolds()
                or mesh.hasNonUniformOrientedFacets() or mesh.isSolid() != self.report['closed']):
            raise ValueError('The edited mesh failed validation. Original mesh unchanged.')
        # Mesh-only edits need no document-wide CAD appearance remapping.
        region = self.operation == 'region'
        self.doc.openTransaction('Edit mesh region' if region else 'Stretch mesh / Move region')
        try:
            result = self.doc.addObject('Mesh::Feature', 'EditedMesh' if region else 'StretchedMesh')
            result.Label = self.source.Label + (' (region edited)' if region else ' (stretched)')
            result.Mesh = mesh
            result.Placement = self.placement
            result.ViewObject.ShapeColor = self.source.ViewObject.ShapeColor
            result.ViewObject.Transparency = self.source.ViewObject.Transparency
            result.ViewObject.DisplayMode = self.source.ViewObject.DisplayMode
            self.source.ViewObject.Visibility = False
            self.doc.recompute()
            self.doc.commitTransaction()
        except Exception:
            self.doc.abortTransaction()
            raise
        self.state, self.stage, self.result_name = 'applied', 'Edited mesh created', result.Name
        self.result_names = [result.Name]
        self.watch.stop(); self.cleanup()
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(result)
        return result

    def split_meshes(self):
        if self.state != 'ready' or self.operation != 'split':
            raise ValueError('The mesh split is not ready.')
        return [Mesh.Mesh(str(self.folder / ('piece-%d.bms' % i))) for i in range(2)]

    def apply_split(self):
        meshes = self.split_meshes()
        for mesh, item in zip(meshes, self.report['pieces']):
            if not mesh.CountFacets or mesh.hasNonManifolds() or (item['closed'] and not mesh.isSolid()):
                raise ValueError('A split mesh failed validation. Original mesh unchanged.')
        normal = self.placement.Rotation.multVec(App.Vector(*self.parameters['normal']))
        results = []
        with operations.transaction(self.doc, 'Split mesh'):
            for side, mesh in zip((-1, 1), meshes):
                result = self.doc.addObject('Mesh::Feature', 'MeshPiece')
                result.Label = self.source.Label + (' · negative side' if side < 0 else ' · positive side')
                if self.parameters.get('glue') is not None:
                    male_side = 1 if self.parameters['glue']['flip'] else -1
                    result.Label = self.source.Label + (' · ridge' if side == male_side else ' · groove')
                result.Mesh = mesh
                placement = App.Placement(self.placement)
                placement.Base += normal * (side * self.parameters.get('gap', 0) / 2)
                result.Placement = placement
                result.ViewObject.ShapeColor = self.source.ViewObject.ShapeColor
                result.ViewObject.Transparency = self.source.ViewObject.Transparency
                result.ViewObject.DisplayMode = self.source.ViewObject.DisplayMode
                results.append(result)
            self.source.ViewObject.Visibility = False
        self.state, self.stage = 'applied', 'Two mesh sides created'
        self.result_names = [obj.Name for obj in results]
        self.watch.stop(); self.cleanup()
        Gui.Selection.clearSelection()
        for obj in results: Gui.Selection.addSelection(obj)
        return results


def _start(source, tolerance=.01, simplify=0, **kw):
    # One mesh worker at a time bounds CPU/memory use across UI and MCP clients.
    for job in _jobs.values():
        job.check_context()
    if any(job.state in ('running', 'ready') for job in _jobs.values()):
        raise ValueError('A mesh operation is already active. Finish or cancel it first.')
    for key in list(_jobs):
        if len(_jobs) < 16:
            break
        old = _jobs.pop(key)
        old.dispose()
        old.deleteLater()
    job = Job(source, tolerance, simplify, **kw)
    _jobs[job.id] = job
    return job


def start(source, tolerance=.01, simplify=0, surfaces=False):
    return _start(source, tolerance, simplify, surfaces=surfaces)


def start_split(source, axis='Main', offset=0, gap=0, cap=True, glue=None):
    from ..mesh import slicing
    if not is_mesh(source): raise ValueError('Select one imported mesh first.')
    offset = slicing.finite(offset, 'Cut offset')
    gap = slicing.finite(gap, 'Gap', 0)
    if not isinstance(cap, bool): raise ValueError('Close cut surfaces must be true or false.')
    from ..mesh.glue import options as glue_options
    glue = glue_options(glue)
    if glue is not None and (not cap or not source.Mesh.isSolid()):
        raise ValueError('A triangular glue seam needs a closed mesh and Close cut surfaces enabled.')
    plane = slicing.plane(source.Mesh, axis)
    if not plane.lower < offset < plane.upper:
        raise ValueError('Place the cut inside the mesh.')
    origin = source.Placement.inverse().multVec(plane.center + plane.normal*offset)
    normal = source.Placement.Rotation.inverted().multVec(plane.normal)
    return _start(source, operation='split', parameters={'origin': list(origin), 'normal': list(normal), 'cap': cap, 'gap': gap, 'glue': glue})


def start_stretch(source, **values):
    from ..mesh.stretch import parameters
    return _start(source, operation='stretch', parameters=parameters(source, **values))


def start_region(source, **values):
    from ..mesh.region_edit import parameters
    return _start(source, operation='region', parameters=parameters(source, **values))


def get(doc, job_id):
    job = _jobs.get(job_id)
    if job is None or job.doc != doc:
        raise ValueError('That mesh job does not belong to this open document.')
    return job
