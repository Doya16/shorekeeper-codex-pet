"""Shipped defaults, kept separate from each user's automatically saved profile."""
import copy,json,pathlib
from .audio_player import resolve_audio

def load_defaults(root):
    try:
        data=json.loads((pathlib.Path(root)/'defaults/settings.json').read_text('utf8'))
        return data if isinstance(data,dict) else {}
    except (OSError,ValueError): return {}

def default_bindings(root):
    data=load_defaults(root); bindings=copy.deepcopy(data.get('bindings',{}))
    directory=data.get('appearance',{}).get('audio_directory','defaults/audio')
    for binding in bindings.values():
        for clip in binding.get('audio_clips',[]):
            path=resolve_audio(clip.get('file',''),directory,pathlib.Path(root))
            if path: clip['file']=str(path.resolve())
        if binding.get('audio_file'):
            path=resolve_audio(binding['audio_file'],directory,pathlib.Path(root))
            if path: binding['audio_file']=str(path.resolve())
    return bindings
