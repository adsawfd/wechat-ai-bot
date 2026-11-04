"""An additional Beijing-time morning greeting, sharing guarded native sends."""
import json
import threading
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from scheduled_greeting import run_once, STATE

BEIJING=timezone(timedelta(hours=8))
CONFIG=Path(__file__).with_name('scheduled_greeting_morning.json')

def validate(config):
    if not isinstance(config,dict):raise ValueError('配置格式无效')
    for key in ('id','account_id','group_id','member_id','member_group_name','text'):
        if not isinstance(config.get(key),str) or not config[key].strip():raise ValueError('任务字段缺失')
    if not config['group_id'].endswith('@chatroom'):raise ValueError('目标不是群聊')
    if type(config.get('hour')) is not int or not 0<=config['hour']<=23:raise ValueError('小时无效')
    if type(config.get('minute')) is not int or not 0<=config['minute']<=59:raise ValueError('分钟无效')
    return config

def tick(wx,config,now,state_file=STATE,on_sent=None,send_guard=None):
    config=validate(config)
    now=now.replace(tzinfo=BEIJING) if now.tzinfo is None else now.astimezone(BEIJING)
    if now.hour!=config['hour'] or now.minute!=config['minute']:return False
    key='daily:morning:'+config['id']+':'+now.date().isoformat()
    run_once(wx,config,key,state_file=state_file,on_sent=on_sent,send_guard=send_guard)
    return True

def run(wx,enabled,config_file=CONFIG,state_file=STATE,on_sent=None,send_guard=None,sleep=time.sleep):
    if not enabled:return
    try:
        config=validate(json.loads(Path(config_file).read_text(encoding='utf-8')))
        if config['account_id']!=wx._db.get_self_info().get('username'):raise ValueError('机器人账号与任务绑定不同')
    except (OSError,ValueError,TypeError,KeyError):
        print('早安定时任务配置不可用，未启动',flush=True);return
    print('早安定时任务已启用：北京时间每天%02d:%02d；真实@群成员；静音时跳过'%(config['hour'],config['minute']),flush=True)
    while True:
        tick(wx,config,datetime.now(BEIJING),state_file=state_file,on_sent=on_sent,send_guard=send_guard)
        sleep(1)

def start(wx,enabled,on_sent=None,send_guard=None):
    thread=threading.Thread(target=run,args=(wx,enabled),kwargs={'on_sent':on_sent,'send_guard':send_guard},name='morning-greeting',daemon=True)
    thread.start();return thread
