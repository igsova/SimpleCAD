#!/usr/bin/env python3
"""Private healing worker. Receives only a temporary snapshot directory."""
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import FreeCAD  # Must precede other native modules.
    import Part
    from simplecad.repair.healing import heal
    folder = Path(sys.argv[1])
    try:
        options = json.loads((folder / 'options.json').read_text())
        shape = Part.Shape()
        shape.read(str(folder / 'source.brep'))
        if shape.Solids and len(shape.Solids) == 1 and len(shape.Faces) == len(shape.Solids[0].Faces):
            shape = shape.Solids[0]
        healed, report = heal(shape, options['tolerance'], remove_slivers=options.get('remove_slivers', False))
        healed.exportBrep(str(folder / 'result.brep'))
        (folder / 'result.json').write_text(json.dumps(report))
    except Exception as error:
        (folder / 'result.json').write_text(json.dumps({'error': str(error)}))
        traceback.print_exc()
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
