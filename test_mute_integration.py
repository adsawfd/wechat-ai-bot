import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from contextlib import nullcontext
from test_group_followups import FollowupTests
from reply_identity import ReplyIdentity
from respectful_contact import RespectfulContacts
class MuteIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.f=FollowupTests();self.f.setUp()
        self.f.silence.bosses=frozenset({'boss1','boss2'})
        self.f.scope['reply_identity']=ReplyIdentity(['boss1','boss2'])
    def test_ack_once_and_all_members_are_silent(self):
        self.f.deliver('闭嘴',sender='boss1')
        self.f.chat.SendMsg.assert_called_once_with('收到');self.f.generate.assert_not_called()
        self.f.deliver('你怎么不说话',sender='alice',at_ids={'me'})
        self.f.deliver('不要再讲话',sender='boss2')
        self.f.deliver('恢复说话',sender='outsider')
        self.assertEqual(self.f.chat.SendMsg.call_count,1);self.f.generate.assert_not_called()
        self.f.deliver('可以说话了',sender='boss2')
        self.assertEqual(self.f.chat.SendMsg.call_count,2)
        self.f.deliver('你好',sender='alice',at_ids={'me'})
        self.assertEqual(self.f.chat.SendMsg.call_count,3)
    def test_nonboss_cannot_mute(self):
        self.f.deliver('闭嘴',sender='outsider')
        self.assertFalse(self.f.silence.muted(self.f.chat.who))
    def test_muting_during_model_call_discards_pending_reply(self):
        def generate(*args,**kwargs):
            self.f.silence.control(self.f.chat.who,'boss1','闭嘴',999)
            return '不应发出的旧回复'
        self.f.generate.side_effect=generate
        self.f.deliver('你在吗',at_ids={'me'})
        self.f.chat.SendMsg.assert_not_called()
    def test_title_is_applied_to_verified_person(self):
        self.f.scope['respectful_contacts']=RespectfulContacts(['queen'],{'queen':'尊重称呼'})
        self.f.deliver('你好',sender='queen',at_ids={'me'})
        self.assertIn('尊重称呼',self.f.chat.SendMsg.call_args.args[0])
        self.f.chat.SendMsg.reset_mock()
        self.f.deliver('你好',sender='other',at_ids={'me'})
        self.assertNotIn('尊重称呼',self.f.chat.SendMsg.call_args.args[0])
if __name__=='__main__':unittest.main()
