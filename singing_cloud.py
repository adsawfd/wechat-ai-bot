"""One bounded Doubao O2.0 song request, checking native singing locally."""
import asyncio
import json
import os
import struct
import subprocess
import uuid
import wave
import zlib
from dataclasses import dataclass, field
from pathlib import Path

ENDPOINT = 'wss://openspeech.bytedance.com/api/v3/realtime/dialogue'
CONFIG_FILE = Path(__file__).with_name('唱歌配置.env')
MAX_PACKET = 4 * 1024 * 1024


class SingingUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class SingingConfig:
    api_key: str = field(default='', repr=False)
    app_id: str = field(default='', repr=False)
    access_key: str = field(default='', repr=False)
    enabled: bool = True
    max_seconds: int = 35

    @property
    def ready(self):
        return self.enabled and bool(self.api_key or (self.app_id and self.access_key))

    @classmethod
    def load(cls):
        from dotenv import dotenv_values
        values = dict(dotenv_values(CONFIG_FILE)) if CONFIG_FILE.is_file() else {}
        values.update({k:v for k,v in os.environ.items() if k.startswith(('VOLC_SING_', 'SINGING_'))})
        value = lambda name: str(values.get(name) or '').strip()
        try:
            maximum = max(5, min(45, int(value('SINGING_MAX_SECONDS') or 35)))
        except ValueError:
            maximum = 35
        return cls(value('VOLC_SING_API_KEY'), value('VOLC_SING_APP_ID'), value('VOLC_SING_ACCESS_KEY'),
                   value('SINGING_ENABLED') != '0', maximum)

    def headers(self):
        if not self.ready:
            raise SingingUnavailable('唱歌服务尚未配置，请先填写唱歌配置.env')
        headers = {'X-Api-Resource-Id':'volc.speech.dialog', 'X-Api-Connect-Id':str(uuid.uuid4())}
        if self.api_key:
            headers['X-Api-Key'] = self.api_key
        else:
            headers.update({'X-Api-App-ID':self.app_id, 'X-Api-Access-Key':self.access_key,
                            'X-Api-App-Key':'PlgvMymc7f3tQnJ6'})  # Public fixed protocol value.
        return headers


