"""Browser QA with synthetic data; separate from the user's running app."""
from pathlib import Path
import sys
import tempfile
import os

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import App, create_server

with tempfile.TemporaryDirectory(prefix='qa-', dir=ROOT / 'tests') as directory:
    data = Path(directory)
    app = App(data / 'data', cli=[sys.executable, str(ROOT / 'tests/fixture_cli.py')], downloads_dir=data / 'books')
    app.settings['domain'] = 'https://example.com'
    os.environ['FIXTURE_DEMO']='1'
    os.environ['FIXTURE_COUNTER_FILE']=str(data/'calls.txt')
    (ROOT/'tests/preview-runtime.json').write_text(__import__('json').dumps({'counter':str(data/'calls.txt')}),encoding='utf-8')
    httpd = create_server(app, 8899)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        app.executor.shutdown(wait=True)
        (ROOT/'tests/preview-runtime.json').unlink(missing_ok=True)
