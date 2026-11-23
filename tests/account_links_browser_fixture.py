"""Isolated loopback Pagelet server for the external account-link browser test."""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import App, create_server


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(dir=ROOT / 'tests') as directory:
        data = Path(directory)
        app = App(data / 'data', cli=[sys.executable, str(ROOT / 'tests/fixture_cli.py')], downloads_dir=data / 'books')
        app.settings['domain'] = 'https://zlib.bz'
        with create_server(app, 0) as httpd:
            print(f'http://127.0.0.1:{httpd.server_port}', flush=True)
            httpd.serve_forever()
