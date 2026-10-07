"""Capture only app-owned widgets and verify the current shipped bubble modes."""
import copy,json,pathlib,sys,tempfile,time
root=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(root))
from PySide6.QtCore import QPoint,Qt
from PySide6.QtGui import QImage,QPainter,QColor
from PySide6.QtWidgets import QApplication
from config_io import save_atomic
from presets import load_defaults
from voice_pool import clip_bubble_text
import pet as module

app=QApplication([]); app.setQuitOnLastWindowClosed(False)
qa=root/'qa'; qa.mkdir(exist_ok=True)
original=(root/'settings.json').read_bytes() if (root/'settings.json').is_file() else None
with tempfile.TemporaryDirectory() as directory:
    temp=pathlib.Path(directory); module.SETTINGS=temp/'settings.json'
    cfg=load_defaults(root); cfg['appearance']['audio_enabled']=False
    save_atomic(module.SETTINGS,cfg)
    pet=module.Pet(offline=True); pet.timer.stop(); pet.hover_timer.stop()
    pet.voice.gate.path=temp/'voice-history.json'
    pet.quota_data=dict(windows=[dict(remaining=98,label='每周')],updated_at=time.time(),source='live')
    paired=[state for state,b in cfg['bindings'].items() if any(clip_bubble_text(c) for c in b.get('audio_clips',[]))]
    assert len(paired)==11 and all(pet.binding(s)['bubble_mode']=='audio' for s in paired)
    pet.state='idle'; pet.voice.busy=True; pet.voice.selected_state='idle'
    pet.voice.selected_clip=copy.deepcopy(pet.binding('idle')['audio_clips'][0])
    pet.show(); pet.move(300,500); pet.update_layout(); app.processEvents()
    assert pet.bubble_visible()
    assert ''.join(pet.bubble_lines)==pet.bubble_text().replace('\n','')
    # A high-resolution render of the two owned widgets, without a desktop grab.
    scale=3; pad=22; gap=5
    width=max(pet.width(),pet.bubble_window.width())+pad*2
    height=pet.height()+pet.bubble_window.height()+pad*2+gap
    image=QImage(width*scale,height*scale,QImage.Format.Format_ARGB32); image.fill(QColor('#dce9f8'))
    painter=QPainter(image); painter.scale(scale,scale)
    pet.bubble_window.render(painter,QPoint(pad+(width-pad*2-pet.bubble_window.width())//2,pad))
    pet.render(painter,QPoint(pad,pad+pet.bubble_window.height()+gap)); painter.end()
    image.save(str(qa/'v082-paired-bubble.png'))
    pet.open_bindings(); editor=pet.binding_editor; editor.timer.stop()
    for i in range(editor.triggers.count()):
        if editor.triggers.item(i).data(Qt.ItemDataRole.UserRole)=='thinking': editor.triggers.setCurrentRow(i); break
    editor.tabs.setCurrentIndex(2); editor.resize(1140,980); app.processEvents()
    assert editor.controls['bubble_mode'].currentText()=='自定义音频+字幕'
    assert not editor.controls['bubble_text'].isEnabled() and not editor.controls['bubble_seconds'].isEnabled()
    assert editor.controls['font_size'].isEnabled()
    (root/'docs/demo').mkdir(parents=True,exist_ok=True)
    editor.grab().save(str(root/'docs/demo/bubble-mode-panel.png'))
    pet.voice._finish(); assert not pet.bubble_visible()
    # Discover a turn in reading, then switch through all work states. The
    # opening clip is not replayed; a new turn can notify again.
    pet.options['audio_enabled']=True; pet.options['volume']=0
    pet.bindings.set('thinking',audio_delay=60)
    pet.on_status(dict(state='reading',thread_id='test',turn_id='one',active=True,stale=False,started=1))
    first=pet.voice.generation; assert pet.voice.busy and pet.voice.selected_state=='thinking'
    for state in ('writing','thinking','reading','thinking'):
        pet.on_status(dict(state=state,thread_id='test',turn_id='one',active=True,stale=False,started=1))
        assert pet.voice.generation==first
        assert pet.state==state and pet.animation_id==pet.binding(state)['asset']
    pet.voice.pending.stop(); pet.voice._finish()
    pet.on_status(dict(state='thinking',thread_id='test',turn_id='one',active=True,stale=False,started=1))
    assert not pet.voice.busy
    pet.on_status(dict(state='thinking',thread_id='test',turn_id='two',active=True,stale=False,started=2))
    assert pet.voice.busy and pet.voice.generation>first
    pet.voice.stop(); pet.hide(); editor.hide()
assert ((root/'settings.json').read_bytes() if (root/'settings.json').is_file() else None)==original
report=dict(ok=True,paired_modes=len(paired),captured_widgets_only=True,voice_once_per_turn=True,thinking_reading_writing_gifs=True,editor_mode_and_locks=True)
(qa/'v082-ui-checks.json').write_text(json.dumps(report,indent=2),encoding='utf8'); print(json.dumps(report))
