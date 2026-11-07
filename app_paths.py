"""Resource and writable paths for source and portable Windows builds."""
from pathlib import Path
import sys


def resolve_layout(frozen, executable, resources):
    resources=Path(resources)
    application=Path(executable).parent if frozen else resources
    return {'resources':resources,'application':application,'data':application/'data',
            'downloads':application/'Downloads' if frozen else resources.parent/'电子书',
            'cli':application/'bin/zlib.exe' if frozen else resources.parent/'zlib-windows-v0.0.12/zlib.exe'}


FROZEN=bool(getattr(sys,'frozen',False))
PATHS=resolve_layout(FROZEN,sys.executable,Path(__file__).resolve().parent)
BASE=PATHS['resources']
APP_DIR=PATHS['application']
DATA_DIR=PATHS['data']
DOWNLOAD_DIR=PATHS['downloads']
CLI_PATH=PATHS['cli']
DEFAULT_DOMAIN='https://z-lib.gd' if FROZEN else ''
