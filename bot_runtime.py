"""Project-local runtime settings; never minimize unrelated windows."""
import time
from types import MethodType
from threading import get_ident, local

_uia_threads = local()


def configure_runtime():
    from wechatauto import rhythm
    from wechatauto.param import WxParam
    rhythm.set_profile('off')
    rhythm.configure(gap=(0.0, 0.0), burst=0, cooloff=(0.0, 0.0))
    WxParam.LISTEN_INTERVAL = 0.35


def attach_gui(gui):
    if getattr(gui, '_bot_visibility_patch', False):
        return
    primary = gui.main_hwnd
    original_get_uia = gui._get_uia
    gui._bot_uia_thread = None

    def get_uia(instance, refresh=False):
        if not getattr(_uia_threads, 'initialized', False):
            import uiautomation as auto
            auto.InitializeUIAutomationInCurrentThread()
            _uia_threads.initialized = True
        owner = get_ident()
        if instance._bot_uia_thread != owner:
            # uiautomation explicitly disallows reusing a Control from another
            # thread. Group listeners and idle timers use different threads.
            instance._uia = None
            instance._uia_tried = False
            instance._uia_check_ts = 0.0
            instance._last_input_box = None
            instance._bot_uia_thread = owner
        return original_get_uia(refresh=refresh)

    def ensure_visible(instance, keep_topmost=False):
        # The upstream implementation minimizes other windows. This one never does.
        if instance.main_hwnd != primary and instance._input._user32.IsWindow(primary):
            instance.use_window(primary)
        if not instance.is_alive():
            return False
        if not instance.bring_to_front(keep_topmost=False):
            # A WeChat-owned popup may legitimately be the foreground window.
            foreground = instance._input._user32.GetForegroundWindow()
            if not foreground or instance._get_pid(foreground) != instance.pid:
                return False
        instance._update_render_rect()
        instance._last_visible_ok = True
        instance._last_visible_ts = time.time()
        return True

    gui.ensure_visible = MethodType(ensure_visible, gui)
    gui._get_uia = MethodType(get_uia, gui)
    gui._bot_visibility_patch = True
