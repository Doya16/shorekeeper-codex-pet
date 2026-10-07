"""Serializable per-event voice pools; independent from Qt and playback."""
import copy,random,hashlib,json,pathlib,time

def task_key(status):
    turn=status.get('turn_id') or status.get('started')
    thread=status.get('thread_id')
    return (str(thread),str(turn)) if thread and turn else None

class TaskVoiceGate:
    """Local de-duplication, persisted separately from portable preferences."""
    def __init__(self,path):
        self.path=pathlib.Path(path); self.played={}
        try:
            data=json.loads(self.path.read_text('utf8'))
            if isinstance(data,dict): self.played={k:v for k,v in data.items() if isinstance(k,str) and isinstance(v,(int,float))}
        except (OSError,ValueError): pass
    def identity(self,state,key):
        return hashlib.sha256(json.dumps([state,key],ensure_ascii=False).encode()).hexdigest()
    def contains(self,state,key): return key is not None and self.identity(state,key) in self.played
    def mark(self,state,key):
        self.played[self.identity(state,key)]=time.time()
        self.played=dict(sorted(self.played.items(),key=lambda item:item[1])[-256:])
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True); tmp=self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.played),encoding='utf8'); tmp.replace(self.path)
        except OSError: pass

def clean_clips(value):
    if not isinstance(value,list): return []
    result=[]
    for row in value[:200]:
        if isinstance(row,str): row={'file':row}
        if not isinstance(row,dict) or not isinstance(row.get('file'),str): continue
        path=row['file'].strip()[:2000]
        if not path: continue
        clip=dict(file=path,subtitle=str(row.get('subtitle','')),title=str(row.get('title',''))[:200],enabled=row.get('enabled',True) is not False)
        # Keep source subtitles intact; a custom bubble can differ or be cleared.
        if isinstance(row.get('bubble_text'),str): clip['bubble_text']=row['bubble_text']
        result.append(clip)
    return result


def clip_bubble_text(clip):
    return clip.get('bubble_text',clip.get('subtitle',''))

def clips_for(binding):
    # An explicit empty pool means silence, even when a legacy path remains.
    if 'audio_clips' in binding: return clean_clips(binding['audio_clips'])
    return clean_clips([binding.get('audio_file','')])

def pick_clip(candidates,previous=None,avoid_repeat=True,chooser=random.choice):
    pool=candidates
    if avoid_repeat and len(pool)>1:
        alternatives=[row for row in pool if row['identity']!=previous]
        if alternatives: pool=alternatives
    return copy.deepcopy(chooser(pool)) if pool else None
