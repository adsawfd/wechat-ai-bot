"""Read exact native stickers from local WeChat cache; never fetch signed URLs."""
import hashlib
import io
import re
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageOps, ImageStat


def sticker_metadata(content):
    from incoming_context import _xml
    root = _xml(content)
    if root is None:
        return None
    emoji = root if root.tag == 'emoji' else root.find('.//emoji')
    if emoji is None:
        return None
    # Only content hashes are retained. URLs, authentication tokens and AES
    # attributes never enter a model request, a log, or a cached metadata object.
    hashes = []
    for name in ('md5', 'androidmd5', 'externmd5'):
        value = (emoji.get(name) or '').lower()
        if re.fullmatch(r'[0-9a-f]{32}', value) and value not in hashes:
            hashes.append(value)
    return {'hashes': hashes} if hashes else None


def decrypt_cached_sticker(data, cfg_dword, wxid):
    if data.startswith((b'GIF8', b'\x89PNG', b'\xff\xd8\xff', b'RIFF', b'wxgf')):
        return data
    if not cfg_dword or not wxid or len(data) < 16 or len(data) % 16:
        return None
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    # Public format reference: zhuobichen/weflow-cli/scripts/wechat_emoticon.py.
    key = hashlib.md5((str(cfg_dword) + wxid + 'EMOTICON').encode()).digest()
    decrypt = Cipher(algorithms.AES(key), modes.CBC(key)).decryptor()
    plain = decrypt.update(data) + decrypt.finalize()
    try:
        unpad = padding.PKCS7(128).unpadder()
        plain = unpad.update(plain) + unpad.finalize()
    except ValueError:
        pass  # Some native cache versions use zero alignment instead of PKCS7.
    return plain if plain.startswith((b'GIF8', b'\x89PNG', b'\xff\xd8\xff', b'RIFF', b'wxgf')) else None


def _frames(data, max_side=384):
    if not data.startswith(b'wxgf'):
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 16000000:
                return []
            count = min(getattr(image, 'n_frames', 1), 1000)
            indexes = sorted({0, count // 3, count * 2 // 3, count - 1})
            frames = []
            for index in indexes:
                image.seek(index)
                frames.append(image.convert('RGBA').copy())
            return frames
    from wechatauto.media import MediaDownloader
    ffmpeg = MediaDownloader._ffmpeg_exe()
    start = data.find(b'\x00\x00\x00\x01')
    if start < 0:
        start = data.find(b'\x00\x00\x01')
    if start < 0:
        start = 4
    if not ffmpeg:
        return []
    with tempfile.TemporaryDirectory(prefix='wechat_sticker_frames_') as folder:
        if Path(folder).resolve().parent != Path(tempfile.gettempdir()).resolve():
            raise ValueError('Unexpected sticker temp folder')
        source = Path(folder) / 'input.hevc'
        source.write_bytes(data[start:])
        result = subprocess.run([ffmpeg, '-y', '-v', 'error', '-threads', '1', '-f', 'hevc', '-i', str(source),
                        '-vf', "select='not(mod(n,8))',scale='min(" + str(max_side) + ",iw)':-2", '-fps_mode', 'passthrough', '-frames:v', '4',
                        str(Path(folder) / 'frame_%02d.png')], capture_output=True, timeout=10,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            print('表情动图转码未成功，错误类型：', result.returncode, flush=True)
        frames = []
        for path in sorted(Path(folder).glob('frame_*.png'))[:4]:
            with Image.open(path) as image:
                frames.append(image.convert('RGBA').copy())
        return frames


def sticker_sheet(data):
    frames = _frames(data)
    visible = [frame for frame in frames if ImageStat.Stat(frame.convert('L')).stddev[0] > 2]
    frames = visible or frames
    if not frames:
        return None
    sheet = Image.new('RGB', (384 * len(frames), 384), 'white')
    for index, frame in enumerate(frames):
        contained = ImageOps.contain(frame, (376, 376))
        x, y = index * 384 + (384 - contained.width) // 2, (384 - contained.height) // 2
        sheet.paste(contained, (x, y), contained if contained.mode == 'RGBA' else None)
    return sheet


class StickerReader:
    def __init__(self, db):
        self.db = db

    def read(self, metadata):
        if not metadata:
            return None
        base = Path(self.db.account_dir).resolve()
        for digest in metadata.get('hashes', []):
            if not re.fullmatch(r'[0-9a-f]{32}', digest):
                continue
            paths = list(base.glob('cache/*/Emoticon/' + digest[:2] + '/' + digest))
            paths += list(base.glob('business/emoticon/*/' + digest))
            paths += list(base.glob('business/emoticon/*/' + digest[:2] + '/' + digest))
            for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
                if not path.resolve().is_relative_to(base) or not 0 < path.stat().st_size <= 12 * 1024 * 1024:
                    continue
                plain = decrypt_cached_sticker(path.read_bytes(), getattr(self.db, 'cfg_dword', None), self.db.wxid)
                if not plain:
                    continue
                sheet = sticker_sheet(plain)
                if sheet is not None:
                    return sheet
        return None
