"""Native group mentions with exact member selection and preserved mention tokens."""
import time
import unicodedata
import math
from threading import local

_thread_state = local()


def _norm(value):
    return ''.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split()).lstrip('@')


def resolve_member_name(db, chat_id, sender_id):
    try:
        members = db.get_group_members(chat_id)
        matches = [m for m in members if m.get('username') == sender_id]
        if len(matches) != 1:
            return None
        for field in ('remark', 'nick_name'):
            candidate = str(matches[0].get(field) or '').strip()
            key = _norm(candidate)
            if not key or key in ('所有人', 'all', 'notify@all'):
                continue
            owners = {m.get('username') for m in members
                      if any(_norm(m.get(f)) == key for f in ('remark', 'nick_name'))}
            if owners == {sender_id}:
                return candidate
    except Exception as exc:
        print('群成员名称读取失败：', type(exc).__name__, flush=True)
    return None


def _failure(message):
    return {'status': '失败', 'message': message, 'data': None}


def _display_name(chat):
    chat_id = str(getattr(chat, 'who', '') or '')
    db = getattr(chat, '_db', None)
    if db is not None:
        try:
            fresh = db.get_nickname(chat_id)
            if isinstance(fresh, str) and fresh.strip() and fresh != chat_id:
                return fresh
        except Exception:
            pass
    name = getattr(chat, 'nickname', '')
    return name if isinstance(name, str) and name.strip() else chat.who


def _plain_reply(chat, text):
    actual = getattr(chat, 'chat', None) or chat
    gui = getattr(actual, '_gui', None)
    if not isinstance(getattr(gui, 'main_hwnd', None), int):
        return chat.SendMsg(text, who=_display_name(chat))
    from wechatauto.utils import LockManager
    with LockManager.acquire():
        uia, control = _ready_input(chat, gui)
        if control is None:
            return _failure('未确认目标会话的发送输入框，未发送，避免发错会话')
        # Use the verified control directly. The old SendMsg path calls open_chat
        # again even when its cached input lookup just failed.
        try:
            control.SetFocus()
            control.SendKeys('{Ctrl}a{Delete}', waitTime=0.01)
            uia._clip_set(text)
            control.SendKeys('{Ctrl}v', waitTime=0.01)
            time.sleep(0.15)
            if not uia._paste_landed(control, text)[0]:
                control.SendKeys('{Ctrl}a{Delete}', waitTime=0.01)
                return _failure('正文未通过输入框回读检查，未发送')
        except Exception as exc:
            return _failure('输入框写入失败：' + type(exc).__name__)
        from wechatauto import rhythm
        rhythm.gate('send')
        try:
            control.SendKeys('{Enter}', waitTime=0.01)
        except Exception:
            return _failure('普通回复已尝试提交，结果未确认，不重发')
        return {'status': '成功', 'message': '已向确认的输入框提交回复', 'data': {'content': text}}


def _layout(root, target):
    title = None
    control = None
    session = None
    stack = [(root, 0)] if root is not None else []
    visited = 0
    while stack and visited < 1500:
        node, depth = stack.pop()
        visited += 1
        if depth > 50:
            continue
        try:
            aid = str(node.AutomationId or '')
            # Exact leaf IDs only: chat_input_field.qt_scrollarea_viewport is
            # not the edit control and often has a zero bounding rectangle.
            leaf = aid.rsplit('.', 1)[-1]
            if leaf == 'current_chat_name_label':
                title = str(node.Name or '')
            elif leaf == 'chat_input_field':
                control = node
            elif aid == 'session_item_' + target:
                session = node
            stack.extend((child, depth + 1) for child in node.GetChildren())
        except Exception:
            continue
    return title, control, session


def _restore_chat_tree(gui, uia, target):
    """Restore Qt's own visibility, rather than only showing its native HWND."""
    print('微信控件未就绪，正在通过微信自身唤起并重新读取', flush=True)
    try:
        # ShowWindow alone leaves Qt's widgets hidden after Escape/close-to-tray.
        # The existing WeChat protocol reopens the actual Qt main view.
        uia.wake()
        for _ in range(12):
            time.sleep(0.15)
            root = uia._anchor(gui.main_hwnd)
            if root is None:
                continue
            current, control, session = _layout(root, target)
            if current or control is not None:
                uia._win = root
                return current, control, session
    except Exception as exc:
        print('微信控件恢复失败：', type(exc).__name__, flush=True)
    return None, None, None


