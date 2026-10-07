import json, pathlib, tempfile, unittest
from shorekeeper_pet.bridge import SessionReader, windows_from_limits,tool_phase,Monitor
from unittest.mock import patch

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=pathlib.Path(self.temp.name)/'session.jsonl'
        self.path.touch(); self.reader=SessionReader(self.path)
    def tearDown(self): self.temp.cleanup()
    def event(self,category,payload):
        return dict(timestamp='2026-10-06T20:00:00Z',type=category,payload=payload)
    def test_public_progress_and_private_reasoning(self):
        r=self.reader
        r.accept(self.event('event_msg',dict(type='task_started')))
        r.accept(self.event('response_item',dict(type='reasoning',summary=[{'text':'PRIVATE'}])))
        self.assertEqual(r.public_note,'')
        r.accept(self.event('response_item',dict(type='message',role='assistant',phase='commentary',content=[dict(type='output_text',text='正在读取文件。')])))
        self.assertEqual(r.public_note,'正在读取文件。')
        r.accept(self.event('response_item',dict(type='message',role='user',content=[dict(type='input_text',text='DO NOT SHOW')])) )
        self.assertNotIn('DO NOT SHOW',r.public_note)
    def test_tool_completion_does_not_complete_turn(self):
        r=self.reader
        r.accept(self.event('response_item',dict(type='custom_tool_call',name='exec',input='await tools.apply_patch("...")')))
        self.assertEqual(r.state,'writing')
        r.accept(self.event('response_item',dict(type='custom_tool_call_output',output='done')))
        self.assertTrue(r.active); self.assertEqual(r.state,'thinking')
        r.accept(self.event('event_msg',dict(type='task_complete')))
        self.assertFalse(r.active); self.assertEqual(r.state,'done')
    def test_wait_then_work(self):
        r=self.reader
        r.accept(self.event('response_item',dict(type='function_call',name='request_user_input_async')))
        r.accept(self.event('response_item',dict(type='function_call_output')))
        self.assertEqual(r.state,'waiting')
        r.accept(self.event('response_item',dict(type='custom_tool_call',name='exec',input='await tools.exec_command({})')))
        self.assertEqual(r.state,'working')
    def test_partial_utf8_line(self):
        line=(json.dumps(self.event('event_msg',dict(type='task_started')),ensure_ascii=False)+'\n').encode()
        self.path.write_bytes(line[:35]); self.reader.poll(); self.assertFalse(self.reader.active)
        with self.path.open('ab') as f: f.write(line[35:])
        self.reader.poll(); self.assertTrue(self.reader.active)
        revision=self.reader.revision; self.reader.poll(); self.assertEqual(revision,self.reader.revision)
    def test_interrupted(self):
        self.reader.accept(self.event('event_msg',dict(type='turn_aborted')))
        self.assertEqual(self.reader.state,'paused'); self.assertFalse(self.reader.active)
    def test_turn_id_is_stable_across_tools(self):
        self.reader.accept(self.event('event_msg',dict(type='task_started',turn_id='turn-a')))
        self.reader.accept(self.event('response_item',dict(type='function_call',name='read_file')))
        self.reader.accept(self.event('response_item',dict(type='function_call_output')))
        self.assertEqual(self.reader.turn_id,'turn-a')
        self.reader.accept(self.event('event_msg',dict(type='task_started',turn_id='turn-b')))
        self.assertEqual(self.reader.turn_id,'turn-b')

    def test_fast_tool_animation_survives_poll_without_delaying_completion(self):
        r=self.reader
        r.accept(self.event('event_msg',dict(type='task_started',turn_id='same-turn')))
        for name,phase in [('read_file','reading'),('apply_patch','writing')]:
            r.accept(self.event('response_item',dict(type='function_call',name=name)))
            r.accept(self.event('response_item',dict(type='function_call_output')))
            self.assertEqual(r.state,'thinking')
            self.assertEqual(r.display_state(r.last_event+1),phase)
            self.assertEqual(r.display_state(r.last_event+2),'thinking')
            self.assertEqual(r.turn_id,'same-turn')
        r.accept(self.event('event_msg',dict(type='task_complete')))
        self.assertEqual(r.display_state(r.last_event+.1),'done')

    def test_shell_reads_and_wrapped_patch_are_classified(self):
        self.assertEqual(tool_phase(dict(name='exec',input='await tools.exec_command({cmd:"Get-Content example.py"})')),'reading')
        self.assertEqual(tool_phase(dict(name='exec_command',arguments=json.dumps({'cmd':'rg -n pattern code'}))),'reading')
        self.assertEqual(tool_phase(dict(name='exec',input='await tools.apply_patch("...")')),'writing')
        self.assertEqual(tool_phase(dict(name='exec',input='await tools.exec_command({cmd:"python build.py"})')),'working')

    def test_auto_follows_active_task_instead_of_old_pinned_task(self):
        old=self.path.parent/'old.jsonl'; old.write_text(json.dumps(self.event('event_msg',dict(type='task_complete')))+'\n')
        self.path.write_text(json.dumps(self.event('event_msg',dict(type='task_started',turn_id='active-turn')))+'\n')
        monitor=Monitor(self.path.parent); monitor.discover=lambda:None
        monitor.threads=[dict(id='old',title='old',path=str(old)),dict(id='new',title='new',path=str(self.path))]
        monitor.selected='old'
        from shorekeeper_pet.bridge import timestamp
        with patch('shorekeeper_pet.bridge.time.time',return_value=timestamp('2026-10-06T20:00:01Z')):
            self.assertEqual(monitor.poll()['state'],'done')
            monitor.selected='auto'; status=monitor.poll()
            self.assertEqual(status['thread_id'],'new'); self.assertEqual(status['state'],'thinking')

class QuotaTests(unittest.TestCase):
    def test_unknown_is_not_zero(self):
        self.assertEqual(windows_from_limits({}),[])
        self.assertEqual(windows_from_limits({'rateLimits':{'primary':{'usedPercent':None}}}),[])
    def test_remaining_multi_bucket(self):
        rows=windows_from_limits({'rateLimitsByLimitId':{'codex':{'primary':{'usedPercent':19,'windowDurationMins':10080}},'other':{'primary':{'usedPercent':103,'windowDurationMins':300},'secondary':{'usedPercent':-2}}}})
        self.assertEqual([r['remaining'] for r in rows],[81,0,100])
        self.assertEqual(rows[0]['label'],'每周'); self.assertEqual(rows[1]['label'],'5 小时')
    def test_session_format(self):
        rows=windows_from_limits({'rateLimits':{'limit_id':'codex','primary':{'used_percent':23,'window_minutes':10080,'resets_at':123}}})
        self.assertEqual(rows[0]['remaining'],77); self.assertEqual(rows[0]['resets_at'],123)

if __name__=='__main__': unittest.main()
