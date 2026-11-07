"""Loopback-only web adapter for the installed zlib CLI and local Vue login."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
import mimetypes
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid
from login_bridge import LoginError, login, validate_credentials
from book_catalog import CatalogError, fetch_details, public_book
from download_progress import run_download, DownloadCancelled
from recycle_file import recycle_file
from app_paths import DATA_DIR, DOWNLOAD_DIR, CLI_PATH, DEFAULT_DOMAIN
from version import APP_NAME, VERSION

BASE = Path(__file__).resolve().parent
FORMATS = {'', 'epub', 'pdf', 'mobi', 'azw3', 'djvu', 'txt', 'fb2'}
LANGUAGES = {'', 'chinese', 'english', 'japanese', 'korean', 'french', 'german', 'russian', 'spanish'}


class AppError(Exception):
    def __init__(self, message, code='invalid_request'):
        super().__init__(message)
        self.code = code


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def clean_error(raw):
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', raw or '')
    text = ''.join(c for c in text if c.isprintable() or c == '\n')
    return text.strip()[:700]


def local_cover(value):
    if not isinstance(value, str) or not re.fullmatch(r'/static/covers/home-[a-z0-9-]+\.(jpg|png|webp)', value):
        return ''
    root = (BASE / 'static/covers').resolve()
    file = (BASE / value.lstrip('/')).resolve()
    return value if file.is_relative_to(root) and file.is_file() else ''


class App:
    def __init__(self, data_dir=None, cli=None, downloads_dir=None):
        self.data_dir = Path(data_dir or DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        binary = CLI_PATH
        self.cli = list(cli or [str(binary)])
        defaults = {'domain': DEFAULT_DOMAIN, 'proxy': '', 'download_dir': str(downloads_dir or DOWNLOAD_DIR)}
        saved = load_json(self.data_dir / 'settings.json', {})
        self.settings = {**defaults, **{k: v for k, v in saved.items() if k in defaults and isinstance(v, str)}}
        self.lock = threading.RLock()
        self.book_seeds = {}
        self.book_cache = {}
        self.catalog_revision = 0
        self.catalog_slots = threading.BoundedSemaphore(3)
        featured = load_json(BASE / 'featured_books.json', {})
        self.featured_books = featured.get('books', []) if isinstance(featured, dict) else []
        self.featured_records = {}
        for book in self.featured_books:
            if isinstance(book, dict) and re.fullmatch(r'[0-9]+:[A-Za-z0-9]+', str(book.get('id', ''))):
                if local_cover(book.get('local_cover')):
                    self.featured_records[book['id']] = book
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='book-download')
        self.download_controls = {}
        self.download_futures = {}
        self.token = secrets.token_urlsafe(32)
        self.login_process = None
        self.auth_thread = None
        self._auth_cancel = threading.Event()
        self._auth = {'status': 'idle', 'error': ''}
        self._cancelled_auth = {}
        self.jobs = load_json(self.data_dir / 'downloads.json', [])
        if not isinstance(self.jobs, list):
            self.jobs = []
        for job in self.jobs:
            if job.get('status') in ('queued', 'running', 'cancelling'):
                job.update(status='failed', error='上次运行已中断，请重新下载。')
        self._save_jobs()

    def _save_jobs(self):
        save_json(self.data_dir / 'downloads.json', self.jobs[-200:])

    def featured(self):
        books = []
        with self.lock:
            for record in self.featured_books:
                if not isinstance(record, dict) or record.get('id') not in self.featured_records:
                    continue
                book = public_book(record, self.settings['domain'], description_is_text=True)
                book['cover'] = local_cover(record.get('local_cover'))
                if not book['cover']:
                    continue
                self.book_seeds[book['id']] = dict(book)
                books.append(book)
            while len(self.book_seeds) > 400:
                self.book_seeds.pop(next(iter(self.book_seeds)))
        return {'books': books}

    def environment(self, settings=None):
        env = os.environ.copy()
        env['PYTHONUTF8'] = '1'
        if settings is None:
            with self.lock:
                settings = self.settings.copy()
        values = settings
        for key, field in [('ZLIB_DOMAIN', 'domain'), ('ZLIB_PROXY', 'proxy')]:
            if values[field]:
                env[key] = values[field]
        env['ZLIB_DOWNLOAD_DIR'] = values['download_dir']
        return env

    def run_cli(self, args, timeout=75, env=None):
        try:
            result = subprocess.run(self.cli + list(args), cwd=BASE, env=env if env is not None else self.environment(),
                                    stdin=subprocess.DEVNULL, capture_output=True, encoding='utf-8',
                                    errors='replace', timeout=timeout,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired:
            raise AppError('连接超时。请在设置中重新检测域名，或检查代理后重试。', 'timeout') from None
        except FileNotFoundError:
            raise AppError('找不到 zlib.exe，请保留原软件文件夹及名称。', 'cli_missing') from None
        except OSError as error:
            raise AppError('无法启动软件：' + clean_error(str(error)), 'cli_error') from None
        if result.returncode:
            detail = clean_error(result.stderr)
            if result.returncode == 3:
                raise AppError('尚未登录或登录已过期，请点击“登录账号”。', 'login_required')
            raise AppError(detail or '操作失败，请检查域名、账号和下载额度。', 'cli_error')
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise AppError('软件返回了无法识别的结果，请确认 zlib 版本。', 'cli_error') from None

    def search(self, payload):
        query = str(payload.get('query', '')).strip()
        if not query or len(query) > 300 or query.startswith('-'):
            raise AppError('请输入有效的书名、作者或 ISBN（最多 300 个字符）。')
        try:
            page = int(payload.get('page', 1))
        except (TypeError, ValueError):
            raise AppError('页码无效。') from None
        extension, language = payload.get('format', ''), payload.get('language', '')
        if not 1 <= page <= 10000 or extension not in FORMATS or language not in LANGUAGES:
            raise AppError('搜索筛选条件无效。')
        args = ['search', query, '--json', '--count', '20', '--page', str(page)]
        if extension:
            args += ['--ext', extension]
        if language:
            args += ['--language', language]
        with self.lock:
            settings, revision = self.settings.copy(), self.catalog_revision
        result = self.run_cli(args, env=self.environment(settings))
        if not isinstance(result, dict) or not isinstance(result.get('books'), list):
            raise AppError('搜索结果格式异常。', 'cli_error')
        with self.lock:
            if revision != self.catalog_revision:
                raise AppError('连接设置已更改，请重新搜索。', 'settings_changed')
            domain = settings['domain']
            result['books'] = [public_book(book, domain) for book in result['books'] if isinstance(book, dict)]
            result['books'].sort(key=lambda book: book.get('extension', '').lower() != 'pdf')
            for book in result['books']:
                if book.get('id'):
                    self.book_seeds[book['id']] = dict(book)
            while len(self.book_seeds) > 400:
                self.book_seeds.pop(next(iter(self.book_seeds)))
        return result

    def book_details(self, payload):
        book_id = payload.get('book_id', '')
        if not isinstance(book_id, str) or not re.fullmatch(r'[0-9]+:[A-Za-z0-9]+', book_id):
            raise AppError('图书编号无效，请重新搜索后选择。')
        with self.lock:
            settings, revision = self.settings.copy(), self.catalog_revision
            domain = settings['domain']
            cached = self.book_cache.get(book_id)
            if cached and cached[0] > time.monotonic():
                return dict(cached[1])
            seed = dict(self.book_seeds.get(book_id) or public_book(self.featured_records.get(book_id, {}), domain, description_is_text=True))
        if not self.catalog_slots.acquire(blocking=False):
            raise AppError('正在读取其他图书详情，请稍后再试。', 'busy')
        try:
            detail = fetch_details(self.cli, self.environment(settings), book_id)
        except CatalogError as error:
            raise AppError(str(error), 'catalog_error') from None
        finally:
            self.catalog_slots.release()
        detail = {**seed, **{key:value for key,value in detail.items() if value}, 'id': book_id}
        # Re-apply public field and link restrictions after merging cached search data.
        detail = public_book(detail, domain, description_is_text=True)
        featured = self.featured_records.get(book_id)
        if featured and local_cover(featured.get('local_cover')):
            detail['cover'] = featured['local_cover']
        with self.lock:
            if revision != self.catalog_revision:
                raise AppError('连接设置已更改，请重新搜索后查看详情。', 'settings_changed')
            self.book_cache[book_id] = (time.monotonic() + 300, detail)
            while len(self.book_cache) > 200:
                self.book_cache.pop(next(iter(self.book_cache)))
        return dict(detail)

    def state(self):
        with self.lock:
            return {'settings': self.settings.copy(), 'jobs': [dict(j) for j in reversed(self.jobs[-200:])],
                    'has_session': (Path.home() / '.config/zlib/session.json').exists(),
                    'login_open': self.login_process is not None and self.login_process.poll() is None}

    def update_settings(self, payload):
        with self.lock:
            new = self.settings.copy()
            for key in new:
                if key in payload:
                    if not isinstance(payload[key], str) or len(payload[key]) > 2000:
                        raise AppError('设置内容无效。')
                    new[key] = payload[key].strip()
            if new['domain']:
                domain = urlsplit(new['domain'])
                if (domain.scheme != 'https' or not domain.hostname or domain.username or domain.password
                        or domain.port not in (None, 443) or domain.path not in ('', '/')
                        or domain.query or domain.fragment):
                    raise AppError('域名必须是完整的 HTTPS 地址，请从检测结果中选择。')
                new['domain'] = new['domain'].rstrip('/')
            if new['proxy']:
                proxy = urlsplit(new['proxy'])
                if (proxy.scheme not in ('http', 'https', 'socks5', 'socks5h') or not proxy.hostname
                        or proxy.username or proxy.password or proxy.query or proxy.fragment
                        or proxy.path not in ('', '/')):
                    raise AppError('代理格式无效，请填写不带账号密码的代理地址。')
                try:
                    proxy.port
                except ValueError:
                    raise AppError('代理端口无效。') from None
            directory = Path(new['download_dir']).expanduser()
            if not new['download_dir'] or not directory.is_absolute():
                raise AppError('请填写完整的下载文件夹路径。')
            try:
                directory.mkdir(parents=True, exist_ok=True)
                # Check actual writability without relying on Windows access bits.
                with tempfile_file(directory):
                    pass
            except OSError:
                raise AppError('无法写入下载文件夹，请选择其他位置。') from None
            new['download_dir'] = str(directory.resolve())
            save_json(self.data_dir / 'settings.json', new)
            self.settings = new
            self.catalog_revision += 1
            self.book_cache.clear()
            self.book_seeds.clear()
        return {'settings': new}

    def start_download(self, payload):
        book_id = str(payload.get('book_id', ''))
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9]+', book_id):
            raise AppError('图书编号无效，请从搜索结果重新选择。')
        with self.lock:
            for job in self.jobs:
                if job['book_id'] == book_id and job['status'] in ('queued', 'running'):
                    return dict(job)
            if any(j['book_id']==book_id and j['status']=='cancelling' for j in self.jobs):
                raise AppError('这本书正在终止下载，请稍后再试。')
            if sum(j['status'] in ('queued', 'running', 'cancelling') for j in self.jobs) >= 20:
                raise AppError('下载队列已满，请等待当前任务完成。')
            job = {'id': uuid.uuid4().hex, 'book_id': book_id, 'title': str(payload.get('title', '未命名图书'))[:300],
                   'status': 'queued', 'created_at': datetime.now(timezone.utc).isoformat(),
                   'path': '', 'error': '', 'directory': self.settings['download_dir'],
                   'phase': 'queued', 'percent': None, 'transferred_bytes': 0, 'total_bytes': None}
            self.jobs.append(job)
            self._save_jobs()
            cancelled=threading.Event()
            self.download_controls[job['id']]=cancelled
            self.download_futures[job['id']]=self.executor.submit(self._download, job, cancelled)
            return dict(job)

    def _download(self, job, cancelled):
        stage=None
        stage_owned=False
        with self.lock:
            if not cancelled.is_set():job.update(status='running', phase='preparing')
            self._save_jobs()
        def progress(sample):
            with self.lock:
                if not cancelled.is_set():job.update(sample)
        try:
            if cancelled.is_set():raise DownloadCancelled()
            try:
                directory=Path(job['directory']).resolve()
                directory.mkdir(parents=True, exist_ok=True)
                staging_root=directory/'.shiye-partials'
                with self.lock:
                    staging_root.mkdir(exist_ok=True)
                    if staging_root.is_symlink() or staging_root.is_junction() or staging_root.resolve().parent!=directory:
                        raise OSError('Invalid staging directory')
                    stage=staging_root/job['id']
                    stage.mkdir()
                    stage_owned=True
            except OSError:
                raise AppError('下载文件夹不可用，请在设置中选择其他位置。') from None
            result = run_download(self.cli, job['book_id'], stage, self.environment(), progress, timeout=900,cancelled=cancelled)
            if not isinstance(result, dict) or not result.get('path'):
                raise AppError('下载结果没有提供文件路径。', 'cli_error')
            path = Path(result['path']).resolve()
            if path.parent!=stage.resolve() or not path.is_file() or Path(result['path']).is_symlink():
                raise AppError('下载文件不存在或保存位置异常。', 'cli_error')
            with self.lock:
                if cancelled.is_set():raise DownloadCancelled()
                destination=directory/path.name
                path.replace(destination)
                path=destination
                size = path.stat().st_size
                job.update(status='completed', phase='completed', path=str(path), percent=100,
                           transferred_bytes=size, total_bytes=size,
                           file_identity=[path.stat().st_dev,path.stat().st_ino])
        except DownloadCancelled:
            with self.lock:
                job.update(status='cancelled',phase='cancelled',error='',percent=None)
        except Exception as error:
            with self.lock:
                job.update(status='failed', phase='failed', error=clean_error(str(error)) or '下载失败，请重试。')
        finally:
            if stage_owned:
                # No recursive removal: only this UUID directory's direct temporary files.
                try:
                    root=Path(job['directory']).resolve()
                    if (stage.parent.name=='.shiye-partials' and stage.parent.resolve().parent==root
                            and stage.name==job['id'] and not stage.is_symlink() and not stage.is_junction()):
                        for file in stage.iterdir():
                            if file.is_file() and not file.is_symlink() and file.resolve().parent==stage.resolve():file.unlink()
                        stage.rmdir()
                        with self.lock:
                            try:stage.parent.rmdir()
                            except OSError:pass
                except OSError:pass
            with self.lock:
                self.download_controls.pop(job['id'],None)
                self.download_futures.pop(job['id'],None)
                self._save_jobs()

    def _download_job(self, payload):
        job_id=payload.get('job_id')
        if not isinstance(job_id,str) or not re.fullmatch(r'[a-f0-9]{32}',job_id):
            raise AppError('下载记录编号无效。')
        job=next((item for item in self.jobs if item['id']==job_id),None)
        if not job:raise AppError('这条下载记录已不存在。')
        return job

    def cancel_download(self, payload):
        with self.lock:
            job=self._download_job(payload)
            if job['status'] not in ('queued','running','cancelling'):return dict(job)
            control=self.download_controls.get(job['id'])
            if control:control.set()
            future=self.download_futures.get(job['id'])
            if future and future.cancel():
                job.update(status='cancelled',phase='cancelled',error='',percent=None)
                self.download_controls.pop(job['id'],None);self.download_futures.pop(job['id'],None)
            else:job.update(status='cancelling',phase='cancelling')
            self._save_jobs()
            return dict(job)

    def remove_download(self, payload):
        with self.lock:
            job=self._download_job(payload)
            if job['status'] in ('queued','running','cancelling'):
                raise AppError('请先终止下载，再移除记录。')
            self.jobs.remove(job);self._save_jobs()
        return {'ok':True}

    def delete_download_file(self, payload):
        with self.lock:
            job=self._download_job(payload)
            if job.get('file_deleted'):return dict(job)
            if job['status']!='completed' or not job.get('path'):
                raise AppError('只有已完成的下载可以删除文件。')
            raw=Path(job['path']);directory=Path(job['directory'])
            if not raw.is_absolute() or not directory.is_absolute():raise AppError('文件位置无效。')
            path=raw.resolve();root=directory.resolve()
            if raw.is_symlink() or raw.is_junction() or path==root or not path.is_relative_to(root):
                raise AppError('文件位置异常，不能删除下载目录以外的文件。')
            if path.exists():
                if not path.is_file():raise AppError('只能删除单个已下载的文件。')
                identity=[path.stat().st_dev,path.stat().st_ino]
                if job.get('file_identity') and job['file_identity']!=identity:
                    raise AppError('文件已被替换，请从最新的下载记录中处理。')
                try:recycle_file(path)
                except Exception:raise AppError('无法移到回收站，文件可能被占用或该位置不支持回收站。') from None
                if path.exists():raise AppError('文件未能移到回收站，请稍后重试。')
                file_state='recycled'
            else:file_state='missing'
            for item in self.jobs:
                try:
                    if item.get('path') and os.path.normcase(str(Path(item['path']).resolve()))==os.path.normcase(str(path)):
                        item.update(file_deleted=True,file_state=file_state)
                except (OSError,ValueError):continue
            self._save_jobs()
            return dict(job)

    def resolve_login_domain(self):
        domain = self.settings['domain']
        if not domain:
            config = self.run_cli(['config', 'network', 'domain', '--json'], timeout=8)
            if isinstance(config, list):
                domain = next((item.get('value', '') for item in config
                               if isinstance(item, dict) and item.get('key') == 'ZLIB_DOMAIN'), '')
        if not domain:
            raise AppError('还没有配置访问域名，请先到设置中检测并保存可用地址。', 'domain_required')
        return domain

    def auth_state(self):
        with self.lock:
            return {**self._auth, 'domain': self.settings['domain']}

    def start_auth(self, payload):
        email, password = payload.get('email'), payload.get('password')
        if not isinstance(email, str) or not isinstance(password, str):
            raise AppError('请输入账号邮箱和密码。')
        try:
            validate_credentials(email, password)
        except LoginError as error:
            raise AppError(str(error)) from None
        attempt_id = payload.get('attempt_id') or uuid.uuid4().hex
        if not isinstance(attempt_id, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,64}', attempt_id):
            raise AppError('登录请求编号无效。')
        with self.lock:
            if attempt_id in self._cancelled_auth:
                raise AppError('本次登录已取消。', 'auth_cancelled')
            if self.auth_thread and self.auth_thread.is_alive():
                raise AppError('已有登录正在进行，请稍候或先取消。', 'login_busy')
            domain = self.resolve_login_domain()
            self._auth_cancel = threading.Event()
            self._auth = {'status': 'running', 'error': '', 'attempt_id': attempt_id}
            self.auth_thread = threading.Thread(target=self._authenticate,
                args=(email.strip(), password, domain, self._auth_cancel, attempt_id), daemon=True)
            self.auth_thread.start()
            return self.auth_state()

    def _authenticate(self, email, password, domain, cancelled, attempt_id):
        try:
            login(self.cli, domain, email, password, cancelled, env=self.environment())
            result = {'status': 'cancelled' if cancelled.is_set() else 'success', 'error': ''}
        except LoginError as error:
            result = {'status': 'cancelled' if cancelled.is_set() else 'failed',
                      'error': '' if cancelled.is_set() else str(error)}
        except Exception:
            result = {'status': 'failed', 'error': '登录未完成，请检查连接后重试。'}
        finally:
            password = ''
        with self.lock:
            self._auth = {**result, 'attempt_id': attempt_id}

    def cancel_auth(self, payload=None):
        with self.lock:
            attempt_id = payload.get('attempt_id') if payload else self._auth.get('attempt_id')
            if attempt_id:
                if not isinstance(attempt_id, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,64}', attempt_id):
                    raise AppError('登录请求编号无效。')
                self._cancelled_auth[attempt_id] = True
                if len(self._cancelled_auth) > 100:
                    del self._cancelled_auth[next(iter(self._cancelled_auth))]
            if self.auth_thread and self.auth_thread.is_alive() and (not attempt_id or attempt_id == self._auth.get('attempt_id')):
                self._auth_cancel.set()
                self._auth['status'] = 'cancelling'
            return self.auth_state()

    def open_login(self):
        if os.name != 'nt':
            raise AppError('请在 Windows 电脑上使用登录窗口。')
        with self.lock:
            if self.login_process and self.login_process.poll() is None:
                return {'message': '登录窗口已打开，请切换到该窗口。'}
            domain = self.resolve_login_domain()
            python = Path(sys.executable)
            if python.with_name('pythonw.exe').exists():
                python = python.with_name('pythonw.exe')
            args = [str(python), str(BASE / 'login_gui.py'), self.cli[0], domain]
            self.login_process = subprocess.Popen(args, cwd=BASE, env=self.environment(),
                                                   creationflags=subprocess.CREATE_NO_WINDOW)
        return {'message': '已打开登录窗口，登录成功后会自动返回并刷新账号。'}


def tempfile_file(directory):
    import tempfile
    return tempfile.TemporaryFile(dir=directory)


class LocalHTTPServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR permits overlapping listeners from different copies.
    # Exclusivity lets the launcher safely move to the next available port.
    allow_reuse_address=os.name!='nt'
    allow_reuse_port=False

    def server_bind(self):
        if os.name=='nt':
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()


def create_server(app, port=8877):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log search queries, account details or request bodies.

        def send_data(self, status, value, mime='application/json; charset=utf-8', cache='no-store', etag=None):
            data = json.dumps(value, ensure_ascii=False).encode('utf-8') if isinstance(value, (dict, list)) else value
            self.send_response(status)
            self.send_header('Content-Type', mime)
            if status != 304:
                self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', cache)
            if etag:
                self.send_header('ETag', etag)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://*.cdn-zlib.sk https://cdn-zlib.sk https://*.zlibcdn2.com https://zlibcdn2.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def send_file(self, file, mime, cover=False):
            data=file.read_bytes()
            etag='"'+hashlib.sha256(data).hexdigest()[:24]+'"'
            cache='private, max-age=86400' if cover else 'private, no-cache'
            if self.headers.get('If-None-Match') == etag:
                self.send_data(304,b'',mime,cache,etag)
            else:
                self.send_data(200,data,mime,cache,etag)

        def permitted(self, mutation=False):
            host = self.headers.get('Host', '')
            hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            origin = self.headers.get('Origin')
            if host not in hosts or (origin and origin not in {f'http://{h}' for h in hosts}):
                self.send_data(403, {'error': '仅允许本机页面访问。'})
                return False
            if mutation and not secrets.compare_digest(self.headers.get('X-Local-Token', ''), app.token):
                self.send_data(403, {'error': '页面已过期，请刷新后重试。'})
                return False
            return True

        def do_GET(self):
            if not self.permitted():
                return
            path = urlsplit(self.path).path
            if path == '/api/ping':
                self.send_data(200, {'app': 'local-book-web', 'name': APP_NAME, 'version': VERSION})
            elif path == '/api/state':
                self.send_data(200, app.state())
            elif path == '/api/auth/state':
                self.send_data(200, app.auth_state())
            elif path == '/api/featured':
                self.send_data(200, app.featured())
            elif path == '/':
                page = (BASE / 'static/index.html').read_text(encoding='utf-8').replace('__TOKEN__', app.token)
                self.send_data(200, page.encode('utf-8'), 'text/html; charset=utf-8')
            elif path in ('/static/app.js', '/static/app.css', '/static/theme.js', '/static/book-cache.js'):
                file = BASE / path.lstrip('/')
                mime = 'text/javascript; charset=utf-8' if file.suffix == '.js' else 'text/css; charset=utf-8'
                self.send_file(file, mime)
            elif local_cover(path):
                file = BASE / path.lstrip('/')
                self.send_file(file, mimetypes.guess_type(file.name)[0] or 'image/jpeg', cover=True)
            elif re.fullmatch(r'/static/login/[a-zA-Z0-9_.-]+\.(js|css)', path):
                file = (BASE / path.lstrip('/')).resolve()
                if not file.is_relative_to((BASE / 'static/login').resolve()) or not file.is_file():
                    self.send_data(404, {'error': '组件文件不存在。'})
                    return
                mime = 'text/javascript; charset=utf-8' if file.suffix == '.js' else 'text/css; charset=utf-8'
                self.send_file(file, mime)
            else:
                self.send_data(404, {'error': '页面不存在。'})

        def do_POST(self):
            if not self.permitted(mutation=True):
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16384 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise AppError('请求格式无效。')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise AppError('请求内容无效。')
                path = urlsplit(self.path).path
                if path == '/api/search':
                    result = app.search(payload)
                elif path == '/api/book/details':
                    result = app.book_details(payload)
                elif path == '/api/auth/start':
                    result = app.start_auth(payload)
                elif path == '/api/auth/cancel':
                    result = app.cancel_auth(payload)
                elif path == '/api/settings':
                    result = app.update_settings(payload)
                elif path == '/api/download':
                    result = app.start_download(payload)
                elif path == '/api/download/cancel':
                    result = app.cancel_download(payload)
                elif path == '/api/download/remove':
                    result = app.remove_download(payload)
                elif path == '/api/download/delete-file':
                    result = app.delete_download_file(payload)
                elif path == '/api/doctor':
                    args = ['doctor', '--json']
                    if app.settings['proxy']:
                        args += ['--proxy', app.settings['proxy']]
                    result = {'domains': app.run_cli(args, timeout=100)}
                elif path == '/api/profile':
                    profile = app.run_cli(['profile', '--json'], timeout=40)
                    result = {k: profile[k] for k in ('name', 'quota_known', 'daily_remaining', 'daily_allowed') if k in profile}
                elif path == '/api/login':
                    result = app.open_login()
                elif path == '/api/open-folder':
                    if os.name == 'nt':
                        os.startfile(app.settings['download_dir'])
                    result = {'ok': True}
                elif path == '/api/shutdown':
                    result = {'ok': True}
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else:
                    self.send_data(404, {'error': '接口不存在。'})
                    return
                self.send_data(200, result)
            except AppError as error:
                self.send_data(400, {'error': str(error), 'code': error.code})
            except (ValueError, TypeError, OverflowError):
                self.send_data(400, {'error': '输入内容格式无效。'})
            except OSError:
                self.send_data(500, {'error': '操作失败，请检查软件文件和目录权限。'})
            except Exception:
                self.send_data(500, {'error': '操作未完成，请刷新页面后重试。'})

    return LocalHTTPServer(('127.0.0.1', port), Handler)


class InstanceLock:
    """Hold an OS lock for the lifetime of the server, including shutdown."""
    def __init__(self, path):
        self.path = path
        self.file = None

    def __enter__(self):
        self.file = self.path.open('a+b')
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            return False
        return True

    def __exit__(self, *args):
        if self.file:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()


def _serve():
    app = App()
    httpd = None
    for port in range(8877, 8897):
        try:
            httpd = create_server(app, port)
            break
        except OSError:
            continue
    if httpd is None:
        raise RuntimeError('没有可用的本机端口（8877–8896）。')
    save_json(app.data_dir / 'server.json', {'url': f'http://127.0.0.1:{httpd.server_port}', 'pid': os.getpid()})
    try:
        httpd.serve_forever()
    finally:
        app.cancel_auth()
        if app.auth_thread:
            app.auth_thread.join(timeout=3)
        httpd.server_close()
        app.executor.shutdown(wait=True)
        runtime = app.data_dir / 'server.json'
        if load_json(runtime, {}).get('pid') == os.getpid():
            runtime.unlink(missing_ok=True)


def main():
    data_dir = DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    with InstanceLock(data_dir / 'service.lock') as acquired:
        if acquired:
            _serve()


if __name__ == '__main__':
    main()
