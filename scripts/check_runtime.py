"""Check the frozen executable itself, including the original CLI and native DLLs."""
from pathlib import Path
import json
import subprocess
import sys


def main():
    executable=Path(sys.argv[1]).resolve()
    report=Path(sys.argv[2]).resolve()
    report.parent.mkdir(parents=True,exist_ok=True)
    report.unlink(missing_ok=True)
    process=subprocess.run([str(executable),'--check-runtime',str(report)],timeout=25,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    result=json.loads(report.read_text(encoding='utf-8'))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if process.returncode or not result.get('ok') or not result.get('frozen'):
        raise SystemExit('Portable runtime check failed.')


if __name__=='__main__':main()
