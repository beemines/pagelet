"""Keep native CLI login output visible without handling account credentials."""
from pathlib import Path
import subprocess
import sys


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv) != 3:
        print('登录启动参数无效，请返回网页重试。', flush=True)
        return 2
    cli, domain = sys.argv[1:]
    print('请在原软件的表单中输入邮箱和密码。', flush=True)
    print('本窗口会保留登录结果，便于查看错误原因。\n', flush=True)
    try:
        result = subprocess.run([cli, 'login', '--domain', domain], cwd=Path(__file__).resolve().parent)
        code = result.returncode
    except OSError as error:
        print('无法启动原软件：' + str(error), flush=True)
        code = 1
    if code == 0:
        print('\n登录成功。请返回网页刷新账号。', flush=True)
    else:
        print('\n登录未完成，请查看上方错误提示。可将错误文字反馈给维护者，勿提供密码或 Cookie。', flush=True)
    try:
        input('按回车关闭此窗口…')
    except EOFError:
        pass
    return code


if __name__ == '__main__':
    raise SystemExit(main())
