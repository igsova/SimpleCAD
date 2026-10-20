"""Reusable Coin mesh buffers must shrink along with the selected region."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
import numpy as np
from simplecad.mesh.region import Topology, RegionPlan
from test_mesh_transform import box


class MultiField:
    """Coin setValues replaces a prefix; it does not truncate trailing values."""
    def __init__(self):
        self.values=[]
        self.writes=0

    def setNum(self,n):
        self.values=self.values[:n]+[None]*max(0,n-len(self.values))

    def setValues(self,*args):
        # Pivy accepts setValues(sequence) or setValues(start, count, array).
        start,values=(0,args[0]) if len(args)==1 else (args[0],args[2][:args[1]])
        self.values[start:start+len(values)]=list(values)
        self.writes+=1


def preview():
    path=Path(__file__).resolve().parents[2]/'simplecad/gui/tools/mesh_stretch.py'
    spec=importlib.util.spec_from_file_location('simplecad.gui.tools._mesh_preview_test',path)
    module=importlib.util.module_from_spec(spec)
    stubs={name:NS() for name in ('FreeCAD','FreeCADGui','simplecad.jobs.mesh',
                                  'simplecad.mesh.slicing','simplecad.mesh.stretch')}
    stubs.update({'pivy':NS(coin=NS()),'simplecad.mesh.conversion':NS(cached_fingerprints=Mock()),
                  'simplecad.gui.previews.shaded':NS(RoundPreview=object,NativeMask=Mock()),
                  'simplecad.gui.qt':NS(QtCore=NS(),QtWidgets=NS()),
                  'simplecad.gui.panels':NS(anchor_panel=lambda dialog:dialog)})
    with patch.dict(sys.modules,stubs): spec.loader.exec_module(module)
    p=module.StretchPreview.__new__(module.StretchPreview)
    p.node=NS(enableNotify=Mock(return_value=True),touch=Mock())
    p.faces=NS(coordIndex=MultiField()); p.coords=NS(point=MultiField())
    p.material=NS(diffuseColor=MultiField()); p.view=NS(redraw=Mock())
    p.masks=[object()]; p.key=p.topology=None; p.marked=(); p.painted=None
    return p


class SequenceOnlyField(MultiField):
    def setValues(self,values):
        super().setValues(values)


class PreviewTests(unittest.TestCase):
    def test_pivy_without_numpy_typemaps_receives_lists(self):
        p=preview(); p.faces.coordIndex,p.coords.point,p.material.diffuseColor=(
            SequenceOnlyField(),SequenceOnlyField(),SequenceOnlyField())
        t=Topology(*box()); p.show_mesh(t.triangles,np.zeros(8),t.points,t)
        self.assert_mesh(p,t.points,t.triangles)

    def assert_mesh(self,preview,points,faces):
        expected=[int(v) for face in faces for v in (*face,-1)]
        self.assertEqual([int(v) for v in preview.faces.coordIndex.values],expected)
        # SoMFVec3f stores single precision, as Coin always did.
        np.testing.assert_array_equal(preview.coords.point.values,np.float32(points))
        self.assertEqual(len(preview.material.diffuseColor.values),len(faces))

    def test_shrink_extrusion_then_clear_discards_old_walls_and_vertices(self):
        p=preview(); topology=Topology(*box())
        for selected in ({2,3},{2}):
            plan=RegionPlan(topology,selected)
            points,faces=plan.transform('Extrude',distance=20)
            weights=np.r_[np.zeros(len(topology.points)),np.ones(len(plan.vertices))]
            p.show_mesh(faces,weights,points,plan)
            self.assert_mesh(p,points,faces)
        p.show_mesh(topology.triangles,np.zeros(len(topology.points)),topology.points,topology)
        self.assert_mesh(p,topology.points,topology.triangles)

    def test_cached_distance_change_updates_coordinates_without_rebuilding_indices(self):
        p=preview(); plan=RegionPlan(Topology(*box()),{2,3})
        weights=np.r_[np.zeros(8),np.ones(4)]
        for distance in (2,20):
            points,faces=plan.transform('Extrude',distance=distance)
            p.show_mesh(faces,weights,points,plan)
            self.assert_mesh(p,points,faces)
        self.assertEqual(p.faces.coordIndex.writes,1)
        self.assertEqual(p.material.diffuseColor.writes,1)

    def test_retriangulation_refreshes_colors_with_same_selection(self):
        from test_mesh_retriangulate import perforated_plate
        p=preview(); t=Topology(*perforated_plate())
        plan=RegionPlan(t,set(np.flatnonzero(t.normals[:,0]>.999)))
        for delta in ((0,0,0),(5,0,0),(0,0,0)):
            points,faces=plan.transform(delta=delta)
            p.show_mesh(faces,plan.weights,points,plan)
            self.assert_mesh(p,points,faces)
            weights=plan.weights[faces].mean(axis=1)
            expected=np.column_stack((.3+.65*weights,.7-.25*weights,.85-.6*weights))
            np.testing.assert_allclose(np.asarray(p.material.diffuseColor.values,dtype=float),expected,rtol=1e-6)
        self.assertEqual(p.material.diffuseColor.writes,3)


if __name__=='__main__': unittest.main()
