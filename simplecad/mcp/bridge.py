"""Opt-in localhost transport; native model access is queued onto Qt's thread."""
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import threading
import uuid

from ..gui.qt import QtCore, QtWidgets
from .api import ModelAPI
from .connection import MAX_MESSAGE, private_directory, runtime_directory


class Task:
    def __init__(self,payload):
        self.payload=payload
        self.lock=threading.Lock()
        self.done=threading.Event()
        self.state='queued'
        self.result=None
        self.bytes=0

    def claim(self):
        with self.lock:
            if self.state!='queued': return False
            self.state='running'
            return True

    def expire(self):
        with self.lock:
            if self.state=='queued': self.state='cancelled'
            return self.state


class HTTPServer(ThreadingHTTPServer):
    daemon_threads=True
    block_on_close=False
    def handle_error(self,request,client_address): pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*unused): pass  # Never write model data or authentication to logs.
    def setup(self):
        super().setup(); self.connection.settimeout(5)

    def reply(self,status,payload):
        data=json.dumps({'instance':self.server.bridge.instance,**payload},allow_nan=False).encode('utf-8')
        self.send_response(status); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data))); self.end_headers()
        try: self.wfile.write(data)
        except OSError: pass

    def authorized(self):
        bridge=self.server.bridge
        host='127.0.0.1:'+str(self.server.server_port)
        if (self.headers.get('Origin') is not None or self.headers.get('Host')!=host
                or not secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+bridge.token)):
            self.reply(403,{'error':'Unauthorized local connection.'}); return False
        return True

    def do_GET(self):
        if not self.authorized(): return
        if self.path!='/health': self.reply(404,{'error':'Unknown endpoint.'}); return
        self.reply(200,{'running':True})

    def do_POST(self):
        if not self.authorized(): return
        if self.path!='/call': self.reply(404,{'error':'Unknown endpoint.'}); return
        try:
            if self.headers.get('Transfer-Encoding') or self.headers.get_content_type()!='application/json': raise ValueError()
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=MAX_MESSAGE: raise ValueError()
            raw=self.rfile.read(length)
            if len(raw)!=length: raise ValueError()
            payload=json.loads(raw)
            if (not isinstance(payload,dict) or set(payload)!={'call_id','name','arguments'}
                    or not isinstance(payload['call_id'],str) or len(payload['call_id'])!=32
                    or not isinstance(payload['name'],str) or not isinstance(payload['arguments'],dict)):
                raise ValueError()
        except (ValueError,OSError):
            self.reply(400,{'error':'Invalid request.'}); return
        bridge=self.server.bridge
        # Duplicate transport IDs share their original result, never rerun edits.
        with bridge.lock:
            if not bridge.accepting or bridge.http is not self.server:
                self.reply(503,{'error':'This FreeCAD server is stopping.'}); return
            task=bridge.tasks.get(payload['call_id'])
            if task and task.payload!=payload:
                self.reply(409,{'error':'Call ID already used for different arguments.'}); return
            if task is None:
                task=Task(payload)
                try: bridge.queue.put_nowait(task)
                except queue.Full:
                    self.reply(429,{'error':'FreeCAD request queue is full. Try again after current work finishes.'}); return
                bridge.tasks[payload['call_id']]=task
                for key in list(bridge.tasks):
                    if len(bridge.tasks)<=256: break
                    if bridge.tasks[key].done.is_set(): del bridge.tasks[key]
        if not task.done.wait(bridge.wait_seconds):
            state=task.expire()
            if state=='done':
                self.reply(200,task.result); return
            self.reply(200,{'error': 'FreeCAD was busy; this queued request was cancelled.' if state=='cancelled'
                            else 'The operation is still running. It may complete; inspect the model before retrying.'})
            return
        self.reply(200,task.result)


class Bridge(QtCore.QObject):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.api=ModelAPI()
        self.http=None; self.path=None
        self.accepting=False
        self.timer=QtCore.QTimer(self); self.timer.setInterval(15); self.timer.timeout.connect(self.process)
        self.lock=threading.Lock(); self.queue=queue.Queue(maxsize=16); self.tasks=OrderedDict()
        self.thread=None
        self.wait_seconds=45

    @property
    def running(self): return self.http is not None

    def start(self,allow_changes=True,directory=None):
        if self.running:
            self.api.allow_changes=allow_changes; return self.path
        self.api=ModelAPI(allow_changes)
        folder=private_directory(directory or runtime_directory())
        self.token=secrets.token_urlsafe(32); self.instance=uuid.uuid4().hex
        self.queue=queue.Queue(maxsize=16); self.tasks=OrderedDict()
        http=HTTPServer(('127.0.0.1',0),Handler); http.bridge=self
        path=folder/('connection-%d-%s.json'%(os.getpid(),self.instance[:8]))
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                json.dump({'host':'127.0.0.1','port':http.server_port,'token':self.token,'instance':self.instance},stream)
            self.http=http; self.path=path; self.accepting=True
            self.thread=threading.Thread(target=http.serve_forever,kwargs={'poll_interval':0.05},daemon=True)
            self.thread.start(); self.timer.start()
        except Exception:
            http.server_close(); path.unlink(missing_ok=True); self.http=None; self.path=None; self.accepting=False
            raise
        return path

    def process(self):
        try: task=self.queue.get_nowait()
        except queue.Empty: return
        if not task.claim():
            task.result={'error':'Request cancelled before execution.'}; task.done.set(); return
        try:
            result=self.api.call(task.payload['name'],task.payload['arguments'])
            # Validate serialization while still inside this error boundary.
            task.bytes=len(json.dumps(result,allow_nan=False))
            task.result={'result':result}
        except Exception as error:
            task.result={'error':str(error)}
        finally:
            with task.lock: task.state='done'
            task.done.set()
            # Screenshots can be large; bound cached replies as well as count.
            with self.lock:
                size=sum(item.bytes for item in self.tasks.values())
                for key,item in list(self.tasks.items()):
                    if size<=24*1024*1024: break
                    if item.done.is_set():
                        size-=item.bytes; del self.tasks[key]

    def stop(self):
        self.timer.stop()
        with self.lock:
            self.accepting=False
            for task in self.tasks.values():
                if task.expire()=='cancelled':
                    task.result={'error':'The FreeCAD server was stopped before execution.'}; task.done.set()
        if self.http:
            self.http.shutdown(); self.http.server_close(); self.http=None
        if self.thread: self.thread.join(timeout=1); self.thread=None
        if self.path: self.path.unlink(missing_ok=True); self.path=None


_instance=None

def instance():
    global _instance
    if _instance is None:
        _instance=Bridge(QtWidgets.QApplication.instance())
        QtWidgets.QApplication.instance().aboutToQuit.connect(_instance.stop)
    return _instance
