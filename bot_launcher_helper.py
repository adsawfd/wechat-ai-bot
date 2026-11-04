"""Process inspection for the companion launcher; no bot modules are imported."""
import os
import sys
import time

import psutil


def path_key(path):
    return os.path.normcase(os.path.realpath(path))


def is_bot_process(process, root):
    """Match the project cwd and an actual bot.py script argument exactly."""
    name = process.name().lower()
    if name not in ('python.exe', 'pythonw.exe'):
        return False
    args = process.cmdline()
    if not args or '-c' in args[1:] or '-m' in args[1:]:
        return False
    if path_key(process.cwd()) != path_key(root):
        return False
    target = path_key(os.path.join(root, 'bot.py'))
    for arg in args[1:]:
        if arg.startswith('-'):
            continue
        try:
            candidate = arg if os.path.isabs(arg) else os.path.join(root, arg)
            if path_key(candidate) == target:
                return True
        except (OSError, ValueError):
            continue
    return False


def find_bots(root, processes=None):
    matched, unknown = [], False
    for process in processes if processes is not None else psutil.process_iter():
        try:
            if is_bot_process(process, root):
                matched.append(process)
        except (psutil.NoSuchProcess, psutil.ZombieProcess, ProcessLookupError):
            continue
        except (psutil.AccessDenied, PermissionError):
            try:
                if process.name().lower() in ('python.exe', 'pythonw.exe'):
                    unknown = True
            except (psutil.Error, OSError):
                unknown = True
        except (OSError, ValueError):
            unknown = True
    return matched, unknown


def status(root):
    bots, unknown = find_bots(root)
    if unknown:
        return 'UNKNOWN'
    return 'RUNNING' if bots else 'STOPPED'


def stop(root):
    bots, unknown = find_bots(root)
    if unknown:
        return 'UNKNOWN'
    # Stop only verified bot processes, never unrelated children such as Word.
    pids = {p.pid for p in bots}
    bots.sort(key=lambda p: p.ppid() in pids, reverse=True)
    failed = False
    for process in bots:
        try:
            if is_bot_process(process, root):
                process.terminate()
        except (psutil.NoSuchProcess, psutil.ZombieProcess, ProcessLookupError):
            continue
        except (psutil.Error, OSError, ValueError):
            failed = True
    if bots:
        psutil.wait_procs(bots, timeout=3)
    remaining, uncertain = find_bots(root)
    if failed or uncertain:
        return 'UNKNOWN'
    return 'RUNNING' if remaining else 'STOPPED'


def main():
    root = os.getcwd()
    if not os.path.isfile(os.path.join(root, 'bot.py')):
        print('UNKNOWN')
        return
    action = sys.argv[1] if len(sys.argv) > 1 else 'status'
    print(stop(root) if action == 'stop' else status(root), flush=True)


if __name__ == '__main__':
    main()
