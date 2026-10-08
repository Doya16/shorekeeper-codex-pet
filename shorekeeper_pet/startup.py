"""Optional per-user Windows startup watcher; does not modify Codex."""
import ctypes,json,os,pathlib,re,subprocess,sys,tempfile,time
import xml.etree.ElementTree as ET
from datetime import datetime,timedelta
from ctypes import wintypes
from .paths import ROOT

RUN_KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME='ShorekeeperCodexPet'
WATCHER_REVISION='--startup-watcher-v2'
TASK_NS='http://schemas.microsoft.com/windows/2004/02/mit/task'

def launch_args(root=ROOT,watch=False):
    root=pathlib.Path(root)
    if getattr(sys,'frozen',False): args=[str(pathlib.Path(sys.executable).resolve())]
    else:
        python=pathlib.Path(sys.executable)
        hidden=python.with_name('pythonw.exe')
        args=[str(hidden if hidden.exists() else python),str(root/'tools/run_pet.py')]
    return args+(['--watch-codex',WATCHER_REVISION] if watch else [])

def registered_command():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY) as key:
            return winreg.QueryValueEx(key,RUN_NAME)[0]
    except FileNotFoundError:return ''

def _control_path():
    # Shared by launchers and Task Scheduler, independent of HKCU registry views.
    return pathlib.Path.home()/'.shorekeeper-codex-pet'/'startup.json'

def _write_control(enabled,root):
    path=_control_path();path.parent.mkdir(parents=True,exist_ok=True)
    data=dict(enabled=bool(enabled),command=subprocess.list2cmdline(launch_args(root,True)))
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=path.parent,delete=False) as stream:
        json.dump(data,stream,ensure_ascii=False);temp=pathlib.Path(stream.name)
    try:temp.replace(path)
    finally:temp.unlink(missing_ok=True)

def _watcher_enabled(root):
    expected=subprocess.list2cmdline(launch_args(root,True))
    try:
        data=json.loads(_control_path().read_text('utf8'))
        return data.get('enabled') is True and data.get('command')==expected
    except FileNotFoundError:
        # Upgrade an existing Run entry when the new control file has not been created yet.
        return registered_command() in (expected,expected.removesuffix(' '+WATCHER_REVISION))
    except (OSError,ValueError):return False

def _write_registration(enabled,root):
    import winreg
    expected=subprocess.list2cmdline(launch_args(root,True))
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,RUN_KEY) as key:
        if enabled:winreg.SetValueEx(key,RUN_NAME,0,winreg.REG_SZ,expected)
        elif registered_command() in (expected,expected.removesuffix(' '+WATCHER_REVISION)):
            try:winreg.DeleteValue(key,RUN_NAME)
            except FileNotFoundError:pass

def _log(root,event,**details):
    """Small local diagnostics, without conversation content or credentials."""
    try:
        path=pathlib.Path(root)/'startup-watch.log'
        if path.exists() and path.stat().st_size>131072:
            path.replace(path.with_name('startup-watch.previous.log'))
        with path.open('a',encoding='utf8') as stream:
            stream.write(json.dumps(dict(time=time.strftime('%Y-%m-%d %H:%M:%S'),event=event,**details),ensure_ascii=False)+'\n')
    except OSError:pass

def _task_command(*args):
    return subprocess.run(['schtasks.exe',*args],capture_output=True,timeout=10,
                          creationflags=subprocess.CREATE_NO_WINDOW)

