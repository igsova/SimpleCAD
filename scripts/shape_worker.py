#!/usr/bin/env python3
"""Private worker for the curved-surface and offset tools. Receives only a temporary snapshot directory.

Defeaturing, splitting and filling can crash natively on difficult geometry,
which no Python handler catches; here a crash only fails the one operation.
"""
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(path):
    import Part
    shape = Part.Shape()
    shape.read(str(path))
    # The reader hands back a compound around a lone solid; face order is kept.
    if shape.ShapeType == 'Compound' and len(shape.Solids) == 1 and len(shape.Faces) == len(shape.Solids[0].Faces):
        shape = shape.Solids[0]
    return shape


def main():
    import FreeCAD  # Must precede other native modules.
    from simplecad.surfaces import edit as se, offset as so
    folder = Path(sys.argv[1])

    def progress(stage):
        (folder / 'progress.json').write_text(json.dumps({'stage': stage}))
    try:
        options = json.loads((folder / 'options.json').read_text())
        shape = read(folder / 'source.brep')
        operation = options['operation']
        if operation == 'remove_faces':
            result, report = se.remove_faces(shape, options['faces'], progress,
                                             options.get('keep_others', False))
        elif operation == 'imprint':
            result, report = se.imprint(shape, options['faces'], read(folder / 'profile.brep'),
                                        FreeCAD.Vector(*options['direction']), options['mode'],
                                        options.get('depth', 0.0), progress, options.get('wrapping'))
        elif operation == 'fill':
            result, report = se.fill(shape, options.get('edges'), options.get('smooth', True), progress)
        elif operation == 'offset_faces':
            result, report = so.offset_faces(shape, options['faces'], options['distance'], progress)
        elif operation == 'shell':
            result, report = so.shell(shape, options.get('faces', ()), options['thickness'], progress)
        elif operation == 'thicken':
            result, report = so.thicken(shape, options['thickness'], options.get('side', 'front'), progress)
        elif operation == 'draft':
            result, report = so.draft(shape, options['faces'], options['angle'], options['axis'],
                                      options.get('hinge', 'bottom'), options.get('narrower', 'top'), progress)
        elif operation == 'unwrap':
            progress('Flattening the face')
            result, report = se.unwrap(shape.Faces[options['face']])
        else:
            raise ValueError('Unknown shape operation.')
        progress('Saving the result')
        result.exportBrep(str(folder / 'result.brep'))
        (folder / 'result.json').write_text(json.dumps(report))
    except Exception as error:
        (folder / 'result.json').write_text(json.dumps({'error': str(error)}))
        traceback.print_exc()
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
