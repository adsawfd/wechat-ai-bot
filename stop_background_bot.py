"""Stop only the background bot started from this project."""
from pathlib import Path
import psutil

root=Path(__file__).resolve().parent
launcher=root/'.venv'/'Scripts'/'python.exe'
parents=[]
for proc in psutil.process_iter(['exe','cmdline']):
    try:
        if Path(proc.info['exe'] or '').resolve()!=launcher.resolve():
            continue
        args=proc.info['cmdline'] or []
        is_bot=any(arg=='bot.py' or str(Path(arg).resolve())==str(root/'bot.py') for arg in args[1:])
        if is_bot and Path(proc.cwd()).resolve()==root:
            parents.append(proc)
    except (psutil.Error,OSError):
        continue
for proc in parents:
    try:
        children=proc.children(recursive=True)
        for child in reversed(children):
            child.terminate()
        proc.terminate()
    except psutil.Error:
        pass
print('后台机器人已停止。' if parents else '当前没有这个项目的后台机器人。')
