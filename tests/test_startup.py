import pathlib,subprocess,tempfile,unittest
from unittest.mock import patch,MagicMock
from shorekeeper_pet import startup as s

class StartupTests(unittest.TestCase):
    def test_detect_desktop_but_not_cli_quota_helpers_or_chatgpt(self):
        self.assertTrue(s.is_codex_desktop('C:/Program Files/WindowsApps/OpenAI.Codex_1_x64/app/ChatGPT.exe'))
        self.assertTrue(s.is_codex_desktop('D:/Apps/Codex/app/Codex.exe'))
        self.assertFalse(s.is_codex_desktop('C:/AppData/Local/OpenAI/Codex/bin/version/codex.exe'))
        self.assertFalse(s.is_codex_desktop('C:/Program Files/WindowsApps/OpenAI.ChatGPT_1/app/ChatGPT.exe'))
    def test_desktop_restart_with_surviving_helper(self):
        edges=s.LaunchEdges();self.assertFalse(edges.update([]))
        self.assertTrue(edges.update(s.desktop_roots({10:1,11:10})))
        self.assertFalse(edges.update(s.desktop_roots({10:1,11:10,12:10})))
        self.assertTrue(edges.update(s.desktop_roots({11:10,20:1,21:20})))
        self.assertFalse(edges.update(s.desktop_roots({11:10,20:1,22:20})))
        self.assertTrue(edges.update(s.desktop_roots({11:10,30:1,31:30})))
        self.assertFalse(edges.update([]));self.assertTrue(edges.update([40]))
    def test_retry_does_not_consume_failed_launch(self):
        edges=s.LaunchEdges();self.assertTrue(edges.update([10]));edges.retry()
        self.assertTrue(edges.update([10]));self.assertFalse(edges.update([10]))
    def test_source_and_frozen_commands_preserve_unicode_spaces(self):
        root=pathlib.Path(tempfile.gettempdir())/'我的 桌宠'
        with patch.object(s.sys,'frozen',False,create=True):
            args=s.launch_args(root,True);self.assertEqual(args[1],str(root/'tools/run_pet.py'))
            self.assertIn('--watch-codex',args);self.assertIn(s.WATCHER_REVISION,args)
        with patch.object(s.sys,'frozen',True,create=True),patch.object(s.sys,'executable',str(root/'守岸人Codex桌宠启动.exe')):
            self.assertEqual(s.launch_args(root,True),[str((root/'守岸人Codex桌宠启动.exe').resolve()),'--watch-codex',s.WATCHER_REVISION])
    def test_task_preserves_paths_and_uses_interactive_account_without_elevation(self):
        root=pathlib.Path('D:/我的 桌宠 & 配置');args=['D:/我的 桌宠/启动.exe','--watch-codex','--scheduled-watcher']
        xml=s._task_xml(root,args,'S-1-5-21-123');task=s.ET.fromstring(xml);ns={'t':s.TASK_NS}
        self.assertEqual(task.findtext('t:Actions/t:Exec/t:Command',namespaces=ns),args[0])
        self.assertEqual(task.findtext('t:Actions/t:Exec/t:WorkingDirectory',namespaces=ns),str(root))
        self.assertEqual(task.findtext('t:Principals/t:Principal/t:LogonType',namespaces=ns),'InteractiveToken')
        self.assertEqual(task.findtext('t:Principals/t:Principal/t:RunLevel',namespaces=ns),'LeastPrivilege')
        self.assertEqual(task.findtext('t:Settings/t:ExecutionTimeLimit',namespaces=ns),'PT0S')
        self.assertEqual(task.findtext('t:Settings/t:StopIfGoingOnBatteries',namespaces=ns),'false')
        self.assertTrue(s._task_matches(xml,xml));self.assertFalse(s._task_matches(b'bad xml',xml))
        self.assertFalse(s._task_matches(s._task_xml(root,args,'S-1-5-21-999'),xml))
    def test_windows_query_xml_with_omitted_defaults_and_account_name(self):
        args=['C:/我的 桌宠/启动.exe','--watch-codex'];expected=s._task_xml(pathlib.Path('C:/我的 桌宠'),args,'S-1-5-21-123')
        task=s.ET.fromstring(expected);ns={'t':s.TASK_NS}
        for parent,name in [('Triggers/LogonTrigger','Enabled'),('Principals/Principal','RunLevel'),('Settings','Enabled')]:
            node=task.find('/'.join('t:'+p for p in parent.split('/')),ns);node.remove(node.find('t:'+name,ns))
        task.find('t:Triggers/t:LogonTrigger/t:UserId',ns).text='PC'+chr(92)+'User'
        text=s.ET.tostring(task,encoding='unicode');raw=('<?xml version="1.0" encoding="UTF-16"?>'+text).encode('utf8')
        with patch.object(s,'_account_name',return_value='PC'+chr(92)+'User'):
            self.assertTrue(s._task_matches(raw,expected))
        with patch.object(s,'_account_name',return_value='PC'+chr(92)+'Another'):
            self.assertFalse(s._task_matches(raw,expected))
    def test_existing_task_is_reused_and_moved_install_is_repaired(self):
        root=pathlib.Path('D:/新位置');sid='S-1-5-21-123'
        expected=s._task_xml(root,s.launch_args(root,True)+['--scheduled-watcher'],sid)
        okay=subprocess.CompletedProcess([],0,stdout=b'')
        with patch.object(s,'_user_sid',return_value=sid),patch.object(s,'_log'),patch.object(s,'_task_command',side_effect=[subprocess.CompletedProcess([],0,stdout=expected),okay]) as command:
            self.assertTrue(s._start_scheduled(root));self.assertEqual(command.call_count,2)
            self.assertEqual(command.call_args.args[0],'/Run')
        with patch.object(s,'_user_sid',return_value=sid),patch.object(s,'_log'),patch.object(s,'_task_command',side_effect=[subprocess.CompletedProcess([],0,stdout=b'old'),okay,okay]) as command:
            self.assertTrue(s._start_scheduled(root));self.assertEqual(command.call_args_list[1].args[0],'/Create')
    def test_configure_scheduler_fallback_and_disable(self):
        import winreg
        with tempfile.TemporaryDirectory() as folder,patch.object(winreg,'CreateKey'),patch.object(winreg,'SetValueEx') as set_value,patch.object(winreg,'DeleteValue') as delete_value,patch.object(s,'_log'):
            with patch.object(s,'_control_path',return_value=pathlib.Path(folder)/'control.json'),patch.object(s,'_start_scheduled',side_effect=OSError('not available')),patch.object(s,'_spawn_watcher',return_value='fallback'):
                self.assertEqual(s.configure(True,folder),'fallback');self.assertIn(s.WATCHER_REVISION,set_value.call_args.args[-1])
            with patch.object(s,'_control_path',return_value=pathlib.Path(folder)/'control.json'),patch.object(s,'registered_command',return_value=s.subprocess.list2cmdline(s.launch_args(pathlib.Path(folder).resolve(),True))),patch.object(s,'_task_command') as task,patch.object(s,'_user_sid',return_value='S-1-5-21-123'):
                s.configure(False,folder);delete_value.assert_called_once();self.assertEqual(task.call_args.args,('/Delete','/TN',s._task_name('S-1-5-21-123'),'/F'))
    def test_run_key_bootstrap_routes_to_scheduler(self):
        with patch.object(s.sys,'argv',['run_pet.py','--watch-codex']),patch.object(s,'_start_scheduled',return_value=True) as task,patch.object(s,'_watcher_enabled',return_value=True):
            self.assertEqual(s.watch(pathlib.Path('D:/pet')),0);task.assert_called_once()
    def test_control_survives_different_registry_views_and_disable_or_move(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(s,'_control_path',return_value=pathlib.Path(folder)/'state/startup.json'),patch.object(s,'registered_command',return_value='stale registry view'):
            root=pathlib.Path(folder)/'pet';s._write_control(True,root)
            self.assertTrue(s._watcher_enabled(root))
            self.assertFalse(s._watcher_enabled(pathlib.Path(folder)/'another-pet'))
            s._write_control(False,root);self.assertFalse(s._watcher_enabled(root))
            self.assertEqual(len(list((pathlib.Path(folder)/'state').iterdir())),1)
    def test_diagnostics_are_lines_and_rotate(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            s._log(folder,'test',pid=123);path=pathlib.Path(folder)/'startup-watch.log'
            self.assertEqual(json.loads(path.read_text('utf8'))['event'],'test')
            path.write_text('x'*131073,'utf8');s._log(folder,'next')
            self.assertTrue(path.with_name('startup-watch.previous.log').exists());self.assertEqual(json.loads(path.read_text('utf8'))['event'],'next')

if __name__=='__main__':unittest.main()