def _user_sid():
    result=subprocess.run(['whoami.exe','/user','/fo','csv','/nh'],capture_output=True,
                          check=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
    match=re.search(rb'S-1-\d+(?:-\d+)+',result.stdout)
    if not match:raise OSError('无法读取当前 Windows 用户标识。')
    return match.group().decode('ascii')

def _account_name():
    api=ctypes.WinDLL('secur32',use_last_error=True).GetUserNameExW
    api.argtypes=[wintypes.ULONG,wintypes.LPWSTR,ctypes.POINTER(wintypes.ULONG)]
    buffer=ctypes.create_unicode_buffer(1024);size=wintypes.ULONG(len(buffer))
    return buffer.value if api(2,buffer,ctypes.byref(size)) else ''

def _task_name(sid):return RUN_NAME+'-'+sid

def _task_xml(root,args,sid):
    task=ET.Element('Task',version='1.2',xmlns=TASK_NS)
    registration=ET.SubElement(task,'RegistrationInfo')
    ET.SubElement(registration,'Description').text='Shorekeeper Codex startup watcher v2'
    trigger=ET.SubElement(ET.SubElement(task,'Triggers'),'LogonTrigger')
    ET.SubElement(trigger,'Enabled').text='true';ET.SubElement(trigger,'UserId').text=sid
    recovery=ET.SubElement(task.find('Triggers'),'TimeTrigger')
    repetition=ET.SubElement(recovery,'Repetition')
    ET.SubElement(repetition,'Interval').text='PT1M'
    ET.SubElement(repetition,'StopAtDurationEnd').text='false'
    ET.SubElement(recovery,'StartBoundary').text=(datetime.now().replace(second=0,microsecond=0)+timedelta(minutes=1)).isoformat()
    ET.SubElement(recovery,'Enabled').text='true'
    principal=ET.SubElement(ET.SubElement(task,'Principals'),'Principal',id='Author')
    for key,value in [('UserId',sid),('LogonType','InteractiveToken'),('RunLevel','LeastPrivilege')]:
        ET.SubElement(principal,key).text=value
    # During a move/update the new watcher can wait for the old mutex owner to exit.
    # The mutex below still permits only one active polling loop.
    settings=ET.SubElement(task,'Settings')
    for key,value in [('MultipleInstancesPolicy','Parallel'),('DisallowStartIfOnBatteries','false'),
                      ('StopIfGoingOnBatteries','false'),('StartWhenAvailable','true'),
                      ('Enabled','true'),('ExecutionTimeLimit','PT0S')]:
        ET.SubElement(settings,key).text=value
    restart=ET.SubElement(settings,'RestartOnFailure')
    ET.SubElement(restart,'Interval').text='PT1M';ET.SubElement(restart,'Count').text='3'
    action=ET.SubElement(ET.SubElement(task,'Actions',Context='Author'),'Exec')
    for key,value in [('Command',args[0]),('Arguments',subprocess.list2cmdline(args[1:])),('WorkingDirectory',str(root))]:
        ET.SubElement(action,key).text=value
    return ET.tostring(task,encoding='utf-16',xml_declaration=True)

def _task_matches(xml,expected):
    try:
        if isinstance(xml,bytes):
            if xml.startswith((b'\xff\xfe',b'\xfe\xff')) or xml[:2]==b'<\x00':xml=xml.decode('utf-16')
            else:
                try:xml=xml.decode('utf8')
                except UnicodeDecodeError:xml=xml.decode('mbcs')
        actual=ET.fromstring(xml);desired=ET.fromstring(expected)
        ns={'t':TASK_NS}
        paths=('RegistrationInfo/Description','Triggers/LogonTrigger/UserId','Triggers/LogonTrigger/Enabled',
               'Triggers/TimeTrigger/Enabled','Triggers/TimeTrigger/Repetition/Interval','Triggers/TimeTrigger/Repetition/StopAtDurationEnd',
               'Principals/Principal/UserId','Principals/Principal/LogonType','Principals/Principal/RunLevel',
               'Settings/MultipleInstancesPolicy','Settings/DisallowStartIfOnBatteries',
               'Settings/StopIfGoingOnBatteries','Settings/StartWhenAvailable','Settings/Enabled',
               'Settings/ExecutionTimeLimit','Settings/RestartOnFailure/Interval','Settings/RestartOnFailure/Count',
               'Actions/Exec/Command','Actions/Exec/Arguments','Actions/Exec/WorkingDirectory')
        defaults={'Triggers/LogonTrigger/Enabled':'true','Settings/Enabled':'true',
                  'Principals/Principal/RunLevel':'LeastPrivilege','Triggers/TimeTrigger/Enabled':'true',
                  'Triggers/TimeTrigger/Repetition/StopAtDurationEnd':'false'}
        if not actual.findtext('t:Triggers/t:TimeTrigger/t:StartBoundary',namespaces=ns):return False
        for path in paths:
            xpath='/'.join('t:'+part for part in path.split('/'))
            value=actual.findtext(xpath,default=defaults.get(path),namespaces=ns)
            wanted=desired.findtext(xpath,namespaces=ns)
            if path=='Triggers/LogonTrigger/UserId':
                if (value or '').casefold()!=wanted.casefold() and (value or '').casefold()!=_account_name().casefold():return False
            elif value!=wanted:return False
        return True
    except (ET.ParseError,ValueError):return False

def _start_scheduled(root):
    """The scheduler starts the watcher outside the launching app's process tree."""
    sid=_user_sid();name=_task_name(sid);expected=_task_xml(root,launch_args(root,True)+['--scheduled-watcher'],sid)
    existing=_task_command('/Query','/TN',name,'/XML')
    if existing.returncode or not _task_matches(existing.stdout,expected):
        with tempfile.TemporaryDirectory(prefix='shorekeeper-startup-') as folder:
            path=pathlib.Path(folder)/'watcher.xml';path.write_bytes(expected)
            result=_task_command('/Create','/TN',name,'/XML',str(path),'/F')
            if result.returncode:raise OSError('Windows 启动任务注册失败：'+str(result.returncode))
    result=_task_command('/Run','/TN',name)
    if result.returncode:raise OSError('Windows 启动任务运行失败：'+str(result.returncode))
    _log(root,'scheduler-started')
    return True

def _spawn_watcher(root):
    # Compatibility fallback when Task Scheduler is unavailable on this PC.
    kwargs=dict(cwd=root,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        return subprocess.Popen(launch_args(root,True)+['--direct-watcher'],creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_BREAKAWAY_FROM_JOB,**kwargs)
    except OSError as exc:
        if getattr(exc,'winerror',None)!=5:raise
        _log(root,'job-breakaway-unavailable',error=str(exc))
        return subprocess.Popen(launch_args(root,True)+['--direct-watcher'],creationflags=subprocess.CREATE_NO_WINDOW,**kwargs)

def configure(enabled,root=ROOT):
    if sys.platform!='win32': raise OSError('随 Codex 启动目前仅支持 Windows。')
    root=pathlib.Path(root).resolve()
    _write_control(enabled,root)
    _write_registration(enabled,root)
    if enabled:
        try:return _start_scheduled(root)
        except (OSError,subprocess.SubprocessError) as exc:
            _log(root,'scheduler-fallback',error=str(exc))
            return _spawn_watcher(root)
    else:
        try:_task_command('/Delete','/TN',_task_name(_user_sid()),'/F')
        except (OSError,subprocess.SubprocessError) as exc:_log(root,'scheduler-remove-error',error=str(exc))
        _log(root,'disabled')

def is_codex_desktop(path):
    path=str(path).replace('/','\\').lower()
    name=path.rsplit('\\',1)[-1]
    if name not in ('chatgpt.exe','codex.exe'):return False
    if '\\openai.codex_' in path:return True
    # Non-Store desktop installations; never match the CLI's bin directory.
    return '\\codex\\app\\' in path or path.endswith('\\codex\\codex.exe') or path.endswith('\\codex\\chatgpt.exe')

def codex_processes():
    if sys.platform!='win32':return set()
    class Entry(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('usage',wintypes.DWORD),('pid',wintypes.DWORD),
                  ('heap',ctypes.c_size_t),('module',wintypes.DWORD),('threads',wintypes.DWORD),
                  ('parent',wintypes.DWORD),('priority',wintypes.LONG),('flags',wintypes.DWORD),('exe',wintypes.WCHAR*260)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD];kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    kernel.Process32FirstW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)]
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    snapshot=kernel.CreateToolhelp32Snapshot(2,0)
    if snapshot==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    found={}
    try:
        entry=Entry();entry.size=ctypes.sizeof(entry);ok=kernel.Process32FirstW(snapshot,ctypes.byref(entry))
        while ok:
            if entry.exe.lower() in ('codex.exe','chatgpt.exe'):
                process=kernel.OpenProcess(0x1000,False,entry.pid)
                if process:
                    try:
                        path=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(path))
                        if kernel.QueryFullProcessImageNameW(process,0,path,ctypes.byref(size)) and is_codex_desktop(path.value):found[entry.pid]=entry.parent
                    finally:kernel.CloseHandle(process)
            ok=kernel.Process32NextW(snapshot,ctypes.byref(entry))
    finally:kernel.CloseHandle(snapshot)
    return desktop_roots(found)

