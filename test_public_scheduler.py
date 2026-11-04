import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock,patch
from scheduled_greeting import run

class SchedulerTests(unittest.TestCase):
    def test_starting_outside_schedule_never_sends_an_automatic_test(self):
        cfg={'account_id':'me','group_id':'group@chatroom','member_id':'person','member_group_name':'成员甲','text':'晚上好','hour':20,'minute':0}
        wx=Mock();wx._db.get_self_info.return_value={'username':'me'}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';path.write_text(json.dumps(cfg),encoding='utf8')
            now=Mock();now.now.return_value=datetime(2026,11,4,12,0)
            with patch('scheduled_greeting.datetime',now),patch('scheduled_greeting.run_once') as send:
                with self.assertRaises(InterruptedError):run(wx,True,path,sleep=Mock(side_effect=InterruptedError))
                send.assert_not_called()
