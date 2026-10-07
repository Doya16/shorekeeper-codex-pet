"""Read-only Codex companion bridge. Never requests model inference or reads auth.json."""
from __future__ import annotations
import json, os, pathlib, queue, re, shutil, sqlite3, subprocess, threading, time
from datetime import datetime

from .paths import ROOT,CODEX_HOME

def timestamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    except (ValueError, AttributeError):
        return 0.0

def windows_from_limits(result):
    buckets = result.get('rateLimitsByLimitId') or {}
    if not buckets and result.get('rateLimits'):
        item = result['rateLimits']
        buckets = {item.get('limitId') or item.get('limit_id') or 'codex': item}
    rows=[]
    for key, bucket in buckets.items():
        for kind in ('primary','secondary'):
            w=bucket.get(kind)
            if not w: continue
            used=w.get('usedPercent', w.get('used_percent'))
            if not isinstance(used,(int,float)): continue
            minutes=w.get('windowDurationMins', w.get('window_minutes'))
            duration = '每周' if minutes==10080 else (f'{minutes//60} 小时' if minutes and minutes%60==0 else f'{minutes} 分钟' if minutes else '额度窗口')
            rows.append(dict(bucket=key,name=bucket.get('limitName') or bucket.get('limit_name') or key,kind=kind,label=duration,remaining=max(0,min(100,100-used)),resets_at=w.get('resetsAt',w.get('resets_at'))))
    return rows

def discover_codex(explicit=''):
    if explicit: return str(pathlib.Path(explicit)) if pathlib.Path(explicit).is_file() else None
    exe=shutil.which('codex')
    if exe: return exe
    base=pathlib.Path(os.environ.get('LOCALAPPDATA',''))/'OpenAI/Codex/bin'
    candidates=list(base.glob('*/codex.exe'))
    return str(max(candidates,key=lambda p:p.stat().st_mtime)) if candidates else None

def tool_phase(payload):
    """Classify operation identifiers locally; never display arguments or output."""
    name=payload.get('name','').rsplit('.',1)[-1]
    code=payload.get('input','') if name=='exec' else ''
    if not isinstance(code,str): code=''
    names=' '.join(re.findall(r'tools\.([A-Za-z0-9_]+)\s*\(',code))+' '+name
    if 'request_user_input' in names: return 'waiting'
    if re.search(r'apply_patch|write_file|edit_file',names): return 'writing'
    if re.search(r'web__|search|read_|view_|list_|get_',names): return 'reading'
    # Shell reads commonly run through exec_command rather than a read_file tool.
    commands=[]
    if name=='exec_command':
        try: commands=[json.loads(payload.get('arguments','{}')).get('cmd','')]
        except (ValueError,TypeError,AttributeError): pass
    elif 'exec_command' in names:
        commands=re.findall(r'''["']?cmd["']?\s*:\s*["']([^"'\r\n]*)''',code)
    if commands and all(isinstance(cmd,str) and re.match(r'^\s*(?:rg|cat|head|tail|ls|Get-Content|Get-ChildItem|Select-String|Test-Path)\b',cmd,re.I) for cmd in commands): return 'reading'
    return 'working'

