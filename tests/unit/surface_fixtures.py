"""Small native inputs shared by surface drawing and viewport regressions."""
import gzip
from pathlib import Path

import Part


def fitted_surface_loop():
    """Two fitted patches and three successive wrapped Line segments."""
    shape = Part.Shape()
    shape.importBrepFromString(gzip.decompress(
        (Path(__file__).parents[1]/'fixtures'/'fitted_surface_loop.brep.gz').read_bytes()).decode())
    source,*segments = shape.childShapes()
    return source,segments
