"""Windowed portable launcher entry point."""
import json
from pathlib import Path
import sys
import time


def runtime_check(output):
    from app_paths import BASE, CLI_PATH
    import site,subprocess
    site.addsitedir(str(BASE/'vendor'))
    import pythoncom
    from win32com.shell import shell
    from winpty import PTY
    result={'version':'0.0.1','frozen':bool(getattr(sys,'frozen',False)),
            'resources':all((BASE/name).is_file() for name in ['static/index.html','static/app.js','static/login/login.js','featured_books.json'])}
    run=subprocess.run([str(CLI_PATH),'version'],capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=10)
    result['cli']=run.returncode==0 and 'v0.0.12' in run.stdout
    terminal=PTY(80,24)
    terminal.spawn(str(CLI_PATH),cmdline=' version',cwd=str(CLI_PATH.parent))
    text='';deadline=time.monotonic()+8;finished_at=None
    while time.monotonic()<deadline:
        try:text+=terminal.read(blocking=False)
        except Exception:pass
        # ConPTY may deliver its last output after the child has exited.
        if not terminal.isalive():
            if finished_at is None:finished_at=time.monotonic()
            if time.monotonic()-finished_at>.25:break
        time.sleep(.03)
    result['pty']='v0.0.12' in text
    if not result['pty']:
        result['pty_diagnostic']={'text':text[:1500], 'alive':terminal.isalive(), 'exit':terminal.get_exitstatus()}
    try:terminal.cancel_io()
    except Exception:pass
    pythoncom.CoInitialize()
    try:
        operation=pythoncom.CoCreateInstance(shell.CLSID_FileOperation,None,pythoncom.CLSCTX_ALL,shell.IID_IFileOperation)
        result['recycle']=operation is not None
    finally:pythoncom.CoUninitialize()
    result['ok']=all(result[key] for key in ['resources','cli','pty','recycle'])
    Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result['ok'] else 1


def main():
    try:
        if '--check-runtime' in sys.argv:
            return runtime_check(sys.argv[sys.argv.index('--check-runtime')+1])
        if '--serve' in sys.argv:
            from server import main as serve
            serve();return 0
        from launcher import main as launch
        return launch()
    except Exception as error:
        from app_paths import DATA_DIR
        DATA_DIR.mkdir(parents=True,exist_ok=True)
        # Startup diagnostics do not include request bodies or account input.
        with (DATA_DIR/'startup.log').open('a',encoding='utf-8') as log:log.write(type(error).__name__+': '+str(error)+'\n')
        if '--check-runtime' in sys.argv:
            Path(sys.argv[sys.argv.index('--check-runtime')+1]).write_text(json.dumps({'ok':False,'error':type(error).__name__+': '+str(error)}),encoding='utf-8')
        elif '--serve' not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,'Pagelet 无法启动，请确认文件已完整解压到可写文件夹。详细信息见 data/startup.log。','Pagelet',0x10)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
