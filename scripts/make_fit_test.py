"""Run with FreeCAD's Python to regenerate the shipped printable fit samples."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import FreeCAD as App
import MeshPart
import Part
from simplecad.modeling import joints
from simplecad.document import operations


def make(output):
    output.mkdir(parents=True, exist_ok=True)
    doc = operations.create_fit_test(joints.StudJoint())
    try:
        doc.Label = "SimpleCAD stud fit test — 0.00, 0.10, 0.20 mm per side"
        doc.saveAs(str(output / "StudFitTest.FCStd"))
        names = []
        for index, obj in enumerate(doc.Objects):
            clearance = (index // 2) * .1
            kind = "stud" if index % 2 == 0 else "socket"
            name = "fit_%smm_%s.stl" % (("%.2f" % clearance).replace(".", "p"), kind)
            mesh = MeshPart.meshFromShape(Shape=obj.Shape, LinearDeflection=.04, AngularDeflection=.15, Relative=False)
            if not mesh.isSolid() or mesh.Volume <= 0:
                raise ValueError("The sample mesh is not a closed printable volume: " + name)
            mesh.write(str(output / name)); names.append(name)
        plate = Part.makeCompound([obj.Shape for obj in doc.Objects])
        mesh = MeshPart.meshFromShape(Shape=plate, LinearDeflection=.04, AngularDeflection=.15, Relative=False)
        if not mesh.isSolid():
            raise ValueError("The complete plate is not watertight.")
        mesh.write(str(output / "StudFitTest_plate.stl"))
        return names
    finally:
        App.closeDocument(doc.Name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] / "examples" / "StudFitTest")
    args = parser.parse_args()
    names = make(args.output)
    print("Created native fit-test document, six individual STLs, and one complete plate:")
    print(args.output.resolve())
    for name in names:
        print(name)
