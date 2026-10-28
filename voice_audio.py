"""Offline speech and a temporary, isolated VB-CABLE recording route."""
import math
import json
import os
import re
import time
import unicodedata
import wave
from contextlib import AbstractContextManager
from pathlib import Path


class VoiceUnavailable(RuntimeError):
    pass


RECOVERY_FILE = Path(__file__).with_name('.voice_audio_recovery.json')


def recover_audio_route(path=RECOVERY_FILE):
    """Recover our saved routing after a killed bot, without overriding new choices."""
    if not path.exists():
        return False
    import psutil
    from pycaw.pycaw import AudioUtilities
    from pycaw.constants import ERole
    saved = json.loads(path.read_text(encoding='utf-8'))
    try:
        process = psutil.Process(saved['pid'])
        if abs(process.create_time() - saved['process_started']) < .01:
            raise VoiceUnavailable('另一个语音发送仍在运行，本次跳过')
    except psutil.NoSuchProcess:
        pass
    enum = AudioUtilities.GetDeviceEnumerator()
    devices = {d.id: d for d in AudioUtilities.GetAllDevices(data_flow=1, device_state=1)}
    for role, previous in saved['defaults']:
        if enum.GetDefaultAudioEndpoint(1, role).GetId() == saved['cable_id']:
            AudioUtilities.SetDefaultDevice(previous, [ERole(role)])
    for device_id, previous in saved['mutes']:
        device = devices.get(device_id)
        if device is not None and bool(device.EndpointVolume.GetMute()) == (device_id != saved['cable_id']):
            device.EndpointVolume.SetMute(previous, None)
    path.unlink()
    return True


VOICE_STYLE = '''
这次对方明确要求语音回复。只生成要说出口的正文，口语自然，通常一到三句，最多150字。
不加“AI助手”、emoji、微信表情码、链接、Markdown、表情包指令或拍一拍指令。
不要声称语音已经发送，发送由程序完成。不冒充任何现实人物的声音。
'''


def wants_voice(text):
    text = str(text or '').strip()
    # Quoted requests and reports about someone else's audio are not commands.
    text = re.sub(r'[“「《"].*?[”」》"]', '', text)
    if re.search(r'(?:别|不要|不用|不必|停止).{0,8}语音', text):
        return False
    if re.search(r'(?:^|[，。！？\s])(?:我|他|她|他们|别人).{0,5}(?:发|用|想|要).{0,8}语音', text):
        return False
    return bool(re.search(
        r'^/语音(?:\s|$)|(?:用|以)语音.{0,6}(?:回复|回答|回我|说|讲|告诉)|'
        r'语音(?:回复|回答|回我)|发(?:一)?(?:条|段|个)?语音(?:吧|吗|给我|试试|听听|$)', text))


def spoken_text(text):
    text = re.sub(r'\[\[.*?\]\]', '', str(text or ''), flags=re.S)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\[[^\]\n]{1,16}\]', '', text)
    text = ''.join(c for c in text if unicodedata.category(c) not in ('So', 'Cs', 'Cf')
                   and c not in '*#`_~\ufe0f\u20e3')
    text = re.sub(r'\s+', ' ', text).strip()
    if not any(c.isalnum() for c in text):
        raise VoiceUnavailable('回复没有可朗读的文字，未录音')
    if len(text) > 200:
        # Keep a complete sentence when available rather than reading a cutoff.
        prefix = text[:200]
        end = max(prefix.rfind(c) for c in '。！？.!?；;')
        text = prefix[:end + 1] if end >= 30 else prefix.rstrip('，,、') + '。'
    return text


def synthesize(text, path, *, profile=None):
    text = spoken_text(text)
    if os.getenv('VOICE_ENGINE', 'edge').strip().lower() != 'sapi':
        try:
            from neural_tts import synthesize_neural
            return synthesize_neural(text, path, profile)
        except Exception as exc:
            # No conversation history or raw request errors go into this log.
            print('自然音色合成暂不可用，改用本机中文声音：', type(exc).__name__, flush=True)
    return _synthesize_local(text, path, profile=profile)


def _synthesize_local(text, path, *, profile=None):
    """Windows SAPI, local generic Chinese voice; treats content as plain text."""
    from win32com.client import Dispatch
    speaker = Dispatch('SAPI.SpVoice')
    voices = speaker.GetVoices()
    chinese = [voices.Item(i) for i in range(voices.Count)
               if '804' in voices.Item(i).GetAttribute('Language').split(';')]
    if not chinese:
        raise VoiceUnavailable('未找到本机中文语音包，未录音')
    speaker.Voice = chinese[0]
    if profile:
        from neural_tts import voice_settings
        speaker.Rate = max(-3, min(3, round(int(voice_settings(profile)['rate'].rstrip('%'))/7)))
    else:
        speaker.Rate = 1
    stream = Dispatch('SAPI.SpFileStream')
    stream.Open(str(path), 3, False)
    try:
        speaker.AudioOutputStream = stream
        speaker.Speak(spoken_text(text), 16)  # SPF_IS_NOT_XML
    finally:
        stream.Close()
    with wave.open(str(path), 'rb') as audio:
        seconds = audio.getnframes() / audio.getframerate()
    if not 0.2 <= seconds <= 50:
        raise VoiceUnavailable('合成语音时长不在可发送范围内，未录音')
    return seconds


def cable_player():
    from win32com.client import Dispatch
    player = Dispatch('SAPI.SpVoice')
    outputs = player.GetAudioOutputs()
    tokens = [outputs.Item(i) for i in range(outputs.Count)]
    matches = [t for t in tokens if t.GetDescription() == 'CABLE Input (VB-Audio Virtual Cable)']
    if len(matches) != 1:
        raise VoiceUnavailable('CABLE Input 播放端未就绪，请完成驱动安装并重启电脑')
    player.AudioOutput = matches[0]
    player.Volume = 100
    return player


