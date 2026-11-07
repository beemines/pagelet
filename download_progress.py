"""Read the original CLI's plain stderr milestones without exposing its logs."""
import json
from pathlib import Path
import re
import subprocess
import threading
import time


class DownloadError(Exception):
    pass


class DownloadCancelled(Exception):
    pass


def run_download(cli, book_id, directory, env, on_progress, timeout=900, cancelled=None):
    cancelled = cancelled or threading.Event()
    if cancelled.is_set():
        raise DownloadCancelled('下载已终止。')
    process = None
    workers = []
    output = []
    oversized = threading.Event()
    quota_error = threading.Event()
    try:
        process = subprocess.Popen(list(cli) + ['download', book_id, '--json', '--dir', str(directory)],
            cwd=Path(__file__).resolve().parent, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

        def read_result():
            result = process.stdout.read(2_000_001)
            if len(result) > 2_000_000:
                oversized.set()
                process.kill()
            else:
                output.append(result)

        def read_progress():
            try:
                for line in iter(lambda: process.stderr.readline(8192), ''):
                    line = line.strip()
                    if 'quota' in line.lower() and 'exceed' in line.lower():
                        quota_error.set()
                    sample = None
                    known = re.fullmatch(r'(\d{1,3})% \((\d+(?:\.\d+)?) MB / (\d+(?:\.\d+)?) MB\)', line)
                    unknown = re.fullmatch(r'(\d+(?:\.\d+)?) MB', line)
                    if known and 0 <= int(known[1]) <= 100:
                        percent = int(known[1])
                        sample = {'phase': 'finalizing' if percent == 100 else 'transferring', 'percent': percent,
                                  'transferred_bytes': int(float(known[2]) * 1048576),
                                  'total_bytes': int(float(known[3]) * 1048576)}
                    elif unknown:
                        sample = {'phase': 'transferring', 'percent': None,
                                  'transferred_bytes': int(float(unknown[1]) * 1048576), 'total_bytes': None}
                    elif line.startswith('Downloading:'):
                        sample = {'phase': 'connecting', 'percent': None, 'transferred_bytes': 0, 'total_bytes': None}
                    if sample:
                        on_progress(sample)
            except (OSError, ValueError):
                pass

        workers = [threading.Thread(target=read_result, daemon=True), threading.Thread(target=read_progress, daemon=True)]
        for worker in workers:
            worker.start()
        deadline=time.monotonic()+timeout
        while process.poll() is None:
            if cancelled.wait(.1):
                raise DownloadCancelled('下载已终止。')
            if time.monotonic()>=deadline:
                raise DownloadError('下载超时，请检查网络后重试。')
        code=process.wait()
        if cancelled.is_set():
            raise DownloadCancelled('下载已终止。')
        for worker in workers:
            worker.join(timeout=2)
        if code:
            if code == 3:
                raise DownloadError('尚未登录或登录已过期，请重新登录后下载。')
            if quota_error.is_set():
                raise DownloadError('下载额度不足，请检查账号额度后重试。')
            raise DownloadError('下载未完成，请检查账号额度和网络后重试。')
        if oversized.is_set():
            raise DownloadError('下载结果格式异常。')
        try:
            result = json.loads(''.join(output))
        except ValueError:
            raise DownloadError('下载结果格式异常。') from None
        if not isinstance(result, dict):
            raise DownloadError('下载结果格式异常。')
        return result
    except OSError:
        raise DownloadError('无法启动下载，请确认 zlib.exe 和下载目录可用。') from None
    finally:
        if process:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
            for worker in workers:
                worker.join(timeout=2)
            for stream in (process.stdout, process.stderr):
                if stream:
                    stream.close()
