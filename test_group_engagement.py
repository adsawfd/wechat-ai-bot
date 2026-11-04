import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch
from group_engagement import GroupEngagement, classify_engagement


class EngagementTests(unittest.TestCase):
    def setUp(self):
        self.now=100
        self.classifier=Mock(return_value={'kind':'question','confidence':0.95})
        self.g=GroupEngagement(classifier=self.classifier, clock=lambda:self.now, rng=lambda:0)
        self.seq=0

    def observe(self,text='有人知道怎么处理吗？',room='room',sender='a'):
        self.seq+=1
        self.g.observe(room,sender,text,self.seq)

    def decide(self,text='有人知道怎么处理吗？',room='room',sender='a'):
        return self.g.decide(None,'model',room,sender,text)

    def test_directed_reply_bypasses_ambient_budget_and_random_gate(self):
        self.observe()
        self.assertEqual(self.decide(),'ambient_question')
        self.g.record_reply('room','我建议先检查网络。')
        self.g.rng=lambda:1
        self.observe('你刚才说的没用',sender='b')
        self.classifier.return_value={'kind':'directed','confidence':0.98}
        self.assertEqual(self.decide('你刚才说的没用',sender='b'),'context')

    def test_same_member_question_follows_confirmed_reply_without_random_gate(self):
        self.observe('我问你个正经的问题',sender='a')
        self.g.record_reply('room','来吧，说正经的。',reply_to='a')
        self.observe('示例丙正经吗？',sender='a')
        self.g.rng=lambda:1
        self.assertEqual(self.decide('示例丙正经吗？',sender='a'),'context')
        self.classifier.assert_not_called()

    def test_followup_is_scoped_to_same_recipient_and_respects_pause_and_quote(self):
        self.observe('我问你个问题',sender='a')
        self.g.record_reply('room','请问',reply_to='a')
        self.observe('他正经吗？',sender='b')
        self.classifier.return_value={'kind':'skip','confidence':1}
        self.assertIsNone(self.decide('他正经吗？',sender='b'))
        self.g.record_reply('room','请问',reply_to='a')
        self.observe('他正经吗？',sender='a')
        self.assertIsNone(self.g.decide(None,'model','room','a','他正经吗？',quoted=True))
        self.g.pause('room','a')
        self.assertIsNone(self.decide('他正经吗？',sender='a'))

    def test_followup_does_not_override_other_addressees_or_stale_replies(self):
        self.observe('我问你个问题',sender='a')
        self.g.record_reply('room','请问',reply_to='a')
        self.seq+=1
        self.g.observe('room','a','他正经吗？',self.seq,addressed_to_others=True)
        self.classifier.return_value={'kind':'skip','confidence':1}
        self.assertIsNone(self.decide('他正经吗？',sender='a'))
        self.g.record_reply('room','请问',reply_to='a')
        self.now += 121
        self.observe('他正经吗？',sender='a')
        self.assertIsNone(self.decide('他正经吗？',sender='a'))

    def test_consecutive_member_followup_requires_recent_bot_and_no_intervening_member(self):
        self.g.record_reply('room','你好')
        self.observe('我今天心情很好',sender='a')
        self.assertTrue(self.g.follows_recent_bot('room','a'))
        self.observe('你呢',sender='a')
        self.assertTrue(self.g.follows_recent_bot('room','a'))
        self.observe('其他人的消息',sender='b')
        self.observe('接下来',sender='a')
        self.assertFalse(self.g.follows_recent_bot('room','a'))

    def test_consecutive_member_followup_respects_pause_and_expiry(self):
        self.g.record_reply('room','你好')
        self.observe('好',sender='a')
        self.g.pause('room','a')
        self.assertFalse(self.g.follows_recent_bot('room','a'))
        self.g.resume('room','a')
        self.now += 121
        self.assertFalse(self.g.follows_recent_bot('room','a'))

    def test_no_recent_bot_no_directed_reply_and_no_cross_room_leak(self):
        self.g.record_reply('other','另一群的消息')
        self.observe()
        self.classifier.return_value={'kind':'directed','confidence':0.99}
        self.assertIsNone(self.decide())
        self.assertNotIn('另一群',str(self.classifier.call_args))

    def test_context_and_ambient_budget_expire_after_a_new_conversation(self):
        self.observe()
        self.assertEqual(self.decide(),'ambient_question')
        self.g.record_reply('room','建议')
        self.now+=181
        self.observe()
        self.classifier.return_value={'kind':'directed','confidence':0.99}
        self.assertIsNone(self.decide())
        self.classifier.return_value={'kind':'question','confidence':0.95}
        self.assertEqual(self.decide(),'ambient_question')

    def test_low_confidence_plain_text_and_trivial_reactions_stay_quiet(self):
        self.observe('到家了')
        self.assertIsNone(self.decide('到家了'))
        self.classifier.assert_not_called()
        self.g.record_reply('room','好好休息')
        self.observe('哈哈哈哈')
        self.assertIsNone(self.decide('哈哈哈哈'))
        self.classifier.assert_not_called()
        self.observe()
        self.classifier.return_value={'kind':'question','confidence':0.4}
        self.assertIsNone(self.decide())

    def test_each_eligible_unmentioned_message_uses_sixty_percent(self):
        self.assertEqual(self.g.probability,.60)
        self.g.rng=lambda:.5999
        for _ in range(3):
            self.observe()
            self.assertEqual(self.decide(),'ambient_question')
        self.g.rng=lambda:.60
        self.observe()
        self.assertIsNone(self.decide())

    def test_open_conversation_can_be_considered_without_keywords(self):
        text='人总是这样，拥有了就抛弃，腻了就背叛。'
        self.observe(text)
        self.classifier.return_value={'kind':'chat','confidence':.95}
        self.assertEqual(self.decide(text),'ambient_chat')
        self.observe(text)
        self.classifier.return_value={'kind':'skip','confidence':.99}
        self.assertIsNone(self.decide(text))
        self.observe(text)
        self.classifier.return_value={'kind':'vent','confidence':.55}
        self.assertEqual(self.decide(text),'ambient_vent')
        self.observe(text)
        self.classifier.return_value={'kind':'vent','confidence':.49}
        self.assertIsNone(self.decide(text))

    def test_new_message_during_judgment_cancels_stale_decision(self):
        self.observe()
        def classify(*args,**kwargs):
            self.observe('别人在问另一个人')
            return {'kind':'question','confidence':0.99}
        self.classifier.side_effect=classify
        self.assertIsNone(self.decide())

    def test_room_memory_is_bounded_and_duplicate_messages_are_ignored(self):
        g=GroupEngagement(max_rooms=2)
        for room in ('one','two','three'):
            for key in range(140):
                self.assertTrue(g.observe(room,'a','test',key))
            self.assertFalse(g.observe(room,'a','test',139))
        self.assertEqual(len(g.rooms),2)
        self.assertEqual(len(g.rooms['three']['messages']),16)
        self.assertEqual(len(g.rooms['three']['seen']),128)

    def test_classifier_receives_anonymous_context_and_rejects_invalid_values(self):
        client=Mock()
        client.with_options.return_value=client
        for payload in ({'kind':'directed','confidence':True}, {'kind':'other','confidence':1},
                        {'kind':'question','confidence':'1'}, {'kind':'question','confidence':1.2}):
            client.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
            self.assertIsNone(classify_engagement(client,'model',[], '怎么处理'))

    def native_fixture(self):
        db=Mock()
        db.get_messages.return_value=[
            dict(local_id=3,sort_seq=3,shard='exact',type='文本',sender_username='alice',content='为什么',create_time=3000),
            dict(local_id=2,sort_seq=2,shard='exact',type='文本',sender_username='me',content='这猫表情比我上班还凝重',create_time=1440),
            dict(local_id=1,sort_seq=1,shard='exact',type='文本',sender_username='alice',content='@小鱼',create_time=1430)]
        return db, SimpleNamespace(local_id=3,sort_seq=3)

    def test_restart_recovers_native_bot_reply_and_why_bypasses_random_gate(self):
        db,msg=self.native_fixture()
        self.g.rng=lambda:1
        with patch('group_engagement.time.time',return_value=3001):
            self.g.recover_context(db,'room',msg,'me')
        self.observe('为什么')
        self.assertEqual(self.decide('为什么'),'context')
        self.classifier.assert_not_called()
        self.assertIn('这猫表情比我上班还凝重',self.g.context_note('room'))
        self.assertIn('original_age_seconds',self.g.context_note('room'))
        db.get_messages.assert_called_once_with('room',limit=40)

    def test_other_persons_reply_breaks_short_followup_and_quote_is_not_forced(self):
        self.g.record_reply('room','先检查一下网络')
        self.observe('为什么',sender='b')
        self.assertEqual(self.decide('为什么',sender='b'),'context')
        self.observe('我在说另一个人',sender='c')
        self.observe('为什么',sender='b')
        self.classifier.return_value={'kind':'skip','confidence':1}
        self.assertIsNone(self.decide('为什么',sender='b'))
        self.g.record_reply('room','上一句')
        self.observe('什么意思')
        self.assertIsNone(self.g.decide(None,'model','room','a','什么意思',quoted=True))

    def test_recovery_rejects_ambiguous_current_old_messages_and_future_rows(self):
        db,msg=self.native_fixture()
        db.get_messages.return_value.append(dict(db.get_messages.return_value[0]))
        with patch('group_engagement.time.time',return_value=3001):
            self.g.recover_context(db,'room',msg,'me')
        self.assertEqual(len(self.g.rooms['room']['messages']),0)
        db,msg=self.native_fixture()
        db.get_messages.return_value.append(dict(local_id=4,sort_seq=4,type='文本',sender_username='me',content='这条是之后的消息',create_time=3001))
        with patch('group_engagement.time.time',return_value=3001):
            self.g.recover_context(db,'room',msg,'me')
        self.assertNotIn('之后的消息',self.g.context_note('room'))
        other=GroupEngagement()
        with patch('group_engagement.time.time',return_value=200000):
            other.recover_context(db,'other',msg,'me')
        self.assertEqual(len(other.rooms['other']['messages']),0)

    def test_recovery_skips_sensitive_text_and_never_transmits_raw_cards(self):
        db,msg=self.native_fixture()
        db.get_messages.return_value[1]['content']='验证码123456'
        db.get_messages.return_value[2].update(type='文件/链接/卡片',content='<secret token="do-not-send"/>')
        with patch('group_engagement.time.time',return_value=3001):
            self.g.recover_context(db,'room',msg,'me')
        text=str(list(self.g.rooms['room']['messages']))
        self.assertNotIn('123456',text)
        self.assertNotIn('do-not-send',text)

    def test_manual_stop_still_blocks_immediate_followup(self):
        self.g.record_reply('room','上文')
        self.g.pause('room','a')
        self.observe('为什么')
        self.assertIsNone(self.decide('为什么'))

    def test_light_pat_can_stand_alone_without_prior_bot_reply_or_random_gate(self):
        self.g.rng=lambda:1
        self.observe('这周一直在准备考试',sender='b')
        self.observe('终于通过了，刚刚查到成绩')
        self.classifier.return_value={'kind':'pat','confidence':.96}
        self.assertEqual(self.g.decide(None,'model','room','a','终于通过了，刚刚查到成绩',allow_pat=True),'ambient_pat')
        self.assertTrue(self.classifier.call_args.kwargs['allow_pat'])
        self.assertIsNone(self.g.decide(None,'model','room','a','终于通过了，刚刚查到成绩',allow_pat=False))
        self.assertIsNone(self.g.decide(None,'model','room','a','终于通过了，刚刚查到成绩',allow_pat=True,quoted=True))

    def test_pat_rejects_low_confidence_stale_and_trivial_context(self):
        self.observe('大家在准备')
        self.observe('我做好啦！')
        self.classifier.return_value={'kind':'pat','confidence':.84}
        self.assertIsNone(self.g.decide(None,'model','room','a','我做好啦！',allow_pat=True))

    def test_mention_openers_are_bounded_without_limiting_explicit_requests(self):
        self.observe('开场')
        self.assertTrue(self.g.reserve_mention('room',1))
        self.assertFalse(self.g.reserve_mention('room',1,requested=True))
        self.observe('下一句')
        self.assertFalse(self.g.reserve_mention('room',2))
        self.assertTrue(self.g.reserve_mention('room',2,requested=True))
        for _ in range(5): self.observe('普通闲聊')
        self.assertTrue(self.g.reserve_mention('room',7))
        for _ in range(6): self.observe('普通闲聊')
        self.assertFalse(self.g.reserve_mention('room',13))
        self.observe('哈哈哈哈')
        self.classifier.reset_mock()
        self.assertIsNone(self.g.decide(None,'model','room','a','哈哈哈哈',allow_pat=True))
        self.classifier.assert_not_called()
        self.observe('我做好啦！')
        def stale(*args,**kwargs):
            self.observe('现在在说严肃的事')
            return {'kind':'pat','confidence':1}
        self.classifier.side_effect=stale
        self.assertIsNone(self.g.decide(None,'model','room','a','我做好啦！',allow_pat=True))


if __name__=='__main__':
    unittest.main()
