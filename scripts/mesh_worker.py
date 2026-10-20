#!/usr/bin/env python3
"""Private mesh worker. Receives only a temporary snapshot directory."""
import json
import faulthandler
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    folder = Path(sys.argv[1])
    faulthandler.enable()  # Native crashes go to worker-error.log, even without result.json.
    def progress(message):
        (folder / 'progress.json').write_text(json.dumps({'stage': message}))
    try:
        progress('Loading FreeCAD mesh libraries')
        import FreeCAD  # Must precede other native modules.
        import Mesh
        data = json.loads((folder / 'options.json').read_text())
        operation = data.pop('operation', 'convert')
        if operation == 'split':
            from simplecad.mesh.slicing import split
            data.pop('gap', None)
            pieces, report = split(Mesh.Mesh(str(folder / 'source.bms')), progress=progress, **data)
            for i, piece in enumerate(pieces):
                if data.get('glue') is not None:
                    progress('Checking closed STL export')
                    check_path = folder / ('check-%d.stl' % i)
                    piece.write(str(check_path)); exported = Mesh.Mesh(str(check_path)); check_path.unlink()
                    if not exported.isSolid() or exported.hasNonManifolds() or exported.hasNonUniformOrientedFacets() or exported.CountFacets != piece.CountFacets:
                        raise ValueError('This glue seam cannot be exported as a closed STL. Move the cut slightly or reduce depth.')
                piece.write(str(folder / ('piece-%d.bms' % i)))
        elif operation == 'stretch':
            from simplecad.mesh.stretch import stretch
            result, report = stretch(Mesh.Mesh(str(folder / 'source.bms')), progress=progress, **data)
            progress('Writing the stretched mesh')
            result.write(str(folder / 'result.bms'))
        elif operation == 'region':
            from simplecad.mesh.region_edit import edit
            result, report = edit(Mesh.Mesh(str(folder / 'source.bms')), progress=progress, **data)
            progress('Writing the edited mesh')
            result.write(str(folder / 'result.bms'))
        elif operation == 'convert':
            from simplecad.mesh.conversion import convert
            shape, report = convert(Mesh.Mesh(str(folder / 'source.stl')), progress=progress, **data)
            progress('Preparing the editable result')
            shape.exportBrep(str(folder / 'result.brep'))
        else:
            raise ValueError('Unknown mesh operation.')
        (folder / 'result.json').write_text(json.dumps(report))
    except Exception as error:
        failure = {'error': str(error)}
        if getattr(error, 'triangles', None):
            failure['triangles'] = [int(i) for i in error.triangles]
        (folder / 'result.json').write_text(json.dumps(failure))
        traceback.print_exc()
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
