"""Real stdio MCP client -> authenticated bridge -> native FreeCAD/Undo."""
from concurrent.futures import ThreadPoolExecutor
import base64
import http.client
import json
import math
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import visibility
from simplecad.core import preferences
from simplecad.gui.controller import instance as controller
from simplecad.mcp.bridge import instance as bridge_instance, Bridge
from simplecad.mcp.connection import Client, exchange, read_connection
from simplecad.gui.qt import QtCore, QtGui, QtWidgets


def run(screenshots=False):
    Gui.activateWorkbench('SimpleCADWorkbench')
    c=controller(); c.cancel(quiet=True)
    original_docs=set(App.listDocuments()); original_settings=preferences.load()
    server=bridge_instance()
    server.stop()
    pool=ThreadPoolExecutor(max_workers=3)
    process=None
    calls=set()
    def wait(future):
        deadline=time.monotonic()+60
        while not future.done():
            QtWidgets.QApplication.processEvents(); Gui.updateGui(); time.sleep(.005)
            if time.monotonic()>deadline: raise AssertionError('MCP test response timed out')
        return future.result()
    try:
        with tempfile.TemporaryDirectory(prefix='simplecad-mcp-test-') as folder:
            server.start(directory=folder)
            connection_path=server.path; connection=read_connection(connection_path)
            assert connection['host']=='127.0.0.1' and (connection_path.stat().st_mode&0o777)==0o600
            assert (Path(folder).stat().st_mode&0o777)==0o700
            assert 'SimpleCAD_MCP' in Gui.listCommands()
            process=subprocess.Popen([shutil.which('python3') or sys.executable,str(ROOT/'scripts/simplecad_mcp.py'),'--connection',str(connection_path)],
                                     stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
            counter=0
            def request(method,params=None):
                nonlocal counter
                counter+=1
                process.stdin.write(json.dumps({'jsonrpc':'2.0','id':counter,'method':method,'params':params or {}})+'\n'); process.stdin.flush()
                line=wait(pool.submit(process.stdout.readline)); assert line,process.poll()
                value=json.loads(line); assert value['id']==counter,value
                assert 'error' not in value,value
                return value['result']
            initialized=request('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'SimpleCADTest','version':'1'}})
            assert initialized['capabilities']=={'tools':{}}
            process.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n'); process.stdin.flush()
            tools=request('tools/list')['tools']; assert len(tools)==50
            def call(name,expected_error=None,**args):
                calls.add('simplecad_'+name)
                result=request('tools/call',{'name':'simplecad_'+name,'arguments':args})
                if expected_error:
                    assert result.get('isError') and expected_error in result['content'][0]['text'],result
                    return result
                assert not result.get('isError'),result
                return result.get('structuredContent',result)
            created=call('create_document',label='MCP integration')
            doc=App.getDocument(created['document'])
            def read(): return call('inspect_document',document=doc.Name)
            def edit(name,expected_error=None,**args):
                stamp=read()
                return call(name,expected_error,document=doc.Name,expected_revision=stamp['revision'],**args)
            listing=call('list_documents'); assert listing['active_document']==doc.Name
            r=edit('create_rectangle',origin=[0,0,0],width=30,height=20)
            owner=doc.getObject(r['object']['name']); assert math.isclose(owner.Shape.Area,600)
            count=doc.UndoCount
            r=edit('push_pull',object=owner.Name,face='Face1',distance=10)
            assert math.isclose(owner.Shape.Volume,6000) and doc.UndoCount==count+1
            details=call('inspect_object',document=doc.Name,object=owner.Name)['object']
            assert details['valid'] and details['closed'] and details['faces']==6
            faces=call('inspect_elements',document=doc.Name,object=owner.Name,kind='Face',limit=3)
            assert faces['total']==6 and len(faces['elements'])==3 and faces['next_offset']==3
            top=next('Face'+str(i) for i,f in enumerate(owner.Shape.Faces,1) if f.CenterOfMass.z>9.99)
            for kind in ('Edge','Vertex'):
                data=call('inspect_elements',document=doc.Name,object=owner.Name,kind=kind)
                assert data['elements'] and data['elements'][0]['visible']
            edit('set_locked',targets=[{'object':owner.Name,'elements':[top]}],locked=True)
            protected=call('inspect_object',document=doc.Name,object=owner.Name)['object']
            assert protected['locked_faces']==[top]
            edit('push_pull','locked',object=owner.Name,face=top,distance=2)
            edit('set_locked',targets=[{'object':owner.Name}],locked=True)
            assert call('inspect_object',document=doc.Name,object=owner.Name)['object']['locked']
            edit('set_visibility',targets=[{'object':owner.Name}],visible=False)
            edit('set_visibility',targets=[{'object':owner.Name}],visible=True)
            edit('set_appearance',targets=[{'object':owner.Name}],opacity=80)
            edit('set_appearance',targets=[{'object':owner.Name}],opacity=100)
            edit('set_locked',targets=[{'object':owner.Name}],locked=False)
            edit('set_locked',targets=[{'object':owner.Name,'elements':[top]}],locked=False)
            edit('select',targets=[{'object':owner.Name,'elements':[top]}])
            assert call('get_selection',document=doc.Name)['targets'][0]['elements']==[top]
            edit('set_appearance',targets=[{'object':owner.Name,'elements':[top]}],color=[1,0,0],opacity=35)
            appearances=call('inspect_elements',document=doc.Name,object=owner.Name,kind='Face')['elements']
            assert next(f for f in appearances if f['name']==top)['appearance']=={'color':[1,0,0],'opacity':35}
            edit('undo')
            previous=read()
            materials=owner.ViewObject.ShapeAppearance
            material=owner.ViewObject.ShapeAppearance[0]; material.DiffuseColor=(0.,1.,0.)
            owner.ViewObject.ShapeAppearance=[material]
            call('set_appearance','model changed',document=doc.Name,expected_revision=previous['revision'],
                 targets=[{'object':owner.Name}],opacity=50)
            owner.ViewObject.ShapeAppearance=materials
            before=owner.Shape
            edit('set_visibility',targets=[{'object':owner.Name,'elements':[top]}],visible=False)
            assert visibility.hidden_faces(owner)=={int(top[4:])} and owner.Shape.isSame(before)
            edit('undo'); assert not visibility.hidden_faces(owner)
            edit('redo'); assert visibility.hidden_faces(owner)
            edit('set_visibility',targets=[{'object':owner.Name}],visible=False)
            edit('set_visibility',targets=[{'object':owner.Name,'elements':[top]}],visible=True)
            assert owner.ViewObject.Visibility and not visibility.hidden_faces(owner)
            # A UI edit invalidates prior revisions before any remote side effect.
            stale=read()['revision']; count=doc.UndoCount
            owner.Label='Renamed in UI'
            call('delete','model changed',document=doc.Name,expected_revision=stale,targets=[{'object':owner.Name}])
            assert doc.getObject(owner.Name) and doc.UndoCount==count
            server.api.allow_changes=False
            edit('move','read-only',objects=[owner.Name],delta=[1,0,0])
            assert call('inspect_object',document=doc.Name,object=owner.Name)['object']['volume']==6000
            server.api.allow_changes=True
            c.start('Line')
            edit('move','manual SimpleCAD',objects=[owner.Name],delta=[1,0,0])
            c.cancel(quiet=True)
            count=doc.UndoCount; stable=read()['revision']
            edit('create_circle','positive radius',origin=[0,0,0],radius=-1)
            assert doc.UndoCount==count and read()['revision']==stable
            edit('create_sphere','positive radius',origin=[0,0,0],radius=-1)
            assert doc.UndoCount==count and read()['revision']==stable
            sphere=edit('create_sphere',origin=[15,10,10],radius=4)['object']
            ball=doc.getObject(sphere['name'])
            assert sphere['valid'] and sphere['closed'] and sphere['faces']==1
            assert abs(ball.Shape.Volume-4*math.pi*64/3)<1e-6
            assert (ball.Shape.CenterOfMass-App.Vector(15,10,10)).Length<1e-7
            assert owner.Shape.Volume==6000 and 'SC_Support' not in ball.PropertiesList
            assert doc.UndoCount==count+1
            edit('undo'); assert doc.getObject(sphere['name']) is None
            edit('redo'); assert doc.getObject(sphere['name']).Shape.isClosed()
            intersection=edit('intersect_faces',targets=[{'object':owner.Name,'elements':[top]},
                                                         {'object':sphere['name'],'elements':['Face1']}])['object']
            assert intersection['faces']==9 and doc.getObject(sphere['name']) is None
            upper=next('Face'+str(i) for i,f in enumerate(owner.Shape.Faces,1)
                       if isinstance(f.Surface,Part.Sphere) and f.CenterOfMass.z>10)
            edit('delete',targets=[{'object':owner.Name,'elements':[upper]}])
            disk=next('Face'+str(i) for i,f in enumerate(owner.Shape.Faces,1)
                      if isinstance(f.Surface,Part.Plane) and abs(f.Area-math.pi*16)<1e-5)
            edit('delete',targets=[{'object':owner.Name,'elements':[disk]}])
            assert owner.Shape.isClosed() and len(owner.Shape.Solids)==1
            assert abs(owner.Shape.Volume-(6000-2*math.pi*64/3))<1e-5
            for _ in range(3): edit('undo')
            assert len(owner.Shape.Faces)==6 and doc.getObject(sphere['name']) is not None
            edit('delete',targets=[{'object':sphere['name']}])
            # Circle partitions the actual host and produces a pullable disk.
            edit('create_circle',origin=[15,10,10],normal=[0,0,1],radius=3,support=owner.Name)
            disk=next('Face'+str(i) for i,f in enumerate(owner.Shape.Faces,1) if abs(f.Area-math.pi*9)<1e-6 and f.CenterOfMass.z>9.99)
            edit('push_pull',object=owner.Name,face=disk,distance=3)
            assert abs(owner.Shape.Volume-(6000+27*math.pi))<1e-5
            copy=edit('copy',objects=[owner.Name],delta=[60,0,0])['objects'][0]['name']
            edit('move',objects=[copy],delta=[5,0,0])
            copied=doc.getObject(copy); volume=copied.Shape.Volume
            edit('rotate',objects=[copy],angle=30,axis='LocalX',pivot='Each')
            assert abs(copied.Shape.Volume-volume)<1e-5
            poly=edit('create_polygon',origin=[120,0,0],radius=10,sides=3)['object']['name']
            edit('subdivide',object=poly,face='Face1',pattern='triangles',divisions=3)
            assert len(doc.getObject(poly).Shape.Faces)==9
            grid=edit('create_rectangle',origin=[160,0,0],width=20,height=20)['object']['name']
            edit('subdivide',object=grid,face='Face1',pattern='grid',rows=2,columns=3)
            assert len(doc.getObject(grid).Shape.Faces)==6
            line=edit('create_line',start=[200,0,0],end=[210,0,0])['object']['name']
            edit('cleanup',objects=[line])
            edit('delete',targets=[{'object':line}]); assert doc.getObject(line) is None
            edit('undo'); assert doc.getObject(line) is not None
            curved=edit('create_arc',origin=[200,30,0],start=[205,30,0],sweep=180)['object']['name']
            assert isinstance(doc.getObject(curved).Shape.Edges[0].Curve,Part.Circle)
            closed=edit('create_line',start=[195,30,0],end=[205,30,0])
            assert closed['divided_face'] and closed['object']['faces']==1
            bowed=edit('create_2_point_arc',start=[200,50,0],end=[210,50,0],bulge=-7)['object']['name']
            assert isinstance(doc.getObject(bowed).Shape.Edges[0].Curve,Part.Circle)
            edit('create_arc','sweep',origin=[200,80,0],start=[205,80,0],sweep=360)
            edit('create_2_point_arc','bulge',start=[200,80,0],end=[210,80,0],bulge=0)
            offset_line=edit('offset',object=line,element='Edge1',distance=2,normal=[0,0,1])['objects'][0]
            assert offset_line['faces']==0 and offset_line['edges']==1
            offset_arc=edit('offset',object=bowed,element='Edge1',distance=1)['objects'][0]
            assert offset_arc['faces']==0 and isinstance(doc.getObject(offset_arc['name']).Shape.Edges[0].Curve,Part.Circle)
            sheet=edit('create_rectangle',origin=[350,0,0],width=20,height=20)['object']['name']
            offset_sheet=edit('offset',object=sheet,element='Face1',distance=-2)['objects'][0]
            assert offset_sheet['faces']==2
            edit('offset','nonzero',object=line,element='Edge1',distance=0,normal=[0,0,1])
            # Native single-transaction round, slice, joint and Union results.
            box=doc.addObject('Part::Feature','JointBox'); box.Shape=Part.makeBox(30,24,30,App.Vector(240,0,0)); doc.recompute()
            edit('round_edges',targets=[{'object':box.Name,'elements':['Edge1']}],radius=1)
            assert len(box.Shape.Faces)==7 and box.Shape.isValid()
            edit('undo'); assert len(box.Shape.Faces)==6
            count=doc.UndoCount
            pieces=edit('slice',objects=[box.Name],axis='Z',gap=4,joint={'count':1,'diameter':6,'length':4})['objects']
            assert len(pieces)==2 and all(p['valid'] and p['closed'] for p in pieces) and doc.UndoCount==count+1
            edit('undo'); box=doc.getObject('JointBox'); assert box.Shape.isValid()
            top=next(i+1 for i,f in enumerate(box.Shape.Faces) if abs(f.CenterOfMass.z-30)<1e-9)
            pieces=edit('slice',objects=[box.Name],at_face={'object':box.Name,'face':'Face%d'%top})['objects']
            assert len(pieces)==1  # A cut on the top face leaves the block whole.
            edit('undo'); box=doc.getObject('JointBox')
            other=doc.addObject('Part::Feature','Overlap'); other.Shape=Part.makeBox(20,24,30,App.Vector(260,0,0)); doc.recompute()
            merged=edit('union',objects=[box.Name,other.Name])['object']
            assert merged['solids']==1 and merged['faces']==6 and abs(merged['volume']-28800)<1e-6
            settings=call('get_settings')['settings']
            changed=call('set_settings',settings={'center_radius':44})
            assert changed['settings']['center_radius']==44
            call('set_settings',settings=settings)
            fit=call('fit_test',joint={'count':1}); assert len(App.getDocument(fit['document']).Objects)==6
            call('activate_document',document=doc.Name,expected_revision=read()['revision'])
            call('view',document=doc.Name,orientation='Isometric',fit=True)
            picture=call('capture_view',document=doc.Name,width=800,height=600)
            assert base64.b64decode(picture['content'][0]['data']).startswith(b'\x89PNG\r\n\x1a\n')
            created=call('create_document',label='MCP vertex deformation'); doc=App.getDocument(created['document'])
            vertex_owner=App.ActiveDocument.addObject('Part::Feature','VertexBox')
            vertex_owner.Shape=Part.makeBox(10,10,10); App.ActiveDocument.recompute()
            old_point=vertex_owner.Shape.Vertexes[0].Point
            moved=edit('move_vertex',object=vertex_owner.Name,vertex='Vertex1',delta=[-2,-3,2])
            assert moved['object']['valid'] and moved['object']['solids']==1
            assert any((v.Point-old_point-App.Vector(-2,-3,2)).Length<1e-6 for v in vertex_owner.Shape.Vertexes)
            edit('undo'); assert abs(vertex_owner.Shape.Volume-1000)<1e-6
            edit('redo'); assert len(vertex_owner.Shape.Faces)>6
            # New formation tools use the same native operations and one Undo.
            created=call('create_document',label='MCP scale loft sweep');doc=App.getDocument(created['document'])
            sphere=edit('create_sphere',origin=[0,0,0],radius=4)['object']['name']
            resized=edit('scale',objects=[sphere],factors=[1.5,1,2],axes='World',pivot='Each')['objects'][0]
            assert resized['valid'] and resized['closed'] and resized['solids']==1
            edit('undo');assert abs(doc.getObject(sphere).Shape.Volume-4/3*math.pi*4**3)<1e-5
            p=edit('create_circle',origin=[30,0,0],radius=3)['object']['name']
            q=edit('create_circle',origin=[30,0,15],radius=1)['object']['name']
            result=edit('loft',profiles=[{'object':p},{'object':q}],solid=True)['object']
            assert result['valid'] and result['closed'] and result['solids']==1
            assert not doc.getObject(p).ViewObject.Visibility and not doc.getObject(q).ViewObject.Visibility
            edit('loft','different',profiles=[{'object':p},{'object':p}])
            profile=edit('create_circle',origin=[60,0,0],radius=1)['object']['name']
            path=edit('create_arc',origin=[70,0,0],start=[60,0,0],normal=[0,0,1],sweep=150)['object']['name']
            result=edit('sweep',profile={'object':profile},path={'object':path},align=True)['object']
            assert result['valid'] and result['closed'] and result['solids']==1
            assert not doc.getObject(profile).ViewObject.Visibility and not doc.getObject(path).ViewObject.Visibility
            created=call('create_document',label='MCP bend and soft move');doc=App.getDocument(created['document'])
            base=edit('create_rectangle',origin=[0,0,0],width=6,height=6)['object']['name']
            edit('push_pull',object=base,face='Face1',distance=25)
            before=doc.getObject(base).Shape.copy()
            bent=edit('deform',object=base,mode='Bend',axis='Z',angle=40,detail=4)
            assert bent['changed'] and bent['object']['valid'] and bent['object']['closed']
            assert bent['object']['faces']>6
            edit('undo');assert abs(doc.getObject(base).Shape.Volume-before.Volume)<1e-5
            moved=edit('deform',object=base,mode='Move',center=[3,3,25],radius=15,delta=[2,0,0],detail=4)
            assert moved['object']['valid'] and moved['object']['closed']
            edit('undo')
            edit('deform','requires delta',object=base,mode='Move')
            assert calls=={tool['name'] for tool in tools},set(tool['name'] for tool in tools)-calls
            # A through-cut may disconnect a bridge. Every resulting owner
            # must be returned to the MCP client, not silently omitted.
            created=call('create_document',label='MCP separated cut')
            doc=App.getDocument(created['document'])
            shape=Part.makeBox(10,10,10).fuse(Part.makeBox(10,4,4,App.Vector(10,3,3))).fuse(
                Part.makeBox(10,10,10,App.Vector(20,0,0)))
            seed=doc.addObject('Part::Feature','Bridge');seed.Shape=shape;doc.recompute()
            face=next('Face'+str(i) for i,f in enumerate(seed.Shape.Faces,1)
                      if (f.CenterOfMass-App.Vector(15,5,7)).Length<1e-6)
            split=edit('push_pull',object=seed.Name,face=face,distance=-4)
            assert split['object']['name']==seed.Name and len(split['objects'])==2
            assert all(item['valid'] and item['closed'] and item['solids']==1 for item in split['objects'])
            assert abs(sum(item['volume'] for item in split['objects'])-2000)<1e-6
            edit('undo');assert len(doc.Objects)==1 and abs(seed.Shape.Volume-2160)<1e-6
            edit('redo');assert len(doc.Objects)==2
            # Transport authentication, Origin rejection and duplicate IDs.
            def http_status(headers):
                client=http.client.HTTPConnection('127.0.0.1',connection['port'],timeout=2)
                try:
                    client.request('GET','/health',headers=headers); response=client.getresponse(); response.read(); return response.status
                finally: client.close()
            assert wait(pool.submit(http_status,{}))==403
            assert wait(pool.submit(http_status,{'Authorization':'Bearer '+connection['token'],'Origin':'https://example.com'}))==403
            duplicate={'call_id':uuid.uuid4().hex,'name':'simplecad_create_document','arguments':{'label':'Duplicate ID test'}}
            first=wait(pool.submit(exchange,connection,duplicate))
            second=wait(pool.submit(exchange,connection,duplicate))
            assert first==second
            # A timed-out queued edit must never run later when Qt becomes free.
            server.timer.stop(); server.wait_seconds=.05
            before_docs=set(App.listDocuments())
            expired=wait(pool.submit(exchange,connection,{'call_id':uuid.uuid4().hex,
                                'name':'simplecad_create_document','arguments':{'label':'Must not appear'}}))
            assert 'cancelled' in expired['error']
            server.process(); assert set(App.listDocuments())==before_docs
            server.wait_seconds=45; server.timer.start()
            # Multiple instances require an explicit connection; pinned clients
            # must not switch to another FreeCAD model after a stop/restart.
            second_server=Bridge()
            try:
                second_server.start(directory=folder)
                try: wait(pool.submit(Client(directory=folder).connect)); assert False
                except ValueError as error: assert 'Several' in str(error)
            finally: second_server.stop()
            if screenshots:
                # Retain the native QAction wrappers while accessing their menus
                # in FreeCAD's embedded PySide runtime.
                menu_bar=Gui.getMainWindow().menuBar()
                menu_actions=menu_bar.actions()
                menus=[action.menu() for action in menu_actions
                       if action.text().replace('&','')=='SimpleCAD']
                assert len(menus)==1, 'SimpleCAD menu is missing from native startup'
                actions=[action for action in menus[0].actions()
                         if action.text().replace('&','')=='AI connection (MCP)…']
                assert len(actions)==1 and actions[0].isEnabled(), 'MCP menu entry is missing or disabled'
                actions[0].trigger()
                QtWidgets.QApplication.processEvents()
                from simplecad.gui.tools import mcp as mcp_ui
                panel=mcp_ui._dialog
                assert panel.isVisible(), 'MCP menu must open the connection panel'
                assert panel.edits.isChecked()
                panel.edits.setChecked(False); assert not server.api.allow_changes
                panel.edits.setChecked(True); assert server.api.allow_changes
                old_clipboard=QtWidgets.QApplication.clipboard().text()
                panel.copy_codex()
                assert 'codex mcp add simplecad --' in QtWidgets.QApplication.clipboard().text()
                assert connection['token'] not in QtWidgets.QApplication.clipboard().text()
                QtWidgets.QApplication.clipboard().setText(old_clipboard)
                for _ in range(3): QtWidgets.QApplication.processEvents(); Gui.updateGui()
                mcp_ui._dialog.grab().save(str(ROOT.parent.parent/'work/mcp-panel.png'))
                mcp_ui._dialog.close()
            assert server.running
            Gui.activateWorkbench('PartWorkbench'); assert server.running
            Gui.activateWorkbench('SimpleCADWorkbench'); assert server.running
            server.stop(); assert not connection_path.exists()
            call('list_documents','interrupted')
            process.stdin.close(); process.wait(timeout=5)
            assert process.returncode==0
            assert not process.stderr.read(), 'stdio server should have no stderr diagnostics'
            return {'tools':len(calls),'transport':'real stdio subprocess','result':'PASS'}
    finally:
        server.stop()
        if process and process.poll() is None: process.terminate(); process.wait(timeout=5)
        pool.shutdown(wait=False,cancel_futures=True)
        c.cancel(quiet=True)
        preferences.save(original_settings); c.seams.configure(original_settings.show_seams)
        for name in set(App.listDocuments())-original_docs: App.closeDocument(name)
