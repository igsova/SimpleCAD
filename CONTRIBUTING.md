# Contributing to SimpleCAD

Thanks for helping. Bug reports, model files that break a tool, and pull
requests are all welcome.

## Reporting a problem

Open an issue with:

- your FreeCAD version (**Help → About FreeCAD → Copy to clipboard**) and
  operating system;
- the tool you used and what you did, step by step;
- the message in SimpleCAD's status bar or FreeCAD's Report view;
- if you can share it, a small `.FCStd` or `.stl` file that shows the problem.

## Setting up

1. Clone the repository and link it into FreeCAD's `Mod` folder, as described
   in the [README](README.md#manual). On macOS, `python3 scripts/install_macos.py`
   creates the link for you.
2. Restart FreeCAD after every change to the code. Reloading Qt modules in a
   running FreeCAD is not supported.

The [architecture notes](docs/development/architecture.md#package-layout)
explain where code lives and how the packages depend on each other.

## Ground rules for changes

- **Keep results plain FreeCAD geometry.** Tools write ordinary Part or Mesh
  objects. Do not add custom document objects or saved Python proxies; a
  model must open without SimpleCAD installed.
- **One Undo step per edit.** Prepare and validate geometry first, then write
  it in a single document transaction through `document/operations.py` (or the
  equivalent writer for meshes and surfaces). Failure or Cancel must leave the
  model unchanged.
- **Previews are temporary.** A preview must not change the document, its
  saved properties or the Undo history.
- **Do not relax validation to make an edit pass.** Validity, area, volume,
  orientation and self-intersection checks exist to catch broken results.
- **Long work runs in a worker.** Mesh and heavy kernel operations run in a
  separate process (`jobs/`, `scripts/*_worker.py`) so a crash cannot take
  FreeCAD down.
- Keep the user guide, the changelog and the tests up to date with your change.

## Tests

Run tests with FreeCAD's own Python, which has Part, Mesh and NumPy:

```sh
# Unit tests (no GUI)
sh scripts/test_macos.sh                                  # macOS app bundle
PYTHONPATH=.:<FreeCAD>/lib <FreeCAD>/bin/python -m unittest discover -s tests/unit

# GUI suites, each in a fresh FreeCAD window (xvfb-run on headless Linux)
sh scripts/test_gui.sh gui_smoke gui_line_regions
FREECAD=/path/to/freecad sh scripts/test_gui.sh          # every suite
```

Unit tests live in `tests/unit`, GUI suites in `tests/gui` and timing scripts in
`tests/benchmarks`. Add a unit test for geometry and logic, and a GUI suite when
the change is about interaction. Automated tests do not replace trying the tool
by hand: please say in your pull request what you tested manually.

## Documentation

The pages in `docs/`, together with this file, the README and the changelog,
are published as the documentation site from `main`. To preview it:

```sh
pip install -r docs/requirements.txt
mkdocs serve                 # http://127.0.0.1:8000
mkdocs build --strict        # the check pull requests run
```

Write links as they work on GitHub; the site build rewrites them. When you
change a tool, update its entry in `docs/tools/` along with the user guide.

## Pull requests

- Keep each pull request to one change, and explain what a user will see
  before and after it.
- Follow the style of the surrounding code: short functions, relative imports
  inside `simplecad/`, and comments only where the reason is not obvious.
- Mention any tests that fail before and after your change.

By contributing you agree that your work is released under the
[MIT License](LICENSE).
