"""Occasional, context-selected pats; never a timer or a random target."""
import re
from collections import OrderedDict, deque
from threading import RLock

PAT_STYLE = '''
你可以根据本群最近的聊天氛围，主动拍一拍当前发言者，不需要等对方命令。适合自然接梗、庆祝好消息、亲切鼓励或轻轻安慰时，偶尔在回复末尾附加内部标记[[拍一拍]]；日常大多数回复不用。
对方明确说“拍我一下/拍一拍我”时可以使用。对方说不要拍、别拍时不能使用；严肃事务、争吵、生气时不用拍一拍。
只拍当前发言者，不让标记携带任何姓名、账号、其他目标或次数，不连续拍、不因对方沉默而拍。
正文不要声称“已经拍了/拍成功了”，动作由程序确认目标后执行；可以自然接一句再附标记。
若回复是表情包标记，将[[拍一拍]]放在整条表情包标记之后。不要解释这个内部标记。
'''
STOP = re.compile(r'(?:别|不要|不许|不用|停止).{0,4}(?:拍我|拍一拍|拍拍|乱拍)')
REQUEST = re.compile(r'拍我(?:一下|一拍)?|拍一拍我|拍拍我|戳我一下')


def extract_pat_intent(answer):
    return answer.replace('[[拍一拍]]', '').strip(), '[[拍一拍]]' in answer


class ProactivePats:
    def __init__(self, *, enabled=True, min_messages=6, max_chats=128):
        self.enabled = enabled
        self.min_messages, self.max_chats = min_messages, max_chats
        self.rooms = OrderedDict()
        self.lock = RLock()

    def _room(self, chat_id):
        if chat_id not in self.rooms:
            self.rooms[chat_id] = dict(messages=0, automatic_turns=deque(maxlen=3),
                                      blocked=OrderedDict(), spent=OrderedDict(), seen=OrderedDict())
        self.rooms.move_to_end(chat_id)
        while len(self.rooms) > self.max_chats:
            self.rooms.popitem(last=False)
        return self.rooms[chat_id]

    def observe_preferences(self, chat_id, sender_id, text):
        with self.lock:
            room = self._room(chat_id)
            if STOP.search(text):
                room['blocked'][sender_id] = None
                while len(room['blocked']) > 128:
                    room['blocked'].popitem(last=False)
            elif REQUEST.search(text):
                room['blocked'].pop(sender_id, None)

    def observe(self, chat_id, sender_id, text, key):
        """Count new group messages, including turns we do not reply to."""
        with self.lock:
            room = self._room(chat_id)
            if key in room['seen']:
                return False
            room['seen'][key] = None
            while len(room['seen']) > 128:
                room['seen'].popitem(last=False)
            room['messages'] += 1
            self.observe_preferences(chat_id, sender_id, text)
            return True

    def can_consider(self, chat_id, sender_id, text, key):
        with self.lock:
            room = self._room(chat_id)
            if not self.enabled or sender_id in room['blocked'] or STOP.search(text) or key in room['spent']:
                return False
            if REQUEST.search(text):
                return True
            turns, sequence = room['automatic_turns'], room['messages']
            return (not turns or sequence-turns[-1] >= self.min_messages) and sum(sequence-t < 20 for t in turns) < 2

    def choose(self, chat_id, sender_id, text, key, *, suggested=False, received_pat=False):
        with self.lock:
            if received_pat:
                return False
            self.observe(chat_id, sender_id, text, key)
            room = self._room(chat_id)
            if not self.can_consider(chat_id, sender_id, text, key):
                return False
            explicit = bool(REQUEST.search(text))
            if not explicit:
                if not suggested:
                    return False
                room['automatic_turns'].append(room['messages'])
            # Reserve before touching the UI; uncertain outcomes are never retried.
            room['spent'][key] = None
            while len(room['spent']) > 128:
                room['spent'].popitem(last=False)
            return True