def _ready_input(chat, gui):
    """Use the existing chat when its title matches; no blind cached coordinates."""
    if not gui.ensure_visible():
        return None, None
    target = _display_name(chat)
    # Session callbacks may cache a raw ID before a new/renamed group has a name.
    # Searching that ID leaves a useless popup over all subsequent chat inputs.
    if str(target).endswith('@chatroom'):
        print('该群名称尚未从微信同步，不使用内部群号搜索，跳过本次发送', flush=True)
        return None, None
    if not getattr(_thread_state, 'initialized', False):
        import uiautomation as auto
        auto.InitializeUIAutomationInCurrentThread()
        _thread_state.initialized = True
    uia = gui._get_uia()
    if uia is not None:
        if not uia.ensure_window():
            return None, None
        # Never send Escape here: WeChat hides its main window when no popup is
        # open. Resolve the current tree again after activation instead.
        current, control, session = _layout(getattr(uia, '_win', None), target)
        current = current or uia.current_chat()
        if not current and control is None:
            current, control, session = _restore_chat_tree(gui, uia, target)
            current = current or uia.current_chat()
        if _norm(current) != _norm(target):
            if session is not None:
                # An existing visible conversation can be selected without search.
                uia._click_ctrl(session)
                # Wait for the header to actually switch instead of trusting a click.
                for _ in range(6):
                    time.sleep(0.15)
                    switched, _, _ = _layout(getattr(uia, '_win', None), target)
                    if _norm(switched) == _norm(target):
                        break
            elif current and not gui.open_chat(target, exact=True):
                return None, None
            current, control, _ = _layout(getattr(uia, '_win', None), target)
            current = current or uia.current_chat()
        if _norm(current) != _norm(target):
            print('会话校验失败：目标=%r，当前=%r' % (target, current), flush=True)
            return None, None
        control = control if control is not None else uia._chat_input()
        if control is not None:
            gui._current_chat = target
            return uia, control
        print('已确认目标会话，但微信尚未提供发送输入框', flush=True)
    # Let the standard text sender handle unavailable UIA without repeating navigation.
    return None, None


def _selector_region(control, gui):
    # Activation/resizing can change the window after the initial visibility check.
    gui._update_render_rect()
    rect = control.BoundingRectangle
    values = (rect.left, rect.top, rect.right, rect.bottom,
              gui.origin_x, gui.origin_y, gui.render_w, gui.render_h, gui.right_pane_left)
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
        return None
    if rect.right <= rect.left or rect.bottom <= rect.top or gui.render_w <= 1 or gui.render_h <= 1:
        return None
    bottom = int(rect.top - gui.origin_y)
    # A stale/off-screen input must never be used to form a screenshot rectangle.
    if bottom < 40 or bottom > gui.render_h:
        return None
    left = max(0, min(int(gui.right_pane_left), int(gui.render_w) - 1))
    right = int(gui.render_w)
    top = max(0, bottom - 500)
    return (left, top, right, bottom) if left < right and top < bottom else None


def _popup_member(root, member):
    """Read only the observed native mention list, never the message pane."""
    matches = []
    stack = [(root, False, 0)]
    visited = 0
    while stack and visited < 300:
        node, in_list, depth = stack.pop()
        visited += 1
        if depth > 15:
            continue
        try:
            in_list = in_list or str(node.AutomationId or '') == 'chat_mention_list'
            if in_list and node.ControlTypeName == 'ListItemControl' and _norm(node.Name) == _norm(member):
                matches.append(node)
            stack.extend((child, in_list, depth + 1) for child in node.GetChildren())
        except Exception:
            continue
    return matches[0] if len(matches) == 1 else None