class RateClient:
    """One authenticated app-server process; only initialize and read limits are sent."""
    def __init__(self,executable='',codex_home=''):
        self.executable=executable; self.codex_home=codex_home
        self.process=None
        self.inbox=queue.Queue()
        self.lock=threading.Lock()
        self.sequence=1

    def _send(self, obj):
        self.process.stdin.write(json.dumps(obj)+'\n')
        self.process.stdin.flush()

    def _response(self, ident, timeout=20):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try: obj=self.inbox.get(timeout=min(1,end-time.monotonic()))
            except queue.Empty: continue
            if obj.get('id')!=ident: continue
            if 'error' in obj: raise RuntimeError('Codex 额度接口暂不可用')
            return obj.get('result',{})
        raise TimeoutError('Codex 额度查询超时')

    def _start(self):
        exe=discover_codex(self.executable)
        if not exe: raise FileNotFoundError('没有找到 Codex 程序')
        self.inbox=queue.Queue()
        env=os.environ.copy()
        if self.codex_home: env['CODEX_HOME']=self.codex_home
        self.process=subprocess.Popen([exe,'app-server'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def reader(proc, inbox):
            try:
                for line in proc.stdout:
                    try: inbox.put(json.loads(line))
                    except json.JSONDecodeError: pass
            except (OSError,ValueError): pass
        threading.Thread(target=reader,args=(self.process,self.inbox),daemon=True).start()
        self._send({'id':0,'method':'initialize','params':{'clientInfo':{'name':'shorekeeper_companion','title':'Shorekeeper companion','version':'0.1.0'}}})
        self._response(0)
        self._send({'method':'initialized','params':{}})

    def read(self):
        with self.lock:
            try:
                if not self.process or self.process.poll() is not None: self._start()
                self.sequence+=1
                self._send({'id':self.sequence,'method':'account/rateLimits/read'})
                result=self._response(self.sequence)
                return dict(windows=windows_from_limits(result),updated_at=time.time(),source='live',error=None)
            except Exception:
                self.close()
                raise

    def close(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except (OSError,subprocess.TimeoutExpired):
                try: self.process.kill()
                except OSError: pass
            self.process=None

class SessionReader:
    def __init__(self, path):
        self.path=pathlib.Path(path)
        self.offset=0
        self.pending=b''
        self.state='idle'
        self.public_note=''
        self.last_event=0.0
        self.started=0.0
        self.turn_id=None
        self.ended=0.0
        self.active=False
        self.rate=None
        self.revision=0
        self.recent_tool_state=None; self.tool_visible_until=0
        self.poll()

    def accept(self, obj):
        payload=obj.get('payload') or {}
        category=obj.get('type')
        kind=payload.get('type')
        when=timestamp(obj.get('timestamp'))
        if category=='event_msg':
            if kind=='task_started':
                turn_id=payload.get('turn_id')
                if not turn_id or turn_id!=self.turn_id: self.started=when
                self.turn_id=turn_id; self.active=True; self.ended=0
                self.state='thinking'; self.public_note=''
                self.recent_tool_state=None; self.tool_visible_until=0
            elif kind in ('task_complete','task_completed','turn_aborted'):
                self.active=False; self.ended=when
                self.state='done' if kind!='turn_aborted' else 'paused'
            elif kind=='token_count':
                limits=payload.get('rate_limits')
                if limits:
                    self.rate=dict(windows=windows_from_limits({'rateLimits':limits}),updated_at=when,source='session',error=None)
                return
            elif kind in ('error','turn_failed'):
                self.active=False; self.ended=when; self.state='error'
            else: return
        elif category=='response_item':
            # Ignore reasoning items, user messages, tool arguments and outputs as text.
            if kind=='message' and payload.get('role')=='assistant':
                if payload.get('phase')=='commentary':
                    text=' '.join(c.get('text','') for c in payload.get('content',[]) if c.get('type') in ('output_text','text'))
                    self.public_note=re.sub(r'\s+',' ',text).strip()[:260]
                elif payload.get('phase')=='final_answer':
                    self.state='done'; self.active=False; self.ended=when
                else: return
            elif kind in ('function_call','custom_tool_call'):
                self.state=tool_phase(payload); self.recent_tool_state=self.state; self.tool_visible_until=0
                self.active=True
            elif kind in ('function_call_output','custom_tool_call_output'):
                if self.active and self.state!='waiting':
                    # A sub-second operation may start and finish between polls.
                    # Briefly retain its animation, but never delay completion.
                    if self.state in ('reading','writing'): self.tool_visible_until=when+1.5
                    self.state='thinking'
            else: return
        else: return
        self.last_event=max(self.last_event,when)
        self.revision+=1

    def display_state(self,now):
        if self.active and self.state=='thinking' and now<self.tool_visible_until and self.recent_tool_state in ('reading','writing'): return self.recent_tool_state
        return self.state

    def poll(self):
        try:
            size=self.path.stat().st_size
            if size<self.offset:
                self.offset=0; self.pending=b''; self.active=False; self.state='idle'; self.last_event=0
            with self.path.open('rb') as file:
                file.seek(self.offset)
                if self.offset==0 and size>8_000_000:
                    file.seek(size-8_000_000); file.readline()
                chunk=file.read()
                self.offset=file.tell()
            lines=(self.pending+chunk).split(b'\n'); self.pending=lines.pop()
            for line in lines:
                if not line.strip(): continue
                try: self.accept(json.loads(line))
                except (ValueError,TypeError,AttributeError): continue
        except OSError: pass

class Monitor:
    def __init__(self, codex_home=CODEX_HOME):
        self.home=pathlib.Path(codex_home)
        self.readers={}
        self.threads=[]
        self.last_discovery=0
        self.selected='auto'
        self.error=None

    def discover(self):
        candidates=sorted(self.home.glob('state_*.sqlite'),key=lambda p:p.stat().st_mtime,reverse=True)
        if not candidates: self.error='尚未找到 Codex 本地会话'; return
        try:
            with sqlite3.connect(candidates[0].as_uri()+'?mode=ro',uri=True,timeout=0.5) as db:
                # Do not select message bodies, auth or account fields.
                rows=db.execute("SELECT id,title,rollout_path,updated_at FROM threads WHERE archived=0 AND (agent_path IS NULL OR agent_path='/root') ORDER BY updated_at DESC LIMIT 16").fetchall()
            self.threads=[dict(id=r[0],title=r[1],path=r[2],updated=r[3]) for r in rows if r[2] and pathlib.Path(r[2]).is_file()]
            self.error=None
        except sqlite3.Error:
            self.error='会话列表暂不可读，稍后重试'

    def poll(self):
        now=time.time()
        if now-self.last_discovery>5:
            self.discover(); self.last_discovery=now
        for row in self.threads:
            if row['id'] not in self.readers: self.readers[row['id']]=SessionReader(row['path'])
            else: self.readers[row['id']].poll()
        # Keep bounded history, but retain an explicitly pinned conversation.
        keep={row['id'] for row in self.threads}|{self.selected}
        self.readers={key:r for key,r in self.readers.items() if key in keep}
        chosen=next((r for r in self.threads if r['id']==self.selected),None)
        if chosen is None and self.selected=='auto' and self.threads:
            active=[r for r in self.threads if self.readers[r['id']].active and now-self.readers[r['id']].last_event<600]
            chosen=max(active or self.threads,key=lambda r:self.readers[r['id']].last_event)
        if not chosen:
            return dict(state='idle',message=self.error or '我在这里，等你开始下一件事。',title='',thread_id=None,stale=False,revision=0)
        reader=self.readers[chosen['id']]
        age=now-reader.last_event
        stale=reader.active and age>180
        state='unknown' if stale else reader.display_state(now)
        return dict(state=state,message=reader.public_note,title=chosen['title'],thread_id=chosen['id'],turn_id=reader.turn_id,stale=stale,revision=reader.revision,last_event=reader.last_event,active=reader.active,age=age,started=reader.started,ended=reader.ended)

    def cached_rate(self):
        rates=[r.rate for r in self.readers.values() if r.rate]
        return max(rates,key=lambda r:r['updated_at']) if rates else None

if __name__=='__main__':
    monitor=Monitor()
    status=monitor.poll()
    print(json.dumps({k:v for k,v in status.items() if k not in ('message','title')},ensure_ascii=False))
    client=RateClient()
    try: print(json.dumps(client.read(),ensure_ascii=False))
    finally: client.close()
