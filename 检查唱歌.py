"""Default: read-only setup check. --preview: two paid local previews, no WeChat sends."""
import argparse
import importlib.util
import json
from pathlib import Path
from singing import song_query
from singing_cloud import SingingConfig, SingingUnavailable, synthesize_song

parser=argparse.ArgumentParser(description='检查唱歌配置；--preview会调用付费唱歌接口生成两个本机试听文件，不发微信')
parser.add_argument('--preview',action='store_true')
args=parser.parse_args()
config=SingingConfig.load()
print(json.dumps(dict(credentials_present=bool(config.api_key or (config.app_id and config.access_key)),
                     enabled=config.enabled,model='1.2.1.1',max_seconds=config.max_seconds,
                     websocket_dependency=importlib.util.find_spec('websockets') is not None),ensure_ascii=False))
if args.preview:
    if not config.ready:
        raise SystemExit('请先在唱歌配置.env中填入并启用服务凭证；未调用付费接口。')
    folder=Path(__file__).with_name('singing_previews')
    folder.mkdir(exist_ok=True)
    samples=[('improv',dict(kind='improv',lyrics='今天风很轻，烦恼先暂停。',style='温柔轻快清唱')),
             ('cover',dict(kind='cover',title='两只老虎',style='轻快清唱'))]
    for name,song in samples:
        path=folder/(name+'.wav')
        try:
            seconds=synthesize_song(song_query(song),path,dict(gender='male'),config)
            print(json.dumps(dict(sample=name,seconds=round(seconds,1),audio=str(path),
                                 singing_checked=True,needs_listening=True),ensure_ascii=False),flush=True)
        except SingingUnavailable as exc:
            print(json.dumps(dict(sample=name,error=str(exc),not_retried=True),ensure_ascii=False),flush=True)
