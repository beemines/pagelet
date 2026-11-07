"""Sanitized README screenshots; no account, network or real download operations."""
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server import App,create_server


class DemoApp(App):
    def state(self):
        value=super().state();value['has_session']=False
        return value

    def profile(self):
        return {'name':'Demo','quota_known':True,'daily_remaining':10,'daily_allowed':10}

    def book_details(self,payload):
        return next(book for book in self.featured()['books'] if book['id']==payload['book_id'])


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='docs-',dir=ROOT/'build') as directory:
        app=DemoApp(Path(directory)/'data',cli=[sys.executable,str(ROOT/'tests/fixture_cli.py')])
        app.settings.update(domain='https://z-lib.gd',download_dir='Downloads')
        app.jobs=[
            {'id':'demo-1','book_id':'1:demo','title':'Pride and Prejudice','status':'running','phase':'downloading','percent':64,'transferred_bytes':6710886,'total_bytes':10485760,'created_at':'2026-11-06T10:20:00+08:00'},
            {'id':'demo-2','book_id':'2:demo','title':'操作系统：精髓与设计原理','status':'completed','path':'Downloads\\操作系统.pdf','transferred_bytes':15728640,'created_at':'2026-11-06T10:18:00+08:00'},
            {'id':'demo-3','book_id':'3:demo','title':'The Little Prince','status':'completed','path':'Downloads\\The Little Prince.epub','transferred_bytes':2097152,'created_at':'2026-11-06T10:15:00+08:00'},
        ]
        server=create_server(app,8899)
        try:server.serve_forever()
        finally:server.server_close();app.executor.shutdown(wait=True)
