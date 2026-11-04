"""Contact-specific tone preferences, keyed by the verified account identifier."""
import json
from pathlib import Path

CONFIG_FILE = Path(__file__).with_name('尊重称呼配置.json')
GENTLE_STYLE = '''
【本次发言者的沟通偏好，优先于玩笑和回怼风格】
对这位已确认的群友保持尊重和耐心，不顶嘴、不回怼、不讽刺、不阴阳怪气，也不用攻击性表情包。
即使她调侃或批评你，也平和接话；可以友善开玩笑，涉及错误或不能答应的事就温和、诚实说明，不必盲目附和。
先听她说、回应她的感受；不要训斥、责备、说教、挖苦或揣测她的动机，不用“你别……”“你应该……”等命令式语气。
她讲夸张故事或玩笑时，不要认定事实或给人贴标签；自然询问或温和接话即可。
本规则仅针对当前发言者，不赋予老板身份，不改变其他群友的风格。
'''


class RespectfulContacts:
    def __init__(self, ids=(), titles=None):
        self.ids = frozenset(str(value) for value in ids if value)
        self.titles = {key:str(value).strip()[:20] for key,value in (titles or {}).items() if key in self.ids and isinstance(value,str) and value.strip()}

    @classmethod
    def load(cls, self_id, config_file=CONFIG_FILE):
        try:
            value = json.loads(config_file.read_text(encoding='utf-8'))
            if value.get('account_id') != self_id:
                return cls()
            contacts=[item for item in value.get('contacts', []) if isinstance(item,dict) and isinstance(item.get('username'),str)]
            return cls((item['username'] for item in contacts),{item['username']:item.get('title') for item in contacts if isinstance(item.get('title'),str)})
        except (OSError, ValueError, AttributeError, TypeError):
            return cls()

    def style_for(self, sender_id):
        if not sender_id or sender_id not in self.ids: return ''
        title=self.title_for(sender_id)
        return GENTLE_STYLE + (f'\n本次发言者的固定称呼是“{title}”，直接称呼她时使用这个称呼，不要称其他人为这个称呼；这不授予老板或电脑操控权限。\n' if title else '')

    def title_for(self,sender_id):
        return self.titles.get(sender_id,'') if sender_id in self.ids else ''

    def address(self,text,sender_id):
        title=self.title_for(sender_id)
        value=str(text or '').strip()
        return title+'，'+value if title and value and title not in value else value
