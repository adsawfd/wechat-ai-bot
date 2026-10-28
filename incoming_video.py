"""Resolve the exact native video, retaining only recent per-sender references."""
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from threading import RLock
from incoming_context import exact_row
from video_tools import analyze_video, MAX_BYTES


@dataclass
class VideoContext:
    blocks: list = field(default_factory=list)
    note: str = ''


def video_cache_path(db, row):
    if not row or int(row.get('local_type') or 0) & 0xffffffff != 43:
        return None
    packed = row.get('packed_info')
    if isinstance(packed, memoryview):
        packed = packed.tobytes()
    if not isinstance(packed, bytes):
        return None
    match = re.search(rb'(?<![0-9a-fA-F])([0-9a-fA-F]{32})(?![0-9a-fA-F])', packed)
    if not match:
        return None
    name = match.group(1).decode().lower() + '.mp4'
    base = (Path(db.account_dir) / 'msg' / 'video').resolve()
    if not base.is_dir():
        return None
    hits, visited = [], 0
    for root, folders, files in os.walk(base, followlinks=False):
        parent = Path(root).resolve()
        if not parent.is_relative_to(base):
            folders[:] = []
            continue
        folders[:] = [f for f in folders if not (parent / f).is_symlink()]
        if len(parent.relative_to(base).parts) >= 4:
            folders[:] = []
        visited += len(files) + len(folders)
        if visited > 60000:
            return None
        for filename in files:
            if filename.lower() != name:
                continue
            path = (parent / filename).resolve()
            if path.is_relative_to(base) and path.is_file() and 0 < path.stat().st_size <= MAX_BYTES:
                hits.append(path)
                if len(hits) > 1:
                    return None
    return hits[0] if len(hits) == 1 else None


def reference_video(db, chat_id, quote):
    server_id = str(quote.get('server_id') or '')
    if quote.get('reference_type') != '43' or not server_id.isdigit() or not 0 < int(server_id) < 2**64:
        return None
    value = int(server_id)
    if value >= 2**63:
        value -= 2**64
    rows = db._run_msg_query(chat_id, lambda tables: db._shard_rows(
        tables, 'WHERE server_id=? AND local_type=43', (value,), per_shard_limit=2))
    return dict(rows[0]) if rows and len(rows) == 1 else None


class IncomingVideos:
    def __init__(self, db, ttl=600, max_entries=32, clock=time.monotonic, analyzer=analyze_video,
                 opener=None):
        self.db, self.ttl, self.max_entries, self.clock = db, ttl, max_entries, clock
        self.entries, self.lock, self.analyzer = OrderedDict(), RLock(), analyzer
        self.opener = opener

    def forget(self, chat_id, sender_id):
        with self.lock:
            self.entries.pop((chat_id, sender_id), None)

    def remember(self, msg, chat_id, sender_id):
        with self.lock:
            self.entries[(chat_id, sender_id)] = dict(msg=msg, expires=self.clock() + self.ttl)
            self.entries.move_to_end((chat_id, sender_id))
            while len(self.entries) > self.max_entries:
                self.entries.popitem(last=False)

    def _verified(self, chat_id, row, sender_id=''):
        if not row or not row.get('shard') or int(row.get('local_type') or 0) & 0xffffffff != 43:
            return None
        raw = self.db.get_message_row(chat_id, int(row['local_id']), shard=row['shard'])
        if (not raw or str(raw.get('sort_seq')) != str(row.get('sort_seq'))
                or int(raw.get('local_type') or 0) & 0xffffffff != 43
                or (sender_id and raw.get('sender_username') != sender_id)):
            return None
        return raw

    def _recover(self, chat_id, sender_id):
        for row in self.db.get_messages(chat_id, limit=40):
            if (row.get('type') == '视频' and row.get('sender_username') == sender_id
                    and time.time() - self.ttl <= float(row.get('create_time') or 0) <= time.time() + 5):
                return self._verified(chat_id, exact_row(SimpleNamespace(**row), chat_id, self.db), sender_id)
        return None

    def for_message(self, msg, chat_id, sender_id, *, quote=None, is_video=False,
                    allow_frames=True, chat=None):
        if quote and quote.get('reference_type') != '43':
            return None
        entry, row = None, None
        try:
            if quote:
                row = self._verified(chat_id, reference_video(self.db, chat_id, quote), quote.get('sender_id', ''))
            else:
                with self.lock:
                    entry = self.entries.get((chat_id, sender_id))
                    if entry and entry['expires'] <= self.clock():
                        self.entries.pop((chat_id, sender_id), None)
                        entry = None
                if is_video:
                    row = self._verified(chat_id, exact_row(msg, chat_id, self.db), sender_id)
                elif entry:
                    row = self._verified(chat_id, exact_row(entry['msg'], chat_id, self.db), sender_id)
                elif re.search(r'这(?:个|段)?视频|刚才.{0,8}(?:视频|那段)|视频[里中]|看看.{0,6}视频|视频.{0,5}(?:讲什么|说什么|什么意思|什么内容)|这段片|片子里', str(getattr(msg, 'content', '') or '')):
                    row = self._recover(chat_id, sender_id)
                    if row is None:
                        return VideoContext(note='未找到这位成员在当前会话最近发送的视频，当前没有视频画面或对白；可请对方引用具体视频。')
                else:
                    return None
            if row is None:
                return VideoContext(note='未能准确定位本次视频，当前没有视频画面或对白，不能猜测内容。')
            identity = (row['shard'], row['local_id'], row['sort_seq'], allow_frames)
            if entry and entry.get('identity') == identity and entry.get('context'):
                return entry['context']
            path = video_cache_path(self.db, row)
            if path is None and self.opener is not None and chat is not None:
                path = self.opener(chat, row, self.db, video_cache_path)
            if path is None:
                return VideoContext(note='这段视频尚未读取到电脑微信中的完整文件。自动打开未能完成或未准确定位气泡；请对方先在电脑微信点开视频、等下载完成后再问。当前未拿到视频画面和声音，不能只根据封面编造内容。')
            blocks, note = self.analyzer(path, allow_frames=allow_frames)
            if not is_video and not quote:
                note = '以下是同一位成员最近发送的视频资料，可用于理解追问；换话题时不要复述视频。\n' + note
            context = VideoContext(blocks, note)
            if entry and (blocks or '【对白开始】' in note):
                with self.lock:
                    entry.update(identity=identity, context=context)
            return context
        except Exception as exc:
            print('视频读取失败：', type(exc).__name__, flush=True)
            return VideoContext(note='视频暂未成功读取，当前没有可靠的视频画面和对白；如实说明，不要假装看过。')
