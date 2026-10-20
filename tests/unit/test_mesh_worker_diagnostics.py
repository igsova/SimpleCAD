"""Worker crashes must retain their stage and stderr before snapshot cleanup."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from simplecad.jobs.diagnostics import failure_details, log_tail


class FailureDetailsTests(unittest.TestCase):
    def test_native_crash_includes_last_stage_and_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'progress.json').write_text(json.dumps({'stage':'Creating the native mesh'}))
            (folder/'worker-error.log').write_text('Fatal Python error: Segmentation fault\nmesh_stretch.py, in stretch\n')
            summary,diagnostics=failure_details(folder,11,True)
            self.assertIn('crashed during Creating the native mesh',summary)
            self.assertIn('exit code 11',summary)
            self.assertIn('Original mesh unchanged',summary)
            self.assertIn('Segmentation fault',diagnostics)

    def test_missing_or_incomplete_progress_does_not_hide_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            for content in (None,'{','[]','{"stage": null}'):
                if content is not None: (folder/'progress.json').write_text(content)
                summary,_=failure_details(folder,1)
                self.assertIn('exit code 1',summary)

    def test_logs_are_bounded_and_decoding_is_resilient(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            log=folder/'worker-error.log'
            log.write_bytes(b'x'*100000+b'\xff\nlast failure')
            tail=log_tail(log)
            self.assertLessEqual(len(tail),8192)
            self.assertTrue(tail.endswith('last failure'))


class JobFailureTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.folder=Path(self.directory.name)
        self.console=Mock()
        modules={
            'FreeCAD': NS(Console=NS(PrintError=self.console)), 'FreeCADGui':NS(),
            'Part':NS(), 'Mesh':NS(), 'simplecad.document.operations':NS(),
            'simplecad.mesh.conversion':NS(is_mesh=Mock(),fingerprint=Mock(),options=Mock(),MAX_FACETS=500000),
            'simplecad.jobs.runtime':NS(runtime=Mock()),
            'simplecad.gui.qt':NS(QtCore=NS(QObject=object,QProcess=NS(CrashExit=1)),QtWidgets=NS()),
        }
        path=Path(__file__).resolve().parents[2]/'simplecad/jobs/mesh.py'
        spec=importlib.util.spec_from_file_location('simplecad.jobs._mesh_jobs_test',path)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,modules): spec.loader.exec_module(module)
        self.job=module.Job.__new__(module.Job)
        self.job.folder=self.folder; self.job.state='running'; self.job.operation='stretch'
        self.job.deadline=Mock(); self.job.watch=Mock(); self.job.diagnostics=None

    def test_crash_cannot_be_applied_even_if_result_file_exists(self):
        (self.folder/'result.json').write_text('{}')
        (self.folder/'result.bms').write_bytes(b'partial result')
        (self.folder/'progress.json').write_text('{"stage":"Creating the native mesh"}')
        (self.folder/'worker-error.log').write_text('Fatal Python error: Segmentation fault')
        self.job.finished(11,1)
        self.assertEqual(self.job.state,'failed')
        self.assertIn('Creating the native mesh',self.job.error)
        self.assertIn('Segmentation fault',self.job.diagnostics)
        self.console.assert_called_once()
        self.job.watch.stop.assert_called_once()
        self.assertFalse(self.folder.exists())

    def test_missing_result_reports_startup_error_before_cleanup(self):
        (self.folder/'worker-error.log').write_text('Could not load native library')
        self.job.finished(1,0)
        self.assertEqual(self.job.state,'failed')
        self.assertIn('exit code 1',self.job.error)
        self.assertIn('Could not load native library',self.job.diagnostics)
        self.assertFalse(self.folder.exists())

    def test_python_validation_message_is_preserved(self):
        (self.folder/'result.json').write_text('{"error":"The source is not manifold."}')
        self.job.finished(1,0)
        self.assertEqual(self.job.error,'The source is not manifold.')
        self.assertEqual(self.job.state,'failed')

    def test_success_keeps_result_for_apply(self):
        (self.folder/'result.json').write_text('{"triangles":42}')
        (self.folder/'result.bms').write_bytes(b'result')
        self.job.finished(0,0)
        self.assertEqual(self.job.state,'ready')
        self.assertEqual(self.job.report,{'triangles':42})
        self.assertIsNone(self.job.diagnostics)
        self.assertTrue(self.folder.exists())
        self.console.assert_not_called()


if __name__ == '__main__': unittest.main()
