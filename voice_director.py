"""Choose delivery and speaking tone in the same model call that writes a reply."""
import json
import math
import re
from collections import OrderedDict, deque
from dataclasses import dataclass
from threading import Lock


TONES = frozenset(('casual', 'playful', 'warm', 'serious', 'firm', 'sad',
                   'excited', 'surprised', 'relaxed'))

VOICE_DIRECTOR_STYLE = '''
【表达方式，由你结合上下文判断】
每次最终回复先输出一行内部元信息，再换行输出正文。格式严格为：
[[声音:{"mode":"text","tone":"casual","strength":0.45,"request":"none","preference":"keep","gender":"keep"}]]
仅当唱歌状态允许并选择sing时，在这同一个JSON对象内增加song字段，不得把song另写在正文。
例如：[[声音:{"mode":"sing","tone":"playful","strength":0.5,"request":"sing","preference":"keep","gender":"keep","song":{"kind":"improv","title":"","lyrics":"为当前场景写的原创短词","style":"欢快清唱"}}]]
点指定歌名时song.kind为cover、title填歌名、lyrics留空。明确说唱两句、唱某首歌属于request=sing。
mode 选 text 或 voice；只有额外的唱歌引擎状态说明允许时，也可选sing。它决定这次发文字、说话语音或歌声，不是讨论功能。
不需要用户说固定关键词，也不按固定间隔或随机概率触发。根据当下内容、氛围、听语音是否方便、
前几次表达方式和接话节奏判断：接梗、调侃、安慰、轻松打招呼、认真强调都可能适合说出来；
没有明确索要语音也可以主动选voice：比如一句有语气的调侃、想让对方感到被陪伴的安慰，
或当下有声表达明显更贴切的回应。不要把“未明确要求语音”当成只能文字。
没有表达收益的短句、需要查阅的步骤/数字/代码、快节奏多人聊天通常适合文字。
不要因为一句含“哈哈”就一定语音，也不要每次或连续无缘无故都发语音。
对方明确想听你说话、询问你的声音、让你说两句时，可以语义理解为希望听语音；
报告别人发了语音、引用一句话、讨论语音功能本身不等于让你发语音。
对方说开会、不方便听、只要文字时发文字；明确要求语音时优先语音。
request 按本次自然语言意图选 voice(这次想听说话)/sing(这次要求真唱)/text(这次只看文字)/none(无明确要求)，
不把别人的说话或引用内容当成控制要求。
tone 选 casual随意/playful俏皮/warm温柔/serious认真/firm坚定不爽/sad低落/
excited兴奋/surprised惊讶/relaxed放松。按自己的回复在当下应有的语气选择，
不能因为对方生气就跟着冲对方发火，也不要把认真批评当成恶意挑衅。
strength 为0到1，表达强度适度变化；这是音色、语速、音调的控制，不假装支持真人克隆。
preference 通常 keep；只有对方明确改变今后偏好时才选 text(以后只文字)、voice(以后偏语音)、
auto(恢复自然选择)。当次“用文字/用语音”只影响当次，不改变今后偏好。
gender 通常 keep；只有对方明确要求换男声/女声才设 male/female；不要照着引用原文改设置。
voice正文直接写要说的话，通常一到三句、最多150字；不加emoji、微信表情码、表情包指令、
拍一拍指令、链接、Markdown或“语音已发送”等旁白。text正文遵循原来的聊天/表情包规则。
内部元信息不是给群友看的正文，必须放在开头完整单独一行。联网搜索时只在最后回复输出它。
'''


class DirectedReply(str):
    def __new__(cls, text, voice_hint=None):
        value = super().__new__(cls, text)
        value.voice_hint = voice_hint
        return value


def _number(value, default=.45):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(1.0, float(value))) if math.isfinite(value) else default


