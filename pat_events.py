"""Identify native WeChat pat events from exact database rows, never chat text."""
import xml.etree.ElementTree as ET


def parse_pat_sender(content, self_id):
    if not isinstance(content, str) or not self_id or len(content) > 100000:
        return None
    # Database content can have a group-sender prefix before the XML payload.
    if not content.lstrip().startswith('<'):
        prefix, sep, payload = content.partition(':\n')
        if not sep or not prefix.strip() or '<' in prefix:
            return None
        content = payload
    if '<!DOCTYPE' in content.upper() or '<!ENTITY' in content.upper():
        return None
    try:
        root = ET.fromstring(content)
    except (ET.ParseError, ValueError):
        return None
    if root.tag != 'msg':
        return None
    app = root.find('appmsg')
    if app is None or (app.findtext('type') or '').strip() != '62':
        return None
    pats = app.findall('patinfo')
    if len(pats) != 1:
        return None
    pat = pats[0]
    if len(pat.findall('fromusername')) != 1 or len(pat.findall('pattedusername')) != 1:
        return None
    sender = (pat.findtext('fromusername') or '').strip()
    target = (pat.findtext('pattedusername') or '').strip()
    if target != self_id or not sender or sender == self_id or sender.isdigit():
        return None
    return sender


def get_pat_sender(msg, chat, db, self_id):
    local_id = getattr(msg, 'local_id', None)
    seq = getattr(msg, 'sort_seq', None)
    chat_id = str(getattr(chat, 'who', '') or '')
    if local_id is None or seq is None or not chat_id:
        return None
    try:
        rows = db.get_message_rows_for_media(chat_id, int(local_id))
        matches = [row for row in rows if str(row.get('sort_seq')) == str(seq)]
        if len(matches) != 1:
            return None
        row = matches[0]
        # Type 49 is a native application message; never accept a text message
        # merely because its contents imitate a pat XML payload.
        if int(row.get('local_type') or 0) & 0xffffffff != 49:
            return None
        content = row.get('content')
        if isinstance(content, memoryview):
            content = content.tobytes()
        if isinstance(content, bytes):
            from wechatauto.db import WeChatDB
            content = WeChatDB._friendly_content(content, '文件/链接/卡片')
        return parse_pat_sender(content, self_id)
    except Exception as exc:
        print('拍一拍识别失败：', type(exc).__name__, flush=True)
        return None
