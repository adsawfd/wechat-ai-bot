"""Open one exactly matched visible video, then wait only for its native cache."""
import math
import re
import time
from group_mentions import _ready_input, _norm


def _plain(value):
    value = re.sub(r'^wxid_[A-Za-z0-9_]+:\s*\n', '', str(value or ''), count=1)
    return _norm(value)


def _db_signature(row):
    kind = row.get('type')
    if kind == '文本':
        return ('text', _plain(row.get('content')))
    return {'视频': ('video', ''), '图片': ('image', ''), '动画表情': ('emoji', ''),
            '语音': ('voice', '')}.get(kind)


def _ui_signature(control):
    kind = str(control.ClassName or '').rsplit('::', 1)[-1]
    # Current WeChat exposes every bubble using the same generic item view.
    # Its accessible name carries the media kind, including the download state.
    aid = str(getattr(control, 'AutomationId', '') or '').rsplit('.', 1)[-1]
    if aid == 'chat_bubble_item_view' or kind == 'ChatBubbleItemView':
        name = str(control.Name or '').strip()
        if re.fullmatch(r'视频\s*(?:下载|播放|暂停|未下载|已下载)?\s*\d+:\d{2}(?::\d{2})?', name):
            return ('video', '')
        if name in ('图片', '[图片]'):
            return ('image', '')
        if name in ('动画表情', '表情', '[动画表情]'):
            return ('emoji', '')
        if re.fullmatch(r'语音(?:\s*\d+[秒\"\u2033])?', name):
            return ('voice', '')
        # Time separators have no chat_bubble_item_view ID and don't enter here.
        return ('text', _plain(name))
    if kind == 'ChatTextItemView':
        return ('text', _plain(control.Name))
    for token, signature in (('Video', 'video'), ('Image', 'image'), ('Emoji', 'emoji'), ('Voice', 'voice')):
        if kind.startswith('Chat') and token in kind:
            return (signature, '')
    return None


def match_visible_video(controls, rows, target):
    """Align the complete visible message sequence, requiring a unique text anchor.

    Matching only 'the last video' or a duration can select a different bubble.
    Text anchors plus all intervening media types must match a single DB window.
    """
    ui = [(control, _ui_signature(control)) for control in controls]
    ui = [(control, signature) for control, signature in ui if signature]
    db = [(row, _db_signature(row)) for row in sorted(rows, key=lambda r: int(r['sort_seq']))]
    db = [(row, signature) for row, signature in db if signature]
    if not ui or not any(s[0] == 'text' and len(s[1]) >= 4 for _, s in ui):
        return None
    matches = []
    for start in range(len(db) - len(ui) + 1):
        window = db[start:start + len(ui)]
        if [s for _, s in window] != [s for _, s in ui]:
            continue
        positions = [i for i, (row, _) in enumerate(window)
                     if str(row.get('local_id')) == str(target.get('local_id'))
                     and str(row.get('sort_seq')) == str(target.get('sort_seq'))
                     and row.get('shard') == target.get('shard')
                     and row.get('sender_username') == target.get('sender_username')]
        if len(positions) == 1 and ui[positions[0]][1][0] == 'video':
            matches.append(ui[positions[0]][0])
        elif any(signature[0] == 'video' for _, signature in window):
            # An identical visible sequence elsewhere makes the mapping ambiguous.
            return None
    return matches[0] if len(matches) == 1 else None


def _previews(gui):
    import win32gui
    output = set()
    def visit(hwnd, _):
        if (hwnd != gui.main_hwnd and win32gui.IsWindowVisible(hwnd)
                and gui._get_pid(hwnd) == gui.pid and win32gui.GetWindowText(hwnd) == '预览'):
            output.add(hwnd)
        return True
    win32gui.EnumWindows(visit, None)
    return output


def _open_and_wait(chat, gui, target, db, resolver, *, sleep=time.sleep, clock=time.monotonic):
    from wechatauto import rhythm
    uia, input_control = _ready_input(chat, gui)
    if input_control is None or _previews(gui):
        return None
    message_list = uia._message_list()
    if message_list is None:
        return None
    bounds = message_list.BoundingRectangle
    controls = []
    for control in message_list.GetChildren():
        try:
            rect = control.BoundingRectangle
            # The top row may be clipped at the nickname while its entire video
            # card remains visible; don't drop that usable bubble.
            if min(rect.bottom, bounds.bottom) - max(rect.top, bounds.top) >= min(60, (rect.bottom-rect.top)/2) and rect.bottom > rect.top:
                controls.append(control)
        except Exception:
            continue
    controls.sort(key=lambda c: c.BoundingRectangle.top)
    video = match_visible_video(controls, db.get_messages(str(chat.who), limit=120), target)
    if video is None:
        print('视频气泡未与原消息唯一匹配，未自动打开', flush=True)
        return None
    rect = video.BoundingRectangle
    # The native row spans the list width; the incoming video bubble starts after
    # the avatar. Both coordinates are bounded by the freshly verified row.
    x = int(rect.left + 130)
    y = int((max(rect.top, bounds.top) + min(rect.bottom, bounds.bottom)) / 2)
    if (not all(math.isfinite(v) for v in (x, y, rect.left, rect.top, rect.right, rect.bottom))
            or rect.bottom - rect.top < 80 or not rect.left < x < rect.right
            or not bounds.top < y < bounds.bottom):
        return None
    before = _previews(gui)
    try:
        rhythm.gate('video')
        gui.wx_click(x, y)  # One attempt only; no blind repeated clicks or scrolling.
        print('已尝试打开对应视频，等待微信下载…', flush=True)
        end, last = clock() + 25, None
        while clock() < end:
            path = resolver(db, target)
            if path:
                stat = path.stat()
                current = (str(path), stat.st_size, stat.st_mtime_ns)
                if current == last:
                    return path
                last = current
            sleep(.75)
        return None
    finally:
        # Close only newly opened media previews, never the main WeChat window.
        import win32con
        import win32gui
        for hwnd in _previews(gui) - before:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)


def ensure_video_cached(chat, target, db, resolver):
    try:
        if target.get('sender_username') == db.get_self_info().get('username'):
            return None  # The incoming-bubble click target never applies to our own sends.
        actual = getattr(chat, 'chat', None) or chat
        gui = getattr(actual, '_gui', None)
        if not isinstance(getattr(gui, 'main_hwnd', None), int):
            return None
        from wechatauto.utils import LockManager
        with LockManager.acquire():
            return _open_and_wait(chat, gui, target, db, resolver)
    except Exception as exc:
        print('视频自动打开未完成：', type(exc).__name__, flush=True)
        return None
