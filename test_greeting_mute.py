import unittest
from contextlib import nullcontext
from unittest.mock import Mock,patch
from scheduled_greeting import send_greeting
class GreetingMuteTests(unittest.TestCase):
    def test_silent_group_has_no_scheduled_send(self):
        wx=Mock();wx._db.get_group_members.return_value=[{'username':'target'}];wx._db.get_nickname.return_value='测试群'
        config={'group_id':'room@chatroom','member_id':'target','text':'test','member_group_name':'target'}
        with patch('group_mentions._send_native') as send:
            result=send_greeting(wx,config,send_guard=lambda room:nullcontext(False))
        self.assertEqual(result['status'],'跳过');send.assert_not_called()
if __name__=='__main__':unittest.main()
