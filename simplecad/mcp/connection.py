"""Private localhost bridge discovery and client. Standard library only."""
import http.client
import json
import os
from pathlib import Path
import stat
import uuid

MAX_MESSAGE = 1024 * 1024
MAX_RESPONSE = 24 * 1024 * 1024


def runtime_directory():
    return Path.home()/'.simplecad'/'mcp'


def private_directory(path):
    path=Path(path)
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    info=path.lstat()
    if not stat.S_ISDIR(info.st_mode) or (hasattr(os,'getuid') and info.st_uid != os.getuid()):
        raise ValueError('The MCP connection directory must be owned by this user and must not be a symlink.')
    path.chmod(0o700)
    return path


def read_connection(path):
    flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)
    fd=os.open(path,flags)
    with os.fdopen(fd,'r',encoding='utf-8') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>4096:
            raise ValueError('Invalid MCP connection file.')
        if os.name=='posix' and (info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077):
            raise ValueError('MCP connection files must be private to their owner (permissions 600).')
        data=json.load(stream)
    if (not isinstance(data,dict) or data.get('host')!='127.0.0.1' or type(data.get('port')) is not int or not 1<=data['port']<=65535
            or not isinstance(data.get('token'),str) or len(data['token'])<32
            or not isinstance(data.get('instance'),str)):
        raise ValueError('Invalid MCP connection details.')
    return data


def exchange(connection, payload=None, timeout=50):
    client=http.client.HTTPConnection('127.0.0.1',connection['port'],timeout=timeout)
    try:
        headers={'Authorization':'Bearer '+connection['token']}
        body=None if payload is None else json.dumps(payload,allow_nan=False).encode('utf-8')
        if body is not None: headers['Content-Type']='application/json'
        client.request('GET' if body is None else 'POST','/health' if body is None else '/call',body,headers)
        response=client.getresponse()
        raw=response.read(MAX_RESPONSE+1)
        if len(raw)>MAX_RESPONSE: raise ValueError('Bridge response is too large. Request a smaller page or image.')
        if response.status!=200: raise ValueError('FreeCAD bridge rejected the request (HTTP %d).'%response.status)
        value=json.loads(raw)
        if value.get('instance')!=connection['instance']: raise ValueError('The FreeCAD connection changed. Restart the MCP client.')
        return value
    finally:
        client.close()


class Client:
    def __init__(self, path=None, directory=None):
        self.path=Path(path) if path else None
        self.directory=Path(directory) if directory else runtime_directory()
        self.connection=None

    def connect(self):
        if self.connection is not None: return
        paths=[self.path] if self.path else sorted(self.directory.glob('connection-*.json'))
        found=[]
        for path in paths:
            try:
                data=read_connection(path)
                exchange(data,timeout=0.5)
                found.append(data)
            except (OSError,ValueError,http.client.HTTPException):
                if self.path: raise ValueError('The specified FreeCAD connection is unavailable. Start AI connection in SimpleCAD again.')
        if not found: raise ValueError('Open FreeCAD, choose SimpleCAD → AI connection (MCP)… and click Start server.')
        if len(found)>1: raise ValueError('Several FreeCAD servers are running. Use --connection with the file shown in the intended FreeCAD AI connection panel.')
        self.connection=found[0]

    def call(self,name,arguments):
        self.connect()
        try:
            value=exchange(self.connection,{'call_id':uuid.uuid4().hex,'name':name,'arguments':arguments})
        except (OSError,http.client.HTTPException) as error:
            raise ValueError('The FreeCAD connection was interrupted. An edit may have completed; inspect the model before retrying. Restart the MCP client if FreeCAD was restarted.') from error
        if 'error' in value: raise ValueError(value['error'])
        return value['result']
