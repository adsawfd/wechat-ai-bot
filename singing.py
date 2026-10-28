"""Validated song intent and singing-only native audio delivery."""
import re
import tempfile
from pathlib import Path
from singing_cloud import SingingConfig, SingingUnavailable, synthesize_song


def validate_song(value):
    if not isinstance(value, dict) or value.get('kind') not in ('cover','improv'):
        return None
    clean = {}
    for key, maximum in (('title',80),('lyrics',100),('style',80)):
        text = value.get(key) or ''
        if not isinstance(text, str) or len(text)>maximum or re.search(r'https?://|wxid_|[A-Za-z]:\\|(?:sk-|Bearer )[A-Za-z0-9_-]{10,}',text):
            return None
        clean[key] = re.sub(r'\[\[.*?\]\]', '', text, flags=re.S).strip()
    if value['kind']=='cover':
        if not clean['title']:
            return None
        clean['lyrics']=''  # Request a licensed catalog title, never generate cover lyrics in chat.
    elif not clean['lyrics']:
        return None
    return dict(kind=value['kind'], **clean)


def singing_available():
    return SingingConfig.load().ready


def singing_note():
    if not singing_available():
        return '\n唱歌引擎尚未接通。当前只能说话，不能真实演唱；对方要求唱歌时如实说明暂未开通，不输出歌词假装唱过，不选择sing。\n'
    return '''
唱歌引擎已配置，支持点曲库歌曲片段和原创短句。可按本次意思和聊天氛围自然选择sing，不需要固定命令，不连续无缘故演唱。
选择sing时内部元信息的mode设sing，request在对方明确要求演唱时设sing，否则none；在同一个声音JSON里面增加song对象，不能另起一行写到正文中：
点歌："song":{"kind":"cover","title":"准确歌名，可带歌手用于消歧","lyrics":"","style":"轻松清唱"}
即兴："song":{"kind":"improv","title":"","lyrics":"本次原创小歌的主题或新写的创意短句，最多60字","style":"随氛围选择的演唱风格"}
只有用户要唱某首歌时才填对应歌名；不知道歌名就先问，不能从引文擅自点歌。原曲歌词不要在正文或song中补写，只把歌名交给曲库。
原创主题或短词不包含群成员账号、私人资料或聊天记录，唱歌引擎可围绕主题扩写原创小段。演唱正文简短即可，不写完整歌词，不声称已经发送；实际歌声由独立引擎生成。
若在讨论谁唱歌、复述别人点歌、询问功能或用户不方便听，不等于本次要求演唱。一次原生语音只唱一个短段，曲库之外歌曲不能保证。
'''


def song_query(song):
    song = validate_song(song)
    if song is None:
        raise SingingUnavailable('本次演唱目标不完整，未调用唱歌服务')
    if song['kind']=='cover':
        request = f'请用唱歌的方式，唱《{song["title"]}》的一小段，保持原曲旋律。'
    else:
        request = f'请用唱歌的方式，唱一首关于“{song["lyrics"]}”的原创小歌。'
    if song['style']:
        request += f'风格{song["style"]}。'
    return request + '直接开唱，只唱一小段。'


def send_singing_reply(chat, song, db, self_id, *, profile=None):
    native_attempted = False
    try:
        query = song_query(song)
        with tempfile.TemporaryDirectory(prefix='wechat_singing_') as folder:
            path=Path(folder)/'song.wav'
            synthesize_song(query,path,profile)
            from native_voice import send_prepared_native_voice
            native_attempted = True
            return send_prepared_native_voice(chat,path,db,self_id)
    except SingingUnavailable as exc:
        return {'status':'失败' if native_attempted else '未生成','message':str(exc),'data':None}
    except Exception as exc:
        return {'status':'失败' if native_attempted else '未生成','message':'歌声流程未完成：'+type(exc).__name__,'data':None}
