import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from nickname_trigger import NicknameTrigger
from chat_persona import generate_pat_reply


def completion(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class PersonaTests(unittest.TestCase):
    def test_pat_context_generation_without_search_and_links(self):
        client = Mock()
        client.chat.completions.create.return_value = completion('“这是什么神秘暗号？” https://example.com')
        previous = [{'role': 'user', 'content': '刚才聊到电影'}]
        answer = generate_pat_reply(client, 'model', '风格', previous)
        self.assertEqual(answer, '这是什么神秘暗号？')
        args = client.chat.completions.create.call_args.kwargs
        self.assertEqual(args['messages'][1], previous[0])
        self.assertNotIn('tools', args)
        client.post.assert_not_called()

    def test_pat_avoids_exact_recent_repeat(self):
        client = Mock()
        client.chat.completions.create.side_effect = [completion('旧回复'), completion('新创作的一句')]
        answer = generate_pat_reply(client, 'model', '', [{'role': 'assistant', 'content': '旧回复'}])
        self.assertEqual(answer, '新创作的一句')
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_generation_failure_has_variable_fallback(self):
        client = Mock()
        client.chat.completions.create.side_effect = TimeoutError()
        answer = generate_pat_reply(client, 'model', '', [])
        self.assertTrue(answer)
        other = generate_pat_reply(client, 'model', '', [{'role': 'assistant', 'content': answer}])
        self.assertNotEqual(answer, other)


class NicknameTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.db = Mock()
        self.db.get_self_info.return_value = {'username': 'me', 'nick_name': '大肥鱼1.0'}
        self.trigger = NicknameTrigger(self.db, 'me', clock=lambda: self.now)

    def test_full_nickname_and_refresh_after_rename(self):
        self.assertTrue(self.trigger.matches('大肥鱼1.0你在干什么'))
        self.assertFalse(self.trigger.matches('这是一条普通消息'))
        self.assertFalse(self.trigger.matches('大肥鱼1.01'))
        self.assertEqual(self.db.get_self_info.call_count, 1)
        self.db.get_self_info.return_value = {'username': 'me', 'nick_name': '新名字'}
        self.now = 11
        self.assertTrue(self.trigger.matches('新名字，你好'))
        self.assertFalse(self.trigger.matches('大肥鱼1.0你好'))

    def test_empty_failed_or_other_account_does_not_match(self):
        self.db.get_self_info.return_value = {'username': 'me', 'nick_name': ''}
        self.assertFalse(self.trigger.matches('随便说点什么'))
        self.db.get_self_info.return_value = {'username': 'other', 'nick_name': '新名字'}
        self.now = 11
        self.assertFalse(self.trigger.matches('新名字'))
        self.db.get_self_info.side_effect = RuntimeError()
        self.now = 22
        self.assertFalse(self.trigger.matches('大肥鱼1.0'))

    def test_english_name_unicode_and_regex_characters(self):
        self.db.get_self_info.return_value = {'username': 'me', 'nick_name': 'Fish[1]'}
        self.assertTrue(self.trigger.matches('ＦＩＳＨ[1]你在吗'))
        self.assertFalse(self.trigger.matches('Fish1'))

    def test_alias_is_candidate_only_and_follows_rename(self):
        hint=self.trigger.reference_hint('大肥鱼还会拍一拍')
        self.assertIn('大肥鱼',hint['aliases'])
        self.assertFalse(self.trigger.matches('大肥鱼还会拍一拍'))
        self.db.get_self_info.return_value={'username':'me','nick_name':'新名字'}
        self.now=11
        self.assertIsNone(self.trigger.reference_hint('大肥鱼还会拍一拍'))

    def test_little_fish_does_not_claim_big_fish_alias(self):
        self.db.get_self_info.return_value={'username':'me','nick_name':'微信助手'}
        self.assertTrue(self.trigger.matches('微信助手你在吗'))
        self.assertIsNone(self.trigger.reference_hint('大肥鱼你在吗'))
        self.assertFalse(self.trigger.matches('这小助手又皮了'))
        self.assertEqual(self.trigger.reference_hint('这小助手又皮了')['aliases'],[])


if __name__ == '__main__':
    unittest.main()
