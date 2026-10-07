"""Verify real Qt mouse resizing and capture only this app's widgets."""
import copy,json,pathlib,sys,tempfile,time
root=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(root))
from PySide6.QtCore import QPoint,Qt
from PySide6.QtGui import QImage,QPainter,QColor
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from config_io import save_atomic
from presets import load_defaults
import pet as module

app=QApplication([]); app.setQuitOnLastWindowClosed(False)
qa=root/'qa'; qa.mkdir(exist_ok=True)
original=(root/'settings.json').read_bytes() if (root/'settings.json').is_file() else None
with tempfile.TemporaryDirectory() as directory:
    temp=pathlib.Path(directory); module.SETTINGS=temp/'settings.json'
    cfg=load_defaults(root); cfg['appearance']['audio_enabled']=False; save_atomic(module.SETTINGS,cfg)
    pet=module.Pet(offline=True); pet.timer.stop(); pet.hover_timer.stop(); pet.voice.gate.path=temp/'voice-history.json'
    pet.quota_data=dict(windows=[dict(remaining=98,label='每周')],updated_at=time.time(),source='live')
    pet.show(); pet.move(350,500); pet.set_bubble_preview('qa',True); app.processEvents()
    serial=pet.controller.serial; generation=pet.voice.generation; old_bindings=copy.deepcopy(pet.bindings.to_dict())
    for widget,rect,key in [(pet.bubble_window,pet.bubble_window.hit_rect(),'bubble_width_ratio'),(pet,pet.quota_hit_rect(),'quota_scale')]:
        before=pet.options[key]; local=QPoint(round(rect.right()-3),round(rect.center().y())); end=widget.mapToGlobal(local)+QPoint(35,0)
        QTest.mousePress(widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,local)
        QTest.mouseMove(widget,widget.mapFromGlobal(end),20)
        QTest.mouseRelease(widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,widget.mapFromGlobal(end))
        assert pet.options[key]>before,(key,before,pet.options[key])
        assert json.loads(module.SETTINGS.read_text('utf8'))['appearance'][key]==pet.options[key]
    assert pet.controller.serial==serial and pet.voice.generation==generation
    assert pet.bindings.to_dict()==old_bindings
    pet.open_size(); control=pet.size_dialog.presentation_control
    control.preview.setChecked(True); pet.set_bubble_preview('qa',False)
    control.controls['bubble_width_ratio'][1].setValue(175); control.controls['quota_scale'][1].setValue(125)
    pet.set_scale(.85); app.processEvents()
    (root/'docs/demo').mkdir(parents=True,exist_ok=True)
    pet.size_dialog.grab().save(str(root/'docs/demo/resize-controls.png'))
    # Render both app widgets directly; no desktop, chats or other apps captured.
    scale=3; pad=20; gap=5; width=max(pet.width(),pet.bubble_window.width())+pad*2
    height=pet.height()+pet.bubble_window.height()+pad*2+gap
    image=QImage(width*scale,height*scale,QImage.Format.Format_ARGB32); image.fill(QColor('#dce9f8'))
    painter=QPainter(image); painter.scale(scale,scale)
    pet.bubble_window.render(painter,QPoint((width-pet.bubble_window.width())//2,pad))
    pet.render(painter,QPoint((width-pet.width())//2,pad+pet.bubble_window.height()+gap)); painter.end()
    image.save(str(root/'docs/demo/resized-bubble-quota.png'))
    pet.set_bubble_preview('qa',False); pet.voice.stop(); pet.hide(); pet.size_dialog.hide()
assert ((root/'settings.json').read_bytes() if (root/'settings.json').is_file() else None)==original
report=dict(ok=True,native_mouse_drag=True,immediate_resize_and_save=True,no_interaction_or_voice_triggered=True,preview_widgets_captured=True,device_pixel_ratio=app.primaryScreen().devicePixelRatio())
(qa/'v083-ui-checks.json').write_text(json.dumps(report,indent=2),encoding='utf8'); print(json.dumps(report))
