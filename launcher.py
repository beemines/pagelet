"""Launch a hidden local server, reuse it on later launches, then open a browser."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser
from app_paths import DATA_DIR, FROZEN

BASE = Path(__file__).resolve().parent


def running_url():
    try:
        info = json.loads((DATA_DIR / 'server.json').read_text(encoding='utf-8'))
        url = info['url']
        # Runtime metadata is never allowed to redirect the browser off this machine.
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.port not in range(8877, 8897):
            return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + '/api/ping', timeout=.6) as response:
            if json.load(response).get('app') == 'local-book-web':
                return url
    except (OSError, ValueError, KeyError):
        pass
    return None


def main():
    url = running_url()
    if not url:
        DATA_DIR.mkdir(parents=True,exist_ok=True)
        python = Path(sys.executable)
        if os.name == 'nt' and python.with_name('pythonw.exe').exists():
            python = python.with_name('pythonw.exe')
        env = os.environ.copy()
        env['PYTHONUTF8'] = '1'
        command=[sys.executable,'--serve'] if FROZEN else [str(python),str(BASE/'server.py')]
        with (DATA_DIR / 'service.log').open('a', encoding='utf-8') as log:
            process = subprocess.Popen(command, cwd=BASE,
                                       env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(60):
            url = running_url()
            if url:
                break
            # Another launcher may have won the server lock; wait for its URL too.
            time.sleep(.15)
    if not url:
        if FROZEN:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,'Pagelet 启动失败。请检查文件是否解压完整，或查看程序旁 data 文件夹中的 service.log。','Pagelet',0x10)
        else: print('启动失败。请查看 data/service.log。')
        return 1
    webbrowser.open(url)
    if not FROZEN:print('Pagelet 已打开：' + url)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
