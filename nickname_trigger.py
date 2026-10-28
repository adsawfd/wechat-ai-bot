"""Follow the logged-in account's current nickname rather than a hardcoded alias."""
import re
import time
import unicodedata
from threading import Lock


def normalized(text):
    return unicodedata.normalize('NFKC', str(text or '')).casefold()


class NicknameTrigger:
    def __init__(self, db, self_id, refresh_seconds=10, clock=time.monotonic):
        self.db = db
        self.self_id = self_id
        self.refresh_seconds = refresh_seconds
        self.clock = clock
        self.next_refresh = float('-inf')
        self.pattern = None
        self.name = ''
        self.aliases = []
        self.lock = Lock()

    def matches(self, content):
        with self.lock:
            now = self.clock()
            if now >= self.next_refresh:
                self.next_refresh = now + self.refresh_seconds
                try:
                    info = self.db.get_self_info()
                    name = normalized(info.get('nick_name')).strip() if info.get('username') == self.self_id else ''
                    if name:
                        self.name = name
                        base = re.sub(r'(?:[ _\-]*v?\d+(?:[.．]\d+)*)$', '', name).strip()
                        aliases = {base} if len(base) >= 2 and base != name else set()
                        self.aliases = sorted(aliases)
                        before = r'(?<![a-z0-9_])' if re.match(r'[a-z0-9_]', name[0]) else ''
                        after = r'(?![a-z0-9_])' if re.match(r'[a-z0-9_]', name[-1]) else ''
                        self.pattern = re.compile(before + re.escape(name) + after)
                    else:
                        self.pattern = None
                        self.name, self.aliases = '', []
                except Exception as exc:
                    # No stale alias triggers if current identity cannot be read.
                    self.pattern = None
                    self.name, self.aliases = '', []
                    print('微信昵称刷新失败：', type(exc).__name__, flush=True)
            return bool(self.pattern and self.pattern.search(normalized(content)))

    def reference_hint(self, content):
        # Short names are candidates, never an unconditional exact-name trigger.
        self.matches('')
        with self.lock:
            text = normalized(content)
            if not self.name:
                return None
            hinted = any(alias in text for alias in self.aliases)
            hinted = hinted or bool(re.search(r'机器人|助手|人工智能|(?<![a-z])ai(?![a-z])|你.*(?:开发|模型|版本|联网|程序)', text))
            return {'nickname': self.name, 'aliases': list(self.aliases)} if hinted else None
