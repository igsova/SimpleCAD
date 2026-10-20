# Stud/socket fit test

Print **StudFitTest_plate.stl** to try all three fits, or import an individual stud/socket pair. The native **StudFitTest.FCStd** contains the same six separate objects with labeled clearances. All pieces have flat bottoms at Z = 0; studs and socket openings face up. STL dimensions are millimeters: import at **100% scale**.

| Pair | Stud diameter | Socket diameter below its entry chamfer | Clearance per side |
|---|---|---|---|
| `fit_0p00mm_*` | 6.00 mm | 6.00 mm | 0.00 mm |
| `fit_0p10mm_*` | 6.00 mm | 6.20 mm | +0.10 mm |
| `fit_0p20mm_*` | 6.00 mm | 6.40 mm | +0.20 mm |

Studs are 4 mm long with tapered tips. Sockets are 4.2 mm deep with widened entry chamfers. Each pad is 11.6 × 11.6 mm, with a 6.4 mm base thickness. On the complete plate, the columns run from 0.00 to 0.10 to 0.20 mm as X increases; the stud row is at lower Y and the socket row at higher Y. Keep track of the socket columns as you remove them. All three studs have the same dimensions.

Use the PLA or PETG and print settings you intend to use for the model. Try the matching pairs, choose the fit that holds as you want, then enter that **clearance per side** in Slice / Separate. If all are too loose, use **Make a fit test** with a lower clearance (negative values give nominal interference). If all are too tight, increase it. The button generates samples at the entered clearance and ±0.10 mm using your current stud diameter, length and wall size.

The test measures a single-stud friction fit. A pattern with several studs can take more force to assemble. These samples have passed native solid and watertight mesh checks; they have not been physically printed here. Material, orientation and print settings affect the fit, as described in [Prusa's modeling guidance](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135).

To regenerate these default files, run `scripts/make_fit_test.py` using FreeCAD's bundled Python. The script validates the meshes before exporting.
