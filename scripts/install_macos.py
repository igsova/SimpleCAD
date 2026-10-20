#!/usr/bin/env python3
"""Install into the Mod directory reported by FreeCAD; never replace an addon."""
import argparse
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freecad-app", default="/Applications/FreeCAD.app")
    parser.add_argument("--mod-dir", type=Path, help="Override using the path reported in FreeCAD's console")
    parser.add_argument("--copy", action="store_true", help="Copy files instead of creating a development symlink")
    parser.add_argument("--uninstall", action="store_true", help="Remove only a symlink pointing to this repository")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    destination_root = args.mod_dir
    if destination_root is None:
        resources = Path(args.freecad_app) / "Contents/Resources"
        executable = resources / "bin/python"
        if not executable.exists():
            parser.error("FreeCAD was not found. Supply --freecad-app or --mod-dir.")
        script = "import sys; sys.path.insert(0, sys.argv[1]); import FreeCAD; print('SC_DATA=' + FreeCAD.getUserAppDataDir())"
        result = subprocess.run([str(executable), "-c", script, str(resources / "lib")],
                                capture_output=True, text=True)
        paths = [line[8:] for line in result.stdout.splitlines() if line.startswith("SC_DATA=")]
        if result.returncode or not paths:
            parser.error("Could not ask FreeCAD for its data directory. Use --mod-dir.\n" + result.stderr)
        destination_root = Path(paths[-1]) / "Mod"
    destination = destination_root.expanduser() / "SimpleCAD"
    same_link = destination.is_symlink() and destination.resolve() == source
    if args.uninstall:
        if not same_link:
            parser.error("Refusing to remove anything except a symlink to this repository.")
        destination.unlink()
        print("Removed " + str(destination) + ". Restart FreeCAD.")
        return
    if same_link:
        print("Already linked: " + str(destination))
        return
    if destination.exists() or destination.is_symlink():
        parser.error("An addon already exists at " + str(destination) + ". Rename it before installing.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if args.copy:
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store"))
    else:
        destination.symlink_to(source, target_is_directory=True)
    print("Installed: " + str(destination))
    print("Restart FreeCAD and choose SimpleCAD in the workbench selector.")


if __name__ == "__main__":
    main()
