"""Local once-per-day group greeting; never retry an uncertain submission."""
import json
import msvcrt
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import nullcontext

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'scheduled_greeting.json'
STATE = ROOT / 'scheduled_greeting_state.json'
BEIJING = timezone(timedelta(hours=8))


def claim(state_file, key):
    lock_stream = None
    try:
        lock_stream = state_file.with_suffix('.lock').open('a+b')
        lock_stream.seek(0)
        msvcrt.locking(lock_stream.fileno(), msvcrt.LK_NBLCK, 1)
        data = json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {}
        if not isinstance(data, dict):
            raise ValueError('invalid state')
        if data.get(key):
            return False
        data[key] = True
        tmp = state_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, state_file)
        return True
    except Exception as exc:
        print('定时问候状态无法保存，跳过以避免重复：', type(exc).__name__, flush=True)
        return False
    finally:
        if lock_stream is not None:
            try:
                lock_stream.seek(0)
                msvcrt.locking(lock_stream.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            lock_stream.close()


def send_greeting(wx, config, send_guard=None):
    from group_mentions import _send_native
    from wechatauto.utils import LockManager
    from wechatauto.wx import Chat, _AllMessageChat
    group_id = config['group_id']
    member_id = config['member_id']
    if not group_id.endswith('@chatroom'):
        raise ValueError('无效的群标识')
    members = wx._db.get_group_members(group_id)
    if sum(m.get('username') == member_id for m in members) != 1:
        raise ValueError('目标成员不在群内或无法唯一确认')
    name = wx._db.get_nickname(group_id)
    if not name or name == group_id:
        raise ValueError('无法确认目标群')
    chat = _AllMessageChat(group_id, name,
                           factory=lambda who: Chat(who, wx._gui, wx._db), db=wx._db)
    with LockManager.acquire():
        with send_guard(group_id) if send_guard is not None else nullcontext(True) as allowed:
            if not allowed:
                return {'status':'跳过','message':'该群已静音，未发送定时问候','data':None}
            actual = chat.chat
            if actual is None:
                raise ValueError('无法打开目标群')
            return _send_native(chat, actual._gui, config['text'], config['member_group_name'],
                                require_mention=True)


def run_once(wx, config, key, state_file=STATE, on_sent=None, send_guard=None):
    if not claim(state_file, key):
        return
    try:
        result = send_greeting(wx, config, send_guard=send_guard) if send_guard is not None else send_greeting(wx, config)
        print('定时问候结果：', result.get('status'), result.get('message'), flush=True)
        from group_engagement import delivery_succeeded
        if on_sent is not None and delivery_succeeded(result):
            on_sent(config)
    except Exception as exc:
        print('定时问候未完成，不自动重发：', type(exc).__name__, flush=True)


def restore_confirmed_test(config, state_file, on_sent, now):
    """Restore one user-confirmed test after restart; never send a message."""
    if on_sent is None:
        return
    try:
        data = json.loads(state_file.read_text(encoding='utf-8'))
        expires = datetime.fromisoformat(config['test_expires']) + timedelta(hours=12)
        if data.get('test_success_confirmed') and now <= expires and claim(state_file, 'test_followup_restored'):
            on_sent(config)
            print('已恢复刚才确认成功的问候接话状态。', flush=True)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('问候接话状态未恢复：', type(exc).__name__, flush=True)


def run(wx, enabled, config_file=CONFIG, state_file=STATE, sleep=time.sleep, on_sent=None, send_guard=None):
    if not enabled:
        print('定时问候未启用：当前自动发送关闭。', flush=True)
        return
    try:
        config = json.loads(config_file.read_text(encoding='utf-8'))
        for field in ('account_id','group_id','member_id','member_group_name','text'):
            if not isinstance(config.get(field),str) or not config[field].strip():
                raise ValueError('配置字段缺失')
        if config['account_id'] != wx._db.get_self_info().get('username'):
            raise ValueError('账号绑定不匹配')
        hour,minute=config.get('hour',20),config.get('minute',0)
        if type(hour) is not int or type(minute) is not int or not 0<=hour<=23 or not 0<=minute<=59:
            raise ValueError('定时时间无效')
    except (OSError, ValueError, KeyError, TypeError):
        print('定时问候配置不可用，未启动。', flush=True)
        return
    print('定时问候已启用：北京时间每天%02d:%02d；启动时不额外测试或补发。'%(hour,minute), flush=True)
    while True:
        now = datetime.now(BEIJING)
        if now.hour == hour and now.minute == minute:
            run_once(wx, config, 'daily:' + now.date().isoformat(), state_file, on_sent=on_sent, send_guard=send_guard)
        sleep(1)


def start(wx, enabled, on_sent=None, send_guard=None):
    thread = threading.Thread(target=run, args=(wx, enabled), kwargs={'on_sent':on_sent,'send_guard':send_guard}, name='daily-greeting', daemon=True)
    thread.start()
    return thread
