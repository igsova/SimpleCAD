#!/bin/sh
# Run FreeCAD GUI suites, each in a fresh FreeCAD process.
#   sh scripts/test_gui.sh gui_mesh_region gui_mesh_stretch
#   sh scripts/test_gui.sh            # every tests/gui/gui_*.py
# FREECAD selects the executable. On Linux without a display, xvfb-run is used.
# Logs are written to $SC_GUI_LOG_DIR (default: a temporary directory).
set -u
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -z "${FREECAD:-}" ]; then
  if [ -x /Applications/FreeCAD.app/Contents/MacOS/FreeCAD ]; then
    FREECAD=/Applications/FreeCAD.app/Contents/MacOS/FreeCAD
  else
    FREECAD=freecad
  fi
fi
logs=${SC_GUI_LOG_DIR:-$(mktemp -d)}
suites=$*
[ -n "$suites" ] || suites=$(cd "$repo_dir/tests/gui" && ls gui_*.py | sed 's/\.py$//')
headless=0
if [ "$(uname)" = Linux ] && [ -z "${DISPLAY:-}" ] && command -v xvfb-run >/dev/null; then
  headless=1
fi
failed=0
for suite in $suites; do
  if [ $headless -eq 1 ]; then
    SC_GUI_TESTS=$suite SC_GUI_LOG="$logs/$suite.log" timeout 900 \
      xvfb-run -a -s "-screen 0 1600x1000x24" "$FREECAD" "$repo_dir/scripts/run_gui_tests.py" >"$logs/$suite.out" 2>&1
  else
    SC_GUI_TESTS=$suite SC_GUI_LOG="$logs/$suite.log" \
      "$FREECAD" "$repo_dir/scripts/run_gui_tests.py" >"$logs/$suite.out" 2>&1
  fi
  status=$?
  if [ $status -eq 0 ]; then echo "PASS $suite"; else echo "FAIL $suite (exit $status, log $logs/$suite.log)"; failed=1; fi
done
exit $failed
