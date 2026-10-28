"""Natural Microsoft Edge voices, with bounded prosody chosen from chat context."""
import asyncio
import os
import shutil
import subprocess
import wave
from pathlib import Path


# Tone names are our prosody profiles, not unsupported Edge SSML emotion tags.
PROFILES = {
    'casual': ('Yunxi', 'Xiaoxiao', 2, 0, 0),
    'playful': ('Yunxia', 'Xiaoyi', 12, 8, 0),
    'warm': ('Yunxi', 'Xiaoxiao', -12, -3, -3),
    'serious': ('Yunyang', 'Xiaoxiao', -2, -4, 0),
    'firm': ('Yunjian', 'Xiaoyi', 5, -6, 2),
    'sad': ('Yunxi', 'Xiaoxiao', -18, -9, -5),
    'excited': ('Yunjian', 'Xiaoyi', 16, 7, 2),
    'surprised': ('Yunxi', 'Xiaoyi', 8, 10, 0),
    'relaxed': ('Yunxi', 'Xiaoxiao', -15, -5, -3),
}


def voice_settings(profile=None):
    from voice_director import _number
    profile = profile if isinstance(profile, dict) else {}
    male, female, rate, pitch, volume = PROFILES.get(profile.get('tone'), PROFILES['casual'])
    gender = profile.get('gender', os.getenv('VOICE_GENDER', 'male'))
    scale = .35 + .65 * _number(profile.get('strength'))
    return dict(voice='zh-CN-' + (female if gender == 'female' else male) + 'Neural',
                rate=f'{round(rate*scale):+d}%', pitch=f'{round(pitch*scale):+d}Hz',
                volume=f'{round(volume*scale):+d}%')


def _ffmpeg():
    executable = shutil.which('ffmpeg')
    if executable:
        return executable
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


async def _download(text, target, settings):
    import edge_tts
    communicator = edge_tts.Communicate(text, **settings, connect_timeout=5, receive_timeout=10)
    await asyncio.wait_for(communicator.save(str(target)), timeout=18)


def synthesize_neural(text, path, profile=None):
    """Only the spoken answer is sent to Microsoft, not the conversation history."""
    path = Path(path)
    target = path.with_suffix('.edge.mp3')
    settings = voice_settings(profile)
    try:
        asyncio.run(_download(text, target, settings))
        if not target.exists() or not 100 <= target.stat().st_size <= 4_000_000:
            raise RuntimeError('No valid natural speech audio')
        subprocess.run([_ffmpeg(), '-y', '-nostdin', '-hide_banner', '-loglevel', 'error',
                        '-i', str(target), '-vn', '-ac', '1', '-ar', '22050',
                        '-acodec', 'pcm_s16le', str(path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        with wave.open(str(path), 'rb') as audio:
            seconds = audio.getnframes()/audio.getframerate()
            if audio.getsampwidth() != 2 or not .2 <= seconds <= 50:
                raise RuntimeError('Natural speech duration or format invalid')
        print('语音音色：', settings['voice'], '语速：', settings['rate'], '音调：', settings['pitch'], flush=True)
        return seconds
    finally:
        target.unlink(missing_ok=True)
