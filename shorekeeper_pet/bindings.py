"""Versioned and validated per-state presentation settings."""
import copy,math
from .voice_pool import clean_clips,clips_for
PLAYBACKS={'once':'播放一次','loop':'正向循环','pingpong':'往返循环'}
MANUAL={'pet','feed','hover','drag','drop','doubleclick'}
NUMBERS={'speed':(.1,4),'hold_seconds':(0,600),'loop_seconds':(0,3600),'bubble_seconds':(0,600),'font_size':(0,40),'audio_delay':(0,60)}

class BindingMap:
    def __init__(self,defaults,assets,once_states,saved=None,baseline=None):
        self.defaults=defaults; self.assets=set(assets); self.once_states=set(once_states)
        self.states=set().union(*(set(p) for p in defaults.values())); self.overrides={}
        self.baseline={state:self.clean(value) for state,value in (baseline or {}).items() if state in self.states and isinstance(value,dict)}
        if isinstance(saved,dict):
            for state,item in saved.items():
                if state in self.states and isinstance(item,dict):
                    valid=self.clean(item)
                    if valid: self.overrides[state]=valid

    def clean(self,item):
        result={}
        for key,value in item.items():
            if key=='asset' and isinstance(value,str) and value in self.assets: result[key]=value
            elif key=='playback' and isinstance(value,str) and value in PLAYBACKS: result[key]=value
            elif key=='next_state' and isinstance(value,str) and value in self.states|{'auto','hold'}: result[key]=value
            elif key=='bubble_mode' and value in ('auto','custom','audio','off'): result[key]=value
            elif key=='audio_policy' and value in ('entry','turn'): result[key]=value
            elif key in NUMBERS and isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):
                low,high=NUMBERS[key]; result[key]=max(low,min(high,float(value)))
            elif key=='bubble_text' and isinstance(value,str): result[key]=value
            elif key in ('font_family','audio_file') and isinstance(value,str): result[key]=value[:2000]
            elif key in ('audio_enabled','interruptible','audio_avoid_repeat','audio_subtitles') and isinstance(value,bool): result[key]=value
            elif key=='audio_clips' and isinstance(value,list): result[key]=clean_clips(value)
        return result

    def resolve(self,pack,state):
        preset=self.defaults[pack]; item=self.overrides.get(state,{})
        result=dict(asset=preset.get(state,preset['idle']),playback='once' if state in self.once_states else 'pingpong',speed=1.0,hold_seconds=2.0,loop_seconds=5.0 if state in MANUAL-{'drag','hover'} else 0.0,next_state='auto',interruptible=state not in MANUAL|{'done','error'},bubble_mode='auto',bubble_text='',bubble_seconds=10.0,font_family='',font_size=0.0,audio_file='',audio_enabled=True,audio_delay=0.0)
        result.update(audio_avoid_repeat=True,audio_subtitles=True,audio_policy='turn' if state=='thinking' else 'entry')
        base=self.baseline.get(state,{})
        result.update(base); result.update(item)
        voice=item if 'audio_clips' in item or 'audio_file' in item else base
        result['audio_clips']=clips_for(voice); result['custom']=bool(item)
        if result['asset'] not in self.assets: result['asset']=base.get('asset',preset.get(state,preset['idle']))
        if result['asset'] not in self.assets: result['asset']=preset.get(state,preset['idle'])
        return result

    def set(self,state,**changes):
        if state not in self.states: raise ValueError('Unknown interaction')
        changes={k:v for k,v in changes.items() if v is not None}; clean=self.clean(changes)
        if set(clean)!=set(changes): raise ValueError('Invalid binding value')
        self.overrides.setdefault(state,{}).update(clean)
    def reset(self,state): self.overrides.pop(state,None)
    def to_dict(self): return copy.deepcopy(self.overrides)

def playback_seconds(binding,duration_ms,pingpong_ms):
    if binding['playback']=='once': return duration_ms/1000/binding['speed']+binding['hold_seconds']
    return binding['loop_seconds'] or None

class PlaybackController:
    """One entry per real event; finished one-shots do not retrigger on polling."""
    def __init__(self,resolve,duration,now=0):
        self.resolve=resolve; self.duration=duration; self.state='idle'; self.started=now; self.serial=0
        self.live_state='idle'; self.live_key=None; self.consumed_key=None; self.owner='live'; self.hard_deadline=None
    def enter(self,state,now,owner='interaction',hard_limit=None):
        self.state=state; self.started=now; self.owner=owner; self.serial+=1
        self.hard_deadline=now+hard_limit if hard_limit is not None else None
    def set_live(self,state,key,now):
        changed=key!=self.live_key; self.live_state=state; self.live_key=key
        if changed and self.owner!='preview' and (self.serial==0 or self.resolve(self.state)['interruptible']): self.enter(state,now,'live')
    def resume(self,now): self.enter('idle' if self.consumed_key==self.live_key else self.live_state,now,'live')
    def tick(self,now):
        b=self.resolve(self.state); duration,ping=self.duration(b['asset']); deadline=playback_seconds(b,duration,ping)
        hard=self.hard_deadline is not None and now>=self.hard_deadline
        if not hard and (b['next_state']=='hold' or deadline is None or now-self.started<deadline): return
        target=b['next_state']
        if target=='auto' or hard:
            if self.state==self.live_state: self.consumed_key=self.live_key
            self.resume(now)
        else:
            self.consumed_key=self.live_key; self.enter(target,now,'chain')
