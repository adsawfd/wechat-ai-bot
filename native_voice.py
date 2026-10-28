"""Send synthesized speech using WeChat's own native voice-message recorder."""
import tempfile
import time
from pathlib import Path

from group_mentions import _display_name, _norm, _ready_input, _layout
from voice_audio import (CableRoute, VoiceUnavailable, synthesize, cable_player,
                         check_cable_signal, play_wave, recover_audio_route)


def _result(status, message, **data):
    return {'status': status, 'message': message, 'data': data}


def _walk(root):
    stack, visited = [(root, 0)], 0
    while stack and visited < 1500:
        node, depth = stack.pop()
        visited += 1
        if node is None or depth > 50:
            continue
        try:
            if getattr(node, 'IsOffscreen', False):
                continue
            yield node
            stack.extend((child, depth + 1) for child in node.GetChildren())
        except Exception:
            continue


def _voice_controls(root):
    """Only the right side of the input toolbar; never chat-message text."""
    areas = [node for node in _walk(root)
             if str(node.AutomationId or '').rsplit('.', 1)[-1] == 'chatinput_toolbar_right_view']
    if len(areas) != 1:
        return None, None, None
    buttons = [n for n in _walk(areas[0])
               if n.ControlTypeName == 'ButtonControl' and getattr(n, 'IsEnabled', True)]
    start = [n for n in buttons if str(n.Name or '').strip().startswith('发语音')]
    cancel = [n for n in buttons if str(n.Name or '').strip() == '取消']
    send = [n for n in buttons if str(n.Name or '').strip() == '发送语音']
    unique = lambda values: values[0] if len(values) == 1 else None
    return unique(start), unique(cancel), unique(send)


class NativeRecorder:
    def __init__(self, chat):
        self.chat = chat
        actual = getattr(chat, 'chat', None) or chat
        self.gui = getattr(actual, '_gui', None)
        if not isinstance(getattr(self.gui, 'main_hwnd', None), int):
            raise VoiceUnavailable('微信原生语音界面不可用')
        self.uia, self.input = _ready_input(chat, self.gui)
        if self.input is None:
            raise VoiceUnavailable('未确认目标会话输入框，未发送语音')
        if self.uia._read_edit_value(self.input) != '':
            raise VoiceUnavailable('输入框有草稿或无法读取，保留草稿，本次语音跳过')
        self.target = _display_name(chat)
        start, cancel, send = self.controls()
        if start is None or cancel is not None or send is not None:
            raise VoiceUnavailable('原生录音入口未就绪，或已有录音，未启动')
        self.start_button = start
        self.opened = False
        self.submitted = False

    def controls(self):
        return _voice_controls(self.uia._anchor(self.gui.main_hwnd))

    def same_chat(self):
        root = self.uia._anchor(self.gui.main_hwnd)
        title, _, _ = _layout(root, self.target)
        return _norm(title) == _norm(self.target)

    def open(self):
        if not self.same_chat():
            raise VoiceUnavailable('会话已切换，未启动语音')
        self.opened = True  # Include partially successful clicks in cleanup.
        if not self.uia._click_ctrl(self.start_button):
            raise VoiceUnavailable('未确认微信录音是否启动，不重试')
        for _ in range(10):
            _, cancel, send = self.controls()
            if cancel is not None and send is not None:
                return
            time.sleep(.1)
        raise VoiceUnavailable('微信未进入原生录音状态，已取消，不重试')

    def guarded(self):
        import win32gui
        foreground = win32gui.GetForegroundWindow()
        _, cancel, send = self.controls()
        return (self.gui._get_pid(foreground) == self.gui.pid and self.same_chat()
                and cancel is not None and send is not None)

    def cancel(self):
        if self.opened:
            start, cancel, _ = self.controls()
            if start is None and cancel is None:
                self.gui.ensure_visible()
                start, cancel, _ = self.controls()
            if cancel is not None:
                self.uia._click_ctrl(cancel)
                for _ in range(10):
                    if self.controls()[1] is None:
                        self.opened = False
                        return
                    time.sleep(.1)
                raise VoiceUnavailable('录音取消状态未确认，请手动点微信录音条的叉号')
            if start is None:
                raise VoiceUnavailable('无法确认录音是否结束，请手动点微信录音条的叉号')
            self.opened = False

    def submit(self):
        if not self.guarded():
            raise VoiceUnavailable('会话、焦点或录音状态变化，取消本次语音')
        _, _, send = self.controls()
        self.submitted = True  # A failed click can still submit; never retry.
        if not self.uia._click_ctrl(send):
            raise VoiceUnavailable('语音已尝试提交，结果未确认，不自动重发')
        for _ in range(10):
            if self.controls()[1] is None:
                self.opened = False
                return
            time.sleep(.1)


def _row_key(row):
    return (str(row.get('shard') or ''), str(row.get('local_id')), str(row.get('sort_seq')))


