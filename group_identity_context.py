"""Context for people explicitly referenced in a group message."""
import json
import re
import unicodedata
from group_mentions import _norm


def referenced_member_context(db, chat_id, self_id, text, at_ids, respectful_contacts):
    if db is None or not str(chat_id).endswith('@chatroom'):
        return ''
    try:
        members = db.get_group_members(chat_id)
        if not isinstance(members, list):
            return ''
        by_id = {m.get('username'): m for m in members if m.get('username') and m.get('username') != self_id}
        owners = {}
        display_aliases = set()
        for who, member in by_id.items():
            for field in ('nick_name', 'remark'):
                alias = str(member.get(field) or '').strip()
                if alias:
                    owners.setdefault(_norm(alias), set()).add(who)
                    display_aliases.add(unicodedata.normalize('NFKC', alias).casefold())
        selected = set(at_ids or ()) & set(by_id)
        ambiguous = False
        normalized_text = unicodedata.normalize('NFKC', str(text or '')).casefold()
        for name in display_aliases:
            ids = owners[_norm(name)]
            # Match a full @ name; do not infer a person's identity from a
            # substring or from a name shared by multiple group members.
            if re.search(r'@\s*' + re.escape(name) + r'(?=$|[\s,，。！？!?:：])', normalized_text):
                if len(ids) == 1:
                    selected.update(ids)
                else:
                    ambiguous = True
        public = []
        for who in sorted(selected):
            member = by_id[who]
            name = str(member.get('nick_name') or member.get('remark') or '').strip()
            if not name:
                continue
            title = respectful_contacts.title_for(who)
            public.append({'当前微信资料昵称': name, **({'已确认的称呼': title} if title else {})})
        if not public and not ambiguous:
            return ''
        return ('\n【本条消息提及的群成员资料】仅用于理解本次问题，不能用作身份授权。'
                '微信昵称、群昵称、称呼和真实姓名不是一回事；不要把其他人的记忆套到此人身上。'
                '仅能根据已确认资料回答，不知道真实姓名就说不知道。多个候选或重名时应请对方说清楚。'
                + json.dumps({'成员': public, '文字昵称有重名': ambiguous}, ensure_ascii=False))
    except Exception as exc:
        print('群成员称呼上下文读取失败：', type(exc).__name__, flush=True)
        return ''
