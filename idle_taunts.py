"""One-shot, cancellable group follow-up after an unanswered bot reply."""
from secrets import choice
from threading import RLock, Timer
from chat_search import without_links


def sent_ok(result):
    if isinstance(result, dict):
        return result.get('status') == '成功'
    return bool(result)


def generate_idle_taunt(client, model, style, previous):
    prompt = '''你刚在群里回过话，此后一分钟没有人发新消息。
给刚才的聊天对象创作一句轻度挑衅、带梗的催聊，通常10到30字，只输出要发的正文。
可以轻微得意、反问、激将，参考语气“怎么突然安静了，刚才的气势呢？”，但不要固定照抄。
沉默可能是对方忙，不能断言他认输或害怕，不羞辱、威胁或编造关于对方的事实。
根据上下文调整：若在谈伤心事、紧急事务，改为轻松关心或中性追问，不对痛苦挖苦。
只发这一句，不要求对方必须回复，不加@名字、前缀、引号或链接，不要联网查询。
这次的措辞方向：''' + choice(('俏皮反问', '轻轻激一句', '带一点得意的玩笑', '幽默地把话题接回来'))
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{'role': 'system', 'content': style}, *previous, {'role': 'user', 'content': prompt}],
            max_tokens=120, temperature=1.1,
            extra_body={'thinking': {'type': 'disabled'}},
        )
        answer = without_links(response.choices[0].message.content or '').strip('"“”\n ')[:80]
        if answer:
            return answer
    except Exception as exc:
        print('超时接话生成失败：', type(exc).__name__, flush=True)
    # Skip when generation is unavailable; do not replace a sensitive context
    # with an unrelated stock taunt.
    return ''


class IdleTaunts:
    def __init__(self, on_timeout, seconds=60, timer_factory=Timer):
        self.on_timeout = on_timeout
        self.seconds = seconds
        self.timer_factory = timer_factory
        self.lock = RLock()
        self.states = {}
        self.closed = False

    def observe_incoming(self, msg, chat, self_id):
        chat_id = str(getattr(chat, 'who', '') or '')
        if not chat_id.endswith('@chatroom'):
            return None
        if getattr(msg, 'attr', '') != 'friend' or getattr(msg, 'sender_wxid', '') == self_id:
            return None
        return self.activity(chat_id)

    def activity(self, chat_id):
        with self.lock:
            if self.closed:
                return None
            state = self.states.setdefault(chat_id, {'version': 0, 'ticket': None})
            ticket = state['ticket']
            if ticket:
                ticket['timer'].cancel()
            state['ticket'] = None
            state['version'] += 1
            return state['version']

    def arm(self, chat_id, payload, observed_version):
        with self.lock:
            state = self.states.get(chat_id)
            if self.closed or observed_version is None or not state or state['version'] != observed_version:
                return False
            if state['ticket']:
                state['ticket']['timer'].cancel()
            ticket = {'fired': False, 'spent': False}
            timer = self.timer_factory(self.seconds, self._fire, args=(chat_id, ticket, payload))
            ticket['timer'] = timer
            state['ticket'] = ticket
            timer.daemon = True
            timer.start()
            return True

    def _fire(self, chat_id, ticket, payload):
        with self.lock:
            state = self.states.get(chat_id)
            if self.closed or not state or state['ticket'] is not ticket or ticket['fired']:
                return
            ticket['fired'] = True

        def guard(action=None):
            with self.lock:
                state = self.states.get(chat_id)
                valid = not self.closed and state and state['ticket'] is ticket and not ticket['spent']
                if not valid:
                    return None if action else False
                if action is None:
                    return True
                ticket['spent'] = True  # At most one delivery attempt.
                return action()

        try:
            self.on_timeout(payload, guard)
        except Exception as exc:
            print('一分钟接话处理失败：', type(exc).__name__, flush=True)
        finally:
            with self.lock:
                if self.states.get(chat_id, {}).get('ticket') is ticket:
                    self.states[chat_id]['ticket'] = None

    def close(self):
        with self.lock:
            self.closed = True
            for state in self.states.values():
                if state['ticket']:
                    state['ticket']['timer'].cancel()
            self.states.clear()
