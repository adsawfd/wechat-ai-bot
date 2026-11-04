import tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import Mock,patch
from scheduled_morning import tick,validate
class MorningTests(unittest.TestCase):
    def setUp(self):
        self.config={'id':'test-job','account_id':'me','group_id':'room@chatroom','member_id':'target','member_group_name':'X&Y','text':'早上好','hour':8,'minute':0}
    def test_only_morning_beijing(self):
        with tempfile.TemporaryDirectory() as folder,patch('scheduled_greeting.send_greeting',return_value={'status':'成功'}) as send:
            state=Path(folder)/'state.json'
            self.assertFalse(tick(Mock(),self.config,datetime(2026,10,30,7,59),state))
            self.assertTrue(tick(Mock(),self.config,datetime(2026,10,30,0,0,tzinfo=timezone.utc),state))
            self.assertTrue(tick(Mock(),self.config,datetime(2026,10,30,8,0,40),state))
            self.assertFalse(tick(Mock(),self.config,datetime(2026,10,30,8,1),state))
            self.assertEqual(send.call_count,1)
            self.assertTrue(tick(Mock(),self.config,datetime(2026,10,31,8,0),state));self.assertEqual(send.call_count,2)
    def test_guard_and_callback_are_forwarded(self):
        guard=Mock();callback=Mock()
        with tempfile.TemporaryDirectory() as folder,patch('scheduled_greeting.send_greeting',return_value={'status':'跳过','message':'静音'}) as send:
            tick(Mock(),self.config,datetime(2026,10,30,8,0),Path(folder)/'state.json',on_sent=callback,send_guard=guard)
            self.assertIs(send.call_args.kwargs['send_guard'],guard);callback.assert_not_called()
    def test_evening_claim_does_not_skip_morning(self):
        from scheduled_greeting import claim
        with tempfile.TemporaryDirectory() as folder,patch('scheduled_greeting.send_greeting',return_value={'status':'成功'}) as send:
            state=Path(folder)/'state.json';claim(state,'daily:2026-10-30')
            tick(Mock(),self.config,datetime(2026,10,30,8,0),state);send.assert_called_once()
if __name__=='__main__':unittest.main()