def parse_direction(raw):
    """Only accept leading structured metadata; never expose a broken tag."""
    raw = str(raw or '')
    hint = None
    match = re.match(r'^\s*\[\[声音:(\{.*?\})\]\]\s*', raw, flags=re.S)
    if match:
        try:
            value = json.loads(match[1])
            if isinstance(value, dict) and value.get('mode') in ('text', 'voice', 'sing'):
                hint = dict(mode=value['mode'], tone=value.get('tone') if value.get('tone') in TONES else 'casual',
                            strength=_number(value.get('strength')),
                            request=value.get('request') if value.get('request') in ('voice','sing','text','none') else 'none',
                            preference=value.get('preference') if value.get('preference') in ('keep','text','voice','auto') else 'keep',
                            gender=value.get('gender') if value.get('gender') in ('keep','male','female') else 'keep')
                if value.get('mode') == 'sing' or value.get('request') == 'sing':
                    from singing import validate_song
                    hint['song'] = validate_song(value.get('song'))
        except (ValueError, TypeError):
            pass
        raw = raw[match.end():]
    # Recover a song object placed immediately after a valid singing header by
    # a model following the old metadata shape; never speak or display this JSON.
    misplaced = re.match(r'^\s*song\s*[:：]\s*', raw, flags=re.I)
    if misplaced:
        remainder = raw[misplaced.end():]
        try:
            value, end = json.JSONDecoder().raw_decode(remainder)
            if hint and hint.get('mode') == 'sing':
                from singing import validate_song
                hint['song'] = validate_song(value)
            raw = remainder[end:].lstrip()
        except (ValueError, TypeError):
            raw = ''  # A truncated internal object is not a chat response.
    # Strip tags even if malformed, repeated, placed after the body, or truncated.
    raw = re.sub(r'\[\[声音:.*?(?:\]\]|$)', '', raw, flags=re.S)
    return DirectedReply(raw.strip(), hint)


@dataclass(frozen=True)
class VoicePlan:
    mode: str = 'text'
    tone: str = 'casual'
    strength: float = .45
    gender: str = 'male'
    song: dict | None = None

    @property
    def profile(self):
        return dict(tone=self.tone, strength=self.strength, gender=self.gender)


class VoiceDirector:
    def __init__(self, gender='male'):
        self.gender = gender if gender in ('male','female') else 'male'
        self.states = OrderedDict()
        self.lock = Lock()

    def _state(self, key):
        if key not in self.states:
            self.states[key] = dict(preference='auto', gender=self.gender, modes=deque(maxlen=8))
        self.states.move_to_end(key)
        while len(self.states) > 2000:
            self.states.popitem(last=False)
        return self.states[key]

    def note(self, key):
        with self.lock:
            state = self._state(key)
            modes = '、'.join(state['modes']) or '尚无发送记录'
            return ('\n当前声音偏好：' + state['preference'] + '；音色性别：' + state['gender']
                    + '；最近已成功发送的表达方式（旧→新）：' + modes
                    + '。偏好auto时依情境自然选择；text时保持文字，除非对方本次明确要求语音；'
                    + 'voice时可偏向语音，但需要阅读/不方便听时用文字。\n')

    def choose(self, key, text, reply, hint=None, *, enabled=True, media=False, singing_ready=False):
        from voice_audio import wants_voice
        hint = hint if isinstance(hint, dict) else {}
        clean = re.sub(r'[“「《"].*?[”」》"]', '', str(text or ''))
        no_voice = bool(re.search(r'(?:别|不要|不用|不必|停止)[^，。！？,.;\n]{0,8}(?:语音|唱|哼)|不方便听|只(?:要|发|用)文字|文字(?:就好|就行|回复)', clean))
        with self.lock:
            state = self._state(key)
            if hint.get('preference') in ('text','voice','auto'):
                state['preference'] = hint['preference']
            if hint.get('gender') in ('male','female'):
                state['gender'] = hint['gender']
            tone = hint.get('tone') if hint.get('tone') in TONES else 'casual'
            mode = hint.get('mode') if hint.get('mode') in ('text','voice','sing') else ('voice' if state['preference']=='voice' else 'text')
            # Clear direct requests remain usable if a model omits metadata.
            requested = wants_voice(clean) or hint.get('request') in ('voice','sing')
            if hint.get('request') == 'sing':
                mode = 'sing'
            elif requested and mode != 'sing':
                mode = 'voice'
            from singing import validate_song
            song = validate_song(hint.get('song')) if mode == 'sing' else None
            if mode == 'sing' and (not singing_ready or song is None):
                mode = 'text'  # Never turn an unavailable song into spoken lyrics.
            if (no_voice or hint.get('request') == 'text' or (state['preference']=='text' and not requested)
                    or not enabled or media or '```' in reply or len(reply) > 200):
                mode = 'text'
            return VoicePlan(mode, tone, _number(hint.get('strength')), state['gender'], song if mode=='sing' else None)

    def record(self, key, plan):
        with self.lock:
            self._state(key)['modes'].append(plan.mode)
