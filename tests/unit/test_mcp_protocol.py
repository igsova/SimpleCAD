"""MCP lifecycle, schema boundaries and local connection security without FreeCAD."""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock
from simplecad.mcp.catalog import BY_NAME, TOOLS, validate
from simplecad.mcp.connection import read_connection, Client
from simplecad.mcp.protocol import Protocol, serve


class MCPProtocolTests(unittest.TestCase):
    def setUp(self):
        self.call=Mock(return_value={'value':1})
        self.protocol=Protocol(self.call)
        self.serial=0

    def request(self,method,params=None):
        self.serial+=1
        return self.protocol.handle({'jsonrpc':'2.0','id':self.serial,'method':method,'params':params or {}})

    def initialize(self,version='2025-11-25'):
        reply=self.request('initialize',{'protocolVersion':version,'capabilities':{},'clientInfo':{'name':'test','version':'1'}})
        self.protocol.handle({'jsonrpc':'2.0','method':'notifications/initialized'})
        return reply

    def test_lifecycle_and_versions(self):
        self.assertIn('error',self.request('tools/list'))
        self.assertEqual(self.request('ping')['result'],{})
        self.assertEqual(self.initialize('2025-06-18')['result']['protocolVersion'],'2025-06-18')
        self.assertIn('error',self.initialize())
        self.assertEqual(len(self.request('tools/list')['result']['tools']),76)
        self.assertEqual(self.request('resources/list')['error']['code'],-32601)
        self.call.assert_not_called()

    def test_unknown_version_negotiates_latest(self):
        self.assertEqual(self.initialize('unknown')['result']['protocolVersion'],'2025-11-25')

    def test_surface_line_face_is_optional_and_validated(self):
        args=dict(document='Doc',expected_revision='rev',start=[1,2,3],end=[4,5,6],
                  support='Part',surface_face='Face1')
        schema=BY_NAME['simplecad_create_line']['inputSchema']
        validate(args,schema)
        validate({k:v for k,v in args.items() if k!='surface_face'},schema)
        for name in ('Face0','Edge1','Face1;import os'):
            with self.assertRaises(ValueError):
                validate(dict(args,surface_face=name),schema)

    def test_schema_rejects_unsafe_or_stale_reference_inputs(self):
        self.initialize()
        for params in ({'name':'execute_python','arguments':{'code':'pass'}},
                       {'name':'simplecad_delete','arguments':{'document':'Doc','targets':[]}},
                       {'name':'simplecad_create_circle','arguments':{'document':'Doc','expected_revision':'x','origin':[0,0,0],'radius':True}},
                       {'name':'simplecad_get_settings','arguments':{'extra':1}},
                       {'name':'simplecad_push_pull','arguments':{'document':'Doc','expected_revision':'x','object':'A','face':'Face0','distance':1}}):
            self.assertEqual(self.request('tools/call',params)['error']['code'],-32602)
        self.call.assert_not_called()

    def test_all_surface_drawing_options_validate_face_names(self):
        for name,args in (
                ('rectangle',dict(origin=[0,0,0],width=3,height=4)),
                ('circle',dict(origin=[0,0,0],radius=2)),
                ('polygon',dict(origin=[0,0,0],radius=2,sides=6)),
                ('arc',dict(origin=[0,0,0],start=[1,0,0],sweep=90)),
                ('2_point_arc',dict(start=[0,0,0],end=[2,0,0],bulge=1))):
            schema = BY_NAME['simplecad_create_'+name]['inputSchema']
            values = dict(args,document='Doc',expected_revision='revision',support='Body',surface_face='Face3')
            validate(values,schema)
            validate({k:v for k,v in values.items() if k!='surface_face'},schema)
            for face in ('Face0','Face-1','Edge1'):
                with self.assertRaises(ValueError):
                    validate(dict(values,surface_face=face),schema)

    def test_error_results_and_structured_success(self):
        self.initialize()
        reply=self.request('tools/call',{'name':'simplecad_get_settings'})['result']
        self.assertEqual(reply['structuredContent'],{'value':1})
        self.assertEqual(json.loads(reply['content'][0]['text']),{'value':1})
        self.call.side_effect=ValueError('Model changed')
        reply=self.request('tools/call',{'name':'simplecad_get_settings'})['result']
        self.assertTrue(reply['isError']); self.assertIn('Model changed',reply['content'][0]['text'])

    def test_image_content_and_notifications(self):
        self.initialize()
        self.call.return_value={'content':[{'type':'image','mimeType':'image/png','data':'aA=='}]}
        self.assertEqual(self.request('tools/call',{'name':'simplecad_capture_view','arguments':{'document':'D'}})['result'],self.call.return_value)
        self.assertIsNone(self.protocol.handle({'jsonrpc':'2.0','method':'tools/call','params':{'name':'simplecad_delete'}}))
        self.assertEqual(self.call.call_count,1)

    def test_stream_parse_errors_and_stdout_framing(self):
        output=io.StringIO()
        serve(io.StringIO('not json\n[]\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n'),output,self.call)
        messages=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([m.get('error',{}).get('code') for m in messages],[-32700,-32600,None])
        self.call.assert_not_called()

    def test_all_schemas_and_annotations(self):
        self.assertEqual(len(BY_NAME),len(TOOLS))
        self.assertTrue(BY_NAME['simplecad_inspect_object']['annotations']['readOnlyHint'])
        self.assertFalse(BY_NAME['simplecad_delete']['annotations']['readOnlyHint'])
        self.assertTrue(BY_NAME['simplecad_delete']['annotations']['destructiveHint'])
        for value in (float('nan'),float('inf'),True):
            with self.assertRaises(ValueError): validate(value,{'type':'number'})
        self.assertFalse(any('code' in t['inputSchema']['properties'] for t in TOOLS))

    def test_mesh_stretch_protocol(self):
        self.initialize()
        common={'document':'Doc','expected_revision':'current','object':'Mesh'}
        for extra in ({'axis':'LocalZ','distance':10,'lower':-5,'upper':5},
                      {'axis':'Main','delta':[0,2,0],'reverse':True},
                      {'axis':'Z','rotation':[15,-30,45],'distance':5}):
            reply=self.request('tools/call',{'name':'simplecad_stretch_mesh','arguments':{**common,**extra}})
            self.assertNotIn('error',reply)
        for extra in ({'distance':True},{'axis':'garbage','distance':2},{'delta':[1,2]},{'lower':float('nan')},
                      {'rotation':[0,181,0]},{'rotation':[0,0]},{'rotation':[False,0,0]}):
            reply=self.request('tools/call',{'name':'simplecad_stretch_mesh','arguments':{**common,**extra}})
            self.assertEqual(reply['error']['code'],-32602)
        for name in ('mesh_axis','mesh_stretch_status'):
            self.assertTrue(BY_NAME['simplecad_'+name]['annotations']['readOnlyHint'])
        for name in ('stretch_mesh','finish_mesh_stretch','cancel_mesh_stretch'):
            self.assertIn('expected_revision',BY_NAME['simplecad_'+name]['inputSchema']['required'])

    def test_mesh_region_protocol(self):
        self.initialize()
        common={'document':'Doc','expected_revision':'current','object':'Mesh'}
        for extra in ({'mode':'Move','seed_triangle':3,'delta':[0,0,2]},
                      {'mode':'Rotate','triangles':[3,4],'axis':[0,0,1],'angle':30,'pivot':[1,2,3],'rings':4},
                      {'mode':'Extrude','seed_triangle':1,'selection':'Smooth','crease':10,'grow':2,'distance':5}):
            reply=self.request('tools/call',{'name':'simplecad_edit_mesh_region','arguments':{**common,**extra}})
            self.assertNotIn('error',reply)
        for extra in ({'triangles':[True]},{'seed_triangle':0},{'rings':31},{'angle':float('nan')},
                      {'triangles':[]},{'selection':'guess'},{'delta':[1,2]}):
            reply=self.request('tools/call',{'name':'simplecad_edit_mesh_region','arguments':{**common,'mode':'Move',**extra}})
            self.assertEqual(reply['error']['code'],-32602)
        for name in ('inspect_mesh_triangles','inspect_mesh_region','mesh_region_status'):
            self.assertTrue(BY_NAME['simplecad_'+name]['annotations']['readOnlyHint'])
        for name in ('edit_mesh_region','finish_mesh_region','cancel_mesh_region'):
            self.assertIn('expected_revision',BY_NAME['simplecad_'+name]['inputSchema']['required'])

    def test_surface_tool_protocol(self):
        self.initialize()
        common={'document':'Doc','expected_revision':'current','object':'Part'}
        valid=(('heal_faces',{'faces':['Face3','Face4']}),('remove_rounds',{'max_radius':2,'convexity':'concave'}),
               ('draw_on_surface',{'faces':['Face1'],'shape':'text','text':'SimpleCAD','size':4,'mode':'emboss','depth':.5,
                                   'point':[1,2,3],'shift':[0,2],'angle':15}),
               ('fill_holes',{'edges':['Edge2'],'smooth':False}),('unwrap_face',{'face':'Face2'}),
               ('draw_on_surface',{'faces':['Face1'],'shape':'circle','diameter':4,'wrap':True}),
               ('offset_faces',{'faces':['Face1','Face2'],'distance':-1.5}),('shell',{'thickness':1,'faces':['Face6']}),
               ('shell',{'thickness':2,'side':'both'}),
               ('draft_faces',{'faces':['Face1'],'angle':3,'axis':'X','hinge':'top','narrower':'bottom'}))
        for name,extra in valid:
            reply=self.request('tools/call',{'name':'simplecad_'+name,'arguments':{**common,**extra}})
            self.assertNotIn('error',reply,name)
        reply=self.request('tools/call',{'name':'simplecad_pattern','arguments':{
            'document':'Doc','expected_revision':'current','objects':['Part'],'kind':'path','count':5,
            'path':{'object':'Rail','elements':['Edge1']},'align':False}})
        self.assertNotIn('error',reply)
        invalid=(('heal_faces',{'faces':[]}),('heal_faces',{'faces':['Edge1']}),('remove_rounds',{'max_radius':0}),
                 ('remove_rounds',{'max_radius':1,'convexity':'both'}),('draw_on_surface',{'faces':['Face1'],'shape':'star'}),
                 ('draw_on_surface',{'faces':['Face1'],'shape':'polygon','sides':2}),('fill_holes',{'edges':['Face1']}),
                 ('unwrap_face',{'face':'Edge1'}),('offset_faces',{'faces':['Face1']}),('offset_faces',{'faces':[],'distance':1}),
                 ('shell',{'thickness':0}),('shell',{'thickness':1,'side':'inside'}),('draft_faces',{'faces':['Face1'],'angle':90}),
                 ('draft_faces',{'faces':['Face1'],'angle':3,'axis':'W'}),('draw_on_surface',{'faces':['Face1'],'shape':'circle','wrap':'yes'}))
        for name,extra in invalid:
            reply=self.request('tools/call',{'name':'simplecad_'+name,'arguments':{**common,**extra}})
            self.assertEqual(reply['error']['code'],-32602,(name,extra))
        self.assertTrue(BY_NAME['simplecad_find_rounds']['annotations']['readOnlyHint'])
        for name in ('heal_faces','remove_rounds'):
            self.assertTrue(BY_NAME['simplecad_'+name]['annotations']['destructiveHint'])
        for name in ('heal_faces','remove_rounds','draw_on_surface','fill_holes','unwrap_face','pattern','offset_faces',
                     'shell','draft_faces'):
            self.assertIn('expected_revision',BY_NAME['simplecad_'+name]['inputSchema']['required'])

    def test_connection_file_is_private_and_loopback_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'connection.json'
            value={'host':'127.0.0.1','port':12345,'token':'a'*40,'instance':'test'}
            path.write_text(json.dumps(value)); path.chmod(0o600)
            self.assertEqual(read_connection(path),value)
            if os.name=='posix':
                path.chmod(0o644)
                with self.assertRaises(ValueError): read_connection(path)
                path.chmod(0o600)
            value['host']='example.com'; path.write_text(json.dumps(value))
            with self.assertRaises(ValueError): read_connection(path)
            with self.assertRaisesRegex(ValueError,'Open FreeCAD'): Client(directory=Path(folder)/'missing').connect()

    def test_cancel_queued_call_while_ping_remains_responsive(self):
        read_fd,write_fd=os.pipe()
        input_stream=os.fdopen(read_fd,'r'); writer=os.fdopen(write_fd,'w')
        output=io.StringIO(); started=threading.Event(); release=threading.Event(); executed=[]
        def call(name,args):
            executed.append(name); started.set(); release.wait(2); return {'ok':True}
        worker=threading.Thread(target=serve,args=(input_stream,output,call))
        worker.start()
        def send(message): writer.write(json.dumps(message)+'\n'); writer.flush()
        try:
            send({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'t','version':'1'}}})
            send({'jsonrpc':'2.0','method':'notifications/initialized'})
            for identifier in (2,3): send({'jsonrpc':'2.0','id':identifier,'method':'tools/call','params':{'name':'simplecad_get_settings'}})
            self.assertTrue(started.wait(1))
            send({'jsonrpc':'2.0','method':'notifications/cancelled','params':{'requestId':3}})
            send({'jsonrpc':'2.0','id':4,'method':'ping'})
            deadline=time.monotonic()+1
            while '"id": 4' not in output.getvalue() and time.monotonic()<deadline: time.sleep(.005)
            self.assertIn('"id": 4',output.getvalue())
            release.set(); writer.close(); worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(executed,['simplecad_get_settings'])
            self.assertNotIn('"id": 3',output.getvalue())
        finally:
            release.set()
            if not writer.closed: writer.close()
            worker.join(2); input_stream.close()


if __name__=='__main__': unittest.main()
