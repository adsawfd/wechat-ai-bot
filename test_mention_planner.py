import json
import unittest
from unittest.mock import Mock
from mention_planner import build_mention_roster,has_mention_request,strip_mention_control


class MentionPlanningTests(unittest.TestCase):
    def fixture(self,text='微信助手，帮我@🐾问问有没有空',recent=('paw',)):
        db=Mock()
        db.get_group_members.return_value=[dict(username='me',nick_name='微信助手'),
            dict(username='caller',nick_name='成员乙'),dict(username='paw',nick_name='🐾'),
            dict(username='private_id_never_send',nick_name='：)')]
        roster=build_mention_roster(db,'room@chatroom','caller','me',text,recent_ids=recent)
        return db,roster

    def tag(self,roster,who='paw',mode='requested'):
        code=next(code for code,item in roster.targets.items() if item['id']==who)
        return '[[群聊@:'+json.dumps(dict(target=code,mode=mode,intro='来聊聊晚上安排'),ensure_ascii=False)+']]'+'晚上有空吗？'

    def test_requested_third_member_is_bound_to_native_id_without_leaking_ids(self):
        db,roster=self.fixture()
        clean,plan,error=roster.parse(self.tag(roster))
        self.assertEqual(clean,'晚上有空吗？')
        self.assertEqual(plan.target_id,'paw')
        self.assertFalse(error)
        self.assertNotIn('private_id_never_send',roster.note())
        self.assertNotIn('me',{item['id'] for item in roster.targets.values()})

    def test_other_target_quoted_requests_all_and_unknown_codes_are_rejected(self):
        db,roster=self.fixture()
        self.assertIsNone(roster.parse(self.tag(roster,'private_id_never_send'))[1])
        for text in ('他说“帮我@🐾一下”，我只是转述','微信助手，@所有人一下'):
            other=build_mention_roster(db,'room@chatroom','caller','me',text)
            self.assertIsNone(other.parse(self.tag(other))[1])
        self.assertIsNone(roster.parse('[[群聊@:{"target":"notify@all","mode":"requested"}]]你好')[1])
        self.assertNotIn('群聊@',strip_mention_control('正文[[群聊@:{broken'))

    def test_duplicate_names_require_clarification(self):
        db,unused=self.fixture()
        db.get_group_members.return_value.extend([dict(username='a',nick_name='小王'),dict(username='b',nick_name='小王')])
        roster=build_mention_roster(db,'room@chatroom','caller','me','帮我@小王问一下')
        self.assertEqual(roster.request_status,'ambiguous')
        self.assertNotIn('a',{item['id'] for item in roster.targets.values()})

    def test_opener_only_uses_relevant_other_members_and_is_not_a_reply_ping(self):
        db,roster=self.fixture('微信助手，你有什么看法？')
        self.assertIsNotNone(roster.parse(self.tag(roster,mode='opener'))[1])
        self.assertIsNone(roster.parse(self.tag(roster,'caller',mode='opener'))[1])
        self.assertIsNone(roster.parse(self.tag(roster,'private_id_never_send',mode='opener'))[1])
        self.assertFalse(has_mention_request('@🐾你觉得呢',addressed=True))
        self.assertTrue(has_mention_request('帮我@🐾问问',addressed=True))
        self.assertFalse(has_mention_request('你叫什么名字？'))