def _mention_item(gui, uia, member):
    # WeChat's MentionPopover is a separate owned window, outside the main tree.
    # Its list exposes emoji nicknames exactly; OCR cannot reliably read those.
    if not isinstance(getattr(gui, 'pid', None), int):
        return None
    try:
        import win32gui
        import win32process
        popups = []
        def visit(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            if win32process.GetWindowThreadProcessId(hwnd)[1] != gui.pid:
                return True
            if 'QWindowTool' not in win32gui.GetClassName(hwnd):
                return True
            root = uia._anchor(hwnd)
            if root is not None and root.AutomationId == 'MentionPopover':
                popups.append(root)
            return True
        win32gui.EnumWindows(visit, None)
        if len(popups) == 1:
            return _popup_member(popups[0], member)
    except Exception:
        pass
    return None


def _compose_mention(uia, control, gui, text, member, sleep, *, require_mention=False):
    control.SetFocus()
    control.SendKeys('{Ctrl}a{Delete}', waitTime=0.01)
    # The dependency's WinInput.type_unicode uses a truncated Win64 INPUT
    # structure and silently drops characters. UIAutomation uses the full ABI.
    control.SendKeys('@', waitTime=0.01)
    sleep(0.1)
    item = _mention_item(gui, uia, member)
    if item is None:
        # Filtering makes members outside the first screen reachable.
        if gui.set_clipboard(member) is False:
            return False
        control.SendKeys('{Ctrl}v', waitTime=0.01)
        sleep(0.15)
        item = _mention_item(gui, uia, member)
    if item is not None:
        if not uia._click_ctrl(item):
            return False
    else:
        if require_mention:
            # New target-selection requests only accept the observed native
            # mention list. Text elsewhere in the chat cannot stand in for it.
            return False
        popup = _selector_region(control, gui)
        if popup is None:
            print('@成员截图区域无效，改为普通回复', flush=True)
            return False
        hits = []
        for _ in range(3):
            hits = [(x, y, w, h) for label, x, y, w, h in gui.ocr(popup)
                    if _norm(label) == _norm(member)]
            if hits:
                break
            sleep(0.15)
        if len(hits) != 1:
            print('@成员未唯一匹配，改为普通回复', flush=True)
            return False
        x, y, w, h = hits[0]
        gui.wx_click(gui.origin_x + x + w // 2, gui.origin_y + y + h // 2)
    sleep(0.15)
    # Never call input_text() here: it uses Ctrl+A and would delete the native @.
    control.SetFocus()
    before = uia._read_edit_value(control)
    if require_mention and (not isinstance(before,str) or not _norm(before)):
        return False
    if gui.set_clipboard(' ' + text) is False:
        return False
    control.SendKeys('{Ctrl}{End}{Ctrl}v', waitTime=0.01)
    sleep(0.15)
    after = uia._read_edit_value(control)
    if isinstance(before, str) and isinstance(after, str):
        # Native @ tokens can be represented by U+FFFC rather than @nickname.
        # Check the appended body and the change, not a literal nickname prefix.
        landed = after != before and uia._compare_norm(text) in uia._compare_norm(after)
        if require_mention:
            landed = landed and uia._compare_norm(after).startswith(uia._compare_norm(before))
    else:
        landed = uia._paste_landed(control, '@' + member + ' ' + text)[0]
    if not landed:
        return False
    return True


def _send_native(chat, gui, text, member, sleep=time.sleep, *, require_mention=False):
    control = None
    prepared = False
    try:
        uia, control = _ready_input(chat, gui)
        if control is not None:
            prepared = _compose_mention(uia, control, gui, text, member, sleep,require_mention=require_mention)
    except Exception as exc:
        # Composition cannot send. It is safe to fall back before any Enter key.
        print('@成员准备失败：', type(exc).__name__, flush=True)
    if not prepared:
        if control is not None:
            try:
                control.SetFocus()
                control.SendKeys('{Ctrl}a{Delete}', waitTime=0.01)
            except Exception:
                pass  # The standard sender clears and validates its own input.
        return _failure('未确认原生@与完整正文，未发送') if require_mention else _plain_reply(chat, text)
    from wechatauto import rhythm
    rhythm.gate('send')
    try:
        # Mark submission once and never retry if a key event raises.
        control.SendKeys('{Enter}', waitTime=0.01)
    except Exception:
        return _failure('@回复提交结果未确认，不自动重发')
    return {'status': '成功', 'message': '@群成员回复已提交，请核对实际结果', 'data': {'content': text}}


def send_group_reply(chat, text, sender_id, db, *, start_topic=False):
    # Replies, pat responses and ongoing conversation never ping the sender.
    # Only an explicit proactive conversation opener may create a native @.
    if not start_topic:
        return _plain_reply(chat, text)
    member = resolve_member_name(db, str(getattr(chat, 'who', '') or ''), sender_id)
    if not member:
        print('无法唯一确认@对象，发送普通回复', flush=True)
        return _plain_reply(chat, text)
    # Use the library's shared reentrant UI lock across all its sending paths.
    from wechatauto.utils import uilock

    @uilock
    def send():
        actual = getattr(chat, 'chat', None) or chat
        gui = getattr(actual, '_gui', None)
        if gui is None:
            return _plain_reply(chat, text)
        return _send_native(chat, gui, text, member)

    return send()


def send_group_mention(chat,text,target_id,db):
    """Strict native mention of a selected current member; never fake success."""
    chat_id=str(getattr(chat,'who','') or '')
    if not chat_id.endswith('@chatroom'):
        return _failure('仅支持在已确认的群聊@成员')
    name=resolve_member_name(db,chat_id,target_id)
    if not name:
        return _failure('目标成员已离群、名称重名或无法唯一确认，未发送@')
    from wechatauto.utils import LockManager
    with LockManager.acquire():
        actual=getattr(chat,'chat',None) or chat
        gui=getattr(actual,'_gui',None)
        if not isinstance(getattr(gui,'main_hwnd',None),int):
            return _failure('原生@界面暂不可用，未发送')
        return _send_native(chat,gui,text,name,require_mention=True)


def send_image_reply(chat, path):
    actual = getattr(chat, 'chat', None) or chat
    gui = getattr(actual, '_gui', None)
    from wechatauto.utils import LockManager
    with LockManager.acquire():
        if isinstance(getattr(gui, 'main_hwnd', None), int):
            _, control = _ready_input(chat, gui)
            if control is None:
                return _failure('未确认目标会话的图片发送输入框，未发送')
        return actual.SendFiles(str(path), who=_display_name(chat))
