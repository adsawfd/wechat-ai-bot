import tempfile
import unittest
import ast
from collections import defaultdict, deque
from threading import Lock
from pathlib import Path
from unittest.mock import Mock, patch
from scheduled_greeting import claim, run_once, send_greeting, restore_confirmed_test
from datetime import datetime, timedelta


class GreetingTests(unittest.TestCase):
    def test_claim_persists_and_never_repeats_same_day(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'state.json'
            self.assertTrue(claim(state, 'daily:2026-10-28'))
            self.assertFalse(claim(state, 'daily:2026-10-28'))
            self.assertTrue(claim(state, 'daily:2026-10-29'))

    def test_ambiguous_send_failure_is_never_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'state.json'
            with patch('scheduled_greeting.send_greeting', side_effect=RuntimeError('unknown')) as send:
                run_once(Mock(), {}, 'daily:2026-10-28', state)
                run_once(Mock(), {}, 'daily:2026-10-28', state)
            self.assertEqual(send.call_count, 1)

    def test_corrupt_state_does_not_send(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'state.json'
            state.write_text('broken', encoding='utf-8')
            with patch('scheduled_greeting.send_greeting') as send:
                run_once(Mock(), {}, 'daily:2026-10-28', state)
            send.assert_not_called()

    def test_followup_callback_only_for_successful_submission(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'state.json'
            callback = Mock()
            config = {'group_id':'group@chatroom', 'member_id':'target'}
            with patch('scheduled_greeting.send_greeting', side_effect=[{'status':'失败'}, {'status':'成功'}]):
                run_once(Mock(), config, 'failed', state, on_sent=callback)
                callback.assert_not_called()
                run_once(Mock(), config, 'success', state, on_sent=callback)
                callback.assert_called_once_with(config)

    def test_target_is_revalidated_before_using_native_mention(self):
        wx = Mock()
        wx._db.get_group_members.return_value = [{'username':'target'}]
        wx._db.get_nickname.return_value = '群聊'
        cfg = {'group_id':'group@chatroom', 'member_id':'target',
               'member_group_name':'群昵称甲', 'text':'友好称呼晚上好'}
        with patch('group_mentions._send_native', return_value={'status':'成功'}) as send:
            result = send_greeting(wx, cfg)
        self.assertEqual(result['status'], '成功')
        self.assertEqual(send.call_args.args[2:4], ('友好称呼晚上好', '群昵称甲'))
        self.assertTrue(send.call_args.kwargs['require_mention'])
        wx._db.get_group_members.return_value = []
        with patch('group_mentions._send_native') as send:
            with self.assertRaises(ValueError):
                send_greeting(wx, cfg)
            send.assert_not_called()

    def test_success_arms_only_the_greeted_member(self):
        tree = ast.parse(Path('bot.py').read_text(encoding='utf-8'))
        callback = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'remember_scheduled_greeting')
        scope = {'group_engagement': Mock(), 'lock': Lock(), 'group_followups': {},
                 'histories': defaultdict(lambda: deque(maxlen=8))}
        exec(compile(ast.Module(body=[callback], type_ignores=[]), 'bot-callback', 'exec'), scope)
        config = {'group_id':'room@chatroom', 'member_id':'target', 'text':'友好称呼晚上好'}
        scope['remember_scheduled_greeting'](config)
        self.assertEqual(set(scope['group_followups']), {('room@chatroom','target')})
        self.assertEqual(scope['histories'][('room@chatroom','target')][-1]['content'], config['text'])
        scope['group_engagement'].record_reply.assert_called_once()

    def test_user_confirmed_test_restores_once_without_sending(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'state.json'
            state.write_text('{"test":true,"test_success_confirmed":true}', encoding='utf-8')
            config = {'test_expires':(datetime.now()+timedelta(minutes=10)).isoformat()}
            callback = Mock()
            with patch('scheduled_greeting.send_greeting') as send:
                restore_confirmed_test(config, state, callback, datetime.now())
                restore_confirmed_test(config, state, callback, datetime.now())
            callback.assert_called_once_with(config)
            send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
