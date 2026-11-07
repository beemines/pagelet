import http.client
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

try:
    import server
except ModuleNotFoundError:
    server = None


class AppTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(server, 'Local web backend has not been implemented')
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent / 'tests')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cli = [sys.executable, str(Path(__file__).parent / 'tests/fixture_cli.py')]
        self.app = server.App(self.root / 'data', cli=self.cli, downloads_dir=self.root / 'books')
        self.addCleanup(self.app.executor.shutdown, wait=True)

    def test_a_live_local_server_exclusively_owns_its_port(self):
        first=server.create_server(self.app,0)
        self.addCleanup(first.server_close)
        with self.assertRaises(OSError):
            duplicate=server.create_server(self.app,first.server_port)
            duplicate.server_close()

    def test_an_older_reusable_listener_is_also_treated_as_occupied(self):
        legacy=server.ThreadingHTTPServer(('127.0.0.1',0),server.BaseHTTPRequestHandler)
        self.addCleanup(legacy.server_close)
        with self.assertRaises(OSError):
            duplicate=server.create_server(self.app,legacy.server_port)
            duplicate.server_close()

    def test_query_metacharacters_stay_literal(self):
        query = '中文 & echo BAD > exploit.txt'
        result = self.app.search({'query': query, 'page': 2, 'format': 'epub', 'language': 'chinese'})
        self.assertEqual(result['books'][0]['name'], query)
        self.assertEqual(result['page'], 2)
        self.assertFalse((self.root / 'exploit.txt').exists())

    def test_bad_queries_and_filters_are_rejected(self):
        for payload in ({'query': ''}, {'query': '--help'}, {'query': 'x', 'page': 0},
                        {'query': 'x', 'format': '--help'}, {'query': 'x', 'language': 'bogus'}):
            with self.subTest(payload=payload), self.assertRaises(server.AppError):
                self.app.search(payload)

    def test_search_stably_orders_pdf_first(self):
        books=[{'id':'1:a','name':'first','extension':'epub'},
               {'id':'2:b','name':'pdf one','extension':'PDF'},
               {'id':'3:c','name':'other','extension':'mobi'},
               {'id':'4:d','name':'pdf two','extension':'pdf'}]
        with mock.patch.object(self.app,'run_cli',return_value={'books':books,'page':2,'total_pages':4}):
            result=self.app.search({'query':'test','page':2})
        self.assertEqual([b['id'] for b in result['books']],['2:b','4:d','1:a','3:c'])
        self.assertEqual(result['page'],2)

    def test_featured_shelf_has_local_covers_and_seeds_matching_details(self):
        self.app.settings['domain']='https://example.com'
        with mock.patch.object(self.app,'run_cli',side_effect=AssertionError('Homepage must not query network')):
            shelf=self.app.featured()
        books=shelf['books']
        self.assertGreaterEqual(len(books),12)
        self.assertTrue(any('一念永恒' in b['name'] for b in books))
        self.assertFalse(any('斗罗大陆' in b['name'] for b in books))
        for book in books:
            self.assertTrue(book['publisher'] and book['authors'])
            self.assertTrue(book['cover'].startswith('/static/covers/home-'))
            self.assertTrue((server.BASE/book['cover'].lstrip('/')).is_file())
            self.assertNotIn('download_url',book)
            self.assertTrue(book['url'].startswith('https://example.com/book/'))
        selected=books[0]
        with mock.patch('server.fetch_details',return_value={'pages':'400','description':'已加载简介'}):
            detail=self.app.book_details({'book_id':selected['id']})
        self.assertEqual(detail['name'],selected['name'])
        self.assertEqual(detail['cover'],selected['cover'])
        self.app.update_settings({'domain':'https://new.example'})
        fresh=self.app.featured()['books'][0]
        self.assertTrue(fresh['url'].startswith('https://new.example/book/'))
        with mock.patch('server.fetch_details',return_value={'description':'新连接下的简介'}):
            self.assertEqual(self.app.book_details({'book_id':fresh['id']})['url'],fresh['url'])

    def test_featured_does_not_serve_untrusted_or_missing_cover_paths(self):
        self.assertEqual(server.local_cover('/static/covers/../../server.py'),'')
        self.assertEqual(server.local_cover('/static/covers/home-does-not-exist.jpg'),'')
        self.assertEqual(server.local_cover('https://evil.invalid/x.jpg'),'')

    def test_search_shows_only_public_metadata_and_detail_merges_cover(self):
        self.app.settings['domain']='https://example.com'
        cover='https://s3proxy-alp2-covers.cdn-zlib.sk/covers/books/test.jpg'
        raw={'books':[{'id':'42:abc','name':'Test','cover':cover,'download_url':'secret',
                       'url':'https://example.com/book/42/abc','authors':['作者']}], 'page':1}
        with mock.patch.object(self.app,'run_cli',return_value=raw):
            search=self.app.search({'query':'Test'})
        self.assertEqual(search['books'][0]['cover'],cover)
        self.assertNotIn('download_url',search['books'][0])
        with mock.patch('server.fetch_details',return_value={'description':'简介 <title>Example</title>','pages':'240','cover':'','url':''}) as fetch:
            details=self.app.book_details({'book_id':'42:abc'})
            again=self.app.book_details({'book_id':'42:abc'})
        self.assertEqual(details['cover'],cover)
        self.assertEqual(details['url'],'https://example.com/book/42/abc')
        self.assertEqual(details['description'],'简介 <title>Example</title>')
        self.assertEqual(details,again)
        self.assertEqual(fetch.call_count,1)

    def test_detail_validates_reference_and_reports_missing_source_metadata(self):
        with mock.patch('server.fetch_details') as fetch:
            with self.assertRaises(server.AppError):
                self.app.book_details({'book_id':'--help'})
            fetch.assert_not_called()
        with mock.patch('server.fetch_details',return_value={'description':'','authors':[]}):
            detail=self.app.book_details({'book_id':'42:abc'})
        self.assertEqual(detail['id'],'42:abc')
        self.assertEqual(detail['description'],'')

    def test_settings_change_discards_inflight_catalog_results(self):
        self.app.settings['domain']='https://old.example'
        def change_settings(*args,**kwargs):
            self.app.update_settings({'domain':'https://new.example'})
            return {'description':'旧域名的简介'}
        with mock.patch('server.fetch_details',side_effect=change_settings) as fetch:
            with self.assertRaises(server.AppError):
                self.app.book_details({'book_id':'42:abc'})
            self.assertEqual(fetch.call_args.args[1]['ZLIB_DOMAIN'],'https://old.example')
        self.assertFalse(self.app.book_cache)
        with mock.patch.object(self.app,'run_cli',side_effect=lambda *args,**kwargs: (self.app.update_settings({'domain':'https://third.example'}), {'books':[]})[1]):
            with self.assertRaises(server.AppError):
                self.app.search({'query':'Test'})

    def test_session_failure_has_actionable_message(self):
        with self.assertRaises(server.AppError) as error:
            self.app.search({'query': 'fail'})
        self.assertEqual(error.exception.code, 'login_required')
        self.assertIn('登录', str(error.exception))

    def test_cli_timeout_returns_error(self):
        with self.assertRaises(server.AppError) as error:
            self.app.run_cli(['search', 'timeout', '--page', '1'], timeout=.1)
        self.assertEqual(error.exception.code, 'timeout')

    def test_missing_login_domain_is_reported_without_opening_a_window(self):
        with mock.patch.dict('os.environ', {'FIXTURE_DEFAULT_DOMAIN': ''}), mock.patch('server.subprocess.Popen'):
            # Config lookup still needs a real subprocess; only replace window creation.
            with mock.patch.object(self.app, 'run_cli', return_value=[{'key':'ZLIB_DOMAIN','value':''}]):
                with self.assertRaises(server.AppError) as error:
                    self.app.open_login()
        self.assertEqual(error.exception.code, 'domain_required')

    def test_login_reuses_original_cli_domain_and_opens_graphical_window(self):
        with mock.patch.object(self.app, 'run_cli', return_value=[{'key':'ZLIB_DOMAIN','value':'https://example.com'}]):
            with mock.patch('server.subprocess.Popen') as launch:
                self.app.open_login()
        args = launch.call_args.args[0]
        self.assertTrue(any(str(arg).endswith('login_gui.py') for arg in args))
        self.assertIn('https://example.com', args)
        self.assertNotIn('--password', args)

    def test_settings_are_persistent_and_invalid_update_is_atomic(self):
        self.app.update_settings({'domain': 'https://example.com', 'proxy': '',
                                  'download_dir': str(self.root / 'new-books')})
        with self.assertRaises(server.AppError):
            self.app.update_settings({'domain': 'http://bad.invalid', 'download_dir': str(self.root / 'wrong')})
        restored = server.App(self.root / 'data', cli=self.cli)
        self.assertEqual(restored.settings['domain'], 'https://example.com')
        self.assertEqual(restored.settings['download_dir'], str(self.root / 'new-books'))
        self.assertTrue((self.root / 'new-books').is_dir())

    def wait_job(self, job_id):
        for _ in range(100):
            job = next(j for j in self.app.state()['jobs'] if j['id'] == job_id)
            if job['status'] not in ('queued', 'running'):
                return job
            time.sleep(.03)
        self.fail('Download never reached a terminal state')

    def test_download_deduplicates_and_persists_success(self):
        first = self.app.start_download({'book_id': '42:abc', 'title': '测试'})
        second = self.app.start_download({'book_id': '42:abc', 'title': '测试'})
        self.assertEqual(first['id'], second['id'])
        job = self.wait_job(first['id'])
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(Path(job['path']).read_bytes(), b'fixture book')
        restored = server.App(self.root / 'data', cli=self.cli)
        self.assertEqual(restored.state()['jobs'][0]['status'], 'completed')

    def test_download_failure_and_invalid_reference(self):
        with self.assertRaises(server.AppError):
            self.app.start_download({'book_id': '--help', 'title': 'bad'})
        job = self.app.start_download({'book_id': '99:bad', 'title': 'bad'})
        self.assertEqual(self.wait_job(job['id'])['status'], 'failed')

    def test_cancel_running_keeps_existing_book_and_cleans_only_its_staging(self):
        self.assertTrue(hasattr(self.app,'cancel_download'))
        directory=self.root/'books';directory.mkdir()
        previous=directory/'fixture.epub';previous.write_bytes(b'previous book')
        unrelated=directory/'.shiye-partials'/'another-task'/'keep.part'
        unrelated.parent.mkdir(parents=True);unrelated.write_bytes(b'other task')
        job=self.app.start_download({'book_id':'45:hang','title':'Cancel'})
        stage=directory/'.shiye-partials'/job['id']
        for _ in range(100):
            if list(stage.glob('*.part')):break
            time.sleep(.03)
        self.assertTrue(list(stage.glob('*.part')))
        self.app.cancel_download({'job_id':job['id']})
        for _ in range(100):
            state=next(j for j in self.app.state()['jobs'] if j['id']==job['id'])
            if state['status']=='cancelled':break
            time.sleep(.03)
        self.assertEqual(state['status'],'cancelled')
        self.assertEqual(previous.read_bytes(),b'previous book')
        self.assertFalse(stage.exists());self.assertEqual(unrelated.read_bytes(),b'other task')

    def test_cancel_queued_job_and_prevent_removing_an_active_record(self):
        self.assertTrue(hasattr(self.app,'cancel_download'))
        first=self.app.start_download({'book_id':'45:hang','title':'First'})
        second=self.app.start_download({'book_id':'46:hang','title':'Second'})
        queued=self.app.start_download({'book_id':'42:abc','title':'Queued'})
        try:
            with self.assertRaises(server.AppError):self.app.remove_download({'job_id':first['id']})
            result=self.app.cancel_download({'job_id':queued['id']})
            self.assertEqual(result['status'],'cancelled')
        finally:
            self.app.cancel_download({'job_id':first['id']});self.app.cancel_download({'job_id':second['id']})

    def test_remove_history_keeps_downloaded_file(self):
        self.assertTrue(hasattr(self.app,'remove_download'))
        job=self.app.start_download({'book_id':'42:abc','title':'Keep file'})
        completed=self.wait_job(job['id']);path=Path(completed['path'])
        self.app.remove_download({'job_id':job['id']})
        self.assertTrue(path.is_file());self.assertFalse(self.app.state()['jobs'])

    def test_delete_file_recycles_only_recorded_file_and_persists_mark(self):
        self.assertTrue(hasattr(self.app,'delete_download_file'))
        job=self.app.start_download({'book_id':'42:abc','title':'Delete file'})
        path=Path(self.wait_job(job['id'])['path']);trash=self.root/'recycled.epub'
        with mock.patch('server.recycle_file',side_effect=lambda p:p.replace(trash)) as recycle:
            self.app.delete_download_file({'job_id':job['id'],'path':'C:\\Windows\\wrong-file'})
            self.app.delete_download_file({'job_id':job['id']})
        self.assertEqual(recycle.call_count,1);self.assertTrue(trash.is_file());self.assertFalse(path.exists())
        self.assertTrue(self.app.state()['jobs'][0]['file_deleted'])
        restored=server.App(self.root/'data',cli=self.cli);self.addCleanup(restored.executor.shutdown,wait=True)
        self.assertTrue(restored.state()['jobs'][0]['file_deleted'])

    def test_delete_rejects_escaped_paths_and_retains_state_on_recycle_failure(self):
        self.assertTrue(hasattr(self.app,'delete_download_file'))
        job=self.app.start_download({'book_id':'42:abc','title':'Protected'})
        completed=self.wait_job(job['id']);path=Path(completed['path'])
        protected=self.root/'protected.epub';protected.write_bytes(b'keep')
        with self.app.lock:self.app.jobs[0]['path']=str(protected)
        with mock.patch('server.recycle_file') as recycle:
            with self.assertRaises(server.AppError):self.app.delete_download_file({'job_id':job['id']})
            recycle.assert_not_called()
        with self.app.lock:self.app.jobs[0]['path']=str(path)
        with mock.patch('server.recycle_file',side_effect=OSError('busy')):
            with self.assertRaises(server.AppError):self.app.delete_download_file({'job_id':job['id']})
        self.assertTrue(path.is_file());self.assertFalse(self.app.state()['jobs'][0].get('file_deleted',False))

    def test_cancellation_before_publish_keeps_an_existing_file(self):
        directory=self.root/'books';directory.mkdir();previous=directory/'fixture.epub';previous.write_bytes(b'original')
        def almost_finished(cli,book_id,stage,env,progress,**kwargs):
            path=Path(stage)/'fixture.epub';path.write_bytes(b'new file');kwargs['cancelled'].set()
            return {'path':str(path)}
        with mock.patch('server.run_download',side_effect=almost_finished):
            job=self.app.start_download({'book_id':'42:abc','title':'Race'})
            result=self.wait_job(job['id'])
        self.assertEqual(result['status'],'cancelled');self.assertEqual(previous.read_bytes(),b'original')

    def test_deleted_or_replaced_file_is_not_sent_to_recycle_again(self):
        job=self.app.start_download({'book_id':'42:abc','title':'Missing'})
        path=Path(self.wait_job(job['id'])['path'])
        with self.app.lock:self.app.jobs[0]['file_identity']=[-1,-1]
        with mock.patch('server.recycle_file') as recycle:
            with self.assertRaises(server.AppError):self.app.delete_download_file({'job_id':job['id']})
            recycle.assert_not_called()
            path.unlink()
            result=self.app.delete_download_file({'job_id':job['id']})
            self.assertEqual(result['file_state'],'missing');recycle.assert_not_called()

    def test_unavailable_saved_directory_does_not_prevent_startup(self):
        occupied = self.root / 'not-a-directory'
        occupied.write_text('occupied', encoding='utf-8')
        self.app.update_settings({'domain': 'https://example.com'})
        settings_path = self.root / 'data/settings.json'
        settings = json.loads(settings_path.read_text(encoding='utf-8'))
        settings['download_dir'] = str(occupied)
        settings_path.write_text(json.dumps(settings), encoding='utf-8')
        restored = server.App(self.root / 'data', cli=self.cli)
        self.addCleanup(restored.executor.shutdown, wait=True)
        self.assertEqual(restored.state()['settings']['download_dir'], str(occupied))
        restored.update_settings({'download_dir': str(self.root / 'recovered')})
        self.assertTrue((self.root / 'recovered').is_dir())

    def test_only_one_server_process_can_own_runtime_files(self):
        lock_path = self.root / 'service.lock'
        script = 'import sys; from pathlib import Path; from server import InstanceLock; lock=InstanceLock(Path(sys.argv[1])); ok=lock.__enter__(); sys.exit(0 if ok else 9)'
        with server.InstanceLock(lock_path) as acquired:
            self.assertTrue(acquired)
            result = subprocess.run([sys.executable, '-c', script, str(lock_path)], cwd=Path(__file__).parent,
                                    capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 9)
        result = subprocess.run([sys.executable, '-c', script, str(lock_path)], cwd=Path(__file__).parent,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0)

    def test_http_rejects_foreign_hosts_origins_and_missing_token(self):
        httpd = server.create_server(self.app, 0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        port = httpd.server_port
        def request(method, path, headers=None, body=None):
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            result = (response.status, response.read())
            conn.close()
            return result
        self.assertEqual(request('GET', '/api/state')[0], 200)
        shelf_status,shelf_body=request('GET','/api/featured')
        self.assertEqual(shelf_status,200)
        first=json.loads(shelf_body)['books'][0]
        self.assertEqual(request('GET',first['cover'])[0],200)
        self.assertEqual(request('GET','/static/covers/../server.py')[0],404)
        self.assertEqual(request('GET', '/api/state', {'Host': 'evil.invalid'})[0], 403)
        self.assertEqual(request('POST', '/api/settings', {'Content-Type': 'application/json'}, '{}')[0], 403)
        headers = {'Content-Type': 'application/json', 'X-Local-Token': self.app.token,
                   'Origin': 'https://evil.invalid'}
        self.assertEqual(request('POST', '/api/settings', headers, '{}')[0], 403)
        headers['Origin'] = f'http://127.0.0.1:{port}'
        self.assertEqual(request('POST', '/api/settings', headers, '{}')[0], 200)
        self.assertEqual(request('GET', '/static/../server.py')[0], 404)

    def test_only_static_assets_use_cache_validators(self):
        httpd=server.create_server(self.app,0)
        threading.Thread(target=httpd.serve_forever,daemon=True).start()
        self.addCleanup(httpd.server_close);self.addCleanup(httpd.shutdown)
        def get(path,headers=None):
            conn=http.client.HTTPConnection('127.0.0.1',httpd.server_port,timeout=3)
            conn.request('GET',path,headers=headers or {})
            response=conn.getresponse();data=response.read();result=(response.status,dict(response.getheaders()),data)
            conn.close();return result
        status,headers,body=get('/static/app.js')
        self.assertEqual(status,200);self.assertIn('ETag',headers)
        self.assertEqual(get('/static/app.js',{'If-None-Match':headers['ETag']})[0],304)
        cover=self.app.featured()['books'][0]['cover']
        self.assertIn('max-age',get(cover)[1]['Cache-Control'])
        self.assertEqual(get('/')[1]['Cache-Control'],'no-store')
        self.assertEqual(get('/api/state')[1]['Cache-Control'],'no-store')


if __name__ == '__main__':
    unittest.main()
