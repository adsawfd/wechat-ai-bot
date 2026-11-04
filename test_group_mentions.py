import unittest
from unittest.mock import Mock, call, patch
from types import SimpleNamespace
from bot_runtime import configure_runtime
from group_mentions import resolve_member_name, _send_native, send_group_reply, _popup_member,send_group_mention


class MentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure_runtime()

    def test_resolve_identity_and_ambiguity(self):
        db = Mock()
        db.get_group_members.return_value = [dict(username='alice', remark='同事甲', nick_name='小鱼'), dict(username='bob', remark='同事乙', nick_name='小鱼')]
        self.assertEqual(resolve_member_name(db, 'room@chatroom', 'alice'), '同事甲')
        self.assertIsNone(resolve_member_name(db, 'room@chatroom', 'missing'))
        db.get_group_members.return_value[0]['remark'] = ''
        self.assertIsNone(resolve_member_name(db, 'room@chatroom', 'alice'))

    def test_all_members_alias_never_selected(self):
        db = Mock()
        db.get_group_members.return_value = [dict(username='alice', nick_name='所有人', remark='')]
        self.assertIsNone(resolve_member_name(db, 'room@chatroom', 'alice'))

    def test_identity_mention_uses_supplied_group_nickname_only_after_member_check(self):
        gui=SimpleNamespace(main_hwnd=123)
        chat=SimpleNamespace(who='room@chatroom',_gui=gui)
        db=Mock();db.get_group_members.return_value=[{'username':'lele','nick_name':'MemberD'}]
        with patch('group_mentions._send_native',return_value={'status':'成功'}) as native:
            send_group_mention(chat,'你好','lele',db,member_group_name='群昵称甲')
            native.assert_called_once_with(chat,gui,'你好','群昵称甲',require_mention=True)
            native.reset_mock()
            result=send_group_mention(chat,'你好','absent',db,member_group_name='群昵称甲')
            self.assertEqual(result['status'],'失败')
            native.assert_not_called()

    def fake_gui(self, labels=None):
        gui = Mock(right_pane_left=10, render_w=800, render_h=850, origin_x=20, origin_y=30)
        gui.ensure_visible.return_value = True
        gui.open_chat.return_value = True
        gui.focus_input.return_value = True
        gui.get_input_box.return_value = (10, 650, 800, 780)
        gui.ocr.return_value = labels if labels is not None else [('同事甲', 100, 200, 60, 20)]
        gui.set_clipboard.return_value = True
        gui.click_send.return_value = True
        gui.uia = Mock()
        gui._get_uia.return_value = gui.uia
        gui.uia.ensure_window.return_value = True
        gui.uia.current_chat.return_value = '测试群'
        gui.control = Mock()
        gui.uia._chat_input.return_value = gui.control
        gui.uia._paste_landed.return_value = (True, '正文', 1.0)
        gui.control.BoundingRectangle = SimpleNamespace(left=30, top=680, right=820, bottom=810)
        return gui

    def test_native_mention_is_preserved_when_appending_body(self):
        chat = Mock(who='room@chatroom', nickname='测试群')
        gui = self.fake_gui()
        after_selection = []
        selected = [False]
        gui.wx_click.side_effect = lambda *args: selected.__setitem__(0, True)
        gui.control.SendKeys.side_effect = lambda *args, **kwargs: after_selection.append((args, kwargs)) if selected[0] else None
        result = _send_native(chat, gui, '回复正文', '同事甲', sleep=lambda _: None)
        self.assertEqual(result['status'], '成功')
        gui.control.SendKeys.assert_any_call('@', waitTime=0.01)
        gui.set_clipboard.assert_any_call('同事甲')
        gui._input.type_unicode.assert_not_called()
        gui.input_text.assert_not_called()
        self.assertFalse(any('a{Delete}' in args[0] for args, _ in after_selection))
        self.assertTrue(any('{Ctrl}v' in args[0] for args, _ in after_selection))
        self.assertEqual(sum(args[0] == '{Enter}' for args, _ in after_selection), 1)
        gui.open_chat.assert_not_called()
        gui.get_input_box.assert_not_called()
        chat.SendMsg.assert_not_called()

    def test_missing_or_duplicate_selector_downgrades_before_send(self):
        for items in ([], [('同事甲', 1, 1, 5, 5), ('同事甲', 1, 15, 5, 5)], [('同事甲乙', 1, 1, 5, 5)]):
            chat = Mock(who='room@chatroom', nickname='测试群')
            gui = self.fake_gui(items)
            _send_native(chat, gui, '正文', '同事甲', sleep=lambda _: None)
            chat.SendMsg.assert_called_once_with('正文', who='测试群')
            gui.click_send.assert_not_called()

    def test_failed_submission_is_never_retried(self):
        chat = Mock(who='room@chatroom', nickname='测试群')
        gui = self.fake_gui()
        def keys(value, **kwargs):
            if value == '{Enter}':
                raise RuntimeError('uncertain submission')
        gui.control.SendKeys.side_effect = keys
        result = _send_native(chat, gui, '正文', '同事甲', sleep=lambda _: None)
        self.assertEqual(result['status'], '失败')
        self.assertEqual(sum(c.args[0] == '{Enter}' for c in gui.control.SendKeys.call_args_list), 1)
        chat.SendMsg.assert_not_called()

    def test_wrong_chat_is_not_sent(self):
        chat = Mock(who='room@chatroom', nickname='测试群')
        gui = self.fake_gui()
        gui.uia.current_chat.return_value = 'other'
        gui.open_chat.return_value = False
        _send_native(chat, gui, '正文', '同事甲', sleep=lambda _: None)
        gui._input.type_unicode.assert_not_called()
        chat.SendMsg.assert_called_once_with('正文', who='测试群')

    def test_unknown_member_plain_reply_without_ui(self):
        chat, db = Mock(who='room@chatroom', nickname='测试群'), Mock()
        db.get_group_members.return_value = []
        send_group_reply(chat, '正文', 'alice', db, start_topic=True)
        chat.SendMsg.assert_called_once_with('正文', who='测试群')

    def test_regular_reply_never_resolves_or_mentions_member(self):
        chat, db = Mock(), Mock()
        with patch('group_mentions._plain_reply', return_value='plain') as plain, patch('group_mentions._send_native') as native:
            self.assertEqual(send_group_reply(chat, '自然接话😂', 'alice', db), 'plain')
        plain.assert_called_once_with(chat, '自然接话😂')
        native.assert_not_called()
        db.get_group_members.assert_not_called()

    def test_only_explicit_topic_opener_mentions_member(self):
        gui = object()
        chat = SimpleNamespace(who='room@chatroom', nickname='测试群', _gui=gui)
        db = Mock()
        db.get_group_members.return_value = [dict(username='alice', nick_name='小鱼', remark='')]
        with patch('group_mentions._send_native', return_value='mentioned') as native, patch('group_mentions._plain_reply') as plain:
            self.assertEqual(send_group_reply(chat, '来聊个新话题', 'alice', db, start_topic=True), 'mentioned')
        native.assert_called_once_with(chat, gui, '来聊个新话题', '小鱼')
        plain.assert_not_called()

    def test_display_name_reuses_current_group(self):
        chat = Mock(who='123@chatroom', nickname='测试群')
        gui = self.fake_gui()
        gui.uia.current_chat.return_value = '测试群'
        _send_native(chat, gui, '😂', '同事甲', sleep=lambda _: None)
        gui.open_chat.assert_not_called()

    def test_native_object_token_and_emoji_body(self):
        chat = Mock(who='room@chatroom', nickname='测试群')
        gui = self.fake_gui()
        gui.uia._read_edit_value.side_effect = ['\ufffc', '\ufffc 😂']
        gui.uia._compare_norm.side_effect = lambda text: ''.join(text.split())
        result = _send_native(chat, gui, '😂', '同事甲', sleep=lambda _: None)
        self.assertEqual(result['status'], '成功')

    def test_native_popup_matches_emoji_without_ocr(self):
        row = Mock(AutomationId='', Name='🐾', ControlTypeName='ListItemControl')
        row.GetChildren.return_value = []
        table = Mock(AutomationId='chat_mention_list', Name='', ControlTypeName='ListControl')
        table.GetChildren.return_value = [row]
        root = Mock(AutomationId='MentionPopover')
        root.GetChildren.return_value = [table]
        self.assertIs(_popup_member(root, '🐾'), row)
        chat = Mock(who='room@chatroom', nickname='测试群')
        gui = self.fake_gui()
        with patch('group_mentions._mention_item', return_value=row):
            result = _send_native(chat, gui, '正文', '🐾', sleep=lambda _: None)
        self.assertEqual(result['status'], '成功')
        gui.uia._click_ctrl.assert_called_once_with(row)
        gui.ocr.assert_not_called()
        gui.control.SendKeys.assert_any_call('@', waitTime=0.01)
        gui._input.type_unicode.assert_not_called()

    def test_failed_paste_does_not_send_mention_alone(self):
        chat = Mock(who='room@chatroom', nickname='测试群')
        gui = self.fake_gui()
        gui.uia._read_edit_value.side_effect = ['\ufffc', '\ufffc']
        gui.uia._compare_norm.side_effect = lambda text: ''.join(text.split())
        result = _send_native(chat, gui, '😂', '同事甲', sleep=lambda _: None)
        chat.SendMsg.assert_called_once_with('😂', who='测试群')
        self.assertFalse(any(c.args[0] == '{Enter}' for c in gui.control.SendKeys.call_args_list))

    def test_invalid_or_stale_rectangle_downgrades_without_screenshot(self):
        for top, bottom in ((0, 0), (-32000, -31900), (20, 120), (3000, 3100)):
            chat = Mock(who='room@chatroom', nickname='测试群')
            gui = self.fake_gui()
            gui.control.BoundingRectangle = SimpleNamespace(left=30, top=top, right=800, bottom=bottom)
            _send_native(chat, gui, '正文', '同事甲', sleep=lambda _: None)
            gui.ocr.assert_not_called()
            chat.SendMsg.assert_called_once_with('正文', who='测试群')

    def test_small_valid_rectangle_never_has_reversed_edges(self):
        chat = Mock(who='room@chatroom', nickname='测试群')
        gui = self.fake_gui()
        gui.control.BoundingRectangle = SimpleNamespace(left=30, top=100, right=800, bottom=200)
        _send_native(chat, gui, '正文', '同事甲', sleep=lambda _: None)
        left, top, right, bottom = gui.ocr.call_args.args[0]
        self.assertLess(top, bottom)
        self.assertLess(left, right)

    def test_screenshot_exception_falls_back_before_submit(self):
        chat = Mock(who='room@chatroom', nickname='测试群')
        gui = self.fake_gui()
        gui.ocr.side_effect = RuntimeError("Coordinate 'lower' is less than 'upper'")
        _send_native(chat, gui, '正文', '同事甲', sleep=lambda _: None)
        chat.SendMsg.assert_called_once_with('正文', who='测试群')
        self.assertFalse(any(c.args[0] == '{Enter}' for c in gui.control.SendKeys.call_args_list))

    def test_strict_mention_requires_native_selector_and_preserved_token(self):
        chat=Mock(who='room@chatroom',nickname='测试群')
        for after,want_success in (('\ufffc 正文',True),('正文',False)):
            gui=self.fake_gui()
            gui.uia._read_edit_value.side_effect=['\ufffc',after]
            gui.uia._compare_norm.side_effect=lambda text:''.join(text.split())
            with patch('group_mentions._mention_item',return_value=Mock()):
                result=_send_native(chat,gui,'正文','🐾',sleep=lambda _:None,require_mention=True)
            self.assertEqual(result['status']=='成功',want_success)
            self.assertEqual(sum(c.args[0]=='{Enter}' for c in gui.control.SendKeys.call_args_list),int(want_success))
            gui.ocr.assert_not_called()
        chat.SendMsg.assert_not_called()

    def test_strict_missing_selector_or_member_never_downgrades_to_fake_mention(self):
        chat=Mock(who='room@chatroom',nickname='测试群')
        gui=self.fake_gui()
        with patch('group_mentions._mention_item',return_value=None):
            result=_send_native(chat,gui,'正文','🐾',sleep=lambda _:None,require_mention=True)
        self.assertEqual(result['status'],'失败')
        gui.ocr.assert_not_called()
        chat.SendMsg.assert_not_called()
        db=Mock()
        db.get_group_members.return_value=[]
        self.assertEqual(send_group_mention(chat,'正文','left_the_group',db)['status'],'失败')
        chat.SendMsg.assert_not_called()


if __name__ == '__main__':
    unittest.main()

