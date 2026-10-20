"""Viewport event contract for region picking, independent of Qt runtime."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch
import numpy as np
from simplecad.mesh.region import Topology, RegionPlan
from test_mesh_transform import box


QT=NS(LeftButton=1,RightButton=2,MiddleButton=4,AltModifier=8,ControlModifier=16,MetaModifier=32,ShiftModifier=64,MouseFocusReason=128)
EVENT=NS(MouseButtonPress=1,MouseMove=2,MouseButtonRelease=3)


class Widget(NS):
    """Distinguish widget events from the preceding native QWindow event."""

def module():
    path=Path(__file__).resolve().parents[2]/'simplecad/gui/tools/mesh_region.py'
    spec=importlib.util.spec_from_file_location('simplecad.gui.tools._region_ui_test',path)
    m=importlib.util.module_from_spec(spec)
    stubs={k:NS() for k in ('FreeCAD','FreeCADGui','simplecad.jobs.mesh','simplecad.mesh.region_edit')}
    stubs.update({'simplecad.mesh.stretch':NS(check_source=lambda obj:None),
                  'simplecad.gui.tools.mesh_stretch':NS(StretchPreview=Mock()),
                  'simplecad.mesh.conversion':NS(cached_fingerprints=Mock()),
                  'simplecad.gui.snapping':NS(ray=lambda view,pos:((2,3,20),(0,0,-1))),
                  'simplecad.gui.qt':NS(QtCore=NS(Qt=QT,QEvent=EVENT),QtWidgets=NS(QWidget=Widget,QApplication=NS(startDragDistance=lambda:10))),
                  'simplecad.gui.panels':NS(anchor_panel=lambda dialog:dialog)})
    with patch.dict(sys.modules,stubs): spec.loader.exec_module(m)
    return m


def event(kind,x=50,y=50,button=1,modifiers=0,buttons=None):
    return NS(type=lambda:kind,button=lambda:button,buttons=lambda:(button if kind!=3 else 0) if buttons is None else buttons,
              modifiers=lambda:modifiers,globalPos=lambda:NS(x=lambda:x+100,y=lambda:y+100),
              localPos=lambda:NS(x=lambda:x,y=lambda:y))


class PickingTests(unittest.TestCase):
    def setUp(self):
        self.module=module(); self.s=self.module.MeshRegionSession.__new__(self.module.MeshRegionSession)
        self.widget=Widget(width=lambda:100,height=lambda:100,setFocus=Mock())
        self.s.controller=NS(selection=NS(is_viewport=lambda w:w is self.widget,replaying=False,replay=Mock()),view=NS(getSize=lambda:(200,200)))
        self.s.closed=False; self.s.press=None; self.s.validation_error=''
        self.s.status=NS(setText=Mock())
        self.s.topology=Topology(*box()); self.s.shown_points=self.s.topology.points; self.s.shown_faces=self.s.topology.triangles
        self.s.origins=np.arange(12); self.s.selected=set(); self.s.selection=NS(currentText=lambda:'Flat')
        self.s.crease=NS(value=lambda:15,setEnabled=Mock()); self.s.action=NS(currentText=lambda:'Replace')
        self.s.selection_count=NS(setText=Mock())
        self.s.selection_buttons=[NS(setEnabled=Mock()) for _ in range(3)]
        self.s.changed=Mock(side_effect=self.s.update_selection_feedback); self.s.check=Mock()
        self.s.collision=None; self.s.collision_timer=Mock(); self.s.collision_poller=Mock()
        self.s.preview=NS(mark=Mock()); self.s.job=None

    def click(self,modifiers=0):
        self.assertTrue(self.s.handle_event(self.widget,event(1,modifiers=modifiers)))
        self.assertTrue(self.s.handle_event(self.widget,event(3,modifiers=modifiers)))

    def test_replace_shift_add_remove_and_physical_coordinates(self):
        original_ray=self.module.ray
        self.module.ray=Mock(side_effect=original_ray)
        self.click(); self.assertEqual(self.s.selected,{2,3})
        np.testing.assert_array_equal(self.module.ray.call_args.args[1],(100,100))
        self.s.selected={0,1}; self.click(QT.ShiftModifier); self.assertEqual(self.s.selected,{0,1,2,3})
        self.s.action=NS(currentText=lambda:'Remove'); self.click(); self.assertEqual(self.s.selected,{0,1})
        self.assertIsNone(self.s.press)

    def test_drag_and_navigation_do_not_change_selection(self):
        self.s.handle_event(self.widget,event(1))
        self.s.handle_event(self.widget,event(2,x=60))
        self.s.handle_event(self.widget,event(3,x=60))
        self.s.changed.assert_not_called()
        for modifier in (QT.AltModifier,QT.ControlModifier,QT.MetaModifier):
            self.assertFalse(self.s.handle_event(self.widget,event(1,modifiers=modifier)))
        self.assertFalse(self.s.handle_event(self.widget,event(1,button=QT.MiddleButton)))
        self.assertFalse(self.s.handle_event(self.widget,event(1,button=QT.RightButton)))

    def test_retina_click_jitter_still_picks(self):
        self.s.handle_event(self.widget,event(1))
        self.s.handle_event(self.widget,event(2,x=53))
        self.s.handle_event(self.widget,event(3,x=53))
        self.assertEqual(self.s.selected,{2,3})
        self.s.selection_count.setText.assert_called_with('2 triangles selected')

    def test_missed_click_and_remove_report_why_nothing_changed(self):
        self.module.ray=lambda view,pos:((100,100,20),(0,0,-1))
        self.click(); self.assertIn('No mesh patch',self.s.status.setText.call_args.args[0])
        self.s.changed.assert_not_called()
        self.module.ray=lambda view,pos:((2,3,20),(0,0,-1))
        self.s.action=NS(currentText=lambda:'Remove'); self.click()
        self.assertIn('Choose Replace or Add',self.s.status.setText.call_args.args[0])
        self.assertIn('Choose Replace or Add',self.s.pick_hint())

    def test_failed_apply_message_survives_missed_and_unchanged_picks(self):
        self.s.selected={2,3}
        error='This edit creates or changes self-intersections. Original mesh unchanged.'
        self.s.job=NS(status=lambda:dict(status='failed',error=error,stage='Checking mesh'))
        self.s.poller=Mock(); self.s.progress=Mock(); self.s.apply_button=Mock()
        self.s.poll()
        self.assertEqual(self.s.validation_error,error)
        self.s.apply_button.setEnabled.assert_called_with(False)
        self.click()  # Selecting the same patch does not change the rejected edit.
        self.s.status.setText.assert_called_with(error)
        self.module.ray=lambda view,pos:((100,100,20),(0,0,-1))
        self.click()
        self.s.status.setText.assert_called_with(error)
        self.s.changed.assert_not_called()

    def test_changing_parameters_clears_failure_and_schedules_fresh_preview(self):
        self.s.validation_error='Previous movement rejected'
        self.s.pending=Mock(); self.s.pending.isActive.return_value=False
        self.s.job=Mock(); job=self.s.job
        self.s.poller=Mock(); self.s.progress=Mock(); self.s.apply_button=Mock()
        self.module.MeshRegionSession.changed(self.s)
        self.assertEqual(self.s.validation_error,'')
        self.assertIsNone(self.s.job); job.cancel.assert_called_once()
        self.s.pending.start.assert_called_once_with(35)

    def test_preview_collisions_are_marked_and_stale_results_ignored(self):
        from test_mesh_region import grid
        p,f=grid(6)
        # Two stacked plates; pushing a patch of the lower one up crosses the upper.
        self.s.topology=Topology(np.vstack((p,p+(0,0,.5))),np.vstack((f,f[:,::-1]+len(p))))
        points=self.s.topology.points.copy()
        plan=RegionPlan(self.s.topology,{28,29},2); moved,faces=plan.transform(delta=(0,0,1))
        self.s.shown_points,self.s.shown_faces=moved,faces; self.s.summary_text='2 selected triangles'
        self.s.check_collisions(); self.s.collision[2].result(5)
        self.s.collisions_ready()
        marked=self.s.preview.mark.call_args.args[0]
        self.assertTrue(min(marked)<len(f)<=max(marked))
        self.assertIn('Red:',self.s.status.setText.call_args.args[0])
        # A result for an older preview never marks the current one.
        self.s.check_collisions(); future=self.s.collision[2]; future.result(5)
        self.s.shown_points=points; self.s.preview.mark.reset_mock()
        self.s.collisions_ready(); self.s.preview.mark.assert_not_called()
        # No collision: say so, and clear old marks.
        moved,faces=plan.transform(delta=(0,0,.2)); self.s.shown_points,self.s.shown_faces=moved,faces
        self.s.check_collisions(); self.s.collision[2].result(5); self.s.collisions_ready()
        self.assertEqual(len(self.s.preview.mark.call_args.args[0]),0)
        self.assertIn('No collisions',self.s.status.setText.call_args.args[0])

    def test_replaced_preview_cancels_its_queued_collision_check(self):
        import threading
        release=threading.Event()
        busy=self.module._collisions.submit(release.wait,5)
        try:
            plan=RegionPlan(self.s.topology,{2,3},1); moved,faces=plan.transform(delta=(0,0,1))
            self.s.shown_points,self.s.shown_faces=moved,faces; self.s.summary_text=''
            self.s.check_collisions(); queued=self.s.collision[2]
            self.s.stop_collision_check()
            self.assertTrue(queued.cancelled())
            self.assertIsNone(self.s.collision)
        finally:
            release.set(); busy.result(5)
        # A finished or deferred check has nothing to cancel.
        self.s.check_collisions(); self.s.collision[2].result(5); self.s.stop_collision_check()
        with patch.object(self.module.mesh_collisions,'PREVIEW_LIMIT',1):
            self.s.check_collisions()
        self.s.stop_collision_check()

    def test_large_edits_defer_collisions_to_apply_and_worker_marks_failures(self):
        plan=RegionPlan(self.s.topology,{2,3},1); moved,faces=plan.transform(delta=(0,0,1))
        self.s.shown_points,self.s.shown_faces=moved,faces; self.s.summary_text=''
        with patch.object(self.module.mesh_collisions,'PREVIEW_LIMIT',1):
            self.s.check_collisions()
        self.assertIn('Large edit',self.s.status.setText.call_args.args[0])
        self.s.show_failed_triangles([4,5]); np.testing.assert_array_equal(self.s.preview.mark.call_args.args[0],[4,5])
        self.s.preview.mark.reset_mock(); self.s.show_failed_triangles([99]); self.s.preview.mark.assert_not_called()

    def test_selection_controls_and_empty_hint_follow_current_mode(self):
        self.s.update_selection_feedback()
        self.s.selection_count.setText.assert_called_with('0 triangles selected')
        for button in self.s.selection_buttons: button.setEnabled.assert_called_with(False)
        self.s.crease.setEnabled.assert_called_with(False)
        self.s.selection=NS(currentText=lambda:'Triangle')
        self.assertIn('a triangle',self.s.pick_hint())
        self.s.selection=NS(currentText=lambda:'Smooth'); self.s.selected={2}; self.s.update_selection_feedback()
        self.s.selection_count.setText.assert_called_with('1 triangle selected')
        self.s.crease.setEnabled.assert_called_with(True)
        for button in self.s.selection_buttons: button.setEnabled.assert_called_with(True)

    def test_navigation_chord_replays_press_without_picking(self):
        self.s.handle_event(self.widget,event(1))
        self.assertFalse(self.s.handle_event(self.widget,event(1,button=QT.MiddleButton,buttons=QT.MiddleButton|QT.LeftButton)))
        self.s.controller.selection.replay.assert_called_once()
        self.assertIsNone(self.s.press); self.s.changed.assert_not_called()
        self.s.controller.selection.replaying=True
        self.assertFalse(self.s.handle_event(self.widget,event(1)))

    def test_preview_cap_maps_to_original_patch(self):
        plan=RegionPlan(self.s.topology,{2,3}); p,f=plan.transform('Extrude',distance=3)
        self.s.shown_points,self.s.shown_faces=p,f
        self.s.origins=np.r_[[0,1],np.arange(4,12),[2,3],np.full(8,-1)]
        self.click(); self.assertEqual(self.s.selected,{2,3})

    def test_unrelated_paint_and_timer_events_do_not_cancel_click(self):
        self.s.handle_event(self.widget,event(1))
        self.assertFalse(self.s.handle_event(NS(),NS(type=lambda:999)))
        self.assertIsNotNone(self.s.press)
        self.s.handle_event(self.widget,event(3))
        self.assertEqual(self.s.selected,{2,3})

    def test_native_window_mouse_events_do_not_cancel_viewport_click(self):
        # A real OS click visits QWidgetWindow first, then its render QWidget.
        # sendEvent(viewport, ...) skips the first visit and concealed this bug.
        window=NS()
        for kind in (EVENT.MouseButtonPress,EVENT.MouseMove,EVENT.MouseButtonRelease):
            self.assertFalse(self.s.handle_event(window,event(kind)))
            self.assertTrue(self.s.handle_event(self.widget,event(kind)))
        self.assertEqual(self.s.selected,{2,3})
        self.s.changed.assert_called_once()

    def test_native_window_release_alone_does_not_pick(self):
        self.s.handle_event(self.widget,event(EVENT.MouseButtonPress))
        self.assertFalse(self.s.handle_event(NS(),event(EVENT.MouseButtonRelease)))
        self.assertIsNotNone(self.s.press)
        self.s.changed.assert_not_called()
        # An actual release over another QWidget still cancels the pending pick.
        self.assertFalse(self.s.handle_event(Widget(),event(EVENT.MouseButtonRelease)))
        self.assertIsNone(self.s.press)

    def test_release_outside_or_navigation_modifier_clears_pending_click(self):
        self.s.handle_event(self.widget,event(1))
        self.assertFalse(self.s.handle_event(Widget(),event(3)))
        self.assertIsNone(self.s.press)
        self.s.handle_event(self.widget,event(1))
        self.s.handle_event(self.widget,event(3,modifiers=QT.AltModifier))
        self.assertIsNone(self.s.press); self.s.changed.assert_not_called()


if __name__=='__main__': unittest.main()