def play_wave(player, path, *, asynchronous=False):
    from win32com.client import Dispatch
    stream = Dispatch('SAPI.SpFileStream')
    stream.Open(str(path), 0, False)
    try:
        player.SpeakStream(stream, 1 if asynchronous else 0)
    except BaseException:
        stream.Close()
        raise
    return stream  # Async playback keeps the stream alive until caller closes it.


def check_cable_signal(path):
    """Read only the explicitly selected virtual mic, before touching WeChat."""
    import numpy as np
    import sounddevice as sd
    hosts = sd.query_hostapis()
    devices = sd.query_devices()
    matches = [i for i, d in enumerate(devices)
               if d['name'] == 'CABLE Output (VB-Audio Virtual Cable)'
               and hosts[d['hostapi']]['name'] == 'Windows WASAPI'
               and d['max_input_channels'] >= 2]
    if len(matches) != 1:
        raise VoiceUnavailable('CABLE Output 录音端未就绪，请完成驱动安装并重启电脑')
    chunks = []
    player = cable_player()
    try:
        with sd.InputStream(device=matches[0], samplerate=48000, channels=2,
                            dtype='float32', callback=lambda data, *_: chunks.append(data.copy())):
            # A short excerpt is enough to check the cable, not the physical mic.
            stream = play_wave(player, path, asynchronous=True)
            try:
                time.sleep(0.55)
            finally:
                player.Speak('', 2)  # SPF_PURGEBEFORESPEAK
                stream.Close()
        data = np.concatenate(chunks) if chunks else np.array([])
        rms = float(np.sqrt(np.mean(data * data))) if data.size else 0
        if not math.isfinite(rms) or rms < 0.0002:
            raise VoiceUnavailable('虚拟语音通道没有收到合成语音，未启动微信录音')
    except VoiceUnavailable:
        raise
    except Exception as exc:
        raise VoiceUnavailable('系统录音端不可用：请确认麦克风访问已开启，并完成驱动安装后的重启') from exc


def active_sessions(device):
    from pycaw.api.audiopolicy import IAudioSessionControl2
    sessions = device.AudioSessionManager.GetSessionEnumerator()
    result = []
    for i in range(sessions.GetCount()):
        session = sessions.GetSession(i).QueryInterface(IAudioSessionControl2)
        if session.GetState() == 1:
            result.append(int(session.GetProcessId()))
    return result


class CableRoute(AbstractContextManager):
    """Restore defaults/mute state on every exit; refuse to interrupt active calls."""
    def __init__(self, recovery_path=RECOVERY_FILE):
        self.defaults = []
        self.mutes = []
        self.devices = []
        self.recovery_path = recovery_path

    def __enter__(self):
        from pycaw.pycaw import AudioUtilities
        from pycaw.constants import ERole
        import psutil
        recover_audio_route(self.recovery_path)
        enum = AudioUtilities.GetDeviceEnumerator()
        self.devices = AudioUtilities.GetAllDevices(data_flow=1, device_state=1)
        cable = [d for d in self.devices if d.FriendlyName == 'CABLE Output (VB-Audio Virtual Cable)']
        if len(cable) != 1:
            raise VoiceUnavailable('未找到唯一 CABLE Output 录音端，请完成安装后的重启')
        self.cable = cable[0]
        if any(active_sessions(d) for d in self.devices):
            raise VoiceUnavailable('其他程序正在录音或通话，本次语音跳过，避免打断')
        self.defaults = [(role, enum.GetDefaultAudioEndpoint(1, role.value).GetId())
                         for role in ERole if role.value <= 2]
        self.mutes = [(d, bool(d.EndpointVolume.GetMute())) for d in self.devices]
        saved = dict(pid=os.getpid(), process_started=psutil.Process().create_time(),
                     cable_id=self.cable.id,
                     defaults=[(r.value, d) for r, d in self.defaults],
                     mutes=[(d.id, m) for d, m in self.mutes])
        # Exclusive creation prevents a second bot from changing the same route.
        with self.recovery_path.open('x', encoding='utf-8') as state:
            json.dump(saved, state)
        try:
            for role, _ in self.defaults:
                AudioUtilities.SetDefaultDevice(self.cable.id, [role])
            # A cached application microphone must never pick up room sound.
            for device, _ in self.mutes:
                volume = device.EndpointVolume
                volume.SetMute(device.id != self.cable.id, None)
            if any(enum.GetDefaultAudioEndpoint(1, role.value).GetId() != self.cable.id
                   for role, _ in self.defaults):
                raise VoiceUnavailable('未能确认虚拟麦克风路由，未录音')
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def wechat_is_recording(self, pids):
        cable_users = active_sessions(self.cable)
        other_users = [pid for d in self.devices if d.id != self.cable.id for pid in active_sessions(d)]
        return bool(set(cable_users) & set(pids)) and not other_users

    def __exit__(self, *args):
        from pycaw.pycaw import AudioUtilities
        errors = []
        # Keep physical mics muted until the caller has finished/cancelled recording.
        for role, previous in reversed(self.defaults):
            try:
                AudioUtilities.SetDefaultDevice(previous, [role])
            except Exception as exc:
                errors.append(type(exc).__name__)
        for device, previous in reversed(self.mutes):
            try:
                device.EndpointVolume.SetMute(previous, None)
            except Exception as exc:
                errors.append(type(exc).__name__)
        self.defaults.clear()
        self.mutes.clear()
        if errors:
            raise VoiceUnavailable('恢复原麦克风设置失败，请检查系统声音设置：' + ', '.join(errors))
        self.recovery_path.unlink(missing_ok=True)
        return False
