"""Behavioral checks for narrow bubbles, exclusive captions and saved profiles."""
import copy,json,pathlib,shutil,tempfile,time,unittest,wave
from unittest.mock import patch
from PySide6.QtCore import QRect
from PySide6.QtGui import QFontMetrics,QFontDatabase
from PySide6.QtWidgets import QApplication
import pet as module
from renderer import wrap_text
from config_io import migrate_settings,save_atomic,export_bundle,import_bundle
from voice_pool import clean_clips


class BubbleMigrationTests(unittest.TestCase):
    def test_legacy_pairs_migrate_but_explicit_modes_survive_later_restarts(self):
        pair={'audio_clips':[{'file':'voice.wav','subtitle':'配对字幕'}],'bubble_text':'旧台词','bubble_mode':'custom'}
        source={'schema_version':6,'bindings':{'pet':pair,'idle':dict(pair,bubble_mode='off'),'feed':dict(pair,audio_subtitles=False)}}
        cfg=migrate_settings(source)
        self.assertEqual(cfg['bindings']['pet']['bubble_mode'],'audio')
        self.assertEqual(cfg['bindings']['pet']['bubble_text'],'旧台词')
        self.assertEqual(cfg['bindings']['idle']['bubble_mode'],'off')
        self.assertEqual(cfg['bindings']['feed']['bubble_mode'],'custom')
        cfg['bindings']['pet']['bubble_mode']='custom'
        self.assertEqual(migrate_settings(cfg),cfg)
        self.assertEqual(source['bindings']['pet']['bubble_mode'],'custom')


class BubbleWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=pathlib.Path(self.temp.name)/'original'; self.root.mkdir()
        self.original_root=module.ROOT; self.original_settings=module.SETTINGS
        asset=module.CATALOG[0]; self.aid=asset['id']
        target=self.root/asset['path']; target.parent.mkdir(parents=True); shutil.copy2(module.ROOT/asset['path'],target)
        (self.root/'audio').mkdir()
        with wave.open(str(self.root/'audio/voice.wav'),'wb') as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(8000); out.writeframes(b'\0\0'*8000)
        cfg={'schema_version':7,'appearance':{'audio_enabled':False},'bindings':{s:{'asset':self.aid,'audio_clips':[],'bubble_mode':'custom','bubble_text':'测试台词','bubble_seconds':0} for s in module.STATES}}
        module.ROOT=self.root; module.SETTINGS=self.root/'settings.json'; save_atomic(module.SETTINGS,cfg)
        self.pet=module.Pet(offline=True); self.pet.timer.stop(); self.pet.hover_timer.stop(); self.pet.click_timer.stop()
        self.pet.screen_area=lambda:QRect(-1280,0,1280,900)
        self.pet.show(); self.pet.update_layout()

    def tearDown(self):
        self.pet.voice.stop(); self.pet.hide(); self.pet.bubble_window.hide()
        for dialog in (self.pet.binding_editor,self.pet.preferences):
            if dialog:
                if hasattr(dialog,'timer'): dialog.timer.stop()
                dialog.hide(); dialog.deleteLater()
        self.pet.deleteLater(); self.app.processEvents()
        module.ROOT=self.original_root; module.SETTINGS=self.original_settings
        QFontDatabase.removeAllApplicationFonts(); self.temp.cleanup()

    def test_horizontal_edges_follow_character_at_all_sizes_and_screen_edges(self):
        p=self.pet
        for size in (140,230,420):
            p.options['pet_size']=size
            for scale in (.5,.85,1,1.333,2):
                p.set_scale(scale)
                for x in (-1280,-900,-p.width()):
                    p.move(x,500); p.clamp_position(); p.update_bubble()
                    left=p.x()+p.pet_rect.left()*p.scale_factor
                    right=p.x()+p.pet_rect.right()*p.scale_factor
                    self.assertGreaterEqual(p.bubble_window.x(),left)
                    self.assertLessEqual(p.bubble_window.x()+p.bubble_window.width(),right)
                    self.assertLess(right-left-p.bubble_window.width(),2.01)

    def test_long_text_wraps_without_line_or_character_truncation_or_font_shrink(self):
        p=self.pet; text='这是完整的长台词。'*650+'结束标记'
        p.set_binding('idle',bubble_text=text)
        self.assertEqual(''.join(p.bubble_lines),text)
        self.assertGreater(len(p.bubble_lines),8)
        self.assertEqual(p.bubble_scale,p.scale_factor)
        self.assertGreater(p.bubble_window.height(),p.screen_area().height())
        metrics=QFontMetrics(p.bubble_font)
        self.assertTrue(all(metrics.horizontalAdvance(line)<=p.bubble_width-52 for line in p.bubble_lines))
        self.assertEqual(wrap_text('甲\n\n乙\n',metrics,500),['甲','','乙',''])
        self.assertEqual(clean_clips([{'file':'voice.wav','subtitle':text,'bubble_text':text}])[0]['bubble_text'],text)
        self.assertTrue(p.save_settings())
        self.assertEqual(module.load_settings()['bindings']['idle']['bubble_text'],text)

    def test_paired_bubble_survives_gif_change_then_hides_without_generic_fallback(self):
        p=self.pet
        clips=[{'file':'voice.wav','subtitle':'只显示抽中的这句','enabled':True}]
        p.set_binding('thinking',bubble_mode='audio',bubble_text='不能出现的通用台词',audio_clips=clips,bubble_seconds=.01)
        p.set_binding('reading',bubble_mode='audio')
        self.assertTrue(p.voice.trigger('thinking',p.binding('thinking'),p.options,preview=True))
        p.voice.pending.stop()  # Exercise state lifetime without playing sound in tests.
        p.controller.enter('reading',time.monotonic()-60,'live'); p.tick()
        self.assertEqual(p.state,'reading'); self.assertEqual(p.bubble_state(),'thinking')
        self.assertTrue(p.bubble_visible()); self.assertEqual(p.bubble_text(),'只显示抽中的这句')
        p.voice._finish()
        self.assertFalse(p.bubble_visible()); self.assertEqual(p.bubble_text(),'')
        self.assertFalse(p.voice.busy)

    def test_empty_missing_disabled_audio_and_custom_mode_do_not_show_paired_text(self):
        p=self.pet
        p.set_binding('idle',bubble_mode='audio',bubble_text='不得回退',audio_clips=[{'file':'missing.wav','subtitle':'缺失文件'}])
        self.assertFalse(p.voice.trigger('idle',p.binding('idle'),p.options,preview=True))
        self.assertFalse(p.bubble_visible()); self.assertEqual(p.bubble_text(),'')
        p.set_binding('idle',audio_clips=[{'file':'voice.wav','subtitle':'原文','bubble_text':''}])
        p.voice.trigger('idle',p.binding('idle'),p.options,preview=True); p.voice.pending.stop()
        self.assertFalse(p.bubble_visible()); self.assertEqual(p.bubble_text(),'')
        p.voice.selected_clip['bubble_text']='配对文案'
        p.set_binding('idle',bubble_mode='custom',bubble_text='只使用我的台词')
        self.assertEqual(p.bubble_text(),'只使用我的台词'); self.assertFalse(p.voice_bubble())
        p.save_settings(); self.assertEqual(module.load_settings()['bindings']['idle']['bubble_mode'],'custom')
        p.set_binding('idle',bubble_mode='off'); self.assertFalse(p.bubble_visible())

    def test_mode_controls_and_long_pairs_survive_two_exports(self):
        p=self.pet
        # Restrict the test gallery to its fixture instead of loading all 83 GIFs.
        from studio import BindingEditor
        p.binding_editor=BindingEditor(p,[module.ASSETS[self.aid]],module.ASSETS,self.root)
        editor=p.binding_editor; combo=editor.controls['bubble_mode']
        self.assertGreaterEqual(combo.findText('自定义音频+字幕'),0)
        combo.setCurrentIndex(combo.findData('audio'))
        self.assertFalse(editor.controls['bubble_text'].isEnabled())
        self.assertFalse(editor.controls['bubble_seconds'].isEnabled())
        self.assertTrue(editor.controls['font_size'].isEnabled())
        text='长字幕'*1700
        p.set_binding('pet',audio_clips=[{'file':'voice.wav','subtitle':text,'bubble_text':text}],bubble_text='保留但不显示的台词')
        cfg=copy.deepcopy(p.settings); root=self.root
        for i in range(2):
            archive=self.root.parent/f'profile-{i}.zip'; self.assertEqual(export_bundle(archive,cfg,root),[])
            root=self.root.parent/f'新电脑-{i}'; cfg=import_bundle(archive,root)
            self.assertEqual(cfg['bindings']['pet']['bubble_mode'],'audio')
            self.assertEqual(cfg['bindings']['pet']['audio_clips'][0]['bubble_text'],text)
            self.assertEqual(cfg['bindings']['pet']['bubble_text'],'保留但不显示的台词')
            self.assertEqual((root/'audio/voice.wav').read_bytes(),(self.root/'audio/voice.wav').read_bytes())
            self.assertEqual((root/module.ASSETS[self.aid]['path']).read_bytes(),(self.root/module.ASSETS[self.aid]['path']).read_bytes())


if __name__=='__main__': unittest.main()
