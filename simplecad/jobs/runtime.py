"""Locate FreeCAD's own Python for isolated worker processes."""
import os
from pathlib import Path
import sys

import FreeCAD as App

from .. import ROOT


def runtime():
    home = Path(App.getHomePath()).resolve()
    candidates = [home / 'bin/python', home / 'bin/python.exe', home / 'bin/python3']
    if Path(sys.executable).name.lower().startswith('python'):
        candidates.append(Path(sys.executable))
    for path in candidates:
        if path.is_file():
            return str(path)
    raise ValueError('Cannot find FreeCAD’s Python runtime for background mesh operations. This FreeCAD installation needs a bundled Python executable.')


def environment():
    """The worker imports this addon and FreeCAD's bundled libraries."""
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(filter(None, [str(ROOT), str(Path(App.getHomePath()).resolve() / 'lib'),
                                                      os.environ.get('PYTHONPATH', '')]))
    return env
