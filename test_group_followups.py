import ast
import os
import re
import unittest
from collections import defaultdict, deque
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock
from group_engagement import GroupEngagement, delivery_succeeded
from group_silence import GroupSilence
from token_usage import is_usage_query, UsageQueries
import tempfile
from proactive_pats import extract_pat_intent, ProactivePats
from reply_identity import ReplyIdentity
from respectful_contact import RespectfulContacts
from group_identity_context import referenced_member_context
from group_profiles import GroupProfiles
from identity_learning import IdentityMemory
import json
from mention_planner import build_mention_roster,strip_mention_control,has_mention_request,MentionPlan
from voice_audio import wants_voice, spoken_text, VOICE_STYLE
from voice_director import VoiceDirector, DirectedReply, VOICE_DIRECTOR_STYLE


class FollowupTests(unittest.TestCase):
    def setUp(self):
        path = Path(os.environ.get('WECHAT_BOT_TEST_SOURCE', str(Path(__file__).with_name('bot.py'))))
        tree = ast.parse(path.read_text(encoding='utf-8'))
        module = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'on_message'], type_ignores=[])
        self.text_type = type('FriendTextMessage', (), {})
        self.generate = Mock(return_value='自然回复')
        self.scope = dict(FriendTextMessage=self.text_type, get_pat_sender=Mock(return_value='alice'), wx=SimpleNamespace(_db=None), self_id='me', GROUPS=set(), PRIVATE_MODE='all', TEST_FRIEND='', BASE_STYLE='', GROUP_STYLE='', PRIVATE_STYLE='', lock=Lock(), group_followups={}, seen=set(), seen_order=deque(), histories=defaultdict(lambda: deque(maxlen=8)), re=re, AUTO_SEND=True, COMPUTER_CONTROL=True, ai=None, MODEL='test', get_at_user_ids=lambda msg, chat: msg.at_ids, generate_answer=self.generate)
        self.scope.update(generate_pat_reply=Mock(return_value='在呢，怎么啦？'), nickname_trigger=SimpleNamespace(matches=lambda text: '大肥鱼1.0' in text, reference_hint=Mock(return_value=None)))
        self.scope['generate_sticker_reply'] = Mock(return_value='[[表情包:得意|接招吧]]')
        self.scope['VISION_UPLOAD'] = True
        self.scope.update(wants_voice=wants_voice, spoken_text=spoken_text, VOICE_STYLE=VOICE_STYLE,
                          VOICE_ENABLED=True, send_native_voice=Mock(return_value={'status':'成功'}))
        self.scope['voice_director'] = VoiceDirector()
        self.scope['reply_identity'] = ReplyIdentity()
        self.scope['respectful_contacts'] = RespectfulContacts()
        self.scope['group_profiles'] = GroupProfiles()
        self.scope['identity_memory'] = Mock(teach=Mock(return_value=None), question=Mock(return_value=(False,None,None)),
            take_pending=Mock(return_value=(False,None,None)),remember_pending=Mock())
        self.scope['referenced_member_context'] = referenced_member_context
        self.scope['learned_preferences'] = Mock(teach=Mock(return_value=None), note=Mock(return_value=''))
        silence_dir=tempfile.TemporaryDirectory();self.addCleanup(silence_dir.cleanup)
        self.silence=GroupSilence('me',(),Path(silence_dir.name)/'silence.sqlite3')
        self.scope['group_silence']=self.silence
        self.scope['group_delivery']=lambda room,token=None:self.silence.delivery(room,token)
        self.scope['remote_computer'] = Mock(route=Mock(return_value=None))
        self.scope['is_usage_query'] = is_usage_query
        self.scope['usage_queries'] = UsageQueries()
        self.scope['usage_ledger'] = Mock(report=Mock(return_value='测试用量报告'))
        self.scope.update(build_mention_roster=build_mention_roster,strip_mention_control=strip_mention_control,
                          has_mention_request=has_mention_request,MentionPlan=MentionPlan,send_group_mention=Mock(return_value={'status':'成功'}))
        self.scope.update(singing_available=Mock(return_value=False), singing_note=Mock(return_value=''),
                          send_singing_reply=Mock(return_value={'status':'成功'}))
        self.classifier = Mock(return_value=None)
        self.engagement = GroupEngagement(classifier=self.classifier, rng=lambda: 0)
        self.scope.update(group_engagement=self.engagement, delivery_succeeded=delivery_succeeded)
        self.scope.update(proactive_pats=Mock(choose=Mock(return_value=False),can_consider=Mock(return_value=False)), PAT_STYLE='',
                          extract_pat_intent=extract_pat_intent, send_native_pat=Mock(return_value={'status':'成功'}))
        self.scope['send_group_reply'] = lambda chat, text, sender, db: chat.SendMsg(text)
        self.scope.update(idle_taunts=Mock(), sent_ok=lambda result: result is True)
        self.scope.update(FriendEmojiMessage=type('FriendEmojiMessage', (), {}), MEDIA_STYLE='', prepare_reply=lambda value: (value, None), send_image_reply=Mock(return_value=True))
        self.scope.update(FriendImageMessage=type('FriendImageMessage', (), {}), FriendQuoteMessage=type('FriendQuoteMessage', (), {}),
                          read_quote=Mock(return_value=None), quote_context=lambda quote: '\n引用原文：'+quote['text'] if quote else '',
                          incoming_images=SimpleNamespace(remember=Mock(), for_message=Mock(return_value=([], ''))))
        self.scope['incoming_images'].forget = Mock()
        self.scope.update(FriendVideoMessage=type('FriendVideoMessage', (), {}),
                          incoming_videos=SimpleNamespace(remember=Mock(), forget=Mock(), for_message=Mock(return_value=None)))
        exec(compile(module, str(path), 'exec'), self.scope)
        self.chat = SimpleNamespace(who='room@chatroom', nickname='测试群', SendMsg=Mock(return_value=True))
        self.seq = 0

    def deliver(self, text='你好', sender='alice', at_ids=None, unknown=False):
        self.seq += 1
        msg = self.text_type()
        msg.content, msg.attr, msg.sender_wxid, msg.sender = text, 'friend', sender, sender
        msg.local_id = msg.sort_seq = self.seq
        msg.at_ids = None if unknown else (at_ids or set())
        with redirect_stdout(StringIO()):
            self.scope['on_message'](msg, self.chat)
        return msg

    def test_conversation_start_continue_stop_restart(self):
        self.deliver()
        self.assertEqual(self.chat.SendMsg.call_count, 0)
        self.deliver(at_ids={'me'})
        self.deliver('然后呢？')
        self.assertEqual(self.chat.SendMsg.call_count, 2)
        previous = self.generate.call_args.args[3]
        self.assertEqual(len(previous), 2)
        self.deliver('/结束')
        self.deliver('还会回吗？')
        self.assertEqual(self.chat.SendMsg.call_count, 2)
        self.deliver(at_ids={'me'})
        self.assertEqual(self.chat.SendMsg.call_count, 3)
        self.assertEqual(self.generate.call_args.args[3], [])

    def test_respected_member_continues_after_manual_bot_message(self):
        self.scope['respectful_contacts'] = RespectfulContacts(['alice'])
        self.engagement.record_reply('room@chatroom', '最近怎样？')
        self.deliver('我今天心情很好', sender='alice')
        self.assertEqual(self.chat.SendMsg.call_count, 1)
        self.assertIn('不顶嘴', self.generate.call_args.args[2])

    def test_other_member_can_ask_about_term_in_bot_reply(self):
        self.engagement.record_reply('room@chatroom', '尊重称呼，这个我不清楚。')
        self.deliver('尊重称呼是谁？', sender='bob')
        self.assertEqual(self.chat.SendMsg.call_count, 1)

    def test_same_member_followup_after_ambient_reply_is_not_randomly_skipped(self):
        self.engagement.observe('room@chatroom','alice','我问你个正经的问题',100)
        self.engagement.record_reply('room@chatroom','来吧，说正经的。',reply_to='alice')
        self.engagement.rng=lambda:1
        self.deliver('示例丙正经吗？',sender='alice')
        self.chat.SendMsg.assert_called_once_with('自然回复')
        self.classifier.assert_not_called()

    def test_identity_question_directly_pings_unique_bound_member(self):
        self.scope['group_profiles'] = GroupProfiles('room@chatroom',[
            {'member_id':'lele','group_nickname':'群昵称甲','real_name':'示例丁','title':'友好称呼'}])
        db=Mock();db.get_group_members.return_value=[{'username':'me','nick_name':'微信助手'},
                                                     {'username':'lele','nick_name':'MemberD'}]
        self.scope['wx'] = SimpleNamespace(_db=db)
        self.engagement.rng=lambda:1
        self.deliver('示例丁是谁？',sender='alice')
        self.scope['send_group_mention'].assert_called_once_with(self.chat,'自然回复','lele',db,member_group_name='群昵称甲')
        self.classifier.assert_not_called()

    def test_ambiguous_identity_question_never_pings_wrong_member(self):
        self.scope['group_profiles'] = GroupProfiles('room@chatroom',[
            {'member_id':'a','group_nickname':'成员乙','real_name':'示例甲'},
            {'member_id':'b','group_nickname':'SameNickname','real_name':'示例乙'}])
        db=Mock();db.get_group_members.return_value=[{'username':'a','nick_name':'SameNickname'},
                                                     {'username':'b','nick_name':'ExampleMember'}]
        self.scope['wx'] = SimpleNamespace(_db=db)
        self.deliver('SameNickname是谁？',sender='alice')
        self.scope['send_group_mention'].assert_not_called()
        self.assertIn('匹配多个',self.generate.call_args.args[2])

    def test_identity_question_respects_member_stop_request(self):
        self.scope['group_profiles'] = GroupProfiles('room@chatroom',[
            {'member_id':'lele','group_nickname':'群昵称甲','real_name':'示例丁','title':'友好称呼'}])
        db=Mock();db.get_group_members.return_value=[{'username':'lele','nick_name':'MemberD'}]
        self.scope['wx'] = SimpleNamespace(_db=db)
        self.engagement.pause('room@chatroom','alice')
        self.deliver('示例丁是谁？',sender='alice')
        self.scope['send_group_mention'].assert_not_called()
        self.generate.assert_not_called()

    def test_identity_learning_and_two_question_forms_use_bound_account(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.scope['identity_memory']=IdentityMemory('me',{'boss'},Path(folder.name)/'id.sqlite3')
        self.scope['reply_identity']=ReplyIdentity(['boss'])
        self.scope['VOICE_ENABLED']=False
        self.scope['nickname_trigger']=SimpleNamespace(matches=lambda text:'微信助手' in text, reference_hint=Mock(return_value=None),name='微信助手',aliases=[])
        db=Mock();db.get_group_members.return_value=[{'username':'me','nick_name':'微信助手'},
            {'username':'boss','nick_name':'🐾'},{'username':'target','nick_name':'：)'}]
        self.scope['wx']=SimpleNamespace(_db=db)
        ai=Mock();ai.with_options.return_value=ai
        ai.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(
            {'action':'remember','subject':'这个人','name':'ExampleName','confidence':.98})))])
        self.scope['ai']=ai
        self.deliver('@：) @微信助手 我@这个人是ExampleName，记住了',sender='boss',at_ids={'me','target'})
        self.chat.SendMsg.assert_called_once_with('好的老板，记住了：这个人是ExampleName。')
        self.chat.SendMsg.reset_mock()
        self.deliver('ExampleName是谁',sender='boss')
        self.scope['send_group_mention'].assert_called_once_with(self.chat,'这是ExampleName。','target',db)
        self.scope['send_group_mention'].reset_mock()
        self.deliver('@：) 这个人是谁',sender='boss',at_ids={'target'})
        self.scope['send_group_mention'].assert_not_called()
        self.deliver('@微信助手',sender='boss',at_ids={'me'})
        self.scope['send_group_mention'].assert_called_once_with(self.chat,'这是ExampleName。','target',db)

    def test_learning_confirmation_uses_saved_result_without_model_generated_claim(self):
        self.scope['reply_identity'] = ReplyIdentity(['alice'])
        self.scope['learned_preferences'].teach.return_value = '记住了：聊天简短一点'
        self.deliver('记住以后聊天简短一点', sender='alice', at_ids={'me'})
        self.chat.SendMsg.assert_called_once_with('好的老板，记住了：聊天简短一点')
        self.generate.assert_not_called()

    def test_private_learning_takes_precedence_over_active_computer_task(self):
        self.chat.who, self.chat.nickname = 'alice', 'alice'
        self.scope['reply_identity'] = ReplyIdentity(['alice'])
        self.scope['learned_preferences'].teach.return_value = '记住了：聊天简短一点'
        self.scope['remote_computer'].route.return_value = 'active task'
        self.deliver('以后聊天简短一点', sender='alice')
        self.scope['remote_computer'].route.assert_not_called()
        self.chat.SendMsg.assert_called_once_with('好的老板，记住了：聊天简短一点')

    def test_other_member_not_triggered_by_respected_member_rule(self):
        self.scope['respectful_contacts'] = RespectfulContacts(['alice'])
        self.engagement.record_reply('room@chatroom', '最近怎样？')
        self.deliver('我今天心情很好', sender='bob')
        self.assertEqual(self.chat.SendMsg.call_count, 0)

    def test_other_members_groups_and_mentions(self):
        self.deliver(at_ids={'me'})
        self.deliver(sender='bob')
        self.deliver(at_ids={'someone_else'})
        self.deliver(at_ids={'notify@all'})
        self.deliver(unknown=True)
        self.deliver(sender='me')
        self.assertEqual(self.chat.SendMsg.call_count, 1)
        self.chat.who = 'another@chatroom'
        self.deliver()
        self.assertEqual(self.chat.SendMsg.call_count, 1)
        self.deliver(sender='bob', at_ids={'me'})
        self.assertEqual(self.generate.call_args.args[3], [])

    def test_duplicate_does_not_reply_twice(self):
        msg = self.deliver(at_ids={'me'})
        with redirect_stdout(StringIO()):
            self.scope['on_message'](msg, self.chat)
        self.assertEqual(self.chat.SendMsg.call_count, 1)

    def test_pat_does_not_activate_followups(self):
        msg = SimpleNamespace(local_id=20, sort_seq=20)
        with redirect_stdout(StringIO()):
            self.scope['on_message'](msg, self.chat)
        self.assertEqual(self.chat.SendMsg.call_count, 1)
        self.assertEqual(self.scope['group_followups'], {})
        self.deliver()
        self.assertEqual(self.chat.SendMsg.call_count, 1)

    def test_preview_does_not_send(self):
        self.scope['AUTO_SEND'] = False
        self.deliver(at_ids={'me'})
        self.deliver()
        self.assertEqual(self.generate.call_count, 2)
        self.chat.SendMsg.assert_not_called()
        self.scope['idle_taunts'].arm.assert_not_called()

    def test_voice_request_uses_native_sender_and_never_text_or_sticker(self):
        self.deliver('大肥鱼1.0用语音回复我', at_ids={'me'})
        self.scope['send_native_voice'].assert_called_once_with(self.chat, '自然回复', None, 'me',
                                                              profile={'tone':'casual','strength':.45,'gender':'male'})
        self.chat.SendMsg.assert_not_called()
        self.scope['send_image_reply'].assert_not_called()
        self.scope['proactive_pats'].choose.assert_not_called()
        self.assertTrue(self.generate.call_args.kwargs['adaptive_voice'])
        self.assertIn('当前声音偏好', self.generate.call_args.args[2])

    def test_context_can_choose_voice_without_voice_keyword(self):
        self.generate.return_value = DirectedReply('哈哈，这波可算让我逮到了。', dict(mode='voice',tone='playful',strength=.7))
        self.deliver('大肥鱼1.0，轮到你发表三秒获奖感言了')
        self.scope['send_native_voice'].assert_called_once()
        self.assertEqual(self.scope['send_native_voice'].call_args.kwargs['profile']['tone'], 'playful')
        self.chat.SendMsg.assert_not_called()
        self.assertNotIn('声音:',self.scope['send_native_voice'].call_args.args[1])
        self.assertIn('voice',self.scope['voice_director'].note(('room@chatroom','alice')))

    def test_voice_failure_does_not_fallback_and_preview_never_records(self):
        self.scope['send_native_voice'].return_value = {'status':'失败'}
        self.deliver('发条语音', at_ids={'me'})
        self.chat.SendMsg.assert_not_called()
        self.scope['send_image_reply'].assert_not_called()
        self.scope['AUTO_SEND'] = False
        self.scope['send_native_voice'].reset_mock()
        self.deliver('用语音回复我', at_ids={'me'})
        self.scope['send_native_voice'].assert_not_called()

    def test_replies_do_not_schedule_unanswered_message_taunts(self):
        self.deliver(at_ids={'me'})
        self.scope['idle_taunts'].arm.assert_not_called()
        self.chat.SendMsg.return_value = False
        self.deliver('继续')
        self.scope['idle_taunts'].arm.assert_not_called()
        self.chat.who = 'private'
        self.chat.SendMsg.return_value = True
        self.deliver('私聊')
        self.scope['idle_taunts'].arm.assert_not_called()

    def test_nickname_starts_followups_without_at(self):
        self.deliver('大肥鱼1.0你在干什么')
        self.deliver('接着聊')
        self.assertEqual(self.chat.SendMsg.call_count, 2)
        self.deliver('/结束')
        self.deliver('接着聊')
        self.assertEqual(self.chat.SendMsg.call_count, 2)

    def test_nickname_does_not_override_addressing_someone_else(self):
        self.deliver('大肥鱼1.0', at_ids={'someone_else'})
        self.chat.SendMsg.assert_not_called()

    def test_native_emoji_starts_battle_and_each_human_sticker_gets_one_reply(self):
        self.scope['incoming_images'].for_message.return_value=([{'type':'image_url'}], '实际表情画面')
        self.scope['prepare_reply'] = lambda value: ('[表情包：接招吧]', 'reaction.png')
        emoji = self.scope['FriendEmojiMessage']()
        emoji.attr, emoji.sender_wxid = 'friend', 'alice'
        emoji.local_id = emoji.sort_seq = 100
        with redirect_stdout(StringIO()):
            self.scope['on_message'](emoji, self.chat)
            self.scope['on_message'](emoji, self.chat)
        self.assertEqual(self.scope['send_image_reply'].call_count,1)
        emoji.local_id = emoji.sort_seq = 101
        with redirect_stdout(StringIO()):
            self.scope['on_message'](emoji, self.chat)
        self.assertEqual(self.scope['send_image_reply'].call_count,2)
        self.scope['idle_taunts'].arm.assert_not_called()
        self.assertEqual(self.scope['group_followups'],{})
        emoji.sender_wxid='me'
        emoji.local_id = emoji.sort_seq = 102
        with redirect_stdout(StringIO()):
            self.scope['on_message'](emoji, self.chat)
        self.assertEqual(self.scope['send_image_reply'].call_count,2)
        self.generate.assert_not_called()

    def test_image_reply_goes_to_file_sender(self):
        self.scope['prepare_reply'] = lambda value: ('[表情包：妙啊]', 'safe_image.png')
        self.deliver(at_ids={'me'})
        self.scope['send_image_reply'].assert_called_once_with(self.chat, 'safe_image.png')
        self.chat.SendMsg.assert_not_called()

    def test_real_media_never_leaves_computer_without_explicit_upload_switch(self):
        self.scope['VISION_UPLOAD'] = False
        self.scope['incoming_images'].for_message.return_value=([{'type':'image_url'}], '本次画面')
        emoji=self.scope['FriendEmojiMessage']()
        emoji.attr,emoji.sender_wxid,emoji.local_id,emoji.sort_seq='friend','alice',100,100
        with redirect_stdout(StringIO()):
            self.scope['on_message'](emoji,self.chat)
        self.scope['generate_sticker_reply'].assert_not_called()
        self.generate.assert_not_called()
        self.scope['send_image_reply'].assert_not_called()
        self.deliver(at_ids={'me'})
        self.generate.assert_called_once()
        self.assertNotIn('images',self.generate.call_args.kwargs)

    def test_incoming_image_is_remembered_without_starting_uninvited_chat(self):
        msg = self.scope['FriendImageMessage']()
        msg.attr, msg.sender_wxid, msg.local_id, msg.sort_seq = 'friend', 'alice', 100, 100
        with redirect_stdout(StringIO()):
            self.scope['on_message'](msg, self.chat)
        self.scope['incoming_images'].remember.assert_called_once_with(msg, self.chat.who, 'alice')
        self.generate.assert_not_called()
        self.scope['get_pat_sender'].assert_not_called()

    def test_active_group_image_reaches_vision_instead_of_pat_filter(self):
        self.deliver(at_ids={'me'})
        block={'type':'image_url','image_url':{'url':'data:image/jpeg;base64,TEST'}}
        self.scope['incoming_images'].for_message.return_value=([block], '本次图片')
        msg = self.scope['FriendImageMessage']()
        msg.attr, msg.sender_wxid, msg.local_id, msg.sort_seq = 'friend', 'alice', 100, 100
        with redirect_stdout(StringIO()):
            self.scope['on_message'](msg, self.chat)
        self.assertEqual(self.generate.call_args.kwargs['images'], [block])
        self.scope['get_pat_sender'].assert_not_called()
        self.assertNotIn('data:image', str(list(self.scope['histories'].values())))

    def test_video_is_remembered_then_answered_during_conversation(self):
        msg = self.scope['FriendVideoMessage']()
        msg.attr, msg.sender_wxid, msg.local_id, msg.sort_seq = 'friend', 'alice', 100, 100
        with redirect_stdout(StringIO()):
            self.scope['on_message'](msg, self.chat)
        self.scope['incoming_videos'].remember.assert_called_once_with(msg, self.chat.who, 'alice')
        self.scope['get_pat_sender'].assert_not_called()
        self.generate.assert_not_called()
        self.deliver(at_ids={'me'})
        self.scope['incoming_videos'].for_message.return_value = SimpleNamespace(blocks=[{'type':'image_url'}], note='实际视频画面和对白')
        msg.local_id = msg.sort_seq = 101
        with redirect_stdout(StringIO()):
            self.scope['on_message'](msg, self.chat)
        self.assertEqual(self.generate.call_args.kwargs['images'], [{'type':'image_url'}])
        self.assertIn('实际视频画面和对白', self.generate.call_args.args[4])
        self.assertTrue(self.scope['incoming_videos'].for_message.call_args.kwargs['is_video'])
        self.scope['incoming_images'].forget.assert_called_with(self.chat.who, 'alice')

    def test_video_failure_does_not_attach_unrelated_picture(self):
        self.scope['incoming_videos'].for_message.return_value = SimpleNamespace(blocks=[], note='视频未下载，不能猜测')
        self.deliver('大肥鱼1.0看看刚才的视频')
        self.scope['incoming_images'].for_message.assert_not_called()
        self.assertNotIn('images', self.generate.call_args.kwargs)
        self.assertIn('视频未下载', self.generate.call_args.args[4])

    def test_video_visual_opt_out_keeps_local_dialogue(self):
        self.scope['VISION_UPLOAD'] = False
        self.scope['incoming_videos'].for_message.return_value = SimpleNamespace(blocks=[], note='本机转写的对白')
        self.deliver('大肥鱼1.0视频里在说什么')
        self.assertFalse(self.scope['incoming_videos'].for_message.call_args.kwargs['allow_frames'])
        self.assertIn('本机转写', self.generate.call_args.args[4])
        self.assertNotIn('images', self.generate.call_args.kwargs)

    def test_short_followup_after_restart_recovers_native_group_context(self):
        from unittest.mock import patch
        db=Mock()
        db.get_messages.return_value=[
            dict(local_id=1,sort_seq=1,type='文本',sender_username='alice',content='为什么',create_time=3000),
            dict(local_id=0,sort_seq=0,type='文本',sender_username='me',content='这猫表情比我上班还凝重',create_time=1440)]
        self.scope['wx']._db=db
        self.engagement.rng=lambda:1
        with patch('group_engagement.time.time',return_value=3001):
            self.deliver('为什么')
        self.chat.SendMsg.assert_called_once_with('自然回复')
        self.assertIn('这猫表情比我上班还凝重',self.generate.call_args.args[4])
        self.classifier.assert_not_called()

    def test_singing_routes_to_song_generator_and_never_to_tts(self):
        self.scope['singing_available'].return_value=True
        self.generate.return_value=DirectedReply('来一小段。',dict(mode='sing',request='sing',
            song=dict(kind='cover',title='测试曲名',style='轻松清唱')))
        self.deliver('唱一小段测试曲名',at_ids={'me'})
        self.scope['send_singing_reply'].assert_called_once()
        self.scope['send_native_voice'].assert_not_called()
        self.chat.SendMsg.assert_not_called()
        self.scope['send_native_pat'].assert_not_called()

    def test_singing_preview_unconfigured_and_failure_never_read_lyrics(self):
        self.generate.return_value=DirectedReply('来一小段。',dict(mode='sing',request='sing',
            song=dict(kind='improv',lyrics='原创两句短词',style='欢快')))
        self.deliver('唱两句',at_ids={'me'})
        self.assertIn('不能真唱',self.chat.SendMsg.call_args.args[0])
        self.scope['send_native_voice'].assert_not_called()
        self.scope['send_singing_reply'].assert_not_called()
        self.scope['singing_available'].return_value=True
        self.scope['AUTO_SEND']=False
        self.deliver('唱两句')
        self.scope['send_singing_reply'].assert_not_called()
        self.scope['AUTO_SEND']=True
        self.scope['send_singing_reply'].return_value={'status':'未生成'}
        self.deliver('唱两句')
        self.assertIn('没唱出来',self.chat.SendMsg.call_args.args[0])
        self.scope['send_native_voice'].assert_not_called()
        self.chat.SendMsg.reset_mock()
        self.scope['send_singing_reply'].return_value={'status':'未确认'}
        self.deliver('再唱两句')
        self.chat.SendMsg.assert_not_called()

    def test_native_quote_of_bot_activates_reply_and_includes_original(self):
        quote=dict(question='具体是什么意思',text='真正被引用的原文',sender_id='me')
        self.scope['read_quote'].return_value=quote
        msg=SimpleNamespace(attr='friend',sender_wxid='alice',local_id=100,sort_seq=100,at_ids=set())
        with redirect_stdout(StringIO()):
            self.scope['on_message'](msg,self.chat)
        self.assertIn('真正被引用的原文',self.generate.call_args.args[4])
        self.scope['get_pat_sender'].assert_not_called()

    def test_name_inside_other_person_quote_is_not_a_call_to_bot(self):
        self.scope['read_quote'].return_value=dict(question='你怎么看',text='大肥鱼1.0',sender_id='someone_else')
        msg=SimpleNamespace(attr='friend',sender_wxid='alice',local_id=100,sort_seq=100,at_ids=set())
        with redirect_stdout(StringIO()):
            self.scope['on_message'](msg,self.chat)
        self.generate.assert_not_called()

    def test_other_member_can_reply_to_bot_without_mention_or_previous_membership(self):
        self.deliver('大肥鱼1.0你怎么看这件事')
        self.classifier.return_value={'kind':'directed','confidence':0.98}
        self.deliver('这个说法明显不成立',sender='bob')
        self.assertEqual(self.chat.SendMsg.call_count,2)
        current=self.generate.call_args.args[4]
        self.assertIn('当前群最近的发言',current)
        self.assertIn('你怎么看这件事',current)
        self.assertIn('自然回复',current)
        self.assertNotIn((self.chat.who,'bob'),self.scope['group_followups'])

    def test_ambient_question_and_vent_are_selective_without_activating_forever(self):
        self.classifier.return_value={'kind':'question','confidence':0.95}
        self.deliver('有没有人知道这个怎么修？')
        self.assertEqual(self.chat.SendMsg.call_count,1)
        self.assertEqual(self.scope['group_followups'],{})
        self.classifier.return_value={'kind':'vent','confidence':0.95}
        self.deliver('又加班，真的无语',sender='bob')
        self.assertEqual(self.chat.SendMsg.call_count,2)
        self.assertEqual(self.scope['group_followups'],{})
        self.deliver('大肥鱼1.0你说句话',sender='bob')
        self.assertEqual(self.chat.SendMsg.call_count,3)

    def test_explicit_other_mentions_duplicates_and_sensitive_text_never_reach_judgment(self):
        self.classifier.return_value={'kind':'question','confidence':0.95}
        self.deliver('你这个问题怎么解决？',at_ids={'someone_else'})
        self.deliver('验证码怎么收不到？')
        self.classifier.assert_not_called()
        self.chat.SendMsg.assert_not_called()
        msg=self.deliver('有没有人知道这个怎么修？')
        calls=self.classifier.call_count
        with redirect_stdout(StringIO()):
            self.scope['on_message'](msg,self.chat)
        self.assertEqual(self.classifier.call_count,calls)
        self.assertEqual(self.chat.SendMsg.call_count,1)

    def test_stop_command_also_pauses_context_and_optional_joining(self):
        self.deliver(at_ids={'me'})
        self.deliver('/结束')
        self.classifier.return_value={'kind':'directed','confidence':0.98}
        self.deliver('你刚才说的不对吧？')
        self.assertEqual(self.chat.SendMsg.call_count,1)
        self.deliver('大肥鱼1.0重新聊')
        self.assertEqual(self.chat.SendMsg.call_count,2)

    def test_fat_fish_short_name_is_semantically_recognized_without_recent_reply(self):
        self.scope['nickname_trigger'].reference_hint.return_value={'nickname':'大肥鱼1.0','aliases':['胖鱼']}
        self.classifier.return_value={'kind':'mentioned','confidence':0.98}
        self.deliver('这胖鱼还会拍一拍',sender='bob')
        self.assertEqual(self.chat.SendMsg.call_count,1)
        self.assertNotIn((self.chat.who,'bob'),self.scope['group_followups'])

    def test_pat_marker_is_removed_and_action_targets_only_current_sender(self):
        self.generate.return_value='来，接一下。[[拍一拍]]'
        self.scope['proactive_pats'].choose.return_value=True
        msg=self.deliver('拍我一下',at_ids={'me'})
        self.chat.SendMsg.assert_called_once_with('来，接一下。')
        self.scope['send_native_pat'].assert_called_once_with(self.chat,msg,'alice',None,'me')
        self.assertNotIn('[[拍一拍]]',str(list(self.scope['histories'].values())))

    def test_pat_never_runs_in_preview_or_after_failed_send(self):
        self.generate.return_value='接住。[[拍一拍]]'
        self.scope['proactive_pats'].choose.return_value=True
        self.scope['AUTO_SEND']=False
        self.deliver(at_ids={'me'})
        self.scope['send_native_pat'].assert_not_called()
        self.scope['AUTO_SEND']=True
        self.chat.SendMsg.return_value=False
        self.deliver()
        self.scope['send_native_pat'].assert_not_called()

    def test_received_pat_does_not_create_an_automatic_pat_loop(self):
        self.scope['proactive_pats']=ProactivePats()
        msg=SimpleNamespace(local_id=100,sort_seq=100)
        with redirect_stdout(StringIO()):
            self.scope['on_message'](msg,self.chat)
        self.scope['send_native_pat'].assert_not_called()

    def test_atmosphere_can_pat_without_mention_or_generated_reply(self):
        self.scope['proactive_pats']=ProactivePats()
        self.classifier.return_value={'kind':'skip','confidence':1}
        self.deliver('这周一直在准备考试',sender='bob')
        self.classifier.return_value={'kind':'pat','confidence':.98}
        msg=self.deliver('终于通过了，刚才查到成绩了！',sender='alice')
        self.scope['send_native_pat'].assert_called_once_with(self.chat,msg,'alice',None,'me')
        self.generate.assert_not_called()
        self.chat.SendMsg.assert_not_called()
        self.assertEqual(self.scope['group_followups'],{})
        self.assertEqual(dict(self.scope['histories']),{})
        self.assertIn('拍了拍',self.engagement.context_note(self.chat.who))
        with redirect_stdout(StringIO()):
            self.scope['on_message'](msg,self.chat)
        self.assertEqual(self.scope['send_native_pat'].call_count,1)

    def test_ambient_pat_respects_opt_out_stop_preview_and_group_filter(self):
        self.scope['proactive_pats']=ProactivePats()
        self.classifier.return_value={'kind':'skip','confidence':1}
        self.deliver('今天在努力',sender='bob')
        self.classifier.return_value={'kind':'pat','confidence':.98}
        self.scope['AUTO_SEND']=False
        self.deliver('总算完成了一个小目标！')
        self.scope['AUTO_SEND']=True
        self.deliver('别拍我')
        self.deliver('太棒了，今天终于搞定啦！')
        self.deliver('/结束',sender='bob')
        self.deliver('我也做完啦！',sender='bob')
        self.scope['GROUPS']={'另一个群'}
        self.deliver('成功了！',sender='charlie')
        self.scope['send_native_pat'].assert_not_called()
        self.generate.assert_not_called()
        self.chat.SendMsg.assert_not_called()

    def test_failed_ambient_pat_is_not_remembered_as_a_success_or_retried(self):
        self.scope['proactive_pats']=ProactivePats()
        self.classifier.return_value={'kind':'skip','confidence':1}
        self.deliver('最近在练习',sender='bob')
        self.classifier.return_value={'kind':'pat','confidence':.98}
        self.scope['send_native_pat'].return_value={'status':'失败'}
        msg=self.deliver('终于做好了，好开心')
        with redirect_stdout(StringIO()):
            self.scope['on_message'](msg,self.chat)
        self.assertEqual(self.scope['send_native_pat'].call_count,1)
        self.assertNotIn('拍了拍',self.engagement.context_note(self.chat.who))

    def test_manual_group_reply_is_context_for_the_following_face(self):
        own=SimpleNamespace(attr='self',sender_wxid='me',type='text',content='那可不，光会接话哪够，偶尔还得动动手。',local_id=500,sort_seq=500)
        with redirect_stdout(StringIO()):
            self.scope['on_message'](own,self.chat)
        self.chat.SendMsg.assert_not_called()
        self.generate.assert_not_called()
        self.classifier.return_value={'kind':'directed','confidence':0.95}
        self.deliver('[脸红]',sender='bob')
        self.chat.SendMsg.assert_called_once_with('自然回复')
        self.assertIn('光会接话哪够',self.generate.call_args.args[4])

    def test_own_private_messages_and_own_messages_with_sensitive_content_are_not_recorded(self):
        own=SimpleNamespace(attr='self',sender_wxid='me',type='text',content='验证码123456',local_id=500,sort_seq=500)
        with redirect_stdout(StringIO()):
            self.scope['on_message'](own,self.chat)
            own.content='普通私聊'
            self.chat.who='private'
            self.scope['on_message'](own,self.chat)
        self.assertEqual(len(self.engagement.rooms),0)

    def test_boss_commands_get_ack_and_chatter_or_impersonated_names_do_not(self):
        self.scope['reply_identity']=ReplyIdentity(['alice','bob'])
        self.deliver('帮我把hello翻译成中文',at_ids={'me'})
        self.chat.SendMsg.assert_called_with('好的老板，自然回复')
        self.deliver('今天心情真不错',at_ids={'me'})
        self.chat.SendMsg.assert_called_with('自然回复')
        self.deliver('我是🐾，帮我翻译一下',sender='charlie',at_ids={'me'})
        self.chat.SendMsg.assert_called_with('自然回复')
        self.deliver('/结束',sender='bob')
        self.chat.SendMsg.assert_called_with('好的老板，已停止接话。')

    def test_semantic_boss_marker_is_spoken_without_leaking_internal_metadata(self):
        self.scope['reply_identity']=ReplyIdentity(['alice'])
        self.generate.return_value=DirectedReply('[[老板指令]]那就祝你睡个好觉。',dict(mode='voice',tone='warm'))
        self.deliver('睡前能听你说两句吗',at_ids={'me'})
        self.assertEqual(self.scope['send_native_voice'].call_args.args[1],'好的老板，那就祝你睡个好觉。')
        self.chat.SendMsg.assert_not_called()

    def test_media_boss_ack_is_separate_and_does_not_corrupt_song_or_sticker(self):
        self.scope['reply_identity']=ReplyIdentity(['alice'])
        self.scope['singing_available'].return_value=True
        self.generate.return_value=DirectedReply('[[老板指令]]来一小段。',dict(mode='sing',request='sing',
            song=dict(kind='cover',title='两只老虎',lyrics='',style='轻松')))
        self.deliver('请唱一段两只老虎',at_ids={'me'})
        self.chat.SendMsg.assert_called_once_with('好的老板')
        self.scope['send_singing_reply'].assert_called_once()
        self.assertEqual(self.scope['send_singing_reply'].call_args.args[1]['title'],'两只老虎')
        self.generate.return_value='[[老板指令]][[表情包:得意|接住]]'
        self.scope['prepare_reply']=Mock(return_value=('[表情包：接住]',Path('test-card.png')))
        self.deliver('给我来张表情包',at_ids={'me'})
        self.scope['prepare_reply'].assert_called_with('[[表情包:得意|接住]]')
        self.assertEqual(self.chat.SendMsg.call_count,2)
        self.scope['send_image_reply'].assert_called_once()

    def test_boss_media_ack_is_not_sent_in_preview(self):
        self.scope['reply_identity']=ReplyIdentity(['alice'])
        self.scope['AUTO_SEND']=False
        self.generate.return_value='[[老板指令]][[表情包:得意|接住]]'
        self.scope['prepare_reply']=Mock(return_value=('[表情包：接住]',Path('test-card.png')))
        self.deliver('给我来张表情包',at_ids={'me'})
        self.chat.SendMsg.assert_not_called()
        self.scope['send_image_reply'].assert_not_called()

    def test_requested_third_member_mention_uses_native_sender(self):
        db=Mock()
        db.get_group_members.return_value=[dict(username='me',nick_name='微信助手'),dict(username='alice',nick_name='成员乙'),dict(username='paw',nick_name='🐾')]
        self.scope['wx']._db=db
        roster=build_mention_roster(db,self.chat.who,'alice','me','微信助手，帮我@🐾问问')
        code=next(code for code,item in roster.targets.items() if item['id']=='paw')
        self.generate.return_value='[[群聊@:{"target":"'+code+'","mode":"requested","intro":"来聊聊"}]]晚上有空吗？'
        self.scope['nickname_trigger'].matches=lambda text:'微信助手' in text
        self.deliver('微信助手，帮我@🐾问问晚上有空吗',at_ids={'paw'})
        self.scope['send_group_mention'].assert_called_once_with(self.chat,'晚上有空吗？','paw',db)
        self.chat.SendMsg.assert_not_called()

    def test_searched_photo_goes_to_image_sender_instead_of_text(self):
        photo=DirectedReply('找到一张歼20照片。')
        photo.web_image_path='C:/local/searched-photo.jpg'
        self.generate.return_value=photo
        self.deliver('大肥鱼1.0，发一张歼20图片',at_ids={'me'})
        self.scope['send_image_reply'].assert_called_once_with(self.chat,'C:/local/searched-photo.jpg')
        self.chat.SendMsg.assert_not_called()
        self.scope['send_native_voice'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