def confirmed_voice(rows, baseline, self_id, started):
    matches = []
    for row in rows:
        try:
            native = row.get('type') == '语音' or int(row.get('local_type') or 0) & 0xffffffff == 34
            if (native and row.get('sender_username') == self_id
                    and _row_key(row) not in baseline
                    and float(row.get('create_time') or 0) >= started - 1):
                matches.append(row)
        except (TypeError, ValueError):
            continue
    return matches[0] if len(matches) == 1 else None


def _wechat_pids(gui):
    import psutil
    parent = psutil.Process(gui.pid)
    return {parent.pid} | {p.pid for p in parent.children(recursive=True)}


def _deliver(chat, text, db, self_id, folder, *, prepared=None):
    if prepared is None:
        path = folder / 'reply.wav'
        seconds = synthesize(text, path)
    else:
        path, seconds = prepared
    check_cable_signal(path)
    recorder = NativeRecorder(chat)
    chat_id = str(getattr(chat, 'who', '') or '')
    if not chat_id or not self_id:
        raise VoiceUnavailable('缺少会话或账号身份，未录音')
    baseline = {_row_key(r) for r in db.get_messages(chat_id, limit=30)}
    started = time.time()
    pids = _wechat_pids(recorder.gui)
    with CableRoute() as route:
        try:
            recorder.open()
            ready = False
            for _ in range(12):
                if route.wechat_is_recording(pids) and recorder.guarded():
                    ready = True
                    break
                time.sleep(.1)
            if not ready:
                raise VoiceUnavailable('未确认微信使用虚拟麦克风，取消录音，未发送')
            player = cable_player()
            stream = play_wave(player, path, asynchronous=True)
            try:
                deadline = time.monotonic() + min(seconds + 3, 53)
                while not player.WaitUntilDone(100):
                    if time.monotonic() > deadline:
                        raise VoiceUnavailable('合成语音播放超时，取消录音')
                    if not route.wechat_is_recording(pids) or not recorder.guarded():
                        raise VoiceUnavailable('录音来源或目标会话变化，取消语音')
                time.sleep(.2)
                if not route.wechat_is_recording(pids):
                    raise VoiceUnavailable('发送前虚拟麦克风状态变化，取消语音')
                recorder.submit()
            finally:
                player.Speak('', 2)
                stream.Close()
        finally:
            recorder.cancel()
    for _ in range(12):
        row = confirmed_voice(db.get_messages(chat_id, limit=30), baseline, self_id, started)
        if row is not None:
            return _result('成功', '已在目标会话确认原生语音条', duration=round(seconds, 1),
                           local_id=row.get('local_id'), native_type=34)
        time.sleep(.25)
    return _result('未确认', '已尝试提交原生语音，数据库尚未确认，不自动重发')


def send_native_voice(chat, text, db, self_id, *, profile=None):
    """Exactly one native submission, with no text/audio-file fallback."""
    import pythoncom
    from wechatauto.utils import LockManager
    pythoncom.CoInitialize()
    try:
        with tempfile.TemporaryDirectory(prefix='wechat_voice_') as folder:
            path = Path(folder) / 'reply.wav'
            # Network synthesis takes place before acquiring the WeChat UI lock.
            seconds = synthesize(text, path, profile=profile)
            with LockManager.acquire():
                return _deliver(chat, text, db, self_id, Path(folder), prepared=(path, seconds))
    except VoiceUnavailable as exc:
        return _result('失败', str(exc))
    except Exception as exc:
        return _result('失败', '原生语音处理失败，不自动重发：' + type(exc).__name__)
    finally:
        pythoncom.CoUninitialize()


def send_prepared_native_voice(chat, path, db, self_id):
    """Send validated generated song audio through the same native recorder."""
    import pythoncom
    import wave
    from wechatauto.utils import LockManager
    pythoncom.CoInitialize()
    try:
        path = Path(path).resolve(strict=True)
        if not path.is_file() or path.stat().st_size > 5_000_000:
            raise VoiceUnavailable('歌声音频文件无效，未录音')
        with wave.open(str(path),'rb') as audio:
            seconds = audio.getnframes()/audio.getframerate()
            if (audio.getnchannels()!=1 or audio.getsampwidth()!=2 or audio.getframerate()!=22050
                    or not 1 <= seconds <= 46):
                raise VoiceUnavailable('歌声必须为可发送的单声道PCM音频，未录音')
        with LockManager.acquire():
            return _deliver(chat, '[歌声片段]', db, self_id, path.parent, prepared=(path,seconds))
    except VoiceUnavailable as exc:
        return _result('失败',str(exc))
    except Exception as exc:
        return _result('失败','歌声原生语音发送未完成，不重试：'+type(exc).__name__)
    finally:
        pythoncom.CoUninitialize()


def recover_voice_audio():
    """Restore an interrupted earlier voice route once when the bot starts."""
    import pythoncom
    pythoncom.CoInitialize()
    try:
        if recover_audio_route():
            print('已恢复上次语音中断前的麦克风设置', flush=True)
    except Exception as exc:
        print('语音设置恢复待检查：', str(exc), flush=True)
    finally:
        pythoncom.CoUninitialize()