def desktop_roots(parents):
    """Ignore renderer/helper PIDs so a leftover helper cannot hide a restart."""
    return {pid for pid,parent in parents.items() if parent not in parents}

class LaunchEdges:
    """One launch per new desktop root, even if an old helper survives."""
    def __init__(self):self.previous=set()
    def retry(self):self.previous=set()
    def update(self,current):
        current=set(current);launch=bool(current-self.previous)
        self.previous=current;return launch

def watch(root=ROOT):
    if not _watcher_enabled(root):
        _write_registration(False,root)
        return 0
    # The legacy Run entry delegates to the same task as the logon trigger.
    if not any(arg in sys.argv for arg in ('--scheduled-watcher','--direct-watcher')):
        try:
            _start_scheduled(root)
            return 0
        except (OSError,subprocess.SubprocessError) as exc:
            _log(root,'scheduler-bootstrap-fallback',error=str(exc))
    _write_registration(True,root)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR];kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.ReleaseMutex.argtypes=[wintypes.HANDLE];kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    mutex=kernel.CreateMutexW(None,False,r'Local\ShorekeeperCodexPetWatcher')
    if not mutex:raise ctypes.WinError(ctypes.get_last_error())
    owned=False
    try:
        owned=kernel.WaitForSingleObject(mutex,6000) in (0,0x80)
        if not owned:return 0
        expected=subprocess.list2cmdline(launch_args(root,True));edges=LaunchEdges();retry_at=0
        _log(root,'watcher-ready',pid=os.getpid())
        while _watcher_enabled(root):
            try:
                if time.monotonic()>=retry_at and edges.update(codex_processes()):
                    child=subprocess.Popen(launch_args(root),cwd=root,creationflags=subprocess.CREATE_NO_WINDOW,
                                           stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    _log(root,'pet-launched',pid=child.pid)
            except OSError as exc:
                edges.retry();retry_at=time.monotonic()+10
                _log(root,'launch-retry',error=str(exc))
            time.sleep(2)
        _write_registration(False,root)
        _log(root,'watcher-stopped',reason='disabled-or-moved')
        return 0
    finally:
        if owned:kernel.ReleaseMutex(mutex)
        kernel.CloseHandle(mutex)
