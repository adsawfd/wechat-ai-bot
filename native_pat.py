"""Pat the verified sender of one visible native text message, at most once."""
import math
import re
import time
import unicodedata
from group_mentions import _ready_input, _norm, _failure
from incoming_context import exact_row, _decoded


def _text(value):
    value = re.sub(r'^wxid_[A-Za-z0-9_]+:\s*\n', '', _decoded(value), count=1)
    return ''.join(unicodedata.normalize('NFKC', value).split())


def _member_names(db, chat_id, sender_id):
    members = db.get_group_members(chat_id)
    matches = [m for m in members if m.get('username') == sender_id]
    if len(matches) != 1:
        return set()
    names = set()
    for field in ('remark', 'nick_name'):
        name = _norm(matches[0].get(field))
        if name and name not in ('所有人', 'all', 'notify@all'):
            owners = {m.get('username') for m in members if any(_norm(m.get(f)) == name for f in ('remark', 'nick_name'))}
            if owners == {sender_id}:
                names.add(name)
    return names


def _verified_menu_item(root, names, is_group):
    stack, visited = [root], 0
    while stack and visited < 1500:
        node = stack.pop()
        visited += 1
        try:
            children = node.GetChildren()
            items = [child for child in children
                     if str(child.AutomationId or '').rsplit('.', 1)[-1] == 'XMenuItem'
                     and getattr(child, 'IsOffscreen', False) is not True]
            pats = [item for item in items if str(item.Name or '').strip() == '拍一拍']
            mentions = [str(item.Name or '').strip() for item in items if str(item.Name or '').strip().startswith('@')]
            if len(pats) == 1:
                if is_group and len(mentions) == 1 and _norm(mentions[0]) in names:
                    return pats[0]
                if not is_group and not mentions:
                    return pats[0]
            stack.extend(children)
        except Exception:
            continue
    return None


def _menu_item(gui, uia, names, is_group):
    root = uia._anchor(gui.main_hwnd)
    item = _verified_menu_item(root, names, is_group) if root is not None else None
    if item is not None:
        return item
    # Some Qt builds expose the avatar menu as a separate owned window.
    import win32gui
    import uiautomation as auto
    roots = []
    def visit(hwnd, _):
        if hwnd != gui.main_hwnd and win32gui.IsWindowVisible(hwnd) and gui._get_pid(hwnd) == gui.pid:
            roots.append(auto.ControlFromHandle(hwnd))
        return True
    win32gui.EnumWindows(visit, None)
    for root in roots:
        item = _verified_menu_item(root, names, is_group)
        if item is not None:
            return item
    return None


def _perform_pat(chat, gui, text, names, is_group, sleep=time.sleep):
    uia, control = _ready_input(chat, gui)
    if control is None:
        return _failure('拍一拍未确认目标会话，跳过')
    messages = uia._message_list()
    if messages is None:
        return _failure('拍一拍未找到消息列表，跳过')
    lr = messages.BoundingRectangle
    rows = []
    for row in messages.GetChildren():
        try:
            if _text(row.Name) != text:
                continue
            rect = row.BoundingRectangle
            if rect.top >= lr.top and rect.bottom <= lr.bottom and rect.bottom > rect.top:
                rows.append(rect)
        except Exception:
            continue
    if len(rows) != 1:
        return _failure('拍一拍未唯一定位当前成员的可见消息，跳过')
    rect = rows[0]
    values = (lr.left, lr.top, lr.right, lr.bottom, rect.top, rect.bottom)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        return _failure('拍一拍头像位置无效，跳过')
    # This avatar offset is only a menu-opening hint. The menu itself must name
    # the exact member before any pat click is possible.
    x = int(lr.left + 36)
    y = int(rect.top + min(26, (rect.bottom - rect.top) / 2))
    if not (lr.left < x < lr.right and lr.top < y < lr.bottom):
        return _failure('拍一拍头像不在消息区内，跳过')
    opened = False
    try:
        gui.wx_click(x, y, right=True)
        opened = True
        item = None
        for _ in range(4):
            sleep(0.12)
            item = _menu_item(gui, uia, names, is_group)
            if item is not None:
                break
        if item is None:
            return _failure('拍一拍菜单未确认目标群成员，跳过')
        # Submission is attempted exactly once; no OCR guesses or click retries.
        if not uia._click_ctrl(item):
            return _failure('拍一拍提交未确认，不自动重试')
        opened = False
        return {'status': '成功', 'message': '已向确认的头像菜单提交拍一拍，请核对实际结果', 'data': None}
    finally:
        if opened:
            # Escape can minimize WeChat. Dismiss only by clicking its input.
            uia._click_ctrl(control)


def send_native_pat(chat, msg, sender_id, db, self_id):
    if not sender_id or sender_id == self_id:
        return _failure('不对自己拍一拍')
    chat_id = str(getattr(chat, 'who', '') or '')
    try:
        row = exact_row(msg, chat_id, db)
        if not row or int(row.get('local_type') or 0) & 0xffffffff != 1 or not row.get('shard'):
            return _failure('拍一拍仅定位原生文字消息，当前消息不适用')
        original = db.get_message_row(chat_id, int(row['local_id']), shard=row['shard'])
        if not original or original.get('sender_username') != sender_id or str(original.get('sort_seq')) != str(row.get('sort_seq')):
            return _failure('拍一拍未确认消息发送者，跳过')
        text = _text(original.get('content'))
        if not text or text != _text(getattr(msg, 'content', '')):
            return _failure('拍一拍原消息正文未匹配，跳过')
        is_group = chat_id.endswith('@chatroom')
        names = _member_names(db, chat_id, sender_id) if is_group else set()
        if is_group and not names:
            return _failure('拍一拍未确认唯一群成员，跳过')
        actual = getattr(chat, 'chat', None) or chat
        gui = getattr(actual, '_gui', None)
        if not isinstance(getattr(gui, 'main_hwnd', None), int):
            return _failure('拍一拍界面暂不可用')
        from wechatauto.utils import LockManager
        with LockManager.acquire():
            return _perform_pat(chat, gui, text, names, is_group)
    except Exception as exc:
        return _failure('拍一拍处理失败，不重试：' + type(exc).__name__)
