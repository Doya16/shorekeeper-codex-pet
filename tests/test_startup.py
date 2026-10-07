import pathlib,tempfile,unittest
from unittest.mock import patch
from shorekeeper_pet.startup import LaunchEdges,is_codex_desktop,launch_args

class StartupTests(unittest.TestCase):
    def test_detect_desktop_but_not_cli_quota_helpers_or_chatgpt(self):
        self.assertTrue(is_codex_desktop('C:/Program Files/WindowsApps/OpenAI.Codex_1_x64/app/ChatGPT.exe'))
        self.assertTrue(is_codex_desktop('D:/Apps/Codex/app/Codex.exe'))
        self.assertFalse(is_codex_desktop('C:/AppData/Local/OpenAI/Codex/bin/version/codex.exe'))
        self.assertFalse(is_codex_desktop('C:/Program Files/WindowsApps/OpenAI.ChatGPT_1/app/ChatGPT.exe'))
    def test_launch_once_per_desktop_session_and_again_after_restart(self):
        edges=LaunchEdges();self.assertFalse(edges.update([]));self.assertTrue(edges.update([10]))
        self.assertFalse(edges.update([10,11]));self.assertFalse(edges.update([10]));self.assertFalse(edges.update([]))
        self.assertTrue(edges.update([20]));self.assertTrue(edges.update([30]));self.assertFalse(edges.update([30]))
    def test_source_and_frozen_commands_preserve_unicode_spaces(self):
        root=pathlib.Path('D:/我的 桌宠')
        with patch('shorekeeper_pet.startup.sys.frozen',False,create=True):
            args=launch_args(root,True);self.assertEqual(args[-2],str(root/'tools/run_pet.py'));self.assertEqual(args[-1],'--watch-codex')
        with patch('shorekeeper_pet.startup.sys.frozen',True,create=True),patch('shorekeeper_pet.startup.sys.executable',str(root/'守岸人Codex桌宠启动.exe')):
            self.assertEqual(launch_args(root,True),[str((root/'守岸人Codex桌宠启动.exe').resolve()),'--watch-codex'])

if __name__=='__main__':unittest.main()
