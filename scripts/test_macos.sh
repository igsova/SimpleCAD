#!/bin/sh
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
freecad_resources="${FREECAD_APP:-/Applications/FreeCAD.app}/Contents/Resources"
export PYTHONPATH="$repo_dir:$freecad_resources/lib${PYTHONPATH:+:$PYTHONPATH}"
exec "$freecad_resources/bin/python" -m unittest discover -s "$repo_dir/tests/unit" -v
