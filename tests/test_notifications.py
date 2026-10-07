import copy,json,pathlib,tempfile,time,unittest,wave
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from shorekeeper_pet import pet as module
from shorekeeper_pet.bridge import Monitor
from shorekeeper_pet.audio_player import VoicePlayer
from shorekeeper_pet.config_io import save_atomic,export_bundle,import_bundle
from shorekeeper_pet.presets import load_defaults

class ConcurrentMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
        self.monitor=Monitor(self.root);self.monitor.observe_since=100;self.monitor.discover=lambda:None
    def tearDown(self):self.tmp.cleanup()
    def event(self,thread,kind,turn,when,category='event_msg',**extra):
        from datetime import datetime,timezone
        path=self.root/(thread+'.jsonl')
        with path.open('a',encoding='utf8') as f:f.write(json.dumps(dict(timestamp=datetime.fromtimestamp(when,timezone.utc).isoformat(),type=category,payload=dict(type=kind,turn_id=turn,**extra)))+'\n')
        if not any(r['id']==thread for r in self.monitor.threads):self.monitor.threads.append(dict(id=thread,title=thread,path=str(path)))
    def poll(self):
        with patch('shorekeeper_pet.bridge.time.time',return_value=110):return self.monitor.poll()
    def test_other_project_completes_while_active_project_keeps_running(self):
        self.event('a','task_started','one',101);self.event('b','task_started','two',102)
        self.assertEqual(self.poll()['thread_id'],'b')
        self.event('a','task_complete','one',103)
        status=self.poll();self.assertEqual(status['thread_id'],'b');self.assertTrue(status['active'])
        self.assertEqual([(x['thread_id'],x['turn_id']) for x in status['events']],[('a','one')])
        self.assertEqual(self.poll()['events'],[])
    def test_final_and_complete_deduplicate_and_two_completions_survive(self):
        for name in ('a','b'):self.event(name,'task_started',name,101)
        self.poll()
        self.event('a','message','a',102,'response_item',role='assistant',phase='final_answer')
        self.event('a','task_complete','a',103);self.event('b','task_complete','b',104)
        self.assertEqual([e['thread_id'] for e in self.poll()['events']],['a','b'])
    def test_fast_new_task_and_completion_between_polls_is_seen_without_old_history(self):
        self.event('old','task_started','old',90);self.event('old','task_complete','old',91)
        self.poll();self.event('new','task_started','new',102);self.event('new','task_complete','new',103)
        self.assertEqual([e['thread_id'] for e in self.poll()['events']],['new'])
    def test_completed_turn_is_retained_when_next_turn_has_already_started(self):
        self.event('a','task_started','first',101);self.poll()
        self.event('a','task_complete','first',102);self.event('a','task_started','second',103)
        status=self.poll();self.assertTrue(status['active']);self.assertEqual(status['turn_id'],'second')
        self.assertEqual(status['events'][0]['turn_id'],'first')
        self.event('a','task_complete','first',104)
        self.assertTrue(self.poll()['active']);self.assertEqual(self.poll()['events'],[])
    def test_fixed_conversation_still_receives_other_project_completions(self):
        self.event('a','task_started','one',101);self.event('b','task_started','two',102)
        self.monitor.selected='b';self.poll();self.event('a','task_complete','one',103)
        status=self.poll();self.assertEqual(status['thread_id'],'b');self.assertEqual(status['events'][0]['thread_id'],'a')

class NotificationWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([]);cls.app.setQuitOnLastWindowClosed(False)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.old=module.SETTINGS
        module.SETTINGS=self.root/'settings.json';cfg=load_defaults(module.ROOT);cfg['appearance']['audio_enabled']=False
        save_atomic(module.SETTINGS,cfg);self.pet=module.Pet(offline=True);self.pet.timer.stop();self.pet.hover_timer.stop();self.pet.voice.gate.path=self.root/'gate.json'
        self.pet.set_binding('done',bubble_mode='custom',bubble_text='{task} 完成',playback='once',hold_seconds=0)
    def tearDown(self):
        self.pet.voice.stop();self.pet.hide()
        for dialog in (self.pet.binding_editor,self.pet.preferences):
            if dialog:
                if hasattr(dialog,'timer'):dialog.timer.stop()
                dialog.hide();dialog.deleteLater()
        self.pet.deleteLater();self.app.processEvents();module.SETTINGS=self.old;self.tmp.cleanup()
    def status(self,events=()):return dict(state='writing',thread_id='running',turn_id='live-turn',started=101,active=True,stale=False,events=list(events),title='Still working')
    def event(self,name):return dict(state='done',thread_id=name,turn_id='turn-'+name,started=101,ended=103,title=name)
    def test_completion_queue_preserves_gifs_context_and_resumes_running_task(self):
        p=self.pet;p.on_status(self.status([self.event('Project A'),self.event('Project B')]))
        self.assertEqual(p.state,'done');self.assertEqual(p.animation_id,p.binding('done')['asset']);self.assertEqual(p.bubble_text(),'Project A 完成')
        p.on_status(self.status());self.assertEqual(p.state,'done')
        p.notification_until=0;p.tick();self.assertEqual(p.bubble_text(),'Project B 完成')
        p.notification_until=0;p.tick();self.assertEqual(p.state,'writing');self.assertEqual(p.animation_id,p.binding('writing')['asset'])
        p.on_status(self.status([self.event('Project A')]));self.assertFalse(p.notifications);self.assertIsNone(p.notification)
    def test_busy_audio_finishes_before_notification_and_each_notification_finishes_its_audio(self):
        p=self.pet;p.voice.busy=True;p.on_status(self.status([self.event('A')]))
        self.assertIsNone(p.notification);self.assertEqual(len(p.notifications),1)
        p.voice.busy=False;p.tick();self.assertEqual(p.state,'done')
        p.voice.busy=True;p.notification_until=0;p.tick();self.assertIsNotNone(p.notification)
        p.voice.busy=False;p.tick();self.assertIsNone(p.notification);self.assertEqual(p.state,'writing')
    def test_repeated_terminal_snapshot_does_not_reenter_completion(self):
        p=self.pet;done=self.event('a');status=dict(done,active=False,events=[done])
        p.on_status(status);p.notification_until=0;p.tick();self.assertEqual(p.state,'idle')
        serial=p.controller.serial;p.on_status(dict(status,events=[]));self.assertEqual(p.controller.serial,serial)
    def test_frequency_controls_locks_and_startup_checkbox_persist(self):
        p=self.pet;p.open_bindings();editor=p.binding_editor;editor.state='idle';editor.load_selection()
        combo=editor.controls['audio_policy'];self.assertEqual(combo.currentData(),'session')
        self.assertFalse(editor.controls['audio_chance'].isEnabled())
        combo.setCurrentIndex(combo.findData('occasional'));self.assertTrue(editor.controls['audio_chance'].isEnabled())
        editor.controls['audio_chance'].setValue(35);editor.controls['audio_min_interval'].setValue(600)
        p.open_preferences();p.preferences.controls['launch_with_codex'].setChecked(True)
        saved=json.loads(module.SETTINGS.read_text('utf8'));self.assertTrue(saved['appearance']['launch_with_codex'])
        self.assertEqual(saved['bindings']['idle']['audio_chance'],35)
        self.assertEqual(p.tray.toolTip(),'守岸人 · 点击唤醒/隐藏')

class VoiceFrequencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
        self.path=self.root/'voice.wav'
        with wave.open(str(self.path),'wb') as f:f.setparams((1,2,8000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*800)
        self.voice=VoicePlayer(self.root);self.options=dict(audio_enabled=True,volume=0,audio_cooldown=0)
        self.binding=dict(audio_policy='session',audio_clips=[dict(file=str(self.path))],audio_delay=60)
    def tearDown(self):self.voice.stop();self.voice.deleteLater();self.app.processEvents();self.tmp.cleanup()
    def play(self,preview=False,**kwargs):
        ok=self.voice.trigger('idle',self.binding,self.options,preview=preview,**kwargs)
        if ok:
            self.voice.pending.stop()
            with patch.object(self.voice.player,'play'):self.voice._prepared(self.voice.generation,str(self.path),'')
        return ok
    def test_once_per_launch_preview_does_not_use_count_and_stop_does_not_reset_count(self):
        self.assertTrue(self.play(preview=True));self.voice.stop();self.assertTrue(self.play())
        self.voice.stop();self.assertFalse(self.play());self.assertTrue(self.play(preview=True));self.voice.stop()
        other=VoicePlayer(self.root);self.assertTrue(other.trigger('idle',self.binding,self.options));other.stop();other.deleteLater()
    def test_missing_or_failed_audio_does_not_spend_session_allowance(self):
        bad=dict(self.binding,audio_clips=[dict(file=str(self.root/'missing.wav'))])
        self.assertFalse(self.voice.trigger('idle',bad,self.options))
        self.assertTrue(self.voice.trigger('idle',self.binding,self.options));self.voice.pending.stop()
        self.voice._prepared(self.voice.generation,'','decoder failed');self.assertTrue(self.play())
    def test_entry_and_occasional_probability_interval(self):
        self.binding.update(audio_policy='entry')
        self.assertTrue(self.play(now=10));self.voice.stop();self.assertTrue(self.play(now=11));self.voice.stop()
        self.binding.update(audio_policy='occasional',audio_chance=25,audio_min_interval=300)
        with patch('shorekeeper_pet.audio_player.random.random',return_value=.1):
            self.assertFalse(self.play(now=12));self.assertTrue(self.play(now=400));self.voice.stop();self.assertFalse(self.play(now=500))
        with patch('shorekeeper_pet.audio_player.random.random',return_value=.9):self.assertFalse(self.play(now=900))
    def test_separate_task_completions_bypass_cooldown_without_duplicates(self):
        binding=dict(self.binding,audio_policy='entry');self.options['audio_cooldown']=300
        for task in (('a','one'),('b','two')):
            self.assertTrue(self.voice.trigger('done',binding,self.options,task=task,notification=True,now=10));self.voice.stop()
            self.assertFalse(self.voice.trigger('done',binding,self.options,task=task,notification=True,now=10))
    def test_options_and_media_survive_two_exports(self):
        cfg={'schema_version':7,'bindings':{'idle':dict(self.binding,audio_policy='occasional',audio_chance=35,audio_min_interval=600)},'appearance':{'audio_directory':'audio','launch_with_codex':True}}
        root=self.root
        for n in range(2):
            archive=self.root/f'profile{n}.zip';self.assertFalse(export_bundle(archive,cfg,root))
            root=self.root/f'restored{n}';cfg=import_bundle(archive,root)
            self.assertTrue(cfg['appearance']['launch_with_codex']);self.assertEqual(cfg['bindings']['idle']['audio_policy'],'occasional')
            self.assertEqual(cfg['bindings']['idle']['audio_min_interval'],600)

if __name__=='__main__':unittest.main()
