import json,pathlib,random,tempfile,unittest,zipfile
from voice_pool import clean_clips,clips_for,pick_clip,TaskVoiceGate,task_key,clip_bubble_text
from bindings import BindingMap
from audio_player import resolve_audio
from config_io import export_bundle,import_bundle

class PoolTests(unittest.TestCase):
    def test_custom_bubble_preserves_source_subtitle_and_explicit_empty(self):
        legacy=clean_clips([{'file':'a.wav','subtitle':'原台词'}])[0]
        self.assertEqual(clip_bubble_text(legacy),'原台词')
        paired=clean_clips([dict(legacy,bubble_text='自定义气泡 {quota}')])[0]
        self.assertEqual(clip_bubble_text(paired),'自定义气泡 {quota}')
        self.assertEqual(paired['subtitle'],'原台词')
        self.assertEqual(clip_bubble_text(clean_clips([dict(paired,bubble_text='')])[0]),'')
    def test_task_identity_ignores_status_changes(self):
        a={'thread_id':'chat','turn_id':'turn-a','started':1,'state':'thinking'}
        self.assertEqual(task_key(a),task_key(dict(a,state='reading',started=2)))
        self.assertNotEqual(task_key(a),task_key(dict(a,turn_id='turn-b')))
        self.assertIsNone(task_key({'state':'thinking'}))
    def test_once_per_turn_survives_restart_and_is_not_a_setting(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/'voice-history.json'; gate=TaskVoiceGate(path)
            a=('chat','turn-a'); gate.mark('thinking',a)
            self.assertTrue(TaskVoiceGate(path).contains('thinking',a))
            self.assertFalse(gate.contains('thinking',('chat','turn-b')))
            self.assertFalse(gate.contains('error',a))
            self.assertNotIn('turn-a',path.read_text())
    def test_legacy_single_and_explicit_silence(self):
        b=BindingMap({'a':{'idle':'gif'}},['gif'],[],{'idle':{'audio_file':'old.wav'}})
        self.assertEqual(b.resolve('a','idle')['audio_clips'][0]['file'],'old.wav')
        b.set('idle',audio_clips=[])
        self.assertEqual(b.resolve('a','idle')['audio_clips'],[])
    def test_normalize_and_defensive_copy(self):
        b=BindingMap({'a':{'idle':'gif'}},['gif'],[])
        b.set('idle',audio_clips=['a.wav',{'file':'b.wav','subtitle':'字幕','enabled':False},None])
        snapshot=b.to_dict(); snapshot['idle']['audio_clips'][0]['file']='changed'
        self.assertEqual(b.resolve('a','idle')['audio_clips'][0]['file'],'a.wav')
        self.assertFalse(b.resolve('a','idle')['audio_clips'][1]['enabled'])
    def test_random_draw_and_no_consecutive_repeat(self):
        rows=[{'identity':str(i),'subtitle':str(i)} for i in range(3)]; rng=random.Random(8); last=None; seen=set()
        for _ in range(50):
            chosen=pick_clip(rows,last,True,rng.choice); self.assertNotEqual(chosen['identity'],last); seen.add(chosen['identity']); last=chosen['identity']
        self.assertEqual(seen,{'0','1','2'})
        self.assertEqual(pick_clip(rows[:1],'0')['identity'],'0')
        self.assertIsNone(pick_clip([]))
    def test_pool_and_captions_survive_two_migrations(self):
        with tempfile.TemporaryDirectory() as td:
            base=pathlib.Path(td); root=base/'original'; (root/'audio').mkdir(parents=True)
            for name in ('a.wav','b.wav'): (root/'audio'/name).write_bytes(b'RIFF'+name.encode())
            cfg={'appearance':{'audio_directory':'audio'},'bindings':{'idle':{'audio_clips':[{'file':'a.wav','subtitle':'第一条','bubble_text':'第一条专用气泡','title':'A'},{'file':'b.wav','subtitle':'第二条','bubble_text':'','title':'B','enabled':False}], 'audio_avoid_repeat':True,'audio_subtitles':True}}}
            original=json.dumps(cfg,ensure_ascii=False)
            for i in range(2):
                archive=base/f'export{i}.zip'; export_bundle(archive,cfg,root)
                root=base/f'新电脑{i}'; cfg=import_bundle(archive,root)
                for clip in cfg['bindings']['idle']['audio_clips']:
                    self.assertIsNotNone(resolve_audio(clip['file'],'audio',root))
                self.assertEqual([c['subtitle'] for c in cfg['bindings']['idle']['audio_clips']],['第一条','第二条'])
                self.assertEqual([clip_bubble_text(c) for c in cfg['bindings']['idle']['audio_clips']],['第一条专用气泡',''])
                self.assertFalse(cfg['bindings']['idle']['audio_clips'][1]['enabled'])
                self.assertTrue(cfg['bindings']['idle']['audio_subtitles'])
                if i==0: names=[c['file'] for c in cfg['bindings']['idle']['audio_clips']]
                else: self.assertEqual(names,[c['file'] for c in cfg['bindings']['idle']['audio_clips']])
            self.assertIn('a.wav',original)

if __name__=='__main__': unittest.main()
