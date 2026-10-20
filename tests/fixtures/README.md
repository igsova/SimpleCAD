# Fitted surface Line regression

`fitted_surface_loop.brep.gz` contains a two-face open shell and three wrapped
Line segments, in draw order. They are reduced from a temporary reconstruction
of the P15 sensor hood, using the failing loop's inspected world coordinates.
It contains neither the complete hood nor the user's saved CAD document.

Closing the third segment splits the two B-spline faces into four. The previous
whole-compound skin comparison reports one complete resulting patch as extra
surface and raises `Dividing a face must preserve its surface area.` Each
identical-support trim comparison instead has no missing or added faces. Scalar
surface integrals drift by about 0.03 mm² when their trim domains change.

Keep the native surfaces, trims and tolerances intact: rebuilding this fixture
as regular planes or freshly trimmed/cropped patches loses the kernel failure.
Gzip stores the native ASCII BREP losslessly; the fixture has no executable code.
