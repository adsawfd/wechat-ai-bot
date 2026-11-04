"""Persistent, per-account group silence controlled only by bound owners."""
import re
import sqlite3
import threading
import unicodedata
from contextlib import closing, contextmanager
from pathlib import Path

STATE = Path(__file__).with_name('群聊静音.sqlite3')
STOP = re.compile(r'(?:闭嘴(?:巴)?(?:一会儿?|一下|吧|了|啊|呀|啦)?|(?:别|不要|不许|不用|不准|先别|先不要)(?:再|继续)?(?:说话|讲话|发言|回复|回话|说了|讲了|发消息|出声|聊天)(?:了|吧|啊|呀|啦|一会儿?|一下)?|(?:停止|结束)(?:自动|群聊)?(?:回复|发言|说话|讲话)|(?:安静|消停)(?:点|一点|一下|一会儿?|吧|了)?)')
RESUME = re.compile(r'(?:现在)?(?:可以(?:继续|再)?(?:说话|讲话|回复|发言)了?|恢复(?:自动)?(?:说话|讲话|回复|发言)|解除静音|取消静音|不用闭嘴了|别闭嘴了)')


def control_intent(text, names=()):
    value=unicodedata.normalize('NFKC',str(text or '')).casefold().strip()
    for name in sorted({unicodedata.normalize('NFKC',str(n)).casefold().strip() for n in (*names,'微信助手') if n},key=len,reverse=True):
        match=re.match(r'^@?'+re.escape(name)+r'(?:[\s,，:：、]+|(?=你|请|先|给我|闭嘴|别|不要|恢复|可以|停止|安静))',value)
        if match:value=value[match.end():].lstrip();break
    value=re.sub(r'^(?:(?:请|麻烦|你|给我|先|现在)[\s,，:：]*){0,4}','',value)
    clause=re.split(r'[，,。!！?？;；\n]',value,maxsplit=1)[0].strip()
    if STOP.fullmatch(clause):return 'mute'
    if RESUME.fullmatch(clause):return 'resume'
    return None


class GroupSilence:
    def __init__(self, account, bosses=(), state=STATE):
        self.account=str(account)
        self.bosses=frozenset(bosses)
        self.state=Path(state)
        self.lock=threading.RLock()
        self.fail_muted=set()

    def connect(self):
        db=sqlite3.connect(str(self.state),timeout=5)
        db.execute('CREATE TABLE IF NOT EXISTS rooms(account TEXT, room TEXT, muted INTEGER NOT NULL, version INTEGER NOT NULL, last_seq INTEGER NOT NULL, PRIMARY KEY(account,room))')
        return db

    def snapshot(self,room):
        if room in self.fail_muted:return True,-1
        try:
            with self.lock,closing(self.connect()) as db:
                row=db.execute('SELECT muted,version FROM rooms WHERE account=? AND room=?',(self.account,room)).fetchone()
            return (bool(row[0]),int(row[1])) if row else (False,0)
        except (OSError,sqlite3.Error):
            print('群聊静音状态读取失败，暂停群聊发送',flush=True)
            return True,-1

    def muted(self,room):return self.snapshot(room)[0]

    def token(self,room):
        muted,version=self.snapshot(room)
        return None if muted else version

    @contextmanager
    def delivery(self,room,token=None):
        with self.lock:
            muted,version=self.snapshot(room)
            yield not muted and (token is None or token==version)

    def control(self,room,sender,text,seq,names=(),quoted=False):
        if not room.endswith('@chatroom') or sender not in self.bosses or quoted:return None
        action=control_intent(text,names)
        if action is None:return None
        answer={'action':action,'ack':False}
        try:
            number=int(seq)
            with self.lock,closing(self.connect()) as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT muted,version,last_seq FROM rooms WHERE account=? AND room=?',(self.account,room)).fetchone()
                muted,version,last=(bool(row[0]),int(row[1]),int(row[2])) if row else (False,0,-1)
                if number<=last:return answer
                target=action=='mute'
                changed=muted!=target
                db.execute('INSERT OR REPLACE INTO rooms VALUES (?,?,?,?,?)',(self.account,room,int(target),version+int(changed),number))
                db.commit()
                self.fail_muted.discard(room)
                answer['ack']=changed
            return answer
        except (ValueError,TypeError,OSError,sqlite3.Error):
            if action=='mute':self.fail_muted.add(room)
            print('群聊静音指令未能保存，未发送确认',flush=True)
            return answer
