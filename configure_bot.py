"""Read local WeChat identities and bind owners without sending messages."""
import argparse
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='本机账号绑定辅助工具，不发送微信消息；输出含本机标识，请勿公开。')
    parser.add_argument('--bind-owners',nargs='+',metavar='微信昵称或备注')
    parser.add_argument('--show-group',metavar='群名')
    parser.add_argument('--replace',action='store_true',help='明确替换现有的称呼配置.json')
    args=parser.parse_args()
    from wechatauto.db import WeChatDB
    from bot_account import open_bound_database
    config=Path(__file__).with_name('称呼配置.json')
    db=open_bound_database() if config.exists() else WeChatDB()
    self_info=db.get_self_info()
    self_id=self_info.get('username')
    if not self_id:raise SystemExit('无法确认当前微信账号。')
    if args.bind_owners:
        people=[]
        for name in args.bind_owners:
            matches={p['username']:p for p in db.search_contact(name)
                     if not str(p.get('username') or '').endswith('@chatroom') and
                     name in (str(p.get('nick_name') or ''),str(p.get('remark') or ''))}
            if len(matches)!=1:raise SystemExit('无法唯一匹配昵称或备注，请换用唯一的好友备注：'+name)
            person=next(iter(matches.values()))
            if person['username']==self_id:raise SystemExit('不能把机器人自己设为管理员。')
            people.append({'username':person['username'],'label':name})
        if len({p['username'] for p in people})!=len(people):raise SystemExit('重复选择了同一个联系人。')
        value={'account_id':self_id,'boss_contacts':people}
        mode='w' if args.replace else 'x'
        try:
            with config.open(mode,encoding='utf8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
        except FileExistsError:raise SystemExit('配置已存在；核对后使用 --replace 才会替换。')
        print('管理员已按实际账号绑定，重启机器人后生效。此配置勿上传。')
    elif args.show_group:
        groups=[g for g in db.get_groups() if g.get('name')==args.show_group]
        if len(groups)!=1:raise SystemExit('群名无法唯一匹配，请使用唯一群名。')
        group_id=groups[0]['username']
        print(json.dumps({'account_id':self_id,'group_id':group_id,'members':db.get_group_members(group_id)},ensure_ascii=False,indent=2))
        print('以上是本机资料昵称/备注，未保证包含群昵称；不要把输出上传到公开仓库。')
    else:
        print(json.dumps({'account_id':self_id,'nickname':self_info.get('nick_name','')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
