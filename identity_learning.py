"""Account-bound identities explicitly taught by verified owners in group chat."""
import json
import re
import sqlite3
import time
import unicodedata
from contextlib import closing
from pathlib import Path
from threading import RLock

from group_profiles import IDENTITY_QUESTION, _mentioned, _normal
from learned_preferences import SECRET

PROMPT = '''判断这条微信群消息是否明确要求长期记住某人的身份或名字。
只有用户明确教你“某人是/叫某名字”或“记住这个人的名字”才记；普通提问、引述、猜测、说别人要求你记住都选none。
自然语言，不限定命令。只提取本句原文中实际出现的名字；名字不能是泛称、账号权限、密码等。
subject填写消息中指代此人的原文，可能是“这个人”、群昵称或微信昵称；name填写用户所教的名字原文。
只返回JSON：{"action":"remember/none","subject":"...","name":"...","confidence":0到1}。拿不准选none。'''
LEARN_HINT = re.compile(r'记住|记下|记着|牢记|别忘|以后|今后|记得|记一下|学会|教你|称呼|名字')


class IdentityMemory:
    def __init__(self, account_id, boss_ids, path=None, clock=time.monotonic):
        self.account_id=str(account_id)
        self.boss_ids=frozenset(boss_ids)
        self.path=str(path or Path(__file__).with_name('群成员学习.sqlite3'))
        self.clock=clock
        self.lock=RLock()
        self.pending={}
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS identities (account TEXT NOT NULL, scope TEXT NOT NULL, member_id TEXT NOT NULL, learned_name TEXT NOT NULL, PRIMARY KEY(account,scope,member_id))')

    def facts(self,scope):
        with self.lock, closing(sqlite3.connect(self.path)) as db, db:
            rows=db.execute('SELECT member_id,learned_name FROM identities WHERE account=? AND scope=?',(self.account_id,str(scope))).fetchall()
        return dict(rows)

    def store(self,scope,member_id,name):
        with self.lock, closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO identities(account,scope,member_id,learned_name) VALUES(?,?,?,?) ON CONFLICT(account,scope,member_id) DO UPDATE SET learned_name=excluded.learned_name',
                       (self.account_id,str(scope),str(member_id),str(name)))

    @staticmethod
    def _members(members):
        return {m.get('username'):m for m in members if isinstance(m,dict) and m.get('username')} if isinstance(members,list) else {}

    def _resolve_subject(self,subject,scope,members,profiles,self_id):
        subject=_normal(subject).lstrip('@').strip()
        if not subject or subject in ('这个人','这人','他','她','对方','人','这个','谁'):
            return None
        by_id=self._members(members)
        matches=set()
        extras=profiles.group_aliases(scope)
        for who,item in by_id.items():
            if who==self_id: continue
            aliases=[item.get('nick_name'),item.get('remark'),*extras.get(who,[])]
            if any(_normal(a)==subject for a in aliases if a):matches.add(who)
        return next(iter(matches)) if len(matches)==1 else None

    def teach(self,client,model,scope,sender_id,text,at_ids,members,profiles,self_id):
        if (sender_id not in self.boss_ids or not str(scope).endswith('@chatroom') or not LEARN_HINT.search(text)
                or SECRET.search(text) or not self._members(members)):
            return None
        by_id=self._members(members)
        raw_native=set(at_ids or ())-{self_id,'notify@all'}
        native=raw_native & set(by_id)
        obvious=bool(native and re.search(r'(?:是|叫)\s*(?!谁|啥|什么|不是)[A-Za-z0-9\u4e00-\u9fff]',text))
        unconfirmed={'status':'unconfirmed','message':'这条身份信息没有确认保存，请再说一次。'}
        try:
            response=client.with_options(timeout=8).chat.completions.create(
                model=model,messages=[{'role':'system','content':PROMPT},{'role':'user','content':text}],
                response_format={'type':'json_object'},max_tokens=160,extra_body={'thinking':{'type':'disabled'}})
            value=json.loads(response.choices[0].message.content or '{}')
            confidence=value.get('confidence')
            if value.get('action')!='remember' or isinstance(confidence,bool) or not isinstance(confidence,(int,float)) or not .9<=confidence<=1:
                return unconfirmed if obvious else None
            name,subject=value.get('name'),value.get('subject')
            if not isinstance(name,str) or not isinstance(subject,str):return unconfirmed if obvious else None
            name=name.strip()
            if (not 1<=len(name)<=32 or any(ch in '@＠<>[]\r\n' or unicodedata.category(ch).startswith('C') for ch in name)
                    or _normal(name) not in _normal(text) or SECRET.search(name)
                    or name in ('这个人','这人','他','她','谁','老板','主人','管理员')):
                return {'status':'unconfirmed','message':'没能确认要记住的名字，请说清楚。'}
            if raw_native != native:
                return {'status':'unconfirmed','message':'未能确认被@的人还在群里，请重新@一次。'}
            if len(native)>1:
                return {'status':'unconfirmed','message':'这次提到了多个人，请只@要记住的那一位。'}
            named_target=self._resolve_subject(subject,scope,members,profiles,self_id)
            if native and named_target and named_target not in native:
                return {'status':'unconfirmed','message':'提到的名字和@对象不一致，请再说明要记住谁。'}
            if native and not named_target:
                normalized_subject=_normal(subject)
                generic=bool(re.fullmatch(r'(?:我@(?:的)?|我艾特(?:的)?|我说的|@)?(?:这个人|这人|这位|这位群友|他|她|对方)',normalized_subject))
                own=by_id.get(self_id,{})
                own_aliases={_normal(own.get('nick_name')),_normal(own.get('remark'))}
                explicit_at=(normalized_subject.startswith('@') and normalized_subject[1:].strip() not in own_aliases
                             and normalized_subject in _normal(text))
                if not generic and not explicit_at:
                    return {'status':'unconfirmed','message':'没能确认说的是被@的人，请再说明一次。'}
            target=next(iter(native)) if native else named_target
            if not target:
                return {'status':'unconfirmed','message':'没能唯一确认这个人，请@一下要记住的那位。'}
            self.store(scope,target,name)
            return {'status':'saved','message':'记住了：这个人是'+name+'。'}
        except Exception as exc:
            print('身份学习判断或保存失败：',type(exc).__name__,flush=True)
            return unconfirmed if obvious else None

    def question(self,scope,text,at_ids,members,self_id,profiles):
        if not IDENTITY_QUESTION.search(str(text or '')):return False,None,None
        facts=self.facts(scope)
        valid=set(self._members(members))
        raw_native=set(at_ids or ())-{self_id,'notify@all'}
        native=raw_native & valid
        if raw_native != native:return False,None,None
        if native:
            selected=native & set(facts)
            if len(native)==1 and len(selected)==1:
                who=next(iter(selected)); return True,who,facts[who]
            return False,None,None
        by_id=self._members(members)
        extras=profiles.group_aliases(scope)
        matches={who for who,name in facts.items() if who in valid and any(_mentioned(text,alias) for alias in
                 [name,by_id[who].get('nick_name'),by_id[who].get('remark'),*extras.get(who,[])])}
        if len(matches)==1:
            who=next(iter(matches));return True,who,facts[who]
        return (True,None,None) if len(matches)>1 else (False,None,None)

    def remember_pending(self,scope,sender_id,text,at_ids,members,self_id,profiles):
        if self_id in set(at_ids or ()):return
        matched,target,name=self.question(scope,text,at_ids,members,self_id,profiles)
        if not matched or not target or not name:return
        with self.lock:
            now=self.clock()
            self.pending={key:value for key,value in self.pending.items() if now-value[0]<=120}
            self.pending[(scope,sender_id)]=(now,target)
            if len(self.pending)>128:self.pending.pop(next(iter(self.pending)))

    def take_pending(self,scope,sender_id,text,at_ids,members,self_id,bot_names):
        if set(at_ids or ())!={self_id}:return False,None,None
        visible=str(text or '').strip()
        if not visible.startswith('@') or _normal(visible[1:]) not in {_normal(n) for n in bot_names if n}:
            return False,None,None
        with self.lock:
            pending=self.pending.pop((scope,sender_id),None)
        if not pending or self.clock()-pending[0]>120:return False,None,None
        target=pending[1]
        name=self.facts(scope).get(target)
        if target not in self._members(members) or not name:return False,None,None
        return True,target,name
