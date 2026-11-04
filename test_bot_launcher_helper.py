import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
import psutil
from bot_launcher_helper import find_bots, is_bot_process, status, stop


class LauncherHelperTests(unittest.TestCase):
    def fake(self, root, args, cwd=None, name='python.exe'):
        process=Mock()
        process.name.return_value=name
        process.cmdline.return_value=args
        process.cwd.return_value=str(cwd or root)
        return process

    def test_only_exact_script_with_matching_project_directory_is_selected(self):
        root=Path.cwd()
        actual=self.fake(root,['python.exe',r'.\bot.py'])
        other=self.fake(root,['python.exe','different.py'])
        different=self.fake(root,['python.exe','bot.py'],cwd=root.parent)
        inline=self.fake(root,['python.exe','-c','bot.py'])
        self.assertTrue(is_bot_process(actual,str(root)))
        for process in (other,different,inline):self.assertFalse(is_bot_process(process,str(root)))
        self.assertEqual(find_bots(str(root),[actual,other,different,inline]),([actual],False))

    def test_unreadable_python_is_not_reported_as_safely_stopped(self):
        process=Mock();process.name.return_value='python.exe'
        process.cmdline.side_effect=psutil.AccessDenied(pid=1)
        self.assertEqual(find_bots(str(Path.cwd()),[process]),([],True))

    def test_start_and_stop_only_a_temporary_dummy_bot(self):
        workspace=Path.cwd().resolve()
        with tempfile.TemporaryDirectory(dir=str(workspace),prefix='launcher_test_') as folder:
            root=Path(folder).resolve()
            self.assertTrue(root.is_relative_to(workspace))
            (root/'bot.py').write_text('import time\ntime.sleep(60)\n',encoding='utf8')
            process=subprocess.Popen([sys.executable,str(root/'bot.py')],cwd=str(root),
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                deadline=time.monotonic()+5
                while time.monotonic()<deadline and status(str(root))!='RUNNING':time.sleep(.1)
                self.assertEqual(status(str(root)),'RUNNING')
                self.assertEqual(stop(str(root)),'STOPPED')
                process.wait(timeout=5)
            finally:
                if process.poll() is None:
                    process.terminate();process.wait(timeout=5)


if __name__=='__main__':unittest.main()