def encode_event(event, payload=None, session_id=''):
    body = json.dumps(payload or {}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    frame = b'\x11\x14\x10\x00' + struct.pack('>I', event)
    if event >= 100:
        sid = session_id.encode('utf-8')
        if not sid or len(sid) > 128:
            raise SingingUnavailable('Invalid singing session ID')
        frame += struct.pack('>I', len(sid)) + sid
    return frame + struct.pack('>I', len(body)) + body


def decode_event(frame):
    if not isinstance(frame, bytes) or not 8 <= len(frame) <= MAX_PACKET:
        raise SingingUnavailable('Invalid singing protocol packet')
    header = (frame[0] & 15) * 4
    if frame[0] >> 4 != 1 or header < 4 or header > len(frame):
        raise SingingUnavailable('Unsupported singing protocol header')
    kind, flags, encoding, compression = frame[1] >> 4, frame[1] & 15, frame[2] >> 4, frame[2] & 15
    cursor = header
    def number():
        nonlocal cursor
        if cursor + 4 > len(frame):
            raise SingingUnavailable('Truncated singing protocol packet')
        result = struct.unpack_from('>I', frame, cursor)[0]
        cursor += 4
        return result
    def field_bytes():
        nonlocal cursor
        size = number()
        if size > MAX_PACKET or cursor + size > len(frame):
            raise SingingUnavailable('Invalid singing protocol length')
        result = frame[cursor:cursor+size]
        cursor += size
        return result
    if kind == 15:
        code = number()
        raise SingingUnavailable(f'唱歌接口返回错误码 {code}，未改为朗读')
    if kind not in (9, 11) or not flags & 4:
        raise SingingUnavailable('Unexpected singing response type')
    if flags & 3 in (1, 3):
        number()  # Optional sequence precedes the event.
    event = number()
    session = ''
    if event >= 100:
        session = field_bytes().decode('utf-8')
    else:
        # Connect replies may carry a connection-ID field, unlike client requests.
        saved = cursor
        first = field_bytes()
        if cursor == len(frame):
            cursor = saved
        elif not first:
            pass
    payload = field_bytes()
    if cursor != len(frame):
        raise SingingUnavailable('Trailing singing protocol data')
    if compression == 1:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        payload = decoder.decompress(payload, MAX_PACKET + 1)
        if len(payload) > MAX_PACKET or not decoder.eof:
            raise SingingUnavailable('Oversized compressed singing packet')
    elif compression != 0:
        raise SingingUnavailable('Unsupported singing compression')
    # Audio stays binary even if a server labels a TTSResponse as JSON.
    data = json.loads(payload.decode('utf-8')) if encoding == 1 and event != 352 else payload
    return event, session, data


def session_parameters(profile, max_seconds):
    female = profile.get('gender') == 'female'
    speaker = 'zh_female_vv_jupiter_bigtts' if female else 'zh_male_xiaotian_jupiter_bigtts'
    return {
        'tts': {'speaker':speaker, 'audio_config':{'format':'pcm_s16le','sample_rate':24000,'channel':1}, 'extra':{}},
        # Preserve the provider's native music behavior; long role/JSON prompts
        # made live requests fall back to reading lyrics. Style goes in query.
        'dialog': {'extra':{'model':'1.2.1.1', 'enable_music':True, 'input_mod':'text', 'strict_audit':True,
                            'enable_volc_websearch':False}}}


async def _receive(ws, sid=''):
    event, actual_sid, payload = decode_event(await asyncio.wait_for(ws.recv(), 12))
    if sid and event >= 100 and actual_sid != sid:
        raise SingingUnavailable('唱歌会话编号不匹配，未发送')
    if event in (51, 153, 599):
        code = payload.get('status_code', '') if isinstance(payload, dict) else ''
        code = str(code)[:20] if str(code).isdigit() else ''
        raise SingingUnavailable('唱歌服务未完成本次请求' + ('，错误码 '+code if code else ''))
    return event, payload


async def _wait_event(ws, expected, sid=''):
    for _ in range(100):
        event, payload = await _receive(ws, sid)
        if event == expected:
            return payload
    raise SingingUnavailable('唱歌会话状态未就绪')


async def collect_singing(ws, query, profile, config):
    sid = str(uuid.uuid4())
    connected = started = False
    tagged, native = bytearray(), bytearray()
    active_type, clipped, received = '', False, 0
    try:
        await ws.send(encode_event(1))
        await _wait_event(ws, 50)
        connected = True
        await ws.send(encode_event(100, session_parameters(profile, config.max_seconds), sid))
        await _wait_event(ws, 150, sid)
        started = True
        await ws.send(encode_event(501, {'content':query}, sid))
        while True:
            event, payload = await _receive(ws, sid)
            if event == 350:
                active_type = payload.get('tts_type','') if isinstance(payload,dict) else ''
            elif event == 351:
                active_type = ''
            elif event == 352 and active_type in ('sing','default'):
                if not isinstance(payload, bytes):
                    raise SingingUnavailable('唱歌音频格式异常')
                budget = config.max_seconds * 24000 * 2 - received
                target = tagged if active_type == 'sing' else native
                target.extend(payload[:budget])
                received += min(len(payload),budget)
                if len(payload) >= budget:
                    clipped = True
                    break
            elif event == 359:
                break
        pcm = bytes(tagged[:len(tagged)//2*2])
        if len(pcm) < 24000*2:
            # Live O2.0 examples confirmed by the user had tts_type=default.
            # Only accept those when several sustained note heights exist.
            from singing_audio import has_melody
            pcm = bytes(native[:len(native)//2*2])
            if not has_melody(pcm):
                raise SingingUnavailable('这次未检测到足够的旋律，未把朗读当成唱歌发送；可以换个唱法或曲目')
        return bytes(pcm[:len(pcm)//2*2]), clipped
    finally:
        try:
            if started:
                await ws.send(encode_event(102, session_id=sid))
                await asyncio.wait_for(_wait_event(ws, 152, sid), 3)
            if connected:
                await ws.send(encode_event(2))
                await asyncio.wait_for(_wait_event(ws, 52), 3)
        except Exception:
            pass  # Never retry a possibly billed generation.


async def _generate(query, profile, config):
    from websockets.asyncio.client import connect
    try:
        async with asyncio.timeout(65):
            async with connect(ENDPOINT, additional_headers=config.headers(), open_timeout=8,
                               close_timeout=2, max_size=MAX_PACKET, max_queue=8, proxy=None) as ws:
                return await collect_singing(ws, query, profile, config)
    except SingingUnavailable:
        raise
    except Exception as exc:
        # Never expose authorization headers or the service's raw error body.
        raise SingingUnavailable('唱歌服务连接或生成未完成：' + type(exc).__name__) from None


def synthesize_song(query, path, profile=None, config=None):
    config = config or SingingConfig.load()
    if not config.ready:
        raise SingingUnavailable('唱歌服务尚未配置，请先填写唱歌配置.env')
    pcm, clipped = asyncio.run(_generate(query, profile or {}, config))
    from neural_tts import _ffmpeg
    original = Path(path).with_suffix('.song-source.wav')
    try:
        with wave.open(str(original), 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000); wav.writeframes(pcm)
        duration = len(pcm) / (24000 * 2)
        args = [_ffmpeg(), '-nostdin','-hide_banner','-loglevel','error','-y','-i',str(original),
                '-ac','1','-ar','22050','-c:a','pcm_s16le']
        if clipped:
            args += ['-af',f'afade=t=out:st={max(0,duration-.15):.3f}:d=0.15']
        subprocess.run([*args,str(path)],check=True,timeout=10,stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        with wave.open(str(path),'rb') as wav:
            seconds = wav.getnframes()/wav.getframerate()
            if wav.getnchannels()!=1 or wav.getsampwidth()!=2 or not 1 <= seconds <= 46:
                raise SingingUnavailable('歌声格式或时长无效，未录音')
        return seconds
    finally:
        original.unlink(missing_ok=True)
