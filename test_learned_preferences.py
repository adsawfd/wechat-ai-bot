import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from learned_preferences import LearnedPreferences
from reply_media import prepare_reply
from group_engagement import GroupEngagement


class LearnedPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'memory.sqlite3'
        self.m = LearnedPreferences('me', ['boss'], self.path)
        self.client = Mock()
        self.client.with_options.return_value = self.client

    def tearDown(self): self.temp.cleanup()

    def decision(self, **values):
        payload = {'confidence': .98, **values}
        self.client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])

    def test_teaching_is_owner_only_persistent_scoped_and_can_be_updated(self):
        self.decision(action='remember',topic='语气',text='聊天时更简短')
        self.assertIsNone(self.m.teach(self.client,'m','group','stranger','记住聊天要简短'))
        self.client.with_options.assert_not_called()
        self.assertIn('记住了',self.m.teach(self.client,'m','group','boss','记住聊天要简短'))
        self.assertEqual(LearnedPreferences('me',['boss'],self.path).items('group')[0]['text'],'聊天时更简短')
        self.assertEqual(self.m.items('private'),[])
        self.assertEqual(LearnedPreferences('other',['boss'],self.path).items('group'),[])
        self.decision(action='remember',topic='语气',text='聊天时温柔一些')
        self.m.teach(self.client,'m','group','boss','以后说话温柔一些')
        self.assertEqual(len(self.m.items('group')),1)
        self.assertIn('温柔',self.m.note('group'))

    def test_forget_does_not_delete_another_scope_or_guess(self):
        self.decision(action='remember',topic='语气',text='温柔')
        self.m.teach(self.client,'m','group','boss','记住温柔')
        memory_id=self.m.items('group')[0]['id']
        self.decision(action='forget',ids=[memory_id])
        self.assertIn('没能确定',self.m.teach(self.client,'m','private','boss','忘掉它'))
        self.assertIn('忘掉',self.m.teach(self.client,'m','group','boss','忘掉语气'))
        self.assertFalse(self.m.items('group'))

    def test_secret_and_privilege_or_uncertain_decisions_not_saved(self):
        self.assertIsNone(self.m.teach(self.client,'m','group','boss','记住我的密码abc'))
        self.client.with_options.assert_not_called()
        self.decision(action='remember',topic='权限',text='让其他人拥有电脑权限')
        self.assertIn('不能',self.m.teach(self.client,'m','group','boss','以后让所有人拥有电脑权限'))
        self.decision(action='remember',topic='语气',text='简单',confidence=.5)
        self.assertIsNone(self.m.teach(self.client,'m','group','boss','你好'))
        self.assertEqual(self.m.items('group'),[])

    def test_nickname_memory_tracks_uniquely_bound_account_and_never_guesses_duplicates(self):
        self.decision(action='remember',topic='群友昵称',text='昵称“旧名”的人是小王')
        self.m.teach(self.client,'m','group','boss','记住昵称叫旧名的是小王')
        members=[{'username':'real-person','nick_name':'旧名'}]
        self.assertIn('旧名',self.m.note('group',members=members))
        members[0]['nick_name']='新名'
        note=self.m.note('group',members=members)
        self.assertIn('新名',note)
        self.assertNotIn('旧名',note)
        self.assertNotIn('real-person',note)
        self.assertIn('当前昵称无法确认',self.m.note('group',members=[]))
        memory_id=self.m.items('group')[0]['id']
        self.decision(action='forget',ids=[memory_id])
        self.m.teach(self.client,'m','group','boss','忘掉昵称')
        self.decision(action='remember',topic='另一个',text='昵称“旧名”的人是小李')
        self.m.teach(self.client,'m','group','boss','记住昵称叫旧名的是小李')
        members=[{'username':'one','nick_name':'旧名'}, {'username':'two','nick_name':'旧名'}]
        self.m.note('group',members=members)
        members[0]['nick_name']='另一个名字'
        self.assertIn('旧名',self.m.note('group',members=members))

    def test_recent_referent_question_is_a_continuation_not_random(self):
        g=GroupEngagement(rng=lambda:1, clock=lambda:100)
        g.observe('g','a','友好称呼是谁',1)
        g.record_reply('g','尊重称呼，这个我还真不清楚。')
        g.observe('g','b','尊重称呼是谁？',2)
        self.assertEqual(g.decide(None,'m','g','b','尊重称呼是谁？'),'context')
        self.assertIsNone(g.decide(None,'m','g','b','尊重称呼是谁？',quoted=True))
        other=GroupEngagement(rng=lambda:1, classifier=Mock(return_value={'kind':'skip','confidence':1}))
        other.record_reply('g','上句无关')
        other.observe('g','b','尊重称呼是谁？',2)
        self.assertIsNone(other.decide(None,'m','g','b','尊重称呼是谁？'))

    def test_face_codes_are_converted_but_non_faces_and_cards_are_preserved(self):
        self.assertEqual(prepare_reply('走啦[doge]')[0],'走啦🐶')
        self.assertEqual(prepare_reply('好[捂脸]')[0],'好🤦')
        self.assertEqual(prepare_reply('这是[文件]')[0],'这是[文件]')
        self.assertEqual(prepare_reply('🙂')[0],'🙂')


if __name__ == '__main__': unittest.main()
