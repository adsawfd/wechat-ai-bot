import unittest
from test_group_followups import FollowupTests
from reply_identity import ReplyIdentity
class QueryTests(unittest.TestCase):
    def setUp(self):
        self.f=FollowupTests();self.f.setUp();self.f.scope['reply_identity']=ReplyIdentity(['boss'])
    def test_group_query_bypasses_model_and_workflow(self):
        self.f.deliver('查询今日token消耗',sender='boss')
        self.f.chat.SendMsg.assert_called_once_with('好的老板，测试用量报告')
        self.f.generate.assert_not_called();self.f.scope['remote_computer'].route.assert_not_called()
    def test_others_can_get_usage_without_boss_title(self):
        self.f.deliver('查询今日token消耗',sender='other',at_ids={'me'})
        self.f.chat.SendMsg.assert_called_once_with('测试用量报告')
        self.f.generate.assert_not_called()
    def test_queen_title_is_preserved_without_boss_role(self):
        from respectful_contact import RespectfulContacts
        self.f.scope['respectful_contacts']=RespectfulContacts(['queen'],{'queen':'尊重称呼'})
        self.f.deliver('今天token用了多少',sender='queen')
        self.f.chat.SendMsg.assert_called_once_with('尊重称呼，测试用量报告')
    def test_muted_group_stays_silent(self):
        self.f.silence.bosses=frozenset({'boss'})
        self.f.silence.control(self.f.chat.who,'boss','闭嘴',1)
        self.f.deliver('查询今日token消耗',sender='boss')
        self.f.chat.SendMsg.assert_not_called();self.f.scope['usage_ledger'].report.assert_not_called()
if __name__=='__main__':unittest.main()

class NaturalQueryTests(unittest.TestCase):
    def test_natural_forms_and_followup(self):
        from token_usage import UsageQueries
        q=UsageQueries(clock=lambda:100)
        for text in ['今天烧了多少token','用量怎么样','输入输出分别多少','微信助手，看看今天用了多少令牌','咱今天token用了多少呀']:
            self.assertTrue(q.matches(text,'room'),text)
        self.assertFalse(q.matches('那输出呢','room'))
        q.remember('room');self.assertTrue(q.matches('那输出呢','room'))
        self.assertFalse(q.matches('那输出呢','other-room'))
        q.clock=lambda:301;self.assertFalse(q.matches('那输出呢','room'))
    def test_semantic_fallback(self):
        from token_usage import UsageQueries
        from unittest.mock import Mock
        from types import SimpleNamespace
        client=Mock();client.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"usage_query":true}'))])
        self.assertTrue(UsageQueries(client).matches('token账本拉出来让我瞅瞅','room'))
        client.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"usage_query":false}'))])
        self.assertFalse(UsageQueries(client).matches('token如何表示语言','room'))
