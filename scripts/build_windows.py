"""Build a clean Windows x64 portable ZIP. Run with Python 3.13 on Windows."""
from pathlib import Path
import argparse
import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from version import VERSION

CLI_VERSION='0.0.12'
CLI_ZIP='zlib_0.0.12_windows_x86_64.zip'
CLI_SHA256='7060b06e0f591f6d93e7e9a27a77259061a0f57b75579fd499fcc4ae0cf9df50'


def run(*args, cwd=ROOT):
    subprocess.run(list(args),cwd=cwd,check=True)


def prepare_cli():
    cache=ROOT/'build/upstream'
    cache.mkdir(parents=True,exist_ok=True)
    archive=cache/CLI_ZIP
    if not archive.exists():
        nearby=ROOT.parent/CLI_ZIP
        if nearby.is_file():shutil.copy2(nearby,archive)
        else:
            url=f'https://github.com/heartleo/zlib/releases/download/v{CLI_VERSION}/{CLI_ZIP}'
            with urllib.request.urlopen(url,timeout=90) as response, archive.open('wb') as target:
                shutil.copyfileobj(response,target)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=CLI_SHA256:
        raise RuntimeError('Upstream zlib ZIP checksum mismatch; remove the cached ZIP and retry.')
    with zipfile.ZipFile(archive) as source:
        member=next(item for item in source.infolist() if Path(item.filename).name=='zlib.exe')
        executable=cache/'zlib.exe'
        executable.write_bytes(source.read(member))
    return executable


def make_icon():
    from PIL import Image,ImageDraw
    image=Image.new('RGBA',(256,256),(0,0,0,0));draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((0,0,255,255),radius=54,fill='#3988f8')
    draw.line([(63,70),(107,70),(128,85),(149,70),(193,70),(193,188),(149,188),(128,202),(107,188),(63,188),(63,70)],fill='white',width=11,joint='curve')
    draw.line([(128,86),(128,196)],fill='white',width=10)
    folder=ROOT/'assets';folder.mkdir(exist_ok=True)
    image.save(folder/'pagelet.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    image.save(folder/'pagelet.png')


def make_archive(folder):
    output=ROOT/'dist'/f'Pagelet-v{VERSION}-windows-x64.zip'
    # Use an explicit distribution root; runtime state is never a release asset.
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for file in sorted(folder.rglob('*')):
            relative=file.relative_to(folder)
            if not file.is_file() or relative.parts[0] in {'data','Downloads'}:continue
            if '__pycache__' in relative.parts or file.suffix in {'.pyc','.log'}:continue
            archive.write(file,Path('Pagelet')/relative)
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    (output.parent/'SHA256SUMS.txt').write_text(f'{digest}  {output.name}\n',encoding='ascii')
    print(f'Release: {output.name} ({output.stat().st_size/1024/1024:.1f} MiB)\nSHA256: {digest}')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--skip-ui',action='store_true')
    parser.add_argument('--archive-only',action='store_true');args=parser.parse_args()
    if sys.platform!='win32':raise SystemExit('Windows is required.')
    folder=ROOT/'dist/Pagelet'
    if args.archive_only:make_archive(folder);return
    if not args.skip_ui:
        npm=shutil.which('npm.cmd') or 'npm.cmd'
        run(npm,'ci',cwd=ROOT/'login-ui');run(npm,'run','build',cwd=ROOT/'login-ui')
    cli=prepare_cli();make_icon()
    run(sys.executable,'-m','PyInstaller','--noconfirm','--clean',str(ROOT/'packaging/pagelet.spec'))
    (folder/'bin').mkdir(exist_ok=True);shutil.copy2(cli,folder/'bin/zlib.exe')
    for name in ['LICENSE','THIRD_PARTY_NOTICES.md','README.md','CHANGELOG.md']:
        shutil.copy2(ROOT/name,folder/name)
    shutil.copytree(ROOT/'licenses',folder/'licenses',dirs_exist_ok=True)
    if (ROOT/'docs/images').is_dir():shutil.copytree(ROOT/'docs/images',folder/'docs/images',dirs_exist_ok=True)
    (folder/'assets').mkdir(exist_ok=True);shutil.copy2(ROOT/'assets/pagelet.png',folder/'assets/pagelet.png')
    run(sys.executable,str(ROOT/'scripts/check_runtime.py'),str(folder/'Pagelet.exe'),str(ROOT/'build/runtime-check.json'))
    make_archive(folder)


if __name__=='__main__':main()
