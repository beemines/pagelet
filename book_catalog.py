"""Public book metadata and read-only CLI MCP adapter."""
from html.parser import HTMLParser
import json
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
from urllib.parse import urlsplit, unquote

BASE=Path(__file__).resolve().parent


class CatalogError(Exception):
    pass


class DescriptionText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]
        self.skipped=0

    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):
            self.skipped+=1
        elif not self.skipped:
            if tag in ('p','div','section','h1','h2','h3','h4'):
                self.parts.append('\n\n')
            elif tag=='br':
                self.parts.append('\n')
            elif tag=='li':
                self.parts.append('\n• ')

    def handle_endtag(self,tag):
        if tag in ('script','style'):
            self.skipped=max(0,self.skipped-1)
        elif not self.skipped and tag in ('p','div','section','h1','h2','h3','h4','ul','ol'):
            self.parts.append('\n\n')

    def handle_data(self,data):
        if not self.skipped:
            self.parts.append(data)


def description_text(value):
    parser=DescriptionText()
    parser.feed(str(value or '')[:80000])
    text=''.join(parser.parts)
    text=''.join(c for c in text if c.isprintable() or c in '\n\t')
    text='\n'.join(re.sub(r'[\t ]+',' ',line).strip() for line in text.splitlines())
    return re.sub(r'\n{3,}','\n\n',text).strip()[:50000]


def safe_cover(value):
    if not isinstance(value,str):
        return ''
    try:
        url=urlsplit(value)
        host=(url.hostname or '').lower()
        allowed=any(host==base or host.endswith('.'+base) for base in ('cdn-zlib.sk','zlibcdn2.com'))
        if url.scheme=='https' and allowed and not url.username and not url.password and url.port in (None,443):
            return value
    except ValueError:
        pass
    return ''


def safe_source(value,domain):
    try:
        source,base=urlsplit(value or ''),urlsplit(domain or '')
        path=source.path
        if (base.scheme=='https' and base.hostname and not base.username and not base.password
                and base.port in (None,443) and path.startswith('/book/')
                and '\\' not in unquote(path) and not any(p in ('.','..') for p in unquote(path).split('/'))):
            return base.scheme+'://'+base.netloc+path
    except (ValueError,TypeError):
        pass
    return ''


def public_book(book,domain='',*,description_is_text=False):
    fields=('id','name','publisher','year','language','extension','size','rating','quality','isbn','isbn_10','isbn_13','edition','pages','categories')
    result={key:str(book[key])[:4000] for key in fields if isinstance(book.get(key),(str,int,float))}
    authors=book.get('authors') or []
    if isinstance(authors,str):
        authors=[authors]
    result['authors']=[value[:400] for value in authors if isinstance(value,str)][:30] if isinstance(authors,list) else []
    result['cover']=safe_cover(book.get('cover',''))
    result['url']=safe_source(book.get('url',''),domain)
    # Detail and search metadata are already text when merged from the cache.
    result['description']=str(book.get('description') or '')[:50000] if description_is_text else description_text(book.get('description',''))
    return result


def fetch_details(cli,env,book_id,timeout=45):
    if not isinstance(book_id,str) or not re.fullmatch(r'[0-9]+:[A-Za-z0-9]+',book_id):
        raise CatalogError('图书编号无效，请重新搜索后选择。')
    process=None
    messages=queue.Queue(maxsize=30)
    deadline=time.monotonic()+timeout
    try:
        process=subprocess.Popen(list(cli)+['mcp','--read-only'],cwd=BASE,env=env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

        def reader():
            try:
                for line in iter(lambda:process.stdout.readline(2_000_000),''):
                    try:
                        message=json.loads(line)
                        if isinstance(message,dict):
                            messages.put_nowait(message)
                    except (ValueError,queue.Full):
                        continue
            finally:
                try: messages.put_nowait(None)
                except queue.Full: pass

        worker=threading.Thread(target=reader,daemon=True)
        worker.start()

        def send(message):
            process.stdin.write(json.dumps(message,ensure_ascii=False)+'\n')
            process.stdin.flush()

        def receive(request_id):
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:
                    raise CatalogError('读取图书详情超时，请稍后重试。')
                try: message=messages.get(timeout=remaining)
                except queue.Empty:
                    raise CatalogError('读取图书详情超时，请稍后重试。') from None
                if message is None:
                    raise CatalogError('图书详情接口已断开，请重试。')
                if message.get('id')==request_id:
                    if 'error' in message:
                        raise CatalogError('无法读取图书详情，请检查登录和连接设置。')
                    return message.get('result',{})

        send({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'pagelet-local','version':'1'}}})
        receive(1)
        send({'jsonrpc':'2.0','method':'notifications/initialized'})
        send({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'get_book','arguments':{'id':book_id}}})
        result=receive(2)
        if result.get('isError'):
            text=' '.join(str(item.get('text','')) for item in result.get('content',[]) if isinstance(item,dict)).lower()
            if any(word in text for word in ('not logged in','session expired','login required')):
                raise CatalogError('登录已过期，请重新登录后查看详情。')
            raise CatalogError('无法读取这本书的详情，可以打开原站进一步确认。')
        details=result.get('structuredContent')
        if not isinstance(details,dict):
            for item in result.get('content',[]):
                if isinstance(item,dict) and item.get('type')=='text':
                    try: details=json.loads(item.get('text',''))
                    except ValueError: continue
                    if isinstance(details,dict): break
        if not isinstance(details,dict):
            raise CatalogError('图书详情格式异常，请稍后重试。')
        return public_book(details)
    except CatalogError:
        raise
    except (OSError,ValueError,TypeError):
        raise CatalogError('无法启动图书详情接口，请确认软件文件完整。') from None
    finally:
        if process:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
            if 'worker' in locals(): worker.join(timeout=1)
            if process.stdin: process.stdin.close()
            if process.stdout: process.stdout.close()
