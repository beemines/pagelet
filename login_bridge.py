"""Drive the original zlib login TUI privately through a Windows pseudoterminal."""
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

BASE = Path(__file__).resolve().parent


class LoginError(Exception):
    pass


def validate_credentials(email, password):
    if not email.strip() or '@' not in email or any(c.isspace() for c in email):
        raise LoginError('请输入正确的账号邮箱。')
    if not password:
        raise LoginError('请输入密码。')
    if any(ord(c) < 32 or ord(c) == 127 for c in email + password):
        raise LoginError('账号或密码含有无法输入的控制字符，请重新输入。')
    if len(email) > 320 or len(password) > 1024:
        raise LoginError('账号或密码过长，请检查输入。')


def plain_terminal(text):
    text = re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)', '', text)
    return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)


def _failure(text):
    lowered = text.lower()
    if 'incorrect email or password' in lowered:
        return '邮箱或密码不正确，请检查后重试。'
    if 'authorization failed' in lowered:
        return '书库拒绝了密码登录。请先确认网页端能否登录；此账号可能需要使用原软件的 Cookie 导入方式。'
    if 'domain' in lowered and any(s in lowered for s in ('not configured', 'not allowed', 'invalid', 'requires')):
        return '访问域名无效，请返回网页设置重新检测。'
    if any(s in lowered for s in ('timeout', 'timed out', 'connect', 'deadline', 'no such host', 'unreachable')):
        return '连接书库失败，请在网页设置中检查域名或代理。'
    return '登录未完成，请检查账号和连接设置后重试。'


def login(cli, domain, email, password, cancelled, timeout=100, env=None):
    validate_credentials(email, password)
    if cancelled.is_set():
        raise LoginError('已取消登录。')
    sys.path.insert(0, str(BASE / 'vendor'))
    try:
        from winpty import PTY
    except ImportError:
        raise LoginError('登录组件缺失，请检查程序文件夹中的 vendor 目录。') from None
    pty = None
    text = ''
    sent = False
    started = time.monotonic()
    try:
        args = list(cli) + ['login', '--domain', domain, '--email', email.strip()]
        pty = PTY(100, 30)
        environment = None if env is None else '\0'.join(f'{key}={value}' for key, value in env.items()) + '\0'
        pty.spawn(args[0], cmdline=' ' + subprocess.list2cmdline(args[1:]), cwd=str(BASE), env=environment)
        finished_at = None
        while True:
            if cancelled.is_set():
                raise LoginError('已取消登录。')
            if time.monotonic() - started > timeout:
                raise LoginError('登录超时，请检查网络后重试。')
            try:
                chunk = pty.read(blocking=False)
            except Exception:
                chunk = ''
                if pty.isalive():
                    raise LoginError('无法读取登录窗口，请重新打开后重试。') from None
            if chunk:
                # Respond only to terminal capability queries; no application commands.
                if '\x1b[6n' in chunk:
                    pty.write('\x1b[1;1R')
                text = (text + plain_terminal(chunk))[-32000:]
                if not sent and 'Password' in text and 'ctrl+s' in text:
                    # Email is prefilled by the original CLI. Bracketed paste keeps
                    # Unicode and shell symbols literal in its masked password field.
                    pty.write('\t\x1b[200~' + password + '\x1b[201~\x13')
                    password = ''
                    sent = True
            if not pty.isalive():
                if finished_at is None:
                    finished_at = time.monotonic()
                if time.monotonic() - finished_at > .15:
                    code = pty.get_exitstatus()
                    if sent and code == 0 and 'Logged in successfully' in text:
                        return True
                    raise LoginError(_failure(text))
            cancelled.wait(.025)
    except LoginError:
        raise
    except Exception:
        # Never forward PTY errors or transcripts: they may contain account input.
        raise LoginError('无法启动登录组件，请关闭窗口后重试。') from None
    finally:
        password = ''
        text = ''
        if pty:
            try:
                if pty.isalive():
                    os.kill(pty.pid, signal.SIGTERM)
                pty.cancel_io()
            except Exception:
                pass
